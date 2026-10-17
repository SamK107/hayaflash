"""Acces visible au Marche (/ventes/) : liens sur /f/, /s/ et l'accueil."""

from __future__ import annotations

from datetime import timedelta

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from analytics.tests import ViralGrowthFixture
from flash_sales.models import FlashSaleStatus

MARKET_HREF = 'href="/ventes/"'


class MarketAccessLinksTests(ViralGrowthFixture):
    def _public(self):
        return self.client.get(reverse("public_flash_sale", kwargs={"slug": self.sale.public_slug}))

    def test_live_sale_page_links_to_market_below_products(self) -> None:
        resp = self._public()
        self.assertEqual(resp.context["page_state"], "live")
        html = resp.content.decode()
        link = "Voir toutes les ventes en direct →"
        self.assertIn(link, html)
        # Sous la liste des produits, avant le bloc de partage.
        self.assertLess(html.index(self.product.name), html.index(link))
        self.assertLess(html.index(link), html.index("Partager cette vente"))
        self.assertIn(MARKET_HREF, html[html.index(link) - 200 : html.index(link)])

    def test_ended_sale_page_links_to_market_prominently(self) -> None:
        now = timezone.now()
        self.sale.start_time = now - timedelta(hours=3)
        self.sale.end_time = now - timedelta(hours=1)
        self.sale.status = FlashSaleStatus.COMPLETED
        self.sale.save()
        cache.clear()
        resp = self._public()
        self.assertEqual(resp.context["page_state"], "ended")
        self.assertContains(resp, "Voir toutes les ventes en direct →")
        self.assertContains(resp, MARKET_HREF)
        self.assertContains(resp, "background:#EEF2FF")  # bouton mis en avant

    def test_seller_page_link_renamed(self) -> None:
        resp = self.client.get(reverse("public_seller", kwargs={"slug": self.seller.public_slug}))
        self.assertContains(resp, "Le Marché — toutes les ventes en direct")
        self.assertNotContains(resp, ">Toutes les ventes<")
        self.assertContains(resp, MARKET_HREF)

    def test_home_menu_has_market_entry_for_visitors_and_sellers(self) -> None:
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, 'class="nav-market"')
        self.assertContains(resp, ">Le Marché</a>")
        self.client.force_login(self.seller_user)
        self.assertContains(self.client.get(reverse("home")), 'class="nav-market"')
