"""Commande send_test_email : validation, envoi (locmem), echec propre."""

from __future__ import annotations

from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class SendTestEmailTests(SimpleTestCase):
    def test_sends_one_message_to_the_recipient(self):
        out = StringIO()
        call_command("send_test_email", "dest@example.com", stdout=out)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["dest@example.com"])
        self.assertIn("envoye", out.getvalue())

    def test_never_prints_credentials(self):
        with self.settings(EMAIL_HOST_PASSWORD="s3cret-value", EMAIL_HOST_USER="user-x"):
            out = StringIO()
            call_command("send_test_email", "dest@example.com", stdout=out)
        self.assertNotIn("s3cret-value", out.getvalue())

    def test_invalid_address_is_refused(self):
        with self.assertRaises(CommandError):
            call_command("send_test_email", "pas-une-adresse")
        self.assertEqual(len(mail.outbox), 0)

    def test_smtp_failure_gives_a_command_error(self):
        with mock.patch("core.management.commands.send_test_email.send_mail", side_effect=OSError("boom")):
            with self.assertRaisesRegex(CommandError, "Echec de l'envoi"):
                call_command("send_test_email", "dest@example.com")
