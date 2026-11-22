"""Admin des grossistes : colonne « Apporté par », filtre, saisie unique via le service (D9)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog
from distrib.models import Distributor
from partners.models import Referral
from partners.services.distributor_attribution import attribute_distributor
from partners.tests_models import make_partner

User = get_user_model()


def make_distributor(phone="+22371000001", name="Gros Bamako"):
    user = User.objects.create_user(phone=phone, password="x", display_name=name)
    return Distributor.objects.create(user=user, business_name=name)


def form_data(distributor, **extra):
    """Données d'un formulaire d'admin complet (valeurs par défaut du modèle)."""
    data = {
        "user": distributor.user_id,
        "business_name": distributor.business_name,
        "contact_phone": "",
        "orange_money_number": "",
        "is_active": "on",
        "is_suspended": "",
        "suspended_reason": "",
        "commission_rate": "6",
        "commission_min": "250",
        "commission_max": "1500",
        "pilot_until": "",
        "credit_ceiling": "10000",
        "reseller_credit_ceiling": "10000",
        "payout_delay_days": "3",
        "auto_confirm_hours": "72",
        "alert_not_delivered_percent": "20",
        "alert_conflicts": "1",
        "alert_contested": "1",
        "apporte_par": "",
    }
    data.update(extra)
    return data


class DistributorAdminAttributionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(phone="+22372000099", password="x", display_name="Admin")
        self.client.force_login(self.admin)
        self.partner = make_partner()
        self.other = make_partner(code="BOB2026", phone="+22360000002", name="Bob")
        self.gros = make_distributor()
        self.gros_sans = make_distributor("+22371000002", "Sans partenaire")

    def change_url(self, distributor):
        return reverse("admin:distrib_distributor_change", args=[distributor.pk])

    def test_saisie_enregistre_le_rattachement_via_le_service(self):
        resp = self.client.post(
            self.change_url(self.gros), form_data(self.gros, apporte_par=self.partner.pk)
        )
        self.assertEqual(resp.status_code, 302)
        ref = Referral.objects.get(distributor=self.gros)
        self.assertEqual(ref.partner, self.partner)
        self.assertEqual(ref.source, "manual")
        log = AuditLog.objects.get(action="partner.distributor_attributed", entity_id=ref.pk)
        self.assertEqual(log.actor, self.admin)

    def test_un_rattachement_existant_ne_se_modifie_pas(self):
        attribute_distributor(partner=self.partner, distributor=self.gros)
        self.client.post(self.change_url(self.gros), form_data(self.gros, apporte_par=self.other.pk))
        self.assertEqual(Referral.objects.filter(distributor=self.gros).count(), 1)
        self.assertEqual(Referral.objects.get(distributor=self.gros).partner, self.partner)

    def test_formulaire_affiche_le_partenaire_existant_en_lecture_seule(self):
        attribute_distributor(partner=self.partner, distributor=self.gros)
        resp = self.client.get(self.change_url(self.gros))
        field = resp.context["adminform"].form.fields["apporte_par"]
        self.assertTrue(field.disabled)
        self.assertEqual(field.initial, self.partner)

    def test_saisie_sans_partenaire_ne_cree_rien(self):
        self.client.post(self.change_url(self.gros_sans), form_data(self.gros_sans, apporte_par=""))
        self.assertFalse(Referral.objects.filter(distributor=self.gros_sans).exists())

    def test_colonne_et_filtre_apporte_par(self):
        attribute_distributor(partner=self.partner, distributor=self.gros)
        url = reverse("admin:distrib_distributor_changelist")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Apporté par")
        self.assertContains(resp, self.partner.name)

        by_partner = self.client.get(url, {"apporte_par": str(self.partner.pk)})
        names = [d.business_name for d in by_partner.context["cl"].result_list]
        self.assertEqual(names, [self.gros.business_name])

        none = self.client.get(url, {"apporte_par": "none"})
        names = [d.business_name for d in none.context["cl"].result_list]
        self.assertEqual(names, [self.gros_sans.business_name])

    def test_ajout_avec_partenaire_cree_le_grossiste_et_le_rattachement(self):
        user = User.objects.create_user(phone="+22371000007", password="x", display_name="Nouveau")
        resp = self.client.post(
            reverse("admin:distrib_distributor_add"),
            form_data_for_add(user, apporte_par=self.other.pk),
        )
        self.assertEqual(resp.status_code, 302)
        created = Distributor.objects.get(user=user)
        self.assertEqual(Referral.objects.get(distributor=created).partner, self.other)


def form_data_for_add(user, **extra):
    data = form_data(Distributor(user=user, business_name="Nouveau gros"), **extra)
    data["business_name"] = "Nouveau gros"
    return data
