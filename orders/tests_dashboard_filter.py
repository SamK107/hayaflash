"""PR 4 / F-86 : la page Commandes (/orders/seller/dashboard/) se filtre par vente.

Le filtre doit suivre les cartes, la liste et les requetes HTMX de
rafraichissement, ne jamais fuiter la vente d'un autre vendeur, et les caches
courts ne doivent pas melanger deux filtres.
"""

from __future__ import annotations

import re
from datetime import timedelta

from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from delivery.tests import DeliveryTestFixture
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order
from orders.tests import _valid_delivery

PAGE = "orders:seller_dashboard"
KPI = "orders:seller_dashboard_kpi"
LIST = "orders:seller_dashboard_orders"


class DashboardFilterBase(DeliveryTestFixture):
    def setUp(self):
        super().setUp()
        cache.clear()
        now = timezone.now()
        self.sale_b = FlashSale.objects.create(
            title="Deuxieme vente",
            start_time=now - timedelta(days=3),
            end_time=now - timedelta(days=2),
            status=FlashSaleStatus.CLOSED,
            owner=self.seller,
        )
        self.foreign_sale = FlashSale.objects.create(
            title="Vente etrangere",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            status=FlashSaleStatus.LIVE,
            owner=self.other_user.seller_profile,
        )
        self.order_a = self._order(self.sale, "Cliente-Alpha")
        self.order_b1 = self._order(self.sale_b, "Cliente-Bravo")
        self.order_b2 = self._order(self.sale_b, "Cliente-Charlie")
        self._order(self.foreign_sale, "Cliente-Intrus")
        self.client = Client()
        self.client.force_login(self.seller_user)

    def _order(self, sale, name):
        return Order.service_objects.create(
            flash_sale=sale, customer_name=name, customer_phone="+22370000009"
        )

    def total_orders(self, sale=None):
        """Valeur de la carte « Commandes », lue dans le HTML rendu."""
        html = self.get(KPI, sale).content.decode()
        match = re.search(r"text-2xl font-bold text-gray-900\">(\d+)</p>", html)
        self.assertIsNotNone(match, html)
        return int(match.group(1))

    def get(self, name, sale=None, **extra):
        params = {} if sale is None else {"flash_sale_id": sale}
        return self.client.get(reverse(name), params, **extra)


class FilteredListTests(DashboardFilterBase):
    def test_default_lists_all_own_sales_and_no_foreign_order(self):
        html = self.get(LIST).content.decode()
        self.assertIn("Cliente-Alpha", html)
        self.assertIn("Cliente-Bravo", html)
        self.assertNotIn("Cliente-Intrus", html)

    def test_filter_restricts_list(self):
        html = self.get(LIST, self.sale_b.pk).content.decode()
        self.assertIn("Cliente-Bravo", html)
        self.assertIn("Cliente-Charlie", html)
        self.assertNotIn("Cliente-Alpha", html)

    def test_filter_restricts_kpi_cards(self):
        self.assertEqual(self.total_orders(), 3)
        self.assertEqual(self.total_orders(self.sale_b.pk), 2)

    def test_total_line_under_list(self):
        html = self.get(LIST, self.sale_b.pk).content.decode()
        self.assertIn("2 sur 2 commandes", html)

    def test_total_line_counts_beyond_page_size(self):
        for i in range(21):
            self._order(self.sale, f"Extra-{i}")
        html = self.get(LIST, self.sale.pk).content.decode()
        self.assertIn("20 sur 22 commandes", html)

    def test_kpi_cards_keep_existing_labels(self):
        html = self.get(KPI).content.decode()
        for label in ("Commandes", "Articles livrés", "Encaissé (FCFA)", "En cours d'encaissement (FCFA)"):
            self.assertIn(label, html)


