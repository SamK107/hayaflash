"""Limites de debit sur /login/ et /register/ (core/views.py)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape

from core import views

User = get_user_model()

PHONE = "+22370000001"
PASSWORD = "bonmotdepasse"


class LoginRateLimitTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(phone=PHONE, password=PASSWORD, display_name="Awa")
        self.url = reverse("login")

    def _post(self, phone=PHONE, password="mauvais", ip="196.200.1.1"):
        return self.client.post(
            self.url, {"phone": phone, "password": password}, REMOTE_ADDR=ip
        )

    def test_sixth_attempt_after_five_failures_is_429_even_with_good_password(self) -> None:
        for _ in range(views.LOGIN_MAX_FAILURES_PER_PHONE):
            self.assertEqual(self._post().status_code, 200)
        response = self._post(password=PASSWORD)
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, views.LOGIN_RATE_LIMIT_MESSAGE, status_code=429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_same_message_for_unknown_number(self) -> None:
        unknown = "+22370009999"
        for _ in range(views.LOGIN_MAX_FAILURES_PER_PHONE):
            self._post(phone=unknown)
        response = self._post(phone=unknown)
        self.assertContains(response, views.LOGIN_RATE_LIMIT_MESSAGE, status_code=429)

    def test_success_resets_phone_counter(self) -> None:
        for _ in range(views.LOGIN_MAX_FAILURES_PER_PHONE - 1):
            self._post()
        self.assertEqual(self._post(password=PASSWORD).status_code, 302)
        self.client.logout()
        for _ in range(views.LOGIN_MAX_FAILURES_PER_PHONE - 1):
            self.assertEqual(self._post().status_code, 200)
        self.assertEqual(self._post(password=PASSWORD).status_code, 302)

    def test_ip_limit(self) -> None:
        for i in range(views.LOGIN_MAX_ATTEMPTS_PER_IP):
            response = self._post(phone=f"+2237000{i:04d}", ip="196.200.9.9")
            self.assertEqual(response.status_code, 200)
        response = self._post(phone="+22371111111", ip="196.200.9.9")
        self.assertEqual(response.status_code, 429)

    def test_other_phone_from_other_ip_not_affected(self) -> None:
        for _ in range(views.LOGIN_MAX_FAILURES_PER_PHONE + 1):
            self._post(ip="196.200.1.1")
        other = User.objects.create_user(phone="+22370000002", password=PASSWORD, display_name="Bina")
        response = self._post(phone=other.phone, password=PASSWORD, ip="196.200.2.2")
        self.assertEqual(response.status_code, 302)

    def test_get_is_not_counted(self) -> None:
        for _ in range(views.LOGIN_MAX_ATTEMPTS_PER_IP + 5):
            self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self._post(password=PASSWORD).status_code, 302)


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
        self.assertContains(response, 'tabindex="-1"')
        self.assertNotContains(response, 'type="hidden" id="website"')

    def test_filled_honeypot_creates_nothing(self) -> None:
        from core.models import LegalAcceptance

        with self.assertLogs("core.views", level="INFO") as logs:
            response = self.client.post(
                self.url, self.payload(website="http://spam.example"), REMOTE_ADDR="196.200.4.4"
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, views.REGISTER_GENERIC_ERROR)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(LegalAcceptance.objects.count(), 0)
        self.assertIn("196.200.4.4", "\n".join(logs.output))

    def test_sixth_registration_from_same_ip_is_429(self) -> None:
        for n in range(views.REGISTER_MAX_ATTEMPTS_PER_IP):
            self.client.post(self.url, self.payload(n), REMOTE_ADDR="196.200.5.5")
            self.client.logout()
        response = self.client.post(self.url, self.payload(99), REMOTE_ADDR="196.200.5.5")
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, escape(views.REGISTER_RATE_LIMIT_MESSAGE), status_code=429)
        self.assertFalse(User.objects.filter(phone="+22371000099").exists())
        self.assertEqual(User.objects.count(), views.REGISTER_MAX_ATTEMPTS_PER_IP)

    def test_other_ip_can_still_register(self) -> None:
        for n in range(views.REGISTER_MAX_ATTEMPTS_PER_IP + 1):
            self.client.post(self.url, self.payload(n), REMOTE_ADDR="196.200.5.5")
            self.client.logout()
        response = self.client.post(self.url, self.payload(50), REMOTE_ADDR="196.200.6.6")
        self.assertEqual(response.status_code, 302)
