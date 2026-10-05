"""F-99 : la livraison d'une commande annulée (ou expirée, F-59) ne compte plus.

Avant correctif, le tableau de bord Livraisons, l'API et la pastille de navigation
ne connaissaient pas le statut de commande « Annulé » : la livraison restait
« en attente » et comptait dans « À encaisser » et dans les compteurs.

Une commande expirée par la tâche de F-59 est simplement une commande passée au
statut CANCELLED : on simule ce statut ici (le module d'expiration vit sur une
autre branche).
"""

from __future__ import annotations

from decimal import Decimal

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

from core.context_processors import seller_interests_count
from delivery.models import Delivery
from delivery.services.delivery import advance_delivery, list_seller_deliveries
from delivery.services.seller_dashboard import (
    get_delivery_row_context,
    get_delivery_summary,
    list_delivery_rows,
)
from delivery.tests import DeliveryTestFixture
from django.test import RequestFactory
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order, OrderStatus

OS = OrderStatus
DS = Delivery.Status


class CancelledDeliveryBase(DeliveryTestFixture):
    def setUp(self):
        super().setUp()
        cache.clear()

    def make(self, order_status, delivery_status=DS.PENDING, *, cod=1000, sale=None, collected=False):
        order = Order.service_objects.create(
            flash_sale=sale or self.sale,
            customer_name="Client",
            customer_phone="+22370000009",
        )
        Order.service_objects.filter(pk=order.pk).update(status=order_status)
        return Delivery.objects.create(
            order=order,
            address_text="Quartier",
            status=delivery_status,
            cod_amount=Decimal(cod),
            cod_collected=collected,
        )

    def summary(self, sale=None):
        return get_delivery_summary(user=self.seller_user, flash_sale_id=(sale or self.sale).pk)

    def rows(self, status=None, sale=None):
        return list_delivery_rows(
            user=self.seller_user, flash_sale_id=(sale or self.sale).pk, status_filter=status
        )

    def nav(self, user=None):
        request = RequestFactory().get("/seller/")
        request.user = user or self.seller_user
        return seller_interests_count(request)


class CancelledNotCountedTests(CancelledDeliveryBase):
    def test_summary_ignores_cancelled_pending_delivery(self):
        self.make(OS.CANCELLED, DS.PENDING, cod=5000)
        s = self.summary()
        self.assertEqual(s["total_orders"], 0)
        self.assertEqual(s["pending"], 0)
        self.assertEqual(s["total_cod_pending"], 0)

    def test_default_list_and_pending_filter_ignore_cancelled(self):
        self.make(OS.CANCELLED, DS.PENDING)
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.rows("all"), [])
        self.assertEqual(self.rows("pending"), [])

    def test_nav_in_progress_counter_ignores_cancelled_assigned_and_in_transit(self):
        self.make(OS.CANCELLED, DS.ASSIGNED)
        self.make(OS.CANCELLED, DS.IN_TRANSIT)
        self.make(OS.CANCELLED, DS.PENDING)
        self.assertEqual(self.nav()["deliveries_active_count"], 0)

    def test_api_list_and_summary_ignore_cancelled(self):
        self.make(OS.CANCELLED, DS.PENDING, cod=7000)
        data = list_seller_deliveries(user=self.seller_user, flash_sale_id=self.sale.pk)
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["summary"]["pending"], 0)
        self.assertEqual(Decimal(data["summary"]["total_cod_pending"]), 0)

    def test_expired_order_status_is_treated_the_same(self):
        # Commande expirée par F-59 = statut CANCELLED ; livraison jamais touchée.
        self.make(OS.PENDING, DS.PENDING, cod=100)
        d = self.make(OS.PENDING, DS.PENDING, cod=9000)
        Order.service_objects.filter(pk=d.order_id).update(status=OS.CANCELLED)
        s = self.summary()
        self.assertEqual((s["total_orders"], s["pending"], int(s["total_cod_pending"])), (1, 1, 100))


