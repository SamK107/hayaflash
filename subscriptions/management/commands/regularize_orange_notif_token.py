"""Regularise le notif_token des paiements Orange en attente.

Contexte (test reel du 27/09, paiement HF-M-D4F26BC7) : Orange Money genere
SON propre notif_token, le renvoie dans la reponse d'initiation
(payment.raw_response["notif_token"]) et l'utilise dans le webhook. Les
paiements inities avant le correctif ont garde notre token : leur webhook
tombe sur « notif_token inconnu » et l'abonnement n'est jamais active.

Cette commande recopie le token d'Orange dans payment.notif_token pour les
paiements EN ATTENTE ou les deux different. Elle n'active rien : on rejoue
ensuite le webhook (ou on laisse la verification active s'en charger).

    python manage.py regularize_orange_notif_token                  # simulation
    python manage.py regularize_orange_notif_token --apply          # ecriture
    python manage.py regularize_orange_notif_token --order-id HF-M-D4F26BC7 --apply

Idempotente : une fois le token recopie, le paiement n'est plus concerne.
Chaque ecriture est tracee dans AuditLog (entity SellerProfile, order_id en
metadonnees ; les tokens ne sont jamais affiches ni journalises en entier).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import audit
from subscriptions.models import PaymentProvider, PaymentStatus, SubscriptionPayment


def _mask(token: str) -> str:
    return f"{token[:8]}..." if token else "(vide)"


class Command(BaseCommand):
    help = "Recopie le notif_token renvoyé par Orange dans les paiements en attente (simulation par défaut)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Écrire (sinon simulation).")
        parser.add_argument("--order-id", help="Limiter à un paiement (order_id).")

    def handle(self, *args, apply: bool = False, order_id: str | None = None, **options):
        qs = SubscriptionPayment.objects.filter(
            status=PaymentStatus.PENDING, provider=PaymentProvider.ORANGE
        ).order_by("created_at")
        if order_id:
            qs = qs.filter(order_id=order_id)

        mode = "ÉCRITURE" if apply else "SIMULATION (aucune écriture, --apply pour appliquer)"
        self.stdout.write(f"Mode : {mode}")

        to_fix = updated = skipped = 0
        for payment in qs:
            orange_token = str((payment.raw_response or {}).get("notif_token") or "").strip()
            if not orange_token or orange_token == payment.notif_token:
                continue
            to_fix += 1
            line = (
                f"{payment.order_id} : notif_token {_mask(payment.notif_token)} "
                f"-> {_mask(orange_token)} (Orange)"
            )
            conflict = (
                SubscriptionPayment.objects.filter(notif_token=orange_token)
                .exclude(pk=payment.pk)
                .exists()
            )
            if conflict:
                skipped += 1
                self.stdout.write(self.style.WARNING(f"{line} - IGNORÉ : token déjà utilisé par un autre paiement"))
                continue
            if not apply:
                self.stdout.write(f"{line} - à corriger")
                continue
            with transaction.atomic():
                locked = SubscriptionPayment.objects.select_for_update().get(pk=payment.pk)
                if locked.status != PaymentStatus.PENDING:
                    skipped += 1
                    self.stdout.write(self.style.WARNING(f"{line} - IGNORÉ : n'est plus en attente"))
                    continue
                old = locked.notif_token
                locked.notif_token = orange_token
                locked.save(update_fields=["notif_token", "updated_at"])
                audit(
                    "subscription_payment.notif_token_regularized",
                    entity_type="SellerProfile",
                    entity_id=locked.seller_id,
                    order_id=locked.order_id,
                    old_token_prefix=_mask(old),
                    new_token_prefix=_mask(orange_token),
                )
            updated += 1
            self.stdout.write(self.style.SUCCESS(f"{line} - corrigé"))

        summary = f"{to_fix} paiement(s) concerné(s), {updated} corrigé(s), {skipped} ignoré(s)."
        if not to_fix:
            summary = "Aucun paiement en attente à régulariser."
        self.stdout.write(summary)
