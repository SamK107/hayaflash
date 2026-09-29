"""F-31 : quota mensuel, 3 ventes/jour (fuseau Africa/Bamako) et duree 2 h max,
sur les chemins de creation/modification (service, formulaire)."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.utils import timezone

from flash_sales.forms import FlashSaleForm
from flash_sales.models import FlashSale, FlashSaleStatus
from flash_sales.services.crud import create_flash_sale, update_flash_sale
from flash_sales.tests_rules import BAMAKO, RulesBase, _future_day, _set_plan
from subscriptions.models import Plan


class CreateQuotaTests(RulesBase):
    """Quota mensuel via create_flash_sale (chemin de creation standard)."""

    def _create(self, i):
        start = _future_day(2 + i) + timedelta(hours=10)  # un jour different a chaque fois
        return create_flash_sale(
            owner=self.seller,
            title=f"V{i}",
            start_time=start,
            end_time=start + timedelta(hours=1),
        )

    def _fill_then_refuse(self, limit):
        for i in range(limit):
            self._create(i)  # la derniere autorisee passe
        with self.assertRaises(ValidationError) as cm:
            self._create(limit)  # la suivante est refusee
        self.assertEqual(FlashSale.objects.count(), limit)
        return " ".join(cm.exception.messages)

    def test_free_limit_is_three(self):
        _set_plan(self.seller, Plan.FREE)
        msg = self._fill_then_refuse(3)
        self.assertIn("3/3 ventes ce mois-ci", msg)

    def test_medium_limit_is_ten(self):
        _set_plan(self.seller, Plan.MEDIUM)
        self._fill_then_refuse(10)

    def test_pro_is_never_blocked(self):
        _set_plan(self.seller, Plan.PRO)
        for i in range(12):
            self._create(i)
        self.assertEqual(FlashSale.objects.count(), 12)

    def test_expired_pro_falls_back_to_free_quota(self):
        _set_plan(self.seller, Plan.PRO, expired=True)
        self._fill_then_refuse(3)

    def test_cancelled_sale_frees_a_slot(self):
        _set_plan(self.seller, Plan.FREE)
        first = self._create(0)
        self._create(1)
        self._create(2)
        first.status = FlashSaleStatus.CANCELLED
        first.save()
        self._create(3)  # passe

    def test_quota_check_failure_is_fail_closed(self):
        with patch(
            "subscriptions.services.limits.can_create_flash_sale",
            side_effect=RuntimeError("panne"),
        ):
            with self.assertRaises(ValidationError) as cm:
                self._create(0)
        self.assertIn(
            "Impossible de vérifier votre quota", " ".join(cm.exception.messages)
        )
        self.assertEqual(FlashSale.objects.count(), 0)


class DailyLimitTests(RulesBase):
    def setUp(self):
        super().setUp()
        _set_plan(self.seller, Plan.PRO)  # isole la regle 3/jour du quota

    def _create_at(self, start, minutes=60):
        return create_flash_sale(
            owner=self.seller,
            title="V",
            start_time=start,
            end_time=start + timedelta(minutes=minutes),
        )

    def test_third_passes_fourth_refused_next_day_passes(self):
        day = _future_day()
        for h in (8, 10, 12):
            self._create_at(day + timedelta(hours=h))  # la 3e passe
        with self.assertRaises(ValidationError) as cm:
            self._create_at(day + timedelta(hours=15))
        self.assertIn(
            "Maximum 3 ventes flash par jour", " ".join(cm.exception.messages)
        )
        self._create_at(day + timedelta(days=1, hours=8))  # le lendemain passe

    def test_midnight_boundary_africa_bamako(self):
        day = _future_day()
        # 3 ventes en toute fin de journee D : 23:00, 23:20, 23:50 (Bamako)
        for hh, mm in ((23, 0), (23, 20), (23, 50)):
            self._create_at(day.replace(hour=hh, minute=mm), minutes=10)
        # 00:00 le lendemain : autre jour, passe
        self._create_at(day + timedelta(days=1))
        # mais une 4e vente le jour D (23:40) est refusee
        with self.assertRaises(ValidationError):
            self._create_at(day.replace(hour=23, minute=40), minutes=5)

    def test_day_is_local_bamako(self):
        day = _future_day()
        for h in (1, 2, 3):
            self._create_at(day + timedelta(hours=h))
        with self.assertRaises(ValidationError):
            self._create_at(
                datetime(day.year, day.month, day.day, 20, 0, tzinfo=BAMAKO)
            )

    def test_completed_counts_cancelled_does_not(self):
        day = _future_day()
        self._sale(start=day + timedelta(hours=8), status=FlashSaleStatus.COMPLETED)
        self._sale(start=day + timedelta(hours=10), status=FlashSaleStatus.COMPLETED)
        self._sale(start=day + timedelta(hours=12), status=FlashSaleStatus.CANCELLED)
        self._create_at(day + timedelta(hours=14))  # 3e « valable » : passe
        with self.assertRaises(ValidationError):
            self._create_at(day + timedelta(hours=16))

    def test_update_moving_to_a_full_day_is_refused(self):
        day = _future_day()
        for h in (8, 10, 12):
            self._create_at(day + timedelta(hours=h))
        other = self._create_at(day + timedelta(days=1, hours=8))
        with self.assertRaises(ValidationError):
            update_flash_sale(
                sale=other,
                seller=self.seller,
                start_time=day + timedelta(hours=15),
                end_time=day + timedelta(hours=16),
            )
        # rester sur son propre jour (exclusion de soi) est autorise
        update_flash_sale(
            sale=other,
            seller=self.seller,
            title="Renommee",
            start_time=other.start_time,
            end_time=other.end_time,
        )

    def test_form_enforces_daily_limit(self):
        day = _future_day()
        for h in (8, 10, 12):
            self._create_at(day + timedelta(hours=h))
        data = {
            "title": "Vente",
            "duration_preset": "60",
            "start_time": (day + timedelta(hours=15)).strftime("%Y-%m-%dT%H:%M"),
            "delivery_zone": "Bamako",
            "category": "",
        }
        form = FlashSaleForm(data, seller=self.seller)
        self.assertFalse(form.is_valid())
        self.assertIn("start_time", form.errors)


class DurationTests(RulesBase):
    def setUp(self):
        super().setUp()
        _set_plan(self.seller, Plan.PRO)

    def _create(self, minutes, i=0):
        start = _future_day(3 + i) + timedelta(hours=9)
        return create_flash_sale(
            owner=self.seller,
            title="V",
            start_time=start,
            end_time=start + timedelta(minutes=minutes),
        )

    def test_exactly_two_hours_accepted(self):
        self._create(120)

    def test_two_hours_one_minute_refused(self):
        with self.assertRaises(ValidationError) as cm:
            self._create(121)
        self.assertIn("2 heures au maximum", " ".join(cm.exception.messages))
        self.assertEqual(FlashSale.objects.count(), 0)

    def test_update_refuses_more_than_two_hours(self):
        sale = self._create(60)
        with self.assertRaises(ValidationError):
            update_flash_sale(
                sale=sale,
                seller=self.seller,
                start_time=sale.start_time,
                end_time=sale.start_time + timedelta(minutes=121),
            )
        update_flash_sale(
            sale=sale,
            seller=self.seller,
            start_time=sale.start_time,
            end_time=sale.start_time + timedelta(minutes=120),
        )

    def test_form_custom_duration_120_ok_121_refused(self):
        base = {
            "title": "Vente",
            "duration_preset": "custom",
            "start_time": (timezone.now() + timedelta(days=3)).strftime(
                "%Y-%m-%dT%H:%M"
            ),
            "delivery_zone": "Bamako",
            "category": "",
        }
        ok = FlashSaleForm({**base, "custom_duration_minutes": "120"}, seller=self.seller)
        self.assertTrue(ok.is_valid(), ok.errors)
        ko = FlashSaleForm({**base, "custom_duration_minutes": "121"}, seller=self.seller)
        self.assertFalse(ko.is_valid())
