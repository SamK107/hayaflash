"""Suspension et reactivation d'une boutique par l'equipe (admin), avec journal d'audit."""

from __future__ import annotations

from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile, User
from accounts.services.suspension import (
    SuspensionError,
    reactivate_shop,
    suspend_shop,
)
from core.models import AuditLog
from flash_sales.models import FlashSale
from flash_sales.services.crud import create_flash_sale
from flash_sales.services.rules import SaleRuleError


def _shop(phone: str, name: str) -> SellerProfile:
    user = User.objects.create_user(phone=phone, password="x", display_name=name)
    return SellerProfile.objects.create(user=user, business_name=name)


class SuspensionServiceTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.staff = User.objects.create_superuser(phone="+22370000401", password="x", display_name="Equipe")
        self.shop = _shop("+22370000402", "Boutique X")

    def test_suspend_requires_reason_and_changes_nothing_without_it(self) -> None:
        for bad in ("", "   "):
            with self.subTest(reason=bad), self.assertRaises(SuspensionError):
                suspend_shop(self.shop, actor=self.staff, reason=bad)
        self.shop.refresh_from_db()
        self.assertTrue(self.shop.is_active)
        self.assertFalse(AuditLog.objects.exists())

    def test_reason_length_limited(self) -> None:
        with self.assertRaises(SuspensionError):
            suspend_shop(self.shop, actor=self.staff, reason="x" * 301)

    def test_suspend_then_reactivate_is_audited_and_deletes_nothing(self) -> None:
        sale = FlashSale.objects.create(
            title="Vente", start_time=timezone.now() + timedelta(days=1),
            end_time=timezone.now() + timedelta(days=1, hours=2), owner=self.shop,
        )
        suspend_shop(self.shop, actor=self.staff, reason="  Plaintes répétées  ", ip="203.0.113.5")
        self.shop.refresh_from_db()
        self.assertFalse(self.shop.is_active)

        log = AuditLog.objects.get()
        self.assertEqual(log.action, "shop.suspended")
        self.assertEqual(log.entity_type, "SellerProfile")
        self.assertEqual(log.entity_id, self.shop.pk)
        self.assertEqual(log.actor, self.staff)
        self.assertEqual(log.metadata["reason"], "Plaintes répétées")
        self.assertEqual(str(log.ip_address), "203.0.113.5")

        reactivate_shop(self.shop, actor=self.staff, reason="Vérifié par téléphone")
        self.shop.refresh_from_db()
        self.assertTrue(self.shop.is_active)
        self.assertEqual(AuditLog.objects.filter(action="shop.reactivated").count(), 1)

        # Aucune suppression : la vente et la boutique existent toujours.
        self.assertTrue(FlashSale.objects.filter(pk=sale.pk).exists())
        self.assertTrue(SellerProfile.objects.filter(pk=self.shop.pk).exists())

    def test_already_in_state_is_refused(self) -> None:
        with self.assertRaises(SuspensionError):
            reactivate_shop(self.shop, actor=self.staff, reason="déjà active")
        self.assertFalse(AuditLog.objects.exists())


class SuspendedShopCannotSellTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.shop = _shop("+22370000411", "Boutique Y")
        self.start = timezone.now() + timedelta(days=2)
        self.end = self.start + timedelta(hours=2)

    def test_active_shop_can_create_sale(self) -> None:
        sale = create_flash_sale(owner=self.shop, title="Ok", start_time=self.start, end_time=self.end)
        self.assertEqual(sale.owner, self.shop)

    def test_suspended_shop_cannot_create_sale(self) -> None:
        suspend_shop(self.shop, actor=None, reason="Test suspension")
        with self.assertRaises(SaleRuleError):
            create_flash_sale(owner=self.shop, title="Refusee", start_time=self.start, end_time=self.end)
        self.assertFalse(FlashSale.objects.filter(title="Refusee").exists())


class SuspensionAdminTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.staff = User.objects.create_superuser(phone="+22370000421", password="x", display_name="Equipe")
        self.shop = _shop("+22370000422", "Boutique Z")
        self.client.force_login(self.staff)
        self.url = reverse("admin:accounts_sellerprofile_changelist")

    def test_two_step_suspend_with_reason(self) -> None:
        # Etape 1 : choix de l'action -> page de confirmation (motif obligatoire).
        resp = self.client.post(self.url, {
            "action": "suspend_shops", "index": 0, "select_across": 0,
            "_selected_action": [self.shop.pk],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Motif (obligatoire)")
        self.shop.refresh_from_db()
        self.assertTrue(self.shop.is_active)

        # Etape 2 : confirmation avec motif.
        resp = self.client.post(self.url, {
            "action": "suspend_shops", "select_across": 0, "apply": 1,
            "_selected_action": [self.shop.pk], "reason": "Signalements vérifiés",
        })
        self.assertEqual(resp.status_code, 302)
        self.shop.refresh_from_db()
        self.assertFalse(self.shop.is_active)
        self.assertEqual(AuditLog.objects.get().action, "shop.suspended")

    def test_two_step_suspend_without_reason_changes_nothing(self) -> None:
        self.client.post(self.url, {
            "action": "suspend_shops", "select_across": 0, "apply": 1,
            "_selected_action": [self.shop.pk], "reason": "  ",
        })
        self.shop.refresh_from_db()
        self.assertTrue(self.shop.is_active)
        self.assertFalse(AuditLog.objects.exists())
