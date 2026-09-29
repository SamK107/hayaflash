"""F-29 / F-31 : quota mensuel, 3 ventes/jour, 2 h max — tous chemins de creation."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from core.models import AuditLog
from flash_sales.models import FlashSale, FlashSaleStatus, SaleOpeningRefused
from flash_sales.services.crud import (
    clone_flash_sale,
)
from flash_sales.tasks import auto_open_scheduled_sales
from subscriptions.models import Plan, Subscription

BAMAKO = ZoneInfo("Africa/Bamako")

User = get_user_model()


class RulesBase(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            phone="+22370000001", password="x", display_name="Vendeur"
        )
        self.seller = SellerProfile.objects.create(user=self.user)
        self.client.force_login(self.user)

    def _sale(self, *, start, status=FlashSaleStatus.SCHEDULED, hours=1, **kw):
        return FlashSale.objects.create(
            owner=self.seller,
            title=kw.pop("title", "Vente"),
            start_time=start,
            end_time=start + timedelta(hours=hours),
            status=status,
            **kw,
        )

    def _old_sales(self, n, status=FlashSaleStatus.COMPLETED):
        """n ventes creees ce mois-ci, mais dont la date est loin (pas de 3/jour)."""
        base = timezone.now() - timedelta(days=10)
        return [
            self._sale(start=base - timedelta(days=i), status=status)
            for i in range(n)
        ]


class CloneBypassReproTests(RulesBase):
    """Reproduisent F-29 : doivent ECHOUER sur le code d'origine."""

    def test_clone_refused_when_monthly_quota_reached(self):
        sales = self._old_sales(3)  # FREE = 3 / mois, quota atteint
        before = FlashSale.objects.count()
        resp = self.client.post(reverse("flash_sales:clone", args=[sales[0].pk]))
        self.assertEqual(FlashSale.objects.count(), before)
        self.assertEqual(resp.status_code, 302)

    def test_clone_refused_when_three_sales_already_that_day(self):
        clone_day = timezone.localtime(timezone.now() + timedelta(days=1))
        day = clone_day.replace(hour=8, minute=0, second=0, microsecond=0)
        # 3 ventes ce jour-la mais creees ce mois-ci : quota FREE (3) atteint aussi ;
        # on passe MEDIUM pour isoler la regle 3/jour.
        _set_plan(self.seller, Plan.MEDIUM)
        sales = [
            self._sale(start=day + timedelta(hours=3 * i), hours=1) for i in range(3)
        ]
        before = FlashSale.objects.count()
        self.client.post(reverse("flash_sales:clone", args=[sales[0].pk]))
        self.assertEqual(FlashSale.objects.count(), before)

    def test_cloned_sale_beyond_quota_is_not_auto_opened(self):
        self._old_sales(3)
        # Contournement : le clone est cree sans controle, puis ouvert par beat.
        clone = self._sale(
            start=timezone.now() - timedelta(minutes=1),
            status=FlashSaleStatus.SCHEDULED,
            title="Copie",
        )
        auto_open_scheduled_sales()
        clone.refresh_from_db()
        self.assertEqual(clone.status, FlashSaleStatus.SCHEDULED)


def _set_plan(seller, plan, *, expired=False):
    Subscription.objects.update_or_create(
        seller=seller,
        defaults={
            "plan": plan,
            "expires_at": (
                timezone.now() + timedelta(days=-1 if expired else 30)
                if plan != Plan.FREE
                else None
            ),
        },
    )


def _future_day(offset=10):
    """Minuit (Bamako) d'un jour futur, pour des tests independants de l'heure."""
    d = timezone.localtime(timezone.now() + timedelta(days=offset))
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


class CloneRulesTests(RulesBase):
    def test_clone_allowed_when_rules_ok(self):
        [sale] = self._old_sales(1)
        clone = clone_flash_sale(sale=sale, seller=self.seller)
        self.assertEqual(clone.status, FlashSaleStatus.SCHEDULED)

    def test_clone_refused_at_quota_free_and_medium(self):
        for plan, limit in ((Plan.FREE, 3), (Plan.MEDIUM, 10)):
            FlashSale.objects.all().delete()
            _set_plan(self.seller, plan)
            sales = self._old_sales(limit - 1)
            clone_flash_sale(sale=sales[0], seller=self.seller)  # dernier slot : passe
            with self.assertRaises(ValidationError) as cm:
                clone_flash_sale(sale=sales[0], seller=self.seller)
            self.assertIn("ventes ce mois-ci", " ".join(cm.exception.messages))

    def test_clone_pro_not_limited_by_quota_but_by_daily_rule(self):
        _set_plan(self.seller, Plan.PRO)
        sales = self._old_sales(2)
        for _ in range(3):
            clone_flash_sale(sale=sales[0], seller=self.seller)
        with self.assertRaises(ValidationError) as cm:
            clone_flash_sale(sale=sales[0], seller=self.seller)
        self.assertIn("par jour", " ".join(cm.exception.messages))

    def test_clone_view_shows_readable_french_message(self):
        sales = self._old_sales(3)
        resp = self.client.post(
            reverse("flash_sales:clone", args=[sales[0].pk]), follow=True
        )
        msgs = [str(m) for m in resp.context["messages"]]
        self.assertTrue(any("ventes ce mois-ci" in m for m in msgs), msgs)
        self.assertFalse(any("['" in m for m in msgs), msgs)


