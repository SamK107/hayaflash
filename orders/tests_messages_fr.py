"""Messages d'erreur du parcours acheteur : en francais (renvoyes tels quels par hf-public.js)."""

from __future__ import annotations

from unittest import mock
from uuid import uuid4

from rest_framework.test import APIClient

from orders.tests import LiveFlashSaleProductFixture, _valid_delivery


class BuyerErrorMessagesFrenchTests(LiveFlashSaleProductFixture):
    def _post(self, **overrides):
        body = {
            "flash_sale_id": self.sale.pk,
            "product_id": self.product.pk,
            "name": "Client",
            "phone": "+22370000010",
            "quantity": 1,
            "client_request_id": str(uuid4()),
            "delivery": _valid_delivery(),
        }
        body.update(overrides)
        return APIClient().post("/api/v1/orders/", body, format="json")

    def test_short_address(self) -> None:
        resp = self._post(delivery=_valid_delivery(address_text="court"))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json()["address_text"],
            ["L'adresse doit contenir au moins 10 caractères "
             "(ou enregistrez un message vocal à la place)."],
        )

    def test_empty_address_without_voice(self) -> None:
        resp = self._post(delivery=_valid_delivery(address_text=""))
        self.assertEqual(
            resp.json()["delivery"],
            ["Écrivez votre adresse ou enregistrez un message vocal."],
        )

    def test_latitude_out_of_range_and_lonely_coordinate(self) -> None:
        resp = self._post(delivery=_valid_delivery(latitude="95", longitude="1"))
        self.assertEqual(
            resp.json()["latitude"], ["La latitude doit être comprise entre -90 et 90."]
        )
        resp = self._post(delivery=_valid_delivery(latitude="10", longitude="200"))
        self.assertEqual(
            resp.json()["longitude"],
            ["La longitude doit être comprise entre -180 et 180."],
        )
        resp = self._post(delivery=_valid_delivery(latitude="10", longitude=""))
        self.assertEqual(
            resp.json()["delivery"],
            ["La latitude et la longitude doivent être renseignées ensemble."],
        )

    def test_notes_too_long(self) -> None:
        resp = self._post(delivery=_valid_delivery(delivery_notes="x" * 1001))
        self.assertEqual(
            resp.json()["delivery_notes"],
            ["Les précisions de livraison ne doivent pas dépasser 1000 caractères."],
        )

    def test_unknown_sale_and_product(self) -> None:
        self.assertEqual(
            self._post(flash_sale_id=999999).json()["flash_sale_id"],
            ["Vente flash introuvable."],
        )
        self.assertEqual(
            self._post(product_id=999999).json()["product_id"],
            ["Produit introuvable."],
        )

    def test_product_not_in_sale(self) -> None:
        from decimal import Decimal

        from products.models import Product

        other = Product.objects.create(
            owner=self.seller, name="Autre", stock_available=1,
            stock_initial=1, price=Decimal("500"),
        )
        self.assertEqual(
            self._post(product_id=other.pk).json()["product_id"],
            ["Ce produit ne fait pas partie de cette vente flash."],
        )

    def test_insufficient_stock(self) -> None:
        resp = self._post(quantity=50)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json()["items"],
            [f"Stock insuffisant pour le produit {self.product.pk} "
             "(demandé : 50, disponible : 10)."],
        )

    def test_ip_rate_limit_message_and_status(self) -> None:
        from orders.services import client_order

        with mock.patch.object(client_order, "ORDER_SUBMIT_RATE_MAX_PER_WINDOW", 0):
            resp = self._post()
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(
            resp.json()["detail"],
            ["Trop de tentatives de commande depuis ce réseau. "
             "Patientez une minute puis réessayez."],
        )
