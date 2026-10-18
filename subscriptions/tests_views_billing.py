"""Vues d'abonnement vendeur : checkout, annulation, callback historique, diagnostic.

Couvre les branches d'erreur qui protegent le paiement : numero obligatoire,
operateur non disponible, echec d'initiation (aucun detail technique montre en
production), annulation d'un paiement en attente seulement, callback historique
(token inconnu, rejeu, echec, montant incoherent, SUCCESS non confirme).
"""

from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from subscriptions.models import PaymentStatus, Plan, SubscriptionPayment, WebhookLog
from subscriptions.services.payment import PaymentNotAllowed
from subscriptions.services.plans import invalidate_plan_cache
from subscriptions.tests_orange_status import STATUS_PATH, _payment, _seller, _status

CREATE = "subscriptions.services.payment.create_orange_payment"


def _messages(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


class _Base(TestCase):
    def setUp(self):
        invalidate_plan_cache()
        self.addCleanup(invalidate_plan_cache)
        self.seller = _seller("+22371110088")
        self.client = Client()
        self.client.force_login(self.seller.user)


class CheckoutViewTests(_Base):
    def url(self, plan=Plan.MEDIUM):
        return reverse("subscriptions:checkout", args=[plan])

    def test_plan_gratuit_ou_inconnu_redirige_vers_la_page_abonnement(self):
        for plan in (Plan.FREE, "inconnu"):
            with self.subTest(plan=plan):
                resp = self.client.get(self.url(plan))
                self.assertRedirects(resp, reverse("subscriptions:subscription"))

    def test_get_affiche_le_prix_decide_par_le_serveur(self):
        resp = self.client.get(self.url())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["amount"], 2000)
        self.assertFalse(resp.context["special_blocked"])

    def test_numero_obligatoire(self):
        with patch(CREATE) as create:
            resp = self.client.post(self.url(), {"provider": "orange", "phone": "  "})
        self.assertEqual(resp.status_code, 200)
        create.assert_not_called()
        self.assertIn("Le numéro de téléphone est obligatoire.", _messages(resp))

    def test_operateur_non_disponible_ne_cree_aucun_paiement(self):
        with patch(CREATE) as create:
            resp = self.client.post(self.url(), {"provider": "wave", "phone": "70123456"})
        self.assertEqual(resp.status_code, 200)
        create.assert_not_called()
        self.assertTrue(any("Wave" in m and "prochainement" in m for m in _messages(resp)))
        self.assertEqual(SubscriptionPayment.objects.count(), 0)

    def test_succes_redirige_vers_la_page_de_paiement_orange(self):
        class Fake:
            payment_url = "https://pay.example/orange"

        with patch(CREATE, return_value=Fake()) as create:
            resp = self.client.post(self.url(), {"provider": "orange", "phone": "70123456"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "https://pay.example/orange")
        self.assertEqual(create.call_args.kwargs["plan"], Plan.MEDIUM)
        self.assertEqual(create.call_args.kwargs["phone"], "70123456")

    def test_paiement_refuse_affiche_la_raison(self):
        with patch(CREATE, side_effect=PaymentNotAllowed("Abonnement déjà actif.")):
            resp = self.client.post(self.url(), {"provider": "orange", "phone": "70123456"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Abonnement déjà actif.", _messages(resp))

    @override_settings(DEBUG=False)
    def test_echec_technique_ne_montre_aucun_detail_en_production(self):
        with patch(CREATE, side_effect=RuntimeError("secret-interne")):
            resp = self.client.post(self.url(), {"provider": "orange", "phone": "70123456"})
        msgs = _messages(resp)
        self.assertEqual(msgs, ["Le paiement Orange Money n'a pas pu être initié."])
        self.assertNotIn("secret-interne", " ".join(msgs))

    @override_settings(DEBUG=True)
    def test_echec_technique_montre_le_detail_en_debug(self):
        with patch(CREATE, side_effect=RuntimeError("detail-debug")):
            resp = self.client.post(self.url(), {"provider": "orange", "phone": "70123456"})
        self.assertIn("detail-debug", " ".join(_messages(resp)))


class PaymentCancelViewTests(_Base):
    def test_annule_un_paiement_en_attente(self):
        payment = _payment(self.seller)
        resp = self.client.get(reverse("subscriptions:payment_cancel", args=[payment.pk]))
        self.assertRedirects(resp, reverse("subscriptions:subscription"))
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.CANCELLED)
        self.assertIn("Paiement annulé.", _messages(resp))

    def test_ne_touche_pas_un_paiement_deja_reussi(self):
        payment = _payment(self.seller, status=PaymentStatus.SUCCESS)
        self.client.get(reverse("subscriptions:payment_cancel", args=[payment.pk]))
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)

    def test_paiement_d_un_autre_vendeur_introuvable(self):
        other = _seller("+22371110089")
        payment = _payment(other, order_id="HF-M-OTHER001", our_token="e" * 64)
        resp = self.client.get(reverse("subscriptions:payment_cancel", args=[payment.pk]))
        self.assertEqual(resp.status_code, 404)
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.PENDING)


