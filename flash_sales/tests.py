from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from flash_sales.services.ordering import assert_flash_sale_accepts_orders
from orders.models import Order
from orders.services.create_order import create_order
from orders.tests import valid_delivery_payload
from products.models import FlashSaleProduct, Product
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

    def test_open_sale_early_pulls_start_time_forward(self) -> None:
        """
        Ouvrir une vente programmee AVANT son heure prevue doit vraiment la
        rendre commandable tout de suite (le message affiche au vendeur est
        "Les commandes sont acceptees.") : is_live()/accepts_orders ne se
        basent que sur start_time/end_time, pas sur le statut. Sans ce
        garde-fou, le bouton "Ouvrir la vente" mentait au vendeur et aucune
        commande n'etait jamais acceptee (voir Phase 10.0).
        """
        now = timezone.now()
        sale = self._sale(
            status=FlashSaleStatus.SCHEDULED,
            start_time=now + timedelta(hours=2),
            end_time=now + timedelta(hours=3),
        )
        sale.open_sale()
        sale.refresh_from_db()

        self.assertEqual(sale.status, FlashSaleStatus.LIVE)
        self.assertTrue(sale.is_live())
        self.assertTrue(sale.accepts_orders)
        # La duree prevue par le vendeur (1h) est conservee, seule la
        # fenetre est avancee a maintenant.
        self.assertAlmostEqual(
            (sale.end_time - sale.start_time).total_seconds(),
            timedelta(hours=1).total_seconds(),
            delta=2,
        )

    def test_open_sale_after_start_time_does_not_shift_window(self) -> None:
        """Ouvrir une vente pile a l'heure (ou en retard) ne doit pas toucher
        a la fenetre existante — seul le cas "trop tot" a besoin du garde-fou."""
        now = timezone.now()
        sale = self._sale(
            status=FlashSaleStatus.SCHEDULED,
            start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=1),
        )
        original_start, original_end = sale.start_time, sale.end_time
        sale.open_sale()
        sale.refresh_from_db()

        self.assertEqual(sale.status, FlashSaleStatus.LIVE)
        self.assertEqual(sale.start_time, original_start)
        self.assertEqual(sale.end_time, original_end)

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
            owner=sale.owner,
            name="SKU-1",
            stock_available=5,
            stock_initial=5,
            price="10.00",
        )
        FlashSaleProduct.objects.create(flash_sale=sale, product=product)
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
        with self.assertRaises(ValidationError):
            assert_flash_sale_accepts_orders(None)


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

        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "flash_sales/quota_exceeded.html")
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

        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "flash_sales/quota_exceeded.html")
        self.assertEqual(
            FlashSale.objects.filter(owner=self.seller, title="Nouvelle vente").count(),
            0,
        )


