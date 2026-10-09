"""BLOC E : validation, versements, relevé anonymisé, exports CSV."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone as dt_timezone

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import SellerProfile
from core.models import AuditLog
from partners.models import CommissionEntry, Payout, Referral
from partners.services.payouts import (
    build_payout,
    carried_over,
    internal_csv,
    mark_paid,
    partner_csv,
    statement_text,
    validate_month,
)
from partners.tests_commissions import pay
from partners.tests_models import make_partner, make_seller


def at(y, m, d=10):
    return datetime(y, m, d, 12, tzinfo=dt_timezone.utc)


class Base(TestCase):
    def setUp(self):
        self.partner = make_partner(code="AWA2026", name="Awa Créatrice")
        self.n = 0

    def seller(self, name="Boutique Secrète"):
        self.n += 1
        s = make_seller(f"+223701200{self.n:02d}")
        SellerProfile.objects.filter(pk=s.pk).update(business_name=name)
        type(s.user).objects.filter(pk=s.user_id).update(display_name="Moussa Traoré")
        s = SellerProfile.objects.select_related("user").get(pk=s.pk)
        return s

    def entry(self, *, commission=594, when=at(2026, 10), status="validated", seller=None, plan="medium", referral=None):
        seller = seller or self.seller()
        referral = referral or Referral.objects.filter(seller=seller).first() or Referral.objects.create(
            partner=self.partner, seller=seller, first_paid_at=when, commission_ends_at=at(2027, 10),
            attributed_at=at(2026, 9, 1),
        )
        net = max(1980, commission)  # contrainte : commission <= net <= montant payé
        gross = max(2000, net)
        payment = pay(seller, amount=gross, paid_at=when, plan=plan)
        return CommissionEntry.objects.create(
            referral=referral, payment=payment, gross_fcfa=gross, net_fcfa=net, percent=30,
            commission_fcfa=commission, status=status,
        )


class ValidateMonthTests(Base):
    def test_pending_of_the_month_become_validated_never_automatically(self):
        oct_ = self.entry(status="pending", when=at(2026, 10, 5))
        nov = self.entry(status="pending", when=at(2026, 11, 5))
        self.assertEqual(oct_.status, "pending")  # rien d'automatique
        n = validate_month(self.partner, "2026-10")
        self.assertEqual(n, 1)
        oct_.refresh_from_db()
        nov.refresh_from_db()
        self.assertEqual(oct_.status, "validated")
        self.assertIsNotNone(oct_.validated_at)
        self.assertEqual(nov.status, "pending")

    def test_validate_is_idempotent_and_skips_cancelled(self):
        self.entry(status="pending", when=at(2026, 10, 5))
        cancelled = self.entry(status="cancelled", when=at(2026, 10, 6))
        self.assertEqual(validate_month(self.partner, "2026-10"), 1)
        self.assertEqual(validate_month(self.partner, "2026-10"), 0)
        cancelled.refresh_from_db()
        self.assertEqual(cancelled.status, "cancelled")

    def test_invalid_period_refused(self):
        for bad in ("2026-13", "26-10", "octobre", ""):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                validate_month(self.partner, bad)

    def test_audit_trace(self):
        self.entry(status="pending", when=at(2026, 10, 5))
        validate_month(self.partner, "2026-10")
        self.assertTrue(AuditLog.objects.filter(action="partner.commissions_validated").exists())


class BuildPayoutTests(Base):
    def test_below_minimum_is_not_paid_and_is_carried_over(self):
        self.entry(commission=1999)
        self.assertIsNone(build_payout(self.partner, "2026-10"))
        self.assertEqual(Payout.objects.count(), 0)
        self.assertEqual(carried_over(self.partner, "2026-10"), 1999)

    def test_exactly_minimum_is_paid(self):
        e = self.entry(commission=2000)
        payout = build_payout(self.partner, "2026-10")
        self.assertEqual((payout.total_fcfa, payout.status), (2000, "due"))
        e.refresh_from_db()
        self.assertEqual(e.payout, payout)
        self.assertEqual(carried_over(self.partner, "2026-10"), 0)

    def test_cumulative_over_two_months(self):
        self.entry(commission=1500, when=at(2026, 10))
        self.assertIsNone(build_payout(self.partner, "2026-10"))
        self.entry(commission=700, when=at(2026, 11))
        payout = build_payout(self.partner, "2026-11")
        self.assertEqual(payout.total_fcfa, 2200)
        self.assertEqual(payout.period, "2026-11")
        self.assertEqual(payout.entries.count(), 2)

    def test_only_validated_and_not_yet_paid_and_up_to_period_end(self):
        self.entry(commission=2500, when=at(2026, 10))
        self.entry(commission=900, when=at(2026, 10), status="pending")
        self.entry(commission=900, when=at(2026, 10), status="cancelled")
        self.entry(commission=900, when=at(2026, 10), status="paid")
        self.entry(commission=4000, when=at(2026, 11, 2))  # mois suivant
        payout = build_payout(self.partner, "2026-10")
        self.assertEqual(payout.total_fcfa, 2500)

    def test_rebuilding_is_idempotent(self):
        self.entry(commission=2500)
        first = build_payout(self.partner, "2026-10")
        again = build_payout(self.partner, "2026-10")
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(Payout.objects.count(), 1)

    def test_late_entry_joins_a_still_due_payout(self):
        self.entry(commission=2500)
        build_payout(self.partner, "2026-10")
        self.entry(commission=300)
        self.assertEqual(build_payout(self.partner, "2026-10").total_fcfa, 2800)

    def test_paid_payout_is_never_rebuilt(self):
        self.entry(commission=2500)
        payout = build_payout(self.partner, "2026-10")
        mark_paid(payout, "OM-123")
        self.entry(commission=2500)
        with self.assertRaises(ValidationError):
            build_payout(self.partner, "2026-10")

    def test_due_date_is_the_tenth_of_next_month(self):
        self.entry(commission=2500)
        self.assertEqual(build_payout(self.partner, "2026-10").due_date, date(2026, 11, 10))

    def test_other_partner_entries_are_never_mixed(self):
        other = make_partner(code="BOB2026", phone="+22360000003")
        s = self.seller()
        ref = Referral.objects.create(partner=other, seller=s)
        self.entry(commission=5000, seller=s, referral=ref)
        self.entry(commission=2500)
        self.assertEqual(build_payout(self.partner, "2026-10").total_fcfa, 2500)


class MarkPaidTests(Base):
    def due(self):
        e = self.entry(commission=2500)
        return build_payout(self.partner, "2026-10"), e

    def test_reference_is_required(self):
        payout, _ = self.due()
        for ref in ("", "   "):
            with self.assertRaises(ValidationError):
                mark_paid(payout, ref)
        payout.refresh_from_db()
        self.assertEqual(payout.status, "due")

    def test_marks_payout_and_lines_paid_with_audit(self):
        payout, entry = self.due()
        mark_paid(payout, "OM-2026-77")
        payout.refresh_from_db()
        entry.refresh_from_db()
        self.assertEqual((payout.status, payout.orange_reference), ("paid", "OM-2026-77"))
        self.assertIsNotNone(payout.paid_at)
        self.assertEqual(entry.status, "paid")
        self.assertTrue(AuditLog.objects.filter(action="partner.payout_paid", entity_id=payout.pk).exists())

    def test_cannot_pay_twice(self):
        payout, _ = self.due()
        mark_paid(payout, "OM-1")
        with self.assertRaises(ValidationError) as ctx:
            mark_paid(payout, "OM-2")
        self.assertIn("déjà", " ".join(ctx.exception.messages))
        payout.refresh_from_db()
        self.assertEqual(payout.orange_reference, "OM-1")
        self.assertEqual(AuditLog.objects.filter(action="partner.payout_paid").count(), 1)


class StatementTests(Base):
    def setUp(self):
        super().setUp()
        self.s1 = self.seller("Boutique Secrète")
        self.s2 = self.seller("Chez Fanta Textile")
        self.entry(seller=self.s1, commission=594, plan="medium")
        self.entry(seller=self.s2, commission=1485, plan="pro")
        Referral.objects.create(
            partner=self.partner, seller=self.seller(), attributed_at=at(2026, 9, 2)
        )  # inscrit via le lien, pas payant

    def test_statement_content_in_french(self):
        text = statement_text(self.partner, "2026-10")
        for expected in (
            "Awa Créatrice",
            "octobre 2026",
            "Vendeurs inscrits via votre lien : 3",
            "payants : 2",
            "Vendeur 1 · Medium",
            "Vendeur 2 · Pro",
            "mois restants",
            "1 980 FCFA",
            "30 %",
            "594 FCFA",
            "1 485 FCFA",
            "2 079 FCFA",  # commission du mois
        ):
            self.assertIn(expected, text)

    def test_statement_never_leaks_names_phones_or_shops(self):
        text = statement_text(self.partner, "2026-10")
        for secret in ("Boutique Secrète", "Fanta", "Textile", "+22370", "7012000", self.s1.user.display_name):
            self.assertNotIn(secret, text)
        self.assertNotIn(self.partner.phone, text)

    def test_cumulative_and_reference_after_payment(self):
        text = statement_text(self.partner, "2026-10")
        self.assertIn("Cumul non versé : 2 079 FCFA", text)
        payout = build_payout(self.partner, "2026-10")
        mark_paid(payout, "OM-9")
        text = statement_text(self.partner, "2026-10")
        self.assertIn("OM-9", text)
        self.assertIn("Cumul non versé : 0 FCFA", text)

    def test_below_minimum_statement_shows_carry_over(self):
        CommissionEntry.objects.all().delete()
        self.entry(seller=self.s1, commission=800)
        text = statement_text(self.partner, "2026-10")
        self.assertIn("Cumul non versé : 800 FCFA", text)
        self.assertIn("2 000 FCFA", text)  # minimum de versement rappelé

    def test_anonymous_ids_are_stable_across_months(self):
        self.entry(seller=self.s2, commission=500, when=at(2026, 11), plan="pro")
        nov = statement_text(self.partner, "2026-11")
        self.assertIn("Vendeur 2 · Pro", nov)
        self.assertNotIn("Vendeur 1", nov)

    def test_empty_month(self):
        text = statement_text(self.partner, "2027-03")
        self.assertIn("Aucune commission", text)

    def test_amounts_have_fcfa_suffix(self):
        self.assertNotRegex(statement_text(self.partner, "2026-10"), r"FCFA\s*\d")


class CsvTests(Base):
    def setUp(self):
        super().setUp()
        self.s1 = self.seller("=HYPERLINK(\"http://evil\")")
        self.entry(seller=self.s1, commission=594)

    def rows(self, content):
        return list(csv.reader(io.StringIO(content.lstrip("﻿")), delimiter=";"))

    def test_partner_csv_is_anonymised(self):
        content, filename = partner_csv(self.partner, "2026-10")
        self.assertNotIn("HYPERLINK", content)
        self.assertNotIn("+22370", content)
        self.assertNotIn(self.s1.user.display_name, content)
        header, first = self.rows(content)[:2]
        self.assertIn("Commission (FCFA)", header)
        self.assertEqual(first[1], "Vendeur 1")
        self.assertIn("partenaire", filename)
        self.assertTrue(filename.endswith(".csv"))

    def test_internal_csv_is_complete_and_named_differently(self):
        content, filename = internal_csv(self.partner, "2026-10")
        self.assertIn("interne", filename)
        _, partner_filename = partner_csv(self.partner, "2026-10")
        self.assertNotEqual(filename, partner_filename)
        header, first = self.rows(content)[:2]
        self.assertTrue(any("Téléphone" in h for h in header))
        self.assertTrue(any("Boutique" in h for h in header))

    def test_formula_injection_is_neutralised(self):
        content, _ = internal_csv(self.partner, "2026-10")
        for row in self.rows(content):
            for cell in row:
                self.assertFalse(cell[:1] in ("=", "+", "-", "@"), cell)
        self.assertIn("'=HYPERLINK", content)
        self.assertIn("'+22370", content)

    def test_csv_utf8_with_bom_for_excel(self):
        content, _ = partner_csv(self.partner, "2026-10")
        self.assertTrue(content.startswith("﻿"))
