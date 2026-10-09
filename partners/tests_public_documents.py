"""BLOC H3 : pages publiques par lien privé, acceptation en ligne."""

from __future__ import annotations

import logging
from datetime import timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils.html import escape
from django.utils import timezone

from core.models import AuditLog
from partners import legal_docs
from partners.models import (
    OutboundMessage,
    Partner,
    PartnerAccessLink,
    PartnerAcceptance,
)
from partners.services.access_links import create_link, revoke
from partners.tests_documents import FACTICE
from partners.tests_models import make_partner

LETTER_ACK = "J'ai lu et j'accepte la lettre d'essai version 1.0"
TERMS_ACK = "J'ai lu et j'accepte les conditions du programme partenaire version 1.0"


def page(token):
    return reverse("partner_doc_page", args=[token])


def accept_url(token):
    return reverse("partner_doc_accept", args=[token])


@override_settings(**FACTICE)
class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.prospect = make_partner(
            code="PROS001", phone="+22360050001", name="Awa Diarra", status="prospect", phase="none",
            accept=False,
        )
        self.link, self.token = create_link(self.prospect, "accept", days=30)
        self.client = Client(enforce_csrf_checks=True)

    def post(self, token=None, **data):
        # CSRF réel : on récupère le jeton sur la page.
        token = token or self.token
        self.client.get(page(token))
        csrf = self.client.cookies["csrftoken"].value
        return self.client.post(accept_url(token), {"csrfmiddlewaretoken": csrf, **data})

    def accept_letter(self, **extra):
        return self.post(accept_terms="1", signer_name="Awa Diarra", **extra)


