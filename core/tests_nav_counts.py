"""PR 4 / F-84 : pastilles de navigation vendeur (commandes à traiter, livraisons
en cours, réservations).

Définitions (écrites aussi dans core/context_processors.py) :
- commandes à traiter = commandes du vendeur au statut ``pending`` ;
- livraisons en cours = livraisons du vendeur aux statuts ``assigned`` ou
  ``in_transit`` ;
- réservations = ``SaleInterest`` du vendeur (inchangé).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone

from core.context_processors import (
    NAV_BADGE_CAP,
    NAV_COUNTS_CACHE_KEY,
    format_nav_badge,
    seller_interests_count,
)
from delivery.models import Delivery
from delivery.tests import DeliveryTestFixture
from flash_sales.models import FlashSale, FlashSaleStatus, SaleInterest
from orders.models import Order, OrderStatus


def _request(user, **headers):
    request = RequestFactory().get("/seller/", **headers)
    request.user = user
    return request


class NavCountsBase(DeliveryTestFixture):
    def setUp(self):
        super().setUp()
        cache.clear()

    def _order(self, sale=None, status=OrderStatus.PENDING):
        order = Order.service_objects.create(
            flash_sale=sale or self.sale,
            customer_name="Client",
            customer_phone="+22370000009",
        )
        if status != OrderStatus.PENDING:
            Order.service_objects.filter(pk=order.pk).update(status=status)
        return order

    def _delivery(self, status, sale=None):
        order = self._order(sale, status=OrderStatus.CONFIRMED)
        return Delivery.objects.create(
            order=order, status=status, cod_amount=Decimal("1000")
        )

    def counts(self, user=None):
        return seller_interests_count(_request(user or self.seller_user))


class DefinitionTests(NavCountsBase):
    def test_orders_to_process_counts_only_pending(self):
        for status in OrderStatus.values:
            self._order(status=status)
        self.assertEqual(self.counts()["orders_to_process_count"], 1)

    def test_deliveries_in_progress_counts_assigned_and_in_transit_only(self):
        for status in Delivery.Status.values:
            self._delivery(status)
        self.assertEqual(self.counts()["deliveries_active_count"], 2)

    def test_interests_count_unchanged(self):
        SaleInterest.objects.create(
            flash_sale=self.sale, phone="+22370000011", name="Awa"
        )
        self.assertEqual(self.counts()["interests_count"], 1)

    def test_counts_are_isolated_between_sellers(self):
        foreign = FlashSale.objects.create(
            title="Etrangere",
            start_time=timezone.now() - timedelta(hours=1),
            end_time=timezone.now() + timedelta(hours=1),
            status=FlashSaleStatus.LIVE,
            owner=self.other_user.seller_profile,
        )
        self._order(foreign)
        self._delivery(Delivery.Status.IN_TRANSIT, foreign)
        mine = self.counts()
        self.assertEqual(mine["orders_to_process_count"], 0)
        self.assertEqual(mine["deliveries_active_count"], 0)
        theirs = self.counts(self.other_user)
        self.assertEqual(theirs["orders_to_process_count"], 1)  # la livraison porte une commande confirmee
        self.assertEqual(theirs["deliveries_active_count"], 1)

    def test_zero_when_anonymous_or_without_seller_profile(self):
        from django.contrib.auth import get_user_model

        plain = get_user_model().objects.create_user(
            phone="+15550009999", password="x", display_name="Acheteur"
        )
        for user in (AnonymousUser(), plain):
            data = seller_interests_count(_request(user))
            self.assertEqual(data["interests_count"], 0)
            self.assertEqual(data["orders_to_process_count"], 0)
            self.assertEqual(data["deliveries_active_count"], 0)


class CostAndCacheTests(NavCountsBase):
    def test_query_count_is_bounded(self):
        request = _request(self.seller_user)
        with self.assertNumQueries(3):  # 3 COUNT (reservations, commandes, livraisons)
            seller_interests_count(request)

    def test_second_call_is_served_from_cache(self):
        self._order()
        first = self.counts()
        self._order()  # invisible pendant la fenetre de cache
        with self.assertNumQueries(1):  # seul le COUNT reservations (non cache)
            second = self.counts()
        self.assertEqual(first, second)

    def test_htmx_fragments_skip_the_counts(self):
        self._order()
        request = _request(self.seller_user, HTTP_HX_REQUEST="true")
        with self.assertNumQueries(0):
            data = seller_interests_count(request)
        self.assertEqual(data["orders_to_process_count"], 0)


class BadgeRenderingTests(NavCountsBase):
    def test_badge_format_caps_at_99_plus(self):
        self.assertEqual(NAV_BADGE_CAP, 99)
        self.assertEqual(format_nav_badge(7), "7")
        self.assertEqual(format_nav_badge(99), "99")
        self.assertEqual(format_nav_badge(100), "99+")

    def _html(self):
        client = Client()
        client.force_login(self.seller_user)
        return client.get(reverse("seller_home")).content.decode()

    def test_badges_hidden_at_zero(self):
        html = self._html()
        self.assertNotIn("hf-nav-badge", html)

    def test_badges_rendered_in_desktop_and_mobile_menus(self):
        self._order()
        self._delivery(Delivery.Status.ASSIGNED)
        html = self._html()
        self.assertEqual(html.count('data-nav-badge="orders"'), 2)
        self.assertEqual(html.count('data-nav-badge="deliveries"'), 2)

    def test_cap_is_displayed(self):
        cache.set(
            NAV_COUNTS_CACHE_KEY.format(seller_id=self.seller.pk),
            {"orders_to_process_count": 250, "deliveries_active_count": 3},
            60,
        )
        html = self._html()
        self.assertIn("99+", html)
        self.assertNotIn(">250<", html)
