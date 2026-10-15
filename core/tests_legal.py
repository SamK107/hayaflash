"""Pages légales, liens de pied de page, acceptation des CGU à l'inscription."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, modify_settings, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import LegalAcceptance, LegalDocument
from core.testing_helpers import honeypot_ok

User = get_user_model()


class LegalAcceptanceModelTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            phone="+22370000001", password="pass-123456", display_name="Awa"
        )

    def test_create(self):
        acc = LegalAcceptance.objects.create(
            user=self.user,
            document=LegalDocument.CGU,
            version="2026-09",
            ip_address="10.0.0.1",
        )
        self.assertIsNotNone(acc.accepted_at)
        self.assertEqual(self.user.legal_acceptances.count(), 1)

    def test_str(self):
        acc = LegalAcceptance.objects.create(
            user=self.user, document=LegalDocument.PRIVACY, version="2026-09"
        )
        text = str(acc)
        self.assertIn("privacy", text)
        self.assertIn("v2026-09", text)

    def test_ordering_most_recent_first(self):
        now = timezone.now()
        old = LegalAcceptance.objects.create(
            user=self.user,
            document=LegalDocument.CGU,
            version="2026-01",
            accepted_at=now - timedelta(days=30),
        )
        new = LegalAcceptance.objects.create(
            user=self.user, document=LegalDocument.CGU, version="2026-09", accepted_at=now
        )
        self.assertEqual(list(LegalAcceptance.objects.all()), [new, old])


class LegalPagesTests(TestCase):
    PAGES = {
        "legal_privacy": ("/confidentialite/", "Politique de confidentialité — HayaFlash"),
        "legal_terms": ("/cgu/", "Conditions générales d'utilisation — HayaFlash"),
        "legal_notice": ("/mentions-legales/", "Mentions légales — HayaFlash"),
    }

    def test_pages_ok_for_anonymous_with_title(self):
        for name, (path, title) in self.PAGES.items():
            with self.subTest(name=name):
                self.assertEqual(reverse(name), path)
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f"<title>{title}</title>", html=False)

    def test_versions_come_from_constants(self):
        from core.legal import LEGAL_CGU_VERSION, LEGAL_PRIVACY_VERSION

        self.assertContains(
            self.client.get(reverse("legal_terms")), f"Version {LEGAL_CGU_VERSION}"
        )
        self.assertContains(
            self.client.get(reverse("legal_privacy")), f"Version {LEGAL_PRIVACY_VERSION}"
        )

    # config.settings.test n'installe pas django.contrib.sitemaps (template
    # sitemap.xml introuvable) : ajoute pour ce test seulement.
    @modify_settings(INSTALLED_APPS={"append": "django.contrib.sitemaps"})
    def test_pages_listed_in_sitemap(self):
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        for path, _title in self.PAGES.values():
            with self.subTest(path=path):
                self.assertContains(response, f"{path}</loc>")


class LegalFooterLinksTests(TestCase):
    def assert_legal_links(self, response):
        self.assertEqual(response.status_code, 200)
        for name in ("legal_privacy", "legal_terms", "legal_notice"):
            self.assertContains(response, f'href="{reverse(name)}"')

    def test_home_has_legal_links(self):
        self.assert_legal_links(self.client.get(reverse("home")))

    def test_public_calendar_has_legal_links(self):
        self.assert_legal_links(self.client.get(reverse("flash_sale_calendar")))

    def test_register_page_has_legal_links(self):
        self.assert_legal_links(self.client.get(reverse("register")))


class RegisterLegalAcceptanceTests(TestCase):
    def payload(self, **extra):
        data = {
            "business_name": "Boutique Awa",
            "phone": "+22370000009",
            "password": "pass-123456",
            "password2": "pass-123456",
            **honeypot_ok(),
        }
        data.update(extra)
        return data

    def test_register_without_checkbox_creates_nothing(self):
        from core.legal import LEGAL_ACCEPTANCE_REQUIRED_MESSAGE

        response = self.client.post(reverse("register"), self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, LEGAL_ACCEPTANCE_REQUIRED_MESSAGE)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(LegalAcceptance.objects.count(), 0)

    def test_register_with_checkbox_records_both_acceptances(self):
        from core.legal import LEGAL_CGU_VERSION, LEGAL_PRIVACY_VERSION

        response = self.client.post(
            reverse("register"),
            self.payload(accept_terms="1"),
            REMOTE_ADDR="196.200.1.2",
        )
        self.assertRedirects(response, reverse("seller_home"), fetch_redirect_response=False)
        user = User.objects.get()
        self.assertTrue(hasattr(user, "seller_profile"))
        versions = dict(user.legal_acceptances.values_list("document", "version"))
        self.assertEqual(
            versions,
            {LegalDocument.CGU: LEGAL_CGU_VERSION, LegalDocument.PRIVACY: LEGAL_PRIVACY_VERSION},
        )
        self.assertEqual(
            set(user.legal_acceptances.values_list("ip_address", flat=True)), {"196.200.1.2"}
        )

    def test_register_form_has_required_checkbox(self):
        response = self.client.get(reverse("register"))
        self.assertContains(response, 'name="accept_terms"')
        self.assertContains(response, 'rel="noopener"')

    def test_failure_after_user_creation_rolls_back(self):
        from unittest.mock import patch

        with patch("core.views.record_legal_acceptances", side_effect=RuntimeError("boom")):
            self.client.post(reverse("register"), self.payload(accept_terms="1"))
        self.assertEqual(User.objects.count(), 0)


class AcceptanceIpTests(TestCase):
    def test_invalid_ip_is_stored_as_none(self):
        from django.test import RequestFactory

        from core.legal import acceptance_ip

        request = RequestFactory().get("/", REMOTE_ADDR="")
        self.assertIsNone(acceptance_ip(request))

    def test_forwarded_for_from_client_is_not_trusted(self):
        """F-26 : ancien test « 1er X-Forwarded-For » = comportement vulnerable.

        Ce en-tete est fourni par le client : la preuve d'acceptation des CGU
        ne doit pas pouvoir etre falsifiee. On enregistre l'IP de la connexion.
        """
        from django.test import RequestFactory

        from core.legal import acceptance_ip

        request = RequestFactory().get(
            "/", REMOTE_ADDR="196.200.1.4", HTTP_X_FORWARDED_FOR="41.73.1.1, 10.0.0.1"
        )
        self.assertEqual(acceptance_ip(request), "196.200.1.4")

    @override_settings(TRUSTED_PROXY_NETWORKS=["172.16.0.0/12"])
    def test_trusted_proxy_header_is_used(self):
        from django.test import RequestFactory

        from core.legal import acceptance_ip

        request = RequestFactory().get(
            "/", REMOTE_ADDR="172.18.0.5", HTTP_X_REAL_IP="41.73.1.1"
        )
        self.assertEqual(acceptance_ip(request), "41.73.1.1")


# ── F-107 : identité de l'éditeur (entreprise individuelle) dans les pages légales ──

import re
from pathlib import Path

from django.conf import settings

IDENTITE = {
    "LEGAL_ENTITY_NAME": "EXPLOITATION-TEST",
    "LEGAL_ENTITY_RCCM": "MA.TST.2099.A.00001",
    "LEGAL_ENTITY_ADDRESS": "Quartier Test, Commune Z, Ville-Test, Pays",
    "LEGAL_HOST_NAME": "HEBERGEUR TEST SA",
    "LEGAL_HOST_ADDRESS": "1 rue de l'Hôte, 99999 Hostville",
    "LEGAL_HOST_PHONE": "+99 (0)9 99 99 99 99",
}
ANCIENNE_IDENTITE = ("SUARL", "ACI 2000", "BKO.2022.A.4291")


def _section(html: str, start_id: str, end_id: str) -> str:
    match = re.search(rf'id="{start_id}"(.*?)id="{end_id}"', html, re.DOTALL)
    assert match, (start_id, end_id)
    return match.group(1)


@override_settings(**IDENTITE)
class LegalIdentityTests(TestCase):
    def get(self, name: str) -> str:
        return self.client.get(reverse(name)).content.decode()

    def test_no_page_mentions_the_old_identity(self):
        for name in ("legal_notice", "legal_privacy", "legal_terms"):
            html = self.get(name)
            for old in ANCIENNE_IDENTITE:
                with self.subTest(page=name, old=old):
                    self.assertNotIn(old, html)

    def test_notice_reads_entity_from_settings(self):
        html = self.get("legal_notice")
        editeur = _section(html, "editeur", "publication")
        self.assertIn("EXPLOITATION-TEST", editeur)
        self.assertIn("MA.TST.2099.A.00001", editeur)
        self.assertIn("Quartier Test, Commune Z, Ville-Test, Pays", editeur)
        self.assertIn("entreprise individuelle", editeur)
        self.assertIn("sans capital social", editeur)
        self.assertNotIn("société", editeur.lower())

    @override_settings(LEGAL_ENTITY_CAPITAL="1 000 000 FCFA")
    def test_notice_never_shows_a_share_capital(self):
        editeur = _section(self.get("legal_notice"), "editeur", "publication")
        self.assertNotIn("1 000 000", editeur)

    def test_publication_director_is_the_company_not_a_person(self):
        publication = _section(self.get("legal_notice"), "publication", "contact")
        self.assertIn(
            "EXPLOITATION-TEST, entreprise individuelle, éditrice de HayaFlash", publication
        )
        self.assertNotIn("équipe", publication)

    def test_notice_shows_host_from_settings(self):
        hebergement = _section(self.get("legal_notice"), "hebergement", "documents")
        self.assertIn("HEBERGEUR TEST SA", hebergement)
        self.assertIn("1 rue de l&#x27;Hôte, 99999 Hostville", hebergement)
        self.assertIn("+99 (0)9 99 99 99 99", hebergement)

    @override_settings(LEGAL_HOST_NAME="", LEGAL_HOST_ADDRESS="", LEGAL_HOST_PHONE="")
    def test_notice_without_host_settings_stays_valid_and_blank_free(self):
        response = self.client.get(reverse("legal_notice"))
        self.assertEqual(response.status_code, 200)
        hebergement = _section(response.content.decode(), "hebergement", "documents")
        self.assertNotIn("Tél", hebergement)
        self.assertNotIn("None", hebergement)

    @override_settings(LEGAL_ENTITY_RCCM="", LEGAL_ENTITY_ADDRESS="")
    def test_notice_with_missing_values_does_not_crash_nor_show_empty_rows(self):
        response = self.client.get(reverse("legal_notice"))
        self.assertEqual(response.status_code, 200)
        editeur = _section(response.content.decode(), "editeur", "publication")
        self.assertNotIn("RCCM", editeur)
        self.assertNotIn("Siège", editeur)

    def test_no_civil_name_nor_phone_in_notice(self):
        """Décision fondateur (F-143) : ni nom civil ni téléphone de l'exploitant."""
        html = self.get("legal_notice")
        editeur = _section(html, "editeur", "contact")
        self.assertNotIn("Tél", editeur)
        self.assertNotIn("+", editeur)

    def test_privacy_and_terms_name_the_entity_from_settings(self):
        privacy = self.get("legal_privacy")
        terms = self.get("legal_terms")
        self.assertIn("EXPLOITATION-TEST, entreprise individuelle", privacy)
        self.assertIn("EXPLOITATION-TEST, entreprise individuelle", terms)

    def test_privacy_recipients_mention_a_host_established_in_france(self):
        destinataires = _section(self.get("legal_privacy"), "destinataires", "conservation")
        self.assertIn("hébergeur établi en France", destinataires)
        self.assertNotRegex(destinataires, r"serveur[s]? (est|sont|situé|localisé)")

    def test_privacy_retention_section_is_untouched(self):
        conservation = _section(self.get("legal_privacy"), "conservation", "droits")
        self.assertIn("dix ans, droit comptable OHADA", conservation)
        self.assertIn("cinq ans, délai de prescription du droit commercial OHADA", conservation)


class LegalHostSettingsTests(TestCase):
    KEYS = ("LEGAL_HOST_NAME", "LEGAL_HOST_ADDRESS", "LEGAL_HOST_PHONE")

    def test_settings_exist_in_test_settings(self):
        for key in self.KEYS:
            self.assertTrue(hasattr(settings, key), key)

    def test_base_defaults_are_empty(self):
        import importlib
        import os

        base = importlib.import_module("config.settings.base")
        for key in self.KEYS:
            expected = os.environ.get(key, "").strip()
            self.assertEqual(getattr(base, key), expected, key)

    def test_env_example_lists_host_variables(self):
        text = (Path(settings.BASE_DIR) / ".env.example").read_text(encoding="utf-8")
        for key in self.KEYS:
            self.assertRegex(text, rf"(?m)^{key}=$", key)
