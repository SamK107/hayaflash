"""BLOC A : modèles du programme partenaires et leurs contraintes en base."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import SellerProfile
from partners.models import (
    CommissionEntry,
    Partner,
    PartnerAcceptance,
    PartnerClick,
    Payout,
    Referral,
)
from subscriptions.models import PaymentProvider, PaymentStatus, SubscriptionPayment

User = get_user_model()


def make_partner(code="AWA2026", phone="+22360000001", accept=True, **kw):
    """Partenaire de test. Sous contrat et actif, il a accepte les conditions (bloc H6) bien
    avant tout paiement de test, sauf ``accept=False``."""
    partner = Partner.objects.create(
        name=kw.pop("name", "Awa Creatrice"), phone=phone, code=code, **kw
    )
    if accept and partner.phase == "contract" and partner.status in ("active", "paused", "ended", "slot_released"):
        PartnerAcceptance.objects.create(
            partner=partner,
            doc_type="program_terms",
            doc_version="1.0",
            text_snapshot="<p>Conditions de test</p>",
            text_sha256="0" * 64,
            signer_name=partner.name,
            accepted_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
            method="written_manual",
            manual_reference="Fixture de test",
        )
    return partner


def make_seller(phone="+22370000101"):
    user = User.objects.create_user(phone=phone, password="x", display_name="V")
    return SellerProfile.objects.create(user=user)


def make_payment(seller, *, amount=2000, n=[0]):
    n[0] += 1
    return SubscriptionPayment.objects.create(
        seller=seller,
        plan="medium",
        provider=PaymentProvider.ORANGE,
        amount=amount,
        phone="+22370000101",
        status=PaymentStatus.SUCCESS,
        order_id=f"HF-M-{n[0]:08d}",
        notif_token=f"tok-{n[0]:040d}",
    )


class PartnerModelTests(TestCase):
    def test_code_is_uppercased_and_validated(self):
        p = make_partner(code="abc123")
        self.assertEqual(p.code, "ABC123")
        for bad in ("AB", "ABCDEFGHIJKLM", "AB-CD1", "AB CD1", "ÉCOLE1"):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                make_partner(code=bad, phone=f"+2236999{abs(hash(bad)) % 10000:04d}")

    def test_code_and_phone_are_unique(self):
        make_partner()
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_partner(phone="+22360000002")  # même code
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_partner(code="AUTRE1")  # même téléphone

    def test_phone_is_normalised_like_accounts(self):
        p = make_partner(phone="+223 60 00 00 09")
        self.assertEqual(p.phone, "+22360000009")

    def test_contract_end_is_start_plus_contract_months(self):
        p = make_partner(contract_start=date(2026, 10, 5))
        self.assertEqual(p.contract_end, date(2027, 10, 5))
        self.assertEqual(settings.PARTNER_CONTRACT_MONTHS, 12)

    def test_contract_end_clamps_month_end(self):
        p = make_partner(contract_start=date(2026, 2, 28), code="FEB2026", phone="+22360000005")
        self.assertEqual(p.contract_end, date(2027, 2, 28))
        q = make_partner(contract_start=date(2028, 2, 29), code="LEAP28", phone="+22360000006")
        self.assertEqual(q.contract_end, date(2029, 2, 28))

    def test_commission_percent_defaults_to_setting_and_is_frozen(self):
        p = make_partner()
        self.assertEqual(p.commission_percent, 30)
        with self.settings(PARTNER_COMMISSION_PERCENT=40):
            self.assertEqual(Partner.objects.get(pk=p.pk).commission_percent, 30)
            self.assertEqual(make_partner(code="NEW40A", phone="+22360000007").commission_percent, 40)

    def test_defaults(self):
        p = make_partner()
        self.assertEqual((p.kind, p.status, p.is_founder), ("creator", "active", False))

    def test_commission_percent_bounds(self):
        with self.assertRaises((ValidationError, IntegrityError)), transaction.atomic():
            make_partner(commission_percent=101)


class ReferralModelTests(TestCase):
    def setUp(self):
        self.partner = make_partner()
        self.seller = make_seller()

    def test_a_seller_has_only_one_sponsor(self):
        Referral.objects.create(partner=self.partner, seller=self.seller)
        other = make_partner(code="BOB2026", phone="+22360000003")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Referral.objects.create(partner=other, seller=self.seller)

    def test_defaults(self):
        r = Referral.objects.create(partner=self.partner, seller=self.seller)
        self.assertEqual((r.source, r.flagged, r.first_paid_at, r.commission_ends_at), ("link", False, None, None))
        self.assertIsNotNone(r.attributed_at)

    def test_click_stores_only_a_hash(self):
        c = PartnerClick.objects.create(partner=self.partner, ip_hash="a" * 16)
        self.assertEqual(c.ip_hash, "a" * 16)
        self.assertNotIn("ip_address", [f.name for f in PartnerClick._meta.get_fields()])


class CommissionEntryTests(TestCase):
    def setUp(self):
        self.partner = make_partner()
        self.seller = make_seller()
        self.referral = Referral.objects.create(partner=self.partner, seller=self.seller)

    def entry(self, payment, **kw):
        data = dict(referral=self.referral, payment=payment, gross_fcfa=2000, net_fcfa=1980, percent=30, commission_fcfa=594)
        data.update(kw)
        return CommissionEntry.objects.create(**data)

    def test_one_line_per_payment(self):
        pay = make_payment(self.seller)
        self.entry(pay)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.entry(pay)

    def test_default_status_pending(self):
        self.assertEqual(self.entry(make_payment(self.seller)).status, "pending")

    def test_amounts_are_never_negative_nor_inconsistent(self):
        for kw in ({"gross_fcfa": -1}, {"commission_fcfa": 1981}, {"net_fcfa": 2001}):
            with self.subTest(kw=kw), self.assertRaises(IntegrityError), transaction.atomic():
                self.entry(make_payment(self.seller), **kw)

    def test_amounts_are_integers(self):
        field = CommissionEntry._meta.get_field("commission_fcfa")
        self.assertEqual(field.get_internal_type(), "PositiveIntegerField")
        self.assertNotIsInstance(self.entry(make_payment(self.seller)).commission_fcfa, Decimal)


class PayoutTests(TestCase):
    def test_unique_per_partner_and_period(self):
        p = make_partner()
        Payout.objects.create(partner=p, period="2026-10", total_fcfa=2500)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Payout.objects.create(partner=p, period="2026-10", total_fcfa=100)
        other = make_partner(code="BOB2026", phone="+22360000003")
        Payout.objects.create(partner=other, period="2026-10", total_fcfa=100)

    def test_default_due_and_due_date_is_the_10th_of_next_month(self):
        p = make_partner()
        po = Payout.objects.create(partner=p, period="2026-10", total_fcfa=2500)
        self.assertEqual(po.status, "due")
        self.assertEqual(po.due_date, date(2026, 11, 10))
        dec = Payout.objects.create(partner=p, period="2026-12", total_fcfa=2500)
        self.assertEqual(dec.due_date, date(2027, 1, 10))

    def test_negative_total_refused(self):
        p = make_partner()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Payout.objects.create(partner=p, period="2026-10", total_fcfa=-1)


class FoundersSlotsTests(TestCase):
    def test_21st_founder_is_refused_in_french(self):
        for i in range(20):
            make_partner(code=f"FND{i:03d}", phone=f"+2236100{i:04d}", is_founder=True)
        with self.assertRaises(ValidationError) as ctx:
            make_partner(code="FND999", phone="+223619999999", is_founder=True)
        self.assertIn("20", " ".join(ctx.exception.messages))
        self.assertIn("places", " ".join(ctx.exception.messages))
        self.assertEqual(Partner.objects.filter(is_founder=True).count(), 20)

    def test_paused_counts_released_does_not(self):
        ps = [make_partner(code=f"FND{i:03d}", phone=f"+2236100{i:04d}", is_founder=True) for i in range(20)]
        ps[0].status = "paused"
        ps[0].save()
        with self.assertRaises(ValidationError):
            make_partner(code="FND998", phone="+223619999998", is_founder=True)
        ps[1].status = "slot_released"
        ps[1].save()
        make_partner(code="FND997", phone="+223619999997", is_founder=True)

    def test_non_founders_are_not_limited(self):
        for i in range(22):
            make_partner(code=f"CRE{i:03d}", phone=f"+2236200{i:04d}")
