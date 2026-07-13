import threading
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient
from unittest import skipIf

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order, OrderItem
from orders.services.create_order import create_order
from products.models import Product

User = get_user_model()


def valid_delivery_payload(**overrides: object) -> dict:
    base = {
        "address_text": "Hamdallaye ACI, Rue 312, Bamako",
        "geo_method": "manual",
    }
    base.update(overrides)
    return base


def _valid_delivery(**overrides: object) -> dict:
    return valid_delivery_payload(**overrides)


class LiveFlashSaleProductFixture(TestCase):
    """Shared live flash sale + product for order API / service tests."""

    def setUp(self) -> None:
        self.buyer = User.objects.create_user(
            phone="+15550003333",
            password="x",
            display_name="Buyer",
        )
        self.seller_user = User.objects.create_user(
            phone="+15550004444",
            password="x",
            display_name="Seller",
        )
        self.seller = SellerProfile.objects.create(user=self.seller_user)
        now = timezone.now()
        self.sale = FlashSale.objects.create(
            title="Drop",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            status=FlashSaleStatus.LIVE,
            owner=self.seller,
        )
        self.product = Product.objects.create(
            flash_sale=self.sale,
            name="Widget",
            stock_available=10,
            stock_initial=10,
            price=Decimal("19.99"),
        )


class CreateOrderServiceTests(LiveFlashSaleProductFixture):
    def _payload(self, **overrides: object) -> dict:
        base = {
            "flash_sale_id": self.sale.pk,
            "customer_name": "Casey",
            "customer_phone": "+19998887777",
            "client_request_id": "req-unique-1",
            "items": [{"product_id": self.product.pk, "quantity": 2}],
            "delivery": _valid_delivery(),
        }
        base.update(overrides)
        return base

    def test_create_order_idempotent_by_client_request_id(self) -> None:
        p = self._payload()
        o1 = create_order(p)
        o2 = create_order(p)
        self.assertEqual(o1.pk, o2.pk)
        self.assertEqual(
            Order.objects.filter(client_request_id="req-unique-1").count(), 1
        )
        self.assertEqual(self.product.pk, o1.items.get().product_id)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_available, 8)

    def test_create_order_rejects_when_flash_sale_window_expired(self) -> None:
        now = timezone.now()
        self.sale.start_time = now - timedelta(hours=3)
        self.sale.end_time = now - timedelta(hours=2)
        self.sale.save()
        with self.assertRaises(ValidationError):
            create_order(self._payload(client_request_id="req-2"))

    def test_create_order_rejects_insufficient_stock(self) -> None:
        with self.assertRaises(ValidationError):
            create_order(
                self._payload(
                    client_request_id="req-3",
                    items=[{"product_id": self.product.pk, "quantity": 100}],
                )
            )

    def test_create_order_rejects_zero_stock(self) -> None:
        self.product.stock_available = 0
        self.product.save(update_fields=["stock_available"])
        self.product.save()
        with self.assertRaises(ValidationError):
            create_order(self._payload(client_request_id="req-zero"))

    def test_create_order_snapshots_name_and_price(self) -> None:
        order = create_order(self._payload(client_request_id="req-4"))
        item = order.items.get()
        self.assertEqual(item.product_name_snapshot, "Widget")
        self.assertEqual(item.price_snapshot, Decimal("19.99"))

    def test_create_order_duplicate_lines_aggregate_stock(self) -> None:
        create_order(
            self._payload(
                client_request_id="req-5",
                items=[
                    {"product_id": self.product.pk, "quantity": 3},
                    {"product_id": self.product.pk, "quantity": 2},
                ],
            )
        )
        self.assertEqual(OrderItem.objects.count(), 2)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_available, 5)

    def test_order_objects_create_is_blocked(self) -> None:
        with self.assertRaises(RuntimeError):
            Order.objects.create(
                flash_sale=self.sale,
                customer_name="X",
                customer_phone="+1",
                client_request_id="blocked",
            )


