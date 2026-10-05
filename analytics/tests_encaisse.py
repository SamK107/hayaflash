"""F-95 : l'analytique compte le CA comme les cartes de la page Commandes (F-94).

Un même jeu de commandes doit donner les mêmes montants sur les cartes
(`get_dashboard_kpis`) et sur les courbes, classements et ventes par vente
(`analytics.services.reporting`) : « Encaissé » = commande livrée ET livraison
`cod_collected`. Livrée non encaissée, livrée sans livraison, annulée : jamais
dans le CA de l'analytique.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone

from analytics.services.reporting import (
    get_flash_sale_stats,
    get_revenue_timeline,
    get_revenue_timeline_monthly,
    get_sales_by_flash,
    get_top_products,
)
from delivery.models import Delivery
from delivery.tests import DeliveryTestFixture
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order, OrderItem, OrderStatus
from orders.services.dashboard import get_dashboard_kpis

OS = OrderStatus


class ReportingEncaisseBase(DeliveryTestFixture):
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

    def make(self, status, *, collected=None, items=((1000, 1),), sale=None, name="Widget"):
        order = Order.service_objects.create(
            flash_sale=sale or self.sale,
            customer_name="Client",
            customer_phone="+22370000009",
        )
        Order.service_objects.filter(pk=order.pk).update(status=status)
        for price, qty in items:
            OrderItem.objects.create(
                order=order,
                product=self.product,
                product_name_snapshot=name,
                price_snapshot=Decimal(price),
                quantity=qty,
            )
        if collected is not None:
            Delivery.objects.create(
                order=order,
                address_text="Quartier",
                status=Delivery.Status.DELIVERED
                if status == OS.DELIVERED
                else Delivery.Status.PENDING,
                cod_amount=Decimal(0),
                cod_collected=collected,
            )
        return order

    def seed_mixed(self):
        self.make(OS.DELIVERED, collected=True, items=((1000, 2), (500, 1)))  # 2500
        self.make(OS.DELIVERED, collected=False, items=((9000, 1),))
        self.make(OS.DELIVERED, collected=None, items=((8000, 1),))
        self.make(OS.CANCELLED, collected=False, items=((7000, 1),))
        self.make(OS.CONFIRMED, collected=False, items=((6000, 1),))

    def card(self, sale=None):
        return int(
            get_dashboard_kpis(self.seller_user, sale.pk if sale else None)["total_revenue"]
        )


class SameTotalsAsCardsTests(ReportingEncaisseBase):
    def test_timeline_30d_matches_card(self):
        self.seed_mixed()
        total = sum(r["revenue"] for r in get_revenue_timeline(self.seller.pk))
        self.assertEqual(int(total), 2500)
        self.assertEqual(int(total), self.card())

    def test_timeline_monthly_matches_card(self):
        self.seed_mixed()
        total = sum(r["revenue"] for r in get_revenue_timeline_monthly(self.seller.pk))
        self.assertEqual(int(total), self.card())

    def test_top_products_revenue_matches_card(self):
        self.seed_mixed()
        rows = get_top_products(self.seller.pk)
        self.assertEqual(int(sum(r["total_revenue"] for r in rows)), self.card())

    def test_sales_by_flash_revenue_matches_card(self):
        self.seed_mixed()
        self.make(OS.DELIVERED, collected=True, items=((300, 1),), sale=self.sale_b)
        self.sale.status = FlashSaleStatus.CLOSED
        self.sale.save(update_fields=["status"])
        by_sale = {s["pk"]: int(s["revenue"]) for s in get_sales_by_flash(self.seller.pk)}
        self.assertEqual(by_sale[self.sale.pk], self.card(self.sale))
        self.assertEqual(by_sale[self.sale_b.pk], self.card(self.sale_b))
        self.assertEqual(sum(by_sale.values()), self.card())

    def test_flash_sale_stats_matches_card_filtered_by_sale(self):
        self.seed_mixed()
        self.make(OS.DELIVERED, collected=True, items=((300, 1),), sale=self.sale_b)
        stats = get_flash_sale_stats(self.sale.pk)
        self.assertEqual(int(stats["total_revenue"]), self.card(self.sale))
        self.assertEqual(int(stats["total_revenue"]), 2500)
        self.assertEqual(stats["total_orders"], 1)
        self.assertEqual(stats["total_quantity"], 3)
        self.assertEqual(int(get_flash_sale_stats(self.sale_b.pk)["total_revenue"]), 300)


class ExcludedCasesTests(ReportingEncaisseBase):
    def test_delivered_not_collected_is_not_revenue(self):
        self.make(OS.DELIVERED, collected=False, items=((1500, 1),))
        self.assertEqual(get_revenue_timeline(self.seller.pk), [])
        self.assertEqual(get_top_products(self.seller.pk), [])
        self.assertEqual(get_flash_sale_stats(self.sale.pk)["total_revenue"], 0)

    def test_delivered_without_delivery_is_never_revenue(self):
        self.make(OS.DELIVERED, collected=None, items=((700, 1),))
        self.assertEqual(get_revenue_timeline_monthly(self.seller.pk), [])
        self.assertEqual(get_flash_sale_stats(self.sale.pk)["total_orders"], 0)

    def test_cancelled_is_not_revenue(self):
        self.make(OS.CANCELLED, collected=True, items=((700, 1),))
        self.assertEqual(get_top_products(self.seller.pk), [])

    def test_no_double_counting_with_several_lines(self):
        self.make(OS.DELIVERED, collected=True, items=((100, 1), (200, 2), (300, 3)))
        stats = get_flash_sale_stats(self.sale.pk)
        self.assertEqual(int(stats["total_revenue"]), 1400)
        self.assertEqual(stats["total_orders"], 1)
        self.assertEqual(stats["total_quantity"], 6)
        timeline = get_revenue_timeline(self.seller.pk)
        self.assertEqual((int(timeline[0]["revenue"]), timeline[0]["orders"]), (1400, 1))

    def test_top_products_ranks_collected_quantities_only(self):
        self.make(OS.DELIVERED, collected=True, items=((100, 1),), name="Collé")
        self.make(OS.DELIVERED, collected=False, items=((100, 50),), name="NonCollé")
        rows = get_top_products(self.seller.pk)
        self.assertEqual([r["product_name_snapshot"] for r in rows], ["Collé"])


class SellerIsolationTests(ReportingEncaisseBase):
    def test_other_seller_orders_never_counted(self):
        foreign = FlashSale.objects.create(
            title="Etrangère",
            start_time=timezone.now() - timedelta(hours=1),
            end_time=timezone.now() + timedelta(hours=1),
            status=FlashSaleStatus.LIVE,
            owner=self.other_user.seller_profile,
        )
        self.make(OS.DELIVERED, collected=True, items=((5000, 1),), sale=foreign)
        self.make(OS.DELIVERED, collected=True, items=((100, 1),))
        self.assertEqual(
            int(sum(r["revenue"] for r in get_revenue_timeline(self.seller.pk))), 100
        )
        self.assertEqual(int(get_top_products(self.seller.pk)[0]["total_revenue"]), 100)
