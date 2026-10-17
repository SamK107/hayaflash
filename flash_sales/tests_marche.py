"""Le Marche HayaFlash (/ventes/) : recently_ended_q, snapshot, vue."""

from __future__ import annotations

from datetime import timedelta

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from analytics.services.market import MARKET_CACHE_KEY, get_market_snapshot
from analytics.tests import ViralGrowthFixture
from flash_sales.models import FlashSale, FlashSaleStatus
from flash_sales.services.ordering import live_now_q, recently_ended_q
from orders.services.create_order import create_order
from products.models import FlashSaleProduct


def _sale(owner, title, start, end, status=FlashSaleStatus.LIVE, **kw):
    return FlashSale.objects.create(
        title=title, start_time=start, end_time=end, status=status, owner=owner, **kw
    )


class RecentlyEndedQTests(ViralGrowthFixture):
    def test_window_status_and_exclusive_with_live(self) -> None:
        now = timezone.now()
        h = timedelta(hours=1)
        ended = _sale(self.seller, "Finie 25 min", now - h, now - timedelta(minutes=25),
                      FlashSaleStatus.COMPLETED)
        stale_live = _sale(self.seller, "Fin passee restee LIVE", now - h, now - timedelta(minutes=5))
        old = _sale(self.seller, "Trop ancienne", now - 5 * h, now - 3 * h, FlashSaleStatus.COMPLETED)
        cancelled = _sale(self.seller, "Annulee", now - h, now - timedelta(minutes=10),
                          FlashSaleStatus.CANCELLED)
        upcoming = _sale(self.seller, "A venir", now + h, now + 2 * h, FlashSaleStatus.SCHEDULED)

        got = set(FlashSale.objects.filter(recently_ended_q(now)))
        self.assertEqual(got, {ended, stale_live})
        self.assertNotIn(self.sale, got)  # en direct
        for s in (old, cancelled, upcoming):
            self.assertNotIn(s, got)
        # Jamais a la fois en direct et terminee.
        both = FlashSale.objects.filter(live_now_q(now)).filter(recently_ended_q(now))
        self.assertFalse(both.exists())

    def test_custom_window_and_boundary(self) -> None:
        now = timezone.now()
        s = _sale(self.seller, "Il y a 30 min", now - timedelta(hours=1), now - timedelta(minutes=30),
                  FlashSaleStatus.COMPLETED)
        self.assertTrue(FlashSale.objects.filter(recently_ended_q(now, timedelta(hours=1)), pk=s.pk).exists())
        self.assertFalse(FlashSale.objects.filter(recently_ended_q(now, timedelta(minutes=10)), pk=s.pk).exists())
        # end_time == now : encore "en direct" (live_now_q est inclusif), pas termine.
        edge = _sale(self.seller, "Pile maintenant", now - timedelta(hours=1), now)
        self.assertFalse(FlashSale.objects.filter(recently_ended_q(now), pk=edge.pk).exists())
        self.assertTrue(FlashSale.objects.filter(live_now_q(now), pk=edge.pk).exists())


class MarketSnapshotTests(ViralGrowthFixture):
    def test_percent_none_when_stock_unknown_or_zero(self) -> None:
        # Vente sans produit lie -> stock inconnu.
        bare = _sale(self.seller, "Sans produit", timezone.now() - timedelta(minutes=5),
                     timezone.now() + timedelta(hours=1))
        self.product.stock_available = 0
        self.product.save()
        snap = get_market_snapshot()
        self.assertIsNone(snap["sales"][bare.pk]["percent_sold"])
        self.assertIsNone(snap["sales"][self.sale.pk]["percent_sold"])

    def test_percent_and_thresholds(self) -> None:
        # stock 5, 1 article vendu -> 1 / (1 + 4) = 20 %.
        create_order(self._payload())
        cache.clear()
        stats = get_market_snapshot()["sales"][self.sale.pk]
        self.assertEqual(stats["items_sold"], 1)
        self.assertEqual(stats["percent_sold"], 20)
        self.assertEqual(stats["orders_visible"], 1)

    def test_percent_under_5_hidden_and_no_orders_hidden(self) -> None:
        self.product.stock_available = 100
        self.product.save()
        cache.clear()
        stats = get_market_snapshot()["sales"][self.sale.pk]
        self.assertIsNone(stats["percent_sold"])
        self.assertIsNone(stats["orders_visible"])
        create_order(self._payload())  # 1 / 100 = 1 % < 5 %
        cache.clear()
        stats = get_market_snapshot()["sales"][self.sale.pk]
        self.assertIsNone(stats["percent_sold"])
        self.assertEqual(stats["orders_visible"], 1)

    def test_inactive_link_not_counted_in_stock(self) -> None:
        create_order(self._payload())
        FlashSaleProduct.objects.filter(flash_sale=self.sale).update(is_active=False)
        cache.clear()
        self.assertIsNone(get_market_snapshot()["sales"][self.sale.pk]["percent_sold"])

    def test_ended_list_limits_and_no_buyer_data(self) -> None:
        create_order(self._payload(customer_name="Secret Acheteur", customer_phone="+15559998888"))
        now = timezone.now()
        for i in range(8):
            _sale(self.seller, f"Terminee {i}", now - timedelta(hours=1, minutes=i),
                  now - timedelta(minutes=10 + i), FlashSaleStatus.COMPLETED)
        FlashSale.objects.filter(pk=self.sale.pk).update(
            start_time=now - timedelta(hours=1), end_time=now - timedelta(minutes=1),
            status=FlashSaleStatus.COMPLETED,
        )
        cache.clear()
        snap = get_market_snapshot()
        self.assertEqual(len(snap["recently_ended"]), 6)
        ends = [e["end_time"] for e in snap["recently_ended"]]
        self.assertEqual(ends, sorted(ends, reverse=True))
        self.assertEqual(snap["recently_ended"][0]["id"], self.sale.pk)
        self.assertNotIn("orders_visible", snap["recently_ended"][0])
        self.assertNotIn("orders", snap["recently_ended"][0])
        dump = repr(snap)
        for forbidden in ("Secret Acheteur", "+15559998888", "Hamdallaye"):
            self.assertNotIn(forbidden, dump)

    def test_cached_under_single_key(self) -> None:
        get_market_snapshot()
        self.assertIsNotNone(cache.get(MARKET_CACHE_KEY))
        with CaptureQueriesContext(connection) as ctx:
            get_market_snapshot()
        self.assertEqual(len(ctx), 0)


