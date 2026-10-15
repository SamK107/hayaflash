"""F-135 : la lettre d'essai v1.0 est remplacée par la « lettre de phase d'évaluation » v1.1.

Aucun partenaire réel n'a accepté la v1.0 (seulement des comptes de test) : la v1.0 reste
lisible et valide, mais une nouvelle acceptation se fait sur la v1.1. Conditions v1.0 inchangées.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from partners import legal_docs
from partners.models import AcceptanceDocType, OutboundMessage, PartnerAcceptance
from partners.services import messages as msg
from partners.services.acceptance import (
    accept_document,
    has_valid_letter,
    pending_document,
)
from partners.services.access_links import create_link
from partners.tests_documents import BANNED_RE, FACTICE, fake_partner
from partners.tests_models import make_partner

# Empreintes verrouillées des textes publiés (rendus avec FACTICE et un partenaire fictif).
LETTER_V1_0 = "187ca2e0d84a84a4cf77eeb024c73f1143a6d8a6444380f84ada6b2a0583b019"
TERMS_V1_0 = "3084d462f872c77ace9ace8a5aea70283812d1ba46d78a2b98da970d8d7c55e6"
LETTER_V1_1_SHA = "fa42e8d4e19121527aab44d5593898e39014c8694a50f26e8e4beb9409acb166"
LETTER_V1_1_ACK = "J'ai lu et j'accepte la lettre de phase d'évaluation version 1.1"


def hash_of(doc_type: str, version: str) -> str:
    html = legal_docs.render_document(doc_type, fake_partner(), version=version)
    return legal_docs.sha256_of(legal_docs.canonical_text(html))


def v1_0_letter(partner):
    """Acceptation v1.0 telle qu'elle existe déjà en base (comptes de test)."""
    return PartnerAcceptance.objects.create(
        partner=partner, doc_type="trial_letter", doc_version="1.0",
        text_snapshot="<p>Lettre d'essai v1.0</p>", text_sha256=LETTER_V1_0,
        signer_name=partner.name, accepted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        method="written_manual", manual_reference="Fixture de test",
    )


@override_settings(**FACTICE)
class PublishedVersionsTests(SimpleTestCase):
    def test_v1_1_stays_published_even_though_v1_2_is_now_current(self):
        # La v1.1 a été fusionnée (PR #73) : elle reste publiée, rendable et verrouillée (F-135).
        self.assertIn("1.1", legal_docs.PUBLISHED["trial_letter"])
        self.assertEqual(legal_docs.PROGRAM_TERMS_VERSION, "1.0")

    def test_published_versions_table_lists_every_letter(self):
        self.assertEqual(legal_docs.PUBLISHED["trial_letter"], {
            "1.0": "partners/legal/trial_letter_v1_0.html",
            "1.1": "partners/legal/trial_letter_v1_1.html",
            "1.2": "partners/legal/trial_letter_v1_2.html",
        })
        self.assertEqual(
            legal_docs.PUBLISHED["program_terms"], {"1.0": "partners/legal/program_terms_v1_0.html"}
        )

    def test_every_published_template_exists(self):
        for versions in legal_docs.PUBLISHED.values():
            for template in versions.values():
                self.assertTrue((Path(settings.BASE_DIR) / "templates" / template).exists(), template)

    def test_sha256_of_every_published_text_is_locked(self):
        self.assertEqual(hash_of("trial_letter", "1.0"), LETTER_V1_0)
        self.assertEqual(hash_of("program_terms", "1.0"), TERMS_V1_0)
        self.assertEqual(hash_of("trial_letter", "1.1"), LETTER_V1_1_SHA)

    def test_unknown_version_is_refused(self):
        with self.assertRaises(KeyError):
            legal_docs.render_document("trial_letter", fake_partner(), version="9.9")


