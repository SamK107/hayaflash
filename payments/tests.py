from __future__ import annotations

import hashlib
import hmac
import json
import threading
from decimal import Decimal
from uuid import uuid4

from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings
from django.test.client import Client
from rest_framework.test import APIClient
from unittest import skipIf

from orders.models import Order
from orders.services.create_order import create_order
from orders.tests import LiveFlashSaleProductFixture, valid_delivery_payload
from payments.models import (
    LedgerEntry,
    LedgerEntryType,
    PaymentTransaction,
    PaymentTransactionStatus,
)


def _sign_webhook(secret: str, payload: dict) -> tuple[bytes, str]:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return raw, f"sha256={digest}"


@override_settings(PAYMENTS_WEBHOOK_SECRET="unit-test-webhook-secret")
class PaymentFlowTests(LiveFlashSaleProductFixture):
    def setUp(self) -> None:
        super().setUp()
        self.client = APIClient()
        self.raw_client = Client(enforce_csrf_checks=True)

    def _make_order(self) -> Order:
        return create_order(
            {
                "flash_sale_id": self.sale.pk,
                "customer_name": "Payer",
                "customer_phone": "+15557000001",
                "client_request_id": f"pay-req-{uuid4().hex}",
                "items": [{"product_id": self.product.pk, "quantity": 2}],
                "delivery": valid_delivery_payload(),
            }
        )

    def test_success_webhook_creates_balanced_ledger(self) -> None:
        order = self._make_order()
        cref = str(uuid4())
        r1 = self.client.post(
            "/api/v1/payments/initiate/",
            {
                "order_id": order.pk,
                "phone": "+15557000001",
                "provider": "orange_money",
                "client_reference": cref,
            },
            format="json",
        )
        self.assertEqual(r1.status_code, 201, r1.content)
        pref = r1.data["provider_reference"]
        self.assertTrue(pref)

        body = {"status": "success", "transaction_id": pref}
        raw, sig = _sign_webhook("unit-test-webhook-secret", body)
        w = self.raw_client.post(
            "/api/v1/payments/webhook/",
            data=raw,
            content_type="application/json",
            HTTP_X_PAYMENT_SIGNATURE=sig,
        )
        self.assertEqual(w.status_code, 200, w.content)

        pt = PaymentTransaction.objects.get(provider_reference=pref)
        self.assertEqual(pt.status, PaymentTransactionStatus.SUCCESS)
        rows = list(LedgerEntry.objects.filter(transaction=pt))
        self.assertEqual(len(rows), 2)
        debit = sum(r.amount for r in rows if r.entry_type == LedgerEntryType.DEBIT)
        credit = sum(r.amount for r in rows if r.entry_type == LedgerEntryType.CREDIT)
        self.assertEqual(debit, credit)
        self.assertEqual(debit, pt.amount)

    def test_double_webhook_does_not_duplicate_ledger(self) -> None:
        order = self._make_order()
        cref = str(uuid4())
        r1 = self.client.post(
            "/api/v1/payments/initiate/",
            {
                "order_id": order.pk,
                "phone": "+15557000001",
                "provider": "mtn",
                "client_reference": cref,
            },
            format="json",
        )
        pref = r1.data["provider_reference"]
        body = {"status": "success", "transaction_id": pref}
        raw, sig = _sign_webhook("unit-test-webhook-secret", body)
        self.raw_client.post(
            "/api/v1/payments/webhook/",
            data=raw,
            content_type="application/json",
            HTTP_X_PAYMENT_SIGNATURE=sig,
        )
        self.raw_client.post(
            "/api/v1/payments/webhook/",
            data=raw,
            content_type="application/json",
            HTTP_X_PAYMENT_SIGNATURE=sig,
        )
        pt = PaymentTransaction.objects.get(provider_reference=pref)
        self.assertEqual(LedgerEntry.objects.filter(transaction=pt).count(), 2)

    def test_failed_webhook_does_not_create_ledger(self) -> None:
        order = self._make_order()
        r1 = self.client.post(
            "/api/v1/payments/initiate/",
            {
                "order_id": order.pk,
                "phone": "+15557000001",
                "provider": "moov",
                "client_reference": str(uuid4()),
            },
            format="json",
        )
        pref = r1.data["provider_reference"]
        body = {"status": "failed", "transaction_id": pref}
        raw, sig = _sign_webhook("unit-test-webhook-secret", body)
        w = self.raw_client.post(
            "/api/v1/payments/webhook/",
            data=raw,
            content_type="application/json",
            HTTP_X_PAYMENT_SIGNATURE=sig,
        )
        self.assertEqual(w.status_code, 200)
        pt = PaymentTransaction.objects.get(provider_reference=pref)
        self.assertEqual(pt.status, PaymentTransactionStatus.FAILED)
        self.assertEqual(LedgerEntry.objects.filter(transaction=pt).count(), 0)

    def test_client_reference_idempotent_initiate(self) -> None:
        order = self._make_order()
        cref = str(uuid4())
        body = {
            "order_id": order.pk,
            "phone": "+15557000001",
            "provider": "orange_money",
            "client_reference": cref,
        }
        a = self.client.post("/api/v1/payments/initiate/", body, format="json")
        b = self.client.post("/api/v1/payments/initiate/", body, format="json")
        self.assertEqual(a.status_code, 201)
        self.assertEqual(b.status_code, 200)
        self.assertEqual(a.data["id"], b.data["id"])
        self.assertEqual(PaymentTransaction.objects.filter(client_reference=cref).count(), 1)

    def test_invalid_signature_rejected(self) -> None:
        order = self._make_order()
        r1 = self.client.post(
            "/api/v1/payments/initiate/",
            {
                "order_id": order.pk,
                "phone": "+15557000001",
                "provider": "orange_money",
                "client_reference": str(uuid4()),
            },
            format="json",
        )
        pref = r1.data["provider_reference"]
        payload = {"status": "success", "transaction_id": pref}
        raw = json.dumps(payload).encode("utf-8")
        w = self.raw_client.post(
            "/api/v1/payments/webhook/",
            data=raw,
            content_type="application/json",
            HTTP_X_PAYMENT_SIGNATURE="sha256=deadbeef",
        )
        self.assertEqual(w.status_code, 403)


