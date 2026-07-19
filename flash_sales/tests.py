from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from flash_sales.services.ordering import assert_flash_sale_accepts_orders
from orders.services.create_order import create_order
from orders.tests import valid_delivery_payload
from products.models import Product
from subscriptions.models import Plan, Subscription


User = get_user_model()


class FlashSaleTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            phone="+15550001111",
            password="x",
            display_name="Buyer",
        )
        self.seller_user = User.objects.create_user(
            phone="+15550002222",
            password="x",
            display_name="Seller",
        )
        self.seller = SellerProfile.objects.create(user=self.seller_user)

    def _sale(self, **kwargs) -> FlashSale:
        now = timezone.now()
        defaults = {
            "title": "Spring drop",
            "start_time": now - timedelta(hours=1),
            "end_time": now + timedelta(hours=1),
            "status": FlashSaleStatus.LIVE,
            "owner": self.seller,
        }
        defaults.update(kwargs)
        return FlashSale.objects.create(**defaults)

    def test_is_live_is_time_window_only(self) -> None:
        now = timezone.now()
        sale = self._sale(
            status=FlashSaleStatus.SCHEDULED,
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
        )
        self.assertTrue(sale.is_live())

        sale.end_time = now - timedelta(minutes=1)
        sale.save()
        self.assertFalse(sale.is_live())

    def test_open_and_close_sale(self) -> None:
        sale = self._sale(status=FlashSaleStatus.SCHEDULED)
        sale.open_sale()
        sale.refresh_from_db()
        self.assertEqual(sale.status, FlashSaleStatus.LIVE)

        sale.close_sale()
        sale.refresh_from_db()
        self.assertEqual(sale.status, FlashSaleStatus.CLOSED)

        with self.assertRaises(ValueError):
            sale.open_sale()

    def test_assert_flash_sale_accepts_orders_blocks_outside_live_window(self) -> None:
        now = timezone.now()
        sale = self._sale(
            status=FlashSaleStatus.LIVE,
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
        )
        with self.assertRaises(ValidationError):
            assert_flash_sale_accepts_orders(sale)

        sale.start_time = now - timedelta(minutes=5)
        sale.end_time = now + timedelta(hours=1)
        sale.save()
        assert_flash_sale_accepts_orders(sale)

        product = Product.objects.create(
            flash_sale=sale,
            name="SKU-1",
            stock_available=5,
            stock_initial=5,
            price="10.00",
        )
        order = create_order(
            {
                "flash_sale_id": sale.pk,
                "customer_name": "Ada",
                "customer_phone": "+10000000000",
                "client_request_id": "test-fs-live-1",
                "items": [{"product_id": product.pk, "quantity": 1}],
                "delivery": valid_delivery_payload(),
            }
        )
        self.assertIsNotNone(order.pk)
        product.refresh_from_db()
        self.assertEqual(product.stock_available, 4)

    def test_assert_flash_sale_accepts_orders_rejects_missing_flash_sale(self) -> None:
        product = Product.objects.create(flash_sale=None, name="Orphan")
        with self.assertRaises(ValidationError):
            assert_flash_sale_accepts_orders(product.flash_sale)


class CeleryTasksTest(TestCase):
    """Tests des taches Celery auto_open / auto_close (CELERY_TASK_ALWAYS_EAGER=True)."""

    def setUp(self) -> None:
        self.seller_user = User.objects.create_user(
            phone="+22300000030", password="x", display_name="SellerC"
        )
        self.seller = SellerProfile.objects.create(user=self.seller_user)

    def test_auto_open_scheduled_sales(self) -> None:
        from flash_sales.tasks import auto_open_scheduled_sales

        now = timezone.now()
        sale = FlashSale.objects.create(
            owner=self.seller,
            title="Auto open",
            start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=1),
            status=FlashSaleStatus.SCHEDULED,
        )
        auto_open_scheduled_sales()
        sale.refresh_from_db()
        self.assertEqual(sale.status, FlashSaleStatus.LIVE)

    def test_auto_close_live_sales(self) -> None:
        from flash_sales.tasks import auto_close_live_sales

        now = timezone.now()
        sale = FlashSale.objects.create(
            owner=self.seller,
            title="Auto close",
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(minutes=5),
            status=FlashSaleStatus.LIVE,
        )
        auto_close_live_sales()
        sale.refresh_from_db()
        self.assertEqual(sale.status, FlashSaleStatus.CLOSED)

    def test_auto_open_does_not_open_future_sales(self) -> None:
        from flash_sales.tasks import auto_open_scheduled_sales

        now = timezone.now()
        sale = FlashSale.objects.create(
            owner=self.seller,
            title="Futur",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            status=FlashSaleStatus.SCHEDULED,
        )
        auto_open_scheduled_sales()
        sale.refresh_from_db()
        self.assertEqual(sale.status, FlashSaleStatus.SCHEDULED)


