"""F-42 : comportements des services de paiement (ledger, initiation, webhook).

Chaque test verifie une regle metier ou de securite (idempotence, montant
falsifie, webhook invalide, transitions d'etat interdites), pas seulement le
passage sur une ligne.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import override_settings
from django.test.client import Client
from rest_framework.test import APIClient

from orders.models import Order, OrderStatus
from orders.services.create_order import create_order
from orders.tests import LiveFlashSaleProductFixture, valid_delivery_payload
from payments.models import (
    LedgerAccount,
    LedgerEntry,
    LedgerEntryType,
    PaymentTransaction,
    PaymentTransactionStatus,
)
from payments.services.ledger import (
    append_balanced_entries_for_success,
    ledger_balanced_for_payment,
)
from payments.services.payments import (
    initiate_payment_for_order,
    order_payable_total,
    payment_public_snapshot,
)
from payments.services.webhooks import (
    WebhookProcessingError,
    apply_provider_webhook,
    parse_webhook_json,
    verify_webhook_signature,
)

SECRET = "unit-test-webhook-secret"
PHONE = "+15557000001"


def _sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _body(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


@override_settings(PAYMENTS_WEBHOOK_SECRET=SECRET, PAYMENTS_MOCK_SIMULATE_FAILURE=False)
class PaymentsBase(LiveFlashSaleProductFixture):
    def setUp(self):
        super().setUp()
        self.product.stock_available = self.product.stock_initial = 1000
        self.product.save()

    def make_order(self, quantity=2, phone=PHONE) -> Order:
        return create_order(
            {
                "flash_sale_id": self.sale.pk,
                "customer_name": "Payer",
                "customer_phone": phone,
                "client_request_id": f"req-{uuid4().hex}",
                "items": [{"product_id": self.product.pk, "quantity": quantity}],
                "delivery": valid_delivery_payload(),
            }
        )

    def make_pending(self, **kw) -> PaymentTransaction:
        order = self.make_order(**kw)
        pt, _ = initiate_payment_for_order(
            order_id=order.pk, phone=PHONE, provider="orange_money"
        )
        return pt

    def send(self, payload: dict, *, signature: str | None = "auto") -> PaymentTransaction:
        raw = _body(payload)
        sig = _sign(raw) if signature == "auto" else signature
        return apply_provider_webhook(raw_body=raw, signature_header=sig)


class LedgerTests(PaymentsBase):
    def test_append_is_idempotent_and_balanced(self):
        pt = self.make_pending()
        append_balanced_entries_for_success(pt)
        append_balanced_entries_for_success(pt)  # rejeu : aucun doublon
        entries = list(LedgerEntry.objects.filter(transaction=pt))
        self.assertEqual(len(entries), 2)
        by_type = {e.entry_type: e for e in entries}
        self.assertEqual(by_type[LedgerEntryType.DEBIT].account, LedgerAccount.USER_WALLET)
        self.assertEqual(
            by_type[LedgerEntryType.CREDIT].account, LedgerAccount.PLATFORM_COMMISSION
        )
        self.assertTrue(ledger_balanced_for_payment(pt))

    def test_no_entries_is_not_balanced(self):
        self.assertFalse(ledger_balanced_for_payment(self.make_pending()))

    def test_tampered_amount_breaks_balance(self):
        pt = self.make_pending()
        append_balanced_entries_for_success(pt)
        credit = LedgerEntry.objects.get(transaction=pt, entry_type=LedgerEntryType.CREDIT)
        LedgerEntry.objects.filter(pk=credit.pk).update(amount=credit.amount - 1)
        self.assertFalse(ledger_balanced_for_payment(pt))

    def test_balanced_entries_not_matching_transaction_amount_are_rejected(self):
        pt = self.make_pending()
        append_balanced_entries_for_success(pt)
        # debit == credit, mais differents du montant du paiement (montant falsifie)
        LedgerEntry.objects.filter(transaction=pt).update(amount=Decimal("1"))
        self.assertFalse(ledger_balanced_for_payment(pt))

    def test_extra_entry_is_not_balanced(self):
        pt = self.make_pending()
        append_balanced_entries_for_success(pt)
        LedgerEntry.objects.create(
            transaction=pt,
            entry_type=LedgerEntryType.DEBIT,
            amount=Decimal("1"),
            account=LedgerAccount.USER_WALLET,
        )
        self.assertFalse(ledger_balanced_for_payment(pt))


class InitiatePaymentTests(PaymentsBase):
    def test_amount_is_computed_server_side_from_price_snapshots(self):
        order = self.make_order(quantity=2)
        self.assertEqual(order_payable_total(order), Decimal("3998"))  # 2 x 1999
        pt, meta = initiate_payment_for_order(
            order_id=order.pk, phone=PHONE, provider="orange_money"
        )
        self.assertEqual(pt.amount, Decimal("3998"))
        self.assertEqual(pt.currency, "XOF")
        self.assertEqual(pt.status, PaymentTransactionStatus.PENDING)
        self.assertNotIn("idempotent_replay", meta)

    def test_client_supplied_amount_is_ignored_via_api(self):
        order = self.make_order(quantity=2)
        resp = APIClient().post(
            "/api/v1/payments/initiate/",
            {
                "order_id": order.pk,
                "phone": PHONE,
                "provider": "orange_money",
                "amount": 1,  # montant falsifie par le client
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(
            PaymentTransaction.objects.get(order=order).amount, Decimal("3998")
        )

    def test_phone_spaces_are_normalized(self):
        order = self.make_order(phone="+15557000001")
        pt, _ = initiate_payment_for_order(
            order_id=order.pk, phone=" +1555 700 0001 ", provider="mtn"
        )
        self.assertEqual(pt.payer_phone, "+15557000001")

    def test_phone_not_matching_order_is_refused(self):
        order = self.make_order()
        with self.assertRaises(ValidationError) as cm:
            initiate_payment_for_order(
                order_id=order.pk, phone="+15559999999", provider="mtn"
            )
        self.assertIn("phone", cm.exception.message_dict)
        self.assertFalse(PaymentTransaction.objects.exists())

    def test_non_pending_order_cannot_be_paid(self):
        order = self.make_order()
        Order.objects.filter(pk=order.pk).update(status=OrderStatus.CANCELLED)
        with self.assertRaises(ValidationError) as cm:
            initiate_payment_for_order(order_id=order.pk, phone=PHONE, provider="mtn")
        self.assertIn("Only pending orders", str(cm.exception))
        self.assertFalse(PaymentTransaction.objects.exists())

    def test_unknown_order_refused(self):
        with self.assertRaises(ValidationError) as cm:
            initiate_payment_for_order(order_id=999999, phone=PHONE, provider="mtn")
        self.assertIn("order_id", cm.exception.message_dict)

    def test_zero_total_order_refused(self):
        order = self.make_order()
        order.items.update(price_snapshot=Decimal("0"))
        with self.assertRaises(ValidationError) as cm:
            initiate_payment_for_order(order_id=order.pk, phone=PHONE, provider="mtn")
        self.assertIn("greater than zero", str(cm.exception))

    def test_invalid_inputs_are_rejected_before_any_write(self):
        order = self.make_order()
        bad_calls = [
            {"order_id": 0, "phone": PHONE, "provider": "mtn"},
            {"order_id": "1", "phone": PHONE, "provider": "mtn"},
            {"order_id": order.pk, "phone": "  ", "provider": "mtn"},
            {"order_id": order.pk, "phone": 123, "provider": "mtn"},
            {"order_id": order.pk, "phone": PHONE, "provider": None},
            {"order_id": order.pk, "phone": PHONE, "provider": "paypal"},
            {"order_id": order.pk, "phone": PHONE, "provider": "mtn", "client_reference": "pas-un-uuid"},
            {"order_id": order.pk, "phone": PHONE, "provider": "mtn", "client_reference": 42},
        ]
        for kwargs in bad_calls:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                initiate_payment_for_order(**kwargs)
        self.assertFalse(PaymentTransaction.objects.exists())

    def test_boolean_order_id_is_rejected_by_type_validation(self):
        """F-50 : `true` (JSON) est un int en Python et ciblait la commande n° 1."""
        self.make_order()
        for value in (True, False):
            with self.subTest(value=value), self.assertRaises(ValidationError) as cm:
                initiate_payment_for_order(order_id=value, phone=PHONE, provider="mtn")
            # refuse par la validation de type, pas par un « Order not found »
            self.assertEqual(
                cm.exception.message_dict["order_id"], ["Must be a positive integer."]
            )
        self.assertFalse(PaymentTransaction.objects.exists())

    def test_boolean_order_id_is_rejected_via_api(self):
        self.make_order()
        resp = APIClient().post(
            "/api/v1/payments/initiate/",
            {"order_id": True, "phone": PHONE, "provider": "mtn"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("Must be a positive integer", json.dumps(resp.json()))

    def test_client_reference_accepts_uuid_object_and_replays(self):
        order = self.make_order()
        ref = uuid4()
        first, _ = initiate_payment_for_order(
            order_id=order.pk, phone=PHONE, provider="mtn", client_reference=ref
        )
        again, meta = initiate_payment_for_order(
            order_id=order.pk, phone=PHONE, provider="mtn", client_reference=ref
        )
        self.assertEqual(first.pk, again.pk)
        self.assertTrue(meta["idempotent_replay"])
        self.assertEqual(PaymentTransaction.objects.count(), 1)

    def test_concurrent_duplicate_client_reference_returns_existing_row(self):
        """Course : la ligne apparait entre le SELECT et le INSERT -> rejeu, pas d'erreur."""
        order = self.make_order()
        ref = uuid4()
        original_create = PaymentTransaction.objects.create

        def racing_create(**kwargs):
            # L'autre requete a gagne la course : sa ligne existe deja.
            original_create(**{**kwargs, "provider_reference": "raced-1"})
            raise IntegrityError("duplicate client_reference")

        with patch.object(PaymentTransaction.objects, "create", side_effect=racing_create):
            pt, meta = initiate_payment_for_order(
                order_id=order.pk, phone=PHONE, provider="mtn", client_reference=ref
            )
        self.assertTrue(meta["idempotent_replay"])
        self.assertEqual(pt.client_reference, ref)
        self.assertEqual(PaymentTransaction.objects.count(), 1)

    def test_integrity_error_without_client_reference_is_not_swallowed(self):
        order = self.make_order()
        with patch.object(
            PaymentTransaction.objects, "create", side_effect=IntegrityError("boom")
        ):
            with self.assertRaises(IntegrityError):
                initiate_payment_for_order(order_id=order.pk, phone=PHONE, provider="mtn")

    def test_public_snapshot_does_not_leak_payer_phone(self):
        pt = self.make_pending()
        snap = payment_public_snapshot(pt)
        self.assertEqual(snap["amount"], "3998")
        self.assertNotIn("payer_phone", snap)
        self.assertNotIn(PHONE, json.dumps(snap))


