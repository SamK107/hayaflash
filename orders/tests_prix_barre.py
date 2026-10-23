"""Prix barre + « Prix promo » sur les pages clientes (docs/specs/SPEC_01_PRIX_BARRE.md).

Affichage seulement : le prix facture reste le prix de la vente.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from products.services.crud import (
    attach_product_to_sale,
    create_product,
    products_for_sale,
    promo_discount_percent,
)

User = get_user_model()


class PrixBarreBase(TestCase):
    def setUp(self):
        user = User.objects.create_user(phone="+22371000001", password="x", display_name="Awa")
        self.seller = SellerProfile.objects.create(user=user, business_name="Boutique Awa")
        now = timezone.now()
        self.sale = FlashSale.objects.create(
            owner=self.seller, title="Destockage",
            start_time=now - timedelta(minutes=5), end_time=now + timedelta(hours=1),
            status=FlashSaleStatus.LIVE,
        )
        self.promo = create_product(owner=self.seller, name="Robe promo", price=Decimal("10000"), stock=5)
        attach_product_to_sale(flash_sale=self.sale, product=self.promo, promo_price=Decimal("7500"))
        self.plain = create_product(owner=self.seller, name="Sac normal", price=Decimal("4000"), stock=5)
        attach_product_to_sale(flash_sale=self.sale, product=self.plain)
        self.same = create_product(owner=self.seller, name="Promo egale", price=Decimal("3000"), stock=5)
        attach_product_to_sale(flash_sale=self.sale, product=self.same, promo_price=Decimal("3000"))

    def order_page(self, product):
        return self.client.get(
            reverse("client_order"), {"flash_sale_id": self.sale.pk, "product_id": product.pk}
        )

    def sale_page(self):
        return self.client.get(f"/f/{self.sale.public_slug}/")


class DiscountCalcTests(TestCase):
    def test_same_rule_everywhere(self):
        self.assertEqual(promo_discount_percent(Decimal("10000"), Decimal("7500")), 25)
        self.assertIsNone(promo_discount_percent(Decimal("10000"), Decimal("10000")))
        self.assertIsNone(promo_discount_percent(Decimal("10000"), None))
        self.assertEqual(promo_discount_percent(Decimal("10000"), Decimal("9990")), 1)


class ProductsForSaleTests(PrixBarreBase):
    def test_catalog_price_kept_and_sale_price_applied(self):
        by_name = {p.name: p for p in products_for_sale(self.sale)}
        robe = by_name["Robe promo"]
        self.assertEqual(robe.price, Decimal("7500"))
        self.assertEqual(robe.catalog_price, Decimal("10000"))
        self.assertEqual((robe.promo_discount, robe.promo_saving), (25, 2500))
        self.assertIsNone(by_name["Sac normal"].promo_discount)
        self.assertIsNone(by_name["Promo egale"].promo_discount)


class SalePageTests(PrixBarreBase):
    def test_promo_product_shows_struck_price_and_saving(self):
        html = self.sale_page().content.decode()
        self.assertIn("10 000 FCFA</s>", html)
        self.assertIn("&minus;25 %", html)
        self.assertIn("Tu économises 2 500 FCFA", html)
        self.assertIn("au lieu de", html)

    def test_no_promo_block_without_real_promo(self):
        html = self.sale_page().content.decode()
        self.assertEqual(html.count("Tu économises"), 1)  # seulement la robe

    @override_settings(HAYAFLASH_PROMO_DISPLAY=False)
    def test_switch_off_hides_struck_price_but_keeps_sale_price(self):
        html = self.sale_page().content.decode()
        self.assertNotIn("Tu économises", html)
        self.assertNotIn("</s>", html)
        self.assertIn("7 500", html)


class OrderPageTests(PrixBarreBase):
    def test_order_page_shows_and_uses_sale_price(self):
        r = self.order_page(self.promo)
        html = r.content.decode()
        self.assertIn("7\xa0500 FCFA", html)
        self.assertIn("10 000 FCFA</s>", html)
        self.assertIn("Tu économises 2 500 FCFA", html)
        # Le formulaire calcule le total avec le prix de la vente (celui facture).
        self.assertIn("price: 7500,", html)
        self.assertNotIn("price: 10000,", html)

    def test_order_page_without_promo_unchanged(self):
        html = self.order_page(self.plain).content.decode()
        self.assertNotIn("Tu économises", html)
        self.assertIn("price: 4000,", html)

    @override_settings(HAYAFLASH_PROMO_DISPLAY=False)
    def test_switch_off_keeps_sale_price_in_form(self):
        html = self.order_page(self.promo).content.decode()
        self.assertNotIn("Tu économises", html)
        self.assertIn("price: 7500,", html)
