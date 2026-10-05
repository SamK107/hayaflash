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


ENGLISH = ("too short", "too common", "entirely numeric", "too similar", "at least", "display name", "champ «")


def assert_french(testcase, text):
    for marker in ENGLISH:
        testcase.assertNotIn(marker, text.lower())


class F17RegisterPasswordTests(TestCase):
    def post(self, **kwargs):
        return self.client.post(reverse("register"), payload(**kwargs))

    def test_seven_characters_refused_and_eight_accepted(self):
        response = self.post(password="abcdef7", phone="+22370000042")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "au minimum 8 caractères")
        self.assertFalse(User.objects.filter(phone="+22370000042").exists())
        response = self.post(password="vache-lune-8", phone="+22370000042")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(phone="+22370000042").exists())

    def test_numeric_password_refused(self):
        response = self.post(password="12345678")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.exists())
        body = response.content.decode()
        self.assertIn("entièrement numérique", body)
        assert_french(self, body)

    def test_too_common_password_refused(self):
        response = self.post(password="password1")
        self.assertFalse(User.objects.exists())
        self.assertContains(response, "trop courant")

    def test_password_similar_to_business_name_refused(self):
        response = self.post(password="boutiqueawa", business_name="Boutique Awa")
        self.assertFalse(User.objects.exists())
        self.assertContains(response, "trop semblable")

    def test_password_similar_to_phone_refused(self):
        response = self.post(password="22370000041x", phone="+22370000041")
        self.assertFalse(User.objects.exists())

    def test_mismatch_still_reported(self):
        response = self.post(password="vache-lune-8", password2="vache-lune-9")
        self.assertContains(response, "ne correspondent pas")
        self.assertFalse(User.objects.exists())

    def test_form_advertises_eight_characters(self):
        body = self.client.get(reverse("register")).content.decode()
        self.assertIn("Minimum 8 caractères", body)
        self.assertNotIn("Minimum 6", body)


class F17SettingsPasswordTests(TestCase):
    def setUp(self):
        from accounts.models import SellerProfile

        self.user = User.objects.create_user(
            phone="+22370000043", password="ancien-mot-de-passe", display_name="Awa Diallo"
        )
        SellerProfile.objects.create(user=self.user, business_name="Boutique Awa")
        self.client.force_login(self.user)

    def change(self, new, current="ancien-mot-de-passe"):
        return self.client.post(
            reverse("seller_settings"),
            {
                "action": "change_password",
                "current_password": current,
                "new_password": new,
                "confirm_password": new,
            },
        )

    def test_seven_characters_refused_old_password_kept(self):
        response = self.change("abcdef7")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "au minimum 8 caractères")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("ancien-mot-de-passe"))

    def test_eight_characters_accepted(self):
        response = self.change("vache-lune-8")
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("vache-lune-8"))

    def test_numeric_common_and_similar_refused_in_french(self):
        for value, fragment in (
            ("20481357", "entièrement numérique"),
            ("password1", "trop courant"),
            ("awadiallo1", "trop semblable"),
        ):
            with self.subTest(value=value):
                response = self.change(value)
                self.assertEqual(response.status_code, 200)
                body = response.content.decode()
                self.assertIn(fragment, body)
                assert_french(self, body)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("ancien-mot-de-passe"))


class F17ExistingShortPasswordsStillLogInTests(TestCase):
    """Les comptes existants ne sont pas touchés : le validateur n'est PAS
    appliqué à la connexion (un hash ne révèle pas la longueur)."""

    def test_six_character_password_still_logs_in(self):
        User.objects.create_user(phone="+22370000044", password="abc123", display_name="Awa")
        response = self.client.post(
            reverse("login"), {"phone": "+22370000044", "password": "abc123"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("seller_home"))
