"""Drapeau PARTNER_REGISTRATIONS_OPEN (D11, lecture B), fermé par défaut.

Le drapeau ne ferme que l'inscription en libre-service d'un NOUVEAU partenaire (acceptation en
ligne de la lettre d'essai par un prospect). Il ne touche ni aux partenaires existants, ni aux
liens, ni au cookie hf_ref, ni aux clics, ni aux attributions, ni à la création ni à
l'acceptation écrite par l'équipe.
"""

from __future__ import annotations

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from partners import legal_docs
from partners.models import (
    AcceptanceDocType,
    AcceptanceMethod,
    OutboundMessage,
    PartnerAcceptance,
    PartnerPhase,
    PartnerStatus,
)
from partners.services.acceptance import (
    REGISTRATIONS_CLOSED_MESSAGE,
    accept_document,
    registrations_open,
    self_service_closed_for,
)
from partners.services.access_links import create_link
from partners.services.attribution import COOKIE_NAME
from partners.tests_models import make_partner
from partners.tests_public_documents import FACTICE

CLOSED_HTML = escape(REGISTRATIONS_CLOSED_MESSAGE)


def page(token):
    return reverse("partner_doc_page", args=[token])


def accept_url(token):
    return reverse("partner_doc_accept", args=[token])


class FlagDefaultTests(TestCase):
    def test_fermee_par_defaut_dans_les_reglages_de_base(self):
        import importlib

        base = importlib.import_module("config.settings.base")
        self.assertIs(base.PARTNER_REGISTRATIONS_OPEN, False)

    def test_lecture_du_reglage(self):
        with override_settings(PARTNER_REGISTRATIONS_OPEN=False):
            self.assertFalse(registrations_open())
        with override_settings(PARTNER_REGISTRATIONS_OPEN=True):
            self.assertTrue(registrations_open())


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.nouveau = make_partner(
            code="NEW0001", phone="+22360070001", name="Nouvelle Partenaire",
            status="prospect", phase="none", accept=False,
        )
        self.existant = make_partner(code="OLD0001", phone="+22360070002", name="Partenaire Engagée")
        self.client = Client()  # la protection CSRF est testée dans tests_public_documents

    def post_accept(self, partner, **data):
        _, token = create_link(partner, "accept", days=30)
        resp = self.client.post(accept_url(token), data)
        return resp, token

    def letter_data(self, name):
        return {"accept_terms": "1", "signer_name": name}


@override_settings(PARTNER_REGISTRATIONS_OPEN=False, **FACTICE)
class RegistrationsClosedTests(_Base):
    def test_nouveau_partenaire_voit_le_message_sans_formulaire(self):
        _, token = create_link(self.nouveau, "accept", days=30)
        resp = self.client.get(page(token))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, CLOSED_HTML)
        self.assertIsNone(resp.context["doc_type"])

    def test_nouveau_partenaire_ne_peut_pas_accepter_la_lettre(self):
        resp, _ = self.post_accept(self.nouveau, **self.letter_data("Nouvelle Partenaire"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, CLOSED_HTML)
        self.assertFalse(PartnerAcceptance.objects.filter(partner=self.nouveau).exists())
        self.nouveau.refresh_from_db()
        self.assertEqual(self.nouveau.status, PartnerStatus.PROSPECT)
        self.assertEqual(self.nouveau.phase, PartnerPhase.NONE)

    def test_partenaire_existant_sous_contrat_n_est_pas_bloque(self):
        resp, _ = self.post_accept(self.existant, **self.letter_data("Partenaire Engagée"))
        self.assertNotContains(resp, CLOSED_HTML)
        self.assertFalse(self_service_closed_for(self.existant))

    def test_partenaire_en_essai_peut_accepter_les_conditions(self):
        trial = make_partner(
            code="TRI0001", phone="+22360070003", name="Essai Partenaire",
            status="active", phase="trial", accept=False,
        )
        PartnerAcceptance.objects.create(
            partner=trial, doc_type=AcceptanceDocType.TRIAL_LETTER,
            doc_version=legal_docs.DOCS[AcceptanceDocType.TRIAL_LETTER]["version"],
            text_snapshot="<p>Lettre</p>", text_sha256="1" * 64, signer_name="Essai Partenaire",
            accepted_at=timezone.now(), method=AcceptanceMethod.ONLINE,
        )
        OutboundMessage.objects.create(
            partner=trial, phone_e164=trial.phone, template_key="envoi_conditions", body_text="x",
        )
        self.assertFalse(self_service_closed_for(trial))
        _, token = create_link(trial, "accept", days=30)
        resp = self.client.get(page(token))
        self.assertEqual(resp.context["doc_type"], AcceptanceDocType.PROGRAM_TERMS)
        self.assertNotContains(resp, CLOSED_HTML)

    def test_creation_et_acceptation_ecrite_par_l_equipe_restent_possibles(self):
        partner = make_partner(
            code="ECR0001", phone="+22360070004", name="Saisie Écrite",
            status="prospect", phase="none", accept=False,
        )
        acceptance, created = accept_document(
            partner, AcceptanceDocType.TRIAL_LETTER, signer_name="Saisie Écrite",
            method=AcceptanceMethod.WRITTEN,
            manual_reference="Message WhatsApp du test",
        )
        self.assertTrue(created)
        self.assertEqual(acceptance.partner, partner)

    def test_cookie_clics_et_attributions_inchanges(self):
        resp = self.client.get("/r/OLD0001/")
        self.assertEqual(resp.cookies[COOKIE_NAME].value, "OLD0001")
        self.assertEqual(self.existant.clicks.count(), 1)


@override_settings(PARTNER_REGISTRATIONS_OPEN=True, **FACTICE)
class RegistrationsOpenTests(_Base):
    def test_nouveau_partenaire_peut_accepter_la_lettre(self):
        self.assertFalse(self_service_closed_for(self.nouveau))
        resp, _ = self.post_accept(self.nouveau, **self.letter_data("Nouvelle Partenaire"))
        self.assertNotContains(resp, CLOSED_HTML)
        self.assertTrue(PartnerAcceptance.objects.filter(partner=self.nouveau, doc_type=AcceptanceDocType.TRIAL_LETTER).exists())

    def test_nouveau_partenaire_voit_le_formulaire(self):
        _, token = create_link(self.nouveau, "accept", days=30)
        resp = self.client.get(page(token))
        self.assertEqual(resp.context["doc_type"], AcceptanceDocType.TRIAL_LETTER)
        self.assertNotContains(resp, CLOSED_HTML)

    def test_partenaire_existant_inchange(self):
        resp, _ = self.post_accept(self.existant, **self.letter_data("Partenaire Engagée"))
        self.assertNotContains(resp, CLOSED_HTML)