class WebhookSignatureTests(PaymentsBase):
    def test_valid_signature_passes(self):
        raw = b'{"a":1}'
        verify_webhook_signature(SECRET, raw, _sign(raw))  # ne leve pas

    def test_missing_secret_is_misconfigured_and_refuses(self):
        with self.assertRaises(WebhookProcessingError) as cm:
            verify_webhook_signature("", b"{}", "sha256=abc")
        self.assertEqual(cm.exception.code, "misconfigured")

    def test_missing_header_refused(self):
        with self.assertRaises(WebhookProcessingError) as cm:
            verify_webhook_signature(SECRET, b"{}", None)
        self.assertEqual(cm.exception.code, "signature")

    def test_wrong_prefix_refused(self):
        raw = b"{}"
        digest = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
        with self.assertRaises(WebhookProcessingError) as cm:
            verify_webhook_signature(SECRET, raw, digest)  # sans « sha256= »
        self.assertEqual(cm.exception.code, "signature")

    def test_signature_from_another_secret_refused(self):
        raw = b"{}"
        with self.assertRaises(WebhookProcessingError) as cm:
            verify_webhook_signature(SECRET, raw, _sign(raw, "autre-secret"))
        self.assertEqual(cm.exception.code, "signature")

    def test_body_altered_after_signing_is_refused(self):
        """Montant / statut falsifie apres signature : la signature ne correspond plus."""
        pt = self.make_pending()
        good = _body({"status": "failed", "transaction_id": pt.provider_reference})
        sig = _sign(good)
        forged = _body({"status": "success", "transaction_id": pt.provider_reference})
        with self.assertRaises(WebhookProcessingError) as cm:
            apply_provider_webhook(raw_body=forged, signature_header=sig)
        self.assertEqual(cm.exception.code, "signature")
        pt.refresh_from_db()
        self.assertEqual(pt.status, PaymentTransactionStatus.PENDING)
        self.assertFalse(LedgerEntry.objects.exists())

    @override_settings(PAYMENTS_WEBHOOK_SECRET="")
    def test_unconfigured_secret_blocks_the_whole_webhook(self):
        pt = self.make_pending()
        raw = _body({"status": "success", "transaction_id": pt.provider_reference})
        with self.assertRaises(WebhookProcessingError) as cm:
            apply_provider_webhook(raw_body=raw, signature_header=_sign(raw, ""))
        self.assertEqual(cm.exception.code, "misconfigured")
        pt.refresh_from_db()
        self.assertEqual(pt.status, PaymentTransactionStatus.PENDING)


