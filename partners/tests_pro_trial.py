"""BLOC H7 : accès Pro offert 30 jours pendant l'essai, sans paiement Orange.

Mécanisme réutilisé (aucun nouveau modèle) : Subscription.plan = « pro » avec expires_at ;
un abonnement expiré retombe de lui-même sur le plan gratuit (is_pro faux). Aucune ligne
SubscriptionPayment n'est créée : ni le chiffre d'affaires ni les commissions ne le voient.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from core.models import AuditLog
from partners.models import CommissionEntry
from partners.services.trial import grant_pro_trial
from partners.tests_models import make_partner
from subscriptions.models import Plan, Subscription, SubscriptionPayment
from subscriptions.services.platform_reporting import revenue_payments

User = get_user_model()


class Base(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(phone="+22379000001", password="x", display_name="E", is_staff=True)
        self.client = Client()
        self.client.force_login(self.staff)
        self.partner = make_partner(
            code="ESSAI01", phone="+22370000555", phase="trial", trial_start=timezone.localdate(), accept=False
        )
        user = User.objects.create_user(phone="+22370000555", password="x", display_name="Awa")
        self.seller = SellerProfile.objects.create(user=user, business_name="Chez Awa")
        self.url = reverse("partners_offer_pro", args=[self.partner.pk])

    def sub(self):
        return Subscription.objects.get(seller=self.seller)


class GrantTests(Base):
    def test_grants_pro_for_thirty_days(self):
        resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 302)
        sub = self.sub()
        self.assertEqual(sub.plan, Plan.PRO)
        self.assertTrue(sub.is_pro)
        delta = sub.expires_at - timezone.now()
        self.assertTrue(timedelta(days=29, hours=23) < delta <= timedelta(days=30))

    def test_is_traced_with_the_reason(self):
        self.client.post(self.url)
        log = AuditLog.objects.get(action="partner.pro_trial_granted")
        self.assertEqual((log.entity_type, log.entity_id), ("SellerProfile", self.seller.pk))
        self.assertEqual(log.metadata["reason"], "essai partenaire")
        self.assertEqual(log.actor, self.staff)
        self.assertNotIn("70000555", str(log.metadata))

    def test_ends_by_itself_and_falls_back_to_free(self):
        grant_pro_trial(self.partner, self.staff)
        Subscription.objects.filter(seller=self.seller).update(expires_at=timezone.now() - timedelta(minutes=1))
        sub = self.sub()
        self.assertFalse(sub.is_pro)
        self.assertFalse(sub.is_paid)
        self.assertTrue(sub.is_free)

    def test_never_counted_as_a_payment_nor_as_revenue_nor_commission(self):
        self.client.post(self.url)
        self.assertEqual(SubscriptionPayment.objects.count(), 0)
        self.assertEqual(revenue_payments().count(), 0)
        self.assertEqual(CommissionEntry.objects.count(), 0)

    def test_second_grant_is_refused(self):
        self.client.post(self.url)
        first_end = self.sub().expires_at
        self.client.post(self.url)
        self.assertEqual(self.sub().expires_at, first_end)
        self.assertEqual(AuditLog.objects.filter(action="partner.pro_trial_granted").count(), 1)

    def test_no_second_grant_after_the_first_one_expired(self):
        grant_pro_trial(self.partner, self.staff)
        Subscription.objects.filter(seller=self.seller).update(expires_at=timezone.now() - timedelta(days=1))
        with self.assertRaises(Exception):
            grant_pro_trial(self.partner, self.staff)
        self.assertFalse(self.sub().is_pro)

    def test_refused_when_a_paid_subscription_is_active(self):
        Subscription.objects.create(
            seller=self.seller, plan=Plan.MEDIUM, expires_at=timezone.now() + timedelta(days=20)
        )
        self.client.post(self.url)
        sub = self.sub()
        self.assertEqual(sub.plan, Plan.MEDIUM)
        self.assertFalse(AuditLog.objects.filter(action="partner.pro_trial_granted").exists())

    def test_expired_paid_subscription_does_not_block(self):
        Subscription.objects.create(
            seller=self.seller, plan=Plan.MEDIUM, expires_at=timezone.now() - timedelta(days=2)
        )
        self.client.post(self.url)
        self.assertEqual(self.sub().plan, Plan.PRO)

    def test_refused_without_a_seller_account(self):
        other = make_partner(code="SANS001", phone="+22360099111", phase="trial",
                             trial_start=timezone.localdate(), accept=False)
        self.client.post(reverse("partners_offer_pro", args=[other.pk]))
        self.assertFalse(AuditLog.objects.filter(action="partner.pro_trial_granted").exists())

    def test_refused_outside_the_trial_phase(self):
        for phase in ("none", "contract", "ended"):
            p = make_partner(code=f"PH{phase.upper()[:4]}1", phone=f"+2237001{len(phase):04d}", phase=phase, accept=False)
            user = User.objects.create_user(phone=p.phone, password="x", display_name="X")
            seller = SellerProfile.objects.create(user=user)
            self.client.post(reverse("partners_offer_pro", args=[p.pk]))
            self.assertFalse(
                AuditLog.objects.filter(action="partner.pro_trial_granted", entity_id=seller.pk).exists(), phase
            )

    def test_staff_only_and_csrf(self):
        anon = Client().post(self.url)
        self.assertEqual(anon.status_code, 302)
        self.assertIn("login", anon["Location"])
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.staff)
        self.assertEqual(strict.post(self.url).status_code, 403)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertFalse(Subscription.objects.filter(seller=self.seller, plan=Plan.PRO).exists())

    def test_button_is_on_the_partner_page_with_confirmation(self):
        html = self.client.get(reverse("partners_detail", args=[self.partner.pk])).content.decode()
        self.assertIn("Offrir 30 jours de plan Pro", html)
        self.assertIn("data-hf-confirm", html)
