"""F-94 : « Encaissé (FCFA) » ne compte que l'argent réellement encaissé.

Définitions (orders/services/dashboard.py, get_dashboard_kpis) :
- Encaissé (total_revenue)  = commandes DELIVERED dont la livraison a
  cod_collected = True ;
- En cours d'encaissement (pending_revenue) = commandes CONFIRMED ou
  OUT_FOR_DELIVERY, plus les commandes DELIVERED non encaissées
  (cod_collected = False) ;
- PENDING et CANCELLED ne comptent dans aucun des deux.

Cas limite : une commande DELIVERED sans livraison associée (donnée héritée,
create_order crée toujours une livraison) n'est PAS comptée comme encaissée,
faute de preuve ; par prudence elle compte « en cours d'encaissement ».
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone

from delivery.models import Delivery
from delivery.services.seller_dashboard import _auto_sync_stale_deliveries
from delivery.tests import DeliveryTestFixture
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order, OrderItem, OrderStatus
from orders.services.dashboard import get_dashboard_kpis, get_dashboard_kpis_cached

OS = OrderStatus


class EncaisseBase(DeliveryTestFixture):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.sale_b = FlashSale.objects.create(
            title="Autre vente",
            start_time=timezone.now() - timedelta(days=2),
            end_time=timezone.now() - timedelta(days=1),
            status=FlashSaleStatus.CLOSED,
            owner=self.seller,
        )

    def make(self, status, *, collected=None, price=1000, qty=1, sale=None, items=None):
        """Commande + ligne(s) ; livraison seulement si `collected` n'est pas None."""
        order = Order.service_objects.create(
            flash_sale=sale or self.sale,
            customer_name="Client",
            customer_phone="+22370000009",
        )
        Order.service_objects.filter(pk=order.pk).update(status=status)
        for p, q in items or [(price, qty)]:
            OrderItem.objects.create(
                order=order,
                product=self.product,
                product_name_snapshot="Widget",
                price_snapshot=Decimal(p),
                quantity=q,
            )
        if collected is not None:
            Delivery.objects.create(
                order=order,
                address_text="Quartier",
                status=(
                    Delivery.Status.DELIVERED
                    if status == OS.DELIVERED
                    else Delivery.Status.PENDING
                ),
                cod_amount=Decimal(price * qty),
                cod_collected=collected,
            )
        return order

    def kpis(self, sale=None):
        return get_dashboard_kpis(self.seller_user, sale.pk if sale else None)

    def amounts(self, sale=None):
        k = self.kpis(sale)
        return int(k["total_revenue"]), int(k["pending_revenue"])


class AmountDefinitionTests(EncaisseBase):
    def test_delivered_and_collected_is_encaisse_only(self):
        self.make(OS.DELIVERED, collected=True, price=1000, qty=2)
        self.assertEqual(self.amounts(), (2000, 0))

    def test_delivered_not_collected_is_en_cours_not_encaisse(self):
        self.make(OS.DELIVERED, collected=False, price=1500)
        self.assertEqual(self.amounts(), (0, 1500))

    def test_confirmed_and_out_for_delivery_are_en_cours(self):
        self.make(OS.CONFIRMED, collected=False, price=100)
        self.make(OS.OUT_FOR_DELIVERY, collected=False, price=200)
        self.assertEqual(self.amounts(), (0, 300))

    def test_pending_and_cancelled_count_nowhere(self):
        self.make(OS.PENDING, collected=False, price=100)
        self.make(OS.CANCELLED, collected=False, price=200)
        self.assertEqual(self.amounts(), (0, 0))

    def test_delivered_without_delivery_is_never_encaisse(self):
        self.make(OS.DELIVERED, collected=None, price=700)
        encaisse, en_cours = self.amounts()
        self.assertEqual(encaisse, 0)
        self.assertEqual(en_cours, 700)

    def test_all_cases_together(self):
        self.make(OS.DELIVERED, collected=True, price=1000)
        self.make(OS.DELIVERED, collected=False, price=10)
        self.make(OS.CONFIRMED, collected=False, price=20)
        self.make(OS.PENDING, collected=False, price=5000)
        self.make(OS.CANCELLED, collected=False, price=6000)
        self.assertEqual(self.amounts(), (1000, 30))