class AuditLogTest(TestCase):
    """Tests du modele AuditLog."""

    def setUp(self) -> None:
        self.seller_user = User.objects.create_user(
            phone="+22300000040", password="x", display_name="SellerA"
        )
        self.seller = SellerProfile.objects.create(user=self.seller_user)

    def test_audit_creates_entry(self) -> None:
        from core.models import audit

        entry = audit(
            "test.action",
            entity_type="FlashSale",
            entity_id=99,
            custom_field="value",
        )
        self.assertIsNotNone(entry.pk)
        self.assertEqual(entry.action, "test.action")
        self.assertEqual(entry.entity_type, "FlashSale")
        self.assertEqual(entry.entity_id, 99)
        self.assertEqual(entry.metadata.get("custom_field"), "value")
        self.assertIsNone(entry.actor)

    def test_audit_with_actor(self) -> None:
        from core.models import audit

        entry = audit(
            "flashsale.opened",
            entity_type="FlashSale",
            entity_id=1,
            actor=self.seller_user,
        )
        self.assertEqual(entry.actor, self.seller_user)

    def test_audit_log_admin_readonly(self) -> None:
        from core.admin import AuditLogAdmin
        from core.models import AuditLog
        from django.contrib.admin.sites import AdminSite

        admin = AuditLogAdmin(model=AuditLog, admin_site=AdminSite())
        self.assertFalse(admin.has_add_permission(None))
        self.assertFalse(admin.has_change_permission(None))


class SubscriptionEnforcementIntegrationTest(TestCase):
    """
    Verifie l'enforcement du quota au niveau HTTP reel (flash_sale_create_view),
    pas seulement au niveau service isole (deja couvert dans subscriptions/tests.py).
    Couvre aussi, via ce chemin HTTP, le fix fail-closed et l'exclusion des
    ventes CANCELLED du comptage.
    """

    def setUp(self) -> None:
        self.seller_user = User.objects.create_user(
            phone="+22300000050", password="x", display_name="SellerQuota"
        )
        self.seller = SellerProfile.objects.create(user=self.seller_user)
        Subscription.objects.get_or_create(
            seller=self.seller, defaults={"plan": Plan.FREE}
        )
        self.client.force_login(self.seller_user)
        self.create_url = reverse("flash_sales:create")

    def _existing_sale(self, *, status, days_from_now=5):
        now = timezone.now()
        return FlashSale.objects.create(
            owner=self.seller,
            title="Vente existante",
            start_time=now + timedelta(days=days_from_now),
            end_time=now + timedelta(days=days_from_now, hours=1),
            status=status,
        )

    def _valid_post_data(self, *, days_from_now=1):
        # Format espace (pas "T") : c'est le format que Django parse par
        # defaut cote serveur, independamment du widget datetime-local HTML5.
        start = timezone.now() + timedelta(days=days_from_now)
        return {
            "title": "Nouvelle vente",
            "description": "",
            "teasers": "",
            "start_time": start.strftime("%Y-%m-%d %H:%M"),
            "delivery_zone": "",
            "duration_preset": "60",
        }

    def test_free_seller_at_quota_is_redirected_without_creating_sale(self) -> None:
        for _ in range(3):
            self._existing_sale(status=FlashSaleStatus.SCHEDULED)

        count_before = FlashSale.objects.filter(owner=self.seller).count()
        resp = self.client.post(self.create_url, self._valid_post_data())

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("flash_sales:list"))
        self.assertEqual(
            FlashSale.objects.filter(owner=self.seller).count(), count_before
        )

    def test_cancelled_sale_frees_a_slot_for_new_creation(self) -> None:
        self._existing_sale(status=FlashSaleStatus.SCHEDULED)
        self._existing_sale(status=FlashSaleStatus.SCHEDULED)
        self._existing_sale(status=FlashSaleStatus.CANCELLED)  # ne compte pas

        resp = self.client.post(self.create_url, self._valid_post_data())

        new_sale = FlashSale.objects.filter(
            owner=self.seller, title="Nouvelle vente"
        ).first()
        self.assertIsNotNone(
            new_sale, "La vente aurait du etre creee (quota non atteint : 2/3)"
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            resp["Location"], reverse("flash_sales:detail", kwargs={"pk": new_sale.pk})
        )

    def test_quota_check_exception_blocks_creation_via_http(self) -> None:
        """Integration du fix fail-closed : une panne subscriptions bloque au niveau HTTP."""
        with patch(
            "subscriptions.services.limits.can_create_flash_sale",
            side_effect=RuntimeError("panne simulee"),
        ):
            resp = self.client.post(self.create_url, self._valid_post_data())

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("flash_sales:list"))
        self.assertEqual(
            FlashSale.objects.filter(owner=self.seller, title="Nouvelle vente").count(),
            0,
        )
