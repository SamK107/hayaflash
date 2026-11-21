"""SPEC_04 §13 : « Paiement par Orange Money sur … » sous le bouton Commander
(numéro du grossiste, lecture seule)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from distrib.models import ImportedProduct, ResellerInvite
from distrib.tests_catalog import make_wholesale
from distrib.tests_models import make_distributor, make_seller
from flash_sales.models import FlashSale, FlashSaleStatus
from products.models import FlashSaleProduct, Product

LINE = "Paiement par Orange Money sur"


class OrangeMoneyLineTests(TestCase):
    def setUp(self):
        cache.clear()
        self.seller = make_seller("+22370000001")
        now = timezone.now()
        self.sale = FlashSale.objects.create(
            title="Vente OM",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            status=FlashSaleStatus.LIVE,
            owner=self.seller,
        )

    def _product(self, name):
        product = Product.objects.create(
            owner=self.seller, name=name, price=Decimal("4500"),
            stock_available=5, stock_initial=5,
        )
        FlashSaleProduct.objects.create(flash_sale=self.sale, product=product)
        return product

    def _import(self, product, number):
        d = make_distributor(orange_money_number=number)
        wp = make_wholesale(d)
        invite = ResellerInvite.objects.create(
            distributor=d, display_name="Awa", phone="+22370000001",
            status=ResellerInvite.Status.ACCEPTED, seller=self.seller,
        )
        ImportedProduct.objects.create(
            wholesale_product=wp, invite=invite, product=product, allocated_qty=5
        )

    def _page(self):
        return self.client.get(f"/f/{self.sale.public_slug}/").content.decode()

    def test_number_shown_for_imported_product_only(self):
        imported = self._product("Robe importee")
        self._product("Sac maison")
        self._import(imported, "76 12 34 56")
        html = self._page()
        self.assertEqual(html.count(LINE), 1)
        self.assertIn(f"{LINE} 76 12 34 56", html)

    def test_nothing_shown_for_non_imported_product(self):
        self._product("Sac maison")
        self.assertNotIn(LINE, self._page())

    def test_nothing_shown_when_distributor_number_is_empty(self):
        self._import(self._product("Robe importee"), "")
        self.assertNotIn(LINE, self._page())