class UnchangedBehaviourTests(CancelledDeliveryBase):
    def test_confirmed_out_for_delivery_and_delivered_still_counted(self):
        self.make(OS.CONFIRMED, DS.PENDING, cod=100)
        self.make(OS.OUT_FOR_DELIVERY, DS.IN_TRANSIT, cod=200)
        self.make(OS.DELIVERED, DS.DELIVERED, cod=400, collected=True)
        self.make(OS.DELIVERED, DS.DELIVERED, cod=800, collected=False)
        s = self.summary()
        self.assertEqual(s["total_orders"], 4)
        self.assertEqual(s["pending"], 1)
        self.assertEqual(s["in_transit"], 1)
        self.assertEqual(s["delivered"], 2)
        self.assertEqual(int(s["total_cod_collected"]), 400)
        self.assertEqual(int(s["total_cod_pending"]), 100 + 200 + 800)
        self.assertEqual(len(self.rows()), 4)
        self.assertEqual(self.nav()["deliveries_active_count"], 1)

    def test_failed_delivery_of_live_order_still_counted(self):
        self.make(OS.CONFIRMED, DS.FAILED)
        self.assertEqual(self.summary()["failed"], 1)

    def test_sale_filter_and_seller_isolation(self):
        other_sale = FlashSale.objects.create(
            title="Autre",
            start_time=self.sale.start_time,
            end_time=self.sale.end_time,
            status=FlashSaleStatus.LIVE,
            owner=self.seller,
        )
        foreign = FlashSale.objects.create(
            title="Etrangère",
            start_time=self.sale.start_time,
            end_time=self.sale.end_time,
            status=FlashSaleStatus.LIVE,
            owner=self.other_user.seller_profile,
        )
        self.make(OS.CONFIRMED, DS.PENDING, cod=100)
        self.make(OS.CONFIRMED, DS.PENDING, cod=10, sale=other_sale)
        self.make(OS.CONFIRMED, DS.PENDING, cod=99999, sale=foreign)
        self.make(OS.CANCELLED, DS.PENDING, cod=5000)
        self.assertEqual(int(self.summary()["total_cod_pending"]), 100)
        self.assertEqual(int(self.summary(other_sale)["total_cod_pending"]), 10)
        with self.assertRaises(Exception):
            get_delivery_summary(user=self.seller_user, flash_sale_id=foreign.pk)


class CancelledFilterTests(CancelledDeliveryBase):
    def test_cancelled_filter_lists_them_read_only(self):
        d = self.make(OS.CANCELLED, DS.PENDING, cod=5000)
        self.make(OS.CONFIRMED, DS.PENDING)
        rows = self.rows("cancelled")
        self.assertEqual([r["delivery"].pk for r in rows], [d.pk])
        row = rows[0]
        self.assertEqual(row["status_label"], "Commande annulée")
        for flag in ("can_confirm", "can_start_delivery", "can_mark_delivered", "can_mark_failed"):
            self.assertFalse(row[flag], flag)

    def test_row_context_of_a_cancelled_delivery_has_no_actions(self):
        d = self.make(OS.CANCELLED, DS.PENDING)
        row = get_delivery_row_context(user=self.seller_user, delivery_id=d.pk)
        self.assertFalse(row["can_mark_failed"])
        self.assertEqual(row["status_label"], "Commande annulée")

    def test_dashboard_page_offers_the_cancelled_filter(self):
        client = Client()
        client.force_login(self.seller_user)
        page = client.get(reverse("orders:seller_deliveries_dashboard"), {"flash_sale_id": self.sale.pk})
        self.assertContains(page, "Annulées")


class ActionsRefusedTests(CancelledDeliveryBase):
    ACTIONS = (
        ("confirm", {}),
        ("start_delivery", {"assigned_to": "Moussa"}),
        ("mark_delivered", {"cod_collected": True}),
        ("mark_failed", {}),
    )

    def test_every_action_is_refused_server_side_in_french(self):
        d = self.make(OS.CANCELLED, DS.PENDING)
        for action, payload in self.ACTIONS:
            with self.subTest(action=action):
                with self.assertRaises(ValidationError) as ctx:
                    advance_delivery(
                        user=self.seller_user, delivery_id=d.pk, action=action, payload=payload
                    )
                self.assertIn("annulée", " ".join(ctx.exception.messages))
        d.refresh_from_db()
        self.assertEqual(d.status, DS.PENDING)
        self.assertEqual(d.order.status, OS.CANCELLED)

    def test_http_action_on_cancelled_delivery_is_refused_with_message(self):
        d = self.make(OS.CANCELLED, DS.PENDING)
        client = Client(enforce_csrf_checks=False)
        client.force_login(self.seller_user)
        url = reverse("orders:seller_delivery_action", args=[d.pk])
        resp = client.post(url, {"action": "mark_failed"}, HTTP_HX_REQUEST="true")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("annulée", resp.content.decode())
        d.refresh_from_db()
        self.assertEqual(d.status, DS.PENDING)

    def test_live_order_actions_unchanged(self):
        d = self.make(OS.PENDING, DS.PENDING)
        advance_delivery(user=self.seller_user, delivery_id=d.pk, action="confirm")
        d.refresh_from_db()
        self.assertEqual(d.order.status, OS.CONFIRMED)
        advance_delivery(user=self.seller_user, delivery_id=d.pk, action="mark_failed")
        d.refresh_from_db()
        self.assertEqual(d.status, DS.FAILED)