class MarketViewTests(ViralGrowthFixture):
    url = reverse("flash_sale_calendar")

    def test_full_page_and_htmx_partial(self) -> None:
        full = self.client.get(self.url)
        self.assertEqual(full.status_code, 200)
        self.assertContains(full, "Le Marché HayaFlash")
        self.assertContains(full, "every 30s")
        self.assertContains(full, "visibilitychange")
        part = self.client.get(self.url, HTTP_HX_REQUEST="true")
        self.assertEqual(part.status_code, 200)
        self.assertNotContains(part, "<html")
        self.assertContains(part, "hfc-card")
        self.assertNotContains(part, "Secret")

    def test_live_card_shows_percent_and_orders_badge(self) -> None:
        create_order(self._payload(customer_name="Secret Acheteur"))
        cache.clear()
        resp = self.client.get(self.url)
        self.assertContains(resp, "20 % vendu")
        self.assertContains(resp, "1 commande")
        self.assertNotContains(resp, "Secret Acheteur")
        self.assertNotContains(resp, "15559991234")

    def test_calm_state_hero_for_next_sale(self) -> None:
        FlashSale.objects.filter(pk=self.sale.pk).update(status=FlashSaleStatus.CANCELLED)
        now = timezone.now()
        _sale(self.seller, "Demain matin", now + timedelta(minutes=40), now + timedelta(hours=2),
              FlashSaleStatus.SCHEDULED)
        resp = self.client.get(self.url)
        self.assertTrue(resp.context["hero"])
        self.assertContains(resp, "Prochaine vente")
        self.assertContains(resp, "M'alerter")
        self.assertContains(resp, "démarre à")  # bandeau : vente imminente

    def test_empty_state_without_any_sale(self) -> None:
        FlashSale.objects.all().delete()
        for kwargs in ({}, {"HTTP_HX_REQUEST": "true"}):
            resp = self.client.get(self.url, **kwargs)
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "Les prochaines ventes arrivent bientôt.")
            self.assertContains(resp, "Tu vends en live ?")
            self.assertNotContains(resp, 'class="hfc-ticker"')

    def test_ended_section_and_category_chips(self) -> None:
        now = timezone.now()
        _sale(self.seller, "Fini hier soir", now - timedelta(hours=1), now - timedelta(minutes=25),
              FlashSaleStatus.COMPLETED, category="beaute")
        _sale(self.seller, "Fini annulee", now - timedelta(hours=1), now - timedelta(minutes=20),
              FlashSaleStatus.CANCELLED)
        resp = self.client.get(self.url)
        self.assertContains(resp, "Vient de se terminer")
        self.assertContains(resp, "Terminée · il y a 25 min")
        self.assertContains(resp, "Voir sa prochaine vente")
        self.assertNotContains(resp, "Fini annulee")
        self.assertContains(resp, "hfc-chip")

    def test_ended_card_has_no_order_counter(self) -> None:
        create_order(self._payload())
        create_order(self._payload(client_request_id="autre-requete"))
        FlashSale.objects.filter(pk=self.sale.pk).update(
            start_time=timezone.now() - timedelta(hours=1),
            end_time=timezone.now() - timedelta(minutes=20),
            status=FlashSaleStatus.COMPLETED,
        )
        self.product.refresh_from_db()
        cache.clear()
        resp = self.client.get(self.url)
        html = resp.content.decode()
        section = html[html.index("Vient de se terminer"):]
        self.assertNotIn("commande", section.split("hfc-empty")[0].split("</section>")[0])
        self.assertContains(resp, "Terminée · il y a 20 min")
        self.assertIn("M'alerter", section.split("</section>")[0])

    def test_ended_card_shows_sold_out_when_stock_zero(self) -> None:
        self.product.stock_available = 0
        self.product.save()
        FlashSale.objects.filter(pk=self.sale.pk).update(
            start_time=timezone.now() - timedelta(hours=1),
            end_time=timezone.now() - timedelta(minutes=20),
            status=FlashSaleStatus.COMPLETED,
        )
        cache.clear()
        self.assertContains(self.client.get(self.url), "Épuisé · il y a 20 min")

    def test_query_count_independent_of_sales(self) -> None:
        def count() -> int:
            cache.clear()
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(self.client.get(self.url).status_code, 200)
            return len(ctx)

        base = count()
        now = timezone.now()
        for i in range(6):
            s = _sale(self.seller, f"Live {i}", now - timedelta(minutes=5), now + timedelta(hours=1))
            FlashSaleProduct.objects.create(flash_sale=s, product=self.product)
            _sale(self.seller, f"Plus tard {i}", now + timedelta(hours=2 + i), now + timedelta(hours=3 + i),
                  FlashSaleStatus.SCHEDULED)
            _sale(self.seller, f"Finie {i}", now - timedelta(hours=1), now - timedelta(minutes=5 + i),
                  FlashSaleStatus.COMPLETED)
        self.assertEqual(count(), base)
