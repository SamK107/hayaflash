"""BLOC H5 : documents consultables en ligne par l'équipe, liens, acceptation écrite."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils.html import escape
from django.utils import timezone

from accounts.models import SellerProfile
from core.models import AuditLog
from partners.models import (
    OutboundMessage,
    Partner,
    PartnerAccessLink,
    PartnerAcceptance,
)
from partners.services.access_links import resolve_token
from partners.tests_documents import FACTICE
from partners.tests_documents_models import make_acceptance
from partners.tests_models import make_partner

User = get_user_model()
PLATFORM = "/platform-admin/"


@override_settings(**FACTICE)
class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user(phone="+22379000001", password="x", display_name="Equipe", is_staff=True)
        self.client = Client()
        self.client.force_login(self.staff)
        self.partner = make_partner(code="AWA2026", name="Awa Diarra", accept=False)
        self.prospect = make_partner(
            code="PROS001", phone="+22360050001", name="Fanta", status="prospect", phase="none", accept=False
        )

    def acceptance(self, partner=None, **kw):
        return make_acceptance(partner or self.partner, **kw)


class AccessTests(Base):
    def test_all_pages_are_staff_only(self):
        acc = self.acceptance()
        link = PartnerAccessLink.objects.create(partner=self.partner, purpose="view", token_hash="a" * 64)
        gets = [
            reverse("partners_documents"),
            reverse("partners_document_detail", args=[acc.pk]),
            reverse("partners_documents_csv"),
            reverse("partners_brief"),
        ]
        posts = [
            reverse("partners_link_create", args=[self.partner.pk]),
            reverse("partners_link_revoke", args=[link.pk]),
            reverse("partners_written_acceptance", args=[self.partner.pk]),
        ]
        platform = Client().get(PLATFORM)
        seller_user = User.objects.create_user(phone="+22379000002", password="x", display_name="V")
        SellerProfile.objects.create(user=seller_user)
        seller = Client()
        seller.force_login(seller_user)
        for who in (Client(), seller):
            for url in gets:
                resp = who.get(url)
                self.assertEqual(resp.status_code, platform.status_code, url)
                self.assertEqual(resp["Location"].split("?")[0], platform["Location"].split("?")[0])
            for url in posts:
                self.assertEqual(who.post(url).status_code, platform.status_code, url)
        for url in gets:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.staff)
        for url in posts:
            self.assertEqual(strict.post(url).status_code, 403, url)
            self.assertEqual(self.client.get(url).status_code, 405, url)


class ListTests(Base):
    def test_table_columns(self):
        self.acceptance(signer_name="Awa Diarra Traoré", ip_hash="b" * 16)
        resp = self.client.get(reverse("partners_documents"))
        for expected in ("Awa Diarra", escape("Lettre d'essai"), "1.0", "Awa Diarra Traoré", "En ligne"):
            self.assertContains(resp, expected)
        self.assertContains(resp, hashlib.sha256(b"<p>Texte</p>").hexdigest())
        self.assertContains(resp, "hf-p-scroll")

    def test_filters(self):
        self.acceptance(doc_type="trial_letter")
        self.acceptance(doc_type="program_terms", method="written_manual", manual_reference="WhatsApp")
        self.acceptance(self.prospect, doc_type="trial_letter", doc_version="1.1")
        url = reverse("partners_documents")
        rows = lambda **q: self.client.get(url, q).context["acceptances"]  # noqa: E731
        self.assertEqual(len(rows()), 3)
        self.assertEqual(len(rows(doc_type="program_terms")), 1)
        self.assertEqual(len(rows(version="1.1")), 1)
        self.assertEqual(len(rows(method="written_manual")), 1)
        self.assertEqual(len(rows(doc_type="trial_letter", version="1.0")), 1)
        self.assertEqual(len(rows(doc_type="nope")), 3)  # filtre invalide ignoré

    def test_empty_state(self):
        resp = self.client.get(reverse("partners_documents"))
        self.assertContains(resp, "Aucune acceptation")

    def test_pending_documents_are_listed(self):
        resp = self.client.get(reverse("partners_documents"))
        self.assertIn("Fanta", [p.name for p in resp.context["pending"]])


class DetailTests(Base):
    def test_exact_snapshot_is_displayed_and_printable(self):
        acc = self.acceptance(text_snapshot="<p>TEXTE EXACT ACCEPTÉ</p>")
        resp = self.client.get(reverse("partners_document_detail", args=[acc.pk]))
        self.assertContains(resp, "<p>TEXTE EXACT ACCEPTÉ</p>", html=True)
        self.assertContains(resp, "data-hf-print")
        self.assertContains(resp, acc.text_sha256)

    def test_unknown_acceptance_is_404(self):
        self.assertEqual(self.client.get(reverse("partners_document_detail", args=[999])).status_code, 404)


class CsvTests(Base):
    def test_export_is_sanitised(self):
        self.acceptance(signer_name="=HYPERLINK(\"http://x\")", method="written_manual", manual_reference="+223 WhatsApp")
        resp = self.client.get(reverse("partners_documents_csv"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        self.assertIn("interne", resp["Content-Disposition"])
        text = resp.content.decode("utf-8")
        rows = list(csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=";"))
        self.assertIn("Empreinte du texte", rows[0])
        for row in rows:
            for cell in row:
                self.assertNotIn(cell[:1], ("=", "+", "-", "@"), cell)
        self.assertIn("'=HYPERLINK", text)
        self.assertIn("'+223 WhatsApp", text)

    def test_export_respects_filters(self):
        self.acceptance()
        self.acceptance(doc_type="program_terms")
        resp = self.client.get(reverse("partners_documents_csv"), {"doc_type": "program_terms"})
        rows = list(csv.reader(io.StringIO(resp.content.decode().lstrip("﻿")), delimiter=";"))
        self.assertEqual(len(rows), 2)


class BriefTests(Base):
    def test_brief_is_a_draft_with_remaining_places(self):
        resp = self.client.get(reverse("partners_brief"))
        self.assertContains(resp, "Brouillon")
        self.assertContains(resp, "Il reste 20 places")
        self.assertContains(resp, "ENTREPRISE TEST SARL")


class LinkTests(Base):
    def test_generate_view_link_shows_the_token_once_and_stores_only_the_hash(self):
        resp = self.client.post(reverse("partners_link_create", args=[self.partner.pk]))
        self.assertEqual(resp.status_code, 200)
        match = re.search(r"/partenaires/d/([A-Za-z0-9_\-]{30,})/", resp.content.decode())
        self.assertIsNotNone(match)
        token = match.group(1)
        link = PartnerAccessLink.objects.get()
        self.assertEqual((link.purpose, link.token_hash), ("view", hashlib.sha256(token.encode()).hexdigest()))
        self.assertIsNone(link.expires_at)
        self.assertIsNotNone(resolve_token(token))
        detail = self.client.get(reverse("partners_detail", args=[self.partner.pk])).content.decode()
        self.assertNotIn(token, detail)
        self.assertTrue(AuditLog.objects.filter(action="partner.link_created").exists())

    def test_revoke(self):
        resp = self.client.post(reverse("partners_link_create", args=[self.partner.pk]))
        token = re.search(r"/partenaires/d/([A-Za-z0-9_\-]{30,})/", resp.content.decode()).group(1)
        link = PartnerAccessLink.objects.get()
        out = self.client.post(reverse("partners_link_revoke", args=[link.pk]))
        self.assertEqual(out.status_code, 302)
        self.assertIsNone(resolve_token(token))
        self.assertTrue(AuditLog.objects.filter(action="partner.link_revoked").exists())

    def test_fiche_shows_documents_tab_with_accepted_and_pending(self):
        self.acceptance()
        html = self.client.get(reverse("partners_detail", args=[self.partner.pk])).content.decode()
        self.assertIn("Documents", html)
        self.assertIn(escape("Lettre d'essai"), html)
        self.assertIn("Générer un lien de consultation", html)
        self.assertIn("Enregistrer une acceptation écrite", html)
        prospect_html = self.client.get(reverse("partners_detail", args=[self.prospect.pk])).content.decode()
        self.assertIn("En attente", prospect_html)


class WrittenAcceptanceTests(Base):
    def post(self, partner=None, **data):
        payload = dict(doc_type="trial_letter", reference="Message WhatsApp du 03/10", accepted_on="2026-10-03")
        payload.update(data)
        return self.client.post(reverse("partners_written_acceptance", args=[(partner or self.prospect).pk]), payload)

    def test_requires_a_reference(self):
        for ref in ("", "   "):
            resp = self.post(reference=ref)
            self.assertEqual(resp.status_code, 302)
        self.assertEqual(PartnerAcceptance.objects.count(), 0)

    def test_records_a_written_acceptance_and_starts_the_trial(self):
        self.post()
        acc = PartnerAcceptance.objects.get()
        self.assertEqual((acc.method, acc.manual_reference), ("written_manual", "Message WhatsApp du 03/10"))
        self.assertEqual(timezone.localtime(acc.accepted_at).date(), date(2026, 10, 3))
        self.assertEqual(acc.signer_name, "Fanta")
        self.prospect.refresh_from_db()
        self.assertEqual((self.prospect.status, self.prospect.phase), ("active", "trial"))
        self.assertEqual(self.prospect.trial_start, date(2026, 10, 3))
        self.assertTrue(AuditLog.objects.filter(action="partner.document_accepted").exists())

    def test_terms_start_the_contract(self):
        self.post(doc_type="program_terms")
        self.prospect.refresh_from_db()
        self.assertEqual(self.prospect.phase, "contract")
        self.assertEqual(self.prospect.contract_start, date(2026, 10, 3))

    def test_double_entry_is_idempotent(self):
        self.post()
        self.post()
        self.assertEqual(PartnerAcceptance.objects.count(), 1)

    def test_bad_date_or_type_is_refused(self):
        self.post(accepted_on="pas-une-date")
        self.post(doc_type="inconnu")
        self.post(accepted_on="2999-01-01")  # date future refusée
        self.assertEqual(PartnerAcceptance.objects.count(), 0)

    def test_written_acceptance_does_not_need_a_complete_document(self):
        with override_settings(LEGAL_ENTITY_RCCM="", ENVIRONMENT="prod"):
            self.post()
        self.assertEqual(PartnerAcceptance.objects.count(), 1)


class NoDeletionTests(Base):
    def test_django_admin_forbids_changes_and_deletions(self):
        request = self.client.get("/admin/").wsgi_request
        request.user = User.objects.create_superuser(phone="+22379000009", password="x", display_name="Root")
        for model in (PartnerAcceptance, OutboundMessage, PartnerAccessLink):
            self.assertIn(model, django_admin.site._registry, model)
            ma = django_admin.site._registry[model]
            self.assertFalse(ma.has_add_permission(request), model)
            self.assertFalse(ma.has_change_permission(request), model)
            self.assertFalse(ma.has_delete_permission(request), model)

    def test_partner_with_acceptances_cannot_be_deleted(self):
        self.acceptance()
        with self.assertRaises(Exception):
            self.partner.delete()
        self.assertTrue(Partner.objects.filter(pk=self.partner.pk).exists())
