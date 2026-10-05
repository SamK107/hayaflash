"""Bout en bout : expiration F-59 + livraisons F-99.

Une commande en attente depuis plus de 48 h est expirée par la VRAIE tâche
`orders.expire_pending_orders` (pas un simple changement de statut) ; sa
livraison, restée « en attente », ne doit plus compter nulle part côté vendeur.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import RequestFactory
from django.utils import timezone

from core.context_processors import seller_interests_count
from delivery.models import Delivery
from delivery.services.delivery import list_seller_deliveries
from delivery.services.seller_dashboard import get_delivery_summary, list_delivery_rows
from orders.models import Order, OrderStatus
from orders.services.create_order import create_order
from orders.tasks import expire_pending_orders_task
from orders.tests import LiveFlashSaleProductFixture, _valid_delivery
from products.models import StockMovement


class ExpirationAndDeliveriesEndToEndTests(LiveFlashSaleProductFixture):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.old = self._place("old", qty=2, hours_ago=60)
        self.recent = self._place("recent", qty=3, hours_ago=2)

    def _place(self, key, *, qty, hours_ago):
        order = create_order(
            {
                "flash_sale_id": self.sale.pk,
                "customer_name": "Awa",
                "customer_phone": "+22370000009",
                "client_request_id": f"e2e-{key}",
                "items": [{"product_id": self.product.pk, "quantity": qty}],
                "delivery": _valid_delivery(),
            }
        )
        Order.service_objects.filter(pk=order.pk).update(
            created_at=timezone.now() - timedelta(hours=hours_ago)
        )
        return Order.service_objects.get(pk=order.pk)

    def _stock(self):
        self.product.refresh_from_db()
        return self.product.stock_available

    def _nav(self):
        request = RequestFactory().get("/seller/")
        request.user = self.seller_user
        return seller_interests_count(request)

    def _summary(self):
        return get_delivery_summary(user=self.seller_user, flash_sale_id=self.sale.pk)

    def _rows(self, status=None):
        return list_delivery_rows(
            user=self.seller_user, flash_sale_id=self.sale.pk, status_filter=status
        )

    def test_scenario(self):
        old_delivery = Delivery.objects.get(order=self.old)
        recent_delivery = Delivery.objects.get(order=self.recent)
        self.assertEqual(old_delivery.status, Delivery.Status.PENDING)
        self.assertEqual(self._stock(), 10 - 2 - 3)

        # Avant : les deux livraisons comptent.
        before = self._summary()
        self.assertEqual(before["total_orders"], 2)
        self.assertEqual(before["pending"], 2)
        self.assertEqual(len(self._rows()), 2)

        expire_pending_orders_task()  # la vraie tâche

        # Commande annulée, stock restitué une seule fois.
        self.old.refresh_from_db()
        self.assertEqual(self.old.status, OrderStatus.CANCELLED)
        self.assertEqual(self._stock(), 10 - 3)
        releases = StockMovement.objects.filter(
            order=self.old, movement_type=StockMovement.MovementType.RELEASE
        )
        self.assertEqual(releases.count(), 1)

        # Livraison expirée : absente du résumé, de « À encaisser », de la liste, de l'API.
        old_delivery.refresh_from_db()
        self.assertEqual(old_delivery.status, Delivery.Status.PENDING)  # jamais touchée
        summary = self._summary()
        self.assertEqual(summary["total_orders"], 1)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(
            summary["total_cod_pending"], Decimal(recent_delivery.cod_amount)
        )
        self.assertEqual([r["delivery"].pk for r in self._rows()], [recent_delivery.pk])
        self.assertEqual([r["delivery"].pk for r in self._rows("pending")], [recent_delivery.pk])
        api = list_seller_deliveries(user=self.seller_user, flash_sale_id=self.sale.pk)
        self.assertEqual(api["count"], 1)

        # Pastille « livraisons en cours » : même une livraison assignée d'une commande annulée.
        Delivery.objects.filter(pk=old_delivery.pk).update(status=Delivery.Status.ASSIGNED)
        cache.clear()
        self.assertEqual(self._nav()["deliveries_active_count"], 0)
        Delivery.objects.filter(pk=old_delivery.pk).update(status=Delivery.Status.PENDING)

        # Visible, en lecture seule, sous « Annulées ».
        cancelled = self._rows("cancelled")
        self.assertEqual([r["delivery"].pk for r in cancelled], [old_delivery.pk])
        row = cancelled[0]
        self.assertEqual(row["status_label"], "Commande annulée")
        for flag in ("can_confirm", "can_start_delivery", "can_mark_delivered", "can_mark_failed"):
            self.assertFalse(row[flag], flag)

        # Seconde exécution : rien ne change.
        expire_pending_orders_task()
        self.assertEqual(self._stock(), 10 - 3)
        self.assertEqual(releases.count(), 1)
        self.assertEqual(self._summary()["total_orders"], 1)
        self.assertEqual(len(self._rows("cancelled")), 1)

        # Commande récente du même vendeur : toujours comptée normalement.
        self.recent.refresh_from_db()
        self.assertEqual(self.recent.status, OrderStatus.PENDING)
        self.assertEqual(self._summary()["pending"], 1)
        self.assertEqual(
            self._summary()["total_cod_pending"], Decimal(recent_delivery.cod_amount)
        )
