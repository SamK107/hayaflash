"""P6 : suivi des commandes, presomption, « Pas livre », corrections (spec §5.4, §15.1, §15.2).

Couvre SPEC §10 tests 2 a 6 et §15.11 tests 13, 14 et 15.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import AuditLog
from distrib.models import (
    DistribCorrection,
    DistribSettlement,
    DistribStatement,
    ResellerInvite,
    ResellerPayout,
)
from distrib.services import allocation, settlement as svc
from distrib.tests_catalog import make_wholesale
from distrib.tests_models import make_distributor, make_seller
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order, OrderItem, OrderStatus
from orders.services.create_order import create_order
from products.models import FlashSaleProduct, Product, StockMovement
from products.services.crud import attach_product_to_sale, create_product

S = DistribSettlement.Status


@override_settings(DISTRIB_ENABLED=True)
class SettlementBase(TestCase):
    def setUp(self):
        self.d = make_distributor()
        self.wp = make_wholesale(self.d, stock_total=50)  # gros 3000, minimum 4500
        self.seller = make_seller()
        self.invite = ResellerInvite.objects.create(
            distributor=self.d, display_name="Awa", phone=self.seller.user.phone,
            status=ResellerInvite.Status.ACCEPTED, seller=self.seller,
        )
        self.imported = allocation.import_product(
            invite=self.invite, wholesale_product=self.wp, retail_price=4800, actor=self.d.user, quantity=20
        )
        now = timezone.now()
        self.sale = FlashSale.objects.create(
            owner=self.seller, title="Live", start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=2), status=FlashSaleStatus.LIVE,
        )
        attach_product_to_sale(flash_sale=self.sale, product=self.imported.product)
        self.n = 0

    def place(self, product=None, qty=1, phone="+22376000001"):
        """Commande reelle par `create_order`, signal `on_commit` execute."""
        self.n += 1
        product = product or self.imported.product
        with self.captureOnCommitCallbacks(execute=True):
            order = create_order(
                {
                    "flash_sale_id": self.sale.pk, "customer_name": "Cliente", "customer_phone": phone,
                    "client_request_id": f"req-{self.n}", "items": [{"product_id": product.pk, "quantity": qty}],
                    "delivery": {"address_text": "Hamdallaye ACI, Bamako", "geo_method": "manual"},
                }
            )
        return order

    def set_order_status(self, order, status):
        order.status = status
        with self.captureOnCommitCallbacks(execute=True):
            order.save()

    def line(self, order=None):
        qs = DistribSettlement.objects.all()
        return qs.get(order=order) if order else qs.get()


class CreationAndMoneyTests(SettlementBase):
    def test_order_on_imported_product_creates_one_line_with_amounts(self):
        order = self.place(qty=2)
        line = self.line(order)
        self.assertEqual((line.distributor, line.invite, line.status), (self.d, self.invite, S.ORDERED))
        self.assertEqual(line.order_item, order.items.get())
        self.assertEqual(
            (line.quantity, line.sale_amount, line.wholesale_amount, line.reseller_margin),
            (2, Decimal("9600"), Decimal("6000"), Decimal("3600")),
        )
        self.assertEqual(len(line.receipt_code), 4)
        self.assertTrue(line.receipt_code.isdigit())
        self.assertGreaterEqual(len(line.receipt_token), 22)
        self.assertEqual((line.commission_amount, line.confirmed_at), (Decimal("0"), None))

    def test_test2_normal_product_orders_are_untouched_imported_ones_are_tracked(self):
        normal = create_product(owner=self.seller, name="Sac", price=Decimal("2000"), stock=5)
        attach_product_to_sale(flash_sale=self.sale, product=normal)
        normal_order = self.place(product=normal)
        imported_order = self.place()
        self.assertEqual(Order.service_objects.count(), 2)  # les deux commandes aboutissent
        self.assertFalse(DistribSettlement.objects.filter(order=normal_order).exists())
        self.assertTrue(DistribSettlement.objects.filter(order=imported_order).exists())
        self.assertEqual(DistribSettlement.objects.count(), 1)

    def test_amount_snapshot_uses_the_sale_price_not_the_catalog_price(self):
        FlashSaleProduct.objects.filter(flash_sale=self.sale, product=self.imported.product).update(
            promo_price=Decimal("4000")
        )
        line = self.line(self.place())
        self.assertEqual((line.sale_amount, line.reseller_margin), (Decimal("4000"), Decimal("1000")))


class SwitchAndFailureTests(SettlementBase):
    def test_test1_switch_off_means_no_signal_and_no_task(self):
        with override_settings(DISTRIB_ENABLED=False):
            order = self.place()
            self.assertTrue(Order.service_objects.filter(pk=order.pk).exists())
            self.assertEqual(DistribSettlement.objects.count(), 0)
            from distrib.tasks import auto_confirm_settlements_task, reconcile_settlements_task

            reconcile_settlements_task()
            auto_confirm_settlements_task()
            self.assertEqual(DistribSettlement.objects.count(), 0)
        # Interrupteur remis : la reconciliation rattrape.
        from distrib.tasks import reconcile_settlements_task

        reconcile_settlements_task()
        self.assertEqual(DistribSettlement.objects.count(), 1)

    def test_test3_an_exception_in_the_sync_never_blocks_the_order(self):
        with mock.patch("distrib.services.settlement.sync_order", side_effect=RuntimeError("boom")):
            order = self.place()
        self.assertTrue(Order.service_objects.filter(pk=order.pk).exists())
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(DistribSettlement.objects.count(), 0)
        # La reconciliation (beat) rattrape.
        self.assertEqual(svc.reconcile(), 1)
        self.assertEqual(DistribSettlement.objects.get().order_id, order.pk)

    def test_test3_an_exception_while_registering_the_callback_never_blocks_the_order(self):
        with mock.patch("distrib.signals.transaction.on_commit", side_effect=RuntimeError("boom")):
            order = self.place()
        self.assertTrue(Order.service_objects.filter(pk=order.pk).exists())
        self.assertEqual(DistribSettlement.objects.count(), 0)
        svc.reconcile()
        self.assertEqual(DistribSettlement.objects.count(), 1)

    def test_test3_stock_is_reserved_even_if_tracking_fails(self):
        with mock.patch("distrib.services.settlement.sync_order", side_effect=RuntimeError("boom")):
            self.place(qty=3)
        self.imported.product.refresh_from_db()
        self.assertEqual(self.imported.product.stock_available, 17)

    def test_reconcile_is_idempotent(self):
        with mock.patch("distrib.services.settlement.sync_order", side_effect=RuntimeError("boom")):
            self.place()
        svc.reconcile()
        svc.reconcile()
        self.assertEqual(DistribSettlement.objects.count(), 1)

    def test_reconcile_aligns_a_missed_status_change(self):
        order = self.place()
        Order.service_objects.filter(pk=order.pk).update(status=OrderStatus.OUT_FOR_DELIVERY)  # sans signal
        svc.reconcile()
        self.assertEqual(self.line(order).status, S.IN_DELIVERY)


class StatusSyncTests(SettlementBase):
    def test_test4_each_order_status_maps_to_the_right_line_status(self):
        expectations = [
            (OrderStatus.PENDING, S.ORDERED),
            (OrderStatus.CONFIRMED, S.ORDERED),
            (OrderStatus.OUT_FOR_DELIVERY, S.IN_DELIVERY),
            (OrderStatus.DELIVERED, S.DELIVERED_BY_SHOP),
            (OrderStatus.CANCELLED, S.CANCELLED),
        ]
        for order_status, expected in expectations:
            DistribSettlement.objects.all().delete()
            order = self.place()
            if order_status != OrderStatus.PENDING:
                self.set_order_status(order, order_status)
            self.assertEqual(self.line(order).status, expected, order_status)
            DistribSettlement.objects.all().delete()
            order.items.all().delete()

    def test_cancelled_line_has_no_commission(self):
        order = self.place()
        self.set_order_status(order, OrderStatus.CANCELLED)
        line = self.line(order)
        self.assertEqual((line.commission_amount, line.commission_billable), (Decimal("0"), False))

    def test_sync_is_idempotent_and_never_duplicates(self):
        order = self.place()
        for _ in range(3):
            svc.sync_order(order.pk)
        self.assertEqual(DistribSettlement.objects.count(), 1)

    def test_orders_are_never_modified_by_tracking(self):
        order = self.place()
        before = (Order.service_objects.values().get(pk=order.pk), list(OrderItem.objects.filter(order=order).values()))
        svc.sync_order(order.pk)
        svc.reconcile()
        svc.auto_confirm_due(now=timezone.now() + timedelta(days=30))
        after = (Order.service_objects.values().get(pk=order.pk), list(OrderItem.objects.filter(order=order).values()))
        self.assertEqual(before, after)


class PresumptionTests(SettlementBase):
    """Test 13 : le silence produit le resultat juste."""

    def test_clock_starts_at_confirmation_not_at_creation(self):
        order = self.place()
        line = self.line(order)
        self.assertIsNone(line.confirmed_at)
        self.assertIsNone(line.auto_confirm_at)
        # Commande restee « pending » : jamais auto-confirmee, meme des semaines apres.
        self.assertEqual(svc.auto_confirm_due(now=timezone.now() + timedelta(days=60)), 0)
        line.refresh_from_db()
        self.assertEqual(line.status, S.ORDERED)

    def test_confirmed_at_is_stamped_by_distrib_once(self):
        order = self.place()
        self.set_order_status(order, OrderStatus.CONFIRMED)
        line = self.line(order)
        first = line.confirmed_at
        self.assertIsNotNone(first)
        self.assertEqual(line.auto_confirm_at, first + timedelta(hours=72))
        self.set_order_status(order, OrderStatus.OUT_FOR_DELIVERY)
        svc.sync_order(order.pk)
        line.refresh_from_db()
        self.assertEqual(line.confirmed_at, first)  # pas de remise a zero
        self.assertEqual(line.auto_confirm_at, first + timedelta(hours=72))

    def test_auto_confirmation_exactly_at_the_deadline_never_before(self):
        order = self.place()
        self.set_order_status(order, OrderStatus.CONFIRMED)
        line = self.line(order)
        self.assertEqual(svc.auto_confirm_due(now=line.auto_confirm_at - timedelta(seconds=1)), 0)
        line.refresh_from_db()
        self.assertEqual(line.status, S.ORDERED)
        self.assertEqual(svc.auto_confirm_due(now=line.auto_confirm_at), 1)
        line.refresh_from_db()
        self.assertEqual(line.status, S.PAID_CONFIRMED)
        self.assertEqual(line.confirmation_source, "auto")
        self.assertIsNone(line.paid_confirmed_by)
        self.assertIsNotNone(line.paid_confirmed_at)

    def test_auto_confirm_hours_is_configurable_per_distributor(self):
        self.d.auto_confirm_hours = 1
        self.d.save()
        order = self.place()
        self.set_order_status(order, OrderStatus.CONFIRMED)
        line = self.line(order)
        self.assertEqual(line.auto_confirm_at, line.confirmed_at + timedelta(hours=1))

    def test_auto_confirmation_is_idempotent(self):
        order = self.place()
        self.set_order_status(order, OrderStatus.CONFIRMED)
        due = self.line(order).auto_confirm_at
        self.assertEqual(svc.auto_confirm_due(now=due), 1)
        stamp = self.line(order).paid_confirmed_at
        self.assertEqual(svc.auto_confirm_due(now=due + timedelta(hours=5)), 0)
        self.assertEqual(self.line(order).paid_confirmed_at, stamp)

    def test_cancelled_order_is_never_presumed_delivered(self):
        order = self.place()
        self.set_order_status(order, OrderStatus.CONFIRMED)
        due = self.line(order).auto_confirm_at
        Order.service_objects.filter(pk=order.pk).update(status=OrderStatus.CANCELLED)  # sync pas encore passee
        self.assertEqual(svc.auto_confirm_due(now=due), 0)
        svc.sync_order(order.pk)
        self.assertEqual(self.line(order).status, S.CANCELLED)

    def test_the_task_runs_the_presumption(self):
        order = self.place()
        self.set_order_status(order, OrderStatus.CONFIRMED)
        DistribSettlement.objects.update(auto_confirm_at=timezone.now() - timedelta(minutes=1))
        from distrib.tasks import auto_confirm_settlements_task

        auto_confirm_settlements_task()
        self.assertEqual(self.line(order).status, S.PAID_CONFIRMED)

    def test_an_error_on_one_line_does_not_stop_the_others(self):
        o1, o2 = self.place(), self.place()
        for o in (o1, o2):
            self.set_order_status(o, OrderStatus.CONFIRMED)
        DistribSettlement.objects.update(auto_confirm_at=timezone.now() - timedelta(minutes=1))
        real = svc._mark_paid
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return real(*args, **kwargs)

        with mock.patch("distrib.services.settlement._mark_paid", side_effect=flaky):
            done = svc.auto_confirm_due()
        self.assertEqual(done, 1)
        self.assertEqual(DistribSettlement.objects.filter(status=S.PAID_CONFIRMED).count(), 1)

    def test_countdown_is_visible_only_once_started(self):
        from distrib.views_orders import auto_confirm_info

        order = self.place()
        line = self.line(order)
        self.assertEqual(auto_confirm_info(line, timezone.now())["kind"], "waiting")
        self.set_order_status(order, OrderStatus.CONFIRMED)
        line = self.line(order)
        info = auto_confirm_info(line, line.confirmed_at + timedelta(hours=31))
        self.assertEqual((info["kind"], info["hours"]), ("running", 41))
        line.status = S.PAID_CONFIRMED
        self.assertEqual(auto_confirm_info(line, timezone.now())["kind"], "none")


class EarlyConfirmationTests(SettlementBase):
    def test_distributor_can_confirm_early_even_from_pending(self):
        order = self.place()
        line = self.line(order)
        confirmed, changed = svc.distributor_confirm(line, self.d.user)
        self.assertTrue(changed)
        self.assertEqual((confirmed.status, confirmed.confirmation_source, confirmed.paid_confirmed_by),
                         (S.PAID_CONFIRMED, "distributor", self.d.user))

    def test_test5_only_the_owner_distributor_can_confirm(self):
        line = self.line(self.place())
        other = make_distributor("+22371000002", "Autre gros")
        with self.assertRaises(PermissionDenied):
            svc.distributor_confirm(line, other.user)
        with self.assertRaises(PermissionDenied):
            svc.distributor_confirm(line, self.seller.user)
        line.refresh_from_db()
        self.assertEqual(line.status, S.ORDERED)

    def test_cancelled_line_cannot_be_confirmed(self):
        order = self.place()
        self.set_order_status(order, OrderStatus.CANCELLED)
        with self.assertRaises(ValidationError):
            svc.distributor_confirm(self.line(order), self.d.user)

    def test_double_confirmation_is_a_noop(self):
        line = self.line(self.place())
        svc.distributor_confirm(line, self.d.user)
        stamp = DistribSettlement.objects.get().paid_confirmed_at
        _, changed = svc.distributor_confirm(line, self.d.user)
        self.assertFalse(changed)
        self.assertEqual(DistribSettlement.objects.get().paid_confirmed_at, stamp)

    def test_paid_confirmed_is_never_downgraded_by_sync(self):
        order = self.place()
        svc.distributor_confirm(self.line(order), self.d.user)
        for status in (OrderStatus.PENDING, OrderStatus.CONFIRMED, OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED):
            self.set_order_status(order, status)
            self.assertEqual(self.line(order).status, S.PAID_CONFIRMED, status)

    def test_views_confirm_and_cloisonnement(self):
        line = self.line(self.place())
        self.client.force_login(self.d.user)
        resp = self.client.post(f"/distrib/commandes/{line.pk}/livre-paye/")
        self.assertRedirects(resp, "/distrib/commandes/")
        line.refresh_from_db()
        self.assertEqual(line.status, S.PAID_CONFIRMED)
        self.assertEqual(self.client.get(f"/distrib/commandes/{line.pk}/livre-paye/").status_code, 405)
        # Un autre grossiste : 404, rien ne change.
        other = make_distributor("+22371000002", "Autre gros")
        line2 = self.line(self.place())  # n'a qu'une ligne ouverte
        self.client.force_login(other.user)
        self.assertEqual(self.client.post(f"/distrib/commandes/{line2.pk}/livre-paye/").status_code, 404)
        self.assertEqual(self.client.post(f"/distrib/commandes/{line2.pk}/pas-livre/", {"reason": "refused"}).status_code, 404)
        line2.refresh_from_db()
        self.assertEqual(line2.status, S.ORDERED)


class NotDeliveredTests(SettlementBase):
    """Test 14 : « Pas livre » ne touche que `distrib`."""

    def snapshot(self, order):
        product = Product.objects.filter(pk=self.imported.product_id).values().get()
        return {
            "order": Order.service_objects.filter(pk=order.pk).values().get(),
            "items": list(OrderItem.objects.filter(order=order).values()),
            "product": product,
            "movements": list(StockMovement.objects.filter(product_id=self.imported.product_id).values()),
        }

    def test_declaration_changes_only_the_line(self):
        order = self.place(qty=2)
        self.set_order_status(order, OrderStatus.OUT_FOR_DELIVERY)
        before = self.snapshot(order)
        line = svc.declare_not_delivered(self.line(order), self.d.user, reason="absent")
        after = self.snapshot(order)
        self.assertEqual(before, after)  # Order, OrderItem, stock et mouvements strictement inchanges
        self.assertEqual((line.status, line.not_delivered_reason, line.declared_by), (S.NOT_DELIVERED, "absent", self.d.user))
        self.assertIsNotNone(line.declared_at)

    def test_no_stock_service_and_no_cancellation_is_called(self):
        order = self.place()
        with mock.patch("orders.services.stock_release.release_order_stock") as release, mock.patch(
            "products.services.crud.adjust_stock"
        ) as adjust, mock.patch("delivery.services.delivery.advance_delivery") as advance:
            svc.declare_not_delivered(self.line(order), self.d.user, reason="refused")
        release.assert_not_called()
        adjust.assert_not_called()
        advance.assert_not_called()

    def test_reason_is_mandatory_and_other_needs_a_note(self):
        line = self.line(self.place())
        for bad in ("", "nimporte"):
            with self.assertRaises(ValidationError):
                svc.declare_not_delivered(line, self.d.user, reason=bad)
        with self.assertRaises(ValidationError):
            svc.declare_not_delivered(line, self.d.user, reason="other", note="  ")
        done = svc.declare_not_delivered(line, self.d.user, reason="other", note="Adresse introuvable")
        self.assertEqual(done.not_delivered_note, "Adresse introuvable")

    def test_refused_after_paid_confirmed_and_for_a_foreign_distributor(self):
        line = self.line(self.place())
        other = make_distributor("+22371000002", "Autre gros")
        with self.assertRaises(PermissionDenied):
            svc.declare_not_delivered(line, other.user, reason="refused")
        svc.distributor_confirm(line, self.d.user)
        with self.assertRaisesMessage(ValidationError, "Trop tard"):
            svc.declare_not_delivered(line, self.d.user, reason="refused")
        self.assertEqual(DistribSettlement.objects.get().status, S.PAID_CONFIRMED)

    def test_declaring_twice_is_refused(self):
        line = self.line(self.place())
        svc.declare_not_delivered(line, self.d.user, reason="refused")
        with self.assertRaises(ValidationError):
            svc.declare_not_delivered(line, self.d.user, reason="absent")

    def test_before_the_deadline_it_blocks_the_presumption(self):
        order = self.place()
        self.set_order_status(order, OrderStatus.CONFIRMED)
        svc.declare_not_delivered(self.line(order), self.d.user, reason="absent")
        self.assertEqual(svc.auto_confirm_due(now=timezone.now() + timedelta(days=10)), 0)
        self.assertEqual(self.line(order).status, S.NOT_DELIVERED)

    def test_sync_never_overwrites_not_delivered(self):
        order = self.place()
        svc.declare_not_delivered(self.line(order), self.d.user, reason="absent")
        for status in (OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED, OrderStatus.CANCELLED):
            self.set_order_status(order, status)
            svc.reconcile()
            self.assertEqual(self.line(order).status, S.NOT_DELIVERED, status)
        self.assertEqual(DistribCorrection.objects.count(), 0)

    def test_expiration_later_does_not_double_release_the_stock(self):
        """Le stock n'est rendu qu'une fois, par le circuit normal : distrib n'a rien libere."""
        from orders.services.expiration import expire_pending_orders

        order = self.place(qty=2)
        svc.declare_not_delivered(self.line(order), self.d.user, reason="absent")
        Order.service_objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(hours=60))
        expire_pending_orders()
        self.imported.product.refresh_from_db()
        self.assertEqual(self.imported.product.stock_available, 20)  # 18 + 2 rendus, une seule fois
        self.assertEqual(self.line(order).status, S.NOT_DELIVERED)

    def test_views(self):
        line = self.line(self.place())
        self.client.force_login(self.d.user)
        resp = self.client.post(f"/distrib/commandes/{line.pk}/pas-livre/", {"reason": "refused"})
        self.assertRedirects(resp, "/distrib/commandes/")
        line.refresh_from_db()
        self.assertEqual(line.status, S.NOT_DELIVERED)
        bad = self.line(self.place())
        self.client.post(f"/distrib/commandes/{bad.pk}/pas-livre/", {"reason": "other"})
        bad.refresh_from_db()
        self.assertEqual(bad.status, S.ORDERED)


