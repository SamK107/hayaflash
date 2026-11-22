"""Migration partners 0004 (grossiste rattaché) : les lignes existantes restent valides.

Vérifie, sur de vraies lignes de vendeuses créées au schéma 0003, que 0004 s'applique sans
perte, que chaque ligne existante satisfait la contrainte « exactement une cible », et que la
migration se réverse tant qu'aucune attribution grossiste n'existe.
"""

from __future__ import annotations

from datetime import date

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

FROM = [("partners", "0003_lettre_essai_libelles")]
TO = [("partners", "0004_referral_grossiste")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    executor.loader.build_graph()
    return executor.loader.project_state(targets).apps


class ReferralGrossisteMigrationTests(TransactionTestCase):
    def setUp(self):
        apps_before = _migrate(FROM)
        User = apps_before.get_model("accounts", "User")
        SellerProfile = apps_before.get_model("accounts", "SellerProfile")
        Partner = apps_before.get_model("partners", "Partner")
        Referral = apps_before.get_model("partners", "Referral")

        partner = Partner.objects.create(
            name="Awa", phone="+22360000001", code="AWA2026",
            contract_start=date(2026, 1, 1), contract_end=date(2027, 1, 1),
        )
        self.seller_ids = []
        for n in range(3):
            user = User.objects.create(phone=f"+2237000010{n}", display_name=f"V{n}", password="x")
            seller = SellerProfile.objects.create(
                user=user, business_name=f"Boutique {n}", public_slug=f"boutique-{n}",
                seller_code=f"VEN{n:03d}"
            )
            self.seller_ids.append(seller.pk)
            Referral.objects.create(partner=partner, seller=seller)
        self.partner_id = partner.pk

    def tearDown(self):
        _migrate(_latest_targets())

    def test_forward_keeps_existing_seller_rows_valid(self):
        apps = _migrate(TO)
        Referral = apps.get_model("partners", "Referral")

        rows = list(Referral.objects.order_by("pk"))
        self.assertEqual(len(rows), 3)
        self.assertEqual([r.seller_id for r in rows], self.seller_ids)
        self.assertTrue(all(r.distributor_id is None for r in rows))
        self.assertTrue(all(r.partner_id == self.partner_id for r in rows))

    def test_constraints_exist_after_forward(self):
        apps = _migrate(TO)
        Referral = apps.get_model("partners", "Referral")
        Partner = apps.get_model("partners", "Partner")
        partner = Partner.objects.get(pk=self.partner_id)

        with self.assertRaises(IntegrityError), transaction.atomic():
            Referral.objects.create(partner=partner)  # aucune cible
        with self.assertRaises(IntegrityError), transaction.atomic():
            Referral.objects.create(partner=partner, seller_id=self.seller_ids[0])  # vendeuse en double

    def test_reverse_succeeds_while_no_distributor_row(self):
        _migrate(TO)
        apps = _migrate(FROM)
        Referral = apps.get_model("partners", "Referral")
        self.assertEqual(Referral.objects.count(), 3)


def _latest_targets():
    executor = MigrationExecutor(connection)
    return executor.loader.graph.leaf_nodes()
