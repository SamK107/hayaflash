"""Niveaux de confiance (D10) et drapeau MARKET_REQUIRE_VERIFIED sur le Marche.

- Drapeau faux (defaut) : comportement inchange, toute boutique active est listee.
- Drapeau vrai : seules les boutiques trust_level >= 1 sont listees.
- Une boutique suspendue reste exclue dans les deux cas.
- Le niveau est un indicateur d'equipe : aucun badge public dans cette tache.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile, User
from analytics.services.market import compute_market_snapshot
from flash_sales.models import FlashSale, FlashSaleStatus
from products.models import FlashSaleProduct, Product


def _shop(phone: str, name: str, *, trust_level: int | None = None, is_active: bool = True) -> SellerProfile:
    user = User.objects.create_user(phone=phone, password="x", display_name=name)
    kwargs = {"user": user, "business_name": name, "is_active": is_active}
    if trust_level is not None:
        kwargs["trust_level"] = trust_level
    return SellerProfile.objects.create(**kwargs)


class TrustLevelDefaultTests(TestCase):
    def test_new_shop_starts_unverified(self) -> None:
        shop = _shop("+22370000501", "Neuve")
        self.assertEqual(shop.trust_level, SellerProfile.TrustLevel.UNVERIFIED)
        self.assertEqual(shop.trust_level, 0)


class MarketTrustFlagTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        now = timezone.now()
        self.shops = {
            0: _shop("+22370000511", "Niveau zero", trust_level=0),
            1: _shop("+22370000512", "Niveau un", trust_level=1),
            2: _shop("+22370000513", "Niveau deux", trust_level=2),
        }
        self.suspended = _shop("+22370000514", "Suspendue", trust_level=2, is_active=False)
        self.sales = {}
        for key, shop in {**self.shops, "s": self.suspended}.items():
            sale = FlashSale.objects.create(
                title=f"Vente {key}", start_time=now - timedelta(hours=1),
                end_time=now + timedelta(hours=2), status=FlashSaleStatus.LIVE, owner=shop,
            )
            product = Product.objects.create(
                owner=shop, name=f"Produit {key}", stock_available=5, stock_initial=5,
                price=Decimal("3000.00"),
            )
            FlashSaleProduct.objects.create(flash_sale=sale, product=product)
            self.sales[key] = sale

    def _live_ids(self) -> set[int]:
        cache.clear()
        return set(compute_market_snapshot()["sales"].keys())

    def test_flag_off_by_default_lists_every_active_shop(self) -> None:
        ids = self._live_ids()
        for key in (0, 1, 2):
            self.assertIn(self.sales[key].pk, ids)
        self.assertNotIn(self.sales["s"].pk, ids)

    @override_settings(MARKET_REQUIRE_VERIFIED=True)
    def test_flag_on_lists_only_verified_shops(self) -> None:
        ids = self._live_ids()
        self.assertNotIn(self.sales[0].pk, ids)
        self.assertIn(self.sales[1].pk, ids)
        self.assertIn(self.sales[2].pk, ids)
        self.assertNotIn(self.sales["s"].pk, ids)

    @override_settings(MARKET_REQUIRE_VERIFIED=True)
    def test_calendar_page_respects_flag(self) -> None:
        cache.clear()
        resp = self.client.get(reverse("flash_sale_calendar"))
        self.assertContains(resp, "Vente 1")
        self.assertContains(resp, "Vente 2")
        self.assertNotContains(resp, "Vente 0")
        self.assertNotContains(resp, "Vente s")

    def test_calendar_page_default_shows_unverified_shop(self) -> None:
        cache.clear()
        resp = self.client.get(reverse("flash_sale_calendar"))
        self.assertContains(resp, "Vente 0")


class TrustLevelAdminTests(TestCase):
    def test_admin_lists_trust_level_column_and_filter(self) -> None:
        admin_user = User.objects.create_superuser(phone="+22370000521", password="x", display_name="Equipe")
        _shop("+22370000522", "Admin visible", trust_level=1)
        self.client.force_login(admin_user)
        resp = self.client.get(reverse("admin:accounts_sellerprofile_changelist"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Niveau de confiance")
        filtered = self.client.get(reverse("admin:accounts_sellerprofile_changelist") + "?trust_level__exact=1")
        self.assertEqual(len(filtered.context["cl"].result_list), 1)