class CancelAfterConfirmationTests(SettlementBase):
    """Test 15 : jamais de retrogradation, sauf la presomption renversee."""

    def confirm_auto(self, order):
        self.set_order_status(order, OrderStatus.CONFIRMED)
        due = self.line(order).auto_confirm_at
        svc.auto_confirm_due(now=due)
        line = self.line(order)
        self.assertEqual((line.status, line.confirmation_source), (S.PAID_CONFIRMED, "auto"))
        return line

    def make_statement(self, *lines, status="to_pay"):
        amount = sum((line.reseller_margin for line in lines), Decimal("0"))
        statement = DistribStatement.objects.create(
            distributor=self.d, invite=self.invite, period_start="2026-10-12", period_end="2026-10-18",
            amount=amount, line_count=len(lines), status=status,
        )
        DistribSettlement.objects.filter(pk__in=[line.pk for line in lines]).update(statement=statement)
        return statement

    def test_a_auto_without_payout_is_reversed_and_recalculated(self):
        o1, o2 = self.place(qty=1), self.place(qty=2)
        l1, l2 = self.confirm_auto(o1), self.confirm_auto(o2)
        self.assertEqual(l1.commission_amount, Decimal("288"))  # 6 % de 4 800
        statement = self.make_statement(l1, l2)  # 1 800 + 3 600
        self.set_order_status(o2, OrderStatus.CANCELLED)
        l2.refresh_from_db()
        self.assertEqual(l2.status, S.CANCELLED)
        self.assertEqual((l2.reseller_margin, l2.commission_amount, l2.commission_billable), (0, 0, False))
        self.assertIsNone(l2.statement_id)
        correction = DistribCorrection.objects.get()
        self.assertEqual((correction.settlement, correction.old_status, correction.new_status, correction.author),
                         (l2, "paid_confirmed", "cancelled", None))
        statement.refresh_from_db()
        self.assertEqual((statement.amount, statement.line_count), (Decimal("1800"), 1))
        from distrib.services import ceilings

        self.assertEqual(ceilings.reseller_due(self.invite), Decimal("1800"))

    def test_a_replaying_the_sync_has_no_further_effect(self):
        order = self.place()
        self.confirm_auto(order)
        self.set_order_status(order, OrderStatus.CANCELLED)
        for _ in range(3):
            svc.sync_order(order.pk)
            svc.reconcile()
        self.assertEqual(DistribCorrection.objects.count(), 1)
        self.assertEqual(self.line(order).status, S.CANCELLED)

    def test_a_an_emptied_statement_disappears(self):
        order = self.place()
        line = self.confirm_auto(order)
        self.make_statement(line)
        self.set_order_status(order, OrderStatus.CANCELLED)
        self.assertEqual(DistribStatement.objects.count(), 0)

    def test_b_distributor_or_customer_confirmation_is_kept_with_a_conflict_flag(self):
        for source in ("distributor", "customer"):
            DistribSettlement.objects.all().delete()
            AuditLog.objects.all().delete()
            order = self.place()
            line = self.line(order)
            svc.confirm_paid(line, source=source, by=self.d.user)
            self.set_order_status(order, OrderStatus.CANCELLED)
            line.refresh_from_db()
            self.assertEqual(line.status, S.PAID_CONFIRMED, source)
            self.assertTrue(line.conflict_flag, source)
            self.assertEqual(line.reseller_margin, Decimal("1800"))
            self.assertTrue(AuditLog.objects.filter(action="distrib.signal.cancelled_after_confirmation").exists())
            self.assertEqual(DistribCorrection.objects.count(), 0)
            Order.service_objects.filter(pk=order.pk).delete()

    def test_c_auto_but_already_in_a_payout_is_kept_with_a_conflict_flag(self):
        order = self.place()
        line = self.confirm_auto(order)
        statement = self.make_statement(line, status="paid")
        payout = ResellerPayout.objects.create(
            distributor=self.d, invite=self.invite, statement=statement, amount=line.reseller_margin,
            om_reference="OM123",
        )
        DistribSettlement.objects.filter(pk=line.pk).update(payout=payout)
        self.set_order_status(order, OrderStatus.CANCELLED)
        line.refresh_from_db()
        self.assertEqual(line.status, S.PAID_CONFIRMED)
        self.assertTrue(line.conflict_flag)
        statement.refresh_from_db()
        self.assertEqual(statement.amount, Decimal("1800"))  # relevé paye : fige

    def test_d_not_delivered_is_never_touched(self):
        order = self.place()
        svc.declare_not_delivered(self.line(order), self.d.user, reason="refused")
        self.set_order_status(order, OrderStatus.CANCELLED)
        line = self.line(order)
        self.assertEqual((line.status, line.conflict_flag), (S.NOT_DELIVERED, False))

    def test_staff_correction_is_journaled_and_staff_only(self):
        order = self.place()
        line = self.line(order)
        svc.distributor_confirm(line, self.d.user)
        staff = make_seller("+22370000099", "Equipe").user
        staff.is_staff = True
        staff.save()
        with self.assertRaises(PermissionDenied):
            svc.staff_correct(line, self.d.user, new_status=S.NOT_DELIVERED, reason="x")
        with self.assertRaises(ValidationError):
            svc.staff_correct(line, staff, new_status=S.NOT_DELIVERED, reason="  ")
        svc.staff_correct(line, staff, new_status=S.NOT_DELIVERED, reason="Cliente jointe : refus confirmé")
        line = self.line(order)
        self.assertEqual((line.status, line.paid_confirmed_at, line.commission_amount), (S.NOT_DELIVERED, None, 0))
        correction = DistribCorrection.objects.get()
        self.assertEqual((correction.old_status, correction.new_status, correction.author, correction.reason),
                         ("paid_confirmed", "not_delivered", staff, "Cliente jointe : refus confirmé"))

    def test_staff_cannot_correct_a_line_already_in_a_payout(self):
        line = self.line(self.place())
        svc.distributor_confirm(line, self.d.user)
        statement = self.make_statement(line, status="paid")
        payout = ResellerPayout.objects.create(
            distributor=self.d, invite=self.invite, statement=statement, amount=line.reseller_margin, om_reference="OM1"
        )
        DistribSettlement.objects.filter(pk=line.pk).update(payout=payout)
        staff = make_seller("+22370000099", "Equipe").user
        staff.is_staff = True
        staff.save()
        with self.assertRaisesMessage(ValidationError, "versement"):
            svc.staff_correct(line, staff, new_status=S.CANCELLED, reason="test")

    def test_pilotage_pages_are_staff_only(self):
        line = self.line(self.place())
        svc.distributor_confirm(line, self.d.user)
        self.client.force_login(self.d.user)
        self.assertEqual(self.client.get("/distrib/pilotage/signaux/").status_code, 403)
        self.assertEqual(
            self.client.post(f"/distrib/pilotage/lignes/{line.pk}/corriger/", {"new_status": "cancelled", "reason": "x"}).status_code,
            403,
        )
        staff = make_seller("+22370000099", "Equipe").user
        staff.is_staff = True
        staff.save()
        self.client.force_login(staff)
        DistribSettlement.objects.filter(pk=line.pk).update(conflict_flag=True)
        self.assertContains(self.client.get("/distrib/pilotage/signaux/"), "Gros Bamako")
        self.client.post(f"/distrib/pilotage/lignes/{line.pk}/corriger/", {"new_status": "cancelled", "reason": "Erreur de saisie"})
        self.assertEqual(self.line().status, S.CANCELLED)
        self.assertEqual(DistribCorrection.objects.get().author, staff)