class CacheIsolationTests(DashboardFilterBase):
    def test_two_filters_do_not_share_list_content(self):
        first = self.get(LIST, self.sale.pk).content.decode()
        second = self.get(LIST, self.sale_b.pk).content.decode()  # < 3 s apres
        self.assertIn("Cliente-Alpha", first)
        self.assertNotIn("Cliente-Alpha", second)
        self.assertIn("Cliente-Bravo", second)
        third = self.get(LIST).content.decode()  # « toutes », pas le cache d'un filtre
        self.assertIn("Cliente-Alpha", third)
        self.assertIn("Cliente-Bravo", third)

    def test_two_filters_do_not_share_kpis(self):
        self.assertEqual(self.total_orders(self.sale.pk), 1)
        self.assertEqual(self.total_orders(self.sale_b.pk), 2)
        self.assertEqual(self.total_orders(), 3)

    def test_new_order_invalidates_every_kpi_variant(self):
        # Au niveau service : la vue ajoute en plus un lissage de 3 s par partial.
        from orders.services.dashboard import get_dashboard_kpis_cached

        user = self.seller_user
        self.assertEqual(get_dashboard_kpis_cached(user)["total_orders"], 3)
        self.assertEqual(get_dashboard_kpis_cached(user, self.sale.pk)["total_orders"], 1)
        self._order_via_service()
        self.assertEqual(get_dashboard_kpis_cached(user)["total_orders"], 4)
        self.assertEqual(get_dashboard_kpis_cached(user, self.sale.pk)["total_orders"], 2)
        self.assertEqual(get_dashboard_kpis_cached(user, self.sale_b.pk)["total_orders"], 2)

    def _order_via_service(self):
        from orders.services.create_order import create_order

        create_order(
            {
                "flash_sale_id": self.sale.pk,
                "customer_name": "Cliente-Delta",
                "customer_phone": "+19998887777",
                "client_request_id": "req-filter-cache-1",
                "items": [{"product_id": self.product.pk, "quantity": 1}],
                "delivery": _valid_delivery(),
            }
        )


class SellerIsolationTests(DashboardFilterBase):
    """IDOR : la vente d'un autre vendeur ne fuit ni en page, ni en partials."""

    def test_foreign_sale_is_404_everywhere(self):
        for name in (PAGE, KPI, LIST):
            resp = self.get(name, self.foreign_sale.pk)
            self.assertEqual(resp.status_code, 404, name)
            self.assertNotIn(b"Cliente-Intrus", resp.content)
            self.assertNotIn(b"Vente etrangere", resp.content)

    def test_unknown_or_malformed_sale_is_404(self):
        for value in ("999999", "abc", "-1"):
            for name in (PAGE, KPI, LIST):
                resp = self.client.get(reverse(name), {"flash_sale_id": value})
                self.assertEqual(resp.status_code, 404, (name, value))

    def test_selector_never_lists_foreign_sales(self):
        html = self.get(PAGE).content.decode()
        self.assertNotIn("Vente etrangere", html)
        self.assertIn("Deuxieme vente", html)


class PageTests(DashboardFilterBase):
    def test_page_offers_all_sales_default_and_selector(self):
        html = self.get(PAGE).content.decode()
        self.assertIn("Toutes les ventes", html)
        self.assertIn('data-hf-nav-prefix="?flash_sale_id="', html)
        self.assertIn(f'value="{self.sale_b.pk}"', html)

    def test_selected_sale_is_marked_and_htmx_requests_keep_filter(self):
        html = self.get(PAGE, self.sale_b.pk).content.decode()
        self.assertRegex(html, rf'value="{self.sale_b.pk}"\s+selected')
        self.assertIn(f"{reverse(KPI)}?flash_sale_id={self.sale_b.pk}", html)
        self.assertIn(f"{reverse(LIST)}?flash_sale_id={self.sale_b.pk}", html)

    def test_default_htmx_requests_have_no_filter(self):
        html = self.get(PAGE).content.decode()
        self.assertIn(f'hx-get="{reverse(LIST)}"', html)
        self.assertIn(f'hx-get="{reverse(KPI)}"', html)

    def test_page_works_without_live_sale(self):
        FlashSale.objects.filter(pk=self.sale.pk).update(
            status=FlashSaleStatus.CLOSED,
            end_time=timezone.now() - timedelta(minutes=5),
        )
        html = self.get(PAGE).content.decode()
        self.assertNotIn("Aucune vente active", html)
        self.assertIn("Cliente-Alpha", html)

    def test_close_buttons_only_for_a_live_selected_sale(self):
        live = self.get(PAGE, self.sale.pk).content.decode()
        self.assertIn(reverse("flash_sales:close", kwargs={"pk": self.sale.pk}), live)
        closed = self.get(PAGE, self.sale_b.pk).content.decode()
        self.assertNotIn(reverse("flash_sales:close", kwargs={"pk": self.sale_b.pk}), closed)

    def test_empty_state_has_icon_badge_and_short_french_text(self):
        Order.service_objects.filter(flash_sale=self.sale).delete()
        html = self.get(LIST, self.sale.pk).content.decode()
        self.assertIn("hf-icon-badge", html)
        self.assertIn("Aucune commande pour cette vente.", html)


class TableauLiveLinkTests(DashboardFilterBase):
    def test_live_button_opens_filtered_page(self):
        html = self.client.get(
            reverse("flash_sales:detail", kwargs={"pk": self.sale.pk})
        ).content.decode()
        self.assertIn(f"{reverse(PAGE)}?flash_sale_id={self.sale.pk}", html)
        self.assertIn("Tableau LIVE", html)
