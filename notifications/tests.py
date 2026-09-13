from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from notifications.models import Notification
from notifications.services.dispatcher import send_notification

User = get_user_model()


class SendNotificationDispatcherTest(TestCase):
    """Tests de notifications.services.dispatcher.send_notification()."""

    def test_sms_channel_creates_notification_and_calls_send_sms(self) -> None:
        with patch("notifications.services.sms.send_sms", return_value=True) as mock_sms:
            notif = send_notification(
                recipient_phone="+22300000001",
                message="Test SMS",
                channel=Notification.Channel.SMS,
            )

        mock_sms.assert_called_once_with("+22300000001", "Test SMS")
        self.assertEqual(notif.status, Notification.Status.SENT)
        self.assertIsNotNone(notif.sent_at)

    def test_sms_failure_marks_notification_failed(self) -> None:
        with patch("notifications.services.sms.send_sms", return_value=False):
            notif = send_notification(
                recipient_phone="+22300000002",
                message="Test SMS echoue",
                channel=Notification.Channel.SMS,
            )

        self.assertEqual(notif.status, Notification.Status.FAILED)
        self.assertIsNone(notif.sent_at)

    def test_sms_exception_marks_notification_failed_with_error_message(self) -> None:
        with patch(
            "notifications.services.sms.send_sms",
            side_effect=RuntimeError("gateway down"),
        ):
            notif = send_notification(
                recipient_phone="+22300000003",
                message="Test exception",
                channel=Notification.Channel.SMS,
            )

        self.assertEqual(notif.status, Notification.Status.FAILED)
        self.assertIn("gateway down", notif.error_message)

    def test_whatsapp_channel_v1_logs_only_and_marks_sent(self) -> None:
        """V1 : WhatsApp est un log uniquement (le lien wa.me est utilise cote client)."""
        notif = send_notification(
            recipient_phone="+22300000004",
            message="Test WhatsApp",
            channel=Notification.Channel.WHATSAPP,
        )
        self.assertEqual(notif.status, Notification.Status.SENT)

    def test_unknown_channel_marks_notification_failed(self) -> None:
        notif = send_notification(
            recipient_phone="+22300000005",
            message="Test canal inconnu",
            channel="carrier-pigeon",
        )
        self.assertEqual(notif.status, Notification.Status.FAILED)


class NotificationTasksTest(TestCase):
    """Tests des taches Celery notifications (CELERY_TASK_ALWAYS_EAGER=True en test)."""

    def setUp(self) -> None:
        self.seller_user = User.objects.create_user(
            phone="+22300000010", password="x", display_name="SellerNotif"
        )
        self.seller = SellerProfile.objects.create(user=self.seller_user)

    def test_send_sale_reminder_creates_sms_notification(self) -> None:
        from notifications.tasks import send_sale_reminder

        now = timezone.now()
        sale = FlashSale.objects.create(
            owner=self.seller,
            title="Vente notif",
            start_time=now,
            end_time=now + timedelta(hours=1),
            status=FlashSaleStatus.SCHEDULED,
        )
        send_sale_reminder(sale.pk, "+22300000099")

        self.assertTrue(
            Notification.objects.filter(recipient_phone="+22300000099").exists()
        )

    def test_send_sale_reminder_missing_sale_does_not_raise(self) -> None:
        from notifications.tasks import send_sale_reminder

        # Ne doit pas lever — juste logger un warning et ne rien envoyer.
        send_sale_reminder(999999, "+22300000098")
        self.assertFalse(
            Notification.objects.filter(recipient_phone="+22300000098").exists()
        )

    def test_send_order_confirmation_missing_order_does_not_raise(self) -> None:
        from notifications.tasks import send_order_confirmation

        send_order_confirmation(999999)
        self.assertEqual(Notification.objects.count(), 0)
