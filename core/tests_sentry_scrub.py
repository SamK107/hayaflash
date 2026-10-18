"""Filtre Sentry : aucun telephone ni e-mail ne doit partir vers Sentry."""

from django.test import SimpleTestCase

from config.settings._sentry import before_breadcrumb, before_send, scrub_text


class ScrubTextTests(SimpleTestCase):
    def test_masque_les_numeros_internationaux(self):
        for raw in ("+22370123456", "+223 70 12 34 56", "00223 70123456", "+33 6 12 34 56 78"):
            out = scrub_text(f"client {raw} introuvable")
            self.assertNotIn("70 12", out)
            self.assertNotIn("70123456", out)
            self.assertIn("[telephone]", out, raw)

    def test_masque_les_numeros_nationaux_a_8_chiffres(self):
        for raw in ("70123456", "70 12 34 56", "70.12.34.56"):
            self.assertEqual(scrub_text(f"tel {raw}."), "tel [telephone].", raw)

    def test_masque_les_emails(self):
        self.assertEqual(scrub_text("write a.b+c@mail.example.org now"), "write [email] now")

    def test_ne_touche_pas_dates_ni_identifiants(self):
        self.assertEqual(scrub_text("2026-10-18 12:30:45"), "2026-10-18 12:30:45")
        self.assertEqual(scrub_text("order HF-M-a1b2c3d4"), "order HF-M-a1b2c3d4")
        self.assertEqual(scrub_text("1234567"), "1234567")


class BeforeSendTests(SimpleTestCase):
    def test_masque_message_exception_et_breadcrumbs(self):
        event = {
            "message": "echec pour +223 70 12 34 56",
            "timestamp": "2026-10-18T10.20.30",
            "exception": {"values": [{"type": "ValueError", "value": "mail bob@example.com"}]},
            "breadcrumbs": {"values": [{"message": "POST 76123456", "category": "query"}]},
            "request": {"query_string": "phone=%2B22370123456&e=a@b.co"},
        }
        out = before_send(event, {})
        blob = repr(out)
        for leak in ("70 12 34 56", "bob@example.com", "76123456", "a@b.co"):
            self.assertNotIn(leak, blob)
        self.assertEqual(out["timestamp"], "2026-10-18T10.20.30")
        self.assertEqual(out["exception"]["values"][0]["type"], "ValueError")

    def test_breadcrumb_masque(self):
        crumb = before_breadcrumb({"message": "sms to +22370123456"}, {})
        self.assertNotIn("70123456", crumb["message"])
