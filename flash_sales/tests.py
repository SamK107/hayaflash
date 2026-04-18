from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from flash_sales.services.ordering import assert_flash_sale_accepts_orders
from orders.models import Order
from products.models import Product


User = get_user_model()


class FlashSaleTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            phone="+15550001111",
            password="x",
            display_name="Buyer",
        )
        self.seller_user = User.objects.create_user(
            phone="+15550002222",
            password="x",
            display_name="Seller",
        )
        self.seller = SellerProfile.objects.create(user=self.seller_user)

    def _sale(self, **kwargs) -> FlashSale:
        now = timezone.now()
        defaults = {
            "title": "Spring drop",
            "start_time": now - timedelta(hours=1),
            "end_time": now + timedelta(hours=1),
            "status": FlashSaleStatus.LIVE,
            "owner": self.seller,
        }
        defaults.update(kwargs)
        return FlashSale.objects.create(**defaults)

    def test_is_live_requires_status_and_window(self) -> None:
        now = timezone.now()
        sale = self._sale(
            status=FlashSaleStatus.DRAFT,
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
        )
        self.assertFalse(sale.is_live())

        sale.status = FlashSaleStatus.LIVE
        sale.save()
        self.assertTrue(sale.is_live())

        sale.end_time = now - timedelta(minutes=1)
        sale.save()
        self.assertFalse(sale.is_live())

    def test_open_and_close_sale(self) -> None:
        sale = self._sale(status=FlashSaleStatus.DRAFT)
        sale.open_sale()
        sale.refresh_from_db()
        self.assertEqual(sale.status, FlashSaleStatus.LIVE)

        sale.close_sale()
        sale.refresh_from_db()
        self.assertEqual(sale.status, FlashSaleStatus.CLOSED)

        with self.assertRaises(ValueError):
            sale.open_sale()

    def test_assert_flash_sale_accepts_orders_blocks_outside_live_window(self) -> None:
        now = timezone.now()
        sale = self._sale(
            status=FlashSaleStatus.LIVE,
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
        )
        with self.assertRaises(ValidationError):
            assert_flash_sale_accepts_orders(sale)

        sale.start_time = now - timedelta(minutes=5)
        sale.end_time = now + timedelta(hours=1)
        sale.save()
        assert_flash_sale_accepts_orders(sale)

        product = Product.objects.create(flash_sale=sale, name="SKU-1")
        order = Order.objects.create(product=product, buyer=self.user)
        self.assertIsNotNone(order.pk)

    def test_assert_flash_sale_accepts_orders_rejects_missing_flash_sale(self) -> None:
        product = Product.objects.create(flash_sale=None, name="Orphan")
        with self.assertRaises(ValidationError):
            assert_flash_sale_accepts_orders(product.flash_sale)
