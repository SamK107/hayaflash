"""Honeypot reutilisable (core/services/honeypot.py) et son application a l'inscription."""

from __future__ import annotations

import re
import time
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.services import honeypot
from core.testing_helpers import honeypot_ok

User = get_user_model()


class HoneypotServiceTests(SimpleTestCase):
    def test_normal_submission_is_accepted(self) -> None:
        data = honeypot_ok(age_seconds=10)
        self.assertIsNone(honeypot.rejection_reason(data))
        self.assertFalse(honeypot.is_bot_submission({**data, honeypot.HONEYPOT_FIELD: ""}))

    def test_filled_trap_is_rejected(self) -> None:
        data = {**honeypot_ok(), honeypot.HONEYPOT_FIELD: "http://spam.example"}
        self.assertEqual(honeypot.rejection_reason(data), "trap_filled")

    def test_too_fast_submission_is_rejected(self) -> None:
        self.assertEqual(honeypot.rejection_reason(honeypot_ok(age_seconds=0)), "too_fast")
        self.assertEqual(honeypot.rejection_reason(honeypot_ok(age_seconds=2)), "too_fast")
        self.assertIsNone(honeypot.rejection_reason(honeypot_ok(age_seconds=4)))

    def test_tampered_signature_is_rejected(self) -> None:
        token = honeypot.make_token(time.time() - 60)
        payload, _, sig = token.rpartition(":")
        forged = f"{payload}:{'A' * len(sig)}"
        self.assertEqual(
            honeypot.rejection_reason({honeypot.TIMESTAMP_FIELD: forged}), "token_invalid"
        )

    def test_altered_payload_is_rejected(self) -> None:
        # Pretendre que le formulaire a ete affiche il y a longtemps sans signer.
        token = honeypot.make_token(time.time())
        other = honeypot.make_token(time.time() - 600)
        mixed = other.split(":")[0] + ":" + ":".join(token.split(":")[1:])
        self.assertEqual(
            honeypot.rejection_reason({honeypot.TIMESTAMP_FIELD: mixed}), "token_invalid"
        )

    def test_token_signed_with_another_salt_is_rejected(self) -> None:
        token = signing.dumps({"t": time.time() - 60}, salt="autre")
        self.assertEqual(
            honeypot.rejection_reason({honeypot.TIMESTAMP_FIELD: token}), "token_invalid"
        )

    def test_missing_or_garbage_token_is_rejected(self) -> None:
        self.assertEqual(honeypot.rejection_reason({}), "token_invalid")
        self.assertEqual(
            honeypot.rejection_reason({honeypot.TIMESTAMP_FIELD: "n'importe quoi"}), "token_invalid"
        )

    def test_expired_token_is_rejected(self) -> None:
        token = honeypot.make_token(time.time() - 60)
        with mock.patch("django.core.signing.time.time", return_value=time.time() + 2 * 3600 + 5):
            self.assertEqual(
                honeypot.rejection_reason({honeypot.TIMESTAMP_FIELD: token}), "token_expired"
            )


class RegisterHoneypotTests(TestCase):
    def setUp(self) -> None:
        self.url = reverse("register")

    def payload(self, **extra) -> dict:
        data = {
            "business_name": "Boutique Awa",
            "phone": "+22370000042",
            "password": "pass-123456",
            "password2": "pass-123456",
            "accept_terms": "1",
            **honeypot_ok(),
        }
        data.update(extra)
        return data

    def _assert_rejected(self, response) -> None:
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, honeypot.GENERIC_ERROR)
        self.assertEqual(User.objects.count(), 0)

    def test_form_renders_trap_and_signed_timestamp(self) -> None:
        html = self.client.get(self.url).content.decode()
        self.assertIn('name="website"', html)
        self.assertIn('tabindex="-1"', html)
        self.assertIn('autocomplete="off"', html)
        self.assertNotIn('type="hidden" id="website"', html)
        token = re.search(r'name="form_ts" value="([^"]+)"', html).group(1)
        payload = signing.loads(token, salt=honeypot.SALT)
        self.assertLess(abs(payload["t"] - time.time()), 5)

    def test_normal_submission_creates_account(self) -> None:
        response = self.client.post(self.url, self.payload())
        self.assertRedirects(response, reverse("seller_home"), fetch_redirect_response=False)
        self.assertEqual(User.objects.count(), 1)

    def test_filled_trap_is_rejected_with_generic_message(self) -> None:
        self._assert_rejected(self.client.post(self.url, self.payload(website="x")))

    def test_too_fast_submission_is_rejected(self) -> None:
        self._assert_rejected(self.client.post(self.url, self.payload(**honeypot_ok(0))))

    def test_tampered_token_is_rejected(self) -> None:
        self._assert_rejected(self.client.post(self.url, self.payload(form_ts="abc:def:ghi")))

    def test_missing_token_is_rejected(self) -> None:
        data = self.payload()
        del data[honeypot.TIMESTAMP_FIELD]
        self._assert_rejected(self.client.post(self.url, data))

    def test_message_does_not_reveal_the_reason(self) -> None:
        a = self.client.post(self.url, self.payload(website="x")).content.decode()
        b = self.client.post(self.url, self.payload(**honeypot_ok(0))).content.decode()
        for text in (a, b):
            self.assertNotIn("trap", text)
            self.assertNotIn("trop vite", text)
            self.assertNotIn("too_fast", text)
