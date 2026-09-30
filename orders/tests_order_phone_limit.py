"""Limite de commande par numero acheteur (CGNAT : on ne limite pas finement par IP)."""

from __future__ import annotations

from uuid import uuid4

from django.conf import settings
from django.test import override_settings
from rest_framework.test import APIClient

from core.services import rate_limit
from orders.models import Order
from orders.tests import LiveFlashSaleProductFixture, _valid_delivery


@override_settings(RATELIMIT_ENABLE=True)
class OrderPhoneRateLimitTests(LiveFlashSaleProductFixture):
    def setUp(self) -> None:
        super().setUp()
        self.api = APIClient()
        self.max = settings.RATELIMIT_ORDER_PHONE[0]
        self.product.stock_available = self.product.stock_initial = 100
        self.product.save()

    def _order(self, phone: str, rid: str | None = None, ip: str = "196.200.1.1"):
        return self.api.post(
            "/api/v1/orders/",
            {
                "flash_sale_id": self.sale.pk,
                "product_id": self.product.pk,
                "name": "Client",
                "phone": phone,
                "quantity": 1,
                "client_request_id": rid or str(uuid4()),
                "delivery": _valid_delivery(),
            },
            format="json",
            REMOTE_ADDR=ip,
        )

    def test_over_limit_returns_french_json_429(self) -> None:
        for _ in range(self.max):
            self.assertEqual(self._order("+22370000001").status_code, 201)
        resp = self._order("+22370000001")
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json(), {"detail": [rate_limit.ORDER_RATE_LIMIT_MESSAGE]})
        self.assertEqual(Order.service_objects.count(), self.max)

    def test_other_phone_same_ip_is_not_impacted(self) -> None:
        for _ in range(self.max + 1):
            self._order("+22370000001")
        self.assertEqual(self._order("+22370000002").status_code, 201)

    def test_same_buyer_other_format_shares_the_quota(self) -> None:
        for _ in range(self.max):
            self._order("+22370000001")
        self.assertEqual(self._order("70 00 00 01").status_code, 429)

    def test_idempotent_replay_does_not_consume_quota(self) -> None:
        rid = str(uuid4())
        self.assertEqual(self._order("+22370000001", rid).status_code, 201)
        for _ in range(self.max + 3):
            self.assertEqual(self._order("+22370000001", rid).status_code, 200)
        self.assertEqual(self._order("+22370000001").status_code, 201)


class OrderPhoneRateLimitDisabledTests(LiveFlashSaleProductFixture):
    def test_disabled_in_test_settings(self) -> None:
        self.assertFalse(settings.RATELIMIT_ENABLE)
        self.assertFalse(rate_limit.order_phone_limited("+22370000001"))
