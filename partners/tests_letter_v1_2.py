"""F-135 : la lettre d'essai passe en version 1.2 (six articles, sans obligation d'activité).

La v1.1 « lettre de phase d'évaluation » est déjà fusionnée (PR #73) : elle reste publiée et verrouillée.
La v1.2 s'ajoute à la table des versions publiées et devient la version courante : une nouvelle acceptation
se fait sur la v1.2 ; les lettres v1.0 et v1.1 restent valides. Conditions v1.0 inchangées. Aucune migration :
le vocabulaire redevient « essai » partout (migration 0003 : libellés seulement, aucun SQL).
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
LETTER_V1_2_SHA = "e1207c5a5baa80b033ae73215739bcc10a766157ffb93e3eae1eeee4a568f1eb"
LETTER_V1_2_ACK = "J'ai lu et j'accepte la lettre d'essai version 1.2"

INVITATION = (
    "Bonjour {prénom}, c'est {ton nom} de HayaFlash. Je propose à quelques vendeurs de live un essai "
    "de 30 jours : accès gratuit au plan Pro et accompagnement pour votre première vente. Si cela vous "
    "intéresse, je vous envoie la lettre à lire et à accepter. Répondez-moi ici."
)


def hash_of(doc_type: str, version: str) -> str:
    html = legal_docs.render_document(doc_type, fake_partner(), version=version)
    return legal_docs.sha256_of(legal_docs.canonical_text(html))


def v1_0_letter(partner):
    """Acceptation v1.0 telle qu'elle existe déjà en base (comptes de test)."""
    return PartnerAcceptance.objects.create(
        partner=partner,
        doc_type="trial_letter",
        doc_version="1.0",
        text_snapshot="<p>Lettre d'essai v1.0</p>",
        text_sha256=LETTER_V1_0,
        signer_name=partner.name,
        accepted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        method="written_manual",
        manual_reference="Fixture de test",
    )


@override_settings(**FACTICE)
class PublishedVersionsTests(SimpleTestCase):
    def test_the_current_letter_is_v1_2_and_the_terms_stay_v1_0(self):
        self.assertEqual(legal_docs.TRIAL_LETTER_VERSION, "1.2")
        self.assertEqual(legal_docs.DOCS["trial_letter"]["version"], "1.2")
        self.assertEqual(legal_docs.PROGRAM_TERMS_VERSION, "1.0")

    def test_published_versions_table_keeps_1_0_and_1_1_and_adds_1_2(self):
        self.assertEqual(
            legal_docs.PUBLISHED["trial_letter"],
            {
                "1.0": "partners/legal/trial_letter_v1_0.html",
                "1.1": "partners/legal/trial_letter_v1_1.html",
                "1.2": "partners/legal/trial_letter_v1_2.html",
            },
        )
        self.assertEqual(
            legal_docs.PUBLISHED["program_terms"],
            {"1.0": "partners/legal/program_terms_v1_0.html"},
        )

    def test_every_published_template_exists(self):
        for versions in legal_docs.PUBLISHED.values():
            for template in versions.values():
                self.assertTrue((Path(settings.BASE_DIR) / "templates" / template).exists(), template)

    def test_sha256_of_every_published_text_is_locked(self):
        self.assertEqual(hash_of("trial_letter", "1.0"), LETTER_V1_0)
        self.assertEqual(hash_of("trial_letter", "1.1"), LETTER_V1_1_SHA)
        self.assertEqual(hash_of("program_terms", "1.0"), TERMS_V1_0)
        self.assertEqual(hash_of("trial_letter", "1.2"), LETTER_V1_2_SHA)

    def test_unknown_version_is_refused(self):
        with self.assertRaises(KeyError):
            legal_docs.render_document("trial_letter", fake_partner(), version="9.9")


