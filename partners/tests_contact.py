"""BLOC H4 : page staff « Contacter » (lien WhatsApp prérempli, aucun envoi automatique)."""

from __future__ import annotations

import hashlib
import re
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import SellerProfile
from partners.models import OutboundMessage, Partner, PartnerAccessLink
from partners.services import messages as msg
from partners.tests_models import make_partner

User = get_user_model()
PLATFORM = "/platform-admin/"
WA_RE = re.compile(r'href="(https://wa\.me/[^"]+)"')
GOOD_TEXT = "Bonjour {prénom}, voici la lettre d'essai à lire et accepter : {lien}"


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user(
            phone="+22379000001", password="x", display_name="Alex Équipe", is_staff=True
        )
        self.client = Client()
        self.client.force_login(self.staff)
        self.url = reverse("partners_contact")

    def send(self, **over):
        data = dict(
            action="send", country="223", phone_national="70 00 00 01", first_name="Awa",
            shop_name="", template_key="envoi_lettre_essai", message=GOOD_TEXT,
        )
        data.update(over)
        return self.client.post(self.url, data)

    def wa_url(self, resp):
        match = WA_RE.search(resp.content.decode())
        self.assertIsNotNone(match, "lien WhatsApp absent")
        return match.group(1).replace("&amp;", "&")


class TemplatesTests(TestCase):
    def test_four_templates_with_the_expected_keys(self):
        self.assertEqual(
            set(msg.TEMPLATES), {"invitation_essai", "envoi_lettre_essai", "envoi_conditions", "relance"}
        )

    def test_invitation_is_the_provided_text(self):
        text = msg.TEMPLATES["invitation_essai"]
        for piece in (
            "Bonjour {prénom},",
            "J'ai suivi ton live, bravo pour {détail à compléter par le staff}.",
            "Je suis {ton nom}, j'ai créé HayaFlash",
            "plan Pro offert",
            "{lien}",
            "Ça t'intéresse ?",
        ):
            self.assertIn(piece, text)

    def test_other_templates(self):
        self.assertIn("Voici la lettre d'essai à lire et accepter : {lien}", msg.TEMPLATES["envoi_lettre_essai"])
        self.assertIn("Voici les conditions du programme partenaire : {lien}", msg.TEMPLATES["envoi_conditions"])
        self.assertIn("Il reste {places} places.", msg.TEMPLATES["envoi_conditions"])
        self.assertIn("{lien}", msg.TEMPLATES["relance"])

    def test_whatsapp_url_is_encoded_and_has_no_plus(self):
        url = msg.whatsapp_url("+22370000001", "Salut & à bientôt ?")
        parsed = urlparse(url)
        self.assertEqual((parsed.scheme, parsed.netloc, parsed.path), ("https", "wa.me", "/22370000001"))
        self.assertEqual(parse_qs(parsed.query)["text"], ["Salut & à bientôt ?"])
        self.assertNotIn(" ", url)
        self.assertNotIn("&à", url)


