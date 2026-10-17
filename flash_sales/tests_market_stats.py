"""Le Marche, phase 2a : indices publics du jour (flash_sales/market_stats.py)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from delivery.models import Delivery
from flash_sales.market_stats import (
    MARKET_MIN_DELIVERIES,
    MARKET_MIN_ORDERS_DAY,
    MARKET_MIN_ORDERS_HOUR,
    compute_market_stats,
    get_market_stats,
)
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order, OrderStatus

User = get_user_model()

# Journee fixe : 14 h 30 a Bamako (UTC+0, sans heure d'ete).
NOW = datetime(2026, 10, 14, 14, 30, tzinfo=ZoneInfo("Africa/Bamako"))


class MarketStatsBase(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self._n = 0
        self.sales: dict[str, FlashSale] = {}

    def shop(self, name: str, category: str = "mode") -> FlashSale:
        self._n += 1
        user = User.objects.create_user(phone=f"+2237100000{self._n}", password="x", display_name=name)
        seller = SellerProfile.objects.create(user=user, business_name=name, category=category)
        sale = FlashSale.objects.create(
            title=f"Vente {name}", owner=seller, status=FlashSaleStatus.LIVE,
            start_time=NOW - timedelta(hours=3), end_time=NOW + timedelta(hours=3),
        )
        self.sales[name] = sale
        return sale

    def order(self, sale: FlashSale, at=None, status=OrderStatus.PENDING) -> Order:
        self._n += 1
        o = Order.service_objects.create(
            flash_sale=sale, customer_name="Secret Acheteur", customer_phone=f"+22372{self._n:06d}",
            status=status, client_request_id=f"mk-{self._n}",
        )
        Order.service_objects.filter(pk=o.pk).update(created_at=at or NOW - timedelta(minutes=10))
        return o

    def transit(self, sale: FlashSale, status=Delivery.Status.IN_TRANSIT) -> Delivery:
        o = self.order(sale)
        return Delivery.objects.create(order=o, address_text="x", cod_amount=0, status=status)


class ThresholdTests(MarketStatsBase):
    def test_orders_last_hour_threshold(self) -> None:
        sale = self.shop("A")
        for _ in range(MARKET_MIN_ORDERS_HOUR - 1):
            self.order(sale)
        self.assertIsNone(compute_market_stats(NOW)["orders_last_hour"])
        self.order(sale)
        self.assertEqual(compute_market_stats(NOW)["orders_last_hour"], MARKET_MIN_ORDERS_HOUR)

    def test_orders_older_than_one_hour_not_counted_in_last_hour(self) -> None:
        sale = self.shop("A")
        for _ in range(5):
            self.order(sale, at=NOW - timedelta(minutes=90))
        self.assertIsNone(compute_market_stats(NOW)["orders_last_hour"])

    def test_deliveries_threshold_and_status(self) -> None:
        sale = self.shop("A")
        for _ in range(MARKET_MIN_DELIVERIES - 1):
            self.transit(sale)
        self.transit(sale, Delivery.Status.DELIVERED)  # ne compte pas
        self.transit(sale, Delivery.Status.PENDING)  # ne compte pas
        self.assertIsNone(compute_market_stats(NOW)["deliveries_in_transit"])
        self.transit(sale)
        self.assertEqual(compute_market_stats(NOW)["deliveries_in_transit"], MARKET_MIN_DELIVERIES)

    def test_cancelled_orders_and_deliveries_not_counted(self) -> None:
        sale = self.shop("A")
        for _ in range(6):
            self.order(sale, status=OrderStatus.CANCELLED)
        o = self.order(sale, status=OrderStatus.CANCELLED)
        for _ in range(MARKET_MIN_DELIVERIES):
            Delivery.objects.create(order=self.order(sale, status=OrderStatus.CANCELLED),
                                    address_text="x", cod_amount=0, status=Delivery.Status.IN_TRANSIT)
        stats = compute_market_stats(NOW)
        self.assertIsNone(stats["orders_last_hour"])
        self.assertIsNone(stats["deliveries_in_transit"])
        self.assertIsNone(stats["sparkline"])
        self.assertFalse(stats["visible"])
        self.assertTrue(o.pk)


class CategoryTests(MarketStatsBase):
    def test_single_shop_category_hidden_two_shops_shown(self) -> None:
        a = self.shop("A", "mode")
        b = self.shop("B", "mode")
        c = self.shop("C", "beaute")
        for s in (a, a, a, b, c, c, c, c):  # beaute : 4 commandes mais 1 seule boutique
            self.order(s)
        self.assertEqual(compute_market_stats(NOW)["top_categories"], ["Mode"])

    def test_top_three_ordered_by_orders(self) -> None:
        shops = {cat: (self.shop(f"{cat}1", cat), self.shop(f"{cat}2", cat))
                 for cat in ("mode", "beaute", "maison", "chaussures")}
        for cat, n in (("mode", 5), ("beaute", 4), ("maison", 3), ("chaussures", 2)):
            for i in range(n):
                self.order(shops[cat][i % 2])
        self.assertEqual(compute_market_stats(NOW)["top_categories"], ["Mode", "Beauté", "Maison"])

    def test_sale_category_overrides_shop_category(self) -> None:
        a, b = self.shop("A", "mode"), self.shop("B", "mode")
        FlashSale.objects.filter(pk__in=[a.pk, b.pk]).update(category="maison")
        self.order(a)
        self.order(b)
        self.assertEqual(compute_market_stats(NOW)["top_categories"], ["Maison"])


class SparklineTests(MarketStatsBase):
    def test_one_point_per_elapsed_hour_and_counts(self) -> None:
        sale = self.shop("A")
        for h in (0, 0, 9, 13, 14):
            self.order(sale, at=NOW.replace(hour=h, minute=5))
        spark = compute_market_stats(NOW)["sparkline"]
        self.assertEqual(len(spark["hours"]), 15)  # 0 h .. 14 h
        self.assertEqual(len(spark["points"].split()), 15)
        self.assertEqual((spark["hours"][0], spark["hours"][9], spark["hours"][14]), (2, 1, 1))
        self.assertEqual(sum(spark["hours"]), 5)

    def test_hidden_below_day_threshold(self) -> None:
        sale = self.shop("A")
        for _ in range(MARKET_MIN_ORDERS_DAY - 1):
            self.order(sale)
        self.assertIsNone(compute_market_stats(NOW)["sparkline"])

    def test_yesterday_not_in_today_series(self) -> None:
        sale = self.shop("A")
        for _ in range(8):
            self.order(sale, at=NOW - timedelta(days=1))
        self.assertIsNone(compute_market_stats(NOW)["sparkline"])


class CacheAndQueriesTests(MarketStatsBase):
    def test_second_call_hits_cache(self) -> None:
        self.order(self.shop("A"))
        get_market_stats(NOW)
        with CaptureQueriesContext(connection) as ctx:
            get_market_stats(NOW)
        self.assertEqual(len(ctx), 0)

    def test_cold_queries_bounded_and_independent_of_orders(self) -> None:
        def cold() -> int:
            cache.clear()
            with CaptureQueriesContext(connection) as ctx:
                get_market_stats(NOW)
            return len(ctx)

        sale = self.shop("A")
        base = cold()
        self.assertLessEqual(base, 4)
        other = self.shop("B")
        for _ in range(25):
            self.order(sale)
            self.order(other)
        self.transit(sale)
        self.assertEqual(cold(), base)


class MarketPageBlockTests(MarketStatsBase):
    url = reverse("flash_sale_calendar")

    def test_block_absent_when_everything_below_thresholds(self) -> None:
        resp = self.client.get(self.url)
        self.assertNotContains(resp, "Le marché aujourd'hui")
        self.assertContains(resp, "Les prochaines ventes arrivent bientôt.")

    def test_block_shown_without_shop_data(self) -> None:
        a, b = self.shop("Boutique Alpha", "mode"), self.shop("Boutique Beta", "mode")
        now = timezone.now()
        for s in (a, a, b, b):
            self.order(s, at=now - timedelta(minutes=5))
        # created_at dans la fenetre meme apres minuit : ces 4 commandes sont recentes.
        resp = self.client.get(self.url)
        self.assertContains(resp, "Le marché aujourd'hui")
        self.assertContains(resp, "Commandes cette dernière heure")
        html = resp.content.decode()
        block = html[html.index('class="hfc-stats"'):html.index("</section>", html.index('class="hfc-stats"'))]
        for forbidden in ("Boutique Alpha", "Boutique Beta", "Secret Acheteur", "Vente "):
            self.assertNotIn(forbidden, block)
        part = self.client.get(self.url, HTTP_HX_REQUEST="true")
        self.assertContains(part, "Commandes cette dernière heure")
