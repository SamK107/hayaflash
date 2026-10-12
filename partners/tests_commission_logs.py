"""F-128 : chaque sortie du crochet de commission laisse une ligne « créée » ou « ignorée : <raison> ».

Contexte : sur staging, un paiement à tarif spécial (motif Partenaire, 100 FCFA) a activé l'abonnement sans
commission et sans aucune ligne de journal, parce que le partenaire était en essai et n'avait pas accepté
les conditions du programme. La règle (aucune commission avant cette acceptation, jamais rattrapée pour un
paiement antérieur) ne change pas : seul le silence est corrigé.

Le journal ne contient que les identifiants du paiement, du partenaire et du lien, plus l'empreinte du
téléphone ; jamais un numéro. Le crochet ne peut toujours pas bloquer un paiement.
"""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from partners.models import CommissionEntry, Partner, PartnerAcceptance, Referral
from partners.services.commissions import record_for_payment
from partners.tests_commissions import pay
from partners.tests_models import make_partner, make_seller
from subscriptions.models import (
    OverrideReason,
    PaymentStatus,
    SellerPriceOverride,
    Subscription,
)
from subscriptions.services.payment import activate_subscription_from_payment
from subscriptions.services.plans import invalidate_plan_cache
from subscriptions.tests_orange_status import STATUS_PATH, _payment, _status

PHONE = "+22370000555"
MARK = "Commission partenaire"


def lines(logs) -> list[str]:
    return [line for line in logs.output if MARK in line]


class LegacyPathBase(TestCase):
    """Parcours exact du paiement staging : tarif spécial « Partenaire », 100 FCFA, webhook historique."""

    def setUp(self):
        invalidate_plan_cache()
        self.addCleanup(invalidate_plan_cache)

    def setup_partner(self, **partner_kw):
        self.partner = make_partner(code="ADAMA01", **partner_kw)
        self.seller = make_seller(PHONE)
        Subscription.objects.get_or_create(seller=self.seller)
        self.referral = Referral.objects.create(partner=self.partner, seller=self.seller)

    def special_payment(self):
        override = SellerPriceOverride.objects.create(
            seller=self.seller, plan="medium", price=100, reason=OverrideReason.PARTNER,
            expires_at=timezone.now() + timedelta(days=5),
        )
        payment = _payment(self.seller)
        payment.amount = 100
        payment.phone = PHONE
        payment.price_override = override
        payment.is_special_price = True
        payment.save()
        return payment

    def confirm_by_legacy_webhook(self, payment):
        body = {"status": "SUCCESS", "notif_token": payment.notif_token, "txnid": "MP-OK"}
        with self.assertLogs(level="INFO") as logs, patch(STATUS_PATH, return_value=_status("SUCCESS", txn_id="MP-OK")):
            response = Client().post(
                reverse("subscriptions:payment_callback"), data=json.dumps(body), content_type="application/json"
            )
        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)  # l'abonnement est activé dans tous les cas
        self.referral.refresh_from_db()
        return lines(logs), "\n".join(logs.output)


