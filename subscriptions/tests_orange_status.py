"""notif_token Orange (regularisation) et verification active du statut.

Contexte : test reel du 27/09 (paiement HF-M-D4F26BC7, txn MP260927.0039.A61409).
Orange renvoie SON notif_token a l'initiation et l'utilise dans le webhook ;
le webhook ne contient pas de montant.
"""

from __future__ import annotations

import json
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile, User
from core.models import AuditLog
from subscriptions.models import (
    PaymentProvider,
    PaymentStatus,
    Plan,
    Subscription,
    SubscriptionPayment,
)
from subscriptions.services.plans import invalidate_plan_cache

STATUS_PATH = "subscriptions.services.orange_money.get_transaction_status"
ORANGE_TOKEN = "hzdg8pgkORANGEtoken32charsXXXXXX"


def _seller(phone):
    user = User.objects.create_user(phone=phone, password="x", display_name="Vendeur")
    seller = SellerProfile.objects.create(user=user, business_name="Boutique test")
    Subscription.objects.create(seller=seller, plan=Plan.FREE)
    return seller


def _payment(seller, *, order_id="HF-M-D4F26BC7", our_token="c5d1cbae" + "0" * 56,
             raw=None, status=PaymentStatus.PENDING, created_at=None):
    raw = {"pay_token": "PAYTOKEN", "notif_token": ORANGE_TOKEN} if raw is None else raw
    p = SubscriptionPayment.objects.create(
        seller=seller,
        plan=Plan.MEDIUM,
        provider=PaymentProvider.ORANGE,
        amount=2000,
        phone="+22370000000",
        order_id=order_id,
        notif_token=our_token,
        raw_response=raw,
        status=status,
    )
    if created_at is not None:
        SubscriptionPayment.objects.filter(pk=p.pk).update(created_at=created_at)
        p.refresh_from_db()
    return p


def _status(status, **extra):
    return {"status": status, "txn_id": extra.get("txn_id", ""), "notif_token": "",
            "amount": extra.get("amount"), "raw": {"status": status}}


class _Base(TestCase):
    def setUp(self):
        invalidate_plan_cache()
        self.addCleanup(invalidate_plan_cache)
        self.seller = _seller("+22371110001")


# ── 1. Regularisation du notif_token ─────────────────────────────────────────


