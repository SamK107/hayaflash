"""Premier lien gagnant : /r/<code>/ ne remplace jamais un cookie hf_ref valide.

Règle (docs/EXECUTION_V2.md, § Brief §6.2) : un vendeur qui clique plusieurs liens avant
son inscription est rattaché au premier partenaire éligible. Un cookie absent, expiré
(supprimé par le navigateur) ou désignant un partenaire devenu inéligible est remplacé.
Un lien invalide ne bloque jamais l'inscription.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from core.tests_register_security import payload
from partners.models import Partner, Referral
from partners.services.attribution import COOKIE_NAME
from partners.tests_models import make_partner

User = get_user_model()
SELLER_PHONE = "+22370000301"


def signup(client):
    return client.post(reverse("register"), payload(phone=SELLER_PHONE))


class PremierLienTests(TestCase):
    def setUp(self):
        cache.clear()
        self.awa = make_partner(code="AWA2026")
        self.bob = make_partner(code="BOB2026", phone="+22360000002")

    def referral(self):
        return Referral.objects.filter(seller__user__phone=SELLER_PHONE).first()

    def test_second_link_before_signup_does_not_replace_the_first(self):
        first = self.client.get("/r/AWA2026/", REMOTE_ADDR="196.200.5.1")
        self.assertEqual(first.cookies[COOKIE_NAME].value, "AWA2026")

        second = self.client.get("/r/BOB2026/", REMOTE_ADDR="196.200.5.2")
        self.assertEqual(second.status_code, 302)
        self.assertNotIn(COOKIE_NAME, second.cookies)
        self.assertEqual(self.client.cookies[COOKIE_NAME].value, "AWA2026")
        # Les deux clics restent comptés : le clic n'est pas une attribution.
        self.assertEqual(self.awa.clicks.count(), 1)
        self.assertEqual(self.bob.clicks.count(), 1)

        self.assertEqual(signup(self.client).status_code, 302)
        self.assertEqual(self.referral().partner, self.awa)

    def test_repeated_click_on_the_same_link_keeps_the_original_cookie(self):
        self.client.get("/r/AWA2026/")
        again = self.client.get("/r/AWA2026/")
        self.assertNotIn(COOKIE_NAME, again.cookies)
        self.assertEqual(self.client.cookies[COOKIE_NAME].value, "AWA2026")

    def test_absent_cookie_is_set_by_the_link(self):
        resp = self.client.get("/r/BOB2026/")
        self.assertEqual(resp.cookies[COOKIE_NAME].value, "BOB2026")
        self.assertEqual(int(resp.cookies[COOKIE_NAME]["max-age"]), 30 * 24 * 3600)

    def test_expired_cookie_is_treated_as_absent(self):
        # Le navigateur supprime un cookie expiré : il n'est plus envoyé au serveur.
        self.client.cookies.pop(COOKIE_NAME, None)
        resp = self.client.get("/r/BOB2026/")
        self.assertEqual(resp.cookies[COOKIE_NAME].value, "BOB2026")

    def test_cookie_pointing_to_an_ineligible_partner_is_replaced(self):
        self.client.cookies[COOKIE_NAME] = "AWA2026"
        Partner.objects.filter(pk=self.awa.pk).update(
            contract_end=timezone.localdate() - timedelta(days=1)
        )
        resp = self.client.get("/r/BOB2026/")
        self.assertEqual(resp.cookies[COOKIE_NAME].value, "BOB2026")

    def test_invalid_link_with_valid_cookie_does_not_block_signup(self):
        self.client.get("/r/AWA2026/")
        bad = self.client.get("/r/NOSUCH1/")
        self.assertEqual(bad.status_code, 302)
        self.assertNotIn(COOKIE_NAME, bad.cookies)
        self.assertEqual(self.client.cookies[COOKIE_NAME].value, "AWA2026")

        self.assertEqual(signup(self.client).status_code, 302)
        self.assertTrue(SellerProfile.objects.filter(user__phone=SELLER_PHONE).exists())
        self.assertEqual(self.referral().partner, self.awa)

    def test_invalid_link_without_cookie_does_not_block_signup(self):
        bad = self.client.get("/r/NOSUCH1/")
        self.assertEqual(bad.status_code, 302)
        self.assertNotIn(COOKIE_NAME, bad.cookies)

        self.assertEqual(signup(self.client).status_code, 302)
        self.assertTrue(SellerProfile.objects.filter(user__phone=SELLER_PHONE).exists())
        self.assertIsNone(self.referral())
