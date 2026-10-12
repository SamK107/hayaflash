"""Cohorte de 8 places de fondateur : le compte à rebours « Il reste N places » suit les enrôlements.

Une place est prise quand un partenaire accepte les CONDITIONS DU PROGRAMME (phase contrat), pas la lettre
d'essai. Le premier à accepter prend une place tant qu'il en reste : aucune sélection n'est codée (la
sélection des partenaires se fait hors plateforme).
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.conf import settings
from django.test import TestCase, override_settings

from partners.services import messages as msg
from partners.services.acceptance import FULL_PLACES_MESSAGE, accept_document, places_left
from partners.tests_documents import FACTICE
from partners.tests_models import make_partner


def message_with_places(staff_name="Alex") -> str:
    class Staff:
        display_name = staff_name
        pk = None

    return msg.prepare(
        staff=Staff(), country="223", national="70 00 00 01", first_name="Awa", shop_name="",
        template_key="envoi_conditions", text=msg.TEMPLATES["envoi_conditions"],
        link_builder=lambda token: f"https://exemple.test/partenaires/d/{token}/", preview=True,
    ).body


@override_settings(**FACTICE)
class CohortOfEightTests(TestCase):
    def trial_partner(self, n):
        return make_partner(
            code=f"ESS{n:04d}", phone=f"+2236200{n:04d}", name=f"Partenaire {n}", accept=False,
            phase="trial", trial_start=None, is_founder=False,
        )

    def enrol(self, n):
        partner = self.trial_partner(n)
        accept_document(partner, "program_terms", signer_name=f"Partenaire {n}")
        return partner

    def test_the_setting_is_eight(self):
        self.assertEqual(settings.PARTNER_FOUNDER_SLOTS, 8)
        self.assertEqual(places_left(), 8)

    def test_the_message_counts_down_with_each_enrolment(self):
        self.assertIn("Il reste 8 places.", message_with_places())
        self.enrol(1)
        self.assertIn("Il reste 7 places.", message_with_places())
        self.enrol(2)
        self.assertIn("Il reste 6 places.", message_with_places())
        self.assertEqual(places_left(), 6)

    def test_the_trial_letter_takes_no_place(self):
        for n in range(1, 4):
            partner = make_partner(
                code=f"LET{n:04d}", phone=f"+2236300{n:04d}", name=f"Lettre {n}", status="prospect",
                phase="none", accept=False,
            )
            accept_document(partner, "trial_letter", signer_name=f"Lettre {n}")
            partner.refresh_from_db()
            self.assertEqual(partner.phase, "trial")
        self.assertEqual(places_left(), 8)
        self.assertIn("Il reste 8 places.", message_with_places())

    def test_the_ninth_acceptance_is_refused_without_any_selection_rule(self):
        for n in range(1, 9):
            self.enrol(n)
        self.assertEqual(places_left(), 0)
        ninth = self.trial_partner(9)
        with self.assertRaises(ValidationError) as ctx:
            accept_document(ninth, "program_terms", signer_name="Partenaire 9")
        self.assertIn(FULL_PLACES_MESSAGE, ctx.exception.messages)
        ninth.refresh_from_db()
        self.assertEqual(ninth.phase, "trial")
        self.assertIn("Il reste 0 places.", message_with_places())
