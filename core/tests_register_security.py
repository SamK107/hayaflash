"""Inscription web (/register/) : F-15 (limite par numéro), F-16 (énumération),
F-17 (validateurs de mot de passe), F-18 (message d'exception brut)."""

from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.testing_helpers import honeypot_ok

User = get_user_model()
PHONE = "+22370000041"
GOOD_PASSWORD = "motdepasse-solide-8"


def payload(phone=PHONE, password=GOOD_PASSWORD, password2=None, **extra):
    data = {
        "business_name": "Boutique Awa",
        "phone": phone,
        "password": password,
        "password2": password if password2 is None else password2,
        "accept_terms": "1",
        **honeypot_ok(),
    }
    data.update(extra)
    return data


class F18ExceptionMessageTests(TestCase):
    def test_exception_text_and_stack_never_reach_the_response(self):
        secret = "SECRET-DETAIL-db-password=hunter2 phone=+22370000041"
        with patch("core.views.record_legal_acceptances", side_effect=RuntimeError(secret)):
            response = self.client.post(reverse("register"), payload())
        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("SECRET-DETAIL", body)
        self.assertNotIn("hunter2", body)
        self.assertNotIn("Traceback", body)
        self.assertNotIn("RuntimeError", body)
        self.assertIn("Impossible de créer le compte pour le moment. Réessayez dans quelques instants.", body)
        self.assertEqual(User.objects.count(), 0)

    def test_exception_is_logged_server_side_without_phone_or_password(self):
        with patch("core.views.record_legal_acceptances", side_effect=RuntimeError("boom +22370000041")):
            with self.assertLogs("core.views", level="ERROR") as logs:
                self.client.post(reverse("register"), payload())
        output = "\n".join(logs.output)
        self.assertIn("RuntimeError", output)
        self.assertNotIn(PHONE, output)
        self.assertNotIn("22370000041", output)
        self.assertNotIn(GOOD_PASSWORD, output)