class AccessTests(Base):
    def test_anonymous_and_seller_get_the_platform_answer(self):
        platform = Client().get(PLATFORM)
        for target in (self.url, reverse("partners_messages")):
            resp = Client().get(target)
            self.assertEqual(resp.status_code, platform.status_code)
            self.assertEqual(resp["Location"].split("?")[0], platform["Location"].split("?")[0])
        user = User.objects.create_user(phone="+22379000002", password="x", display_name="V")
        SellerProfile.objects.create(user=user)
        seller = Client()
        seller.force_login(user)
        self.assertEqual(seller.get(self.url).status_code, platform.status_code)
        self.assertEqual(seller.post(self.url, {"action": "send"}).status_code, platform.status_code)
        self.assertEqual(OutboundMessage.objects.count(), 0)

    def test_staff_opens_the_page_and_sees_the_no_auto_send_notice(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Rien n'est envoyé automatiquement")
        self.assertContains(resp, "+223")
        for key in msg.TEMPLATES:
            self.assertContains(resp, key)

    def test_post_requires_csrf(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.staff)
        self.assertEqual(strict.post(self.url, {"action": "send"}).status_code, 403)

    def test_page_has_no_sender_script_or_form_action_to_whatsapp(self):
        html = self.client.get(self.url).content.decode()
        self.assertNotIn("wa.me", html)  # le lien n'existe qu'après génération


class SendTests(Base):
    def test_builds_the_exact_encoded_url_and_opens_in_a_new_tab(self):
        resp = self.send()
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('target="_blank"', html)
        self.assertIn('rel="noopener"', html)
        url = self.wa_url(resp)
        parsed = urlparse(url)
        self.assertEqual(parsed.path, "/22370000001")
        body = parse_qs(parsed.query)["text"][0]
        self.assertTrue(body.startswith("Bonjour Awa, voici la lettre d'essai à lire et accepter : http"))
        self.assertIn("/partenaires/d/", body)
        self.assertNotIn("{", body)

    def test_creates_a_prospect_when_unknown(self):
        self.send()
        p = Partner.objects.get(phone="+22370000001")
        self.assertEqual((p.status, p.phase, p.name), ("prospect", "none", "Awa"))
        self.assertFalse(p.is_founder)
        self.assertRegex(p.code, r"^[A-Z0-9]{4,12}$")

    def test_existing_partner_is_reused_not_duplicated(self):
        existing = make_partner(code="AWA2026", phone="+22370000001", name="Awa Diarra")
        self.send()
        self.send()
        self.assertEqual(Partner.objects.filter(phone="+22370000001").count(), 1)
        self.assertEqual(OutboundMessage.objects.filter(partner=existing).count(), 2)

    def test_access_link_is_created_and_token_is_not_logged_in_clear(self):
        resp = self.send()
        body = parse_qs(urlparse(self.wa_url(resp)).query)["text"][0]
        token = re.search(r"/partenaires/d/([^/\s]+)/", body).group(1)
        link = PartnerAccessLink.objects.get()
        self.assertEqual((link.purpose, link.token_hash), ("accept", hashlib.sha256(token.encode()).hexdigest()))
        self.assertIsNotNone(link.expires_at)
        stored = OutboundMessage.objects.get()
        self.assertNotIn(token, stored.body_text)
        self.assertIn("Bonjour Awa", stored.body_text)
        journal = self.client.get(reverse("partners_messages")).content.decode()
        detail = self.client.get(reverse("partners_message_detail", args=[stored.pk])).content.decode()
        self.assertNotIn(token, journal)
        self.assertNotIn(token, detail)

    def test_no_link_when_the_text_has_none(self):
        self.send(message="Bonjour {prénom}, un petit coucou.")
        self.assertEqual(PartnerAccessLink.objects.count(), 0)

    def test_places_variable(self):
        self.send(template_key="envoi_conditions", message=msg.TEMPLATES["envoi_conditions"])
        stored = OutboundMessage.objects.get()
        self.assertIn("Il reste 20 places.", stored.body_text)

    def test_ton_nom_is_filled_with_the_staff_name_and_detail_must_be_completed(self):
        raw = msg.TEMPLATES["invitation_essai"]
        refused = self.send(template_key="invitation_essai", message=raw)
        self.assertContains(refused, "détail à compléter par le staff")
        self.assertEqual(OutboundMessage.objects.count(), 0)
        ok = self.send(
            template_key="invitation_essai",
            message=raw.replace("{détail à compléter par le staff}", "ton dernier live sur les pagnes"),
        )
        self.assertEqual(ok.status_code, 200)
        body = OutboundMessage.objects.get().body_text
        self.assertIn("Je suis Alex Équipe", body)
        self.assertIn("ton dernier live sur les pagnes", body)

    def test_missing_first_name_is_refused(self):
        for name in ("", "  "):
            resp = self.send(first_name=name)
            self.assertContains(resp, "prénom")
        self.assertEqual(OutboundMessage.objects.count(), 0)
        self.assertEqual(Partner.objects.count(), 0)

    def test_invalid_numbers_are_refused_and_nothing_is_created(self):
        for national in ("7000", "700000012345", "abcdefgh", "", "0022370000001"):
            with self.subTest(national=national):
                resp = self.send(phone_national=national)
                self.assertEqual(resp.status_code, 200)
                self.assertNotIn("wa.me", resp.content.decode())
        self.assertEqual(OutboundMessage.objects.count(), 0)
        self.assertEqual(Partner.objects.count(), 0)

    def test_no_country_is_ever_guessed(self):
        for country in ("", "999", "mali"):
            with self.subTest(country=country):
                resp = self.send(country=country)
                self.assertNotIn("wa.me", resp.content.decode())
        self.assertEqual(Partner.objects.count(), 0)

    def test_another_valid_country_is_accepted_with_its_own_length(self):
        ok = self.send(country="221", phone_national="77 123 45 67")
        self.assertEqual(urlparse(self.wa_url(ok)).path, "/221771234567")
        bad = self.send(country="221", phone_national="70 00 00 01")  # 8 chiffres : invalide au Sénégal
        self.assertNotIn("wa.me", bad.content.decode())

    def test_too_long_message_is_refused(self):
        resp = self.send(message="Bonjour {prénom} " + "x" * 1000)
        self.assertContains(resp, "1 000 caractères")
        self.assertEqual(OutboundMessage.objects.count(), 0)

    def test_unresolved_variable_is_refused(self):
        resp = self.send(message="Bonjour {prénom}, {boutique} {inconnu}")
        self.assertContains(resp, "{inconnu}")
        self.assertEqual(OutboundMessage.objects.count(), 0)

    def test_shop_variable_needs_a_value(self):
        refused = self.send(message="Bonjour {prénom}, pour {boutique}")
        self.assertContains(refused, "{boutique}")
        ok = self.send(message="Bonjour {prénom}, pour {boutique}", shop_name="Chez Fanta")
        self.assertEqual(ok.status_code, 200)
        self.assertIn("pour Chez Fanta", OutboundMessage.objects.get().body_text)

    def test_preview_creates_nothing_and_shows_the_message(self):
        resp = self.send(action="preview")
        self.assertContains(resp, "Bonjour Awa")
        self.assertEqual(OutboundMessage.objects.count(), 0)
        self.assertEqual(Partner.objects.count(), 0)
        self.assertEqual(PartnerAccessLink.objects.count(), 0)
        self.assertNotIn("wa.me", resp.content.decode())

    def test_no_outgoing_network_call(self):
        with patch("requests.sessions.Session.request", side_effect=AssertionError("réseau")), patch(
            "urllib.request.urlopen", side_effect=AssertionError("réseau")
        ), patch("socket.socket.connect", side_effect=AssertionError("réseau")):
            self.assertEqual(self.send().status_code, 200)
            self.assertEqual(self.send(action="preview").status_code, 200)

    def test_staff_is_recorded_on_the_journal(self):
        self.send()
        self.assertEqual(OutboundMessage.objects.get().created_by, self.staff)
        self.assertEqual(OutboundMessage.objects.get().phone_e164, "+22370000001")


class JournalTests(Base):
    def test_journal_lists_messages_with_date_template_and_partner(self):
        self.send()
        resp = self.client.get(reverse("partners_messages"))
        self.assertContains(resp, "envoi_lettre_essai")
        self.assertContains(resp, "Awa")
        self.assertContains(resp, "+22370000001")

    def test_full_text_is_viewable_by_staff_only(self):
        self.send()
        stored = OutboundMessage.objects.get()
        url = reverse("partners_message_detail", args=[stored.pk])
        self.assertContains(self.client.get(url), "Bonjour Awa")
        self.assertNotEqual(Client().get(url).status_code, 200)

    def test_prefill_from_a_partner(self):
        p = make_partner(code="AWA2026", phone="+22370000001", name="Awa Diarra")
        resp = self.client.get(self.url, {"partner": p.pk})
        self.assertContains(resp, 'value="70000001"')
        self.assertContains(resp, 'value="Awa Diarra"')
