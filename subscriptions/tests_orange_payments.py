"""F-42 : client Orange Money et orchestration des paiements d'abonnement.

Regles verifiees (CLAUDE.md, « Orange Money Payment Integration ») : order_id
<= 24 car., montant decide cote serveur et envoye en FCFA entiers, SSL jamais
desactive, montant du callback falsifie refuse (fail-closed), activation
idempotente, aucun secret dans les erreurs.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from accounts.models import SellerProfile
from subscriptions.models import (
    OverrideReason,
    PaymentProvider,
    PaymentStatus,
    Plan,
    SellerPriceOverride,
    Subscription,
    SubscriptionPayment,
)
from subscriptions.services import orange_money as om
from subscriptions.services import payment as pay
from subscriptions.services.plans import get_official_price, invalidate_plan_cache

User = get_user_model()
POST = "subscriptions.services.orange_money.requests.post"
OM_SETTINGS = dict(
    ORANGE_MONEY_CLIENT_ID="cid",
    ORANGE_MONEY_CLIENT_SECRET="csecret",
    ORANGE_MONEY_MERCHANT_KEY="mkey",
)


def _resp(status=200, body=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body if body is not None else {}
    r.text = text
    return r


def _seller(phone="+22372000001", plan=Plan.FREE, expires_at=None):
    user = User.objects.create_user(phone=phone, password="x", display_name="V")
    seller = SellerProfile.objects.create(user=user, business_name="Boutique")
    Subscription.objects.create(seller=seller, plan=plan, expires_at=expires_at)
    return seller


class Isolated(TestCase):
    def setUp(self):
        invalidate_plan_cache()
        self.addCleanup(invalidate_plan_cache)


# ── Client Orange Money ──────────────────────────────────────────────────────


@override_settings(**OM_SETTINGS)
class AccessTokenTests(Isolated):
    @patch(POST)
    def test_token_requested_with_client_credentials(self, post):
        post.return_value = _resp(200, {"access_token": "T0K"})
        self.assertEqual(om._get_access_token(), "T0K")
        args, kwargs = post.call_args
        self.assertEqual(args[0], om.OM_TOKEN_URL)
        self.assertEqual(kwargs["data"], {"grant_type": "client_credentials"})
        self.assertEqual(kwargs["auth"], ("cid", "csecret"))
        self.assertIn("timeout", kwargs)
        self.assertIsNot(kwargs.get("verify"), False)

    @override_settings(ORANGE_MONEY_CLIENT_ID="", ORANGE_MONEY_CLIENT_SECRET="")
    @patch(POST)
    def test_missing_credentials_never_call_the_network(self, post):
        with self.assertRaises(om.OrangeMoneyError):
            om._get_access_token()
        post.assert_not_called()

    @patch(POST)
    def test_http_error_is_reported_with_truncated_body(self, post):
        post.return_value = _resp(401, text="x" * 1000)
        with self.assertRaises(om.OrangeMoneyError) as cm:
            om._get_access_token()
        self.assertIn("401", str(cm.exception))
        self.assertLess(len(str(cm.exception)), 300)  # pas de fuite d'un corps entier


@override_settings(**OM_SETTINGS)
class InitiatePaymentTests(Isolated):
    KW = dict(
        amount=2000,
        order_id="HF-M-ABCDEF12",
        notif_token="a" * 64,
        return_url="https://x/return",
        cancel_url="https://x/cancel",
        notif_url="https://x/notify",
    )

    @patch(POST)
    @patch.object(om, "_get_access_token", return_value="tok")
    def test_payload_amount_is_whole_fcfa_and_ssl_is_verified(self, _tok, post):
        post.return_value = _resp(201, {"payment_url": "https://pay/x"})
        out = om.initiate_payment(**self.KW, reference="Boutique Été & Cie !!")
        self.assertEqual(out["payment_url"], "https://pay/x")
        _, kwargs = post.call_args
        self.assertEqual(kwargs["json"]["amount"], 2000)  # ni x100 ni /100
        self.assertIsInstance(kwargs["json"]["amount"], int)
        self.assertEqual(kwargs["json"]["currency"], "XOF")
        self.assertTrue(kwargs["verify"])
        self.assertEqual(kwargs["json"]["reference"], "Boutique Ete Cie")  # ASCII propre
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok")

    @patch(POST)
    @patch.object(om, "_get_access_token", return_value="tok")
    def test_camelcase_payment_url_is_accepted(self, _tok, post):
        post.return_value = _resp(200, {"paymentUrl": "https://pay/camel"})
        self.assertEqual(om.initiate_payment(**self.KW)["payment_url"], "https://pay/camel")

    @override_settings(ORANGE_MONEY_MERCHANT_KEY="")
    @patch(POST)
    def test_missing_merchant_key_blocks_before_network(self, post):
        with self.assertRaises(om.OrangeMoneyError):
            om.initiate_payment(**self.KW)
        post.assert_not_called()

    @patch(POST)
    @patch.object(om, "_get_access_token")
    def test_order_id_over_24_chars_is_refused_before_any_call(self, tok, post):
        with self.assertRaises(om.OrangeMoneyError) as cm:
            om.initiate_payment(**{**self.KW, "order_id": "X" * 25})
        self.assertIn("24", str(cm.exception))
        tok.assert_not_called()
        post.assert_not_called()
        # la limite exacte (24) passe la validation
        post.return_value = _resp(200, {"payment_url": "https://p"})
        tok.return_value = "t"
        om.initiate_payment(**{**self.KW, "order_id": "X" * 24})

    @patch(POST)
    @patch.object(om, "_get_access_token", return_value="tok")
    def test_orange_rejection_raises_without_payment_url(self, _tok, post):
        post.return_value = _resp(400, text="bad syntax")
        with self.assertRaises(om.OrangeMoneyError) as cm:
            om.initiate_payment(**self.KW)
        self.assertIn("400", str(cm.exception))

    @patch(POST)
    @patch.object(om, "_get_access_token", return_value="tok")
    def test_success_response_without_url_is_an_error(self, _tok, post):
        post.return_value = _resp(200, {"status": "OK"})
        with self.assertRaises(om.OrangeMoneyError):
            om.initiate_payment(**self.KW)

    @patch(POST)
    @patch.object(om, "_get_access_token", return_value="tok")
    def test_notif_token_is_not_logged_in_clear(self, _tok, post):
        post.return_value = _resp(200, {"payment_url": "https://p"})
        with self.assertLogs("subscriptions.services.orange_money", level="INFO") as cm:
            om.initiate_payment(**self.KW)
        self.assertFalse(any("a" * 64 in line for line in cm.output))


class CallbackParsingTests(Isolated):
    def test_success_statuses_and_aliases(self):
        for status in ("SUCCESS", "success", "SUCCESSFULL", "200"):
            with self.subTest(status=status):
                self.assertTrue(om.verify_callback({"status": status})["success"])
        for status in ("FAILED", "PENDING", "", None):
            with self.subTest(status=status):
                self.assertFalse(om.verify_callback({"status": status})["success"])

    def test_field_aliases(self):
        out = om.verify_callback(
            {"status": "success", "notifToken": "tok", "orderId": "HF-M-1",
             "txnId": "T1", "subscribernumber": "+223700"}
        )
        self.assertEqual(
            (out["notif_token"], out["order_id"], out["txn_id"], out["phone"]),
            ("tok", "HF-M-1", "T1", "+223700"),
        )

    def test_missing_token_gives_empty_token_never_a_guess(self):
        out = om.verify_callback({"status": "SUCCESS", "order_id": "HF-M-1"})
        self.assertEqual(out["notif_token"], "")

    def test_amount_mismatch_rules(self):
        m = om.callback_amount_mismatch
        self.assertFalse(m({}, 2000))  # absent : rien a comparer
        self.assertFalse(m({"amount": ""}, 2000))
        self.assertFalse(m({"amount": 2000}, 2000))
        self.assertFalse(m({"amount": "2 000"}, 2000))
        self.assertFalse(m({"amount": "2000,0"}, 2000))
        self.assertTrue(m({"amount": 20}, 2000))  # montant falsifie (moins)
        self.assertTrue(m({"amount": 200000}, 2000))  # x100 refuse aussi
        self.assertTrue(m({"amount": "abc"}, 2000))  # illisible : fail-closed
        self.assertTrue(m({"amount": [1]}, 2000))


@override_settings(**OM_SETTINGS)
class TransactionStatusTests(Isolated):
    @patch(POST)
    @patch.object(om, "_get_access_token", return_value="tok")
    def test_status_is_uppercased_and_request_is_exact(self, _tok, post):
        post.return_value = _resp(
            200, {"status": "success", "txnId": "TX9", "notif_token": "n", "amount": 2000}
        )
        out = om.get_transaction_status(order_id="HF-M-1", amount=2000, pay_token="PT")
        self.assertEqual(out["status"], "SUCCESS")
        self.assertEqual(out["txn_id"], "TX9")
        _, kwargs = post.call_args
        self.assertEqual(
            kwargs["json"], {"order_id": "HF-M-1", "amount": 2000, "pay_token": "PT"}
        )
        self.assertTrue(kwargs["verify"])

    @patch(POST)
    @patch.object(om, "_get_access_token", return_value="tok")
    def test_missing_status_is_empty_string(self, _tok, post):
        post.return_value = _resp(200, {})
        out = om.get_transaction_status(order_id="HF-M-1", amount=2000, pay_token="PT")
        self.assertEqual(out["status"], "")
        self.assertIsNone(out["amount"])

    @patch(POST)
    @patch.object(om, "_get_access_token", return_value="tok")
    def test_http_error_raises(self, _tok, post):
        post.return_value = _resp(500, text="down")
        with self.assertRaises(om.OrangeMoneyError):
            om.get_transaction_status(order_id="HF-M-1", amount=2000, pay_token="PT")


class SafeReferenceTests(Isolated):
    def test_strips_accents_symbols_and_truncates(self):
        self.assertEqual(om._safe_reference("Café  déjà-vu_1 <script>"), "Cafe deja-vu_1 script")
        self.assertEqual(len(om._safe_reference("A" * 100)), om.OM_REFERENCE_MAX_LEN)
        self.assertEqual(om._safe_reference("éèà"), "eea")


# ── Orchestration (payment.py) ───────────────────────────────────────────────


class IdentifierTests(Isolated):
    def test_order_id_format_length_and_uniqueness(self):
        ids = {pay._generate_order_id(Plan.MEDIUM) for _ in range(200)}
        self.assertEqual(len(ids), 200)
        for oid in ids:
            self.assertTrue(oid.startswith("HF-M-"))
            self.assertLessEqual(len(oid), 24)
        self.assertTrue(pay._generate_order_id(Plan.PRO).startswith("HF-P-"))

    def test_order_id_over_limit_raises(self):
        with self.assertRaises(ValueError):
            pay._generate_order_id(Plan.MEDIUM, max_length=5)

    def test_notif_token_is_64_hex_and_random(self):
        a, b = pay._generate_notif_token(), pay._generate_notif_token()
        self.assertNotEqual(a, b)
        self.assertRegex(a, r"^[0-9a-f]{64}$")


class UrlTests(Isolated):
    def setUp(self):
        super().setUp()
        self.request = RequestFactory().get("/", HTTP_HOST="testserver")
        self.payment = SubscriptionPayment(order_id="HF-M-ABC12345")
        self.payment.pk = uuid4()

    @override_settings(
        ORANGE_MONEY_RETURN_URL="https://hf.example/billing/return/",
        ORANGE_MONEY_CANCEL_URL="https://hf.example/billing/cancel/?a=1",
        ORANGE_MONEY_NOTIFY_URL="https://hf.example/billing/webhook/orange/",
    )
    def test_explicit_urls_carry_order_id_and_notify_is_untouched(self):
        ret, cancel, notif = pay._om_urls(self.request, self.payment)
        self.assertEqual(ret, "https://hf.example/billing/return/?order_id=HF-M-ABC12345")
        self.assertEqual(cancel, "https://hf.example/billing/cancel/?a=1&order_id=HF-M-ABC12345")
        self.assertEqual(notif, "https://hf.example/billing/webhook/orange/")

    @override_settings(
        ORANGE_MONEY_RETURN_URL="", ORANGE_MONEY_CANCEL_URL="", ORANGE_MONEY_NOTIFY_URL="",
        ORANGE_MONEY_BASE_URL="https://public.example/",
    )
    def test_base_url_is_used_instead_of_localhost(self):
        ret, cancel, notif = pay._om_urls(self.request, self.payment)
        for url in (ret, cancel, notif):
            self.assertTrue(url.startswith("https://public.example/"), url)
            self.assertNotIn("testserver", url)

    @override_settings(
        ORANGE_MONEY_RETURN_URL="", ORANGE_MONEY_CANCEL_URL="", ORANGE_MONEY_NOTIFY_URL="",
        ORANGE_MONEY_BASE_URL="",
    )
    def test_falls_back_to_request_host(self):
        _, _, notif = pay._om_urls(self.request, self.payment)
        self.assertTrue(notif.startswith("http://testserver/"), notif)


class CreatePaymentTests(Isolated):
    INIT = "subscriptions.services.orange_money.initiate_payment"

    def setUp(self):
        super().setUp()
        self.seller = _seller()
        self.request = RequestFactory().get("/", HTTP_HOST="testserver")

    def _create(self, plan=Plan.MEDIUM, **kw):
        return pay.create_orange_payment(
            seller=self.seller, plan=plan, phone="+22370000000", request=self.request
        )

    def test_free_or_unknown_plan_is_refused_without_a_row(self):
        for plan in (Plan.FREE, "gold"):
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                self._create(plan)
        self.assertFalse(SubscriptionPayment.objects.exists())

    def test_inactive_plan_is_refused(self):
        with patch.object(pay, "is_plan_active", return_value=False):
            with self.assertRaises(pay.PaymentNotAllowed):
                self._create()
        self.assertFalse(SubscriptionPayment.objects.exists())

    def test_amount_comes_from_server_and_token_is_stored_before_call(self):
        seen = {}

        def fake(**kwargs):
            # Au moment de l'appel Orange, le paiement existe deja en base avec
            # le notif_token envoye (regle « stocke AVANT redirection »).
            row = SubscriptionPayment.objects.get(order_id=kwargs["order_id"])
            seen["stored_token"] = row.notif_token
            seen["sent_token"] = kwargs["notif_token"]
            seen["amount"] = kwargs["amount"]
            return {"payment_url": "https://pay/x", "raw": {"pay_token": "PT"}}

        with patch(self.INIT, side_effect=fake):
            payment = self._create(Plan.MEDIUM)
        self.assertEqual(seen["stored_token"], seen["sent_token"])
        self.assertEqual(seen["amount"], get_official_price(Plan.MEDIUM))
        self.assertEqual(payment.amount, get_official_price(Plan.MEDIUM))
        self.assertEqual(payment.status, PaymentStatus.PENDING)
        self.assertEqual(payment.payment_url, "https://pay/x")

    def test_orange_notif_token_replaces_ours(self):
        result = {"payment_url": "https://p", "raw": {"notif_token": " ORANGETOK "}}
        with patch(self.INIT, return_value=result):
            payment = self._create()
        payment.refresh_from_db()
        self.assertEqual(payment.notif_token, "ORANGETOK")

    def test_initiation_failure_marks_payment_failed_and_reraises(self):
        with patch(self.INIT, side_effect=om.OrangeMoneyError("HTTP 400")):
            with self.assertRaises(om.OrangeMoneyError):
                self._create()
        row = SubscriptionPayment.objects.get()
        self.assertEqual(row.status, PaymentStatus.FAILED)
        self.assertEqual(row.raw_response, {"error": "HTTP 400"})

    def _override(self, **kw):
        return SellerPriceOverride.objects.create(
            seller=self.seller,
            plan=Plan.MEDIUM,
            price=100,
            reason=OverrideReason.TEST,
            expires_at=timezone.now() + timedelta(days=5),
            **kw,
        )

    def test_special_price_is_refused_on_active_paid_subscription(self):
        self._override()
        Subscription.objects.filter(seller=self.seller).update(
            plan=Plan.PRO, expires_at=timezone.now() + timedelta(days=10)
        )
        with patch(self.INIT) as init:
            with self.assertRaises(pay.PaymentNotAllowed):
                self._create(Plan.MEDIUM)
        init.assert_not_called()
        self.assertFalse(SubscriptionPayment.objects.exists())

    def test_special_price_reference_and_flags(self):
        override = self._override()
        captured = {}

        def fake(**kwargs):
            captured.update(kwargs)
            return {"payment_url": "https://p", "raw": {}}

        with patch(self.INIT, side_effect=fake):
            payment = self._create(Plan.MEDIUM)
        self.assertEqual(captured["amount"], 100)
        self.assertTrue(captured["reference"].endswith("SPECIAL"))
        self.assertTrue(payment.is_special_price)
        self.assertEqual(payment.price_override_id, override.pk)


class ActivationTests(Isolated):
    def setUp(self):
        super().setUp()
        self.seller = _seller()

    def _payment(self, plan=Plan.MEDIUM, override=None):
        return SubscriptionPayment.objects.create(
            seller=self.seller,
            plan=plan,
            provider=PaymentProvider.ORANGE,
            amount=2000,
            phone="+223",
            order_id=f"HF-{plan[0].upper()}-{SubscriptionPayment.objects.count():08d}",
            notif_token=f"{SubscriptionPayment.objects.count():064d}",
            price_override=override,
            is_special_price=override is not None,
        )

    def test_activation_is_idempotent_and_never_extends_twice(self):
        p = self._payment()
        sub1 = pay.activate_subscription_from_payment(p)
        first_expiry = sub1.expires_at
        p2 = SubscriptionPayment.objects.get(pk=p.pk)  # 2e livraison (webhook rejoue)
        sub2 = pay.activate_subscription_from_payment(p2)
        self.assertEqual(sub2.expires_at, first_expiry)
        self.assertEqual(p2.status, PaymentStatus.SUCCESS)

    def test_same_plan_renewal_extends_from_current_expiry(self):
        current = timezone.now() + timedelta(days=10)
        Subscription.objects.filter(seller=self.seller).update(
            plan=Plan.MEDIUM, expires_at=current
        )
        sub = pay.activate_subscription_from_payment(self._payment(Plan.MEDIUM))
        self.assertGreater(sub.expires_at, current + timedelta(days=25))

    def test_plan_change_starts_from_now(self):
        Subscription.objects.filter(seller=self.seller).update(
            plan=Plan.MEDIUM, expires_at=timezone.now() + timedelta(days=100)
        )
        sub = pay.activate_subscription_from_payment(self._payment(Plan.PRO))
        self.assertEqual(sub.plan, Plan.PRO)
        self.assertLess(sub.expires_at, timezone.now() + timedelta(days=40))

    def _override(self, **kw):
        return SellerPriceOverride.objects.create(
            seller=self.seller,
            plan=Plan.MEDIUM,
            price=100,
            reason=OverrideReason.TEST,
            expires_at=timezone.now() + timedelta(days=5),
            **kw,
        )

    def test_special_price_counts_use_and_custom_duration(self):
        override = self._override(duration_days=3)
        sub = pay.activate_subscription_from_payment(self._payment(override=override))
        override.refresh_from_db()
        self.assertEqual(override.uses_count, 1)
        self.assertLess(sub.expires_at, timezone.now() + timedelta(days=4))

    def test_exhausted_override_still_activates_paid_payment_but_alerts(self):
        override = self._override(max_uses=1)
        SellerPriceOverride.objects.filter(pk=override.pk).update(uses_count=1)
        p = self._payment(override=override)
        with self.assertLogs("subscriptions.services.payment", level="ERROR") as cm:
            sub = pay.activate_subscription_from_payment(p)
        self.assertTrue(any("epuise" in line for line in cm.output))
        self.assertEqual(sub.plan, Plan.MEDIUM)  # le vendeur a paye : activation

    def test_special_payment_never_alters_an_active_paid_subscription(self):
        override = self._override()
        current = timezone.now() + timedelta(days=50)
        Subscription.objects.filter(seller=self.seller).update(
            plan=Plan.PRO, expires_at=current
        )
        with self.assertLogs("subscriptions.services.payment", level="ERROR"):
            sub = pay.activate_subscription_from_payment(self._payment(override=override))
        self.assertEqual(sub.plan, Plan.PRO)
        self.assertEqual(sub.expires_at, current)

    def test_cancel_only_affects_pending_payments(self):
        pending = self._payment()
        pay.cancel_payment(pending)
        pending.refresh_from_db()
        self.assertEqual(pending.status, PaymentStatus.CANCELLED)

        done = self._payment(Plan.PRO)
        pay.activate_subscription_from_payment(done)
        pay.cancel_payment(done)
        done.refresh_from_db()
        self.assertEqual(done.status, PaymentStatus.SUCCESS)  # jamais annule apres coup


class SyncStatusTests(Isolated):
    STATUS = "subscriptions.services.orange_money.get_transaction_status"

    def setUp(self):
        super().setUp()
        self.seller = _seller()

    def _payment(self, **kw):
        defaults = dict(
            seller=self.seller, plan=Plan.MEDIUM, provider=PaymentProvider.ORANGE,
            amount=2000, phone="+223", order_id="HF-M-SYNC0001", notif_token="s" * 64,
            raw_response={"pay_token": "PT"},
        )
        defaults.update(kw)
        return SubscriptionPayment.objects.create(**defaults)

    def _result(self, status, amount=None, txn_id=""):
        return {"status": status, "txn_id": txn_id, "notif_token": "", "amount": amount,
                "raw": {}}

    def test_success_with_forged_amount_never_activates(self):
        p = self._payment()
        with patch(self.STATUS, return_value=self._result("SUCCESS", amount=20)):
            with self.assertLogs("subscriptions.services.payment", level="ERROR"):
                out = pay.sync_orange_payment_status(p, source="test")
        self.assertEqual(out, "AMOUNT_MISMATCH")
        p.refresh_from_db()
        self.assertEqual(p.status, PaymentStatus.PENDING)
        self.assertEqual(Subscription.objects.get(seller=self.seller).plan, Plan.FREE)

    def test_success_without_amount_activates_once_and_records_txn(self):
        p = self._payment()
        with patch(self.STATUS, return_value=self._result("SUCCESS", txn_id="TX1")):
            self.assertEqual(pay.sync_orange_payment_status(p, source="return"), "SUCCESS")
        p.refresh_from_db()
        self.assertEqual((p.status, p.txn_id), (PaymentStatus.SUCCESS, "TX1"))
        expiry = Subscription.objects.get(seller=self.seller).expires_at
        # 2e verification (page rechargee) : paiement plus pending -> rien n'est appele
        with patch(self.STATUS) as status:
            self.assertEqual(pay.sync_orange_payment_status(p, source="return"), "")
        status.assert_not_called()
        self.assertEqual(Subscription.objects.get(seller=self.seller).expires_at, expiry)

    def test_failed_and_expired_map_to_local_statuses(self):
        for orange, local, order in (
            ("FAILED", PaymentStatus.FAILED, "HF-M-F0000001"),
            ("EXPIRED", PaymentStatus.EXPIRED, "HF-M-E0000001"),
        ):
            with self.subTest(orange=orange):
                p = self._payment(order_id=order, notif_token=orange[0] * 64)
                with patch(self.STATUS, return_value=self._result(orange)):
                    self.assertEqual(pay.sync_orange_payment_status(p, source="t"), orange)
                p.refresh_from_db()
                self.assertEqual(p.status, local)
        self.assertEqual(Subscription.objects.get(seller=self.seller).plan, Plan.FREE)

    def test_failure_never_overwrites_a_payment_confirmed_meanwhile(self):
        p = self._payment()

        def confirmed_by_webhook_meanwhile(**_):
            SubscriptionPayment.objects.filter(pk=p.pk).update(status=PaymentStatus.SUCCESS)
            return self._result("FAILED")

        with patch(self.STATUS, side_effect=confirmed_by_webhook_meanwhile):
            pay.sync_orange_payment_status(p, source="t")
        p.refresh_from_db()
        self.assertEqual(p.status, PaymentStatus.SUCCESS)

    def test_still_pending_changes_nothing(self):
        p = self._payment()
        with patch(self.STATUS, return_value=self._result("PENDING")):
            self.assertEqual(pay.sync_orange_payment_status(p, source="t"), "PENDING")
        p.refresh_from_db()
        self.assertEqual(p.status, PaymentStatus.PENDING)

    def test_network_error_is_swallowed(self):
        p = self._payment()
        with patch(self.STATUS, side_effect=om.OrangeMoneyError("down")):
            with self.assertLogs("subscriptions.services.payment", level="WARNING"):
                self.assertEqual(pay.sync_orange_payment_status(p, source="t"), "")

    def test_missing_pay_token_or_other_provider_is_skipped(self):
        no_token = self._payment(raw_response={})
        with patch(self.STATUS) as status:
            with self.assertLogs("subscriptions.services.payment", level="WARNING"):
                self.assertEqual(pay.sync_orange_payment_status(no_token, source="t"), "")
            other = self._payment(
                order_id="HF-M-OTHER001", notif_token="o" * 64,
                provider=PaymentProvider.MOOV,
            )
            self.assertEqual(pay.sync_orange_payment_status(other, source="t"), "")
        status.assert_not_called()