class OrdersPageTests(SettlementBase):
    def test_test6_cloisonnement_and_no_receipt_code_anywhere_on_the_distributor_side(self):
        order = self.place()
        line = self.line(order)
        DistribSettlement.objects.filter(pk=line.pk).update(receipt_code="9273")
        self.client.force_login(self.d.user)
        page = self.client.get("/distrib/commandes/")
        self.assertContains(page, "Robe wax")
        self.assertContains(page, "Hamdallaye ACI")  # adresse de livraison, pour livrer
        self.assertNotContains(page, "9273")
        self.assertNotContains(page, line.receipt_token)
        other = make_distributor("+22371000002", "Autre gros")
        self.client.force_login(other.user)
        self.assertNotContains(self.client.get("/distrib/commandes/"), "Robe wax")

    def test_distributor_does_not_see_non_imported_products_of_the_reseller(self):
        normal = create_product(owner=self.seller, name="Secret perso", price=Decimal("2000"), stock=5)
        attach_product_to_sale(flash_sale=self.sale, product=normal)
        self.place(product=normal, phone="+22376000007")
        self.place()
        self.client.force_login(self.d.user)
        page = self.client.get("/distrib/commandes/")
        self.assertNotContains(page, "Secret perso")
        self.assertNotContains(page, "+22376000007")

    def test_filters(self):
        o1, o2 = self.place(), self.place()
        svc.distributor_confirm(self.line(o1), self.d.user)
        self.client.force_login(self.d.user)
        page = self.client.get("/distrib/commandes/?statut=paid_confirmed")
        self.assertContains(page, f"Commande n° {o1.pk}")
        self.assertNotContains(page, f"Commande n° {o2.pk}")

    def test_countdown_is_displayed(self):
        order = self.place()
        self.client.force_login(self.d.user)
        self.assertContains(self.client.get("/distrib/commandes/"), "Démarre à la confirmation")
        self.set_order_status(order, OrderStatus.CONFIRMED)
        self.assertContains(self.client.get("/distrib/commandes/"), "Confirmée automatiquement dans")

    def test_off_means_404_and_resellers_are_forbidden(self):
        self.client.force_login(self.seller.user)
        self.assertEqual(self.client.get("/distrib/commandes/").status_code, 403)
        with override_settings(DISTRIB_ENABLED=False):
            self.client.force_login(self.d.user)
            self.assertEqual(self.client.get("/distrib/commandes/").status_code, 404)
