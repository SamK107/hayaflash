from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from products.models import Product, ProductMedia, ProductVariant, StockMovement

User = get_user_model()


class ProductModelTest(TestCase):
    def setUp(self) -> None:
        self.seller_user = User.objects.create_user(
            phone="+22300000060", password="x", display_name="SellerProduct"
        )
        self.seller = SellerProfile.objects.create(user=self.seller_user)
        now = timezone.now()
        self.sale = FlashSale.objects.create(
            owner=self.seller,
            title="Vente produits",
            start_time=now,
            end_time=now + timedelta(hours=1),
            status=FlashSaleStatus.LIVE,
        )

    def _product(self, **kwargs) -> Product:
        defaults = {
            "owner": self.seller,
            "name": "Sac a main",
            "price": Decimal("15000.00"),
            "stock_initial": 10,
            "stock_available": 10,
        }
        defaults.update(kwargs)
        return Product.objects.create(**defaults)

    def test_is_available_true_when_active_and_in_stock(self) -> None:
        product = self._product()
        self.assertTrue(product.is_available)

    def test_is_available_false_when_out_of_stock(self) -> None:
        product = self._product(stock_available=0)
        self.assertFalse(product.is_available)

    def test_is_available_false_when_inactive(self) -> None:
        product = self._product(is_active=False)
        self.assertFalse(product.is_available)

    def test_stock_percentage_computed_from_initial(self) -> None:
        product = self._product(stock_initial=20, stock_available=5)
        self.assertEqual(product.stock_percentage, 25)

    def test_stock_percentage_zero_initial_does_not_divide_by_zero(self) -> None:
        product = self._product(stock_initial=0, stock_available=0)
        self.assertEqual(product.stock_percentage, 0)

    def test_product_media_ordering(self) -> None:
        product = self._product()
        second = ProductMedia.objects.create(product=product, order=2)
        first = ProductMedia.objects.create(product=product, order=1)
        self.assertEqual(list(product.media.all()), [first, second])

    def test_product_variant_unique_together(self) -> None:
        product = self._product()
        ProductVariant.objects.create(
            product=product, type="couleur", value="rouge", stock=3
        )
        with self.assertRaises(Exception):
            ProductVariant.objects.create(
                product=product, type="couleur", value="rouge", stock=1
            )

    def test_stock_movement_str_shows_sign(self) -> None:
        product = self._product()
        movement = StockMovement.objects.create(
            product=product,
            quantity_change=-2,
            movement_type=StockMovement.MovementType.RESERVATION,
        )
        self.assertNotIn("+", str(movement))

        movement_in = StockMovement.objects.create(
            product=product,
            quantity_change=5,
            movement_type=StockMovement.MovementType.INITIAL,
        )
        self.assertIn("+5", str(movement_in))
