"""F-134 : la lettre d'essai est un prérequis des conditions du programme.

Règles :
1. `accept_document` refuse `program_terms` si la lettre d'essai n'est pas acceptée (en ligne comme en
   écrit), en français, sans acceptation créée ni changement de phase ;
2. le modèle « conditions » est refusé à l'envoi pour un numéro inconnu ou un partenaire sans lettre
   acceptée, avec un message clair pour l'équipe ;
3. aucune exception, aucun « accord hors plateforme » : une lettre invalidée ne compte pas ;
4. `make_partner(accept=True)` et `seed_partners_demo` continuent de produire des partenaires sous contrat.
"""

from __future__ import annotations

from datetime import date

from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog
from partners.models import AcceptanceInvalidation, OutboundMessage, Partner, PartnerAcceptance
from partners.services import messages as msg
from partners.services.access_links import create_link
from partners.services.acceptance import accept_document, pending_document
from partners.tests_contact import GOOD_TEXT, WA_RE  # noqa: F401
from partners.tests_documents import FACTICE
from partners.tests_documents_admin import Base as StaffBase
from partners.tests_models import make_partner

LETTER_REQUIRED = "La lettre d'essai doit être acceptée avant les conditions du programme."


def trial_partner_without_letter(code="ESSAI01", phone="+22360050001"):
    return make_partner(
        code=code, phone=phone, name="Awa Diarra", phase="trial", status="active",
        trial_start=timezone.localdate(), accept=False,
    )


def invite(partner):
    return OutboundMessage.objects.create(
        partner=partner, phone_e164=partner.phone, template_key="envoi_conditions", body_text="x"
    )


@override_settings(**FACTICE)
class ServiceTests(TestCase):
    def assertRefused(self, partner, **kwargs):
        with self.assertRaises(ValidationError) as ctx:
            accept_document(partner, "program_terms", signer_name="Awa Diarra", **kwargs)
        self.assertIn(LETTER_REQUIRED, ctx.exception.messages)
        self.assertEqual(PartnerAcceptance.objects.filter(partner=partner).count(), 0)
        before = Partner.objects.get(pk=partner.pk)
        self.assertEqual((before.phase, before.is_founder), ("trial", False))
        self.assertFalse(AuditLog.objects.filter(action="partner.document_accepted").exists())

    def test_online_terms_without_the_letter_are_refused(self):
        self.assertRefused(trial_partner_without_letter())

    def test_written_terms_without_the_letter_are_refused(self):
        self.assertRefused(
            trial_partner_without_letter(), method="written_manual", manual_reference="Message du 03/10"
        )

    def test_a_prospect_without_the_letter_is_refused_too(self):
        prospect = make_partner(code="PROS001", phone="+22360050002", status="prospect", phase="none", accept=False)
        with self.assertRaises(ValidationError) as ctx:
            accept_document(
                prospect, "program_terms", signer_name="Fanta", method="written_manual", manual_reference="x"
            )
        self.assertIn(LETTER_REQUIRED, ctx.exception.messages)
        prospect.refresh_from_db()
        self.assertEqual((prospect.status, prospect.phase), ("prospect", "none"))

    def test_terms_are_accepted_once_the_letter_is(self):
        for method, extra in (("online", {}), ("written_manual", {"manual_reference": "Message du 03/10"})):
            with self.subTest(method=method):
                partner = trial_partner_without_letter(
                    code=f"ESS{method[:3].upper()}", phone="+2236005" + ("1001" if method == "online" else "1002")
                )
                accept_document(partner, "trial_letter", signer_name="Awa Diarra")
                accept_document(partner, "program_terms", signer_name="Awa Diarra", method=method, **extra)
                partner.refresh_from_db()
                self.assertEqual(partner.phase, "contract")
                self.assertTrue(partner.is_founder)

    def test_an_invalidated_letter_does_not_count(self):
        partner = trial_partner_without_letter()
        letter, _ = accept_document(partner, "trial_letter", signer_name="Awa Diarra")
        AcceptanceInvalidation.objects.create(acceptance=letter, reason="Erreur de saisie")
        with self.assertRaises(ValidationError) as ctx:
            accept_document(partner, "program_terms", signer_name="Awa Diarra")
        self.assertIn(LETTER_REQUIRED, ctx.exception.messages)

    def test_a_replay_of_an_existing_acceptance_stays_idempotent(self):
        partner = trial_partner_without_letter()
        accept_document(partner, "trial_letter", signer_name="Awa Diarra")
        first, created = accept_document(partner, "program_terms", signer_name="Awa Diarra")
        again, created_again = accept_document(partner, "program_terms", signer_name="Awa Diarra")
        self.assertEqual((created, created_again, first.pk), (True, False, again.pk))

    def test_there_is_no_off_platform_exemption(self):
        import inspect

        self.assertNotIn("off_platform", inspect.signature(accept_document).parameters)


@override_settings(**FACTICE)
class OnlineHoleTests(TestCase):
    """Partenaire passé en essai par un autre chemin (administration), invité, sans lettre acceptée."""

    def setUp(self):
        cache.clear()
        self.partner = trial_partner_without_letter()
        invite(self.partner)
        self.link, self.token = create_link(self.partner, "accept", days=30)
        self.client = Client()

    def test_the_terms_are_not_offered_without_the_letter(self):
        self.assertIsNone(pending_document(self.partner))
        resp = self.client.get(reverse("partner_doc_page", args=[self.token]))
        self.assertNotContains(resp, 'name="signer_name"')

    def test_a_forged_submission_creates_nothing(self):
        resp = self.client.post(
            reverse("partner_doc_accept", args=[self.token]),
            {"accept_terms": "1", "signer_name": "Awa Diarra", "doc_type": "program_terms"},
        )
        self.assertContains(resp, "Aucun document n'est à accepter pour le moment.")
        self.assertEqual(PartnerAcceptance.objects.count(), 0)
        self.partner.refresh_from_db()
        self.assertEqual(self.partner.phase, "trial")

    def test_the_terms_are_offered_once_the_letter_is_accepted(self):
        accept_document(self.partner, "trial_letter", signer_name="Awa Diarra")
        self.partner.refresh_from_db()
        self.assertEqual(pending_document(self.partner), "program_terms")


