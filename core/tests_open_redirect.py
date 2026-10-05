"""F-06 : /login/?next= ne doit jamais rediriger hors du site."""

from __future__ import annotations

from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

User = get_user_model()
PHONE = "+22370000031"
PASSWORD = "motdepasse-8"


class LoginNextRedirectTests(TestCase):
    def setUp(self):
        User.objects.create_user(phone=PHONE, password=PASSWORD, display_name="Awa")

    def login(self, next_value, **extra):
        url = reverse("login") + "?next=" + quote(next_value, safe="")
        return self.client.post(url, {"phone": PHONE, "password": PASSWORD}, **extra)

    def assertDefaultTarget(self, response):
        # Compte sans profil vendeur non staff : cible par defaut = seller_home.
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("seller_home"))

    def test_external_absolute_url_is_ignored(self):
        self.assertDefaultTarget(self.login("https://evil.example/phish"))

    def test_scheme_relative_url_is_ignored(self):
        self.assertDefaultTarget(self.login("//evil.example/phish"))

    def test_javascript_scheme_is_ignored(self):
        self.assertDefaultTarget(self.login("javascript:alert(1)"))

    def test_backslash_tricks_are_ignored(self):
        bs = chr(92)  # antislash
        for value in (
            "/" + bs + "evil.example",
            bs + bs + "evil.example",
            "https:" + bs + bs + "evil.example",
            "/" + bs + "/evil.example",
        ):
            with self.subTest(value=value):
                self.client.logout()
                self.assertDefaultTarget(self.login(value))

    def test_other_dangerous_schemes_are_ignored(self):
        for value in ("data:text/html,x", "ftp://evil.example/", "  https://evil.example"):
            with self.subTest(value=value):
                self.client.logout()
                self.assertDefaultTarget(self.login(value))

    def test_valid_internal_path_is_accepted(self):
        response = self.login("/orders/seller/dashboard/?flash_sale_id=3")
        self.assertEqual(response["Location"], "/orders/seller/dashboard/?flash_sale_id=3")

    def test_valid_relative_path_is_accepted(self):
        self.assertEqual(self.login("/seller/parametres/")["Location"], "/seller/parametres/")

    def test_absolute_url_on_own_host_is_accepted(self):
        response = self.login("http://testserver/seller/parametres/")
        self.assertEqual(response["Location"], "http://testserver/seller/parametres/")

    @override_settings(ALLOWED_HOSTS=["testserver", "boutique.example"])
    def test_other_host_is_refused_even_if_listed_for_another_site(self):
        # Seul l'hote de la requete courante est autorise : un autre hote de
        # ALLOWED_HOSTS n'est pas une cible de redirection acceptable.
        self.assertDefaultTarget(self.login("https://boutique.example/x"))

    def test_https_page_does_not_downgrade_to_http(self):
        response = self.login("http://testserver/seller/", secure=True)
        self.assertDefaultTarget(response)

    def test_no_next_uses_default(self):
        response = self.client.post(reverse("login"), {"phone": PHONE, "password": PASSWORD})
        self.assertDefaultTarget(response)
