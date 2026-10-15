"""F-129 : trois libellés trompeurs corrigés (fiche staff d'un partenaire en essai, relevé, « Essai jusqu'au »)."""

from __future__ import annotations

from django.urls import reverse
from django.utils import timezone

from partners.models import Partner
from partners.services.payouts import statement_text
from partners.tests_documents_admin import Base as StaffBase
from partners.tests_models import make_partner
from partners.tests_payouts import Base as PayoutBase
from partners.tests_payouts import at

NOTE = "(applicable après acceptation des conditions du programme)"


class SheetCommissionLabelTests(StaffBase):
    def sheet(self, partner):
        return self.client.get(reverse("partners_detail", args=[partner.pk])).content.decode()

    def test_trial_partner_sees_the_commission_as_not_yet_applicable(self):
        trial = make_partner(
            code="ESSAI01", phone="+22360080001", name="Fanta", phase="trial", status="active",
            trial_start=timezone.localdate(), accept=False,
        )
        html = self.sheet(trial)
        self.assertIn(f"Commission : 30 % {NOTE}", html)

    def test_partner_without_phase_sees_the_same_note(self):
        html = self.sheet(self.prospect)  # prospect, phase « aucune »
        self.assertIn(f"Commission : 30 % {NOTE}", html)

    def test_partner_under_contract_sees_the_plain_commission(self):
        contract = make_partner(code="CONTRAT1", phone="+22360080002")
        html = self.sheet(contract)
        self.assertIn("Commission : 30 %", html)
        self.assertNotIn(NOTE, html)


class SheetTrialEndLabelTests(StaffBase):
    def sheet(self, partner):
        return self.client.get(reverse("partners_detail", args=[partner.pk])).content.decode()

    def test_trial_end_is_shown_during_the_trial(self):
        trial = make_partner(
            code="ESSAI01", phone="+22360080001", phase="trial", status="active",
            trial_start=timezone.localdate(), accept=False,
        )
        self.assertIn("Essai jusqu'au", self.sheet(trial))

    def test_trial_end_is_hidden_once_the_partner_is_under_contract(self):
        contract = make_partner(code="CONTRAT1", phone="+22360080002")
        Partner.objects.filter(pk=contract.pk).update(
            trial_start=timezone.localdate(), trial_end=timezone.localdate()
        )  # un partenaire passé de l'essai au contrat garde ses dates d'essai
        html = self.sheet(Partner.objects.get(pk=contract.pk))
        self.assertIn("Phase : Contrat", html)
        self.assertNotIn("Essai jusqu'au", html)


class StatementCumulLabelTests(PayoutBase):
    def test_label_says_the_cumul_counts_validated_commissions_only(self):
        self.entry(commission=2079, status="validated")
        text = statement_text(self.partner, "2026-10")
        self.assertIn("Cumul non versé (commissions validées) : 2 079 FCFA", text)
        self.assertNotIn("Cumul non versé : ", text)
        self.assertNotIn("en attente de validation", text)

    def test_pending_commissions_are_shown_apart(self):
        self.entry(commission=2079, status="validated")
        self.entry(commission=29, status="pending")
        text = statement_text(self.partner, "2026-10")
        self.assertIn(
            "Cumul non versé (commissions validées) : 2 079 FCFA, hors 29 FCFA en attente de validation", text
        )

    def test_only_pending_commissions_show_a_zero_cumul_with_the_explanation(self):
        self.entry(commission=29, status="pending")
        text = statement_text(self.partner, "2026-10")
        self.assertIn("Commission du mois : 29 FCFA", text)
        self.assertIn(
            "Cumul non versé (commissions validées) : 0 FCFA, hors 29 FCFA en attente de validation", text
        )

    def test_cancelled_and_other_months_pending_commissions_are_not_counted_as_waiting(self):
        self.entry(commission=29, status="cancelled")
        self.entry(commission=40, status="pending", when=at(2026, 11))  # après la fin de la période
        text = statement_text(self.partner, "2026-10")
        self.assertNotIn("en attente de validation", text)
