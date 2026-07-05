from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import SellerProfile
from delivery.models import Delivery
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order, OrderStatus

User = get_user_model()


def _valid_delivery(**overrides) -> dict:
    base = {
        "address_text": "Hamdallaye ACI, Rue 312, Bamako",
        "geo_method": "manual",
    }
    base.update(overrides)
    return base


class DeliveryTestFixture(TestCase):
    def setUp(self) -> None:
        self.seller_user = User.objects.create_user(
            phone="+15550007777",
            password="x",
            display_name="Seller",
        )
        self.seller = SellerProfile.objects.create(user=self.seller_user)
        self.other_user = User.objects.create_user(
            phone="+15550008888",
            password="x",
            display_name="Other",
        )
        SellerProfile.objects.create(user=self.other_user)
        now = timezone.now()
        self.sale = FlashSale.objects.create(
            title="Drop",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            status=FlashSaleStatus.LIVE,
            owner=self.seller,
        )
        from products.models import Product

        self.product = Product.objects.create(
            flash_sale=self.sale,
            name="Widget",
            stock_available=10, stock_initial=10,
            price=Decimal("19.99"),
        )
        self.api = APIClient()

    def _order_body(self, **overrides) -> dict:
        base = {
            "flash_sale_id": self.sale.pk,
            "product_id": self.product.pk,
            "name": "Client X",
            "phone": "+15559990002",
            "quantity": 2,
            "client_request_id": str(uuid4()),
            "delivery": _valid_delivery(),
        }
        base.update(overrides)
        return base


class CreateOrderDeliveryIntegrationTests(DeliveryTestFixture):
    def test_create_order_creates_delivery_with_cod_amount(self) -> None:
        resp = self.api.post("/api/v1/orders/", self._order_body(), format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        order_id = resp.data["id"]
        order = Order.service_objects.get(pk=order_id)
        self.assertEqual(order.total_amount, Decimal("39.98"))
        delivery = Delivery.objects.get(order_id=order_id)
        self.assertEqual(delivery.cod_amount, Decimal("39.98"))
        self.assertEqual(delivery.address_text, _valid_delivery()["address_text"])
        self.assertIn("delivery_id", resp.data["delivery"])

    def test_create_order_requires_address_min_10_chars(self) -> None:
        body = self._order_body(
            delivery={"address_text": "short", "geo_method": "manual"},
        )
        resp = self.api.post("/api/v1/orders/", body, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_create_order_validates_coordinates(self) -> None:
        body = self._order_body(
            delivery={
                "address_text": "Valid address text here",
                "latitude": 999,
                "longitude": 0,
                "geo_method": "gps",
            },
        )
        resp = self.api.post("/api/v1/orders/", body, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_create_order_idempotent_returns_same_delivery(self) -> None:
        rid = str(uuid4())
        body = self._order_body(client_request_id=rid)
        r1 = self.api.post("/api/v1/orders/", body, format="json")
        r2 = self.api.post("/api/v1/orders/", body, format="json")
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.data.get("already_exists"))
        self.assertEqual(Delivery.objects.filter(order_id=r1.data["id"]).count(), 1)


class DeliveryAdvanceAPITests(DeliveryTestFixture):
    def setUp(self) -> None:
        super().setUp()
        resp = self.api.post("/api/v1/orders/", self._order_body(), format="json")
        self.assertEqual(resp.status_code, 201)
        self.order = Order.service_objects.get(pk=resp.data["id"])
        self.delivery = Delivery.objects.get(order_id=self.order.pk)

    def test_advance_delivery_start_requires_auth(self) -> None:
        resp = self.api.patch(
            f"/api/v1/delivery/{self.delivery.pk}/advance/",
            {"action": "confirm"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_seller_cannot_access_other_seller_delivery(self) -> None:
        self.api.force_authenticate(user=self.other_user)
        resp = self.api.patch(
            f"/api/v1/delivery/{self.delivery.pk}/advance/",
            {"action": "confirm"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_advance_delivery_mark_delivered_sets_cod(self) -> None:
        self.api.force_authenticate(user=self.seller_user)
        r1 = self.api.patch(
            f"/api/v1/delivery/{self.delivery.pk}/advance/",
            {"action": "confirm"},
            format="json",
        )
        self.assertEqual(r1.status_code, 200)
        r2 = self.api.patch(
            f"/api/v1/delivery/{self.delivery.pk}/advance/",
            {"action": "start_delivery", "assigned_to": "Moussa D."},
            format="json",
        )
        self.assertEqual(r2.status_code, 200)
        r3 = self.api.patch(
            f"/api/v1/delivery/{self.delivery.pk}/advance/",
            {"action": "mark_delivered", "cod_collected": True},
            format="json",
        )
        self.assertEqual(r3.status_code, 200)
        self.delivery.refresh_from_db()
        self.order.refresh_from_db()
        self.assertTrue(self.delivery.cod_collected)
        self.assertEqual(self.order.status, OrderStatus.DELIVERED)
        self.assertEqual(self.delivery.status, Delivery.Status.DELIVERED)

    def test_list_deliveries_for_seller(self) -> None:
        self.api.force_authenticate(user=self.seller_user)
        resp = self.api.get(
            f"/api/v1/delivery/?flash_sale_id={self.sale.pk}",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        self.assertIn("summary", resp.data)
