"""Pages légales, liens de pied de page, acceptation des CGU à l'inscription."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import LegalAcceptance, LegalDocument

User = get_user_model()


class LegalAcceptanceModelTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            phone="+22370000001", password="pass-123456", display_name="Awa"
        )

    def test_create(self):
        acc = LegalAcceptance.objects.create(
            user=self.user,
            document=LegalDocument.CGU,
            version="2026-09",
            ip_address="10.0.0.1",
        )
        self.assertIsNotNone(acc.accepted_at)
        self.assertEqual(self.user.legal_acceptances.count(), 1)

    def test_str(self):
        acc = LegalAcceptance.objects.create(
            user=self.user, document=LegalDocument.PRIVACY, version="2026-09"
        )
        text = str(acc)
        self.assertIn("privacy", text)
        self.assertIn("v2026-09", text)

    def test_ordering_most_recent_first(self):
        now = timezone.now()
        old = LegalAcceptance.objects.create(
            user=self.user,
            document=LegalDocument.CGU,
            version="2026-01",
            accepted_at=now - timedelta(days=30),
        )
        new = LegalAcceptance.objects.create(
            user=self.user, document=LegalDocument.CGU, version="2026-09", accepted_at=now
        )
        self.assertEqual(list(LegalAcceptance.objects.all()), [new, old])
