"""F-59 : une commande jamais confirmée expire après 48 h et rend son stock.

Une commande à paiement à la livraison réserve le stock dès sa création
(create_order). Sans expiration, un bot vide une vente sans jamais payer.
`expire_pending_orders` passe en « annulée » les commandes restées en attente
depuis plus de ORDER_PENDING_EXPIRY_HOURS et restitue leur stock, une seule fois.
"""

from __future__ import annotations

import importlib
import threading
from datetime import timedelta
from decimal import Decimal
from unittest import skipIf
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone

from accounts.models import SellerProfile
from core.models import AuditLog
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order, OrderStatus
from orders.services.create_order import create_order
from orders.services.dashboard import advance_order_status, get_dashboard_kpis
from orders.services.expiration import expire_pending_orders
from orders.tests import LiveFlashSaleProductFixture, _valid_delivery
from products.models import FlashSaleProduct, Product, StockMovement

User = get_user_model()
OS = OrderStatus
HOURS = 48


class ExpirationBase(LiveFlashSaleProductFixture):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.t0 = timezone.now() - timedelta(days=10)
        self.product2 = Product.objects.create(
            owner=self.seller,
            name="Autre",
            stock_available=5,
            stock_initial=5,
            price=Decimal("500"),
        )
        FlashSaleProduct.objects.create(flash_sale=self.sale, product=self.product2)
        self._n = 0

    def place(self, lines=((None, 2),), *, created_at=None, status=OS.PENDING):
        """Commande réelle via create_order (réserve le stock), puis recalée dans le temps."""
        self._n += 1
        items = [
            {"product_id": (p or self.product).pk, "quantity": q} for p, q in lines
        ]
        order = create_order(
            {
                "flash_sale_id": self.sale.pk,
                "customer_name": "Awa",
                "customer_phone": "+22370000009",
                "client_request_id": f"exp-{self._n}",
                "items": items,
                "delivery": _valid_delivery(),
            }
        )
        Order.service_objects.filter(pk=order.pk).update(
            created_at=created_at or self.t0, status=status
        )
        return order

    def stock(self, product=None):
        p = product or self.product
        p.refresh_from_db()
        return p.stock_available

    def status(self, order):
        order.refresh_from_db()
        return order.status

    def expire(self, hours=HOURS, minutes=1):
        return expire_pending_orders(now=self.t0 + timedelta(hours=hours, minutes=minutes))


class SettingTests(SimpleTestCase):
    def test_single_constant_is_48_hours_in_test_and_deployed_settings(self):
        self.assertEqual(settings.ORDER_PENDING_EXPIRY_HOURS, 48)
        base = importlib.import_module("config.settings.base")
        self.assertEqual(base.ORDER_PENDING_EXPIRY_HOURS, 48)


class BoundaryTests(ExpirationBase):
    def test_47h59_is_not_expired(self):
        order = self.place()
        self.assertEqual(self.expire(hours=47, minutes=59), 0)
        self.assertEqual(self.status(order), OS.PENDING)
        self.assertEqual(self.stock(), 8)

    def test_48h01_is_expired_and_stock_returned(self):
        order = self.place()
        self.assertEqual(self.stock(), 8)
        self.assertEqual(self.expire(hours=48, minutes=1), 1)
        self.assertEqual(self.status(order), OS.CANCELLED)
        self.assertEqual(self.stock(), 10)

    def test_exactly_48h_is_not_yet_expired(self):
        order = self.place()
        self.assertEqual(self.expire(hours=48, minutes=0), 0)
        self.assertEqual(self.status(order), OS.PENDING)


class IdempotenceTests(ExpirationBase):
    def test_second_run_returns_stock_only_once(self):
        order = self.place()
        self.assertEqual(self.expire(), 1)
        self.assertEqual(self.expire(), 0)
        self.assertEqual(self.expire(hours=500), 0)
        self.assertEqual(self.stock(), 10)
        releases = StockMovement.objects.filter(
            order=order, movement_type=StockMovement.MovementType.RELEASE
        )
        self.assertEqual(releases.count(), 1)
        self.assertEqual(releases.get().quantity_change, 2)

    def test_audit_trace_one_per_expired_order(self):
        a, b = self.place(), self.place()
        self.expire()
        self.expire()
        rows = AuditLog.objects.filter(action="order.expired", entity_type="Order")
        self.assertEqual(sorted(rows.values_list("entity_id", flat=True)), sorted([a.pk, b.pk]))

    def test_no_notification_is_sent(self):
        from notifications.models import Notification

        self.place()
        before = Notification.objects.count()
        with patch("notifications.services.sms.send_sms") as sms:
            self.expire()
        sms.assert_not_called()
        self.assertEqual(Notification.objects.count(), before)