@override_settings(**FACTICE)
class LetterTextTests(SimpleTestCase):
    def html(self):
        return legal_docs.render_document("trial_letter", fake_partner(), version="1.2")

    def test_title_and_ack(self):
        html = self.html()
        self.assertIn("lettre d'essai. Version 1.2.", html)
        self.assertIn(LETTER_V1_2_ACK, html)
        self.assertEqual(legal_docs.DOCS["trial_letter"]["ack"], LETTER_V1_2_ACK)
        self.assertEqual(legal_docs.DOCS["trial_letter"]["label"], "Lettre d'essai")

    def test_six_articles_no_governing_law_article(self):
        html = self.html()
        for title in (
            "1. Ce que HayaFlash vous offre",
            "2. Ce que nous vous proposons",
            "3. Votre lien personnel",
            "4. Votre liberté",
            "5. Fin de l'essai",
            "6. Données personnelles",
        ):
            self.assertIn(title, html)
        self.assertNotIn("7. ", html)
        self.assertNotIn("Droit applicable", html)

    def test_no_obligation_of_activity_or_feedback(self):
        html = self.html()
        self.assertIn("nous faire part de vos retours quand vous le souhaitez", html)
        self.assertIn("Pendant l'essai, il n'y a pas de rémunération.", html)
        for old in ("au moins 2 fois par semaine", "Aucune activité minimale", "phase d'évaluation"):
            self.assertNotIn(old, html)

    def test_same_variables_as_v1_0(self):
        html = self.html()
        for expected in (
            "ENTREPRISE TEST SARL",
            "Awa Diarra",
            "+22370000001",
            "Boutique Test",
            "contact@test.example",
            "ML-BKO-2026-B-00000",
        ):
            self.assertIn(expected, html)
        self.assertIn("Version 1.2.</p>", html[-80:])

    def test_f142_wording(self):
        html = self.html()
        self.assertIn("offert pendant 30 jours", html)
        self.assertNotIn("1 mois", html)
        self.assertIn(
            "L'essai est gratuit des deux côtés : HayaFlash vous offre l'accès au plan Pro, "
            "et il n'y a pas d'autre rémunération pendant l'essai.",
            html,
        )
        for old in ("gratuit pour les deux parties", "contrepartie de votre participation"):
            self.assertNotIn(old, html)
        self.assertIn("paie un abonnement payant.", html)
        self.assertNotIn("Medium", html)
        self.assertNotIn("(Medium ou Pro)", html)

    def test_no_banned_word(self):
        self.assertIsNone(BANNED_RE.search(self.html()))

    def test_templates_partners_stay_clean(self):
        offenders = []
        for path in (Path(settings.BASE_DIR) / "templates" / "partners").rglob("*.html"):
            if BANNED_RE.search(path.read_text(encoding="utf-8")):
                offenders.append(path.name)
        self.assertEqual(offenders, [])


@override_settings(**FACTICE)
class NewPartnerGetsV1_2Tests(TestCase):
    def setUp(self):
        cache.clear()
        self.prospect = make_partner(
            code="PROS012",
            phone="+22360050012",
            name="Awa Diarra",
            status="prospect",
            phase="none",
            accept=False,
        )
        self.link, self.token = create_link(self.prospect, "accept", days=30)
        self.client = Client(enforce_csrf_checks=True)

    def test_v1_2_is_proposed_to_a_new_partner(self):
        self.assertEqual(pending_document(self.prospect), "trial_letter")
        resp = self.client.get(reverse("partner_doc_page", args=[self.token]))
        self.assertContains(resp, LETTER_V1_2_ACK)
        self.assertNotContains(resp, "version 1.0")

    def test_online_acceptance_is_recorded_as_v1_2(self):
        self.client.get(reverse("partner_doc_page", args=[self.token]))
        csrf = self.client.cookies["csrftoken"].value
        resp = self.client.post(
            reverse("partner_doc_accept", args=[self.token]),
            {"csrfmiddlewaretoken": csrf, "accept_terms": "1", "signer_name": "Awa Diarra"},
        )
        self.assertEqual(resp.status_code, 200)
        acc = PartnerAcceptance.objects.get(partner=self.prospect)
        self.assertEqual((acc.doc_type, acc.doc_version, acc.method), ("trial_letter", "1.2", "online_checkbox"))
        self.assertIn("lettre d'essai. Version 1.2.", acc.text_snapshot)
        self.assertEqual(acc.text_sha256, legal_docs.sha256_of(acc.text_snapshot))

    def test_written_acceptance_is_recorded_as_v1_2(self):
        acc, created = accept_document(
            self.prospect,
            "trial_letter",
            signer_name="Awa Diarra",
            method="written_manual",
            manual_reference="Message WhatsApp du 03/10",
        )
        self.assertTrue(created)
        self.assertEqual(acc.doc_version, "1.2")
        self.assertEqual(acc.method, "written_manual")
        self.assertTrue(has_valid_letter(self.prospect))

    def test_enum_label_is_back_to_trial_with_a_labels_only_migration(self):
        self.assertEqual(AcceptanceDocType.TRIAL_LETTER.label, "Lettre d'essai")
        migrations = Path(settings.BASE_DIR) / "partners/migrations"
        self.assertEqual(len(list(migrations.glob("0003*"))), 1)
        self.assertEqual(len(list(migrations.glob("0002*"))), 1)  # déjà fusionnée : jamais retirée


