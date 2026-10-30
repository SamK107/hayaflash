"""Le stock d'un produit importe ne vient QUE de l'allocation du grossiste.

Regression : la grille « Publication rapide » (bulk-update -> adjust_stock) permettait a la
revendeuse de saisir librement un stock (30 affiches / 0 alloue). Le stock classique (hors
Distrib) reste, lui, librement editable par sa proprietaire.
"""

from __future__ import annotations

from decimal import Decimal

from django.urls import reverse
from rest_framework.test import APIClient

from distrib.tests_allocation import Base
from flash_sales.models import FlashSale
from products.models import Product
from products.services.crud import create_product

from datetime import timedelta
from django.utils import timezone


class ImportedStockCapTests(Base):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.sale = FlashSale.objects.create(
            owner=self.invite.seller, title="Vente",
            start_time=now - timedelta(minutes=5), end_time=now + timedelta(hours=1),
        )
        self.api = APIClient()
        self.api.force_authenticate(user=self.invite.seller.user)
        self.url = reverse("flashsaleproduct-bulk-update", kwargs={"flash_sale_pk": self.sale.pk})

    def _set_stock(self, product, stock):
        res = self.api.post(
            self.url, {"mutations": [{"product_id": product.pk, "stock": stock}]}, format="json"
        )
        self.assertEqual(res.status_code, 200, res.data)

    def test_unallocated_import_cannot_be_given_stock_by_the_reseller(self):
        imported = self.do_import(quantity=0)
        self._set_stock(imported.product, 30)
        product = Product.objects.get(pk=imported.product_id)
        self.assertEqual(product.stock_available, 0)  # pas 30
        self.assertEqual(imported.allocated_qty, 0)

    def test_allocated_import_cannot_exceed_allocation_minus_sold(self):
        imported = self.do_import(quantity=5)
        Product.objects.filter(pk=imported.product_id).update(stock_available=3)  # 2 vendues
        self._set_stock(imported.product, 30)
        self.assertEqual(Product.objects.get(pk=imported.product_id).stock_available, 3)

    def test_classic_product_stock_stays_freely_editable(self):
        product = create_product(owner=self.invite.seller, name="Classique", price=Decimal("100"), stock=1)
        self._set_stock(product, 30)
        self.assertEqual(Product.objects.get(pk=product.pk).stock_available, 30)