class LegacyCallbackTests(_Base):
    url = property(lambda self: reverse("subscriptions:payment_callback"))

    def _post(self, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload)
        ctype = "application/json" if raw is None else "application/x-www-form-urlencoded"
        return Client().post(self.url, data=body, content_type=ctype)

    def test_sans_notif_token_repond_200_sans_rien_modifier(self):
        resp = self._post({"status": "SUCCESS"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(WebhookLog.objects.count(), 0)

    def test_token_inconnu_est_journalise_sans_paiement(self):
        resp = self._post({"status": "SUCCESS", "notif_token": "x" * 32, "txnid": "T1"})
        self.assertEqual(resp.status_code, 200)
        log = WebhookLog.objects.get()
        self.assertIsNone(log.payment)
        self.assertFalse(log.processed)

    def test_corps_encode_en_formulaire_est_lu(self):
        payment = _payment(self.seller)
        resp = self._post(None, raw=f"status=FAILED&notif_token={payment.notif_token}")
        self.assertEqual(resp.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.FAILED)

    def test_echec_notifie_passe_le_paiement_en_echec(self):
        payment = _payment(self.seller)
        self._post({"status": "FAILED", "notif_token": payment.notif_token})
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.FAILED)

    def test_rejeu_apres_succes_ne_retraite_pas(self):
        payment = _payment(self.seller, status=PaymentStatus.SUCCESS)
        with patch(STATUS_PATH) as check:
            resp = self._post({"status": "FAILED", "notif_token": payment.notif_token})
        self.assertEqual(resp.status_code, 200)
        check.assert_not_called()
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)

    def test_montant_incoherent_n_active_pas(self):
        payment = _payment(self.seller)
        with patch(STATUS_PATH) as check:
            resp = self._post(
                {"status": "SUCCESS", "notif_token": payment.notif_token, "amount": 1}
            )
        self.assertEqual(resp.status_code, 200)
        check.assert_not_called()
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.PENDING)

    def test_succes_confirme_par_orange_active_l_abonnement(self):
        payment = _payment(self.seller)
        with patch(STATUS_PATH, return_value=_status("SUCCESS")):
            resp = self._post({"status": "SUCCESS", "notif_token": payment.notif_token})
        self.assertEqual(resp.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)

    def test_erreur_interne_repond_quand_meme_200(self):
        payment = _payment(self.seller)
        with patch(STATUS_PATH, side_effect=RuntimeError("boom")):
            resp = self._post({"status": "SUCCESS", "notif_token": payment.notif_token})
        self.assertEqual(resp.status_code, 200)


class OmDebugViewTests(_Base):
    url = property(lambda self: reverse("subscriptions:om_debug"))

    @override_settings(DEBUG=False)
    def test_introuvable_hors_debug(self):
        self.assertEqual(self.client.get(self.url).status_code, 404)

    @override_settings(
        DEBUG=True,
        ORANGE_MONEY_CLIENT_ID="",
        ORANGE_MONEY_CLIENT_SECRET="",
        ORANGE_MONEY_MERCHANT_KEY="",
        ORANGE_MONEY_BASE_URL="",
    )
    def test_sans_identifiants_signale_la_configuration_manquante(self):
        data = self.client.get(self.url).json()
        self.assertFalse(data["token_ok"])
        self.assertFalse(data["BASE_URL_ok"])
        self.assertIn("BASE_URL_warning", data)
        self.assertEqual(data["CLIENT_ID_val"], "VIDE")

    @override_settings(
        DEBUG=True,
        ORANGE_MONEY_CLIENT_ID="abcdefghij",
        ORANGE_MONEY_CLIENT_SECRET="secret",
        ORANGE_MONEY_MERCHANT_KEY="mkey1234567",
        ORANGE_MONEY_BASE_URL="http://localhost:8000",
    )
    def test_url_non_https_saute_le_test_webpayment_et_masque_les_secrets(self):
        with patch("subscriptions.services.orange_money._get_access_token", return_value="TOKEN1234567890"):
            data = self.client.get(self.url).json()
        self.assertTrue(data["token_ok"])
        self.assertIn("webpayment_skipped", data)
        self.assertEqual(data["CLIENT_ID_val"], "abcdef...")
        self.assertNotIn("secret", json.dumps(data))

    @override_settings(
        DEBUG=True,
        ORANGE_MONEY_CLIENT_ID="cid",
        ORANGE_MONEY_CLIENT_SECRET="csecret",
        ORANGE_MONEY_MERCHANT_KEY="mkey",
        ORANGE_MONEY_BASE_URL="https://example.test",
    )
    def test_echec_du_jeton_est_rapporte_sans_planter(self):
        with patch("subscriptions.services.orange_money._get_access_token", side_effect=RuntimeError("refus")):
            data = self.client.get(self.url).json()
        self.assertFalse(data["token_ok"])
        self.assertEqual(data["token_error"], "refus")
