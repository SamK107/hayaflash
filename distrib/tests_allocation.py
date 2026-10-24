"""P5 : import, allocation, reprise, plafonds (spec §5.3, §15.6, tests 8 et 9)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from distrib.models import (
    AllocationMovement,
    DistribPayment,
    DistribSettlement,
    ImportedProduct,
    ResellerInvite,
    ResellerPayout,
    DistribStatement,
)
from distrib.services import allocation, ceilings
from distrib.services.catalog import available_qty
from distrib.tests_catalog import make_wholesale, photo
from distrib.tests_models import make_distributor, make_seller
from distrib.services import catalog
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order
from orders.services.create_order import create_order
from products.models import FlashSaleProduct, Product, StockMovement
from products.services.crud import attach_product_to_sale


def accepted_invite(distributor, phone="+22370000001", name="Awa"):
    seller = make_seller(phone, name)
    invite = ResellerInvite.objects.create(
        distributor=distributor, display_name=name, phone=phone,
        status=ResellerInvite.Status.ACCEPTED, seller=seller,
    )
    return invite


class Base(TestCase):
    def setUp(self):
        self.d = make_distributor()
        self.wp = make_wholesale(self.d, stock_total=20)
        self.invite = accepted_invite(self.d)

    def do_import(self, price=4500, quantity=0, invite=None, wp=None):
        return allocation.import_product(
            invite=invite or self.invite, wholesale_product=wp or self.wp,
            retail_price=price, actor=self.d.user, quantity=quantity,
        )


class ImportTests(Base):
    def test_import_creates_a_normal_product_in_the_shop(self):
        catalog.add_wholesale_image(wholesale_product=self.wp, image_file=photo("a.jpg"))
        catalog.add_wholesale_image(wholesale_product=self.wp, image_file=photo("b.jpg", color=(0, 0, 255)))
        imported = self.do_import(price=4800)
        product = imported.product
        self.assertEqual(product.owner, self.invite.seller)
        self.assertEqual((product.name, product.price, product.stock_available), ("Robe wax", Decimal("4800"), 0))
        self.assertTrue(product.is_active)
        self.assertEqual(imported.allocated_qty, 0)
        self.assertEqual(product.distrib_import, imported)
        # Images COPIEES : fichiers distincts de ceux du catalogue.
        own = set(product.media.values_list("file", flat=True))
        src = set(self.wp.images.values_list("image", flat=True))
        self.assertEqual(len(own), 2)
        self.assertFalse(own & src)
        self.assertEqual([m.order for m in product.media.all()], [0, 1])

    def test_import_with_initial_quantity_uses_the_initial_stock_movement(self):
        imported = self.do_import(quantity=5)
        product = imported.product
        self.assertEqual((product.stock_initial, product.stock_available, imported.allocated_qty), (5, 5, 5))
        self.assertEqual(product.stock_movements.get().movement_type, StockMovement.MovementType.INITIAL)
        self.assertEqual(AllocationMovement.objects.get().quantity_change, 5)
        self.assertEqual(available_qty(self.wp), 15)

    def test_price_below_minimum_is_refused(self):
        for price in (4499, 1, 0, "abc", "4500.5", -5):
            with self.assertRaises(ValidationError, msg=str(price)):
                self.do_import(price=price)
        self.assertEqual(Product.objects.count(), 0)
        self.assertEqual(ImportedProduct.objects.count(), 0)

    def test_minimum_price_exactly_is_accepted(self):
        self.assertEqual(self.do_import(price=4500).product.price, Decimal("4500"))

    def test_only_once_per_reseller(self):
        self.do_import()
        with self.assertRaisesMessage(ValidationError, "déjà"):
            self.do_import()
        self.assertEqual(Product.objects.count(), 1)

    def test_two_resellers_can_import_the_same_product(self):
        self.do_import()
        other = accepted_invite(self.d, "+22370000002", "Fanta")
        self.do_import(invite=other)
        self.assertEqual(ImportedProduct.objects.count(), 2)

    def test_revoked_declined_or_pending_reseller_cannot_import(self):
        for status in ("revoked", "declined", "invited"):
            ResellerInvite.objects.filter(pk=self.invite.pk).update(status=status)
            with self.assertRaises(ValidationError, msg=status):
                self.do_import()
        self.assertEqual(Product.objects.count(), 0)

    def test_suspended_or_inactive_distributor_blocks_import(self):
        self.d.is_suspended = True
        self.d.save()
        with self.assertRaisesMessage(ValidationError, "suspendu"):
            self.do_import()
        self.d.is_suspended = False
        self.d.is_active = False
        self.d.save()
        with self.assertRaises(ValidationError):
            self.do_import()

    def test_hidden_product_and_foreign_product_are_refused(self):
        self.wp.is_active = False
        self.wp.save()
        with self.assertRaises(ValidationError):
            self.do_import()
        other = make_distributor("+22371000002", "Autre gros")
        foreign = make_wholesale(other, name="Voisin")
        with self.assertRaisesMessage(ValidationError, "n'appartient pas"):
            self.do_import(wp=foreign)

    def test_missing_image_file_does_not_block_the_import(self):
        img = catalog.add_wholesale_image(wholesale_product=self.wp, image_file=photo())
        img.image.storage.delete(img.image.name)
        imported = self.do_import()
        self.assertEqual(imported.product.media.count(), 0)

    def test_catalog_product_is_untouched(self):
        before = (self.wp.stock_total, self.wp.wholesale_price)
        self.do_import(quantity=3)
        self.wp.refresh_from_db()
        self.assertEqual((self.wp.stock_total, self.wp.wholesale_price), before)


class AllocateTests(Base):
    def test_allocate_adds_stock_and_journals(self):
        imported = self.do_import()
        allocation.allocate(imported=imported, quantity=8, actor=self.d.user)
        imported.refresh_from_db()
        product = imported.product
        product.refresh_from_db()
        self.assertEqual((imported.allocated_qty, product.stock_available, product.stock_initial), (8, 8, 8))
        move = StockMovement.objects.get(product=product, movement_type="correction")
        self.assertEqual((move.quantity_change, move.movement_type), (8, StockMovement.MovementType.CORRECTION))
        log = AllocationMovement.objects.get()
        self.assertEqual((log.quantity_change, log.created_by, log.imported_product), (8, self.d.user, imported))
        self.assertEqual(available_qty(self.wp), 12)

    def test_allocation_beyond_available_is_refused(self):
        imported = self.do_import()
        with self.assertRaisesMessage(ValidationError, "20 unité"):
            allocation.allocate(imported=imported, quantity=21, actor=self.d.user)
        imported.refresh_from_db()
        self.assertEqual(imported.allocated_qty, 0)
        self.assertEqual(AllocationMovement.objects.count(), 0)
        self.assertFalse(StockMovement.objects.filter(product=imported.product, movement_type="correction").exists())

    def test_exactly_the_available_quantity_is_accepted_then_nothing_left(self):
        imported = self.do_import()
        allocation.allocate(imported=imported, quantity=20, actor=self.d.user)
        self.assertEqual(available_qty(self.wp), 0)
        with self.assertRaises(ValidationError):
            allocation.allocate(imported=imported, quantity=1, actor=self.d.user)

    def test_availability_is_shared_between_resellers(self):
        a = self.do_import()
        b = self.do_import(invite=accepted_invite(self.d, "+22370000002", "Fanta"))
        allocation.allocate(imported=a, quantity=15, actor=self.d.user)
        with self.assertRaisesMessage(ValidationError, "5 unité"):
            allocation.allocate(imported=b, quantity=6, actor=self.d.user)
        allocation.allocate(imported=b, quantity=5, actor=self.d.user)
        self.assertEqual(available_qty(self.wp), 0)

    def test_quantity_must_be_a_positive_whole_number(self):
        imported = self.do_import()
        for bad in (0, -3, "abc", "", "2.5", None):
            with self.assertRaises(ValidationError, msg=str(bad)):
                allocation.allocate(imported=imported, quantity=bad, actor=self.d.user)

    def test_blocked_for_revoked_reseller_and_suspended_distributor(self):
        imported = self.do_import()
        ResellerInvite.objects.filter(pk=self.invite.pk).update(status="revoked")
        with self.assertRaises(ValidationError):
            allocation.allocate(imported=imported, quantity=1, actor=self.d.user)
        ResellerInvite.objects.filter(pk=self.invite.pk).update(status="accepted")
        self.d.is_suspended = True
        self.d.save()
        with self.assertRaisesMessage(ValidationError, "suspendu"):
            allocation.allocate(imported=imported, quantity=1, actor=self.d.user)

    def test_stale_stock_in_memory_is_not_overwritten(self):
        """Le defaut de `adjust_stock` (valeur absolue lue en memoire) ne doit pas se reproduire."""
        imported = self.do_import(quantity=10)
        stale = Product.objects.get(pk=imported.product_id)  # voit 10
        Product.objects.filter(pk=stale.pk).update(stock_available=7)  # 3 commandes passent entre-temps
        allocation.allocate(imported=imported, quantity=5, actor=self.d.user)
        self.assertEqual(Product.objects.get(pk=stale.pk).stock_available, 12)  # 7 + 5, pas 10 + 5

    def test_allocated_stock_is_orderable_through_the_unchanged_order_circuit(self):
        imported = self.do_import()
        allocation.allocate(imported=imported, quantity=3, actor=self.d.user)
        now = timezone.now()
        sale = FlashSale.objects.create(
            owner=self.invite.seller, title="Live", start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=1), status=FlashSaleStatus.LIVE,
        )
        attach_product_to_sale(flash_sale=sale, product=imported.product)
        order = create_order(
            {
                "flash_sale_id": sale.pk, "customer_name": "Cliente", "customer_phone": "+22376000000",
                "client_request_id": "req-1", "items": [{"product_id": imported.product_id, "quantity": 2}],
                "delivery": {"address_text": "Hamdallaye ACI", "geo_method": "manual"},
            }
        )
        self.assertEqual(Order.service_objects.get(pk=order.pk).items.get().quantity, 2)
        imported.product.refresh_from_db()
        self.assertEqual(imported.product.stock_available, 1)
        # Reprise : seulement ce qui n'est pas parti.
        with self.assertRaisesMessage(ValidationError, "1 unité"):
            allocation.take_back(imported=imported, quantity=2, actor=self.d.user)
        allocation.take_back(imported=imported, quantity=1, actor=self.d.user)
        imported.refresh_from_db()
        imported.product.refresh_from_db()
        self.assertEqual((imported.allocated_qty, imported.product.stock_available), (2, 0))
        self.assertEqual(allocation.sold_qty(imported), 2)


class TakeBackTests(Base):
    def setUp(self):
        super().setUp()
        self.imported = self.do_import()
        allocation.allocate(imported=self.imported, quantity=10, actor=self.d.user)

    def test_take_back_removes_unsold_units_and_journals(self):
        allocation.take_back(imported=self.imported, quantity=4, actor=self.d.user, reason="Retour entrepôt")
        self.imported.refresh_from_db()
        product = Product.objects.get(pk=self.imported.product_id)
        self.assertEqual((self.imported.allocated_qty, product.stock_available, product.stock_initial), (6, 6, 6))
        self.assertEqual(list(AllocationMovement.objects.values_list("quantity_change", flat=True)), [-4, 10])
        last = StockMovement.objects.filter(product=product, quantity_change=-4).get()
        self.assertEqual((last.quantity_change, last.movement_type, last.notes), (-4, "correction", "Retour entrepôt"))
        self.assertEqual(available_qty(self.wp), 14)

    def test_limited_to_the_unsold_stock(self):
        Product.objects.filter(pk=self.imported.product_id).update(stock_available=3)  # 7 parties en commandes
        with self.assertRaisesMessage(ValidationError, "3 unité"):
            allocation.take_back(imported=self.imported, quantity=4, actor=self.d.user)
        allocation.take_back(imported=self.imported, quantity=3, actor=self.d.user)
        self.imported.refresh_from_db()
        self.assertEqual(self.imported.allocated_qty, 7)  # les 7 vendues restent comptees
        self.assertEqual(Product.objects.get(pk=self.imported.product_id).stock_available, 0)

    def test_stock_never_goes_negative(self):
        with self.assertRaises(ValidationError):
            allocation.take_back(imported=self.imported, quantity=11, actor=self.d.user)
        self.assertEqual(Product.objects.get(pk=self.imported.product_id).stock_available, 10)

    def test_always_possible_even_when_everything_else_is_blocked(self):
        self.d.is_suspended = True
        self.d.save()
        ResellerInvite.objects.filter(pk=self.invite.pk).update(status="revoked")
        allocation.take_back(imported=self.imported, quantity=2, actor=self.d.user)
        self.imported.refresh_from_db()
        self.assertEqual(self.imported.allocated_qty, 8)

    def test_below_minimum_alert_selector(self):
        Product.objects.filter(pk=self.imported.product_id).update(price=Decimal("4000"))
        self.assertEqual(list(allocation.imports_below_minimum(self.d)), [self.imported])
        Product.objects.filter(pk=self.imported.product_id).update(price=Decimal("4500"))
        self.assertEqual(list(allocation.imports_below_minimum(self.d)), [])


class CeilingTests(Base):
    """§15.6 : alerte a 80 %, blocage au-dela de 100 %, deblocage automatique."""

    def setUp(self):
        super().setUp()
        self.imported = self.do_import()
        self.sale_n = 0

    def line(self, margin, *, invite=None, payout=None, commission=0, billable=False):
        invite = invite or self.invite
        self.sale_n += 1
        now = timezone.now()
        sale = FlashSale.objects.create(
            owner=invite.seller, title=f"v{self.sale_n}", start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=1), status=FlashSaleStatus.LIVE,
        )
        product = Product.objects.create(owner=invite.seller, name="s", price=5000, stock_available=9, stock_initial=9)
        FlashSaleProduct.objects.create(flash_sale=sale, product=product)
        order = create_order(
            {
                "flash_sale_id": sale.pk, "customer_name": "C", "customer_phone": "+22376000000",
                "client_request_id": f"c-{self.sale_n}", "items": [{"product_id": product.pk, "quantity": 1}],
                "delivery": {"address_text": "Hamdallaye ACI, Bamako", "geo_method": "manual"},
            }
        )
        item = order.items.get()
        wp = make_wholesale(self.d, name=f"c{self.sale_n}")
        imp = ImportedProduct.objects.create(wholesale_product=wp, invite=invite, product=product)
        return DistribSettlement.objects.create(
            distributor=self.d, invite=invite, order=order, order_item=item, imported_product=imp,
            quantity=1, sale_amount=5000, wholesale_amount=3000, reseller_margin=margin,
            commission_amount=commission, commission_billable=billable,
            status=DistribSettlement.Status.PAID_CONFIRMED, payout=payout,
        )

    def test_levels(self):
        self.assertEqual(ceilings.level(Decimal("7999"), Decimal("10000")), "ok")
        self.assertEqual(ceilings.level(Decimal("8000"), Decimal("10000")), "warning")
        self.assertEqual(ceilings.level(Decimal("10000"), Decimal("10000")), "warning")
        self.assertEqual(ceilings.level(Decimal("10001"), Decimal("10000")), "blocked")

    def test_reseller_margin_ceiling_blocks_only_that_reseller(self):
        other_invite = accepted_invite(self.d, "+22370000002", "Fanta")
        other_imported = self.do_import(invite=other_invite)
        self.line(8000)
        self.assertEqual(ceilings.reseller_level(self.invite), "warning")
        allocation.allocate(imported=self.imported, quantity=1, actor=self.d.user)  # 80 % : encore permis
        self.line(2001)  # 10 001 > 10 000
        self.assertEqual(ceilings.reseller_level(self.invite), "blocked")
        with self.assertRaisesMessage(ValidationError, "Règle les marges dues pour débloquer"):
            allocation.allocate(imported=self.imported, quantity=1, actor=self.d.user)
        # Un autre revendeur du meme grossiste n'est pas touche.
        allocation.allocate(imported=other_imported, quantity=1, actor=self.d.user)

    def test_exactly_at_the_ceiling_is_not_blocked(self):
        self.line(10000)
        allocation.allocate(imported=self.imported, quantity=1, actor=self.d.user)

    def test_import_is_blocked_too_but_take_back_is_not(self):
        allocation.allocate(imported=self.imported, quantity=2, actor=self.d.user)
        self.line(10001)
        other_wp = make_wholesale(self.d, name="Autre produit")
        with self.assertRaises(ValidationError):
            self.do_import(wp=other_wp)
        allocation.take_back(imported=self.imported, quantity=1, actor=self.d.user)

    def test_unblocks_automatically_once_paid(self):
        line = self.line(10001)
        with self.assertRaises(ValidationError):
            allocation.allocate(imported=self.imported, quantity=1, actor=self.d.user)
        statement = DistribStatement.objects.create(
            distributor=self.d, invite=self.invite, period_start="2026-10-12", period_end="2026-10-18",
            amount=10001, line_count=1,
        )
        payout = ResellerPayout.objects.create(
            distributor=self.d, invite=self.invite, statement=statement, amount=10001, om_reference="OM1",
            status=ResellerPayout.Status.DECLARED,
        )
        DistribSettlement.objects.filter(pk=line.pk).update(payout=payout)
        allocation.allocate(imported=self.imported, quantity=1, actor=self.d.user)

    def test_a_contested_payout_stays_due(self):
        line = self.line(10001)
        statement = DistribStatement.objects.create(
            distributor=self.d, invite=self.invite, period_start="2026-10-12", period_end="2026-10-18",
            amount=10001, line_count=1,
        )
        payout = ResellerPayout.objects.create(
            distributor=self.d, invite=self.invite, statement=statement, amount=10001, om_reference="OM1",
            status=ResellerPayout.Status.CONTESTED,
        )
        DistribSettlement.objects.filter(pk=line.pk).update(payout=payout)
        with self.assertRaises(ValidationError):
            allocation.allocate(imported=self.imported, quantity=1, actor=self.d.user)

    def test_only_confirmed_lines_count(self):
        line = self.line(50000)
        DistribSettlement.objects.filter(pk=line.pk).update(status="ordered")
        allocation.allocate(imported=self.imported, quantity=1, actor=self.d.user)
        DistribSettlement.objects.filter(pk=line.pk).update(status="cancelled")
        allocation.allocate(imported=self.imported, quantity=1, actor=self.d.user)

    def test_commission_ceiling_blocks_the_whole_distributor(self):
        other_invite = accepted_invite(self.d, "+22370000002", "Fanta")
        other_imported = self.do_import(invite=other_invite)
        self.line(100, commission=1500, billable=True)
        for _ in range(6):
            self.line(100, commission=1500, billable=True)  # 10 500 > 10 000
        self.assertEqual(ceilings.commission_outstanding(self.d), Decimal("10500"))
        for imported in (self.imported, other_imported):
            with self.assertRaisesMessage(ValidationError, "commission"):
                allocation.allocate(imported=imported, quantity=1, actor=self.d.user)
        # Un reglement enregistre par l'equipe debloque.
        DistribPayment.objects.create(distributor=self.d, amount=1000, reference="OM-PAY")
        allocation.allocate(imported=self.imported, quantity=1, actor=self.d.user)

    def test_non_billable_commission_is_not_counted(self):
        for _ in range(8):
            self.line(100, commission=1500, billable=False)  # periode d'essai
        self.assertEqual(ceilings.commission_outstanding(self.d), Decimal("0"))
        allocation.allocate(imported=self.imported, quantity=1, actor=self.d.user)

    def test_running_orders_are_never_blocked(self):
        """Le plafond ne bloque que l'allocation : une commande sur du stock deja alloue passe."""
        allocation.allocate(imported=self.imported, quantity=3, actor=self.d.user)
        self.line(20000)
        now = timezone.now()
        sale = FlashSale.objects.create(
            owner=self.invite.seller, title="Live", start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=1), status=FlashSaleStatus.LIVE,
        )
        attach_product_to_sale(flash_sale=sale, product=self.imported.product)
        order = create_order(
            {
                "flash_sale_id": sale.pk, "customer_name": "C", "customer_phone": "+22376000001",
                "client_request_id": "run-1", "items": [{"product_id": self.imported.product_id, "quantity": 1}],
                "delivery": {"address_text": "Hamdallaye ACI, Bamako", "geo_method": "manual"},
            }
        )
        self.assertIsNotNone(order.pk)