class WebhookPayloadTests(PaymentsBase):
    def test_parse_rejects_bad_json_encoding_and_non_object(self):
        for raw in (b"\xff\xfe", b"{pas json", b"[1,2]", b'"texte"'):
            with self.subTest(raw=raw), self.assertRaises(WebhookProcessingError):
                parse_webhook_json(raw)
        self.assertEqual(parse_webhook_json(b'{"a": 1}'), {"a": 1})

    def test_signed_but_malformed_payloads_do_not_touch_payments(self):
        pt = self.make_pending()
        cases = [
            b"pas json",  # JSON invalide (mais correctement signe)
            _body([pt.provider_reference]),  # pas un objet
            _body({"status": "success"}),  # transaction_id absent
            _body({"status": "success", "transaction_id": "  "}),
            _body({"status": "success", "transaction_id": 42}),
            _body({"status": 1, "transaction_id": pt.provider_reference}),
            _body({"status": "refunded", "transaction_id": pt.provider_reference}),
        ]
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(WebhookProcessingError) as cm:
                apply_provider_webhook(raw_body=raw, signature_header=_sign(raw))
            self.assertEqual(cm.exception.code, "invalid")
        pt.refresh_from_db()
        self.assertEqual(pt.status, PaymentTransactionStatus.PENDING)
        self.assertFalse(LedgerEntry.objects.exists())

    def test_unknown_transaction_id_is_not_found(self):
        with self.assertRaises(WebhookProcessingError) as cm:
            self.send({"status": "success", "transaction_id": "mock-inexistant"})
        self.assertEqual(cm.exception.code, "not_found")

    def test_status_aliases_are_accepted(self):
        for alias in ("SUCCESS", "Succeeded", " ok ", "completed"):
            with self.subTest(alias=alias):
                pt = self.make_pending()
                out = self.send({"status": alias, "transaction_id": pt.provider_reference})
                self.assertEqual(out.status, PaymentTransactionStatus.SUCCESS)
        for alias in ("failed", "ERROR", "declined"):
            with self.subTest(alias=alias):
                pt = self.make_pending()
                out = self.send({"status": alias, "transaction_id": pt.provider_reference})
                self.assertEqual(out.status, PaymentTransactionStatus.FAILED)