@override_settings(**FACTICE)
class LetterTextTests(SimpleTestCase):
    def html(self):
        return legal_docs.render_document("trial_letter", fake_partner(), version="1.1")

    def test_title_and_ack_use_the_evaluation_vocabulary(self):
        html = self.html()
        self.assertIn("lettre de phase d'évaluation. Version 1.1.", html)
        self.assertIn(LETTER_V1_1_ACK, html)

    def test_text_speaks_of_an_evaluation_phase_not_a_trial(self):
        html = self.html()
        self.assertIn("phase d'évaluation", html)
        for old in ("lettre d'essai", "l'essai", "Utiliser HayaFlash pour vos ventes en direct, au moins"):
            self.assertNotIn(old, html)

    def test_no_activity_minimum_and_no_remuneration(self):
        html = self.html()
        self.assertIn("Aucune activité minimale ne vous est imposée.", html)
        self.assertIn("Aucune rémunération n'est due pendant cette phase.", html)
        self.assertIn("aucune admission au programme partenaire", html)

    def test_same_variables_as_v1_0(self):
        html = self.html()
        for expected in (
            "ENTREPRISE TEST SARL", "Awa Diarra", "+22370000001", "Boutique Test",
            "contact@test.example", "le tribunal de commerce de Bamako", "ML-BKO-2026-B-00000",
        ):
            self.assertIn(expected, html)
        self.assertTrue(html.rstrip().endswith("Version 1.1.</p>\n</div>") or "Version 1.1.</p>" in html[-60:])

    def test_no_banned_word(self):
        self.assertIsNone(BANNED_RE.search(self.html()))

    def test_templates_partners_stay_clean(self):
        offenders = []
        for path in (Path(settings.BASE_DIR) / "templates" / "partners").rglob("*.html"):
            if BANNED_RE.search(path.read_text(encoding="utf-8")):
                offenders.append(path.name)
        self.assertEqual(offenders, [])


@override_settings(**FACTICE)
class NewPartnerGetsV1_1Tests(TestCase):
    def setUp(self):
        cache.clear()
        self.prospect = make_partner(
            code="PROS011", phone="+22360050011", name="Awa Diarra", status="prospect", phase="none",
            accept=False,
        )
        self.link, self.token = create_link(self.prospect, "accept", days=30)
        self.client = Client(enforce_csrf_checks=True)

    def test_enum_label_is_the_evaluation_letter(self):
        self.assertEqual(AcceptanceDocType.TRIAL_LETTER.label, "Lettre d'essai")  # F-135 : revenu à « essai » (0003)