class AccessTests(Base):
    def test_valid_link_shows_the_letter_with_the_form(self):
        resp = self.client.get(page(self.token))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "lettre d'essai")
        self.assertContains(resp, "Awa Diarra")
        self.assertContains(resp, LETTER_ACK)
        self.assertContains(resp, 'name="signer_name"')
        self.assertContains(resp, 'name="cite_shop"')

    def test_unknown_expired_and_revoked_links_give_the_same_404(self):
        expired, t_expired = create_link(self.prospect, "accept", days=30)
        PartnerAccessLink.objects.filter(pk=expired.pk).update(expires_at=timezone.now() - timedelta(days=1))
        revoked, t_revoked = create_link(self.prospect, "accept", days=30)
        revoke(revoked)
        bodies = set()
        for token in ("inconnu-" + "x" * 40, t_expired, t_revoked):
            resp = self.client.get(page(token))
            self.assertEqual(resp.status_code, 404)
            bodies.add(resp.content)
        self.assertEqual(len(bodies), 1)
        post = Client().post(accept_url("inconnu-" + "x" * 40))  # sans CSRF : atteint la vue
        self.assertEqual(post.status_code, 404)
        self.assertEqual(post.content, resp.content)

    def test_security_headers(self):
        for resp in (self.client.get(page(self.token)), self.client.get(page("inconnu"))):
            self.assertIn("noindex", resp["X-Robots-Tag"])
            self.assertIn("no-store", resp["Cache-Control"])
            self.assertEqual(resp["Referrer-Policy"], "same-origin")

    def test_page_has_no_robots_index_and_no_token_in_links(self):
        html = self.client.get(page(self.token)).content.decode()
        self.assertIn('name="robots" content="noindex', html)

    @override_settings(RATELIMIT_ENABLE=True, RATELIMIT_PARTNER_LINK_IP=(3, 60))
    def test_rate_limit_per_ip(self):
        for _ in range(3):
            self.client.get(page("inconnu"), REMOTE_ADDR="196.200.5.5")
        resp = self.client.get(page(self.token), REMOTE_ADDR="196.200.5.5")
        self.assertEqual(resp.status_code, 429)
        self.assertIn("no-store", resp["Cache-Control"])
        self.assertEqual(self.client.get(page(self.token), REMOTE_ADDR="196.200.5.6").status_code, 200)

    def test_post_requires_csrf(self):
        resp = self.client.post(accept_url(self.token), {"accept_terms": "1", "signer_name": "Awa Diarra"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(PartnerAcceptance.objects.count(), 0)

    def test_get_on_accept_is_refused(self):
        self.assertEqual(self.client.get(accept_url(self.token)).status_code, 405)

    def test_token_never_reaches_our_logs(self):
        with self.assertLogs(level=logging.DEBUG) as logs:
            logging.getLogger("partners").debug("sentinelle")
            self.client.get(page(self.token))
            self.accept_letter()
        self.assertNotIn(self.token, "\n".join(logs.output))

    def test_view_link_is_read_only(self):
        self.prospect_view, token = create_link(self.prospect, "view")
        resp = self.client.get(page(token))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'name="signer_name"')
        resp = Client().post(accept_url(token), {"accept_terms": "1", "signer_name": "Awa Diarra"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(PartnerAcceptance.objects.count(), 0)


class TrialLetterAcceptanceTests(Base):
    def test_required_checkbox(self):
        resp = self.post(signer_name="Awa Diarra")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Cochez la case")
        self.assertEqual(PartnerAcceptance.objects.count(), 0)

    def test_required_full_name(self):
        for name in ("", "   ", "A"):
            with self.subTest(name=name):
                resp = self.post(accept_terms="1", signer_name=name)
                self.assertContains(resp, "nom complet")
        self.assertEqual(PartnerAcceptance.objects.count(), 0)

    def test_acceptance_starts_the_trial(self):
        resp = self.accept_letter()
        self.assertEqual(resp.status_code, 200)
        acc = PartnerAcceptance.objects.get()
        self.assertEqual((acc.doc_type, acc.doc_version, acc.method), ("trial_letter", "1.0", "online_checkbox"))
        self.assertEqual(acc.signer_name, "Awa Diarra")
        self.prospect.refresh_from_db()
        self.assertEqual((self.prospect.status, self.prospect.phase), ("active", "trial"))
        self.assertEqual(self.prospect.trial_start, timezone.localdate())
        self.assertEqual(self.prospect.trial_end, timezone.localdate() + timedelta(days=30))
        self.assertFalse(self.prospect.is_founder)

    def test_optional_consent_is_independent_and_never_precheckeds(self):
        html = self.client.get(page(self.token)).content.decode()
        self.assertNotRegex(html, r'name="cite_shop"[^>]*checked')
        self.accept_letter()
        acc = PartnerAcceptance.objects.get()
        self.assertEqual(acc.optional_consents, {"cite_shop": False})
        self.prospect.refresh_from_db()
        self.assertFalse(self.prospect.cite_shop_consent)

    def test_optional_consent_checked(self):
        self.accept_letter(cite_shop="1")
        self.assertEqual(PartnerAcceptance.objects.get().optional_consents, {"cite_shop": True})
        self.prospect.refresh_from_db()
        self.assertTrue(self.prospect.cite_shop_consent)

    def test_optional_box_alone_does_not_accept(self):
        self.post(cite_shop="1", signer_name="Awa Diarra")
        self.assertEqual(PartnerAcceptance.objects.count(), 0)

    def test_snapshot_and_hash_are_stored(self):
        self.accept_letter()
        acc = PartnerAcceptance.objects.get()
        self.assertIn("lettre d'essai", acc.text_snapshot)
        self.assertIn("Awa Diarra", acc.text_snapshot)
        self.assertEqual(acc.text_sha256, legal_docs.sha256_of(acc.text_snapshot))
        self.assertEqual(len(acc.ip_hash), 16)

    def test_snapshot_stays_frozen_even_if_the_template_changes(self):
        self.accept_letter()
        before = PartnerAcceptance.objects.get().text_snapshot
        with patch("partners.legal_docs.render_to_string", return_value="<p>TEXTE MODIFIÉ</p>"):
            self.client.get(page(self.token))
        after = PartnerAcceptance.objects.get()
        self.assertEqual(after.text_snapshot, before)
        self.assertNotIn("MODIFIÉ", after.text_snapshot)

    def test_ip_is_never_stored_in_clear(self):
        self.client.get(page(self.token), REMOTE_ADDR="196.200.7.7")
        self.post(accept_terms="1", signer_name="Awa Diarra")
        acc = PartnerAcceptance.objects.get()
        self.assertNotIn("196.200.7.7", acc.ip_hash)
        for field in ("text_snapshot", "manual_reference", "signer_name"):
            self.assertNotIn("196.200.7.7", getattr(acc, field))

    def test_second_submit_with_the_same_token_is_refused_without_duplicate(self):
        self.accept_letter()
        again = self.accept_letter()
        self.assertEqual(again.status_code, 409)
        self.assertContains(again, "Ce lien a déjà servi à une acceptation", status_code=409)
        self.assertEqual(PartnerAcceptance.objects.count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="partner.document_accepted").count(), 1)

    def test_audit_trail_has_no_phone(self):
        self.accept_letter()
        log = AuditLog.objects.get(action="partner.document_accepted")
        self.assertEqual(log.entity_id, self.prospect.pk)
        self.assertNotIn("60050001", str(log.metadata))
        self.assertEqual(log.metadata["doc_type"], "trial_letter")

    def test_confirmation_page(self):
        resp = self.accept_letter()
        self.assertContains(resp, "Imprimer")
        self.assertContains(resp, "1.0")
        self.assertContains(resp, "Awa Diarra")
        self.assertIn("no-store", resp["Cache-Control"])

    def test_accepted_documents_are_listed_with_proof(self):
        self.accept_letter()
        resp = self.client.get(page(self.token))
        acc = PartnerAcceptance.objects.get()
        self.assertContains(resp, acc.text_sha256[:12])  # référence imprimée
        self.assertContains(resp, "Awa Diarra")
        self.assertNotContains(resp, 'name="signer_name"')  # plus rien à accepter

    def test_no_bracket_in_any_public_page(self):
        for resp in (self.client.get(page(self.token)), self.accept_letter()):
            html = resp.content.decode()
            body = html.split('<div class="hf-doc">')[-1]
            self.assertNotIn("[", body.split("</div>")[0])


class IncompleteDocumentTests(Base):
    @override_settings(LEGAL_ENTITY_RCCM="", ENVIRONMENT="prod")
    def test_refused_outside_dev(self):
        resp = self.accept_letter()
        self.assertContains(resp, escape("Ce document n'est pas encore finalisé."))
        self.assertEqual(PartnerAcceptance.objects.count(), 0)

    @override_settings(LEGAL_ENTITY_RCCM="", ENVIRONMENT="dev")
    def test_dev_shows_a_draft_banner_and_allows_acceptance(self):
        resp = self.client.get(page(self.token))
        self.assertContains(resp, "BROUILLON : informations de l'éditeur manquantes")
        self.assertEqual(self.accept_letter().status_code, 200)
        self.assertEqual(PartnerAcceptance.objects.count(), 1)

    def test_no_banner_when_complete(self):
        self.assertNotContains(self.client.get(page(self.token)), "BROUILLON")


class ProgramTermsAcceptanceTests(Base):
    def setUp(self):
        super().setUp()
        self.accept_letter()
        self.prospect.refresh_from_db()
        _, self.token2 = create_link(self.prospect, "accept", days=30)  # un jeton = une acceptation
        OutboundMessage.objects.create(
            partner=self.prospect, phone_e164=self.prospect.phone, template_key="envoi_conditions", body_text="x"
        )

    def terms(self, **extra):
        return self.post(token=self.token2, accept_terms="1", signer_name="Awa Diarra", **extra)

    def test_terms_are_offered_once_invited_during_the_trial(self):
        resp = self.client.get(page(self.token2))
        self.assertContains(resp, "conditions générales")
        self.assertContains(resp, TERMS_ACK)
        self.assertNotContains(resp, 'name="cite_shop"')

    def test_terms_not_offered_without_invitation(self):
        OutboundMessage.objects.all()  # journal immuable : on repart d'un autre partenaire
        other = make_partner(code="ESSAI02", phone="+22360050002", phase="trial", status="active",
                             trial_start=timezone.localdate(), accept=False)
        _, token = create_link(other, "accept", days=30)
        resp = self.client.get(page(token))
        self.assertNotContains(resp, 'name="signer_name"')

    def test_acceptance_starts_the_contract(self):
        self.assertEqual(self.terms().status_code, 200)
        self.prospect.refresh_from_db()
        self.assertEqual(self.prospect.phase, "contract")
        self.assertEqual(self.prospect.contract_start, timezone.localdate())
        self.assertEqual(self.prospect.contract_end.year, timezone.localdate().year + 1)
        self.assertTrue(self.prospect.is_founder)
        self.assertEqual(
            sorted(PartnerAcceptance.objects.values_list("doc_type", flat=True)),
            ["program_terms", "trial_letter"],
        )

    def test_full_places_refuse_in_french(self):
        for i in range(20):
            make_partner(code=f"FND{i:03d}", phone=f"+2236100{i:04d}", is_founder=True)
        resp = self.terms()
        self.assertContains(resp, "Les places sont actuellement toutes attribuées.")
        self.prospect.refresh_from_db()
        self.assertEqual(self.prospect.phase, "trial")
        self.assertEqual(PartnerAcceptance.objects.filter(partner=self.prospect, doc_type="program_terms").count(), 0)

    def test_trial_partners_do_not_use_places(self):
        for i in range(19):
            make_partner(code=f"FND{i:03d}", phone=f"+2236100{i:04d}", is_founder=True)
        self.assertContains(self.client.get(page(self.token2)), "conditions générales")
        self.assertEqual(self.terms().status_code, 200)
        self.prospect.refresh_from_db()
        self.assertEqual(self.prospect.phase, "contract")

    def test_terms_snapshot_is_the_article_text(self):
        self.terms()
        acc = PartnerAcceptance.objects.get(doc_type="program_terms")
        self.assertIn("Article 8 bis", acc.text_snapshot)
        self.assertEqual(acc.optional_consents, {})
        self.assertEqual(acc.doc_version, "1.0")

    def test_second_submit_of_terms_is_refused_without_duplicate(self):
        self.terms()
        self.assertEqual(self.terms().status_code, 409)
        self.assertEqual(PartnerAcceptance.objects.filter(doc_type="program_terms").count(), 1)
        self.assertEqual(Partner.objects.get(pk=self.prospect.pk).phase, "contract")


class ClosingBlockPageTests(Base):
    def test_page_shows_the_frame_the_new_sentence_and_a_visible_button(self):
        html = self.client.get(page(self.token)).content.decode()
        self.assertIn('class="hf-doc-accept"', html)
        self.assertIn("Fin du document", html)
        self.assertIn("Accepter et envoyer", html)
        self.assertIn("hf-p-btn--lg", html)
        self.assertIn(
            "En envoyant, vous acceptez ce document dans sa version 1.0. Pour preuve de votre "
            "acceptation, HayaFlash conserve la date, l&#x27;heure, le texte accepté et des données "
            "techniques de connexion.",
            html.replace("l'heure", "l&#x27;heure"),
        )

        frame = html.split('class="hf-doc-accept"', 1)[1]
        self.assertLess(frame.index("<h3>Acceptation</h3>"), frame.index("En envoyant, vous acceptez"))
        self.assertLess(frame.index("En envoyant, vous acceptez"), frame.index('name="signer_name"'))
        self.assertLess(frame.index('name="signer_name"'), frame.index("Accepter et envoyer"))
        self.assertIn("politique de confidentialité", frame)

    def test_frame_links_to_the_privacy_policy_and_never_says_ip_address(self):
        from django.urls import reverse as rev

        html = self.client.get(page(self.token)).content.decode()
        frame = html.split('class="hf-doc-accept"', 1)[1]
        self.assertIn(f'href="{rev("legal_privacy")}"', frame)
        self.assertNotIn("adresse IP", html)
        self.assertIsNone(re.search(r"\bIP\b", html))

    def test_page_keeps_both_checkboxes_and_the_name_field(self):
        html = self.client.get(page(self.token)).content.decode()
        for name in ('name="accept_terms"', 'name="signer_name"', 'name="cite_shop"'):
            self.assertIn(name, html)

    def test_read_only_page_has_no_form_but_shows_the_text(self):
        _, token = create_link(self.prospect, "view")
        html = self.client.get(page(token)).content.decode()
        self.assertNotIn("Accepter et envoyer", html)

    def test_snapshot_has_the_closing_but_no_acceptance_frame_nor_sentence_nor_form(self):
        self.accept_letter()
        snap = PartnerAcceptance.objects.get().text_snapshot
        self.assertIn("Fin du document", snap)
        self.assertTrue(snap.endswith("Version 1.0.</p></div>"))
        for forbidden in (
            "hf-doc-accept", "<h3>Acceptation</h3>", "En envoyant, vous acceptez", "<form", "<input",
            "<button", "csrfmiddlewaretoken", "Accepter et envoyer",
        ):
            self.assertNotIn(forbidden, snap)

    def test_hash_is_the_same_whatever_the_page_adds_around_the_text(self):
        self.accept_letter()
        acc = PartnerAcceptance.objects.get()
        plain = legal_docs.canonical_text(legal_docs.render_document("trial_letter", self.prospect))
        self.assertEqual(acc.text_snapshot, plain)
        self.assertEqual(acc.text_sha256, legal_docs.sha256_of(plain))


class FinalPageTests(Base):
    """Après acceptation (confirmation puis réouverture du même lien) : page en lecture seule."""

    def confirmation(self, **extra):
        return self.accept_letter(**extra)

    def reopened(self):
        return self.client.get(page(self.token))

    def both(self, **extra):
        return (self.confirmation(**extra), self.reopened())

    def test_banner_name_date_version_and_reference(self):
        acc_resp, reopen = self.both(cite_shop="1")
        acc = PartnerAcceptance.objects.get()
        reference = f"{acc.pk:06d}-{acc.text_sha256[:12]}"
        for resp in (acc_resp, reopen):
            html = resp.content.decode()
            self.assertIn("Document important, à conserver", html)
            self.assertIn("Accepté par le partenaire", html)
            self.assertIn("Awa Diarra", html)
            self.assertIn("heure de Bamako (UTC)", html)
            self.assertIn(acc.accepted_at.astimezone(dt_timezone.utc).strftime("%d/%m/%Y"), html)
            self.assertIn(acc.accepted_at.astimezone(dt_timezone.utc).strftime("%H:%M"), html)
            self.assertIn("Version 1.0", html)
            self.assertIn(reference, html)
            self.assertIn("Fin du document", html)  # texte figé

    def test_cite_shop_authorisation_is_shown_yes_or_no(self):
        _, reopen = self.both(cite_shop="1")
        self.assertRegex(reopen.content.decode(), r"citer la boutique[^<]*</[^>]+>\s*<[^>]+>\s*Oui")
        Client().get("/")  # isolement
        other = make_partner(code="PROS002", phone="+22360050002", name="Fanta", status="prospect",
                             phase="none", accept=False)
        _, token = create_link(other, "accept", days=30)
        self.client.get(page(token))
        csrf = self.client.cookies["csrftoken"].value
        self.client.post(accept_url(token), {"csrfmiddlewaretoken": csrf, "accept_terms": "1", "signer_name": "Fanta Traoré"})
        self.assertRegex(self.client.get(page(token)).content.decode(), r"citer la boutique[^<]*</[^>]+>\s*<[^>]+>\s*Non")

    def test_seal_is_inline_svg_readable_in_black_and_white(self):
        html = self.both()[0].content.decode()
        acc = PartnerAcceptance.objects.get()
        seal = html.split('<svg class="hf-seal"', 1)[1].split("</svg>", 1)[0]
        self.assertIn(acc.seal_date, seal)
        self.assertNotRegex(seal, r"fill=\"#(?!(?:000|111|fff|FFF)\b)[0-9a-fA-F]{3,6}")

    def test_reference_is_repeated_in_the_print_footer(self):
        html = self.both()[1].content.decode()
        acc = PartnerAcceptance.objects.get()
        self.assertIn('class="hf-print-ref"', html)
        foot = html.split('class="hf-print-ref"', 1)[1]
        self.assertIn(f"{acc.pk:06d}-{acc.text_sha256[:12]}", foot.split("</div>", 1)[0])

    def test_no_form_no_explanation_no_ip_mention(self):
        for resp in self.both():
            html = resp.content.decode()
            for forbidden in ("<form", "csrfmiddlewaretoken", "Accepter et envoyer", "En envoyant, vous acceptez",
                              'class="hf-doc-accept"', "adresse IP"):
                self.assertNotIn(forbidden, html, forbidden)
            self.assertIsNone(re.search(r"\bIP\b", html))
            self.assertIn("data-hf-print", html)

    def test_the_proof_block_comes_from_the_record_not_from_the_snapshot(self):
        self.confirmation()
        snap = PartnerAcceptance.objects.get().text_snapshot
        for piece in ("Accepté par le partenaire", "Document important", "heure de Bamako", "hf-seal"):
            self.assertNotIn(piece, snap)

    def test_reopening_is_read_only_and_does_not_create_anything(self):
        self.confirmation()
        before = (PartnerAcceptance.objects.count(), PartnerAccessLink.objects.count())
        self.reopened()
        self.reopened()
        self.assertEqual((PartnerAcceptance.objects.count(), PartnerAccessLink.objects.count()), before)
        self.assertEqual(self.reopened().status_code, 200)

    def test_a_token_serves_one_acceptance(self):
        self.confirmation()
        link = PartnerAccessLink.objects.get(partner=self.prospect, purpose="accept")
        self.assertIsNotNone(link.acceptance_id)
        again = self.accept_letter()
        self.assertEqual(again.status_code, 409)
        self.assertContains(again, "Ce lien a déjà servi à une acceptation", status_code=409)
        self.assertContains(again, "Document important, à conserver", status_code=409)
        self.assertEqual(PartnerAcceptance.objects.count(), 1)

    def test_a_refused_second_post_with_another_name_changes_nothing(self):
        self.confirmation()
        self.post(accept_terms="1", signer_name="Quelqu'un d'autre")
        self.assertEqual(PartnerAcceptance.objects.get().signer_name, "Awa Diarra")

    def test_ip_never_blocks_an_acceptance_and_two_partners_can_share_one_ip(self):
        other = make_partner(code="PROS003", phone="+22360050003", name="Fanta", status="prospect",
                             phase="none", accept=False)
        _, token2 = create_link(other, "accept", days=30)
        for token, name in ((self.token, "Awa Diarra"), (token2, "Fanta Traoré")):
            self.client.get(page(token), REMOTE_ADDR="196.200.8.8")
            csrf = self.client.cookies["csrftoken"].value
            resp = self.client.post(
                accept_url(token),
                {"csrfmiddlewaretoken": csrf, "accept_terms": "1", "signer_name": name},
                REMOTE_ADDR="196.200.8.8",
            )
            self.assertEqual(resp.status_code, 200)
        accs = list(PartnerAcceptance.objects.order_by("pk"))
        self.assertEqual(len(accs), 2)
        self.assertEqual(accs[0].ip_hash, accs[1].ip_hash)  # signal interne, jamais un blocage

    def test_csrf_is_still_enforced(self):
        resp = self.client.post(accept_url(self.token), {"accept_terms": "1", "signer_name": "Awa Diarra"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(PartnerAcceptance.objects.count(), 0)

    def test_terms_page_after_acceptance_is_read_only_too(self):
        self.confirmation()
        OutboundMessage.objects.create(
            partner=self.prospect, phone_e164=self.prospect.phone, template_key="envoi_conditions", body_text="x"
        )
        _, token2 = create_link(self.prospect, "accept", days=30)
        self.client.get(page(token2))
        csrf = self.client.cookies["csrftoken"].value
        ok = self.client.post(
            accept_url(token2), {"csrfmiddlewaretoken": csrf, "accept_terms": "1", "signer_name": "Awa Diarra"}
        )
        self.assertEqual(ok.status_code, 200)
        html = self.client.get(page(token2)).content.decode()
        self.assertIn("Article 8 bis", html)
        self.assertNotIn("<form", html)
        self.assertNotRegex(html, r"citer la boutique")  # sans objet pour les conditions


import re  # noqa: E402


class CsrfOnPublicFormTests(Base):
    """Bug : « Interdit (403) La vérification CSRF a échoué » à l'envoi du formulaire.

    Cause : l'en-tête ``Referrer-Policy: no-referrer`` de la page. Avec cette politique, un
    navigateur envoie ``Origin: null`` sur un POST de formulaire (et aucun Referer) ; Django
    refuse alors la requête même avec un jeton valide. Le client de test n'envoie ni Origin ni
    Referer, il ne voit donc pas le bug sans simuler le comportement du navigateur.
    """

    def browser_post(self, token, *, secure=False, **data):
        """GET puis POST comme un navigateur : jeton extrait du HTML, Origin selon la politique."""
        scheme = "https" if secure else "http"
        resp = self.client.get(page(token), secure=secure)
        html = resp.content.decode()
        match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
        self.assertIsNotNone(match, "csrfmiddlewaretoken absent du formulaire")
        policy = resp["Referrer-Policy"]
        extra = {"HTTP_ORIGIN": "null" if policy == "no-referrer" else f"{scheme}://testserver"}
        payload = {"csrfmiddlewaretoken": match.group(1), "accept_terms": "1", "signer_name": "Awa Diarra"}
        payload.update(data)
        return self.client.post(accept_url(token), payload, secure=secure, **extra)

    def test_form_contains_the_csrf_token_inside_the_form(self):
        html = self.client.get(page(self.token)).content.decode()
        form = html.split("<form", 1)[1].split("</form>", 1)[0]
        self.assertIn('name="csrfmiddlewaretoken"', form)
        self.assertEqual(html.count('name="csrfmiddlewaretoken"'), 1)

    def test_post_with_a_valid_token_is_accepted_like_a_browser_would_send_it(self):
        resp = self.browser_post(self.token)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PartnerAcceptance.objects.count(), 1)

    def test_post_with_a_valid_token_is_accepted_over_https(self):
        resp = self.browser_post(self.token, secure=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PartnerAcceptance.objects.count(), 1)

    def test_post_without_a_token_is_still_refused(self):
        self.client.get(page(self.token))
        resp = self.client.post(accept_url(self.token), {"accept_terms": "1", "signer_name": "Awa Diarra"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(PartnerAcceptance.objects.count(), 0)

    def test_post_with_a_wrong_token_is_refused(self):
        self.client.get(page(self.token))
        resp = self.client.post(
            accept_url(self.token),
            {"csrfmiddlewaretoken": "x" * 64, "accept_terms": "1", "signer_name": "Awa Diarra"},
            HTTP_ORIGIN="http://testserver",
        )
        self.assertEqual(resp.status_code, 403)

    def test_a_foreign_origin_is_refused_even_with_a_valid_token(self):
        html = self.client.get(page(self.token)).content.decode()
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html).group(1)
        resp = self.client.post(
            accept_url(self.token),
            {"csrfmiddlewaretoken": token, "accept_terms": "1", "signer_name": "Awa Diarra"},
            HTTP_ORIGIN="https://evil.example",
        )
        self.assertEqual(resp.status_code, 403)

    def test_view_is_not_csrf_exempt(self):
        from partners import public_views

        self.assertFalse(getattr(public_views.document_accept, "csrf_exempt", False))
        self.assertFalse(getattr(public_views.document_page, "csrf_exempt", False))

    def test_referrer_policy_lets_the_browser_send_a_usable_origin_but_still_hides_the_url(self):
        policy = self.client.get(page(self.token))["Referrer-Policy"]
        self.assertNotEqual(policy, "no-referrer")  # « Origin: null » casserait le CSRF
        self.assertEqual(policy, "same-origin")  # jamais d'URL (donc de jeton) vers un tiers

    def test_inserting_the_form_does_not_change_the_frozen_text_or_its_hash(self):
        self.browser_post(self.token)
        acc = PartnerAcceptance.objects.get()
        plain = legal_docs.canonical_text(legal_docs.render_document("trial_letter", self.prospect))
        self.assertEqual(acc.text_snapshot, plain)  # texte seul, sans le formulaire
        self.assertEqual(acc.text_sha256, legal_docs.sha256_of(plain))
        self.assertNotIn("csrfmiddlewaretoken", acc.text_snapshot)
        self.assertNotIn("<form", acc.text_snapshot)
        self.assertEqual(acc.text_sha256, legal_docs.sha256_of(acc.text_snapshot))