class RegularizeNotifTokenCommandTests(_Base):
    def _run(self, *args):
        out = StringIO()
        call_command("regularize_orange_notif_token", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_by_default_writes_nothing(self):
        p = _payment(self.seller)
        out = self._run()
        self.assertIn("SIMULATION", out)
        self.assertIn("HF-M-D4F26BC7", out)
        self.assertNotIn(ORANGE_TOKEN, out)  # jamais le token complet
        p.refresh_from_db()
        self.assertNotEqual(p.notif_token, ORANGE_TOKEN)
        self.assertFalse(AuditLog.objects.filter(action__contains="regularized").exists())

    def test_apply_copies_orange_token_audits_and_is_idempotent(self):
        p = _payment(self.seller)
        self._run("--apply")
        p.refresh_from_db()
        self.assertEqual(p.notif_token, ORANGE_TOKEN)
        self.assertEqual(p.status, PaymentStatus.PENDING)  # rien n'est active
        log = AuditLog.objects.get(action="subscription_payment.notif_token_regularized")
        self.assertEqual(log.metadata["order_id"], "HF-M-D4F26BC7")
        self.assertNotIn(ORANGE_TOKEN, json.dumps(log.metadata))
        self.assertIn("Aucun paiement", self._run("--apply"))
        self.assertEqual(AuditLog.objects.filter(action__contains="regularized").count(), 1)

    def test_only_pending_and_order_id_filter(self):
        done = _payment(self.seller, order_id="HF-M-DONE0001", status=PaymentStatus.SUCCESS,
                        raw={"notif_token": "autreTokenOrange"})
        target = _payment(self.seller, order_id="HF-M-TARGET01", our_token="b" * 64,
                          raw={"pay_token": "x", "notif_token": "tokenCible"})
        other = _payment(self.seller, order_id="HF-M-OTHER001", our_token="c" * 64,
                         raw={"pay_token": "x", "notif_token": "tokenAutre"})
        self._run("--apply", "--order-id", "HF-M-TARGET01")
        for p in (done, target, other):
            p.refresh_from_db()
        self.assertEqual(target.notif_token, "tokenCible")
        self.assertEqual(other.notif_token, "c" * 64)
        self.assertNotEqual(done.notif_token, "autreTokenOrange")

    def test_token_already_used_elsewhere_is_skipped(self):
        _payment(self.seller, order_id="HF-M-OWNER001", our_token=ORANGE_TOKEN,
                 status=PaymentStatus.SUCCESS, raw={})
        p = _payment(self.seller, order_id="HF-M-DUPLI001", our_token="d" * 64)
        out = self._run("--apply")
        self.assertIn("IGNOR", out)
        p.refresh_from_db()
        self.assertEqual(p.notif_token, "d" * 64)

    def test_after_regularization_webhook_activates(self):
        p = _payment(self.seller)
        self._run("--apply")
        Client().post(
            reverse("billing_callback_orange"),
            data=json.dumps({"status": "SUCCESS", "notif_token": ORANGE_TOKEN,
                             "txnid": "MP260927.0039.A61409"}),
            content_type="application/json",
        )
        p.refresh_from_db()
        self.assertEqual(p.status, PaymentStatus.SUCCESS)
        self.assertEqual(p.txn_id, "MP260927.0039.A61409")
        self.assertEqual(Subscription.objects.get(seller=self.seller).plan, Plan.MEDIUM)


# ── 2. Verification active (transactionstatus) ───────────────────────────────


class SyncOrangePaymentStatusTests(_Base):
    def _sync(self, payment, result=None, side_effect=None):
        from subscriptions.services.payment import sync_orange_payment_status

        with patch(STATUS_PATH, return_value=result, side_effect=side_effect) as call:
            status = sync_orange_payment_status(payment, source="test")
        return status, call

    def test_success_activates_idempotently_and_audits(self):
        p = _payment(self.seller)
        status, call = self._sync(p, _status("SUCCESS", txn_id="MP1"))
        self.assertEqual(status, "SUCCESS")
        self.assertEqual(call.call_args.kwargs, {"order_id": p.order_id, "amount": 2000, "pay_token": "PAYTOKEN"})
        p.refresh_from_db()
        self.assertEqual((p.status, p.txn_id), (PaymentStatus.SUCCESS, "MP1"))
        sub = Subscription.objects.get(seller=self.seller)
        self.assertEqual(sub.plan, Plan.MEDIUM)
        self.assertTrue(AuditLog.objects.filter(action="subscription_payment.confirmed_by_status_check").exists())

        # Webhook qui arrive ensuite : pas de seconde prolongation.
        expires = sub.expires_at
        Client().post(
            reverse("billing_callback_orange"),
            data=json.dumps({"status": "SUCCESS", "notif_token": p.notif_token, "txnid": "MP1"}),
            content_type="application/json",
        )
        self.assertEqual(Subscription.objects.get(seller=self.seller).expires_at, expires)

    def test_already_success_not_reactivated(self):
        from subscriptions.services.payment import activate_subscription_from_payment

        p = _payment(self.seller)
        activate_subscription_from_payment(p)
        expires = Subscription.objects.get(seller=self.seller).expires_at
        stale = SubscriptionPayment.objects.get(pk=p.pk)
        stale.status = PaymentStatus.PENDING  # copie en memoire perimee (course)
        activate_subscription_from_payment(stale)
        self.assertEqual(Subscription.objects.get(seller=self.seller).expires_at, expires)

    def test_pending_or_initiated_changes_nothing(self):
        for orange_status in ("PENDING", "INITIATED"):
            p = _payment(self.seller, order_id=f"HF-M-{orange_status[:8]}",
                         our_token=orange_status * 8)
            self.assertEqual(self._sync(p, _status(orange_status))[0], orange_status)
            p.refresh_from_db()
            self.assertEqual(p.status, PaymentStatus.PENDING)
        self.assertEqual(Subscription.objects.get(seller=self.seller).plan, Plan.FREE)

    def test_failed_and_expired_mark_payment(self):
        p1 = _payment(self.seller, order_id="HF-M-FAILED01", our_token="1" * 64)
        p2 = _payment(self.seller, order_id="HF-M-EXPIRE01", our_token="2" * 64)
        self._sync(p1, _status("FAILED"))
        self._sync(p2, _status("EXPIRED"))
        p1.refresh_from_db()
        p2.refresh_from_db()
        self.assertEqual((p1.status, p2.status), (PaymentStatus.FAILED, PaymentStatus.EXPIRED))

    def test_amount_mismatch_blocks_activation(self):
        p = _payment(self.seller)
        with self.assertLogs("subscriptions.services.payment", level="ERROR"):
            status, _ = self._sync(p, _status("SUCCESS", amount="100"))
        self.assertEqual(status, "AMOUNT_MISMATCH")
        p.refresh_from_db()
        self.assertEqual(p.status, PaymentStatus.PENDING)

    def test_no_pay_token_or_network_error_never_raises(self):
        no_token = _payment(self.seller, order_id="HF-M-NOTOKEN1", raw={"notif_token": "x"})
        status, call = self._sync(no_token, _status("SUCCESS"))
        self.assertEqual(status, "")
        call.assert_not_called()

        p = _payment(self.seller, order_id="HF-M-NETERR01", our_token="3" * 64)
        self.assertEqual(self._sync(p, side_effect=ConnectionError("réseau"))[0], "")
        p.refresh_from_db()
        self.assertEqual(p.status, PaymentStatus.PENDING)

    def test_non_pending_payment_not_queried(self):
        p = _payment(self.seller, status=PaymentStatus.CANCELLED)
        status, call = self._sync(p, _status("SUCCESS"))
        self.assertEqual(status, "")
        call.assert_not_called()


class BillingReturnStatusCheckTests(_Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.seller.user)

    def test_return_activates_when_orange_says_success(self):
        p = _payment(self.seller)
        with patch(STATUS_PATH, return_value=_status("SUCCESS", txn_id="MP2")):
            resp = self.client.get(f"/billing/return/?order_id={p.order_id}")
        self.assertRedirects(resp, reverse("subscriptions:subscription"), fetch_redirect_response=False)
        p.refresh_from_db()
        self.assertEqual(p.status, PaymentStatus.SUCCESS)

    def test_return_shows_pending_page_when_still_pending(self):
        p = _payment(self.seller)
        with patch(STATUS_PATH, return_value=_status("PENDING")):
            resp = self.client.get(f"/billing/return/?order_id={p.order_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "subscriptions/payment_pending.html")

    def test_return_survives_orange_outage(self):
        p = _payment(self.seller)
        with patch(STATUS_PATH, side_effect=ConnectionError("down")):
            resp = self.client.get(f"/billing/return/?order_id={p.order_id}")
        self.assertEqual(resp.status_code, 200)

    def test_legacy_return_also_checks(self):
        p = _payment(self.seller)
        with patch(STATUS_PATH, return_value=_status("SUCCESS")):
            self.client.get(reverse("subscriptions:payment_return", args=[p.pk]))
        p.refresh_from_db()
        self.assertEqual(p.status, PaymentStatus.SUCCESS)


class CheckPendingOrangePaymentsTaskTests(_Base):
    def test_checks_only_recent_pending_orange_and_continues_on_error(self):
        from subscriptions.tasks import check_pending_orange_payments

        recent = _payment(self.seller, order_id="HF-M-RECENT01", our_token="4" * 64)
        broken = _payment(self.seller, order_id="HF-M-BROKEN01", our_token="5" * 64)
        old = _payment(self.seller, order_id="HF-M-OLDONE01", our_token="6" * 64,
                       created_at=timezone.now() - timedelta(hours=25))
        _payment(self.seller, order_id="HF-M-SUCCESS1", our_token="7" * 64,
                 status=PaymentStatus.SUCCESS)

        def fake(order_id, amount, pay_token):
            if order_id == "HF-M-BROKEN01":
                raise ConnectionError("down")
            return _status("SUCCESS")

        with patch(STATUS_PATH, side_effect=fake) as call:
            counts = check_pending_orange_payments()
        called = {c.kwargs["order_id"] for c in call.call_args_list}
        self.assertEqual(called, {"HF-M-RECENT01", "HF-M-BROKEN01"})
        self.assertEqual(counts, {"SUCCESS": 1, "UNCHECKED": 1})
        for p in (recent, broken, old):
            p.refresh_from_db()
        self.assertEqual(recent.status, PaymentStatus.SUCCESS)
        self.assertEqual(broken.status, PaymentStatus.PENDING)
        self.assertEqual(old.status, PaymentStatus.PENDING)

    def test_scheduled_every_five_minutes(self):
        from django.conf import settings

        from config.settings import base

        entry = base.CELERY_BEAT_SCHEDULE["check-pending-orange-payments"]
        self.assertEqual(entry["task"], "subscriptions.check_pending_orange_payments")
        self.assertEqual(entry["schedule"], 300.0)
        self.assertTrue(settings.CELERY_TASK_ALWAYS_EAGER)


class TransactionStatusClientTests(TestCase):
    @override_settings(ORANGE_MONEY_CLIENT_ID="id", ORANGE_MONEY_CLIENT_SECRET="s")
    @patch("subscriptions.services.orange_money._get_access_token", return_value="tok")
    @patch("subscriptions.services.orange_money.requests.post")
    def test_payload_and_tls(self, post, _tok):
        from subscriptions.services.orange_money import OM_STATUS_URL, get_transaction_status

        post.return_value.status_code = 201
        post.return_value.json.return_value = {"status": "success", "txnid": "MP9", "notif_token": "n"}
        result = get_transaction_status(order_id="HF-M-1", amount=2000, pay_token="PT")
        self.assertEqual(post.call_args.args[0], OM_STATUS_URL)
        self.assertEqual(post.call_args.kwargs["json"], {"order_id": "HF-M-1", "amount": 2000, "pay_token": "PT"})
        self.assertIsInstance(post.call_args.kwargs["json"]["amount"], int)
        self.assertIs(post.call_args.kwargs["verify"], True)
        self.assertEqual((result["status"], result["txn_id"]), ("SUCCESS", "MP9"))
