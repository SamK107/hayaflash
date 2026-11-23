"""Boutique suspendue : page /f/<slug>/ neutre, nouvelles commandes refusees, commandes existantes intactes."""

from __future__ import annotations

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.urls import reverse

from accounts.services.suspension import suspend_shop
from analytics.tests import ViralGrowthFixture
from flash_sales.services.ordering import MSG_SHOP_UNAVAILABLE
from orders.models import Order
from orders.services.create_order import create_order


class SuspendedShopPublicPageTests(ViralGrowthFixture):
    def _page(self):
        cache.clear()
        return self.client.get(reverse("public_flash_sale", kwargs={"slug": self.sale.public_slug}))

    def test_active_shop_page_shows_sale(self) -> None:
        resp = self._page()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Mega Drop Afrique")

    def test_suspended_shop_page_is_neutral(self) -> None:
        suspend_shop(self.seller, actor=None, reason="Test page neutre")
        resp = self._page()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Boutique indisponible pour le moment.")
        self.assertNotContains(resp, "Mega Drop Afrique")
        self.assertNotContains(resp, "Awa Boutique")

    def test_new_order_refused_and_existing_order_untouched(self) -> None:
        existing = create_order(self._payload(customer_name="Avant suspension"))
        suspend_shop(self.seller, actor=None, reason="Test commandes")

        with self.assertRaises(ValidationError) as ctx:
            create_order(self._payload(customer_name="Apres suspension"))
        self.assertIn(MSG_SHOP_UNAVAILABLE, str(ctx.exception))
        self.assertEqual(Order.objects.filter(flash_sale=self.sale).count(), 1)

        existing.refresh_from_db()
        self.assertEqual(existing.customer_name, "Avant suspension")
        self.assertNotEqual(existing.status, "cancelled")

    def test_home_no_longer_says_every_payment_is_tracked(self) -> None:
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Chaque paiement à la livraison est tracé")
