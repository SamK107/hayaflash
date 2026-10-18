"""D13 : les pages légales décrivent ce que le service fait réellement (ni plus, ni moins).

Les engagements chiffrés du texte (blocage après 3 échecs en 30 jours) sont comparés
aux constantes du code : si l'une change sans l'autre, ce test échoue.
"""

from __future__ import annotations

import datetime
import re

from django.test import TestCase, override_settings
from django.urls import reverse

from core.legal import LEGAL_CGU_VERSION, LEGAL_LAST_UPDATED, LEGAL_PRIVACY_VERSION
from orders.services.unhonored import UNHONORED_ORDERS_THRESHOLD, UNHONORED_WINDOW_DAYS

HOTE_VIDE = dict(LEGAL_HOST_NAME="", LEGAL_HOST_ADDRESS="", LEGAL_HOST_PHONE="")


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


class LegalRealityTests(TestCase):
    def page(self, name):
        return _text(self.client.get(reverse(name)).content.decode())

    @override_settings(LEGAL_ENTITY_RCCM="", **HOTE_VIDE)
    def test_mentions_legales(self):
        text = self.page("legal_notice")
        self.assertIn("ABEXPERTISES", text)
        self.assertIn("entreprise individuelle", text)
        self.assertIn("RCCM) de Bamako", text)
        self.assertIn("contact@hayaflash.com", text)
        self.assertIn("L'équipe HayaFlash", text)
        self.assertIn("hébergé par LWS (France)", text)

    @override_settings(LEGAL_ENTITY_RCCM="ML-BKO-2099-X-00001", **HOTE_VIDE)
    def test_numero_rccm_affiche_seulement_s_il_est_configure(self):
        self.assertIn("RCCM) de Bamako, n° ML-BKO-2099-X-00001", self.page("legal_notice"))

    def test_aucun_telephone_ni_nom_de_personne_dans_les_mentions(self):
        text = self.page("legal_notice")
        # Hors NIF (numéro d'entreprise), aucune suite de 8 chiffres ou plus : pas de téléphone.
        sans_nif = re.sub(r"NIF\s*\d+", "NIF", text)
        self.assertIsNone(re.search(r"\+?\d[\d .()-]{7,}\d", sans_nif))

    def test_politique_de_confidentialite_dit_la_verite(self):
        text = self.page("legal_privacy")
        self.assertIn("bilans mensuels", text)
        self.assertIn("anonymisés", text)
        self.assertIn("sans nom, numéro de téléphone ni adresse de cliente", text)
        self.assertIn("intelligence artificielle", text)
        self.assertIn("Sentry", text)
        self.assertIn("sans données personnelles", text)
        self.assertIn("LWS", text)
        self.assertIn("Orange Money", text)
        self.assertIn("à la livraison", text)
        self.assertIn(
            f"après {UNHONORED_ORDERS_THRESHOLD} livraisons non abouties", text
        )
        self.assertIn(f"en {UNHONORED_WINDOW_DAYS} jours", text)

    def test_cgu_disent_la_verite(self):
        text = self.page("legal_terms")
        self.assertIn("Bilans et conseils", text)
        self.assertIn("intelligence artificielle", text)
        self.assertIn("paiement se fait à la livraison", text.replace("Le paiement", "paiement"))
        self.assertIn("Orange Money", text)
        self.assertIn(f"{UNHONORED_ORDERS_THRESHOLD} livraisons non abouties en {UNHONORED_WINDOW_DAYS} jours", text)
        self.assertIn("Ce numéro ne peut plus commander pour le moment. Contacte la boutique.", text)

    def test_aucune_promesse_de_sms(self):
        for name in ("legal_notice", "legal_privacy", "legal_terms"):
            with self.subTest(page=name):
                self.assertNotRegex(self.page(name).replace("aucun SMS n'est envoyé", ""), r"\bSMS\b")

    def test_date_et_versions_mises_a_jour(self):
        self.assertEqual(LEGAL_LAST_UPDATED, datetime.date(2026, 10, 18))
        self.assertEqual((LEGAL_CGU_VERSION, LEGAL_PRIVACY_VERSION), ("2026-10", "2026-10"))
        for name in ("legal_notice", "legal_privacy", "legal_terms"):
            with self.subTest(page=name):
                self.assertIn("18 octobre 2026", self.page(name))

    def test_aucune_mention_a_valider_par_un_juriste_visible(self):
        for name in ("legal_notice", "legal_privacy", "legal_terms"):
            html = self.client.get(reverse(name)).content.decode()
            with self.subTest(page=name):
                self.assertNotIn("juriste", html.split("<article")[1] if "<article" in html else html)
