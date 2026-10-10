"""BLOC C : commissions calculées au paiement d'abonnement."""

from __future__ import annotations

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.models import AuditLog
from partners.models import CommissionEntry, Referral
from partners.services.commissions import (
    cancel_entry,
    compute_amounts,
    record_for_payment,
)
from partners.services.dates import add_months
from partners.tests_models import make_partner, make_seller
from subscriptions.models import (
    OverrideReason,
    PaymentProvider,
    PaymentStatus,
    SellerPriceOverride,
    Subscription,
    SubscriptionPayment,
)
from subscriptions.services.payment import (
    activate_subscription_from_payment,
    sync_orange_payment_status,
)

COUNTER = [0]


def pay(seller, *, amount=2000, status=PaymentStatus.SUCCESS, paid_at=None, plan="medium", override=None):
    COUNTER[0] += 1
    n = COUNTER[0]
    p = SubscriptionPayment.objects.create(
        seller=seller,
        plan=plan,
        provider=PaymentProvider.ORANGE,
        amount=amount,
        phone="+22370000101",
        status=status,
        order_id=f"HF-M-{n:08d}",
        notif_token=f"tok-{n:040d}",
        raw_response={"pay_token": "PAYTOKEN"},
        price_override=override,
        is_special_price=override is not None,
        paid_at=paid_at if paid_at is not None else (timezone.now() if status == PaymentStatus.SUCCESS else None),
    )
    return p


class Base(TestCase):
    def setUp(self):
        self.partner = make_partner()
        self.seller = make_seller()
        Subscription.objects.get_or_create(seller=self.seller)
        self.referral = Referral.objects.create(partner=self.partner, seller=self.seller)


class AmountTests(TestCase):
    def test_examples_from_the_rules(self):
        self.assertEqual(compute_amounts(2000, 30), (1980, 594))
        self.assertEqual(compute_amounts(5000, 30), (4950, 1485))

    def test_rounding_is_always_down(self):
        net, commission = compute_amounts(2999, 30)
        self.assertEqual(net, 2969)  # 2999 * 0.99 = 2969.01
        self.assertEqual(commission, 890)  # 2969 * 0.30 = 890.7
        self.assertEqual(compute_amounts(1, 30), (0, 0))
        self.assertEqual(compute_amounts(101, 30), (99, 29))

    def test_amounts_are_integers_and_respect_other_percents(self):
        for gross in (100, 333, 2000, 4999, 12345):
            for percent in (0, 10, 30, 50, 100):
                net, commission = compute_amounts(gross, percent)
                self.assertIsInstance(net, int)
                self.assertIsInstance(commission, int)
                self.assertLessEqual(commission, net)
                self.assertLessEqual(net, gross)

    def test_percent_comes_from_the_partner_not_the_setting(self):
        partner = make_partner(code="BOB2026", phone="+22360000003", commission_percent=20)
        seller = make_seller("+22370000102")
        Referral.objects.create(partner=partner, seller=seller)
        entry = record_for_payment(pay(seller))
        self.assertEqual((entry.percent, entry.commission_fcfa), (20, 396))


