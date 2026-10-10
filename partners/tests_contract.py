"""BLOC D : contrat d'un an, places de fondateur, seuil trimestriel."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import AuditLog
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order, OrderStatus
from partners.models import Partner, Referral
from partners.services.contract import quarterly_status, release_slot
from partners.tests_models import make_partner, make_seller

START = date(2026, 1, 15)


def aware(d: date, hour=12) -> datetime:
    return datetime(d.year, d.month, d.day, hour, tzinfo=dt_timezone.utc)


class Base(TestCase):
    def setUp(self):
        self.partner = make_partner(contract_start=START)
        self._n = 0

    def referral(self, *, flagged=False, phone=None):
        self._n += 1
        seller = make_seller(phone or f"+223701100{self._n:02d}")
        return Referral.objects.create(partner=self.partner, seller=seller, flagged=flagged)

    def activate(self, referral, when: date, *, sale_status=FlashSaleStatus.CLOSED, order_status=OrderStatus.CONFIRMED):
        """Une vente non annulée avec une commande non annulée, à la date donnée."""
        sale = FlashSale.objects.create(
            owner=referral.seller,
            title="Vente",
            start_time=aware(when) - timedelta(hours=2),
            end_time=aware(when) + timedelta(hours=2),
            status=sale_status,
        )
        order = Order.service_objects.create(
            flash_sale=sale, customer_name="Client", customer_phone="+22370000009"
        )
        Order.service_objects.filter(pk=order.pk).update(status=order_status, created_at=aware(when))
        return order

    def status(self, today):
        return quarterly_status(self.partner, today=today)


class ReferralEligibilityTests(Base):
    def test_new_referrals_only_while_active_and_inside_the_contract(self):
        self.assertEqual(self.partner.contract_end, date(2027, 1, 15))
        self.assertTrue(self.partner.accepts_new_referrals)
        for status in ("paused", "ended", "slot_released"):
            self.partner.status = status
            self.assertFalse(self.partner.accepts_new_referrals, status)

    def test_contract_boundary_is_inclusive(self):
        from unittest.mock import patch

        with patch("partners.models.today", return_value=date(2027, 1, 15)):
            self.assertTrue(self.partner.accepts_new_referrals)
        with patch("partners.models.today", return_value=date(2027, 1, 16)):
            self.assertFalse(self.partner.accepts_new_referrals)


class QuarterlyTests(Base):
    def test_first_quarter_is_never_missed(self):
        s = self.status(date(2026, 4, 14))  # dernier jour du T1, rien d'actif
        self.assertEqual(s["consecutive_missed"], 0)
        self.assertFalse(s["warning"])
        self.assertFalse(s["releasable"])
        self.assertEqual(s["quarters"][0]["missed"], False)

    def test_quarters_are_three_months_from_contract_start(self):
        s = self.status(date(2026, 4, 14))
        q = s["quarters"]
        self.assertEqual((q[0]["start"], q[0]["end"]), (date(2026, 1, 15), date(2026, 4, 15)))
        self.assertEqual((q[1]["start"], q[1]["end"]), (date(2026, 4, 15), date(2026, 7, 15)))
        self.assertEqual(len(q), 4)  # contrat d'un an

    def test_second_quarter_filled_by_a_seller_who_became_active_in_it(self):
        r = self.referral()
        self.activate(r, date(2026, 5, 1))
        s = self.status(date(2026, 7, 20))
        self.assertTrue(s["quarters"][1]["filled"])
        self.assertFalse(s["quarters"][1]["missed"])
        self.assertEqual(s["consecutive_missed"], 0)

    def test_second_quarter_missed_gives_a_warning(self):
        s = self.status(date(2026, 7, 20))
        self.assertTrue(s["quarters"][1]["missed"])
        self.assertEqual(s["consecutive_missed"], 1)
        self.assertTrue(s["warning"])
        self.assertFalse(s["releasable"])

    def test_two_consecutive_missed_quarters_make_the_slot_releasable(self):
        s = self.status(date(2026, 10, 20))  # T2 et T3 clos et manqués
        self.assertEqual(s["consecutive_missed"], 2)
        self.assertTrue(s["releasable"])

    def test_a_filled_quarter_resets_the_streak(self):
        r = self.referral()
        self.activate(r, date(2026, 8, 1))  # rempli T3
        s = self.status(date(2026, 10, 20))
        self.assertEqual([q["missed"] for q in s["quarters"][:3]], [False, True, False])
        self.assertEqual(s["consecutive_missed"], 0)

    def test_quarter_in_progress_is_not_judged(self):
        s = self.status(date(2026, 5, 1))  # T2 en cours
        self.assertFalse(s["quarters"][1]["closed"])
        self.assertFalse(s["quarters"][1]["missed"])
        self.assertEqual(s["consecutive_missed"], 0)

    def test_seller_never_active_does_not_fill(self):
        self.referral()  # inscrit, aucune vente
        self.assertTrue(self.status(date(2026, 7, 20))["quarters"][1]["missed"])

    def test_cancelled_sale_or_cancelled_orders_do_not_activate(self):
        r1, r2 = self.referral(), self.referral()
        self.activate(r1, date(2026, 5, 1), sale_status=FlashSaleStatus.CANCELLED)
        self.activate(r2, date(2026, 5, 2), order_status=OrderStatus.CANCELLED)
        self.assertTrue(self.status(date(2026, 7, 20))["quarters"][1]["missed"])

    def test_pending_order_counts_as_active_but_only_non_cancelled(self):
        r = self.referral()
        self.activate(r, date(2026, 5, 2), order_status=OrderStatus.PENDING)
        self.assertTrue(self.status(date(2026, 7, 20))["quarters"][1]["filled"])

    def test_flagged_referral_is_ignored(self):
        r = self.referral(flagged=True)
        self.activate(r, date(2026, 5, 1))
        self.assertTrue(self.status(date(2026, 7, 20))["quarters"][1]["missed"])

    def test_referral_with_the_partners_own_phone_is_ignored(self):
        r = self.referral(phone=self.partner.phone)
        self.activate(r, date(2026, 5, 1))
        self.assertTrue(self.status(date(2026, 7, 20))["quarters"][1]["missed"])

    def test_activity_date_is_the_first_qualifying_order(self):
        r = self.referral()
        self.activate(r, date(2026, 8, 1))
        self.activate(r, date(2026, 5, 1))  # la plus ancienne compte : T2, pas T3
        q = self.status(date(2026, 10, 20))["quarters"]
        self.assertTrue(q[1]["filled"])
        self.assertFalse(q[2]["filled"])

    def test_activation_before_contract_start_fills_nothing(self):
        r = self.referral()
        self.activate(r, date(2025, 12, 1))
        self.assertTrue(self.status(date(2026, 7, 20))["quarters"][1]["missed"])


class ReleaseSlotTests(Base):
    def make_founder(self):
        Partner.objects.filter(pk=self.partner.pk).update(is_founder=True)
        self.partner.refresh_from_db()

    def test_refused_when_threshold_not_reached(self):
        self.make_founder()
        with self.assertRaises(ValidationError) as ctx:
            release_slot(self.partner, today=date(2026, 7, 20))  # 1 seul manqué
        self.assertIn("seuil", " ".join(ctx.exception.messages))
        self.partner.refresh_from_db()
        self.assertEqual(self.partner.status, "active")
        self.assertFalse(AuditLog.objects.filter(action="partner.slot_released").exists())

    def test_released_when_two_consecutive_quarters_missed(self):
        self.make_founder()
        release_slot(self.partner, today=date(2026, 10, 20))
        self.partner.refresh_from_db()
        self.assertEqual(self.partner.status, "slot_released")
        log = AuditLog.objects.get(action="partner.slot_released")
        self.assertEqual(log.entity_id, self.partner.pk)

    def test_released_slot_no_longer_counts_for_the_twenty(self):
        for i in range(19):
            make_partner(code=f"FND{i:03d}", phone=f"+2236100{i:04d}", is_founder=True)
        self.make_founder()  # 20e
        with self.assertRaises(ValidationError):
            make_partner(code="FND900", phone="+223619999900", is_founder=True)
        release_slot(self.partner, today=date(2026, 10, 20))
        make_partner(code="FND901", phone="+223619999901", is_founder=True)

    def test_acquired_commission_rights_survive_release(self):
        from partners.services.commissions import record_for_payment
        from partners.tests_commissions import pay

        r = self.referral()
        self.make_founder()
        release_slot(self.partner, today=date(2026, 10, 20))
        self.assertIsNotNone(record_for_payment(pay(r.seller)))

    def test_non_founder_can_be_released_too(self):
        release_slot(self.partner, today=date(2026, 10, 20))
        self.partner.refresh_from_db()
        self.assertEqual(self.partner.status, "slot_released")

    def test_already_released_is_refused(self):
        release_slot(self.partner, today=date(2026, 10, 20))
        with self.assertRaises(ValidationError):
            release_slot(self.partner, today=date(2026, 10, 20))
