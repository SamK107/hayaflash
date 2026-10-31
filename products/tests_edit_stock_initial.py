"""F-162 : le formulaire d'edition produit ne doit jamais modifier le stock."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from products.models import Product
from products.services.crud import attach_product_to_sale, create_product

User = get_user_model()


class ProductEditKeepsStockTests(TestCase):
    def setUp(self) -> None:
        user = User.objects.create_user(phone="+22300000111", password="x", display_name="S")
        self.seller = SellerProfile.objects.create(user=user)
        now = timezone.now()
        self.sale = FlashSale.objects.create(
            owner=self.seller, title="V", status=FlashSaleStatus.LIVE,
            start_time=now - timedelta(minutes=5), end_time=now + timedelta(hours=1),
        )
        self.product = create_product(owner=self.seller, name="Sac", price=34000, stock=5)
        attach_product_to_sale(flash_sale=self.sale, product=self.product)
        self.client.force_login(user)

    def test_edit_form_does_not_overwrite_stock_initial(self) -> None:
        url = reverse("products:edit", args=[self.sale.pk, self.product.pk])
        response = self.client.post(
            url,
            {"name": "Sac luxe", "description": "", "price": "34000",
             "stock_initial": "99", "unit": "piece", "display_order": "0"},
        )
        self.assertEqual(response.status_code, 302)
        fresh = Product.objects.get(pk=self.product.pk)
        self.assertEqual(fresh.name, "Sac luxe")  # l'edition normale fonctionne
        self.assertEqual(fresh.stock_initial, 5)
        self.assertEqual(fresh.stock_available, 5)