class RecordTests(Base):
    def test_creates_one_pending_entry_with_exact_amounts(self):
        entry = record_for_payment(pay(self.seller))
        self.assertEqual(
            (entry.gross_fcfa, entry.net_fcfa, entry.percent, entry.commission_fcfa, entry.status),
            (2000, 1980, 30, 594, "pending"),
        )
        self.assertEqual(entry.referral, self.referral)

    def test_pro_amount(self):
        entry = record_for_payment(pay(self.seller, amount=5000, plan="pro"))
        self.assertEqual((entry.net_fcfa, entry.commission_fcfa), (4950, 1485))

    def test_seller_without_referral_gets_nothing(self):
        other = make_seller("+22370000103")
        self.assertIsNone(record_for_payment(pay(other)))
        self.assertEqual(CommissionEntry.objects.count(), 0)

    def test_test_payment_is_ignored(self):
        override = SellerPriceOverride.objects.create(
            seller=self.seller, plan="medium", price=100, reason=OverrideReason.TEST,
            expires_at=timezone.now() + timedelta(days=5),
        )
        self.assertIsNone(record_for_payment(pay(self.seller, amount=100, override=override)))
        self.assertEqual(CommissionEntry.objects.count(), 0)
        self.referral.refresh_from_db()
        self.assertIsNone(self.referral.first_paid_at)

    def test_zero_amount_special_price_is_ignored(self):
        override = SellerPriceOverride.objects.create(
            seller=self.seller, plan="medium", price=100, reason=OverrideReason.PILOT,
            expires_at=timezone.now() + timedelta(days=5),
        )
        self.assertIsNone(record_for_payment(pay(self.seller, amount=0, override=override)))
        self.assertEqual(CommissionEntry.objects.count(), 0)

    def test_non_test_special_price_with_a_real_amount_counts(self):
        override = SellerPriceOverride.objects.create(
            seller=self.seller, plan="medium", price=1000, reason=OverrideReason.PILOT,
            expires_at=timezone.now() + timedelta(days=5),
        )
        entry = record_for_payment(pay(self.seller, amount=1000, override=override))
        self.assertEqual((entry.net_fcfa, entry.commission_fcfa), (990, 297))

    def test_partner_reason_special_price_counts_on_the_amount_actually_paid(self):
        override = SellerPriceOverride.objects.create(
            seller=self.seller, plan="medium", price=1500, reason=OverrideReason.PARTNER,
            expires_at=timezone.now() + timedelta(days=5),
        )
        entry = record_for_payment(pay(self.seller, amount=1500, override=override))
        self.assertEqual((entry.gross_fcfa, entry.net_fcfa, entry.commission_fcfa), (1500, 1485, 445))
        self.referral.refresh_from_db()
        self.assertIsNotNone(self.referral.first_paid_at)  # démarre la fenêtre de 12 mois

    def test_promo_reason_special_price_counts_on_the_amount_actually_paid(self):
        override = SellerPriceOverride.objects.create(
            seller=self.seller, plan="medium", price=1200, reason=OverrideReason.PROMO,
            expires_at=timezone.now() + timedelta(days=5),
        )
        entry = record_for_payment(pay(self.seller, amount=1200, override=override))
        self.assertEqual((entry.gross_fcfa, entry.net_fcfa, entry.commission_fcfa), (1200, 1188, 356))
        self.referral.refresh_from_db()
        self.assertIsNotNone(self.referral.first_paid_at)

    def test_payment_not_really_collected_is_ignored(self):
        for status in (PaymentStatus.PENDING, PaymentStatus.FAILED, PaymentStatus.EXPIRED, PaymentStatus.CANCELLED):
            with self.subTest(status=status):
                self.assertIsNone(record_for_payment(pay(self.seller, status=status)))
        self.assertEqual(CommissionEntry.objects.count(), 0)

    def test_status_is_read_from_the_database_not_from_the_object(self):
        payment = pay(self.seller, status=PaymentStatus.PENDING)
        payment.status = PaymentStatus.SUCCESS  # objet en mémoire seulement
        self.assertIsNone(record_for_payment(payment))

    def test_idempotent_one_line_per_payment(self):
        payment = pay(self.seller)
        first = record_for_payment(payment)
        again = record_for_payment(payment)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(CommissionEntry.objects.count(), 1)

    def test_flagged_referral_still_earns_but_stays_flagged(self):
        Referral.objects.filter(pk=self.referral.pk).update(flagged=True, flag_reason="x")
        self.assertIsNotNone(record_for_payment(pay(self.seller)))

    def test_paused_or_ended_partner_keeps_acquired_rights(self):
        self.partner.status = "ended"
        self.partner.save()
        self.assertIsNotNone(record_for_payment(pay(self.seller)))