@override_settings(DISTRIB_ENABLED=True)
class StockViewTests(Base):
    def setUp(self):
        super().setUp()
        self.imported = self.do_import()
        self.client.force_login(self.d.user)

    def test_allocate_and_take_back_through_the_views(self):
        resp = self.client.post(f"/distrib/stock/{self.imported.pk}/allouer/", {"quantity": "6"})
        self.assertRedirects(resp, "/distrib/stock/")
        self.imported.refresh_from_db()
        self.assertEqual(self.imported.allocated_qty, 6)
        self.client.post(f"/distrib/stock/{self.imported.pk}/reprendre/", {"quantity": "2"})
        self.imported.refresh_from_db()
        self.assertEqual(self.imported.allocated_qty, 4)

    def test_errors_are_shown_and_nothing_changes(self):
        resp = self.client.post(f"/distrib/stock/{self.imported.pk}/allouer/", {"quantity": "99"}, follow=True)
        self.assertContains(resp, "Il ne reste que 20")
        self.imported.refresh_from_db()
        self.assertEqual(self.imported.allocated_qty, 0)

    def test_stock_page_shows_the_four_figures(self):
        allocation.allocate(imported=self.imported, quantity=5, actor=self.d.user)
        resp = self.client.get("/distrib/stock/")
        self.assertContains(resp, "Robe wax")
        self.assertContains(resp, "Alloué 5")

    def test_below_minimum_warning_is_displayed(self):
        Product.objects.filter(pk=self.imported.product_id).update(price=Decimal("1000"))
        self.assertContains(self.client.get("/distrib/stock/"), "prix sous le minimum")

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(f"/distrib/stock/{self.imported.pk}/allouer/").status_code, 405)

    def test_cloisonnement_between_distributors(self):
        other = make_distributor("+22371000002", "Autre gros")
        self.client.force_login(other.user)
        self.assertEqual(
            self.client.post(f"/distrib/stock/{self.imported.pk}/allouer/", {"quantity": "1"}).status_code, 404
        )
        self.assertEqual(
            self.client.post(f"/distrib/stock/{self.imported.pk}/reprendre/", {"quantity": "1"}).status_code, 404
        )
        self.assertNotContains(self.client.get("/distrib/stock/"), "Robe wax")

    def test_reseller_cannot_use_distributor_pages(self):
        self.client.force_login(self.invite.seller.user)
        self.assertEqual(self.client.get("/distrib/stock/").status_code, 403)
        self.assertEqual(
            self.client.post(f"/distrib/stock/{self.imported.pk}/allouer/", {"quantity": "1"}).status_code, 403
        )


