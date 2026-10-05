"""F-36 : aucun numéro de téléphone en clair dans les journaux.

Chemins couverts : SMS (succès, échec, non configuré), WhatsApp (journal seul),
rappels aux inscrits, OTP, inscription, webhook Orange Money. Ce qui est stocké
en base (Notification.recipient_phone) et le texte du SMS ne changent pas.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from core.services import rate_limit
from core.tests_register_security import PHONE as REGISTER_PHONE
from core.tests_register_security import payload
from flash_sales.models import FlashSale, FlashSaleStatus, SaleInterest
from flash_sales.tasks import send_pending_sale_reminders
from notifications.models import Notification
from notifications.services.dispatcher import send_notification

User = get_user_model()
PHONE = "+22377123456"
DIGITS = "77123456"


class NoPhoneInLogsCase(TestCase):
    """Capture tous les journaux (racine, niveau DEBUG) pendant le test."""

    def setUp(self):
        cache.clear()
        self._stream = StringIO()
        handler = logging.StreamHandler(self._stream)
        handler.setLevel(logging.DEBUG)
        root = logging.getLogger()
        self._old_level = root.level
        root.setLevel(logging.DEBUG)
        root.addHandler(handler)
        self._handler = handler
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        root = logging.getLogger()
        root.removeHandler(self._handler)
        root.setLevel(self._old_level)

    @property
    def logs(self) -> str:
        return self._stream.getvalue()

    def assertNoPhone(self, digits=DIGITS):
        self.assertNotIn(digits, self.logs)


class FingerprintHelperTests(TestCase):
    def test_fingerprint_is_stable_short_and_hides_number(self):
        fp = rate_limit.phone_fingerprint(PHONE)
        self.assertEqual(fp, rate_limit.phone_fingerprint(PHONE))
        self.assertNotIn(DIGITS, fp)
        self.assertNotEqual(fp, rate_limit.phone_fingerprint("+22377123457"))

    def test_fingerprint_matches_the_one_inside_rate_limit_keys(self):
        fp = rate_limit.phone_fingerprint(PHONE)
        self.assertTrue(rate_limit.phone_key("login", PHONE).endswith(fp.split(":")[-1]))

    def test_empty_phone_is_safe(self):
        self.assertTrue(rate_limit.phone_fingerprint(""))
        self.assertTrue(rate_limit.phone_fingerprint(None))


class SmsGatewayLogTests(NoPhoneInLogsCase):
    @override_settings(ORANGE_SMS_API_KEY="k", ORANGE_SMS_BASE_URL="https://sms.example")
    def test_success(self):
        from notifications.services.sms import send_sms

        with patch("notifications.services.sms.requests.post", return_value=MagicMock()) as post:
            self.assertTrue(send_sms(PHONE, "Bonjour"))
        # Le destinataire réel et le texte partent toujours à la passerelle.
        self.assertEqual(post.call_args.kwargs["json"], {"recipient": PHONE, "message": "Bonjour"})
        self.assertNoPhone()

    @override_settings(ORANGE_SMS_API_KEY="k", ORANGE_SMS_BASE_URL="https://sms.example")
    def test_failure_even_if_exception_text_contains_the_number(self):
        from notifications.services.sms import send_sms

        with patch(
            "notifications.services.sms.requests.post",
            side_effect=RuntimeError(f"echec pour {PHONE}"),
        ):
            self.assertFalse(send_sms(PHONE, "Bonjour"))
        self.assertIn("RuntimeError", self.logs)
        self.assertNoPhone()

    @override_settings(ORANGE_SMS_API_KEY="", ORANGE_SMS_BASE_URL="")
    def test_not_configured(self):
        from notifications.services.sms import send_sms

        self.assertFalse(send_sms(PHONE, "Bonjour"))
        self.assertIn("SMS non configure", self.logs)
        self.assertNoPhone()


class DispatcherLogTests(NoPhoneInLogsCase):
    def test_whatsapp_log_only_channel(self):
        notif = send_notification(
            recipient_phone=PHONE, message="Salut", channel=Notification.Channel.WHATSAPP
        )
        self.assertEqual(notif.recipient_phone, PHONE)  # stocké tel quel (sert à envoyer)
        self.assertNoPhone()

    @override_settings(ORANGE_SMS_API_KEY="", ORANGE_SMS_BASE_URL="")
    def test_sms_path_stores_number_but_not_in_logs(self):
        notif = send_notification(recipient_phone=PHONE, message="Salut")
        self.assertEqual(notif.recipient_phone, PHONE)
        self.assertNoPhone()


class ReminderLogTests(NoPhoneInLogsCase):
    def setUp(self):
        super().setUp()
        user = User.objects.create_user(phone="+22300000060", password="x", display_name="S")
        seller = SellerProfile.objects.create(user=user)
        now = timezone.now()
        sale = FlashSale.objects.create(
            owner=seller,
            title="Vente rappel",
            start_time=now + timedelta(minutes=30),
            end_time=now + timedelta(hours=2),
            status=FlashSaleStatus.SCHEDULED,
        )
        SaleInterest.objects.create(flash_sale=sale, phone=PHONE)

    def test_reminder_success(self):
        with patch("notifications.services.sms.send_sms", return_value=True):
            send_pending_sale_reminders()
        self.assertNoPhone()

    def test_reminder_failure_returned_false(self):
        with patch("notifications.services.sms.send_sms", return_value=False):
            send_pending_sale_reminders()
        self.assertNoPhone()

    def test_reminder_exception_text_containing_number(self):
        with patch(
            "notifications.tasks.send_sale_reminder",
            side_effect=RuntimeError(f"boom {PHONE}"),
        ):
            send_pending_sale_reminders()
        self.assertIn("Erreur envoi rappel", self.logs)
        self.assertNoPhone()


class OtpLogTests(NoPhoneInLogsCase):
    def test_send_otp_mock_sms_does_not_print_number(self):
        from accounts.services.otp import send_otp

        with patch("builtins.print") as printed:
            send_otp(PHONE)
        self.assertTrue(printed.called)
        for call in printed.call_args_list:
            self.assertNotIn(DIGITS, " ".join(str(a) for a in call.args))
        self.assertNoPhone()

    @override_settings(DEBUG=True)
    def test_lockout_logs_in_debug_do_not_leak_tail(self):
        from accounts.services.otp import send_otp, verify_phone_otp

        User.objects.create_user(phone=PHONE, password="x", display_name="C")
        with patch("builtins.print"):
            send_otp(PHONE)
        for _ in range(12):
            verify_phone_otp(PHONE, "000000")
        self.assertIn("OTP verify", self.logs)
        self.assertNoPhone()
        self.assertNotIn("tail=", self.logs)  # plus de fragment du numéro


class RegisterLogTests(NoPhoneInLogsCase):
    def test_registration_failure_path(self):
        with patch(
            "core.views.record_legal_acceptances",
            side_effect=RuntimeError(f"boom {REGISTER_PHONE}"),
        ):
            self.client.post(reverse("register"), payload())
        self.assertIn("Inscription echouee", self.logs)
        self.assertNoPhone(REGISTER_PHONE[-8:])

    def test_registration_success_path(self):
        with patch("builtins.print"):
            self.client.post(reverse("register"), payload())
        self.assertNoPhone(REGISTER_PHONE[-8:])


class OrangeWebhookLogTests(NoPhoneInLogsCase):
    def test_payload_without_token_is_not_logged_with_subscriber_number(self):
        body = {"subscribernumber": PHONE, "status": "SUCCESS"}
        for url in ("/billing/webhook/orange/", "/seller/abonnement/callback/"):
            self.client.post(url, data=body, content_type="application/json")
        self.assertNoPhone()
