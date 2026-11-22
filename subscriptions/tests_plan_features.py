"""Non-régression des droits par plan (contrôle central plan_has_feature).

Chaque plan garde EXACTEMENT les droits qu'il avait avant l'introduction du contrôle
central (EXECUTION_V2 § 1 : aucun changement visible pour FREE, MEDIUM, PRO).
Les valeurs attendues ci-dessous sont celles de l'ancien code :
    has_stats          = (MEDIUM ou PRO) et non expiré
    has_advanced_stats = PRO et non expiré
    is_paid            = (MEDIUM ou PRO) et non expiré
BUSINESS n'existe pas encore : il doit être refusé partout (fail-closed).
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from accounts.models import SellerProfile
from subscriptions.models import Plan, Subscription
from subscriptions.services.plans import PLAN_FEATURES, plan_has_feature

User = get_user_model()

# Droits attendus, par plan, pour un abonnement NON expiré (ancien code).
EXPECTED_ACTIVE = {
    Plan.FREE: {"stats": False, "advanced_stats": False, "paid_subscription": False},
    Plan.MEDIUM: {"stats": True, "advanced_stats": False, "paid_subscription": True},
    Plan.PRO: {"stats": True, "advanced_stats": True, "paid_subscription": True},
}


class PlanHasFeatureMatrixTests(SimpleTestCase):
    def test_matrix_is_exactly_the_historical_rights(self):
        self.assertEqual(PLAN_FEATURES["stats"], frozenset({Plan.MEDIUM, Plan.PRO}))
        self.assertEqual(PLAN_FEATURES["advanced_stats"], frozenset({Plan.PRO}))
        self.assertEqual(PLAN_FEATURES["paid_subscription"], frozenset({Plan.MEDIUM, Plan.PRO}))

    def test_every_plan_keeps_its_rights(self):
        for plan, expected in EXPECTED_ACTIVE.items():
            for feature, value in expected.items():
                with self.subTest(plan=plan, feature=feature):
                    self.assertIs(plan_has_feature(plan, feature), value)

    def test_plan_given_as_plain_string_works(self):
        self.assertTrue(plan_has_feature("pro", "advanced_stats"))
        self.assertFalse(plan_has_feature("medium", "advanced_stats"))
        self.assertFalse(plan_has_feature("free", "stats"))

    def test_unknown_plan_is_refused_everywhere(self):
        # BUSINESS n'est pas ouvert : il ne doit donner aucun droit (fail-closed).
        for feature in PLAN_FEATURES:
            with self.subTest(feature=feature):
                self.assertFalse(plan_has_feature("business", feature))
                self.assertFalse(plan_has_feature("", feature))

    def test_unknown_feature_is_a_programming_error(self):
        with self.assertRaises(ValueError):
            plan_has_feature(Plan.PRO, "fonction_inexistante")


class SubscriptionRightsTests(TestCase):
    _counter = 0

    def _sub(self, plan, *, expired=False):
        SubscriptionRightsTests._counter += 1
        user = User.objects.create_user(
            phone=f"+2237{SubscriptionRightsTests._counter:07d}", password="x", display_name="V"
        )
        seller = SellerProfile.objects.create(user=user)
        expires = timezone.now() + (timedelta(days=-1) if expired else timedelta(days=30))
        return Subscription.objects.create(seller=seller, plan=plan, expires_at=expires)

    def test_active_plans_keep_their_rights(self):
        for plan, expected in EXPECTED_ACTIVE.items():
            sub = self._sub(plan)
            with self.subTest(plan=plan):
                self.assertIs(sub.has_stats, expected["stats"])
                self.assertIs(sub.has_advanced_stats, expected["advanced_stats"])
                self.assertIs(sub.is_paid, expected["paid_subscription"])

    def test_expired_paid_plans_fall_back_to_free_rights(self):
        for plan in (Plan.MEDIUM, Plan.PRO):
            sub = self._sub(plan, expired=True)
            with self.subTest(plan=plan):
                self.assertEqual(sub.current_plan, Plan.FREE)
                self.assertFalse(sub.has_stats)
                self.assertFalse(sub.has_advanced_stats)
                self.assertFalse(sub.is_paid)

    def test_free_has_no_paid_right(self):
        sub = self._sub(Plan.FREE)
        self.assertEqual(sub.current_plan, Plan.FREE)
        self.assertFalse(sub.has_stats or sub.has_advanced_stats or sub.is_paid)

    def test_identity_helpers_for_display_are_unchanged(self):
        # is_pro / is_medium restent des identités de palier pour l'affichage.
        self.assertTrue(self._sub(Plan.PRO).is_pro)
        self.assertFalse(self._sub(Plan.PRO, expired=True).is_pro)
        self.assertTrue(self._sub(Plan.MEDIUM).is_medium)
        self.assertFalse(self._sub(Plan.MEDIUM).is_pro)


class PaymentEligibilityTests(SimpleTestCase):
    """Seuls les plans payants sont achetables : FREE et plan inconnu sont refusés."""

    def test_only_paid_plans_pass_the_purchase_check(self):
        self.assertTrue(plan_has_feature(Plan.MEDIUM, "paid_subscription"))
        self.assertTrue(plan_has_feature(Plan.PRO, "paid_subscription"))
        self.assertFalse(plan_has_feature(Plan.FREE, "paid_subscription"))
        self.assertFalse(plan_has_feature("business", "paid_subscription"))
