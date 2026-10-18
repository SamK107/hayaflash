"""Commande publique : construction de la charge utile et page de commande.

Le corps JSON vient d'un navigateur non fiable : chaque champ est valide avant
d'atteindre create_order, et une note vocale illisible ne bloque jamais la commande.
"""

from __future__ import annotations

from uuid import uuid4

from django.core.exceptions import ValidationError
from django.test import RequestFactory

from delivery.tests import DeliveryTestFixture
from orders.services.client_order import (
    MAX_AUDIO_BASE64_LENGTH,
    _as_positive_int,
    _clean_audio_base64,
    build_create_order_payload_from_public,
    resolve_client_order_page,
)
from orders.tests import _valid_delivery
from products.models import FlashSaleProduct, Product


class AsPositiveIntTests(DeliveryTestFixture):
    def test_accepte_entier_et_chaine_numerique(self):
        self.assertEqual(_as_positive_int(3, "q"), 3)
        self.assertEqual(_as_positive_int(" 4 ", "q"), 4)

    def test_refuse_booleen_texte_et_valeur_trop_petite(self):
        for bad in (True, "abc", "-1", 1.5, None):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                _as_positive_int(bad, "q")
        with self.assertRaises(ValidationError):
            _as_positive_int(0, "q")


class CleanAudioTests(DeliveryTestFixture):
    def test_extrait_la_partie_base64_d_une_data_url(self):
        self.assertEqual(_clean_audio_base64("data:audio/webm;base64,QUJD"), "QUJD")

    def test_ignore_les_valeurs_inutilisables(self):
        for bad in (None, 12, "", "   ", "data:audio/webm;base64,"):
            self.assertIsNone(_clean_audio_base64(bad), bad)

    def test_ignore_une_note_trop_volumineuse(self):
        self.assertIsNone(_clean_audio_base64("A" * (MAX_AUDIO_BASE64_LENGTH + 1)))


class BuildPayloadTests(DeliveryTestFixture):
    def _body(self, **overrides):
        body = self._order_body()
        body.update(overrides)
        return body

    def _refused(self, body, field):
        with self.assertRaises(ValidationError) as ctx:
            build_create_order_payload_from_public(data=body)
        self.assertIn(field, ctx.exception.message_dict)

    def test_corps_non_objet(self):
        with self.assertRaises(ValidationError):
            build_create_order_payload_from_public(data=["x"])

    def test_champs_obligatoires_listes_ensemble(self):
        with self.assertRaises(ValidationError) as ctx:
            build_create_order_payload_from_public(data={})
        self.assertEqual(
            set(ctx.exception.message_dict),
            {"flash_sale_id", "product_id", "name", "phone", "quantity", "client_request_id"},
        )

    def test_textes_vides_refuses(self):
        for field in ("name", "phone", "client_request_id"):
            with self.subTest(field=field):
                self._refused(self._body(**{field: "  "}), field)

    def test_vente_ou_produit_inconnu(self):
        self._refused(self._body(flash_sale_id=999999), "flash_sale_id")
        self._refused(self._body(product_id=999999), "product_id")

    def test_produit_hors_de_la_vente(self):
        other = Product.objects.create(owner=self.seller, name="Autre", stock_available=5,
                                       stock_initial=5, price=100)
        self._refused(self._body(product_id=other.pk), "product_id")

    def test_produit_desactive_dans_la_vente(self):
        FlashSaleProduct.objects.filter(flash_sale=self.sale, product=self.product).update(is_active=False)
        self._refused(self._body(), "product_id")

    def test_charge_utile_valide_normalise_le_numero_et_tronque_l_identifiant(self):
        payload = build_create_order_payload_from_public(
            data=self._body(name="  Aminata  ", phone="+223 70 12 34 56", client_request_id="x" * 300)
        )
        self.assertEqual(payload["customer_name"], "Aminata")
        self.assertEqual(len(payload["client_request_id"]), 128)
        self.assertEqual(payload["items"], [{"product_id": self.product.pk, "quantity": 2}])
        self.assertEqual(payload["customer_phone"], "+22370123456")

    def test_adresse_a_plat_ancien_format_et_note_vocale_best_effort(self):
        body = {
            "flash_sale_id": self.sale.pk,
            "product_id": self.product.pk,
            "name": "Fanta",
            "phone": "+22370123456",
            "quantity": 1,
            "client_request_id": str(uuid4()),
            "address_text": _valid_delivery()["address_text"],
            "audio_base64": "data:audio/webm;base64,QUJD",
        }
        payload = build_create_order_payload_from_public(data=body)
        self.assertEqual(payload["delivery"]["address_text"], _valid_delivery()["address_text"])
        self.assertEqual(payload["delivery"]["audio_base64"], "QUJD")

    def test_livraison_absente_refusee(self):
        body = self._body()
        del body["delivery"]
        self._refused(body, "delivery")


class ResolveOrderPageTests(DeliveryTestFixture):
    def _page(self, **params):
        return resolve_client_order_page(RequestFactory().get("/order/", params))

    def test_parametres_absents(self):
        ctx = self._page()
        self.assertFalse(ctx["can_submit"])
        self.assertIn("flash_sale_id", ctx["page_error"])

    def test_parametres_non_entiers(self):
        ctx = self._page(flash_sale_id="a", product_id="b")
        self.assertFalse(ctx["can_submit"])

    def test_vente_ou_produit_introuvable(self):
        ctx = self._page(flash_sale_id=999999, product_id=999999)
        self.assertFalse(ctx["can_submit"])
        self.assertEqual(ctx["page_error"], "Vente flash ou produit introuvable.")

    def test_produit_hors_vente(self):
        other = Product.objects.create(owner=self.seller, name="Autre", stock_available=5,
                                       stock_initial=5, price=100)
        ctx = self._page(flash_sale_id=self.sale.pk, product_id=other.pk)
        self.assertFalse(ctx["can_submit"])
        self.assertEqual(ctx["product_name"], "Autre")

    def test_vente_en_direct_accepte_les_commandes(self):
        ctx = self._page(flash_sale_id=self.sale.pk, product_id=self.product.pk)
        self.assertTrue(ctx["can_submit"])
        self.assertEqual(ctx["page_error"], "")