@override_settings(**FACTICE)
class ExistingV1_0StaysValidTests(TestCase):
    def test_a_v1_0_letter_is_still_a_valid_letter(self):
        partner = make_partner(code="OLD0001", phone="+22360050021", phase="trial", accept=False)
        v1_0_letter(partner)
        self.assertTrue(has_valid_letter(partner))

    def test_a_prospect_with_a_v1_0_letter_is_not_asked_again(self):
        partner = make_partner(
            code="OLD0002", phone="+22360050022", status="prospect", phase="none", accept=False
        )
        v1_0_letter(partner)
        self.assertIsNone(pending_document(partner))

    def test_a_trial_partner_with_a_v1_0_letter_is_not_asked_for_v1_1(self):
        partner = make_partner(code="OLD0003", phone="+22360050023", phase="trial", accept=False)
        v1_0_letter(partner)
        self.assertIsNone(pending_document(partner))

    def test_the_v1_0_acceptance_stays_readable_from_its_snapshot(self):
        partner = make_partner(code="OLD0004", phone="+22360050024", phase="trial", accept=False)
        acc = v1_0_letter(partner)
        _, token = create_link(partner, "view", days=30)
        resp = self.client.get(reverse("partner_doc_page", args=[token]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PartnerAcceptance.objects.get(pk=acc.pk).doc_version, "1.0")

    def test_a_v1_1_letter_is_valid_and_not_asked_again(self):
        partner = make_partner(
            code="OLD0005", phone="+22360050025", status="prospect", phase="none", accept=False
        )
        PartnerAcceptance.objects.create(
            partner=partner, doc_type="trial_letter", doc_version="1.1",
            text_snapshot="<p>Lettre v1.1</p>", text_sha256=LETTER_V1_1_SHA,
            signer_name=partner.name, accepted_at=datetime(2026, 10, 14, tzinfo=timezone.utc),
            method="written_manual", manual_reference="Fixture de test",
        )
        self.assertTrue(has_valid_letter(partner))
        self.assertIsNone(pending_document(partner))

    def test_the_v1_0_text_is_still_renderable_for_the_lock(self):
        html = legal_docs.render_document("trial_letter", fake_partner(), version="1.0")
        self.assertIn("lettre d'essai. Version 1.0.", html)


@override_settings(**FACTICE)
class TermsAfterEitherLetterTests(TestCase):
    def invite(self, partner):
        OutboundMessage.objects.create(
            partner=partner, phone_e164=partner.phone, template_key="envoi_conditions",
            body_text="Conditions : (jeton non conservé)",
        )

    def test_terms_are_acceptable_after_a_v1_0_letter(self):
        partner = make_partner(code="TRM0001", phone="+22360050031", phase="trial", accept=False)
        v1_0_letter(partner)
        self.invite(partner)
        self.assertEqual(pending_document(partner), "program_terms")
        acc, created = accept_document(partner, "program_terms", signer_name="Awa")
        self.assertTrue(created)
        self.assertEqual(acc.doc_version, "1.0")

    def test_terms_are_acceptable_after_a_v1_1_letter(self):
        partner = make_partner(
            code="TRM0002", phone="+22360050032", phase="trial", accept=False
        )
        PartnerAcceptance.objects.create(
            partner=partner, doc_type="trial_letter", doc_version="1.1",
            text_snapshot="<p>Lettre v1.1</p>", text_sha256=LETTER_V1_1_SHA,
            signer_name=partner.name, accepted_at=datetime(2026, 10, 14, tzinfo=timezone.utc),
            method="written_manual", manual_reference="Fixture de test",
        )
        self.invite(partner)
        self.assertEqual(pending_document(partner), "program_terms")
        acc, created = accept_document(partner, "program_terms", signer_name="Awa")
        self.assertTrue(created)
        self.assertEqual(acc.doc_version, "1.0")


@override_settings(**FACTICE)
class BriefAndConditionsMessageTests(TestCase):
    def test_brief_v1_1_has_no_remaining_places_counter(self):
        html = legal_docs.render_brief(places=5, version="1.1")  # F-135 : texte publié, gardé tel quel
        self.assertIn("Places limitées, sélection à l'issue de la phase", html)
        self.assertNotIn("Il reste", html)
        self.assertNotIn("5 places", html)
        self.assertIsNone(BANNED_RE.search(html))

    def test_brief_v1_0_template_is_untouched(self):
        raw = (Path(settings.BASE_DIR) / "templates/partners/legal/partner_brief_v1_0.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("Il reste {{ places }} places.", raw)
        self.assertTrue((Path(settings.BASE_DIR) / "templates/partners/legal/partner_brief_v1_1.html").exists())

    def test_conditions_message_no_longer_counts_places(self):
        text = msg.TEMPLATES["envoi_conditions"]
        # Remplacé par « l'issue de l'essai » avec la v1.2 (tests_letter_v1_2.py) ; le compteur reste absent.
        self.assertIn("Places limitées, sélection à l'issue de", text)
        self.assertNotIn("Il reste", text)
        self.assertNotIn("{places}", text)

    def test_visible_strings_say_trial_letter_again_with_v1_2(self):
        # F-135 (v1.2) : le vocabulaire « évaluation » de la v1.1 est abandonné ; l'invitation est remplacée
        # (tests_letter_v1_2.py). Le modèle d'envoi de la lettre dit de nouveau « lettre d'essai ».
        self.assertIn("lettre d'essai", msg.TEMPLATES["envoi_lettre_essai"])
        self.assertEqual(msg.LABELS["envoi_lettre_essai"], "Envoi de la lettre d'essai")