class LegacyWebhookTests(LegacyPathBase):
    def test_a_partner_without_accepted_program_terms_is_ignored_with_the_reason(self):
        self.setup_partner(accept=False)
        found, _ = self.confirm_by_legacy_webhook(self.special_payment())
        self.assertEqual(CommissionEntry.objects.count(), 0)
        self.assertIsNone(self.referral.first_paid_at)
        self.assertIsNone(self.referral.commission_ends_at)
        self.assertEqual(len(found), 1, found)
        self.assertIn("ignorée : conditions du programme non acceptées", found[0])

    def test_terms_accepted_before_the_payment_create_the_commission(self):
        self.setup_partner()  # acceptation des conditions datée de l'an 2000
        found, _ = self.confirm_by_legacy_webhook(self.special_payment())
        entry = CommissionEntry.objects.get()
        self.assertEqual((entry.gross_fcfa, entry.net_fcfa, entry.commission_fcfa), (100, 99, 29))
        self.assertIsNotNone(self.referral.first_paid_at)
        self.assertEqual(len(found), 1, found)
        self.assertIn("créée", found[0])
        self.assertNotIn("ignorée", found[0])

    def accept_terms(self, accepted_at):
        PartnerAcceptance.objects.create(
            partner=self.partner, doc_type="program_terms", doc_version="1.0", text_snapshot="<p>x</p>",
            text_sha256="0" * 64, signer_name="Adama", accepted_at=accepted_at,
            method="written_manual", manual_reference="Fixture de test",
        )

    def test_terms_accepted_after_the_payment_are_never_caught_up(self):
        self.setup_partner(accept=False)
        found, _ = self.confirm_by_legacy_webhook(self.special_payment())
        self.assertEqual(len(found), 1, found)
        self.assertIn("ignorée : conditions du programme non acceptées", found[0])  # état au moment du paiement
        self.accept_terms(timezone.now() + timedelta(minutes=1))  # acceptation postérieure
        call_command("partners_reconcile", "--apply", stdout=_Null())
        self.assertEqual(CommissionEntry.objects.count(), 0)
        self.referral.refresh_from_db()
        self.assertIsNone(self.referral.first_paid_at)

    def test_a_payment_dated_before_the_acceptance_is_ignored_with_the_reason(self):
        self.setup_partner(accept=False)
        self.accept_terms(timezone.now() + timedelta(hours=1))  # déjà enregistrée, datée après le paiement
        found, _ = self.confirm_by_legacy_webhook(self.special_payment())
        self.assertEqual(CommissionEntry.objects.count(), 0)
        self.assertIsNone(self.referral.first_paid_at)
        self.assertEqual(len(found), 1, found)
        self.assertIn("ignorée : paiement antérieur à l'acceptation des conditions du programme", found[0])

    def test_a_partner_in_trial_is_ignored_with_the_reason(self):
        self.setup_partner(accept=False, phase="trial", trial_start=timezone.localdate())
        found, _ = self.confirm_by_legacy_webhook(self.special_payment())
        self.assertEqual(CommissionEntry.objects.count(), 0)
        self.assertIsNone(self.referral.first_paid_at)
        self.assertEqual(len(found), 1, found)
        self.assertIn("ignorée : partenaire en essai", found[0])

    def test_the_log_line_holds_identifiers_and_a_fingerprint_never_a_phone_number(self):
        self.setup_partner(accept=False)
        payment = self.special_payment()
        found, everything = self.confirm_by_legacy_webhook(payment)
        line = found[0]
        self.assertIn(f"paiement={payment.pk}", line)
        self.assertIn(f"partenaire={self.partner.pk}", line)
        self.assertIn(f"lien={self.referral.pk}", line)
        self.assertIn("tel:", line)
        for leak in ("22370000555", "70000555", "ADAMA01", self.partner.name):
            self.assertNotIn(leak, line)
            self.assertNotIn(leak, everything.split(MARK)[1] if MARK in everything else "")


class _Null:
    def write(self, *_args, **_kwargs):
        return None


