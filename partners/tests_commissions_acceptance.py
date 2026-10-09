"""BLOC H6 : une commission exige un contrat accepté ; rien avant l'acceptation."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.test import TestCase
from django.utils import timezone

from partners.models import CommissionEntry, Partner, PartnerAcceptance, Referral
from partners.services.commissions import record_for_payment
from partners.services.contract import quarterly_status
from partners.services.dates import add_months
from partners.tests_commissions import pay
from partners.tests_models import make_partner, make_seller


def utc(y, m, d, h=12):
    return datetime(y, m, d, h, tzinfo=dt_timezone.utc)


ACCEPTED = utc(2026, 10, 10)


def accept_terms(partner, when=ACCEPTED):
    return PartnerAcceptance.objects.create(
        partner=partner, doc_type="program_terms", doc_version="1.0", text_snapshot="<p>x</p>",
        text_sha256="0" * 64, signer_name=partner.name, accepted_at=when,
    )


class Base(TestCase):
    def setUp(self):
        self.partner = make_partner(code="AWA2026", accept=False)
        self.seller = make_seller()
        self.referral = Referral.objects.create(partner=self.partner, seller=self.seller)

    def record(self, when, **kw):
        return record_for_payment(pay(self.seller, paid_at=when, **kw))


class BeforeAndAfterAcceptanceTests(Base):
    def test_payment_before_acceptance_gives_nothing_and_sets_no_window(self):
        accept_terms(self.partner)
        self.assertIsNone(self.record(ACCEPTED - timedelta(seconds=1)))
        self.assertEqual(CommissionEntry.objects.count(), 0)
        self.referral.refresh_from_db()
        self.assertIsNone(self.referral.first_paid_at)
        self.assertIsNone(self.referral.commission_ends_at)

    def test_payment_after_acceptance_gives_a_line(self):
        accept_terms(self.partner)
        entry = self.record(ACCEPTED + timedelta(days=3))
        self.assertIsNotNone(entry)
        self.assertEqual(entry.commission_fcfa, 594)

    def test_payment_at_the_exact_acceptance_instant_counts(self):
        accept_terms(self.partner)
        self.assertIsNotNone(self.record(ACCEPTED))

    def test_first_payment_after_acceptance_fixes_the_twelve_months(self):
        accept_terms(self.partner)
        self.record(ACCEPTED - timedelta(days=40))  # ignoré
        first = ACCEPTED + timedelta(days=20)
        self.record(first)
        self.referral.refresh_from_db()
        self.assertEqual(self.referral.first_paid_at, first)
        self.assertEqual(self.referral.commission_ends_at, add_months(first, 12))
        self.assertIsNone(self.record(add_months(first, 12) + timedelta(days=1)))

    def test_reconcile_style_replay_never_pays_the_old_payment(self):
        accept_terms(self.partner)
        self.record(ACCEPTED - timedelta(days=5))
        self.record(ACCEPTED + timedelta(days=5))
        self.assertEqual(CommissionEntry.objects.count(), 1)

    def test_no_acceptance_at_all_gives_nothing(self):
        self.assertIsNone(self.record(timezone.now()))
        self.assertEqual(CommissionEntry.objects.count(), 0)

    def test_acceptance_of_the_trial_letter_alone_is_not_enough(self):
        PartnerAcceptance.objects.create(
            partner=self.partner, doc_type="trial_letter", doc_version="1.0", text_snapshot="<p>x</p>",
            text_sha256="0" * 64, signer_name="A", accepted_at=ACCEPTED,
        )
        self.assertIsNone(self.record(ACCEPTED + timedelta(days=1)))


class TrialAttributionTests(TestCase):
    def test_seller_registered_during_the_trial_earns_from_the_first_payment_after_acceptance(self):
        partner = make_partner(
            code="ESSAI01", phone="+22360050007", phase="trial", status="active",
            trial_start=timezone.localdate(), accept=False,
        )
        self.assertTrue(partner.accepts_new_referrals)
        seller = make_seller("+22370000771")
        ref = Referral.objects.create(partner=partner, seller=seller)  # inscrit pendant l'essai
        # paiement pendant l'essai : rien
        self.assertIsNone(record_for_payment(pay(seller, paid_at=ACCEPTED - timedelta(days=2))))
        # le partenaire accepte les conditions : sous contrat
        accept_terms(partner)
        Partner.objects.filter(pk=partner.pk).update(phase="contract")
        paid = ACCEPTED + timedelta(days=9)
        entry = record_for_payment(pay(seller, paid_at=paid))
        self.assertIsNotNone(entry)
        ref.refresh_from_db()
        self.assertEqual(ref.first_paid_at, paid)
        self.assertEqual(ref.commission_ends_at, add_months(paid, 12))

    def test_partner_in_trial_earns_nothing(self):
        partner = make_partner(
            code="ESSAI02", phone="+22360050008", phase="trial", status="active",
            trial_start=timezone.localdate(), accept=False,
        )
        accept_terms(partner, utc(2000, 1, 1))  # même avec un texte accepté, la phase essai ne paie pas
        seller = make_seller("+22370000772")
        Referral.objects.create(partner=partner, seller=seller)
        self.assertIsNone(record_for_payment(pay(seller)))

    def test_phase_none_earns_nothing(self):
        partner = make_partner(code="PHNONE1", phone="+22360050009", phase="none", accept=False)
        accept_terms(partner, utc(2000, 1, 1))
        seller = make_seller("+22370000773")
        Referral.objects.create(partner=partner, seller=seller)
        self.assertIsNone(record_for_payment(pay(seller)))

    def test_ended_trial_without_contract_earns_nothing(self):
        partner = make_partner(code="PHEND01", phone="+22360050010", phase="ended", status="ended", accept=False)
        seller = make_seller("+22370000774")
        Referral.objects.create(partner=partner, seller=seller)
        self.assertIsNone(record_for_payment(pay(seller)))

    def test_ended_contract_keeps_acquired_rights(self):
        # Décision : article 6.3 des conditions : après la fin du contrat (phase « terminée »),
        # les vendeurs inscrits pendant le contrat paient encore leurs commissions.
        partner = make_partner(code="PHEND02", phone="+22360050011", phase="ended", status="ended", accept=False)
        accept_terms(partner, utc(2000, 1, 1))
        seller = make_seller("+22370000775")
        Referral.objects.create(partner=partner, seller=seller)
        self.assertIsNotNone(record_for_payment(pay(seller)))


class QuarterlyStartsAtContractTests(TestCase):
    def test_trial_partner_is_never_judged(self):
        partner = make_partner(
            code="ESSAI03", phone="+22360050012", phase="trial", status="active",
            contract_start=date(2025, 1, 1), trial_start=timezone.localdate(), accept=False,
        )
        status = quarterly_status(partner, today=date(2026, 10, 5))
        self.assertFalse(status["warning"])
        self.assertFalse(status["releasable"])
        self.assertEqual(status["consecutive_missed"], 0)

    def test_contract_partner_is_judged_from_contract_start(self):
        partner = make_partner(code="CONT001", phone="+22360050013", contract_start=date(2025, 1, 15))
        self.assertTrue(quarterly_status(partner, today=date(2026, 10, 5))["releasable"])
