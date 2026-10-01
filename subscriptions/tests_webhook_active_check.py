"""F-61 — defense en profondeur : un webhook SUCCESS ne suffit jamais a activer.

Les deux endpoints de notification Orange (/billing/webhook/orange/ et le
callback historique /seller/abonnement/callback/, encore utilise comme notif_url
de repli) doivent faire confirmer le paiement aupres d'Orange (transactionstatus)
avant d'activer l'abonnement. Si Orange dit autre chose que SUCCESS, ou est
injoignable : pas d'activation, mais toujours 200 OK.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from subscriptions.models import PaymentStatus, Plan, Subscription, WebhookLog
from subscriptions.services.plans import invalidate_plan_cache
from subscriptions.tests_orange_status import STATUS_PATH, _payment, _seller, _status

ENDPOINTS = ("billing_callback_orange", "subscriptions:payment_callback")


class WebhookActiveCheckTests(TestCase):
    def setUp(self):
        invalidate_plan_cache()
        self.addCleanup(invalidate_plan_cache)
        self.seller = _seller("+22371110077")
        self.payment = _payment(self.seller)

    def _post(self, endpoint, status="SUCCESS", txnid="MP-FORGED"):
        return Client().post(
            reverse(endpoint),
            data=json.dumps(
                {"status": status, "notif_token": self.payment.notif_token, "txnid": txnid}
            ),
            content_type="application/json",
        )

    def _assert_not_activated(self):
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.PENDING)
        self.assertEqual(Subscription.objects.get(seller=self.seller).plan, Plan.FREE)

    def test_forged_success_when_orange_says_pending_does_not_activate(self):
        for endpoint in ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                with patch(STATUS_PATH, return_value=_status("PENDING")) as check:
                    resp = self._post(endpoint)
                self.assertEqual(resp.status_code, 200)
                check.assert_called_once()
                self._assert_not_activated()

    def test_forged_success_when_orange_says_failed_does_not_activate(self):
        with patch(STATUS_PATH, return_value=_status("FAILED")):
            resp = self._post("billing_callback_orange")
        self.assertEqual(resp.status_code, 200)
        self.payment.refresh_from_db()
        self.assertNotEqual(self.payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(Subscription.objects.get(seller=self.seller).plan, Plan.FREE)

    def test_orange_unreachable_does_not_activate_but_answers_200(self):
        for endpoint in ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                with patch(STATUS_PATH, side_effect=TimeoutError("orange down")):
                    resp = self._post(endpoint)
                self.assertEqual(resp.status_code, 200)
                self._assert_not_activated()

    def test_unconfirmed_success_is_traced_not_processed(self):
        with patch(STATUS_PATH, return_value=_status("PENDING")):
            self._post("billing_callback_orange")
        log = WebhookLog.objects.get(payment=self.payment)
        self.assertFalse(log.processed)
        self.assertIn("Orange", log.error_message)

    def test_success_confirmed_by_orange_activates(self):
        """Chemin nominal : webhook SUCCESS + Orange confirme SUCCESS."""
        for n, endpoint in enumerate(ENDPOINTS):
            with self.subTest(endpoint=endpoint):
                p = _payment(
                    self.seller, order_id=f"HF-M-NOMINAL{n}", our_token=f"{n}" * 64
                )
                body = {"status": "SUCCESS", "notif_token": p.notif_token, "txnid": "MP-OK"}
                with patch(STATUS_PATH, return_value=_status("SUCCESS", txn_id="MP-OK")):
                    resp = Client().post(
                        reverse(endpoint), data=json.dumps(body), content_type="application/json"
                    )
                self.assertEqual(resp.status_code, 200)
                p.refresh_from_db()
                self.assertEqual((p.status, p.txn_id), (PaymentStatus.SUCCESS, "MP-OK"))
                self.assertEqual(p.raw_callback, body)
                self.assertEqual(Subscription.objects.get(seller=self.seller).plan, Plan.MEDIUM)
                if endpoint == "billing_callback_orange":
                    self.assertTrue(WebhookLog.objects.filter(payment=p, processed=True).exists())
