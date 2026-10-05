"""django-axes : verrou telephone + IP sur login HTML, API DRF et admin."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from axes.models import AccessAttempt

User = get_user_model()

PHONE = "+22370000001"
PASSWORD = "bonmotdepasse"
LIMIT = 5


@override_settings(AXES_ENABLED=True)
class AxesLoginTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(phone=PHONE, password=PASSWORD, display_name="Awa")
        self.url = reverse("login")

    def _post(self, password="mauvais", phone=PHONE, ip="196.200.1.1"):
        return self.client.post(
            self.url, {"phone": phone, "password": password}, REMOTE_ADDR=ip
        )

    def _fail(self, n=LIMIT, **kw):
        for _ in range(n):
            self._post(**kw)

    def test_locked_after_five_failures_even_with_good_password(self) -> None:
        self._fail()
        response = self._post(password=PASSWORD)
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "Trop de tentatives", status_code=429)
        self.assertContains(response, "30 minutes", status_code=429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_four_failures_do_not_lock(self) -> None:
        self._fail(LIMIT - 1)
        self.assertEqual(self._post(password=PASSWORD).status_code, 302)

    def test_other_ip_is_not_blocked_for_the_same_phone(self) -> None:
        self._fail()
        self.assertEqual(self._post(password=PASSWORD).status_code, 429)
        response = self._post(password=PASSWORD, ip="196.200.2.2")
        self.assertEqual(response.status_code, 302)

    def test_other_phone_same_ip_is_not_blocked(self) -> None:
        other = User.objects.create_user(phone="+22370000002", password=PASSWORD, display_name="Bina")
        self._fail()
        self.assertEqual(self._post(phone=other.phone, password=PASSWORD).status_code, 302)

    def test_successful_login_resets_counter(self) -> None:
        self._fail(LIMIT - 1)
        self.assertEqual(self._post(password=PASSWORD).status_code, 302)
        self.client.logout()
        self._fail(LIMIT - 1)
        self.assertEqual(self._post(password=PASSWORD).status_code, 302)

    def test_ip_comes_from_trusted_proxy_header(self) -> None:
        with override_settings(TRUSTED_PROXY_NETWORKS=["10.0.0.0/8"]):
            for _ in range(LIMIT):
                self.client.post(
                    self.url,
                    {"phone": PHONE, "password": "mauvais"},
                    REMOTE_ADDR="10.0.0.5",
                    HTTP_X_REAL_IP="196.200.3.3",
                )
            attempt = AccessAttempt.objects.get()
            self.assertEqual(attempt.ip_address, "196.200.3.3")
            # meme proxy, autre client final : pas bloque
            response = self.client.post(
                self.url,
                {"phone": PHONE, "password": PASSWORD},
                REMOTE_ADDR="10.0.0.5",
                HTTP_X_REAL_IP="196.200.4.4",
            )
            self.assertEqual(response.status_code, 302)

    def test_phone_formats_share_one_counter(self) -> None:
        for raw in ("+22370000001", "+223 70000001", "+223 7000 0001", "+22370000001 ", "+22370000001"):
            self._post(phone=raw)
        self.assertEqual(AccessAttempt.objects.count(), 1)
        self.assertEqual(self._post(password=PASSWORD).status_code, 429)


@override_settings(AXES_ENABLED=True)
class AxesAdminTests(TestCase):
    def setUp(self) -> None:
        User.objects.create_superuser(phone="+22370000009", password=PASSWORD, display_name="Root")
        self.url = reverse("admin:login")

    def _post(self, password="mauvais", ip="196.200.1.1"):
        return self.client.post(
            self.url,
            {"username": "+22370000009", "password": password, "next": "/admin/"},
            REMOTE_ADDR=ip,
        )

    def test_admin_login_is_locked_too(self) -> None:
        for _ in range(LIMIT):
            self._post()
        response = self._post(password=PASSWORD)
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_admin_other_ip_not_blocked(self) -> None:
        for _ in range(LIMIT):
            self._post()
        self.assertEqual(self._post(password=PASSWORD, ip="196.200.9.9").status_code, 302)


class AxesDisabledByDefaultInTests(TestCase):
    def test_disabled_globally_in_test_settings(self) -> None:
        User.objects.create_user(phone=PHONE, password=PASSWORD, display_name="Awa")
        for _ in range(LIMIT + 3):
            self.client.post(reverse("login"), {"phone": PHONE, "password": "x"}, REMOTE_ADDR="196.200.1.1")
        self.assertEqual(AccessAttempt.objects.count(), 0)
        response = self.client.post(
            reverse("login"), {"phone": PHONE, "password": PASSWORD}, REMOTE_ADDR="196.200.1.1"
        )
        self.assertEqual(response.status_code, 302)
