"""Commande de dev seed_marche_demo."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from core.management.commands.seed_marche_demo import DEMO_PHONE_PREFIX
from delivery.models import Delivery
from flash_sales.market_stats import compute_market_stats
from flash_sales.models import FlashSale
from orders.models import Order

User = get_user_model()


class SeedMarcheDemoTests(TestCase):
    def setUp(self) -> None:
        cache.clear()

    @override_settings(DEBUG=False)
    def test_refuses_when_debug_false(self) -> None:
        with self.assertRaises(CommandError):
            call_command("seed_marche_demo")
        self.assertFalse(User.objects.filter(phone__startswith=DEMO_PHONE_PREFIX).exists())

    @override_settings(DEBUG=True)
    def test_creates_demo_then_clears_everything(self) -> None:
        other = User.objects.create_user(phone="+22370000999", password="x", display_name="Autre")
        call_command("seed_marche_demo", verbosity=0)
        self.assertEqual(User.objects.filter(phone__startswith=DEMO_PHONE_PREFIX).count(), 3)
        self.assertEqual(FlashSale.objects.count(), 3)
        self.assertEqual(Order.service_objects.count(), 10)
        self.assertEqual(Delivery.objects.filter(status=Delivery.Status.IN_TRANSIT).count(), 3)
        stats = compute_market_stats()
        self.assertTrue(stats["visible"])
        self.assertEqual(stats["deliveries_in_transit"], 3)
        self.assertEqual(self.client.get(reverse("flash_sale_calendar")).status_code, 200)
        with self.assertRaises(CommandError):
            call_command("seed_marche_demo", verbosity=0)  # deja presente

        call_command("seed_marche_demo", "--clear", verbosity=0)
        self.assertFalse(User.objects.filter(phone__startswith=DEMO_PHONE_PREFIX).exists())
        self.assertEqual(FlashSale.objects.count(), 0)
        self.assertEqual(Order.service_objects.count(), 0)
        self.assertTrue(User.objects.filter(pk=other.pk).exists())