class WindowTests(Base):
    T0 = timezone.now() - timedelta(days=400)

    def paid_on(self, when, amount=2000):
        return record_for_payment(pay(self.seller, amount=amount, paid_at=when))

    def test_first_payment_sets_window_of_twelve_months(self):
        entry = self.paid_on(self.T0)
        self.referral.refresh_from_db()
        self.assertEqual(self.referral.first_paid_at, self.T0)
        self.assertEqual(self.referral.commission_ends_at, add_months(self.T0, 12))
        self.assertIsNotNone(entry)

    def test_eleventh_month_pays_thirteenth_does_not(self):
        self.paid_on(self.T0)
        self.assertIsNotNone(self.paid_on(add_months(self.T0, 10) + timedelta(days=5)))  # 11e mois
        self.assertIsNotNone(self.paid_on(add_months(self.T0, 12) - timedelta(seconds=1)))  # 12e mois, dernière seconde
        self.assertIsNone(self.paid_on(add_months(self.T0, 12) + timedelta(seconds=1)))
        self.assertIsNone(self.paid_on(add_months(self.T0, 12) + timedelta(days=30)))  # 13e mois
        self.assertEqual(CommissionEntry.objects.count(), 3)

    def test_window_does_not_move_with_later_payments(self):
        self.paid_on(self.T0)
        self.paid_on(add_months(self.T0, 5))
        self.referral.refresh_from_db()
        self.assertEqual(self.referral.first_paid_at, self.T0)

    def test_rights_survive_partner_contract_end(self):
        from partners.models import Partner

        Partner.objects.filter(pk=self.partner.pk).update(
            status="slot_released", contract_end=timezone.localdate() - timedelta(days=30)
        )
        self.assertIsNotNone(self.paid_on(timezone.now()))


class ReconcileTests(Base):
    def test_dry_run_by_default_then_apply_is_idempotent(self):
        for i in range(2):
            pay(self.seller, paid_at=timezone.now() - timedelta(days=60 - i))
        out = StringIO()
        call_command("partners_reconcile", stdout=out)
        self.assertEqual(CommissionEntry.objects.count(), 0)
        self.assertIn("2", out.getvalue())
        call_command("partners_reconcile", "--apply", stdout=StringIO())
        self.assertEqual(CommissionEntry.objects.count(), 2)
        call_command("partners_reconcile", "--apply", stdout=StringIO())
        self.assertEqual(CommissionEntry.objects.count(), 2)

    def test_reconcile_replays_in_payment_order_so_the_window_starts_at_the_first(self):
        first = timezone.now() - timedelta(days=500)
        late = timezone.now() - timedelta(days=30)
        pay(self.seller, paid_at=late)
        pay(self.seller, paid_at=first)
        call_command("partners_reconcile", "--apply", stdout=StringIO())
        self.referral.refresh_from_db()
        self.assertEqual(self.referral.first_paid_at, first)
        self.assertEqual(CommissionEntry.objects.count(), 1)  # le paiement tardif est hors fenêtre

    def test_reconcile_skips_sellers_without_referral_tests_and_failures(self):
        other = make_seller("+22370000103")
        pay(other)
        pay(self.seller, status=PaymentStatus.FAILED)
        call_command("partners_reconcile", "--apply", stdout=StringIO())
        self.assertEqual(CommissionEntry.objects.count(), 0)


class CancelTests(Base):
    def test_cancel_pending_marks_cancelled_and_audits(self):
        entry = record_for_payment(pay(self.seller))
        cancel_entry(entry, "Remboursement du vendeur")
        entry.refresh_from_db()
        self.assertEqual(entry.status, "cancelled")
        log = AuditLog.objects.get(action="partner.commission_cancelled")
        self.assertEqual(log.entity_id, entry.pk)
        self.assertEqual(log.metadata["reason"], "Remboursement du vendeur")

    def test_reason_is_required(self):
        entry = record_for_payment(pay(self.seller))
        with self.assertRaises(ValidationError):
            cancel_entry(entry, "  ")

    def test_paid_entry_cannot_be_cancelled_without_counterpart(self):
        entry = record_for_payment(pay(self.seller))
        CommissionEntry.objects.filter(pk=entry.pk).update(status="paid")
        entry.refresh_from_db()
        with self.assertRaises(ValidationError) as ctx:
            cancel_entry(entry, "Erreur")
        self.assertIn("versée", " ".join(ctx.exception.messages))
        entry.refresh_from_db()
        self.assertEqual(entry.status, "paid")
        self.assertFalse(AuditLog.objects.filter(action="partner.commission_cancelled").exists())

    def test_cancelling_twice_is_harmless(self):
        entry = record_for_payment(pay(self.seller))
        cancel_entry(entry, "Erreur")
        cancel_entry(entry, "Erreur")
        self.assertEqual(AuditLog.objects.filter(action="partner.commission_cancelled").count(), 1)


