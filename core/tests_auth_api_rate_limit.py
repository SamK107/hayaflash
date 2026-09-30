"""Limites par IP sur l'API d'auth publique (F-19 : encore routee), cles partagees avec le HTML."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.services import rate_limit
from core.testing_helpers import honeypot_ok

User = get_user_model()
LOGIN = "/api/v1/accounts/auth/login/"
REGISTER = "/api/v1/accounts/auth/register/"


@override_settings(RATELIMIT_ENABLE=True)
class ApiAuthRateLimitTests(TestCase):
    def _login(self, ip="196.200.1.1"):
        return self.client.post(
            LOGIN, {"phone": "+22370000001", "password": "x"},
            content_type="application/json", REMOTE_ADDR=ip,
        )

    def _register(self, n, ip="196.200.1.1"):
        return self.client.post(
            REGISTER,
            {
                "phone": f"+2237100{n:04d}", "display_name": "A", "password": "pass-123456",
                "accept_terms": True,
            },
            content_type="application/json", REMOTE_ADDR=ip,
        )

    def test_login_over_limit_is_json_429(self) -> None:
        for _ in range(settings.RATELIMIT_LOGIN_IP[0]):
            self.assertNotEqual(self._login().status_code, 429)
        resp = self._login()
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json(), {"detail": [rate_limit.LOGIN_RATE_LIMIT_MESSAGE]})
        self.assertNotEqual(self._login(ip="196.200.2.2").status_code, 429)

    def test_register_over_limit_is_json_429(self) -> None:
        for n in range(settings.RATELIMIT_REGISTER_IP[0]):
            self.assertEqual(self._register(n).status_code, 201)
            self.client.logout()
        resp = self._register(99)
        self.assertEqual(resp.status_code, 429)
        self.assertFalse(User.objects.filter(phone="+22371000099").exists())
        self.assertEqual(self._register(98, ip="196.200.2.2").status_code, 201)

    def test_html_and_api_register_share_one_quota(self) -> None:
        for n in range(settings.RATELIMIT_REGISTER_IP[0]):
            self.client.post(
                reverse("register"),
                {"business_name": "B", "phone": f"+2237100{n:04d}", "password": "pass-123456",
                 "password2": "pass-123456", "accept_terms": "1", **honeypot_ok()},
                REMOTE_ADDR="196.200.1.1",
            )
            self.client.logout()
        self.assertEqual(self._register(99).status_code, 429)

    def test_html_and_api_login_share_one_quota(self) -> None:
        for _ in range(settings.RATELIMIT_LOGIN_IP[0] - 1):
            self._login()
        self.client.post(reverse("login"), {"phone": "+22370000001", "password": "x"}, REMOTE_ADDR="196.200.1.1")
        self.assertEqual(self._login().status_code, 429)