class UntouchedStatusesTests(ExpirationBase):
    def test_confirmed_out_for_delivery_delivered_and_cancelled_are_untouched(self):
        orders = {s: self.place(status=s) for s in (OS.CONFIRMED, OS.OUT_FOR_DELIVERY, OS.DELIVERED, OS.CANCELLED)}
        stock_before = self.stock()
        self.assertEqual(self.expire(), 0)
        for status, order in orders.items():
            self.assertEqual(self.status(order), status)
        self.assertEqual(self.stock(), stock_before)
        self.assertFalse(
            StockMovement.objects.filter(movement_type=StockMovement.MovementType.RELEASE).exists()
        )

    def test_recent_pending_orders_are_untouched_next_to_expired_ones(self):
        old = self.place()
        recent = self.place(created_at=self.t0 + timedelta(hours=40))
        self.expire()
        self.assertEqual(self.status(old), OS.CANCELLED)
        self.assertEqual(self.status(recent), OS.PENDING)
        self.assertEqual(self.stock(), 10 - 2)


class MultiLineTests(ExpirationBase):
    def test_each_product_of_each_line_is_returned(self):
        order = self.place(lines=((None, 3), (self.product2, 2)))
        self.assertEqual((self.stock(), self.stock(self.product2)), (7, 3))
        self.expire()
        self.assertEqual(self.status(order), OS.CANCELLED)
        self.assertEqual((self.stock(), self.stock(self.product2)), (10, 5))

    def test_same_product_on_two_lines_is_returned_in_full_once(self):
        order = self.place(lines=((None, 1), (None, 2)))
        self.assertEqual(self.stock(), 7)
        self.expire()
        self.expire()
        self.assertEqual(self.stock(), 10)
        self.assertEqual(
            StockMovement.objects.filter(
                order=order, movement_type=StockMovement.MovementType.RELEASE
            ).count(),
            1,
        )

    def test_two_orders_same_product(self):
        self.place(lines=((None, 2),))
        self.place(lines=((None, 4),))
        self.assertEqual(self.stock(), 4)
        self.assertEqual(self.expire(), 2)
        self.assertEqual(self.stock(), 10)


class ClosedSaleTests(ExpirationBase):
    def test_stock_returns_even_if_the_sale_was_closed_meanwhile(self):
        order = self.place()
        FlashSale.objects.filter(pk=self.sale.pk).update(status=FlashSaleStatus.CLOSED)
        self.assertEqual(self.expire(), 1)
        self.assertEqual(self.status(order), OS.CANCELLED)
        self.assertEqual(self.stock(), 10)


class ConfirmedMeanwhileTests(ExpirationBase):
    def test_order_confirmed_after_candidate_selection_is_left_alone(self):
        order = self.place()
        from orders.services import expiration

        real = expiration._candidate_ids

        def stale_candidates(cutoff):
            ids = real(cutoff)
            # Le vendeur confirme entre la sélection et le verrou.
            Order.service_objects.filter(pk=order.pk).update(status=OS.CONFIRMED)
            return ids

        with patch.object(expiration, "_candidate_ids", stale_candidates):
            self.assertEqual(self.expire(), 0)
        self.assertEqual(self.status(order), OS.CONFIRMED)
        self.assertEqual(self.stock(), 8)

    def test_advance_on_an_expired_order_is_refused(self):
        order = self.place()
        self.expire()
        with self.assertRaises(ValidationError):
            advance_order_status(user=self.seller_user, order_id=order.pk)
        self.assertEqual(self.status(order), OS.CANCELLED)