class ActivationHookTests(Base):
    """Le point d'accroche : activate_subscription_from_payment (webhook ET retour)."""

    def pending(self, **kw):
        return pay(self.seller, status=PaymentStatus.PENDING, **kw)

    def test_activation_records_the_commission(self):
        payment = self.pending()
        activate_subscription_from_payment(payment)
        entry = CommissionEntry.objects.get(payment=payment)
        self.assertEqual(entry.commission_fcfa, 594)
        self.assertIsNotNone(entry.payment.paid_at)

    def test_replayed_activation_does_not_duplicate(self):
        payment = self.pending()
        activate_subscription_from_payment(payment)
        activate_subscription_from_payment(payment)
        self.assertEqual(CommissionEntry.objects.count(), 1)

    def test_both_paths_webhook_and_return_never_double_count(self):
        payment = self.pending()
        ok = {"status": "SUCCESS", "txn_id": "T1", "amount": None}
        with patch("subscriptions.services.orange_money.get_transaction_status", return_value=ok):
            sync_orange_payment_status(payment, source="webhook")
            sync_orange_payment_status(payment, source="return")
        activate_subscription_from_payment(payment)
        self.assertEqual(CommissionEntry.objects.count(), 1)

    def test_service_failure_never_breaks_or_rolls_back_the_activation(self):
        payment = self.pending()
        with patch(
            "partners.services.commissions.record_for_payment", side_effect=RuntimeError("panne +22370000101")
        ):
            sub = activate_subscription_from_payment(payment)
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(sub.plan, "medium")
        self.assertGreater(sub.expires_at, timezone.now())
        self.assertEqual(CommissionEntry.objects.count(), 0)

    def test_database_error_inside_the_service_does_not_poison_the_transaction(self):
        from django.db import IntegrityError

        payment = self.pending()
        with patch("partners.models.CommissionEntry.objects.create", side_effect=IntegrityError("x")):
            sub = activate_subscription_from_payment(payment)
        self.assertEqual(sub.plan, "medium")
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)

    def test_failure_is_logged_without_the_phone_number(self):
        payment = self.pending()
        with patch("partners.services.commissions.record_for_payment", side_effect=RuntimeError("boom")):
            with self.assertLogs("subscriptions.services.payment", level="ERROR") as logs:
                activate_subscription_from_payment(payment)
        text = "\n".join(logs.output)
        self.assertIn("RuntimeError", text)
        self.assertNotIn("70000101", text)

    def test_seller_without_referral_activation_unchanged(self):
        other = make_seller("+22370000104")
        Subscription.objects.get_or_create(seller=other)
        payment = pay(other, status=PaymentStatus.PENDING)
        activate_subscription_from_payment(payment)
        self.assertEqual(CommissionEntry.objects.count(), 0)
        self.assertEqual(Subscription.objects.get(seller=other).plan, "medium")

    def test_logging_failure_never_breaks_the_activation(self):
        # La journalisation de l'échec ne doit jamais lever : numéro vide (la colonne est NOT NULL),
        # et empreinte qui lève elle-même.
        for phone in ("",):
            with self.subTest(phone=phone):
                payment = self.pending()
                payment.phone = phone
                with patch("partners.services.commissions.record_for_payment", side_effect=RuntimeError("boom")):
                    with patch("core.services.rate_limit.phone_fingerprint", side_effect=ValueError("empreinte")):
                        sub = activate_subscription_from_payment(payment)
                payment.refresh_from_db()
                self.assertEqual(payment.status, PaymentStatus.SUCCESS)
                self.assertEqual(sub.plan, "medium")
