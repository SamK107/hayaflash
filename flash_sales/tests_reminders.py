"""F-81 bloc 5 : reminded_at n'est pose que si le SMS est reellement parti ; plafond de tentatives."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus, SaleInterest
from flash_sales.tasks import MAX_REMINDER_ATTEMPTS, send_pending_sale_reminders
from notifications.models import Notification

User = get_user_model()
SMS = "notifications.services.sms.send_sms"


class ReminderReliabilityTests(TestCase):
    def setUp(self) -> None:
        user = User.objects.create_user(phone="+22300000060", password="x", display_name="S")
        self.seller = SellerProfile.objects.create(user=user)
        now = timezone.now()
        self.sale = FlashSale.objects.create(
            owner=self.seller, title="Vente rappel",
            start_time=now + timedelta(minutes=30),
            end_time=now + timedelta(hours=2),
            status=FlashSaleStatus.SCHEDULED,
        )
        self.interest = SaleInterest.objects.create(flash_sale=self.sale, phone="+22399990001")

    def _run(self, **sms_kwargs) -> None:
        with patch(SMS, **sms_kwargs):
            send_pending_sale_reminders()
        self.interest.refresh_from_db()

    def test_success_sets_reminded_at(self) -> None:
        self._run(return_value=True)
        self.assertIsNotNone(self.interest.reminded_at)
        self.assertEqual(Notification.objects.get().status, Notification.Status.SENT)

    def test_failure_does_not_set_reminded_at(self) -> None:
        self._run(return_value=False)
        self.assertIsNone(self.interest.reminded_at)
        self.assertEqual(Notification.objects.get().status, Notification.Status.FAILED)

    def test_exception_in_sms_does_not_set_reminded_at(self) -> None:
        self._run(side_effect=RuntimeError("passerelle HS"))
        self.assertIsNone(self.interest.reminded_at)
        self.assertEqual(Notification.objects.get().status, Notification.Status.FAILED)

    def test_failed_reminder_is_retried_on_next_tick_then_succeeds(self) -> None:
        self._run(return_value=False)
        self._run(return_value=False)
        self.assertIsNone(self.interest.reminded_at)
        self.assertEqual(Notification.objects.count(), 2)
        self._run(return_value=True)
        self.assertIsNotNone(self.interest.reminded_at)
        self.assertEqual(Notification.objects.filter(status=Notification.Status.SENT).count(), 1)

    def test_attempts_are_capped(self) -> None:
        for _ in range(MAX_REMINDER_ATTEMPTS + 3):
            self._run(return_value=False)
        self.assertEqual(Notification.objects.count(), MAX_REMINDER_ATTEMPTS)
        self.assertIsNone(self.interest.reminded_at)

    def test_cap_does_not_depend_on_other_numbers_or_sales(self) -> None:
        other = SaleInterest.objects.create(flash_sale=self.sale, phone="+22399990002")
        for _ in range(MAX_REMINDER_ATTEMPTS):
            self._run(return_value=False)
        # Un autre numero n'a pas ete bloque par les echecs du premier : il en a eu autant.
        self.assertEqual(Notification.objects.filter(recipient_phone=other.phone).count(), MAX_REMINDER_ATTEMPTS)
        # Une autre vente repart de zero pour le meme numero.
        now = timezone.now()
        sale2 = FlashSale.objects.create(
            owner=self.seller, title="Autre", start_time=now + timedelta(minutes=20),
            end_time=now + timedelta(hours=2), status=FlashSaleStatus.SCHEDULED,
        )
        fresh = SaleInterest.objects.create(flash_sale=sale2, phone="+22399990001")
        self._run(return_value=True)
        fresh.refresh_from_db()
        self.assertIsNotNone(fresh.reminded_at)

    def test_already_reminded_is_not_sent_again(self) -> None:
        self.interest.reminded_at = timezone.now()
        self.interest.save()
        self._run(return_value=True)
        self.assertEqual(Notification.objects.count(), 0)
