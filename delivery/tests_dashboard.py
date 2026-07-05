from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from delivery.models import Delivery
from delivery.services.delivery import advance_delivery
from delivery.tests import DeliveryTestFixture, _valid_delivery
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order, OrderStatus
from orders.services.create_order import create_order
from products.models import Product

User = get_user_model()


class SellerDeliveriesDashboardTests(DeliveryTestFixture):
    def setUp(self) -> None:
        super().setUp()
        self.client = Client()
        self.dashboard_url = reverse("orders:seller_deliveries_dashboard")

    def test_deliveries_dashboard_requires_seller(self) -> None:
        resp = self.client.get(self.dashboard_url)
        self.assertEqual(resp.status_code, 302)

        buyer = User.objects.create_user(
            phone="+15550009999",
            password="x",
            display_name="Buyer only",
        )
        self.client.force_login(buyer)
        resp = self.client.get(self.dashboard_url)
        self.assertEqual(resp.status_code, 403)

    def test_deliveries_dashboard_scoped_to_seller_flash_sale(self) -> None:
        self.client.force_login(self.seller_user)
        resp = self.client.get(
            f"{self.dashboard_url}?flash_sale_id={self.sale.pk}",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.sale.title)

        other_sale = FlashSale.objects.create(
            title="Other drop",
            start_time=timezone.now() - timedelta(hours=1),
            end_time=timezone.now() + timedelta(hours=1),
            status=FlashSaleStatus.LIVE,
            owner=self.other_user.seller_profile,
        )
        resp = self.client.get(
            f"{self.dashboard_url}?flash_sale_id={other_sale.pk}",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Vente introuvable")

    def test_summary_partial_returns_cod_totals(self) -> None:
        self._create_order(client_request_id="sum-a")
        self._create_order(client_request_id="sum-b")
        order3 = self._create_order(client_request_id="sum-c")
        delivery3 = Delivery.objects.get(order=order3)
        self.client.force_login(self.seller_user)
        advance_delivery(
            user=self.seller_user,
            delivery_id=delivery3.pk,
            action="confirm",
            payload={},
        )
        advance_delivery(
            user=self.seller_user,
            delivery_id=delivery3.pk,
            action="start_delivery",
            payload={"assigned_to": "Ali"},
        )
        advance_delivery(
            user=self.seller_user,
            delivery_id=delivery3.pk,
            action="mark_delivered",
            payload={"cod_collected": True},
        )

        resp = self.client.get(
            reverse("orders:seller_deliveries_summary"),
            {"flash_sale_id": self.sale.pk},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "3")
        self.assertContains(resp, ">80<")
        self.assertContains(resp, ">40<")

    def test_list_filter_in_transit(self) -> None:
        order = self._create_order(client_request_id="filt-a")
        delivery = Delivery.objects.get(order=order)
        self.client.force_login(self.seller_user)
        advance_delivery(
            user=self.seller_user,
            delivery_id=delivery.pk,
            action="confirm",
            payload={},
        )
        advance_delivery(
            user=self.seller_user,
            delivery_id=delivery.pk,
            action="start_delivery",
            payload={"assigned_to": "Moussa"},
        )
        self._create_order(client_request_id="filt-b")

        resp = self.client.get(
            reverse("orders:seller_deliveries_list"),
            {"flash_sale_id": self.sale.pk, "status": "in_transit"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Moussa")
        self.assertNotContains(resp, "filt-b")

    def test_htmx_confirm_action_swaps_row(self) -> None:
        order = self._create_order(client_request_id="htmx-confirm")
        delivery = Delivery.objects.get(order=order)
        self.client.force_login(self.seller_user)
        resp = self.client.post(
            reverse("orders:seller_delivery_action", kwargs={"delivery_id": delivery.pk}),
            {"action": "confirm"},
        )
        self.assertEqual(resp.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CONFIRMED)

    def test_start_delivery_requires_assigned_to(self) -> None:
        order = self._create_order(client_request_id="htmx-start")
        delivery = Delivery.objects.get(order=order)
        self.client.force_login(self.seller_user)
        advance_delivery(
            user=self.seller_user,
            delivery_id=delivery.pk,
            action="confirm",
            payload={},
        )
        resp = self.client.post(
            reverse("orders:seller_delivery_action", kwargs={"delivery_id": delivery.pk}),
            {"action": "start_delivery"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_mark_delivered_sets_cod(self) -> None:
        order = self._create_order(client_request_id="htmx-delivered")
        delivery = Delivery.objects.get(order=order)
        self.client.force_login(self.seller_user)
        advance_delivery(
            user=self.seller_user,
            delivery_id=delivery.pk,
            action="confirm",
            payload={},
        )
        advance_delivery(
            user=self.seller_user,
            delivery_id=delivery.pk,
            action="start_delivery",
            payload={"assigned_to": "Driver"},
        )
        resp = self.client.post(
            reverse("orders:seller_delivery_action", kwargs={"delivery_id": delivery.pk}),
            {"action": "mark_delivered", "cod_collected": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "collecte")
        delivery.refresh_from_db()
        self.assertTrue(delivery.cod_collected)

    def _create_order(self, *, client_request_id: str) -> Order:
        return create_order(
            {
                "flash_sale_id": self.sale.pk,
                "customer_name": "Client",
                "customer_phone": "+15559990001",
                "client_request_id": client_request_id,
                "items": [{"product_id": self.product.pk, "quantity": 2}],
                "delivery": _valid_delivery(),
            }
        )