class WebhookStateMachineTests(PaymentsBase):
    def test_success_uses_stored_amount_not_the_webhook_amount(self):
        """Un webhook signe portant un montant different ne change pas le ledger."""
        pt = self.make_pending()
        out = self.send(
            {"status": "success", "transaction_id": pt.provider_reference, "amount": 1}
        )
        self.assertEqual(out.status, PaymentTransactionStatus.SUCCESS)
        self.assertEqual(out.amount, Decimal("3998"))
        entries = LedgerEntry.objects.filter(transaction=pt)
        self.assertEqual({e.amount for e in entries}, {Decimal("3998")})
        self.assertTrue(ledger_balanced_for_payment(pt))

    def test_success_replay_is_idempotent(self):
        pt = self.make_pending()
        payload = {"status": "success", "transaction_id": pt.provider_reference}
        self.send(payload)
        updated_at = PaymentTransaction.objects.get(pk=pt.pk).updated_at
        again = self.send(payload)  # rejeu du meme webhook
        self.assertEqual(again.status, PaymentTransactionStatus.SUCCESS)
        self.assertEqual(LedgerEntry.objects.filter(transaction=pt).count(), 2)
        self.assertEqual(PaymentTransaction.objects.get(pk=pt.pk).updated_at, updated_at)

    def test_success_after_failed_is_ignored(self):
        """Un paiement echoue ne peut plus etre valide par un webhook tardif."""
        pt = self.make_pending()
        self.send({"status": "failed", "transaction_id": pt.provider_reference})
        out = self.send({"status": "success", "transaction_id": pt.provider_reference})
        self.assertEqual(out.status, PaymentTransactionStatus.FAILED)
        self.assertFalse(LedgerEntry.objects.filter(transaction=pt).exists())

    def test_failed_after_success_is_ignored_and_keeps_ledger(self):
        pt = self.make_pending()
        self.send({"status": "success", "transaction_id": pt.provider_reference})
        out = self.send({"status": "failed", "transaction_id": pt.provider_reference})
        self.assertEqual(out.status, PaymentTransactionStatus.SUCCESS)
        self.assertEqual(LedgerEntry.objects.filter(transaction=pt).count(), 2)

    def test_failed_replay_is_idempotent_and_logs_error_once(self):
        pt = self.make_pending()
        payload = {"status": "failed", "transaction_id": pt.provider_reference}
        with self.assertLogs("payments.services.webhooks", level="ERROR") as cm:
            self.send(payload)
        self.assertEqual(len(cm.output), 1)
        # 2e livraison : deja FAILED -> aucun nouveau log d'erreur (pas de bruit d'alerte)
        with self.assertNoLogs("payments.services.webhooks", level="ERROR"):
            out = self.send(payload)
        self.assertEqual(out.status, PaymentTransactionStatus.FAILED)


