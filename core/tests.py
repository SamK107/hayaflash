from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from subscriptions.models import (
    PaymentProvider,
    PaymentStatus,
    Plan,
    Subscription,
    SubscriptionPayment,
)

User = get_user_model()


class PlatformAdminDashboardTests(TestCase):
    """Couvre core.views.platform_admin_dashboard (staff only, chiffres financiers)."""

    def setUp(self) -> None:
        self.url = reverse("platform_admin")
        self.client = Client()

        self.staff_user = User.objects.create_user(
            phone="+22370000001",
            password="x",
            display_name="Admin",
            is_staff=True,
        )
        self.non_staff_user = User.objects.create_user(
            phone="+22370000002",
            password="x",
            display_name="Vendeur",
        )
        self.seller = SellerProfile.objects.create(
            user=self.non_staff_user,
            business_name="Boutique Test",
        )

    def test_anonymous_user_is_redirected_to_admin_login(self) -> None:
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    def test_non_staff_user_is_redirected_not_shown_dashboard(self) -> None:
        # staff_member_required (django.contrib.admin) redirige plutot que
        # de renvoyer 403 : verifie qu'un vendeur non-staff n'atteint jamais
        # les donnees financieres.
        self.client.force_login(self.non_staff_user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])
        self.assertNotEqual(resp.status_code, 200)

    def test_staff_user_gets_200(self) -> None:
        self.client.force_login(self.staff_user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_context_contains_expected_dashboard_data(self) -> None:
        self.client.force_login(self.staff_user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

        for key in (
            "total_sellers",
            "subs_by_plan",
            "live_sales",
            "total_orders_month",
            "mrr",
            "total_revenue",
            "revenue_ytd",
            "revenue_timeline_json",
            "orange",
            "subscribed_sellers",
            "recent_payments",
        ):
            self.assertIn(key, resp.context, f"contexte manquant: {key}")

    def test_total_sellers_counts_only_active_sellers(self) -> None:
        SellerProfile.objects.create(
            user=User.objects.create_user(
                phone="+22370000003", password="x", display_name="Inactif"
            ),
            business_name="Boutique Inactive",
            is_active=False,
        )
        self.client.force_login(self.staff_user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.context["total_sellers"], 1)

    def _make_payment(self, *, amount, status, paid_at, order_id):
        return SubscriptionPayment.objects.create(
            seller=self.seller,
            plan=Plan.MEDIUM,
            provider=PaymentProvider.ORANGE,
            amount=amount,
            phone=self.non_staff_user.phone,
            status=status,
            order_id=order_id,
            paid_at=paid_at,
        )

    def test_mrr_only_sums_recent_successful_payments(self) -> None:
        now = timezone.now()
        self._make_payment(
            amount=2000, status=PaymentStatus.SUCCESS, paid_at=now, order_id="ord-recent-ok"
        )
        self._make_payment(
            amount=5000,
            status=PaymentStatus.SUCCESS,
            paid_at=now - timedelta(days=45),
            order_id="ord-old-ok",
        )
        self._make_payment(
            amount=9999,
            status=PaymentStatus.PENDING,
            paid_at=None,
            order_id="ord-pending",
        )

        self.client.force_login(self.staff_user)
        resp = self.client.get(self.url)

        self.assertEqual(resp.context["mrr"], 2000)
        self.assertEqual(resp.context["total_revenue"], 7000)

    def test_recent_payments_lists_created_payment(self) -> None:
        payment = self._make_payment(
            amount=2000,
            status=PaymentStatus.SUCCESS,
            paid_at=timezone.now(),
            order_id="ord-visible",
        )
        self.client.force_login(self.staff_user)
        resp = self.client.get(self.url)
        recent_ids = [p.id for p in resp.context["recent_payments"]]
        self.assertIn(payment.id, recent_ids)

    def test_subs_by_plan_groups_by_plan(self) -> None:
        Subscription.objects.create(seller=self.seller, plan=Plan.PRO)
        self.client.force_login(self.staff_user)
        resp = self.client.get(self.url)
        by_plan = {row["plan"]: row["count"] for row in resp.context["subs_by_plan"]}
        self.assertEqual(by_plan.get(Plan.PRO), 1)