class DashboardAmountsTests(ExpirationBase):
    def test_expired_orders_count_nowhere_in_encaisse_or_en_cours(self):
        from delivery.models import Delivery

        kept = self.place(lines=((None, 1),), status=OS.CONFIRMED)
        expired = self.place(lines=((None, 4),))
        Delivery.objects.filter(order=expired).update(cod_collected=False)
        before = get_dashboard_kpis(self.seller_user)
        self.assertEqual(before["total_orders"], 2)
        self.expire()
        after = get_dashboard_kpis(self.seller_user)
        self.assertEqual(after["total_orders"], 1)
        self.assertEqual(after["total_revenue"], 0)
        self.assertEqual(int(after["pending_revenue"]), 1999)  # la commande confirmée seule
        self.assertEqual(self.status(kept), OS.CONFIRMED)


class SchedulingTests(SimpleTestCase):
    def test_task_is_in_beat_schedule_every_15_minutes(self):
        base = importlib.import_module("config.settings.base")
        entries = [
            e for e in base.CELERY_BEAT_SCHEDULE.values() if e["task"] == "orders.expire_pending_orders"
        ]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["schedule"], 900.0)

    def test_task_queue_is_listened_by_the_worker(self):
        from celery import Celery

        base = importlib.import_module("config.settings.base")
        importlib.import_module("orders.tasks")
        app = Celery("hayaflash-check")
        app.config_from_object(base, namespace="CELERY")
        route = app.amqp.router.route({}, "orders.expire_pending_orders")
        self.assertIn(route["queue"].name, base.CELERY_WORKER_QUEUES)
        entry = next(
            e for e in base.CELERY_BEAT_SCHEDULE.values() if e["task"] == "orders.expire_pending_orders"
        )
        # Pas de file imposée dans le planning : la file par défaut (écoutée) s'applique.
        self.assertNotIn("queue", entry.get("options", {}))

    def test_task_runs_the_service(self):
        from orders.tasks import expire_pending_orders_task

        with patch("orders.tasks.expire_pending_orders", return_value=3) as svc:
            expire_pending_orders_task()
        svc.assert_called_once_with()


@skipIf(connection.vendor == "sqlite", "La concurrence exige PostgreSQL")
class ExpirationConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(phone="+15550007777", password="x", display_name="S")
        self.seller = SellerProfile.objects.create(user=self.user)
        now = timezone.now()
        self.sale = FlashSale.objects.create(
            title="Course",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            status=FlashSaleStatus.LIVE,
            owner=self.seller,
        )
        self.product = Product.objects.create(
            owner=self.seller, name="Hot", stock_available=5, stock_initial=5, price=Decimal("1000")
        )
        FlashSaleProduct.objects.create(flash_sale=self.sale, product=self.product)

    def _stale_order(self):
        order = create_order(
            {
                "flash_sale_id": self.sale.pk,
                "customer_name": "T",
                "customer_phone": "+1",
                "client_request_id": f"race-{threading.get_ident()}-{Order.objects.count()}",
                "items": [{"product_id": self.product.pk, "quantity": 2}],
                "delivery": _valid_delivery(),
            }
        )
        old = timezone.now() - timedelta(hours=60)
        Order.service_objects.filter(pk=order.pk).update(created_at=old)
        return order

    def test_confirm_racing_with_expiration_never_loses_or_duplicates_stock(self):
        for _ in range(8):
            order = self._stale_order()
            barrier = threading.Barrier(2)

            def expirer():
                close_old_connections()
                try:
                    barrier.wait()
                    expire_pending_orders()
                finally:
                    close_old_connections()

            def confirmer():
                close_old_connections()
                try:
                    barrier.wait()
                    try:
                        advance_order_status(user=self.user, order_id=order.pk)
                    except ValidationError:
                        pass
                finally:
                    close_old_connections()

            threads = [threading.Thread(target=expirer), threading.Thread(target=confirmer)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            order.refresh_from_db()
            self.product.refresh_from_db()
            releases = StockMovement.objects.filter(
                order=order, movement_type=StockMovement.MovementType.RELEASE
            ).count()
            if order.status == OS.CANCELLED:
                self.assertEqual(releases, 1)
            else:
                self.assertEqual(order.status, OS.CONFIRMED)
                self.assertEqual(releases, 0)
            # Invariant : stock = initial - réservé par les commandes non annulées.
            held = sum(
                i.quantity
                for o in Order.service_objects.exclude(status=OS.CANCELLED)
                for i in o.items.all()
            )
            self.assertEqual(self.product.stock_available, 5 - held)
            Order.service_objects.all().delete()
            Product.objects.filter(pk=self.product.pk).update(stock_available=5)
