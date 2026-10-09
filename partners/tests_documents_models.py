"""BLOC H1 : phases, liens privés, acceptations immuables, journal des messages."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from partners.models import (
    OutboundMessage,
    Partner,
    PartnerAccessLink,
    PartnerAcceptance,
)
from partners.services.access_links import create_link, hash_token, resolve_token, revoke
from partners.tests_models import make_partner


def make_acceptance(partner, **kw):
    data = dict(
        partner=partner,
        doc_type="trial_letter",
        doc_version="1.0",
        text_snapshot="<p>Texte</p>",
        text_sha256=hashlib.sha256(b"<p>Texte</p>").hexdigest(),
        signer_name="Awa Diarra",
        ip_hash="a" * 16,
        method="online_checkbox",
    )
    data.update(kw)
    return PartnerAcceptance.objects.create(**data)


class PartnerPhaseTests(TestCase):
    def test_new_statuses_and_phases_exist(self):
        self.assertIn("prospect", Partner._meta.get_field("status").choices[0:0] or [c[0] for c in Partner._meta.get_field("status").choices])
        self.assertEqual(
            {c[0] for c in Partner._meta.get_field("phase").choices}, {"none", "trial", "contract", "ended"}
        )

    def test_defaults_keep_admin_created_partners_under_contract(self):
        p = make_partner(accept=False)
        self.assertEqual(p.phase, "contract")
        self.assertFalse(p.cite_shop_consent)
        self.assertEqual(p.shop_name, "")
        self.assertIsNone(p.trial_start)

    def test_trial_end_is_start_plus_thirty_days(self):
        p = make_partner(phase="trial", trial_start=date(2026, 10, 5))
        self.assertEqual(p.trial_end, date(2026, 11, 4))

    def test_prospect_does_not_count_for_places_nor_attribution(self):
        for i in range(20):
            make_partner(code=f"FND{i:03d}", phone=f"+2236100{i:04d}", is_founder=True)
        prospect = make_partner(
            code="PROS001", phone="+22360099001", status="prospect", phase="none", is_founder=True
        )
        self.assertFalse(prospect.accepts_new_referrals)
        make_partner(code="PROS002", phone="+22360099002", status="prospect", phase="none", is_founder=True)

    def test_trial_partner_takes_no_place_but_accepts_referrals(self):
        for i in range(20):
            make_partner(code=f"FND{i:03d}", phone=f"+2236100{i:04d}", is_founder=True)
        trial = make_partner(
            code="ESSAI01", phone="+22360099003", phase="trial", is_founder=True, trial_start=timezone.localdate()
        )
        self.assertTrue(trial.accepts_new_referrals)

    def test_trial_referrals_stop_after_trial_end(self):
        p = make_partner(phase="trial", trial_start=timezone.localdate() - timedelta(days=31))
        self.assertFalse(p.accepts_new_referrals)

    def test_phase_none_or_ended_never_accepts_referrals(self):
        for phase in ("none", "ended"):
            p = make_partner(code=f"PH{phase.upper()}1", phone=f"+2236098{len(phase):04d}", phase=phase)
            self.assertFalse(p.accepts_new_referrals, phase)


class AccessLinkTests(TestCase):
    def setUp(self):
        self.partner = make_partner(accept=False)

    def test_clear_token_is_never_stored(self):
        link, token = create_link(self.partner, "accept", days=30)
        self.assertGreaterEqual(len(token), 40)
        self.assertEqual(link.token_hash, hashlib.sha256(token.encode()).hexdigest())
        self.assertEqual(len(link.token_hash), 64)
        for field in PartnerAccessLink._meta.get_fields():
            if hasattr(field, "attname"):
                self.assertNotEqual(getattr(link, field.attname), token)
        self.assertFalse(PartnerAccessLink.objects.filter(token_hash=token).exists())

    def test_two_links_have_different_tokens(self):
        _, a = create_link(self.partner, "accept", days=30)
        _, b = create_link(self.partner, "accept", days=30)
        self.assertNotEqual(a, b)

    def test_resolve_valid_marks_last_viewed(self):
        link, token = create_link(self.partner, "view")
        found = resolve_token(token)
        self.assertEqual(found.pk, link.pk)
        link.refresh_from_db()
        self.assertIsNotNone(link.last_viewed_at)

    def test_view_links_do_not_expire(self):
        link, token = create_link(self.partner, "view")
        self.assertIsNone(link.expires_at)
        PartnerAccessLink.objects.filter(pk=link.pk).update(created_at=timezone.now() - timedelta(days=900))
        self.assertIsNotNone(resolve_token(token))

    def test_expired_revoked_and_unknown_resolve_to_none(self):
        link, token = create_link(self.partner, "accept", days=30)
        PartnerAccessLink.objects.filter(pk=link.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertIsNone(resolve_token(token))
        link2, token2 = create_link(self.partner, "accept", days=30)
        revoke(link2)
        self.assertIsNone(resolve_token(token2))
        self.assertIsNone(resolve_token("n-importe-quoi"))
        self.assertIsNone(resolve_token(""))

    def test_revoke_is_idempotent_and_keeps_first_date(self):
        link, _ = create_link(self.partner, "accept", days=30)
        revoke(link)
        first = PartnerAccessLink.objects.get(pk=link.pk).revoked_at
        revoke(link)
        self.assertEqual(PartnerAccessLink.objects.get(pk=link.pk).revoked_at, first)

    def test_hash_token_matches_sha256(self):
        self.assertEqual(hash_token("abc"), hashlib.sha256(b"abc").hexdigest())


class AcceptanceImmutabilityTests(TestCase):
    def setUp(self):
        self.partner = make_partner(accept=False)

    def test_cannot_be_updated(self):
        acc = make_acceptance(self.partner)
        acc.signer_name = "Autre"
        with self.assertRaises(ValidationError):
            acc.save()
        self.assertEqual(PartnerAcceptance.objects.get(pk=acc.pk).signer_name, "Awa Diarra")

    def test_cannot_be_deleted(self):
        acc = make_acceptance(self.partner)
        with self.assertRaises(ValidationError):
            acc.delete()
        with self.assertRaises(ValidationError):
            PartnerAcceptance.objects.filter(pk=acc.pk).delete()
        with self.assertRaises(ValidationError):
            PartnerAcceptance.objects.filter(pk=acc.pk).update(signer_name="x")
        self.assertEqual(PartnerAcceptance.objects.count(), 1)

    def test_partner_deletion_cannot_cascade_over_it(self):
        make_acceptance(self.partner)
        with self.assertRaises(Exception):
            self.partner.delete()
        self.assertEqual(PartnerAcceptance.objects.count(), 1)

    def test_unique_per_partner_type_and_version(self):
        make_acceptance(self.partner)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_acceptance(self.partner)
        make_acceptance(self.partner, doc_type="program_terms")
        make_acceptance(self.partner, doc_version="1.1")

    def test_written_acceptance_requires_a_reference(self):
        with self.assertRaises(ValidationError):
            make_acceptance(self.partner, method="written_manual", manual_reference="")
        ok = make_acceptance(self.partner, method="written_manual", manual_reference="WhatsApp du 03/10")
        self.assertEqual(ok.manual_reference, "WhatsApp du 03/10")

    def test_defaults(self):
        acc = make_acceptance(self.partner)
        self.assertEqual(acc.optional_consents, {})
        self.assertIsNotNone(acc.accepted_at)


class OutboundMessageTests(TestCase):
    def test_journal_is_append_only(self):
        msg = OutboundMessage.objects.create(
            partner=None, phone_e164="+22370000001", template_key="relance", body_text="Bonjour"
        )
        msg.body_text = "Modifié"
        with self.assertRaises(ValidationError):
            msg.save()
        with self.assertRaises(ValidationError):
            msg.delete()
        with self.assertRaises(ValidationError):
            OutboundMessage.objects.all().delete()
        self.assertEqual(OutboundMessage.objects.get().body_text, "Bonjour")
        self.assertIsNotNone(msg.created_at)
