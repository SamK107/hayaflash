"""Crée les commissions manquantes (paiements réussis d'un vendeur inscrit via le lien).

Simulation par défaut : rien n'est écrit ; ``--apply`` pour créer les lignes.
Idempotent : une ligne existante n'est jamais dupliquée. Les paiements sont rejoués
dans l'ordre de paiement pour que la fenêtre de 12 mois démarre au premier.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from partners.services.commissions import record_for_payment
from subscriptions.services.platform_reporting import revenue_payments


class Command(BaseCommand):
    help = "Crée les commissions manquantes (simulation par défaut, --apply pour écrire)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Écrit réellement les lignes.")

    def handle(self, *args, **options):
        apply = options["apply"]
        payments = list(
            revenue_payments()
            .filter(seller__referral__isnull=False, partner_commission__isnull=True)
            .order_by("paid_at", "created_at")
        )
        created = 0
        with transaction.atomic():
            for payment in payments:
                entry = record_for_payment(payment)
                if entry is not None:
                    created += 1
            if not apply:
                transaction.set_rollback(True)  # simulation exacte, rien n'est conservé
        verb = "créée(s)" if apply else "à créer (simulation, rien n'est écrit)"
        self.stdout.write(
            f"{len(payments)} paiement(s) examiné(s) : {created} commission(s) {verb}."
        )
        if not apply and created:
            self.stdout.write("Relancez avec --apply pour les créer.")
