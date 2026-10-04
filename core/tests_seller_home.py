"""PR 4 / F-75 : accueil vendeur sobre (sans emoji) et compteurs exacts."""

from __future__ import annotations

from datetime import timedelta

from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from delivery.tests import DeliveryTestFixture
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order, OrderStatus


class SellerHomeBase(DeliveryTestFixture):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.seller_user.display_name = "Awa Traoré"
        self.seller_user.save(update_fields=["display_name"])
        self.client = Client()
        self.client.force_login(self.seller_user)

    def _order(self, sale=None, status=OrderStatus.PENDING, name="Client"):
        order = Order.service_objects.create(
            flash_sale=sale or self.sale,
            customer_name=name,
            customer_phone="+22370000009",
        )
        if status != OrderStatus.PENDING:
            Order.service_objects.filter(pk=order.pk).update(status=status)
        return order

    def _sales(self, count, *, upcoming):
        now = timezone.now()
        for i in range(count):
            if upcoming:
                start, end, st = (
                    now + timedelta(days=1 + i),
                    now + timedelta(days=1 + i, hours=2),
                    FlashSaleStatus.SCHEDULED,
                )
            else:
                start, end, st = (
                    now - timedelta(days=10 + i),
                    now - timedelta(days=10 + i) + timedelta(hours=2),
                    FlashSaleStatus.CLOSED,
                )
            FlashSale.objects.create(
                title=f"{'A venir' if upcoming else 'Passee'} {i}",
                start_time=start,
                end_time=end,
                status=st,
                owner=self.seller,
            )

    def home(self):
        return self.client.get(reverse("seller_home"))


class HeaderTests(SellerHomeBase):
    def test_no_waving_hand_and_new_button_label(self):
        html = self.home().content.decode()
        self.assertNotIn("\U0001F44B", html)
        self.assertIn("Créer une vente flash", html)
        self.assertIn(reverse("flash_sales:create"), html)

    def test_initials_badge_and_first_name(self):
        html = self.home().content.decode()
        self.assertIn("Bonjour, Awa", html)
        self.assertIn(">AT<", html)

    def test_status_line_singular_and_plural(self):
        self._order(name="A")
        self._order(name="B")
        self._order(status=OrderStatus.CONFIRMED, name="C")  # pas « à traiter »
        html = self.home().content.decode()
        self.assertIn("1 vente en cours", html)
        self.assertIn("2 commandes à traiter", html)

        self._sales(1, upcoming=False)
        FlashSale.objects.filter(pk=self.sale.pk).update(
            start_time=timezone.now() - timedelta(hours=3),
            end_time=timezone.now() - timedelta(hours=1),
            status=FlashSaleStatus.CLOSED,
        )
        Order.service_objects.filter(status=OrderStatus.PENDING).exclude(
            customer_name="A"
        ).update(status=OrderStatus.CANCELLED)
        html = self.home().content.decode()
        self.assertNotIn("en cours ·", html)
        self.assertIn("1 commande à traiter", html)

    def test_status_line_when_nothing_to_do(self):
        FlashSale.objects.filter(pk=self.sale.pk).update(
            end_time=timezone.now() - timedelta(minutes=5),
            status=FlashSaleStatus.CLOSED,
        )
        html = self.home().content.decode()
        self.assertIn("Rien à traiter pour le moment", html)

    def test_to_process_counts_only_own_orders(self):
        foreign = FlashSale.objects.create(
            title="Etrangere",
            start_time=timezone.now() - timedelta(hours=1),
            end_time=timezone.now() + timedelta(hours=1),
            status=FlashSaleStatus.LIVE,
            owner=self.other_user.seller_profile,
        )
        self._order(foreign, name="Intrus")
        self.assertEqual(self.home().context["to_process_count"], 0)


class CountersNotTruncatedTests(SellerHomeBase):
    """F-75 : les cartes ne comptent plus les listes tranchées ([:5], [:3])."""

    def test_active_total_exceeds_list_cap(self):
        self._sales(6, upcoming=True)  # + la vente en cours de la fixture = 7
        resp = self.home()
        self.assertEqual(resp.context["active_total"], 7)
        self.assertEqual(len(resp.context["active_sales"]), 5)
        self.assertIn('text-3xl font-bold text-primary mt-1">7</p>', resp.content.decode())

    def test_recent_total_exceeds_list_cap(self):
        self._sales(5, upcoming=False)
        resp = self.home()
        self.assertEqual(resp.context["recent_total"], 5)
        self.assertEqual(len(resp.context["recent_sales"]), 3)


class EmptyStateTests(SellerHomeBase):
    def test_empty_state_uses_icon_badge_with_short_text(self):
        FlashSale.objects.filter(owner=self.seller).delete()
        html = self.home().content.decode()
        self.assertIn("hf-icon-badge", html)
        self.assertIn("Lancez votre première vente flash", html)