@override_settings(PAYMENTS_MOCK_SIMULATE_FAILURE=True, PAYMENTS_WEBHOOK_SECRET="x")
class MockImmediateFailureTests(LiveFlashSaleProductFixture):
    def setUp(self) -> None:
        super().setUp()
        self.client = APIClient()

    def test_mock_failure_sets_status_without_ledger(self) -> None:
        order = create_order(
            {
                "flash_sale_id": self.sale.pk,
                "customer_name": "F",
                "customer_phone": "+15557000002",
                "client_request_id": f"fail-{uuid4().hex}",
                "items": [{"product_id": self.product.pk, "quantity": 1}],
                "delivery": valid_delivery_payload(),
            }
        )
        r1 = self.client.post(
            "/api/v1/payments/initiate/",
            {
                "order_id": order.pk,
                "phone": "+15557000002",
                "provider": "orange_money",
                "client_reference": str(uuid4()),
            },
            format="json",
        )
        self.assertEqual(r1.status_code, 201)
        pid = r1.data["id"]
        pt = PaymentTransaction.objects.get(pk=pid)
        self.assertEqual(pt.status, PaymentTransactionStatus.FAILED)
        self.assertEqual(LedgerEntry.objects.filter(transaction=pt).count(), 0)


@skipIf(connection.vendor == "sqlite", "SQLite does not support concurrency tests reliably")
@override_settings(PAYMENTS_WEBHOOK_SECRET="concurrent-webhook-secret")
class WebhookConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self) -> None:
        from django.contrib.auth import get_user_model
        from django.utils import timezone
        from datetime import timedelta

        from accounts.models import SellerProfile
        from flash_sales.models import FlashSale, FlashSaleStatus
        from products.models import Product

        User = get_user_model()
        self.api = APIClient()
        self.raw_client = Client(enforce_csrf_checks=True)

        _buyer = User.objects.create_user(phone="+15558000001", password="x")
        seller_user = User.objects.create_user(phone="+15558000002", password="x")
        seller = SellerProfile.objects.create(user=seller_user)
        now = timezone.now()
        sale = FlashSale.objects.create(
            title="Pay",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            status=FlashSaleStatus.LIVE,
            owner=seller,
        )
        product = Product.objects.create(
            flash_sale=sale,
            name="Item",
            stock_available=10, stock_initial=10,
            price=Decimal("3.00"),
        )
        self.order = create_order(
            {
                "flash_sale_id": sale.pk,
                "customer_name": "C",
                "customer_phone": "+15558000003",
                "client_request_id": f"conc-pay-{uuid4().hex}",
                "items": [{"product_id": product.pk, "quantity": 1}],
                "delivery": valid_delivery_payload(),
            }
        )

    def test_parallel_success_webhooks_single_ledger(self) -> None:
        r1 = self.api.post(
            "/api/v1/payments/initiate/",
            {
                "order_id": self.order.pk,
                "phone": "+15558000003",
                "provider": "orange_money",
                "client_reference": str(uuid4()),
            },
            format="json",
        )
        pref = r1.data["provider_reference"]
        body = {"status": "success", "transaction_id": pref}
        raw, sig = _sign_webhook("concurrent-webhook-secret", body)
        barrier = threading.Barrier(2)
        codes: list[int] = []

        def worker() -> None:
            close_old_connections()
            try:
                barrier.wait()
                c = Client(enforce_csrf_checks=True)
                resp = c.post(
                    "/api/v1/payments/webhook/",
                    data=raw,
                    content_type="application/json",
                    HTTP_X_PAYMENT_SIGNATURE=sig,
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

        self.assertTrue(all(c == 200 for c in codes), codes)
        pt = PaymentTransaction.objects.get(provider_reference=pref)
        self.assertEqual(LedgerEntry.objects.filter(transaction=pt).count(), 2)
