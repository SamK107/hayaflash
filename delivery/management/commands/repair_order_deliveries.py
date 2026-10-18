"""Rattrapage des commandes dont la fiche de livraison manque ou diverge.

Cause (voir docs/releases/reports/commandes-livraison-circuit-unique.md) : des
commandes anciennes n'ont pas de fiche de livraison, ou ont été passées « en
livraison » / « livré » depuis la page Commandes sans que la fiche suive. Elles
avançaient dans Commandes mais restaient invisibles ou bloquées sur Livraison.

  python manage.py repair_order_deliveries --dry-run   # affiche, ne modifie rien
  python manage.py repair_order_deliveries             # applique

Idempotent : un second passage ne change plus rien. Ne touche ni aux commandes
annulées, ni à l'encaissement (``cod_collected``), ni aux échecs enregistrés.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from delivery.models import Delivery
from delivery.services.delivery import ensure_delivery_for_order
from orders.models import Order, OrderStatus


class Command(BaseCommand):
    help = "Crée les fiches de livraison manquantes et réaligne les statuts divergents."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Affiche sans rien modifier.")

    def handle(self, *args, dry_run=False, **options):
        now = timezone.now()
        created = delivered = in_transit = 0
        prefix = "[dry-run] " if dry_run else ""

        missing = Order.service_objects.filter(delivery__isnull=True).exclude(
            status=OrderStatus.CANCELLED
        ).select_related("flash_sale")
        for order in missing.iterator():
            created += 1
            self.stdout.write(f"{prefix}fiche manquante : commande #{order.pk} ({order.get_status_display()})")
            if not dry_run:
                with transaction.atomic():
                    ensure_delivery_for_order(order)

        stale_delivered = Delivery.objects.filter(order__status=OrderStatus.DELIVERED).exclude(
            status=Delivery.Status.DELIVERED
        )
        for d in stale_delivered.iterator():
            delivered += 1
            self.stdout.write(f"{prefix}livraison {d.pk} : {d.status} -> delivered (commande #{d.order_id})")
            if not dry_run:
                d.status = Delivery.Status.DELIVERED
                d.delivered_at = d.delivered_at or now
                d.save(update_fields=["status", "delivered_at", "updated_at"])

        stale_transit = Delivery.objects.filter(
            order__status=OrderStatus.OUT_FOR_DELIVERY,
            status__in=[Delivery.Status.PENDING, Delivery.Status.ASSIGNED],
        )
        for d in stale_transit.iterator():
            in_transit += 1
            self.stdout.write(f"{prefix}livraison {d.pk} : {d.status} -> in_transit (commande #{d.order_id})")
            if not dry_run:
                d.status = Delivery.Status.IN_TRANSIT
                d.scheduled_at = d.scheduled_at or now
                d.save(update_fields=["status", "scheduled_at", "updated_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}{created} fiche(s) créée(s), {delivered} réalignée(s) 'livré', "
                f"{in_transit} réalignée(s) 'en livraison'."
            )
        )