class OpeningRulesTests(RulesBase):
    def test_last_allowed_sale_opens(self):
        """La vente du dernier slot n'est pas comptee contre elle-meme."""
        self._old_sales(2)
        last = self._sale(start=timezone.now() - timedelta(minutes=1))
        self.assertEqual(FlashSale.objects.count(), 3)
        last.open_sale()
        last.refresh_from_db()
        self.assertEqual(last.status, FlashSaleStatus.LIVE)

    def test_manual_open_refused_beyond_quota_keeps_status(self):
        self._old_sales(3)
        clone = self._sale(start=timezone.now() - timedelta(minutes=1))
        with self.assertRaises(SaleOpeningRefused):
            clone.open_sale()
        clone.refresh_from_db()
        self.assertEqual(clone.status, FlashSaleStatus.SCHEDULED)

    def test_manual_open_view_shows_reason_and_keeps_scheduled(self):
        self._old_sales(3)
        clone = self._sale(start=timezone.now() + timedelta(hours=1))
        resp = self.client.post(
            reverse("flash_sales:open", args=[clone.pk]), follow=True
        )
        clone.refresh_from_db()
        self.assertEqual(clone.status, FlashSaleStatus.SCHEDULED)
        msgs = [str(m) for m in resp.context["messages"]]
        self.assertTrue(any("ventes ce mois-ci" in m for m in msgs), msgs)

    def test_refused_open_does_not_shift_window(self):
        self._old_sales(3)
        start = timezone.now() + timedelta(hours=3)
        clone = self._sale(start=start)
        with self.assertRaises(SaleOpeningRefused):
            clone.open_sale()
        clone.refresh_from_db()
        self.assertEqual(clone.start_time, start)

    def test_auto_open_refused_logs_and_audits_once(self):
        self._old_sales(3)
        clone = self._sale(start=timezone.now() - timedelta(minutes=1))
        with self.assertLogs("flash_sales.tasks", level="WARNING") as cm:
            auto_open_scheduled_sales()
        self.assertTrue(any("REFUSEE" in line for line in cm.output))
        auto_open_scheduled_sales()  # 2e passage de beat : pas de doublon
        clone.refresh_from_db()
        self.assertEqual(clone.status, FlashSaleStatus.SCHEDULED)
        self.assertEqual(
            AuditLog.objects.filter(
                action="flashsale.open_refused", entity_id=clone.pk
            ).count(),
            1,
        )

    def test_auto_open_still_opens_compliant_sales(self):
        sale = self._sale(start=timezone.now() - timedelta(minutes=1))
        auto_open_scheduled_sales()
        sale.refresh_from_db()
        self.assertEqual(sale.status, FlashSaleStatus.LIVE)

    def test_open_refused_when_day_is_full(self):
        _set_plan(self.seller, Plan.PRO)
        day = _future_day(1)
        # 3 ventes deja programmees ce jour-la ; une 4e (creee sans controle)
        for h in (8, 10, 12):
            self._sale(start=day + timedelta(hours=h))
        fourth = self._sale(start=day + timedelta(hours=15))
        with self.assertRaises(SaleOpeningRefused) as cm:
            # fenetre passee par rapport a « maintenant » : pas de decalage,
            # la regle du jour s'applique sur le jour de la vente
            with patch("flash_sales.models.timezone.now", return_value=day + timedelta(hours=15, minutes=1)):
                fourth.open_sale()
        self.assertIn("par jour", str(cm.exception))

    def test_open_is_fail_closed_when_quota_check_breaks(self):
        sale = self._sale(start=timezone.now() - timedelta(minutes=1))
        with patch(
            "subscriptions.services.limits.can_create_flash_sale",
            side_effect=RuntimeError("panne"),
        ):
            with self.assertRaises(SaleOpeningRefused):
                sale.open_sale()
        sale.refresh_from_db()
        self.assertEqual(sale.status, FlashSaleStatus.SCHEDULED)

    def test_detail_page_explains_why_sale_cannot_open(self):
        self._old_sales(3)
        clone = self._sale(start=timezone.now() + timedelta(hours=2))
        resp = self.client.get(reverse("flash_sales:detail", args=[clone.pk]))
        self.assertContains(resp, "ne peut pas s")
        self.assertContains(resp, "ventes ce mois-ci")