@override_settings(DISTRIB_ENABLED=True)
class ResellerImportViewTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.invite.seller.user)
        self.url = f"/distrib/mes-grossistes/{self.invite.pk}/"

    def test_catalog_lists_active_products_with_prices(self):
        make_wholesale(self.d, name="Masque", is_active=False)
        resp = self.client.get(self.url)
        self.assertContains(resp, "Robe wax")
        self.assertContains(resp, "4500")
        self.assertNotContains(resp, "Masque")

    def test_import_through_the_view(self):
        resp = self.client.post(f"{self.url}importer/{self.wp.pk}/", {"retail_price": "5000"})
        self.assertRedirects(resp, self.url)
        imported = ImportedProduct.objects.get()
        self.assertEqual((imported.product.price, imported.product.owner), (Decimal("5000"), self.invite.seller))
        self.assertContains(self.client.get(self.url), "En attente d'allocation")

    def test_price_below_minimum_is_refused_with_a_message(self):
        resp = self.client.post(f"{self.url}importer/{self.wp.pk}/", {"retail_price": "4000"}, follow=True)
        self.assertEqual(ImportedProduct.objects.count(), 0)
        self.assertEqual(resp.status_code, 200)

    def test_only_my_accepted_distributor_is_reachable(self):
        stranger = make_seller("+22370000002", "Fanta")
        self.client.force_login(stranger.user)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(f"{self.url}importer/{self.wp.pk}/", {"retail_price": "5000"}).status_code, 404)
        self.assertEqual(ImportedProduct.objects.count(), 0)

    def test_revoked_reseller_loses_the_catalog(self):
        ResellerInvite.objects.filter(pk=self.invite.pk).update(status="revoked")
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_cannot_import_another_distributors_product_through_my_invite(self):
        other = make_distributor("+22371000002", "Autre gros")
        foreign = make_wholesale(other, name="Voisin")
        resp = self.client.post(f"{self.url}importer/{foreign.pk}/", {"retail_price": "9999"})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(ImportedProduct.objects.count(), 0)

    def test_get_is_not_allowed_on_import(self):
        self.assertEqual(self.client.get(f"{self.url}importer/{self.wp.pk}/").status_code, 405)

    def test_mes_grossistes_links_to_the_catalog(self):
        self.assertContains(self.client.get("/distrib/mes-grossistes/"), self.url)