class ScopeAndJoinTests(EncaisseBase):
    def test_sale_filter_applies_to_both_amounts(self):
        self.make(OS.DELIVERED, collected=True, price=1000, sale=self.sale)
        self.make(OS.DELIVERED, collected=False, price=300, sale=self.sale)
        self.make(OS.DELIVERED, collected=True, price=50, sale=self.sale_b)
        self.make(OS.CONFIRMED, collected=False, price=7, sale=self.sale_b)
        self.assertEqual(self.amounts(self.sale), (1000, 300))
        self.assertEqual(self.amounts(self.sale_b), (50, 7))
        self.assertEqual(self.amounts(), (1050, 307))

    def test_multi_line_order_is_not_double_counted(self):
        self.make(OS.DELIVERED, collected=True, items=[(1000, 2), (500, 1)])
        self.make(OS.DELIVERED, collected=False, items=[(100, 1), (200, 3)])
        self.assertEqual(self.amounts(), (2500, 700))

    def test_other_sellers_orders_are_ignored(self):
        foreign = FlashSale.objects.create(
            title="Etrangere",
            start_time=timezone.now() - timedelta(hours=1),
            end_time=timezone.now() + timedelta(hours=1),
            status=FlashSaleStatus.LIVE,
            owner=self.other_user.seller_profile,
        )
        self.make(OS.DELIVERED, collected=True, price=9999, sale=foreign)
        self.assertEqual(self.amounts(), (0, 0))


class StaleSyncTests(EncaisseBase):
    def test_auto_sync_never_rewrites_unpaid_to_paid(self):
        order = self.make(OS.DELIVERED, collected=False, price=800)
        Delivery.objects.filter(order=order).update(status=Delivery.Status.PENDING)
        _auto_sync_stale_deliveries(Delivery.objects.filter(order=order))
        delivery = Delivery.objects.get(order=order)
        self.assertFalse(delivery.cod_collected)
        self.assertEqual(self.amounts(), (0, 800))

    def test_auto_sync_still_aligns_status_and_delivery_date(self):
        order = self.make(OS.DELIVERED, collected=False, price=800)
        Delivery.objects.filter(order=order).update(status=Delivery.Status.PENDING)
        _auto_sync_stale_deliveries(Delivery.objects.filter(order=order))
        delivery = Delivery.objects.get(order=order)
        self.assertEqual(delivery.status, Delivery.Status.DELIVERED)
        self.assertIsNotNone(delivery.delivered_at)

    def test_auto_sync_keeps_a_true_cod_collected(self):
        order = self.make(OS.DELIVERED, collected=True, price=800)
        Delivery.objects.filter(order=order).update(status=Delivery.Status.PENDING)
        _auto_sync_stale_deliveries(Delivery.objects.filter(order=order))
        self.assertTrue(Delivery.objects.get(order=order).cod_collected)


class CacheInvalidationTests(EncaisseBase):
    def _advance(self, delivery, collected):
        from delivery.services.delivery import advance_delivery

        advance_delivery(
            user=self.seller_user,
            delivery_id=delivery.pk,
            action="mark_delivered",
            payload={"cod_collected": collected},
        )

    def _out_for_delivery(self, price):
        order = self.make(OS.OUT_FOR_DELIVERY, collected=False, price=price)
        return Delivery.objects.get(order=order)

    def test_mark_delivered_collected_moves_amount_to_encaisse(self):
        delivery = self._out_for_delivery(1200)
        cached = get_dashboard_kpis_cached(self.seller_user)  # remplit le cache
        self.assertEqual((int(cached["total_revenue"]), int(cached["pending_revenue"])), (0, 1200))
        self._advance(delivery, True)
        after = get_dashboard_kpis_cached(self.seller_user)
        self.assertEqual((int(after["total_revenue"]), int(after["pending_revenue"])), (1200, 0))

    def test_mark_delivered_not_collected_stays_en_cours(self):
        delivery = self._out_for_delivery(1200)
        get_dashboard_kpis_cached(self.seller_user, self.sale.pk)
        self._advance(delivery, False)
        after = get_dashboard_kpis_cached(self.seller_user, self.sale.pk)
        self.assertEqual((int(after["total_revenue"]), int(after["pending_revenue"])), (0, 1200))

    def test_commandes_page_livre_et_paye_counts_as_encaisse(self):
        """Le bouton « Livré et payé » de la page Commandes affirme le paiement."""
        from orders.services.dashboard import advance_order_status

        order = self.make(OS.OUT_FOR_DELIVERY, collected=False, price=400)
        advance_order_status(user=self.seller_user, order_id=order.pk)
        self.assertEqual(self.amounts(), (400, 0))