@override_settings(**FACTICE)
class ExistingV1_0StaysValidTests(TestCase):
    def test_a_v1_0_letter_is_still_a_valid_letter(self):
        partner = make_partner(code="OLD0001", phone="+22360050021", phase="trial", accept=False)
        v1_0_letter(partner)
        self.assertTrue(has_valid_letter(partner))

    def test_a_prospect_with_a_v1_0_letter_is_not_asked_again(self):
        partner = make_partner(code="OLD0002", phone="+22360050022", status="prospect", phase="none", accept=False)
        v1_0_letter(partner)
        self.assertIsNone(pending_document(partner))

    def test_a_v1_1_letter_stays_valid_and_is_not_asked_again(self):
        partner = make_partner(code="OLD0006", phone="+22360050026", status="prospect", phase="none", accept=False)
        PartnerAcceptance.objects.create(
            partner=partner,
            doc_type="trial_letter",
            doc_version="1.1",
            text_snapshot="<p>Lettre v1.1</p>",
            text_sha256=LETTER_V1_1_SHA,
            signer_name=partner.name,
            accepted_at=datetime(2026, 10, 14, tzinfo=timezone.utc),
            method="written_manual",
            manual_reference="Fixture de test",
        )
        self.assertTrue(has_valid_letter(partner))
        self.assertIsNone(pending_document(partner))

    def test_a_trial_partner_with_a_v1_0_letter_is_not_asked_for_v1_2(self):
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

    def test_the_v1_0_text_is_still_renderable_for_the_lock(self):
        html = legal_docs.render_document("trial_letter", fake_partner(), version="1.0")
        self.assertIn("lettre d'essai. Version 1.0.", html)