@override_settings(**FACTICE)
class WrittenAcceptanceViewTests(StaffBase):
    def post(self, partner, **data):
        payload = {"doc_type": "program_terms", "accepted_on": "2026-10-03", "reference": "Message WhatsApp du 03/10"}
        payload.update(data)
        return self.client.post(
            reverse("partners_written_acceptance", args=[partner.pk]), payload, follow=True
        )

    def test_refused_without_the_letter_with_a_clear_message(self):
        resp = self.post(self.prospect)
        self.assertContains(resp, LETTER_REQUIRED.replace("'", "&#x27;"))
        self.assertEqual(PartnerAcceptance.objects.filter(partner=self.prospect).count(), 0)
        self.prospect.refresh_from_db()
        self.assertEqual((self.prospect.status, self.prospect.phase), ("prospect", "none"))

    def test_there_is_no_off_platform_checkbox(self):
        html = self.client.get(reverse("partners_detail", args=[self.prospect.pk])).content.decode().lower()
        self.assertNotIn("hors plateforme", html)
        self.assertNotIn("off_platform", html)

    def test_accepted_after_a_written_letter(self):
        self.post(self.prospect, doc_type="trial_letter", accepted_on="2026-10-01")
        self.post(self.prospect)
        self.prospect.refresh_from_db()
        self.assertEqual(self.prospect.phase, "contract")
        self.assertEqual(
            sorted(PartnerAcceptance.objects.values_list("doc_type", flat=True)), ["program_terms", "trial_letter"]
        )
        self.assertEqual(
            PartnerAcceptance.objects.get(doc_type="program_terms").accepted_at.date(), date(2026, 10, 3)
        )


@override_settings(**FACTICE)
class SendConditionsTests(StaffBase):
    def send(self, **over):
        data = dict(
            action="send", country="223", phone_national="70 00 00 01", first_name="Awa", shop_name="",
            template_key="envoi_conditions", message=msg.TEMPLATES["envoi_conditions"],
        )
        data.update(over)
        return self.client.post(reverse("partners_contact"), data)

    def assertNothingCreated(self):
        self.assertEqual(OutboundMessage.objects.count(), 0)

    def test_unknown_number_is_refused_and_creates_no_prospect(self):
        before = Partner.objects.count()
        resp = self.send()
        self.assertContains(resp, "lettre d&#x27;essai")
        self.assertNotRegex(resp.content.decode(), WA_RE)
        self.assertEqual(Partner.objects.count(), before)
        self.assertNothingCreated()

    def test_prospect_without_the_letter_is_refused_with_a_clear_message(self):
        phone_national = self.prospect.phone[4:]
        resp = self.send(phone_national=phone_national, first_name="Fanta")
        text = resp.content.decode()
        self.assertIn("pas encore accepté la lettre d&#x27;essai", text)
        self.assertIn("Envoi de la lettre d&#x27;essai", text)  # indique quoi envoyer à la place
        self.assertNothingCreated()

    def test_preview_is_refused_too(self):
        resp = self.send(action="preview")
        self.assertContains(resp, "lettre d&#x27;essai")

    def test_partner_with_the_letter_can_receive_the_conditions(self):
        partner = trial_partner_without_letter(code="ESSAI09", phone="+22360050009")
        accept_document(partner, "trial_letter", signer_name="Awa Diarra")
        resp = self.send(phone_national=partner.phone[4:], first_name="Awa")
        self.assertRegex(resp.content.decode(), WA_RE)
        self.assertEqual(OutboundMessage.objects.filter(template_key="envoi_conditions").count(), 1)

    def test_the_other_templates_are_still_open_to_unknown_numbers(self):
        for key in ("invitation_essai", "envoi_lettre_essai"):
            with self.subTest(key=key):
                text = "Bonjour {prénom} : {lien}" if key == "envoi_lettre_essai" else (
                    "Bonjour {prénom}, essai gratuit de 30 jours. {lien}"
                )
                resp = self.send(template_key=key, message=text, phone_national="70 00 00 02")
                self.assertRegex(resp.content.decode(), WA_RE)


class NonRegressionTests(TestCase):
    def test_make_partner_still_builds_a_contract_partner_without_a_letter(self):
        partner = make_partner(code="CONTRAT1", phone="+22360070001")
        self.assertEqual(partner.phase, "contract")
        kinds = list(partner.acceptances.values_list("doc_type", flat=True))
        self.assertEqual(kinds, ["program_terms"])

    def test_the_demo_seed_still_runs_and_its_partners_stay_under_contract(self):
        from io import StringIO

        from django.core.management import call_command

        with override_settings(ENVIRONMENT="dev", DEBUG=True):
            call_command("seed_partners_demo", stdout=StringIO())
        contract = Partner.objects.get(code="DEMOAWA")
        self.assertEqual(contract.phase, "contract")
        self.assertTrue(contract.acceptances.filter(doc_type="program_terms").exists())
        self.assertTrue(contract.acceptances.filter(doc_type="trial_letter").exists())
