"""F-19 : l'API d'authentification /api/v1/accounts/auth/* est retirée du routage.

L'inscription et la connexion passent par les pages web (/register/, /login/),
protégées (limites par IP/numéro, honeypot, django-axes). Les URLs de l'ancienne
API doivent répondre 404, et le reste de l'API (health, flash-sales, orders)
rester routé.
"""

from __future__ import annotations

from django.test import TestCase
from django.urls import NoReverseMatch, resolve, reverse
from rest_framework.test import APIClient

REMOVED = (
    "/api/v1/accounts/auth/register/",
    "/api/v1/accounts/auth/login/",
    "/api/v1/accounts/auth/logout/",
    "/api/v1/accounts/auth/me/",
)


class RemovedAuthApiTests(TestCase):
    def test_removed_urls_answer_404_for_every_method(self):
        client = APIClient()
        for url in REMOVED:
            for method in ("get", "post", "put", "delete"):
                with self.subTest(url=url, method=method):
                    response = getattr(client, method)(url, {}, format="json")
                    self.assertEqual(response.status_code, 404)

    def test_authenticated_session_does_not_resurrect_me(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(
            phone="+22370000050", password="motdepasse-8", display_name="Awa"
        )
        client = APIClient()
        client.force_authenticate(user)
        self.assertEqual(client.get("/api/v1/accounts/auth/me/").status_code, 404)

    def test_url_names_are_gone(self):
        for name in ("accounts:register", "accounts:login", "accounts:logout", "accounts:me"):
            with self.subTest(name=name), self.assertRaises(NoReverseMatch):
                reverse(name)

    def test_rest_of_the_api_is_still_routed(self):
        for url in ("/api/v1/health/", "/api/v1/orders/", "/api/v1/flash-sales/"):
            with self.subTest(url=url):
                self.assertEqual(resolve(url).route.startswith("api/v1/"), True)
        self.assertEqual(APIClient().get("/api/v1/health/").status_code, 200)
        self.assertEqual(APIClient().get("/api/v1/flash-sales/").status_code, 200)
        # orders : POST public, un corps vide donne une erreur de validation, pas 404.
        self.assertNotEqual(APIClient().post("/api/v1/orders/", {}, format="json").status_code, 404)

    def test_web_registration_and_login_pages_are_untouched(self):
        self.assertEqual(self.client.get(reverse("register")).status_code, 200)
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)
