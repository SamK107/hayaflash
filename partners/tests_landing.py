"""F-122 : /r/<code>/ renvoie vers l'accueil, qui affiche une bannière d'inscription.

Comportement neutre : tous les cas non valides (inconnu, en pause, terminé, place libérée, expiré, code
mal formé) sont identiques entre eux : 302 vers /, sans cookie, sans clic, corps vide. Le cas valide pose
le cookie hf_ref (30 jours) et enregistre le clic. La bannière de l'accueil n'apparaît que pour un
visiteur non connecté dont le cookie désigne un partenaire éligible ; elle n'affiche que son prénom.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.tests_register_security import payload
from partners.models import Partner, PartnerClick, Referral
from partners.tests_models import make_partner

BANNER_TITLE = "Pour utiliser HayaFlash, créez votre compte"
BANNER_BUTTON = "Créer mon compte"


def home(client, code=None):
    if code is not None:
        client.cookies["hf_ref"] = code
    return client.get("/")


def banner(html: str) -> str:
    start = html.find('id="partner-banner"')
    if start < 0:
        return ""
    return html[start : html.index("</aside>", start)]


class LinkRedirectsToTheHomePageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.partner = make_partner(code="AWA2026", phone="+22360000001", name="Awa Diarra")

    def test_valid_code_redirects_to_home_with_click_and_cookie(self):
        resp = self.client.get("/r/AWA2026/", REMOTE_ADDR="196.200.1.1")
        self.assertEqual((resp.status_code, resp["Location"]), (302, "/"))
        self.assertEqual(resp.content, b"")
        cookie = resp.cookies["hf_ref"]
        self.assertEqual(cookie.value, "AWA2026")
        self.assertEqual(int(cookie["max-age"]), 30 * 24 * 3600)
        self.assertEqual(PartnerClick.objects.filter(partner=self.partner).count(), 1)

    def test_every_invalid_case_is_identical_and_does_nothing(self):
        make_partner(code="PAUSE01", phone="+22360000011", status="paused")
        make_partner(code="ENDED01", phone="+22360000012", status="ended")
        make_partner(code="FREE001", phone="+22360000013", status="slot_released")
        expired = make_partner(code="OLD0001", phone="+22360000014")
        Partner.objects.filter(pk=expired.pk).update(contract_end=timezone.localdate() - timedelta(days=1))
        seen = set()
        for code in ("NOSUCH1", "PAUSE01", "ENDED01", "FREE001", "OLD0001", "@@", "x" * 40):
            with self.subTest(code=code):
                resp = self.client.get(f"/r/{code}/")
                self.assertNotIn("hf_ref", resp.cookies)
                seen.add((resp.status_code, resp["Location"], resp.content))
        self.assertEqual(seen, {(302, "/", b"")})
        self.assertEqual(PartnerClick.objects.count(), 0)

    def test_the_valid_response_differs_only_by_the_cookie(self):
        ok = self.client.get("/r/AWA2026/")
        bad = self.client.get("/r/NOSUCH1/")
        self.assertEqual((ok.status_code, ok["Location"], ok.content), (bad.status_code, bad["Location"], bad.content))
        self.assertIn("hf_ref", ok.cookies)
        self.assertNotIn("hf_ref", bad.cookies)

    @override_settings(RATELIMIT_ENABLE=True, RATELIMIT_REFERRAL_IP=(2, 60))
    def test_rate_limit_is_unchanged_and_still_redirects_to_home(self):
        for _ in range(2):
            self.client.get("/r/AWA2026/", REMOTE_ADDR="196.200.9.9")
        limited = self.client.get("/r/AWA2026/", REMOTE_ADDR="196.200.9.9")
        self.assertEqual((limited.status_code, limited["Location"]), (302, "/"))
        self.assertNotIn("hf_ref", limited.cookies)
        self.assertEqual(PartnerClick.objects.count(), 2)

    def test_the_target_stays_fixed(self):
        for qs in ("?next=https://evil.example/", "?url=//evil.example"):
            self.assertEqual(self.client.get(f"/r/AWA2026/{qs}")["Location"], "/")


class HomeBannerTests(TestCase):
    def setUp(self):
        cache.clear()
        self.partner = make_partner(code="AWA2026", phone="+22360000001", name="Awa Diarra")

    def test_home_is_200_with_and_without_cookie(self):
        self.assertEqual(Client().get("/").status_code, 200)
        self.assertEqual(home(Client(), "AWA2026").status_code, 200)
        self.assertEqual(home(Client(), "ZZZZZZZ").status_code, 200)

    def test_banner_is_shown_with_a_valid_cookie(self):
        html = home(Client(), "AWA2026").content.decode()
        text = banner(html)
        self.assertIn(BANNER_TITLE, text)
        self.assertIn(BANNER_BUTTON, text)
        self.assertIn(f'href="{reverse("register")}"', text)

    def test_banner_is_absent_without_a_cookie(self):
        html = Client().get("/").content.decode()
        self.assertEqual(banner(html), "")
        self.assertNotIn(BANNER_TITLE, html)

    def test_banner_is_absent_with_an_unknown_or_malformed_cookie(self):
        for code in ("NOSUCH1", "@@", "x" * 40, ""):
            with self.subTest(code=code):
                html = home(Client(), code).content.decode()
                self.assertEqual(banner(html), "")
                self.assertNotIn(BANNER_TITLE, html)

    def test_banner_is_absent_when_the_partner_became_ineligible(self):
        for status in ("paused", "ended", "slot_released"):
            with self.subTest(status=status):
                Partner.objects.filter(pk=self.partner.pk).update(status=status)
                self.assertEqual(banner(home(Client(), "AWA2026").content.decode()), "")
        Partner.objects.filter(pk=self.partner.pk).update(
            status="active", contract_end=timezone.localdate() - timedelta(days=1)
        )
        self.assertEqual(banner(home(Client(), "AWA2026").content.decode()), "")

    def test_banner_is_absent_for_a_logged_in_visitor(self):
        client = Client()
        user = make_user_and_login(client)
        self.assertTrue(user.is_authenticated)
        self.assertEqual(banner(home(client, "AWA2026").content.decode()), "")

    def test_only_the_first_name_is_shown(self):
        text = banner(home(Client(), "AWA2026").content.decode())
        self.assertIn("Awa", text)
        self.assertNotIn("Diarra", text)
        self.assertNotIn("22360000001", text)
        self.assertNotIn("60000001", text)

    def test_first_word_of_a_compound_name(self):
        for name, shown, hidden in (("Awa-Fanta Diarra", "Awa-Fanta", "Diarra"), ("  Moussa   Traoré Kane ", "Moussa", "Traoré")):
            with self.subTest(name=name):
                Partner.objects.filter(pk=self.partner.pk).update(name=name)
                text = banner(home(Client(), "AWA2026").content.decode())
                self.assertIn(shown, text)
                self.assertNotIn(hidden, text)

    def test_no_name_is_shown_when_the_name_is_empty(self):
        Partner.objects.filter(pk=self.partner.pk).update(name="   ")
        text = banner(home(Client(), "AWA2026").content.decode())
        self.assertIn(BANNER_TITLE, text)  # la bannière reste utile, sans nom
        self.assertNotIn("None", text)
        self.assertNotIn("lien de", text.lower())

    def test_shop_name_is_never_shown(self):
        Partner.objects.filter(pk=self.partner.pk).update(shop_name="Boutique Secrète")
        self.assertNotIn("Secrète", banner(home(Client(), "AWA2026").content.decode()))

    def test_a_failure_of_the_partners_lookup_never_breaks_the_home_page(self):
        with patch("partners.services.attribution.find_partner_for_new_referral", side_effect=RuntimeError("boom")):
            resp = home(Client(), "AWA2026")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(banner(resp.content.decode()), "")

    def test_the_vocabulary_of_the_programme_is_respected(self):
        text = banner(home(Client(), "AWA2026").content.decode()).lower()
        for word in ("parrain", "filleul", "recommand", "garanti", "certifi", "signé"):
            self.assertNotIn(word, text)


def make_user_and_login(client):
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(phone="+22379000077", password="x", display_name="V")
    client.force_login(user)
    return user


class SignupFromTheHomePageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.partner = make_partner(code="AWA2026", phone="+22360000001")

    def test_link_then_home_then_register_attributes_the_seller(self):
        client = Client()
        landing = client.get("/r/AWA2026/", REMOTE_ADDR="196.200.1.1")
        self.assertEqual(landing["Location"], "/")
        page = client.get("/")  # le cookie posé par /r/ est renvoyé
        self.assertIn(BANNER_TITLE, banner(page.content.decode()))
        self.assertEqual(client.get(reverse("register")).status_code, 200)
        resp = client.post(reverse("register"), payload(phone="+22370000301"))
        self.assertEqual(resp.status_code, 302)
        referral = Referral.objects.get(seller__user__phone="+22370000301")
        self.assertEqual(referral.partner, self.partner)
        self.assertEqual(referral.source, "link")