class PublicCalendarScheduledLinkTest(TestCase):
    """Audit 10.0 : les ventes programmees du calendrier public n'avaient pas de lien."""

    def setUp(self) -> None:
        seller_user = User.objects.create_user(
            phone="+15550009999", password="x", display_name="Seller"
        )
        self.seller = SellerProfile.objects.create(user=seller_user)

    def test_scheduled_sale_card_links_to_public_page(self) -> None:
        now = timezone.now()
        sale = FlashSale.objects.create(
            title="Vente a venir",
            start_time=now + timedelta(hours=2),
            end_time=now + timedelta(hours=3),
            status=FlashSaleStatus.SCHEDULED,
            owner=self.seller,
        )
        response = self.client.get(reverse("flash_sale_calendar"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, reverse("public_flash_sale", kwargs={"slug": sale.public_slug})
        )


class OrderingStatusGuardTest(TestCase):
    """Une vente annulee/fermee/terminee refuse les commandes, meme dans sa fenetre horaire."""

    def setUp(self) -> None:
        seller_user = User.objects.create_user(
            phone="+15550008888", password="x", display_name="Seller"
        )
        self.seller = SellerProfile.objects.create(user=seller_user)
        self.product = Product.objects.create(
            owner=self.seller,
            name="Pagne",
            price="5000.00",
            stock_initial=10,
            stock_available=10,
        )

    def _sale(self, status) -> FlashSale:
        now = timezone.now()
        sale = FlashSale.objects.create(
            title="Vente test",
            start_time=now - timedelta(minutes=10),
            end_time=now + timedelta(hours=1),
            status=status,
            owner=self.seller,
        )
        FlashSaleProduct.objects.create(flash_sale=sale, product=self.product)
        return sale

    def test_blocked_statuses_inside_window(self) -> None:
        for status in (
            FlashSaleStatus.CANCELLED,
            FlashSaleStatus.CLOSED,
            FlashSaleStatus.EXECUTING,
            FlashSaleStatus.COMPLETED,
        ):
            with self.subTest(status=status):
                sale = self._sale(status)
                with self.assertRaises(ValidationError) as ctx:
                    assert_flash_sale_accepts_orders(sale)
                self.assertIn("annulée", str(ctx.exception))

    def test_live_and_late_scheduled_accept_orders(self) -> None:
        for status in (FlashSaleStatus.LIVE, FlashSaleStatus.SCHEDULED):
            with self.subTest(status=status):
                assert_flash_sale_accepts_orders(self._sale(status))

    def test_api_refuses_order_on_cancelled_sale(self) -> None:
        sale = self._sale(FlashSaleStatus.CANCELLED)
        payload = {
            "flash_sale_id": sale.pk,
            "product_id": self.product.pk,
            "name": "Client",
            "phone": "+22370000001",
            "quantity": 1,
            "client_request_id": str(uuid4()),
            "delivery": valid_delivery_payload(),
        }
        resp = self.client.post(
            "/api/v1/orders/", data=payload, content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("annulée", resp.content.decode())
        self.assertFalse(Order.service_objects.filter(flash_sale=sale).exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_available, 10)


class SellerInstallInviteTest(TestCase):
    """Bandeau "Installez votre espace vendeur" : apres creation d'une vente
    uniquement, affiche une seule fois (flag de session consomme par base.html)."""

    def setUp(self) -> None:
        self.seller_user = User.objects.create_user(
            phone="+22300000060", password="x", display_name="SellerInstall"
        )
        self.seller = SellerProfile.objects.create(user=self.seller_user)
        Subscription.objects.get_or_create(
            seller=self.seller, defaults={"plan": Plan.FREE}
        )
        self.client.force_login(self.seller_user)

    def test_invite_after_first_sale_then_consumed(self) -> None:
        self.assertNotContains(self.client.get(reverse("seller_home")), "data-hf-install-invite")
        start = timezone.now() + timedelta(days=1)
        resp = self.client.post(
            reverse("flash_sales:create"),
            {
                "title": "Premiere vente",
                "description": "",
                "teasers": "",
                "start_time": start.strftime("%Y-%m-%d %H:%M"),
                "delivery_zone": "",
                "duration_preset": "60",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-hf-install-invite="seller"')
        # Consomme : pas de nouvelle invitation sur la page suivante.
        self.assertNotContains(self.client.get(reverse("seller_home")), "data-hf-install-invite")

    def test_htmx_fragment_does_not_consume_invite(self) -> None:
        from core.context_processors import PWA_INSTALL_INVITE_SESSION_KEY

        session = self.client.session
        session[PWA_INSTALL_INVITE_SESSION_KEY] = "seller"
        session.save()
        self.client.get(reverse("seller_home"), HTTP_HX_REQUEST="true")
        self.assertEqual(self.client.session.get(PWA_INSTALL_INVITE_SESSION_KEY), "seller")


class SellerListByTimeTest(TestCase):
    """
    Phase 10.0 (cloture) : /seller/flash-sales/, la fiche vente, le badge nav,
    le dashboard LIVE et l'admin plateforme classaient par statut brut. Sans
    Celery beat (dev) ou en retard (prod), une vente SCHEDULED deja ouverte
    restait "Programmee" et une vente LIVE finie restait "LIVE" indefiniment.
    Regle unique : l'heure fait foi (CLAUDE.md point 15).
    """

    def setUp(self) -> None:
        self.seller_user = User.objects.create_user(
            phone="+22300000091", password="x", display_name="SellerTabs"
        )
        self.seller = SellerProfile.objects.create(user=self.seller_user)
        self.client.force_login(self.seller_user)
        now = timezone.now()
        h = timedelta(hours=1)

        def mk(title, status, start, end):
            return FlashSale.objects.create(
                owner=self.seller, title=title, status=status,
                start_time=start, end_time=end,
            )

        self.upcoming = mk("A venir", FlashSaleStatus.SCHEDULED, now + h, now + 2 * h)
        self.late_open = mk("Ouverte sans beat", FlashSaleStatus.SCHEDULED, now - h, now + h)
        self.live = mk("En direct", FlashSaleStatus.LIVE, now - h, now + h)
        self.stale_live = mk("LIVE finie", FlashSaleStatus.LIVE, now - 3 * h, now - 2 * h)
        self.stale_sched = mk("Jamais ouverte finie", FlashSaleStatus.SCHEDULED, now - 3 * h, now - 2 * h)
        self.closed = mk("Fermee", FlashSaleStatus.CLOSED, now - h, now + h)
        self.executing = mk("Execution", FlashSaleStatus.EXECUTING, now - 3 * h, now - 2 * h)
        self.completed = mk("Terminee", FlashSaleStatus.COMPLETED, now - 3 * h, now - 2 * h)
        self.cancelled = mk("Annulee", FlashSaleStatus.CANCELLED, now + h, now + 2 * h)

    def test_tabs_follow_time_and_partition_all_sales(self) -> None:
        resp = self.client.get(reverse("flash_sales:list"))
        self.assertEqual(resp.status_code, 200)
        ids = lambda key: {s.pk for s in resp.context[key]}  # noqa: E731
        self.assertEqual(ids("sales_scheduled"), {self.upcoming.pk})
        self.assertEqual(ids("sales_live"), {self.late_open.pk, self.live.pk})
        self.assertEqual(
            ids("sales_closed"),
            {self.stale_live.pk, self.stale_sched.pk, self.closed.pk, self.executing.pk},
        )
        self.assertEqual(ids("sales_done"), {self.completed.pk, self.cancelled.pk})
        total = sum(len(resp.context[k]) for k in
                    ("sales_scheduled", "sales_live", "sales_closed", "sales_done"))
        self.assertEqual(total, FlashSale.objects.filter(owner=self.seller).count())
        self.assertEqual(resp.context["default_tab"], "live")

    def test_seller_state_matches_tabs(self) -> None:
        self.assertEqual(self.upcoming.seller_state, "upcoming")
        self.assertEqual(self.late_open.seller_state, "live")
        self.assertEqual(self.stale_live.seller_state, "ended")
        self.assertEqual(self.stale_sched.seller_state, "ended")
        self.assertEqual(self.closed.seller_state, "ended")
        self.assertEqual(self.executing.seller_state, "executing")
        self.assertEqual(self.completed.seller_state, "completed")
        self.assertEqual(self.cancelled.seller_state, "cancelled")

    def test_detail_of_stale_live_sale_offers_closing_not_live(self) -> None:
        resp = self.client.get(reverse("flash_sales:detail", kwargs={"pk": self.stale_live.pk}))
        html = resp.content.decode()
        self.assertIn("Clôturer la vente", html)
        self.assertIn("Fermée", html)
        self.assertNotIn("animate-ping", html)  # pas de badge LIVE

    def test_detail_of_late_opened_scheduled_sale_is_live(self) -> None:
        resp = self.client.get(reverse("flash_sales:detail", kwargs={"pk": self.late_open.pk}))
        html = resp.content.decode()
        self.assertIn("Tableau LIVE", html)
        self.assertNotIn("Annuler la vente", html)
        self.assertNotIn("Ouvrir la vente", html)

    def test_cannot_cancel_scheduled_sale_already_taking_orders(self) -> None:
        with self.assertRaises(ValueError):
            self.late_open.cancel_sale()
        self.upcoming.cancel_sale()
        self.upcoming.refresh_from_db()
        self.assertEqual(self.upcoming.status, FlashSaleStatus.CANCELLED)

    def test_nav_badge_and_live_dashboard_ignore_stale_live(self) -> None:
        FlashSale.objects.filter(pk__in=[self.live.pk, self.late_open.pk]).delete()
        resp = self.client.get("/seller/")
        self.assertIsNone(resp.context["active_sale"])
        resp = self.client.get(reverse("orders:seller_dashboard"))
        self.assertIsNone(resp.context["live_sale"])
        self.assertEqual(resp.context["next_sale"], self.upcoming)

    def test_default_tab_is_scheduled_without_live_sale(self) -> None:
        FlashSale.objects.filter(pk__in=[self.live.pk, self.late_open.pk]).delete()
        resp = self.client.get(reverse("flash_sales:list"))
        self.assertEqual(resp.context["default_tab"], "scheduled")
