"""Limites de debit sur /login/ et /register/ (core/views.py)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

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
