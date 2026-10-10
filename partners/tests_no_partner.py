"""Sans aucun partenaire en base, le comportement des vendeurs existants est inchangé.

Preuves complémentaires de tests déjà présents :
- inscription sans code : core/tests_register_security.py, partners/tests_attribution.py
  (test_signup_without_code_is_unchanged, test_attribution_failure_never_breaks_signup) ;
- crochet de paiement : partners/tests_commissions.py::ActivationHookTests ;
- limites de débit : core/tests_auth_rate_limit.py, core/tests_register_security.py.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import DatabaseError, connection
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from core.services import rate_limit
from core.tests_register_security import payload
from partners.models import CommissionEntry, Partner, PartnerClick, Referral
from partners.tests_commissions import pay
from subscriptions.models import PaymentStatus, Plan, Subscription
from subscriptions.services.payment import activate_subscription_from_payment

User = get_user_model()


class NoPartnerBase(TestCase):
    def setUp(self):
        cache.clear()
        self.assertEqual(Partner.objects.count(), 0)


class RegistrationWithoutPartnersTests(NoPartnerBase):
    def register(self, phone, **extra):
        return self.client.post(reverse("register"), payload(phone=phone, **extra))

    def test_registration_is_identical_with_no_code_an_unknown_code_or_a_stale_cookie(self):
        results = []
        for i, code in enumerate(("", "INCONNU1", "AB")):
            resp = self.register(f"+2237000050{i}", partner_code=code)
            results.append((resp.status_code, resp["Location"]))
            self.client.logout()
        self.client.cookies["hf_ref"] = "FANTOME1"
        resp = self.register("+22370000509")
        results.append((resp.status_code, resp["Location"]))
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(results[0], (302, reverse("seller_home")))
        self.assertEqual(SellerProfile.objects.count(), 4)
        self.assertEqual((Referral.objects.count(), PartnerClick.objects.count()), (0, 0))

    def test_the_partner_code_field_is_optional(self):
        data = payload(phone="+22370000510")
        data.pop("partner_code", None)
        self.assertEqual(self.client.post(reverse("register"), data).status_code, 302)

    @override_settings(RATELIMIT_ENABLE=True, RATELIMIT_REGISTER_IP=(2, 3600))
    def test_register_ip_limit_still_applies(self):
        codes = []
        for i in range(3):
            codes.append(self.register(f"+2237000052{i}").status_code)
            self.client.logout()  # sinon la 2e requête est redirigée comme déjà connectée
        self.assertEqual(codes, [302, 302, 429])

    def test_the_referral_link_limit_never_consumes_the_login_or_register_quota(self):
        request = RequestFactory().get("/", REMOTE_ADDR="196.200.1.1")
        with override_settings(RATELIMIT_ENABLE=True, RATELIMIT_REFERRAL_IP=(2, 60)):
            for _ in range(5):
                rate_limit.referral_ip_limited(request)
            self.assertTrue(rate_limit.referral_ip_limited(request))
            self.assertFalse(rate_limit.login_ip_limited(request))
            self.assertFalse(rate_limit.register_ip_limited(request))


class ActivationWithoutPartnersTests(NoPartnerBase):
    def setUp(self):
        super().setUp()
        user = User.objects.create_user(phone="+22370000600", password="x", display_name="V")
        self.seller = SellerProfile.objects.create(user=user)
        Subscription.objects.get_or_create(seller=self.seller)

    def pending(self):
        return pay(self.seller, status=PaymentStatus.PENDING)

    def assertActivated(self, payment):
        sub = Subscription.objects.get(seller=self.seller)
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(sub.plan, Plan.MEDIUM)
        self.assertGreater(sub.expires_at, timezone.now() + timedelta(days=20))

    def test_activation_works_and_creates_no_commission(self):
        payment = self.pending()
        activate_subscription_from_payment(payment)
        self.assertActivated(payment)
        self.assertEqual(CommissionEntry.objects.count(), 0)

    def test_the_hook_costs_at_most_three_queries_for_a_seller_without_a_link(self):
        def fresh(n):
            user = User.objects.create_user(phone=f"+2237000070{n}", password="x", display_name=f"V{n}")
            seller = SellerProfile.objects.create(user=user)
            Subscription.objects.get_or_create(seller=seller)
            return pay(seller, status=PaymentStatus.PENDING)

        def measure(payment, *, hook):
            ctx = patch("subscriptions.services.payment._record_partner_commission") if not hook else patch(
                "subscriptions.services.payment.logger.info"
            )
            with ctx, CaptureQueriesContext(connection) as queries:
                activate_subscription_from_payment(payment)
            return len(queries)

        measure(fresh(0), hook=False)  # échauffement : caches et requêtes uniques
        without = measure(fresh(1), hook=False)
        with_hook = measure(fresh(2), hook=True)
        self.assertLessEqual(with_hook - without, 3)

    def test_activation_survives_a_broken_partners_module(self):
        payment = self.pending()
        with patch.dict(sys.modules, {"partners.services.commissions": None}):  # ImportError à l'import
            activate_subscription_from_payment(payment)
        self.assertActivated(payment)

    def test_activation_survives_a_database_error_in_the_hook(self):
        payment = self.pending()
        with patch("partners.models.Referral.objects.filter", side_effect=DatabaseError("panne")):
            activate_subscription_from_payment(payment)
        self.assertActivated(payment)

    def test_activation_survives_any_exception_in_the_hook(self):
        payment = self.pending()
        with patch("partners.services.commissions.record_for_payment", side_effect=RuntimeError("boom")):
            activate_subscription_from_payment(payment)
        self.assertActivated(payment)

    def test_a_replayed_activation_stays_idempotent(self):
        payment = self.pending()
        activate_subscription_from_payment(payment)
        first_end = Subscription.objects.get(seller=self.seller).expires_at
        activate_subscription_from_payment(payment)
        self.assertEqual(Subscription.objects.get(seller=self.seller).expires_at, first_end)