class OtherExitsTests(TestCase):
    """Chaque autre sortie du crochet explique pourquoi (appel direct du service et du crochet)."""

    def setUp(self):
        self.partner = make_partner(code="AWA2026")
        self.seller = make_seller("+22370000101")
        Subscription.objects.get_or_create(seller=self.seller)
        self.referral = Referral.objects.create(partner=self.partner, seller=self.seller)

    def hook_lines(self, payment):
        with self.assertLogs(level="INFO") as logs:
            activate_subscription_from_payment(payment)
        return lines(logs)

    def test_seller_without_a_partner_link(self):
        other = make_seller("+22370000104")
        Subscription.objects.get_or_create(seller=other)
        found = self.hook_lines(pay(other, status=PaymentStatus.PENDING))
        self.assertEqual(len(found), 1, found)
        self.assertIn("ignorée : aucun lien partenaire", found[0])

    def test_test_payment(self):
        override = SellerPriceOverride.objects.create(
            seller=self.seller, plan="medium", price=100, reason=OverrideReason.TEST,
            expires_at=timezone.now() + timedelta(days=5),
        )
        found = self.hook_lines(pay(self.seller, amount=100, status=PaymentStatus.PENDING, override=override))
        self.assertEqual(len(found), 1, found)
        self.assertIn("ignorée : paiement de test", found[0])

    def test_payment_not_collected(self):
        with self.assertLogs(level="INFO") as logs:
            self.assertIsNone(record_for_payment(pay(self.seller, status=PaymentStatus.PENDING), report=_log_to_root))
        self.assertIn("ignorée : paiement non encaissé", "\n".join(lines(logs)))

    def test_zero_amount(self):
        with self.assertLogs(level="INFO") as logs:
            record_for_payment(pay(self.seller, amount=0), report=_log_to_root)
        self.assertIn("ignorée : montant nul", "\n".join(lines(logs)))

    def test_commission_already_created(self):
        payment = pay(self.seller)
        record_for_payment(payment)
        with self.assertLogs(level="INFO") as logs:
            record_for_payment(payment, report=_log_to_root)
        self.assertIn("ignorée : commission déjà créée", "\n".join(lines(logs)))
        self.assertEqual(CommissionEntry.objects.count(), 1)

    def test_partner_without_a_contract(self):
        Partner.objects.filter(pk=self.partner.pk).update(phase="none")
        found = self.hook_lines(pay(self.seller, status=PaymentStatus.PENDING))
        self.assertEqual(len(found), 1, found)
        self.assertIn("ignorée : partenaire sans contrat", found[0])

    def test_payment_outside_the_twelve_month_window(self):
        first = pay(self.seller)
        record_for_payment(first)
        Referral.objects.filter(pk=self.referral.pk).update(commission_ends_at=timezone.now() - timedelta(days=1))
        found = self.hook_lines(pay(self.seller, status=PaymentStatus.PENDING))
        self.assertEqual(len(found), 1, found)
        self.assertIn("ignorée : hors de la fenêtre de 12 mois", found[0])

    def test_created_line_for_a_regular_payment(self):
        found = self.hook_lines(pay(self.seller, status=PaymentStatus.PENDING))
        self.assertEqual(len(found), 1, found)
        self.assertIn("créée", found[0])
        self.assertIn("commission=594", found[0])


def _log_to_root(outcome):
    import logging

    logging.getLogger("partners.test").info("%s %s", MARK, outcome.message)


class TheHookStillNeverBlocksAPaymentTests(TestCase):
    def setUp(self):
        self.partner = make_partner(code="AWA2026")
        self.seller = make_seller("+22370000101")
        Subscription.objects.get_or_create(seller=self.seller)
        Referral.objects.create(partner=self.partner, seller=self.seller)

    def assertActivated(self, payment):
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(Subscription.objects.get(seller=self.seller).plan, "medium")

    def test_a_failing_fingerprint_does_not_block_nor_roll_back_the_commission(self):
        payment = pay(self.seller, status=PaymentStatus.PENDING)
        with patch("core.services.rate_limit.phone_fingerprint", side_effect=ValueError("empreinte")):
            activate_subscription_from_payment(payment)
        self.assertActivated(payment)
        self.assertEqual(CommissionEntry.objects.count(), 1)  # la commission survit à un journal défaillant

    def test_a_failing_logger_does_not_block_nor_roll_back_the_commission(self):
        payment = pay(self.seller, status=PaymentStatus.PENDING)
        with patch("subscriptions.services.payment._log_commission_outcome", side_effect=OSError("disque plein")):
            activate_subscription_from_payment(payment)
        self.assertActivated(payment)
        self.assertEqual(CommissionEntry.objects.count(), 1)

    def test_a_failing_service_and_a_failing_error_log_still_activate(self):
        payment = pay(self.seller, status=PaymentStatus.PENDING)
        with patch("partners.services.commissions.record_for_payment", side_effect=RuntimeError("boom")), patch(
            "subscriptions.services.payment.logger.error", side_effect=OSError("disque plein")
        ):
            activate_subscription_from_payment(payment)
        self.assertActivated(payment)
        self.assertEqual(CommissionEntry.objects.count(), 0)
