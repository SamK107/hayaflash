"""Le Marche (/ventes/) n'affiche que les boutiques actives (SellerProfile.is_active).

Une boutique suspendue ou desactivee n'apparait dans aucune surface du Marche :
listing, aperçu, produits du moment, entree de l'accueil, statistiques.
Les boutiques actives ne sont pas touchees (cas témoin).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest import mock
from uuid import uuid4

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile, User
from analytics.services.market import compute_market_snapshot
from flash_sales import market_stats
from flash_sales.market_entry import compute_market_entry
from flash_sales.market_stats import compute_market_stats
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.services.create_order import create_order
from products.models import FlashSaleProduct, Product


class MarketHidesInactiveShopsTests(TestCase):
    def _shop(self, phone: str, name: str, *, is_active: bool) -> SellerProfile:
        user = User.objects.create_user(phone=phone, password="x", display_name=name)
        return SellerProfile.objects.create(user=user, business_name=name, is_active=is_active)

    def _sale(self, owner, title, start, end, status) -> FlashSale:
        sale = FlashSale.objects.create(
            title=title, start_time=start, end_time=end, status=status, owner=owner,
        )
        product = Product.objects.create(
            owner=owner, name=f"Produit {title}", stock_available=10, stock_initial=10,
            price=Decimal("5000.00"),
        )
        FlashSaleProduct.objects.create(flash_sale=sale, product=product)
        return sale

    def setUp(self) -> None:
        cache.clear()
        now = timezone.now()
        h = timedelta(hours=1)
        self.active = self._shop("+22370000101", "Boutique Active", is_active=True)
        self.inactive = self._shop("+22370000102", "Boutique Suspendue", is_active=False)
        self.active_live = self._sale(
            self.active, "Vente active en direct", now - h, now + h, FlashSaleStatus.LIVE,
        )
        self.inactive_live = self._sale(
            self.inactive, "Vente suspendue en direct", now - h, now + h, FlashSaleStatus.LIVE,
        )
        self.inactive_soon = self._sale(
            self.inactive, "Vente suspendue a venir", now + 2 * h, now + 3 * h,
            FlashSaleStatus.SCHEDULED,
        )
        self.inactive_ended = self._sale(
            self.inactive, "Vente suspendue terminee", now - 3 * h, now - timedelta(minutes=20),
            FlashSaleStatus.COMPLETED,
        )
        self.active_ended = self._sale(
            self.active, "Vente active terminee", now - 3 * h, now - timedelta(minutes=20),
            FlashSaleStatus.COMPLETED,
        )

    def test_snapshot_excludes_inactive_shop_sales(self) -> None:
        snap = compute_market_snapshot()
        self.assertIn(self.active_live.pk, snap["sales"])
        self.assertNotIn(self.inactive_live.pk, snap["sales"])
        ended_ids = {item["id"] for item in snap["recently_ended"]}
        self.assertIn(self.active_ended.pk, ended_ids)
        self.assertNotIn(self.inactive_ended.pk, ended_ids)
        self.assertNotIn(self.inactive_live.pk, snap["showcase"])
        self.assertNotIn(self.inactive_soon.pk, snap["showcase"])
        self.assertNotIn("Boutique Suspendue", {m.get("shop_name") for m in snap["moment"]})

    def test_calendar_page_hides_inactive_shop(self) -> None:
        resp = self.client.get(reverse("flash_sale_calendar"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Vente active en direct")
        self.assertNotContains(resp, "Vente suspendue en direct")
        self.assertNotContains(resp, "Vente suspendue a venir")
        self.assertNotContains(resp, "Vente suspendue terminee")

    def test_home_entry_counts_only_active_shops(self) -> None:
        self.assertEqual(compute_market_entry()["live"], 1)

    def test_market_stats_ignore_orders_from_inactive_shop(self) -> None:
        # Seuils abaisses pour que les indicateurs s'affichent avec peu de commandes.
        def _order(sale, phone):
            product = sale.flash_sale_products.get().product
            create_order({
                "flash_sale_id": sale.pk,
                "customer_name": "Client",
                "customer_phone": phone,
                "client_request_id": str(uuid4()),
                "items": [{"product_id": product.pk, "quantity": 1}],
                "delivery": {"address_text": "Hamdallaye ACI, Bamako", "geo_method": "manual"},
            })

        _order(self.active_live, "+22370000201")
        # Les commandes de la boutique ont ete passees AVANT sa suspension : on la
        # reactive le temps de les creer (la prise de commande refuse une boutique suspendue).
        SellerProfile.objects.filter(pk=self.inactive.pk).update(is_active=True)
        _order(self.inactive_live, "+22370000202")
        _order(self.inactive_live, "+22370000203")
        SellerProfile.objects.filter(pk=self.inactive.pk).update(is_active=False)
        with mock.patch.object(market_stats, "MARKET_MIN_ORDERS_HOUR", 1), \
                mock.patch.object(market_stats, "MARKET_MIN_SHOPS", 1):
            stats = compute_market_stats()
        self.assertEqual(stats["orders_last_hour"], 1)
