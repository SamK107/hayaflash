"""Commande `seed_demo_distrib` : coherence des donnees de demonstration et remise a zero ciblee."""

from __future__ import annotations

import logging
import tempfile
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Sum
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from accounts.models import SellerProfile
from distrib.management.commands import seed_demo_distrib as seed
from distrib.models import (
    AllocationMovement,
    DistribPayment,
    DistribSettlement,
    DistribStatement,
    Distributor,
    ImportedProduct,
    ResellerInvite,
    ResellerPayout,
    WholesaleProduct,
)
from distrib.services import ceilings
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order, OrderItem, OrderStatus
from products.models import Product
from products.services.crud import create_product

User = get_user_model()


def _fake_images(root: Path) -> None:
    """Images factices nommees comme les vraies (le nom du fichier fait le nom du produit)."""
    stems = {
        "habits": ["abaya-brodee", "boubou-bazin-brode", "chemise-lin-homme", "ensemble-tailleur-femme", "robe-wax-cintree", "robe-dentelle-cocktail", "robe-longue-foulard"],
        "chaussures": ["baskets-bleu-marine", "escarpins-bordeaux", "escarpins-dores", "escarpins-moutarde-chainette", "mocassins-cuir-homme"],
        "sacs": ["sac-a-main-cuir-camel", "sac-a-main-cuir-creme", "sac-a-main-cuir-noir", "sac-bandouliere-beige-cognac", "sac-trapeze-taupe"],
        "parfums": ["eau-de-parfum-rose", "parfum-ambre-coffret-noir", "parfum-cristal-or", "parfum-flacon-noir-or", "parfum-oriental-ambre"],
        "cosmetiques": ["lait-corporel-karite", "beurre-de-karite-pur", "huile-de-coco-visage", "savon-noir-africain", "gommage-corps-sucre"],
    }
    for category, names in stems.items():
        folder = root / "produits" / category
        folder.mkdir(parents=True)
        for index, name in enumerate(names):
            Image.new("RGB", (60, 40), (40 * index, 90, 160)).save(folder / f"{name}.jpg")
    market = root / "marche"
    market.mkdir(parents=True)
    for index, name in enumerate(seed.MARKET_PRICES):
        Image.new("RGBA", (60, 40), (200, 40 * index, 90, 255)).save(market / f"{name}.png")
    return stems


class SeedDemoDistribTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        logging.disable(logging.INFO)  # delivery_advance journalise chaque etape : bruit, pas un signal
        cls._tmp = tempfile.TemporaryDirectory()
        cls.assets = Path(cls._tmp.name) / "assets"
        cls.stems = _fake_images(cls.assets)
        cls._media = override_settings(MEDIA_ROOT=str(Path(cls._tmp.name) / "media"), DEBUG=True)
        cls._media.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media.disable()
        logging.disable(logging.NOTSET)
        cls._tmp.cleanup()
        super().tearDownClass()

    def run_seed(self, **options):
        out = StringIO()
        call_command("seed_demo_distrib", assets_dir=str(self.assets), stdout=out, **options)
        return out.getvalue()

    def make_real_shop(self):
        """Une vraie boutique, hors plage demo, dont rien ne doit bouger."""
        user = User.objects.create_user(phone="+22377112233", password="x-Real-2026", display_name="Vraie Vendeuse")
        seller = SellerProfile.objects.create(user=user, business_name="Vraie Boutique")
        product = create_product(owner=seller, name="Vrai produit", price=5000, stock=7)
        now = timezone.now()
        sale = FlashSale.objects.create(
            owner=seller, title="Vraie vente", start_time=now, end_time=now + timedelta(hours=1),
            status=FlashSaleStatus.LIVE,
        )
        return user, seller, product, sale

    # ── Garde-fous ────────────────────────────────────────────────────────

    def test_refuses_when_debug_is_false(self):
        with override_settings(DEBUG=False):
            with self.assertRaises(CommandError):
                self.run_seed()
        self.assertFalse(User.objects.filter(phone__regex=seed.DEMO_PHONE_REGEX).exists())

    def test_refuses_on_production_environment(self):
        with override_settings(ENVIRONMENT="prod"):
            with self.assertRaises(CommandError):
                self.run_seed()

    # ── Coherence ─────────────────────────────────────────────────────────

    def test_seed_is_consistent(self):
        output = self.run_seed()
        self.assertIn("IDENTIFIANTS", output)
        self.assertIn("/ventes/", output)

        distributor = Distributor.objects.get()
        self.assertEqual(distributor.business_name, "Grossiste Démo Bamako")
        self.assertEqual(WholesaleProduct.objects.count(), 27)
        self.assertEqual(ResellerInvite.objects.filter(status=ResellerInvite.Status.ACCEPTED).count(), 15)

        # Tout est dans la plage de numeros fictifs.
        for user in User.objects.all():
            self.assertTrue(seed.is_demo_phone(user.phone), user.phone)
        for order in Order.service_objects.all():
            self.assertTrue(seed.is_demo_phone(order.customer_phone), order.customer_phone)

        # Montants entiers, prix de revente > prix de gros (marge 1 000 a 3 000).
        for imported in ImportedProduct.objects.select_related("product", "wholesale_product"):
            margin = imported.product.price - imported.wholesale_product.wholesale_price
            self.assertEqual(imported.product.price, imported.product.price.to_integral_value())
            self.assertTrue(Decimal(1000) <= margin <= Decimal(3000), margin)

        self.assert_stock_consistent()
        self.assert_money_consistent()
        self.assert_categories_respected()
        self.assert_scenario_coverage()

    def assert_stock_consistent(self):
        for imported in ImportedProduct.objects.select_related("product"):
            ordered = (
                OrderItem.objects.filter(product=imported.product).exclude(order__status=OrderStatus.CANCELLED)
                .aggregate(t=Sum("quantity"))["t"] or 0
            )
            self.assertEqual(imported.allocated_qty - ordered, imported.product.stock_available, imported)
            self.assertGreaterEqual(imported.product.stock_available, 0)

    def assert_money_consistent(self):
        paid = DistribSettlement.objects.filter(status=DistribSettlement.Status.PAID_CONFIRMED)
        for line in paid:
            self.assertEqual(line.reseller_margin, line.sale_amount - line.wholesale_amount)
        total_margins = paid.aggregate(t=Sum("reseller_margin"))["t"]
        statement_total = DistribStatement.objects.aggregate(t=Sum("amount"))["t"] or Decimal(0)
        unstatemented = paid.filter(statement__isnull=True).aggregate(t=Sum("reseller_margin"))["t"] or Decimal(0)
        self.assertEqual(total_margins, statement_total + unstatemented)
        for statement in DistribStatement.objects.all():
            lines_total = statement.lines.aggregate(t=Sum("reseller_margin"))["t"]
            self.assertEqual(statement.amount, lines_total)
            self.assertEqual(statement.line_count, statement.lines.count())
        for payout in ResellerPayout.objects.select_related("statement"):
            self.assertEqual(payout.amount, payout.statement.amount)

        distributor = Distributor.objects.get()
        for invite in ResellerInvite.objects.all():
            self.assertLess(ceilings.reseller_due(invite), distributor.reseller_credit_ceiling, invite.display_name)
        self.assertEqual(distributor.credit_ceiling, Decimal(10000))
        self.assertLess(ceilings.commission_outstanding(distributor), distributor.credit_ceiling)
        self.assertGreaterEqual(ceilings.commission_outstanding(distributor), 0)
        self.assertTrue(DistribPayment.objects.exists())

    def assert_categories_respected(self):
        category_of = {seed.product_name_from_stem(stem): category for category, stems in self.stems.items() for stem in stems}
        for spec in seed.RESELLERS:
            allowed = {category for category, _count in spec["products"]}
            invite = ResellerInvite.objects.get(phone=spec["phone"])
            names = ImportedProduct.objects.filter(invite=invite).values_list("wholesale_product__name", flat=True)
            self.assertTrue(names)
            self.assertLessEqual({category_of[name] for name in names}, allowed, spec["shop"])
            # Le stock de la boutique ne contient que ces produits importes (aucun autre stock).
            shop_products = Product.objects.filter(owner=invite.seller)
            self.assertEqual(shop_products.count(), len(names))

    def assert_scenario_coverage(self):
        now = timezone.now()
        statuses = set(Order.service_objects.values_list("status", flat=True))
        self.assertTrue({OrderStatus.PENDING, OrderStatus.CONFIRMED, OrderStatus.OUT_FOR_DELIVERY,
                         OrderStatus.DELIVERED, OrderStatus.CANCELLED} <= statuses, statuses)
        lines = set(DistribSettlement.objects.values_list("status", flat=True))
        S = DistribSettlement.Status
        self.assertTrue({S.ORDERED, S.IN_DELIVERY, S.DELIVERED_BY_SHOP, S.PAID_CONFIRMED, S.CANCELLED, S.NOT_DELIVERED} <= lines, lines)

        awa = SellerProfile.objects.get(user__phone=seed.RESELLERS[0]["phone"])
        live = FlashSale.objects.filter(owner=awa, status=FlashSaleStatus.LIVE, start_time__lte=now, end_time__gte=now)
        self.assertEqual(live.count(), 1)
        self.assertTrue(live.get().orders.exists())
        done = FlashSale.objects.filter(owner__user__phone__in=[r["phone"] for r in seed.RESELLERS], status=FlashSaleStatus.COMPLETED)
        self.assertGreaterEqual(done.count(), 5)
        self.assertEqual(done.filter(end_time__gte=now - timedelta(days=91), end_time__lt=now).count(), done.count())

        self.assertTrue(DistribStatement.objects.filter(status=DistribStatement.Status.ACCEPTED).exists())
        self.assertTrue(ResellerPayout.objects.exists())
        self.assertTrue(DistribStatement.objects.filter(status=DistribStatement.Status.TO_PAY).exists())

        # Boutiques independantes : aucune n'est liee a Distrib, toutes ont une vente en cours.
        market_sellers = SellerProfile.objects.filter(user__phone__in=[m["phone"] for m in seed.MARKET_SHOPS])
        self.assertGreaterEqual(market_sellers.count(), 4)
        for seller in market_sellers:
            self.assertFalse(ImportedProduct.objects.filter(product__owner=seller).exists())
            self.assertTrue(FlashSale.objects.filter(owner=seller, start_time__lte=now, end_time__gte=now).exists())

        # Les montants ne portent jamais de centimes.
        for value in Order.service_objects.values_list("total_amount", flat=True):
            self.assertEqual(value, value.to_integral_value())

    # ── Idempotence et remise a zero ──────────────────────────────────────

    def test_rerun_without_reset_changes_nothing(self):
        self.run_seed()
        counts = (Order.service_objects.count(), User.objects.count(), FlashSale.objects.count())
        output = self.run_seed()
        self.assertIn("--reset", output)
        self.assertEqual(counts, (Order.service_objects.count(), User.objects.count(), FlashSale.objects.count()))

    def test_reset_only_removes_demo_data(self):
        real_user, real_seller, real_product, real_sale = self.make_real_shop()
        self.run_seed()
        first_distributor = Distributor.objects.get().pk
        orders_before = Order.service_objects.count()

        self.run_seed(reset=True)
        self.assertEqual(Distributor.objects.count(), 1)
        self.assertEqual(Order.service_objects.count(), orders_before)  # meme scenario, recree
        self.assertEqual(WholesaleProduct.objects.count(), 27)
        self.assertNotEqual(Distributor.objects.get().pk, first_distributor)

        # La vraie boutique n'a pas bougé.
        real_product.refresh_from_db()
        self.assertEqual(real_product.stock_available, 7)
        self.assertTrue(User.objects.filter(pk=real_user.pk).exists())
        self.assertTrue(SellerProfile.objects.filter(pk=real_seller.pk).exists())
        self.assertTrue(FlashSale.objects.filter(pk=real_sale.pk).exists())
        self.assertEqual(Product.objects.filter(owner=real_seller).count(), 1)
        self.assert_stock_consistent()

        # Reset sans rien a supprimer, puis suppression complete : il ne reste que le reel.
        from distrib.management.commands.seed_demo_distrib import Command

        cmd = Command()
        cmd.stdout = StringIO()
        cmd.style = Command().style
        cmd.reset()
        self.assertFalse(User.objects.filter(phone__regex=seed.DEMO_PHONE_REGEX).exists())
        self.assertEqual(Distributor.objects.count(), 0)
        self.assertEqual(Order.service_objects.count(), 0)
        self.assertEqual(list(User.objects.values_list("pk", flat=True)), [real_user.pk])
        self.assertEqual(FlashSale.objects.count(), 1)
        self.assertEqual(Product.objects.count(), 1)

    # ── V2 : 15 revendeuses, 90 jours d'historique ────────────────────────

    def snapshot(self):
        S = DistribSettlement.Status
        paid = DistribSettlement.objects.filter(status=S.PAID_CONFIRMED)
        return {
            "orders": Order.service_objects.count(),
            "lines": DistribSettlement.objects.count(),
            "paid": paid.count(),
            "revenue": paid.aggregate(t=Sum("sale_amount"))["t"],
            "not_delivered": DistribSettlement.objects.filter(status=S.NOT_DELIVERED).count(),
            "statements": sorted(DistribStatement.objects.values_list("status", flat=True)),
            "paid_by_reseller": sorted(paid.values_list("invite__phone", flat=True)),
        }

    def test_v2_resellers_profiles_and_history(self):
        from distrib.services import reliability
        from distrib.services.allocation import imports_below_minimum

        self.run_seed()
        S = DistribSettlement.Status
        now = timezone.now()
        distributor = Distributor.objects.get()

        # 15 revendeuses, les 10 nouvelles sur +22370000050 a 59, tous les numeros dans la plage demo.
        self.assertEqual(len(seed.RESELLERS), 15)
        new_phones = {f"+223700000{n}" for n in range(50, 60)}
        self.assertTrue(new_phones <= {r["phone"] for r in seed.RESELLERS})
        for user in User.objects.all():
            self.assertTrue(seed.is_demo_phone(user.phone), user.phone)
        profiles = {}
        for spec in seed.RESELLERS:
            profiles.setdefault(spec["profile"], []).append(spec)
        self.assertEqual({k: len(v) for k, v in profiles.items()},
                         {"star": 2, "reguliere": 5, "moyenne": 4, "irreguliere": 2, "nouvelle": 2})

        def paid_count(spec):
            return DistribSettlement.objects.filter(invite__phone=spec["phone"], status=S.PAID_CONFIRMED).count()

        def failed_ratio(spec):
            lines = DistribSettlement.objects.filter(invite__phone=spec["phone"]).exclude(status=S.CANCELLED)
            return lines.filter(status=S.NOT_DELIVERED).count() / max(lines.count(), 1)

        for spec in profiles["star"]:
            self.assertTrue(60 <= paid_count(spec) <= 90, (spec["shop"], paid_count(spec)))
            self.assertLess(failed_ratio(spec), 0.06)
        for spec in profiles["reguliere"]:
            self.assertTrue(25 <= paid_count(spec) <= 45, (spec["shop"], paid_count(spec)))
        for spec in profiles["moyenne"]:
            self.assertTrue(10 <= paid_count(spec) <= 20, (spec["shop"], paid_count(spec)))
        for spec in profiles["irreguliere"]:
            self.assertGreater(failed_ratio(spec), 0.4, spec["shop"])
        for spec in profiles["nouvelle"]:
            self.assertTrue(2 <= paid_count(spec) <= 6, (spec["shop"], paid_count(spec)))
            self.assertGreaterEqual(User.objects.get(phone=spec["phone"]).date_joined, now - timedelta(days=21))

        # Alertes : fiabilite sur 30 jours, prix minimum, versement conteste.
        self.assertIn(reliability.ALERT_NOT_DELIVERED, reliability.reliability(distributor)["alerts"])
        self.assertTrue(imports_below_minimum(distributor).exists())
        self.assertTrue(ResellerPayout.objects.filter(status=ResellerPayout.Status.CONTESTED).exists())
        self.assertTrue(DistribStatement.objects.filter(status=DistribStatement.Status.CONTESTED).exists())

        # Releves hebdomadaires sur toute la periode : references OM saisies sauf les releves « a regler ».
        self.assertGreaterEqual(DistribStatement.objects.values("period_start").distinct().count(), 10)
        to_pay = DistribStatement.objects.filter(status=DistribStatement.Status.TO_PAY)
        self.assertTrue(to_pay.exists())
        self.assertFalse(ResellerPayout.objects.filter(statement__in=to_pay).exists())
        self.assertTrue(DistribStatement.objects.filter(status=DistribStatement.Status.PAID).exists())
        for payout in ResellerPayout.objects.all():
            self.assertTrue(payout.om_reference)

        # Activite : au moins 30 % dans les 30 derniers jours, trois sources de confirmation, reprises d'invendus.
        paid = DistribSettlement.objects.filter(status=S.PAID_CONFIRMED)
        self.assertGreaterEqual(paid.filter(paid_confirmed_at__gte=now - timedelta(days=30)).count() * 100, 30 * paid.count())
        self.assertEqual(set(paid.values_list("confirmation_source", flat=True)),
                         {"distributor", "customer", "auto"})
        self.assertTrue(AllocationMovement.objects.filter(quantity_change__lt=0, reason="Reprise d'invendus").exists())
        self.assertGreaterEqual(FlashSale.objects.filter(status=FlashSaleStatus.LIVE, start_time__lte=now, end_time__gte=now).count(), 1)

        # FCFA entiers partout, prix de revente >= minimum sauf cas d'alerte volontaire.
        for line in DistribSettlement.objects.all():
            for value in (line.sale_amount, line.wholesale_amount, line.reseller_margin, line.commission_amount):
                self.assertEqual(value, value.to_integral_value())
        flagged = set(imports_below_minimum(distributor).values_list("pk", flat=True))
        for imported in ImportedProduct.objects.select_related("product", "wholesale_product"):
            if imported.pk not in flagged:
                self.assertGreaterEqual(imported.product.price, imported.wholesale_product.min_retail_price)

    def test_v2_is_reproducible(self):
        self.run_seed()
        first = self.snapshot()
        self.run_seed(reset=True)
        self.assertEqual(self.snapshot(), first)

    def test_no_brand_names_in_demo_texts(self):
        self.run_seed()
        forbidden = ("chanel", "dior", "gucci", "louis vuitton", "nike", "adidas", "rolex", "apple", "samsung", "zara")
        texts = list(WholesaleProduct.objects.values_list("name", "description")) + list(
            SellerProfile.objects.values_list("business_name", "bio")
        ) + list(FlashSale.objects.values_list("title", "description"))
        for row in texts:
            for text in row:
                self.assertFalse(any(word in text.lower() for word in forbidden), text)
