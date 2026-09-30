"""Limites de debit sur /login/ et /register/ (core/views.py)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.html import escape

from core.services import honeypot, rate_limit
from core.testing_helpers import honeypot_ok

User = get_user_model()

PHONE = "+22370000001"
PASSWORD = "bonmotdepasse"


@override_settings(RATELIMIT_ENABLE=True)
class LoginRateLimitTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(phone=PHONE, password=PASSWORD, display_name="Awa")
        self.url = reverse("login")

    def _post(self, phone=PHONE, password="mauvais", ip="196.200.1.1"):
        return self.client.post(
            self.url, {"phone": phone, "password": password}, REMOTE_ADDR=ip
        )

    def test_failures_no_longer_lock_the_phone_alone(self) -> None:
        # Verrou telephone seul retire (django-axes verrouille telephone + IP,
        # voir core/tests_axes.py) : le vendeur se connecte depuis son IP
        # meme si des tiers ont echoue sur son numero depuis d'autres IP.
        for i in range(10):
            self._post(ip=f"196.200.7.{i}")
        self.assertEqual(self._post(password=PASSWORD, ip="196.200.8.8").status_code, 302)

    def test_ip_limit(self) -> None:
        for i in range(settings.RATELIMIT_LOGIN_IP[0]):
            response = self._post(phone=f"+2237000{i:04d}", ip="196.200.9.9")
            self.assertEqual(response.status_code, 200)
        response = self._post(phone="+22371111111", ip="196.200.9.9")
        self.assertEqual(response.status_code, 429)

    def test_get_is_not_counted(self) -> None:
        for _ in range(settings.RATELIMIT_LOGIN_IP[0] + 5):
            self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self._post(password=PASSWORD).status_code, 302)


@override_settings(RATELIMIT_ENABLE=True)
class RegisterRateLimitAndHoneypotTests(TestCase):
    def setUp(self) -> None:
        self.url = reverse("register")

    def payload(self, n: int = 0, **extra) -> dict:
        data = {
            "business_name": f"Boutique {n}",
            "phone": f"+2237100{n:04d}",
            "password": "pass-123456",
            "password2": "pass-123456",
            "accept_terms": "1",
            **honeypot_ok(),
        }
        data.update(extra)
        return data

    def test_normal_registration_still_works(self) -> None:
        from core.models import LegalAcceptance

        response = self.client.post(self.url, self.payload(), REMOTE_ADDR="196.200.3.3")
        self.assertRedirects(response, reverse("seller_home"), fetch_redirect_response=False)
        user = User.objects.get()
        self.assertTrue(hasattr(user, "seller_profile"))
        self.assertEqual(LegalAcceptance.objects.filter(user=user).count(), 2)

    def test_form_has_offscreen_honeypot(self) -> None:
        response = self.client.get(self.url)
        self.assertContains(response, 'name="website"')
        self.assertContains(response, 'name="form_ts"')
        self.assertContains(response, 'tabindex="-1"')
        self.assertNotContains(response, 'type="hidden" id="website"')

    def test_filled_honeypot_creates_nothing(self) -> None:
        from core.models import LegalAcceptance

        with self.assertLogs("core.views", level="INFO") as logs:
            response = self.client.post(
                self.url, self.payload(website="http://spam.example"), REMOTE_ADDR="196.200.4.4"
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, honeypot.GENERIC_ERROR)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(LegalAcceptance.objects.count(), 0)
        self.assertIn("196.200.4.4", "\n".join(logs.output))

    def test_sixth_registration_from_same_ip_is_429(self) -> None:
        for n in range(settings.RATELIMIT_REGISTER_IP[0]):
            self.client.post(self.url, self.payload(n), REMOTE_ADDR="196.200.5.5")
            self.client.logout()
        response = self.client.post(self.url, self.payload(99), REMOTE_ADDR="196.200.5.5")
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, escape(rate_limit.REGISTER_RATE_LIMIT_MESSAGE), status_code=429)
        self.assertFalse(User.objects.filter(phone="+22371000099").exists())
        self.assertEqual(User.objects.count(), settings.RATELIMIT_REGISTER_IP[0])

    def test_other_ip_can_still_register(self) -> None:
        for n in range(settings.RATELIMIT_REGISTER_IP[0] + 1):
            self.client.post(self.url, self.payload(n), REMOTE_ADDR="196.200.5.5")
            self.client.logout()
        response = self.client.post(self.url, self.payload(50), REMOTE_ADDR="196.200.6.6")
        self.assertEqual(response.status_code, 302)
