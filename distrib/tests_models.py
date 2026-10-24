"""P1 : modeles, contraintes, interrupteur (spec §4, §7, §15.9)."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from accounts.models import SellerProfile
from distrib import models as m

User = get_user_model()


def make_distributor(phone="+22371000001", name="Gros Bamako", **extra):
    user = User.objects.create_user(phone=phone, password="x", display_name=name)
    return m.Distributor.objects.create(user=user, business_name=name, **extra)


def make_seller(phone="+22370000001", name="Awa"):
    user = User.objects.create_user(phone=phone, password="x", display_name=name)
    return SellerProfile.objects.create(user=user, business_name=f"Boutique {name}")


class DistributorDefaultsTests(TestCase):
    def test_defaults_follow_the_spec(self):
        d = make_distributor()
        self.assertEqual(d.commission_rate, Decimal("6"))
        self.assertEqual(d.commission_min, Decimal("250"))
        self.assertEqual(d.commission_max, Decimal("1500"))
        self.assertEqual(d.credit_ceiling, Decimal("10000"))
        self.assertEqual(d.reseller_credit_ceiling, Decimal("10000"))
        self.assertEqual(d.payout_delay_days, 3)
        self.assertEqual(d.auto_confirm_hours, 72)
        self.assertTrue(d.is_active)
        self.assertFalse(d.is_suspended)
        self.assertIsNone(d.pilot_until)

    def test_amounts_are_whole_fcfa(self):
        fields = [
            m.Distributor._meta.get_field(n)
            for n in ("commission_min", "commission_max", "credit_ceiling", "reseller_credit_ceiling")
        ] + [
            m.WholesaleProduct._meta.get_field("wholesale_price"),
            m.WholesaleProduct._meta.get_field("min_retail_price"),
            m.DistribSettlement._meta.get_field("sale_amount"),
            m.DistribSettlement._meta.get_field("reseller_margin"),
            m.DistribSettlement._meta.get_field("commission_amount"),
            m.DistribStatement._meta.get_field("amount"),
            m.ResellerPayout._meta.get_field("amount"),
            m.DistribPayment._meta.get_field("amount"),
        ]
        for f in fields:
            self.assertEqual(f.decimal_places, 0, f.name)

    def test_one_distributor_per_user(self):
        d = make_distributor()
        with self.assertRaises(IntegrityError), transaction.atomic():
            m.Distributor.objects.create(user=d.user, business_name="Doublon")


class InviteConstraintTests(TestCase):
    def test_phone_is_unique_per_distributor_only(self):
        a, b = make_distributor(), make_distributor("+22371000002", "Autre gros")
        m.ResellerInvite.objects.create(distributor=a, display_name="Awa", phone="+22370000001")
        m.ResellerInvite.objects.create(distributor=b, display_name="Awa", phone="+22370000001")
        with self.assertRaises(IntegrityError), transaction.atomic():
            m.ResellerInvite.objects.create(distributor=a, display_name="Awa bis", phone="+22370000001")

    def test_new_invite_is_invited_without_seller(self):
        inv = m.ResellerInvite.objects.create(
            distributor=make_distributor(), display_name="Awa", phone="+22370000001"
        )
        self.assertEqual(inv.status, m.ResellerInvite.Status.INVITED)
        self.assertIsNone(inv.seller)
        self.assertIsNone(inv.answered_at)


class SettlementModelTests(TestCase):
    """Champs de l'Avenant A (§15.9) et unicites."""

    def test_settlement_fields_exist(self):
        names = {f.name for f in m.DistribSettlement._meta.get_fields()}
        for expected in (
            "not_delivered_reason", "not_delivered_note", "declared_by", "declared_at",
            "confirmation_source", "confirmed_at", "auto_confirm_at", "statement", "payout",
            "receipt_token", "receipt_code", "customer_confirmed_at", "customer_om_reference",
            "commission_billable", "conflict_flag", "paid_confirmed_at", "paid_confirmed_by",
        ):
            self.assertIn(expected, names)
        statuses = {v for v, _ in m.DistribSettlement.Status.choices}
        self.assertEqual(
            statuses,
            {"ordered", "in_delivery", "delivered_by_shop", "paid_confirmed", "cancelled", "not_delivered"},
        )

    def test_receipt_token_is_long_and_unique(self):
        t1, t2 = m.generate_receipt_token(), m.generate_receipt_token()
        self.assertGreaterEqual(len(t1), 22)
        self.assertNotEqual(t1, t2)
        self.assertTrue(m.DistribSettlement._meta.get_field("receipt_token").unique)

    def test_statement_and_payout_uniqueness_declared(self):
        names = {c.name for c in m.DistribStatement._meta.constraints}
        self.assertIn("distrib_statement_unique_period", names)
        names = {c.name for c in m.ResellerPayout._meta.constraints}
        self.assertIn("distrib_payout_unique_attempt", names)
        names = {c.name for c in m.DistribSettlement._meta.constraints}
        self.assertIn("distrib_settlement_unique_item", names)

    def test_statuses_of_statements_and_payouts(self):
        self.assertEqual(
            {v for v, _ in m.DistribStatement.Status.choices},
            {"to_pay", "paid", "accepted", "contested", "escalated"},
        )
        self.assertEqual(
            {v for v, _ in m.ResellerPayout.Status.choices}, {"declared", "accepted", "contested"}
        )

    def test_correction_author_is_nullable_for_the_system(self):
        self.assertTrue(m.DistribCorrection._meta.get_field("author").null)


class FeatureSwitchTests(TestCase):
    def setUp(self):
        self.distributor = make_distributor()

    def test_switch_is_off_by_default(self):
        from django.conf import settings

        self.assertFalse(settings.DISTRIB_ENABLED)

    def test_urls_are_404_when_off_even_for_the_distributor(self):
        self.client.force_login(self.distributor.user)
        self.assertEqual(self.client.get("/distrib/").status_code, 404)

    @override_settings(DISTRIB_ENABLED=True)
    def test_urls_work_when_on(self):
        self.client.force_login(self.distributor.user)
        resp = self.client.get("/distrib/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Gros Bamako")

    @override_settings(DISTRIB_ENABLED=True)
    def test_anonymous_goes_to_the_dedicated_login_entry(self):
        resp = self.client.get("/distrib/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith("/distrib/connexion/"))

    @override_settings(DISTRIB_ENABLED=True)
    def test_user_without_distributor_is_forbidden(self):
        self.client.force_login(make_seller().user)
        self.assertEqual(self.client.get("/distrib/").status_code, 403)

    @override_settings(DISTRIB_ENABLED=True)
    def test_inactive_distributor_is_forbidden(self):
        self.distributor.is_active = False
        self.distributor.save()
        self.client.force_login(self.distributor.user)
        self.assertEqual(self.client.get("/distrib/").status_code, 403)