@override_settings(**FACTICE)
class TermsAfterEitherLetterTests(TestCase):
    def invite(self, partner):
        OutboundMessage.objects.create(
            partner=partner,
            phone_e164=partner.phone,
            template_key="envoi_conditions",
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

    def test_terms_are_acceptable_after_a_v1_2_letter(self):
        partner = make_partner(code="TRM0002", phone="+22360050032", status="prospect", phase="none", accept=False)
        accept_document(partner, "trial_letter", signer_name="Awa")
        partner.refresh_from_db()
        self.invite(partner)
        self.assertEqual(pending_document(partner), "program_terms")
        acc, created = accept_document(partner, "program_terms", signer_name="Awa")
        self.assertTrue(created)
        self.assertEqual(acc.doc_version, "1.0")


@override_settings(**FACTICE)
class BriefAndMessagesTests(TestCase):
    def test_brief_v1_2_says_trial_and_has_no_remaining_places_counter(self):
        html = legal_docs.render_brief(places=5)
        self.assertEqual(legal_docs.BRIEF_VERSION, "1.2")
        self.assertIn("Places limitées, sélection à l'issue de l'essai", html)
        self.assertNotIn("la phase", html)
        self.assertNotIn("évaluation", html)
        self.assertNotIn("Il reste", html)
        self.assertNotIn("5 places", html)
        self.assertIn("Version 1.2.", html)
        self.assertIsNone(BANNED_RE.search(html))

    def test_brief_v1_1_stays_intact_and_published(self):
        self.assertEqual(
            legal_docs.PUBLISHED["brief"],
            {
                "1.1": "partners/legal/partner_brief_v1_1.html",
                "1.2": "partners/legal/partner_brief_v1_2.html",
            },
        )
        raw = (Path(settings.BASE_DIR) / "templates/partners/legal/partner_brief_v1_1.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("sélection à l'issue de la phase", raw)
        self.assertIn("Version 1.1.", raw)
        html = legal_docs.render_brief(places=5, version="1.1")
        self.assertIn("Places limitées, sélection à l'issue de la phase", html)

    def test_brief_v1_0_template_is_untouched(self):
        raw = (Path(settings.BASE_DIR) / "templates/partners/legal/partner_brief_v1_0.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("Il reste {{ places }} places.", raw)

    def test_conditions_message_no_longer_counts_places(self):
        text = msg.TEMPLATES["envoi_conditions"]
        self.assertIn("Places limitées, sélection à l'issue de l'essai.", text)
        self.assertNotIn("la phase", text)
        self.assertNotIn("Il reste", text)
        self.assertNotIn("{places}", text)

    def test_invitation_is_the_final_text_without_link(self):
        self.assertEqual(msg.TEMPLATES["invitation_essai"], INVITATION)
        self.assertNotIn("{lien}", msg.TEMPLATES["invitation_essai"])
        self.assertIsNone(BANNED_RE.search(msg.TEMPLATES["invitation_essai"]))

    def test_letter_messages_say_trial_again(self):
        self.assertIn("lettre d'essai", msg.TEMPLATES["envoi_lettre_essai"])
        self.assertEqual(msg.LABELS["envoi_lettre_essai"], "Envoi de la lettre d'essai")


NO_JURISDICTION = {**FACTICE, "LEGAL_JURISDICTION": ""}


class CompletenessF141Tests(SimpleTestCase):
    """F-141 : seules les valeurs LEGAL_* que le gabarit utilise sont exigées."""

    @override_settings(**NO_JURISDICTION)
    def test_the_v1_2_letter_does_not_require_the_jurisdiction(self):
        self.assertEqual(legal_docs.missing_fields("trial_letter"), [])
        self.assertTrue(legal_docs.is_complete("trial_letter"))

    @override_settings(**NO_JURISDICTION, ENVIRONMENT="prod")
    def test_the_letter_can_be_accepted_online_outside_dev_without_jurisdiction(self):
        self.assertTrue(legal_docs.acceptance_allowed("trial_letter"))

    @override_settings(**NO_JURISDICTION, ENVIRONMENT="prod")
    def test_the_terms_still_require_the_jurisdiction(self):
        self.assertEqual(legal_docs.missing_fields("program_terms"), ["LEGAL_JURISDICTION"])
        self.assertFalse(legal_docs.is_complete("program_terms"))
        self.assertFalse(legal_docs.acceptance_allowed("program_terms"))

    @override_settings(**FACTICE)
    def test_the_letter_still_requires_the_values_it_uses(self):
        for setting in ("LEGAL_ENTITY_NAME", "LEGAL_ENTITY_ADDRESS", "LEGAL_ENTITY_RCCM", "LEGAL_ENTITY_CONTACT"):
            with self.subTest(setting=setting), override_settings(**{setting: ""}):
                self.assertIn(setting, legal_docs.missing_fields("trial_letter"))

    @override_settings(**FACTICE)
    def test_every_required_value_of_the_letter_is_really_used_by_its_template(self):
        # Garde-fou : une valeur exigée mais absente du gabarit courant bloquerait l'acceptation pour rien.
        html = legal_docs.render_document("trial_letter", fake_partner())
        shown = {
            "LEGAL_ENTITY_NAME": "ENTREPRISE TEST SARL",
            "LEGAL_ENTITY_FORM": "société à responsabilité limitée unipersonnelle",
            "LEGAL_ENTITY_ADDRESS": "12 rue de Test, Bamako",
            "LEGAL_ENTITY_RCCM": "ML-BKO-2026-B-00000",
            "LEGAL_ENTITY_CONTACT": "contact@test.example",
        }
        for key in legal_docs.DOCS["trial_letter"]["fields"]:
            setting = legal_docs.ENTITY_SETTINGS[key]
            self.assertIn(shown[setting], html, setting)