class WebhookHttpTests(PaymentsBase):
    def setUp(self):
        super().setUp()
        self.http = Client(enforce_csrf_checks=True)

    def _post(self, raw: bytes, sig: str | None):
        extra = {"HTTP_X_PAYMENT_SIGNATURE": sig} if sig else {}
        return self.http.post(
            "/api/v1/payments/webhook/", data=raw, content_type="application/json", **extra
        )

    def test_forged_body_gets_403_and_payment_untouched(self):
        pt = self.make_pending()
        signed = _body({"status": "failed", "transaction_id": pt.provider_reference})
        forged = _body({"status": "success", "transaction_id": pt.provider_reference})
        with self.assertLogs("payments.api", level="ERROR"):
            resp = self._post(forged, _sign(signed))
        self.assertEqual(resp.status_code, 403)
        pt.refresh_from_db()
        self.assertEqual(pt.status, PaymentTransactionStatus.PENDING)

    def test_missing_signature_is_403(self):
        resp = self._post(b"{}", None)
        self.assertEqual(resp.status_code, 403)

    @override_settings(PAYMENTS_WEBHOOK_SECRET="")
    def test_unconfigured_secret_is_503(self):
        with self.assertLogs("payments.api", level="ERROR"):
            resp = self._post(b"{}", "sha256=x")
        self.assertEqual(resp.status_code, 503)

    def test_unknown_transaction_is_404_and_invalid_status_is_400(self):
        raw = _body({"status": "success", "transaction_id": "nope"})
        self.assertEqual(self._post(raw, _sign(raw)).status_code, 404)
        raw = _body({"status": "???", "transaction_id": "nope"})
        self.assertEqual(self._post(raw, _sign(raw)).status_code, 400)

    def test_success_returns_200_with_status(self):
        pt = self.make_pending()
        raw = _body({"status": "success", "transaction_id": pt.provider_reference})
        resp = self._post(raw, _sign(raw))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], PaymentTransactionStatus.SUCCESS)