@skipIf(
    connection.vendor == "sqlite", "SQLite does not support concurrency tests reliably"
)
class CreateOrderConcurrencyTests(TransactionTestCase):
    """
    IMPORTANT:
    Ce test nécessite PostgreSQL (ou une DB supportant les transactions concurrentes).
    SQLite ne gère pas correctement les écritures concurrentes (database locking).
    """

    reset_sequences = True

    def setUp(self) -> None:
        self.seller_user = User.objects.create_user(
            phone="+15550005555",
            password="x",
            display_name="Seller",
        )
        self.seller = SellerProfile.objects.create(user=self.seller_user)
        now = timezone.now()
        self.sale = FlashSale.objects.create(
            title="Concurrent",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            status=FlashSaleStatus.LIVE,
            owner=self.seller,
        )
        self.product = Product.objects.create(
            flash_sale=self.sale,
            name="Hot",
            stock_available=1,
            stock_initial=1,
            price=Decimal("1.00"),
        )

    def _payload(self, client_request_id: str) -> dict:
        return {
            "flash_sale_id": self.sale.pk,
            "customer_name": "T",
            "customer_phone": "+1",
            "client_request_id": client_request_id,
            "items": [{"product_id": self.product.pk, "quantity": 1}],
            "delivery": _valid_delivery(),
        }

    def test_concurrent_last_unit_only_one_order_succeeds(self) -> None:
        outcomes: list[str] = []
        barrier = threading.Barrier(2)

        def worker(req_id: str) -> None:
            close_old_connections()
            try:
                barrier.wait()
                create_order(self._payload(req_id))
                outcomes.append("ok")
            except ValidationError:
                outcomes.append("err")
            finally:
                close_old_connections()

        t1 = threading.Thread(target=worker, args=("conc-a",))
        t2 = threading.Thread(target=worker, args=("conc-b",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(outcomes.count("ok"), 1)
        self.assertEqual(outcomes.count("err"), 1)
        self.assertEqual(Order.objects.count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_available, 0)


class PublicOrderAPITests(LiveFlashSaleProductFixture):
    def setUp(self) -> None:
        super().setUp()
        self.api = APIClient()

    def test_post_orders_missing_required_returns_400(self) -> None:
        resp = self.api.post("/api/v1/orders/", {}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_post_orders_happy_path_201(self) -> None:
        rid = str(uuid4())
        resp = self.api.post(
            "/api/v1/orders/",
            {
                "flash_sale_id": self.sale.pk,
                "product_id": self.product.pk,
                "name": "Client X",
                "phone": "+15559990002",
                "quantity": 2,
                "client_request_id": rid,
                "delivery": _valid_delivery(),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data.get("status"), "pending")
        self.assertTrue(Order.service_objects.filter(client_request_id=rid).exists())

    def test_api_duplicate_client_request_id_returns_same_order(self) -> None:
        rid = str(uuid4())
        body = {
            "flash_sale_id": self.sale.pk,
            "product_id": self.product.pk,
            "name": "Dup",
            "phone": "+15559990003",
            "quantity": 1,
            "client_request_id": rid,
            "delivery": _valid_delivery(),
        }
        r1 = self.api.post("/api/v1/orders/", body, format="json")
        r2 = self.api.post("/api/v1/orders/", body, format="json")
        self.assertEqual(r1.status_code, 201, r1.content)
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(r1.data.get("id"), r2.data.get("id"))
        self.assertEqual(
            Order.service_objects.filter(client_request_id=rid).count(),
            1,
        )
        oid = r1.data.get("id")
        order = Order.service_objects.get(pk=oid)
        self.assertEqual(order.items.count(), 1)


@skipIf(
    connection.vendor == "sqlite", "SQLite does not support concurrency tests reliably"
)
class PublicOrderAPIConcurrencyTests(TransactionTestCase):
    """Last-unit-safety via HTTP API (same invariants as ``create_order``)."""

    reset_sequences = True

    def setUp(self) -> None:
        self.seller_user = User.objects.create_user(
            phone="+15550006666",
            password="x",
            display_name="Seller",
        )
        self.seller = SellerProfile.objects.create(user=self.seller_user)
        now = timezone.now()
        self.sale = FlashSale.objects.create(
            title="API concurrent",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            status=FlashSaleStatus.LIVE,
            owner=self.seller,
        )
        self.product = Product.objects.create(
            flash_sale=self.sale,
            name="Solo",
            stock_available=1,
            stock_initial=1,
            price=Decimal("5.00"),
        )

    def test_concurrent_last_unit_via_api_one_201_one_400(self) -> None:
        codes: list[int] = []
        barrier = threading.Barrier(2)

        def worker() -> None:
            close_old_connections()
            try:
                barrier.wait()
                client = APIClient()
                resp = client.post(
                    "/api/v1/orders/",
                    {
                        "flash_sale_id": self.sale.pk,
                        "product_id": self.product.pk,
                        "name": "Race",
                        "phone": "+15558887777",
                        "quantity": 1,
                        "client_request_id": str(uuid4()),
                        "delivery": _valid_delivery(),
                    },
                    format="json",
                )
                codes.append(resp.status_code)
            finally:
                close_old_connections()

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(sorted(codes), [201, 400])
        self.assertEqual(Order.service_objects.count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_available, 0)
