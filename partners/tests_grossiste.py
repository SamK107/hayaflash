"""Grossiste rattaché à un partenaire (D9) : contraintes, immuabilité, service, compteurs.

Aucune commission n'est calculée pour un grossiste : ces tests ne vérifient que le
rattachement et la protection des compteurs de vendeuses.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from core.models import AuditLog
from distrib.models import Distributor
from partners.models import CommissionEntry, Referral
from partners.services.distributor_attribution import (
    DistributorAttributionError,
    attribute_distributor,
    existing_partner_referral,
)
from partners.services.reporting import dashboard_stats, funnel
from partners.tests_models import make_partner, make_seller

User = get_user_model()


def make_distributor(phone="+22371000001", name="Gros Bamako"):
    user = User.objects.create_user(phone=phone, password="x", display_name=name)
    return Distributor.objects.create(user=user, business_name=name)


class ReferralCibleContrainteTests(TestCase):
    def setUp(self):
        self.partner = make_partner()
        self.seller = make_seller()
        self.gros = make_distributor()

    def test_une_seule_cible_vendeuse_seule_ou_grossiste_seul(self):
        Referral.objects.create(partner=self.partner, seller=self.seller)
        Referral.objects.create(partner=self.partner, distributor=self.gros)
        self.assertEqual(Referral.objects.count(), 2)

    def test_aucune_cible_refusee_par_la_base(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Referral.objects.create(partner=self.partner)

    def test_double_cible_refusee_par_la_base(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Referral.objects.create(partner=self.partner, seller=self.seller, distributor=self.gros)

    def test_un_grossiste_n_a_qu_une_attribution(self):
        Referral.objects.create(partner=self.partner, distributor=self.gros)
        other = make_partner(code="BOB2026", phone="+22360000003")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Referral.objects.create(partner=other, distributor=self.gros)

    def test_une_vendeuse_n_a_qu_un_parrain_toujours(self):
        Referral.objects.create(partner=self.partner, seller=self.seller)
        other = make_partner(code="BOB2026", phone="+22360000003")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Referral.objects.create(partner=other, seller=self.seller)

    def test_attribution_grossiste_immuable(self):
        r = Referral.objects.create(partner=self.partner, distributor=self.gros)
        other_gros = make_distributor("+22371000002", "Autre gros")
        r.distributor = other_gros
        with self.assertRaises(ValidationError):
            r.save()
        r.refresh_from_db()
        self.assertEqual(r.distributor_id, self.gros.pk)

    def test_attribution_grossiste_ne_change_pas_de_partenaire(self):
        r = Referral.objects.create(partner=self.partner, distributor=self.gros)
        r.partner = make_partner(code="BOB2026", phone="+22360000003")
        with self.assertRaises(ValidationError):
            r.save()

    def test_attribution_vendeuse_reste_immuable_et_se_met_a_jour_sur_champs_libres(self):
        r = Referral.objects.create(partner=self.partner, seller=self.seller)
        r.flagged = True
        r.flag_reason = "test"
        r.save()  # champs non identitaires : autorisé
        r.refresh_from_db()
        self.assertTrue(r.flagged)
        r.seller = make_seller("+22370000199")
        with self.assertRaises(ValidationError):
            r.save()

    def test_str_des_deux_cibles(self):
        vendeuse = Referral.objects.create(partner=self.partner, seller=self.seller)
        grossiste = Referral.objects.create(partner=self.partner, distributor=self.gros)
        self.assertIn(f"vendeur {self.seller.pk}", str(vendeuse))
        self.assertIn(f"grossiste {self.gros.pk}", str(grossiste))


class AttribuerGrossisteTests(TestCase):
    def setUp(self):
        self.partner = make_partner()
        self.gros = make_distributor()
        self.staff = User.objects.create_user(phone="+22372000001", password="x", display_name="Équipe")

    def test_enregistre_source_date_et_audit(self):
        when = timezone.now().replace(microsecond=0) - timedelta(days=3)
        r = attribute_distributor(
            partner=self.partner, distributor=self.gros, source="manual", attributed_at=when, actor=self.staff
        )
        self.assertEqual(r.distributor_id, self.gros.pk)
        self.assertIsNone(r.seller_id)
        self.assertEqual(r.source, "manual")
        self.assertEqual(r.attributed_at, when)
        log = AuditLog.objects.get(action="partner.distributor_attributed", entity_id=r.pk)
        self.assertEqual(log.entity_type, "Referral")
        self.assertEqual(log.actor, self.staff)
        self.assertEqual(log.metadata["distributor_id"], self.gros.pk)
        self.assertEqual(log.metadata["partner_id"], self.partner.pk)

    def test_refuse_un_doublon_sans_nouvelle_ligne_ni_audit(self):
        attribute_distributor(partner=self.partner, distributor=self.gros)
        other = make_partner(code="BOB2026", phone="+22360000003")
        with self.assertRaises(DistributorAttributionError):
            attribute_distributor(partner=other, distributor=self.gros)
        self.assertEqual(Referral.objects.filter(distributor=self.gros).count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="partner.distributor_attributed").count(), 1)

    def test_refuse_une_source_inconnue(self):
        with self.assertRaises(DistributorAttributionError):
            attribute_distributor(partner=self.partner, distributor=self.gros, source="publique")
        self.assertFalse(Referral.objects.exists())

    def test_aucune_commission_ni_donnee_vendeuse_pour_un_grossiste(self):
        attribute_distributor(partner=self.partner, distributor=self.gros)
        self.assertFalse(CommissionEntry.objects.exists())
        self.assertEqual(existing_partner_referral(self.gros).partner, self.partner)
        self.assertIsNone(existing_partner_referral(make_distributor("+22371000009", "Sans")))

    def test_compteurs_de_vendeuses_ignorent_les_grossistes(self):
        seller = make_seller()
        Referral.objects.create(partner=self.partner, seller=seller)
        attribute_distributor(partner=self.partner, distributor=self.gros)
        self.assertEqual(dashboard_stats()["referrals"], 1)
        row = next(p for p in funnel() if p["partner"].pk == self.partner.pk)
        self.assertEqual(row["signups"], 1)
