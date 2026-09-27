"""Pages légales, liens de pied de page, acceptation des CGU à l'inscription."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, modify_settings
from django.urls import reverse
from django.utils import timezone

from core.models import LegalAcceptance, LegalDocument

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
