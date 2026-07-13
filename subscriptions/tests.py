"""Tests subscription limits."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from subscriptions.models import Plan, Subscription
from subscriptions.services.limits import can_create_flash_sale, FREE_MONTHLY_SALES_LIMIT

User = get_user_model()


def _make_seller(phone="+22300000001"):
    user = User.objects.create_user(phone=phone, password="x", display_name="Vendeur")
    return SellerProfile.objects.create(user=user)


def _make_sale(seller, *, months_ago=0):
    now = timezone.now()
    sale = FlashSale.objects.create(
        owner=seller,
        title="Vente test",
        start_time=now + timedelta(hours=1),
        end_time=now + timedelta(hours=2),
        status=FlashSaleStatus.SCHEDULED,
    )
    if months_ago:
        past = now - timedelta(days=months_ago * 31)
        FlashSale.objects.filter(pk=sale.pk).update(created_at=past)
        sale.created_at = past
    return sale


class FreePlanLimitsTest(TestCase):
    def setUp(self):
        self.seller = _make_seller("+22300000010")
        Subscription.objects.get_or_create(seller=self.seller, defaults={"plan": Plan.FREE})

    def test_free_plan_allows_up_to_limit(self):
        for i in range(FREE_MONTHLY_SALES_LIMIT):
            ok, msg = can_create_flash_sale(self.seller)
            self.assertTrue(ok, f"Devrait pouvoir creer la vente {i + 1}")
            _make_sale(self.seller)

    def test_free_plan_blocks_at_limit(self):
        for _ in range(FREE_MONTHLY_SALES_LIMIT):
            _make_sale(self.seller)
        ok, msg = can_create_flash_sale(self.seller)
        self.assertFalse(ok)
        self.assertIn("limite", msg.lower())

    def test_old_month_sales_do_not_count(self):
        for _ in range(FREE_MONTHLY_SALES_LIMIT):
            _make_sale(self.seller, months_ago=1)
        ok, _ = can_create_flash_sale(self.seller)
        self.assertTrue(ok, "Les ventes du mois precedent ne doivent pas bloquer")


class ProPlanLimitsTest(TestCase):
    def setUp(self):
        self.seller = _make_seller("+22300000020")
        Subscription.objects.get_or_create(seller=self.seller, defaults={"plan": Plan.PRO})

    def test_pro_plan_unlimited(self):
        for _ in range(FREE_MONTHLY_SALES_LIMIT + 5):
            _make_sale(self.seller)
        ok, msg = can_create_flash_sale(self.seller)
        self.assertTrue(ok, "Le plan Pro ne doit pas avoir de limite")
        self.assertEqual(msg, "")
