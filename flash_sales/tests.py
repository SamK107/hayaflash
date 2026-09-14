from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from flash_sales.services.ordering import assert_flash_sale_accepts_orders
from orders.services.create_order import create_order
from orders.tests import valid_delivery_payload
from products.models import Product


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


class SendPendingSaleRemindersTest(TestCase):
    """Tests de send_pending_sale_reminders (CELERY_TASK_ALWAYS_EAGER=True en test)."""

    def setUp(self) -> None:
        self.seller_user = User.objects.create_user(
            phone="+22300000050", password="x", display_name="SellerReminder"
        )
        self.seller = SellerProfile.objects.create(user=self.seller_user)

    def _sale(self, *, start_in, status=FlashSaleStatus.SCHEDULED):
        now = timezone.now()
        return FlashSale.objects.create(
            owner=self.seller,
            title="Vente rappel",
            start_time=now + start_in,
            end_time=now + start_in + timedelta(hours=1),
            status=status,
        )

    def _interest(self, sale, *, phone="+22399990001", reminded_at=None):
        from flash_sales.models import SaleInterest

        return SaleInterest.objects.create(
            flash_sale=sale, phone=phone, reminded_at=reminded_at
        )

    def test_reminds_interest_within_the_hour(self) -> None:
        from flash_sales.tasks import send_pending_sale_reminders
        from notifications.models import Notification

        sale = self._sale(start_in=timedelta(minutes=30))
        interest = self._interest(sale)

        send_pending_sale_reminders()

        interest.refresh_from_db()
        self.assertIsNotNone(interest.reminded_at)
        self.assertTrue(
            Notification.objects.filter(recipient_phone=interest.phone).exists()
        )

    def test_does_not_remind_sale_more_than_an_hour_away(self) -> None:
        from flash_sales.tasks import send_pending_sale_reminders

        sale = self._sale(start_in=timedelta(hours=3))
        interest = self._interest(sale)

        send_pending_sale_reminders()

        interest.refresh_from_db()
        self.assertIsNone(interest.reminded_at)

    def test_does_not_remind_twice(self) -> None:
        from flash_sales.tasks import send_pending_sale_reminders
        from notifications.models import Notification

        sale = self._sale(start_in=timedelta(minutes=30))
        already = timezone.now() - timedelta(minutes=5)
        interest = self._interest(sale, reminded_at=already)

        send_pending_sale_reminders()

        interest.refresh_from_db()
        self.assertEqual(interest.reminded_at, already)
        self.assertFalse(
            Notification.objects.filter(recipient_phone=interest.phone).exists()
        )

    def test_ignores_interest_on_non_scheduled_sale(self) -> None:
        from flash_sales.tasks import send_pending_sale_reminders

        sale = self._sale(start_in=timedelta(minutes=30), status=FlashSaleStatus.LIVE)
        interest = self._interest(sale)

        send_pending_sale_reminders()

        interest.refresh_from_db()
        self.assertIsNone(interest.reminded_at)


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


class PublicFlashSaleApiPermissionsTest(TestCase):
    """
    Garde-fou : trouve lors d'un audit complet des routes du projet — ces deux
    vues heritaient de DEFAULT_PERMISSION_CLASSES=IsAuthenticated (aucun
    override) et renvoyaient 403 a tout appelant anonyme, alors qu'elles sont
    censees etre l'API publique du calendrier de ventes (cf. PROJECT_SPEC.md,
    smoke_test.sh qui les appelle sans authentification).
    """

    def setUp(self) -> None:
        self.seller_user = User.objects.create_user(
            phone="+22300000070", password="x", display_name="SellerApi"
        )
        self.seller = SellerProfile.objects.create(user=self.seller_user)
        now = timezone.now()
        self.sale = FlashSale.objects.create(
            owner=self.seller,
            title="Vente API publique",
            start_time=now,
            end_time=now + timedelta(hours=1),
            status=FlashSaleStatus.LIVE,
        )

    def test_list_api_accessible_anonymously(self) -> None:
        from django.test import Client

        resp = Client().get("/api/v1/flash-sales/")
        self.assertEqual(resp.status_code, 200)

    def test_detail_api_accessible_anonymously(self) -> None:
        from django.test import Client

        resp = Client().get(f"/api/v1/flash-sales/{self.sale.public_slug}/")
        self.assertEqual(resp.status_code, 200)


class ActiveLiveSaleNavBadgeTest(TestCase):
    """
    Garde-fou : le badge "LIVE" de partials/_nav_seller.html referencait un
    contexte `active_sale` jamais peuple nulle part (seul `active_sales`,
    pluriel, existait dans seller_home_view) et un lien vers `flash_sales:live`
    (URL inexistante). Le bloc `{% if active_sale %}` etant toujours faux, ca
    ne crashait jamais — le badge n'est simplement jamais apparu. Corrige par
    core.context_processors.active_live_sale + lien vers flash_sales:detail.
    """

    def setUp(self) -> None:
        self.seller_user = User.objects.create_user(
            phone="+22300000071", password="x", display_name="SellerBadge"
        )
        self.seller = SellerProfile.objects.create(user=self.seller_user)

    def test_badge_appears_with_valid_link_when_sale_is_live(self) -> None:
        now = timezone.now()
        sale = FlashSale.objects.create(
            owner=self.seller,
            title="Vente en cours",
            start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=1),
            status=FlashSaleStatus.LIVE,
        )
        self.client.force_login(self.seller_user)
        resp = self.client.get("/seller/")
        content = resp.content.decode()
        self.assertIn("LIVE", content)
        self.assertIn(f"/seller/flash-sales/{sale.pk}/", content)

    def test_badge_absent_when_no_live_sale(self) -> None:
        self.client.force_login(self.seller_user)
        resp = self.client.get("/seller/")
        self.assertIsNone(resp.context["active_sale"])
