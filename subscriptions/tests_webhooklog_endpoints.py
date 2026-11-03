"""F-166 : les deux routes du webhook Orange laissent la même trace dans WebhookLog.

Sans ORANGE_ML_*_URL dans le .env, le paiement part avec l'ancienne route
(/seller/abonnement/callback/). Elle posait raw_callback mais n'écrivait aucun WebhookLog
sur un succès, un échec, un doublon ou un montant incohérent.
"""

import json
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from subscriptions.models import PaymentStatus, Plan, Subscription, WebhookLog
from subscriptions.services.plans import invalidate_plan_cache
from subscriptions.tests_orange_status import STATUS_PATH, _payment, _seller, _status

ENDPOINTS = ("billing_callback_orange", "subscriptions:payment_callback")


class WebhookLogOnBothEndpointsTests(TestCase):
    def setUp(self):
        invalidate_plan_cache()
        self.addCleanup(invalidate_plan_cache)
        self.seller = _seller("+22371110088")

    def _payment(self, n):
        return _payment(self.seller, order_id=f"HF-M-WL{n:06d}", our_token=f"{n}" * 64)

    def _post(self, endpoint, payment, **body):
        payload = {"status": "SUCCESS", "notif_token": payment.notif_token, "txnid": "MP-1"}
        payload.update(body)
        return Client().post(
            reverse(endpoint), data=json.dumps(payload), content_type="application/json"
        )

    def test_confirmed_success_is_logged_as_processed(self):
        for n, endpoint in enumerate(ENDPOINTS, start=1):
            with self.subTest(endpoint=endpoint):
                p = self._payment(n)
                with patch(STATUS_PATH, return_value=_status("SUCCESS", txn_id="MP-1")):
                    resp = self._post(endpoint, p)
                self.assertEqual(resp.status_code, 200)
                p.refresh_from_db()
                self.assertEqual(p.status, PaymentStatus.SUCCESS)
                log = WebhookLog.objects.get(payment=p)
                self.assertTrue(log.processed)
                self.assertEqual((log.status, log.txn_id), ("SUCCESS", "MP-1"))
                self.assertEqual(log.raw_payload["notif_token"], p.notif_token)

    def test_failure_is_logged_as_processed(self):
        for n, endpoint in enumerate(ENDPOINTS, start=3):
            with self.subTest(endpoint=endpoint):
                p = self._payment(n)
                resp = self._post(endpoint, p, status="FAILED")
                self.assertEqual(resp.status_code, 200)
                p.refresh_from_db()
                self.assertEqual(p.status, PaymentStatus.FAILED)
                log = WebhookLog.objects.get(payment=p)
                self.assertTrue(log.processed)
                self.assertEqual(log.status, "FAILED")

    def test_duplicate_after_success_is_logged_not_reprocessed(self):
        for n, endpoint in enumerate(ENDPOINTS, start=5):
            with self.subTest(endpoint=endpoint):
                p = self._payment(n)
                with patch(STATUS_PATH, return_value=_status("SUCCESS", txn_id="MP-1")):
                    self._post(endpoint, p)
                    self._post(endpoint, p)
                self.assertEqual(WebhookLog.objects.filter(payment=p).count(), 2)
                skipped = WebhookLog.objects.get(payment=p, processed=False)
                self.assertIn("idempot", skipped.error_message.lower())
                self.assertEqual(
                    Subscription.objects.get(seller=self.seller).plan, Plan.MEDIUM
                )

    def test_amount_mismatch_is_logged_and_not_activated(self):
        for n, endpoint in enumerate(ENDPOINTS, start=7):
            with self.subTest(endpoint=endpoint):
                p = self._payment(n)
                with patch(STATUS_PATH) as check:
                    resp = self._post(endpoint, p, amount=100)
                self.assertEqual(resp.status_code, 200)
                check.assert_not_called()
                p.refresh_from_db()
                self.assertEqual(p.status, PaymentStatus.PENDING)
                log = WebhookLog.objects.get(payment=p)
                self.assertFalse(log.processed)
                self.assertIn("montant", log.error_message.lower())

    def test_legacy_route_keeps_its_own_source_in_the_audit(self):
        """La route historique reste distinguable dans l'audit (source=webhook_legacy)."""
        p = self._payment(9)
        with patch(STATUS_PATH, return_value=_status("SUCCESS", txn_id="MP-1")), patch(
            "subscriptions.services.payment.sync_orange_payment_status",
            wraps=__import__(
                "subscriptions.services.payment", fromlist=["sync_orange_payment_status"]
            ).sync_orange_payment_status,
        ) as sync:
            self._post("subscriptions:payment_callback", p)
            self._post("billing_callback_orange", self._payment(10))
        sources = [call.kwargs["source"] for call in sync.call_args_list]
        self.assertEqual(sources, ["webhook_legacy", "webhook"])
