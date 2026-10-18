"""create_order : validation stricte de la charge utile et rejeu idempotent.

Le service est l'unique voie de creation d'une commande (CLAUDE.md) : toute
charge utile mal formee doit etre refusee AVANT d'ecrire quoi que ce soit.
"""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError

from delivery.tests import DeliveryTestFixture
from orders.models import Order
from orders.services.create_order import create_order
from orders.tests import _valid_delivery


class CreateOrderValidationTests(DeliveryTestFixture):
    def _data(self, **overrides):
        data = {
            "flash_sale_id": self.sale.pk,
            "customer_name": "Aminata",
            "customer_phone": "+22370123456",
            "client_request_id": str(uuid4()),
            "items": [{"product_id": self.product.pk, "quantity": 1}],
            "delivery": _valid_delivery(),
        }
        data.update(overrides)
        return data

    def _assert_refused(self, data, field=None):
        before = Order.service_objects.count()
        with self.assertRaises(ValidationError) as ctx:
            create_order(data)
        if field is not None:
            self.assertIn(field, ctx.exception.message_dict)
        self.assertEqual(Order.service_objects.count(), before)

    def test_charge_utile_non_dictionnaire(self):
        self._assert_refused(["pas", "un", "dict"])

    def test_champ_obligatoire_absent(self):
        for key in ("flash_sale_id", "customer_name", "customer_phone",
                    "client_request_id", "items", "delivery"):
            with self.subTest(key=key):
                data = self._data()
                del data[key]
                self._assert_refused(data, key)

    def test_livraison_doit_etre_un_objet(self):
        self._assert_refused(self._data(delivery="rue"), "delivery")

    def test_identifiant_de_vente_invalide(self):
        for bad in ("1", 0, -3, True and "x"):
            with self.subTest(bad=bad):
                self._assert_refused(self._data(flash_sale_id=bad), "flash_sale_id")

    def test_textes_vides_ou_non_textuels(self):
        for key in ("customer_name", "customer_phone", "client_request_id"):
            for bad in ("   ", 12345, None):
                with self.subTest(key=key, bad=bad):
                    self._assert_refused(self._data(**{key: bad}), key)

    def test_articles_invalides(self):
        cases = [
            [],
            "x",
            ["pas un objet"],
            [{"product_id": self.product.pk}],
            [{"quantity": 1}],
            [{"product_id": 0, "quantity": 1}],
            [{"product_id": "1", "quantity": 1}],
            [{"product_id": self.product.pk, "quantity": 0}],
            [{"product_id": self.product.pk, "quantity": "2"}],
        ]
        for items in cases:
            with self.subTest(items=items):
                self._assert_refused(self._data(items=items), "items")

    def test_stock_non_modifie_apres_un_refus(self):
        self._assert_refused(self._data(items=[{"product_id": self.product.pk, "quantity": 0}]))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_available, 10)


class CreateOrderIdempotenceTests(DeliveryTestFixture):
    def _data(self):
        return {
            "flash_sale_id": self.sale.pk,
            "customer_name": "Aminata",
            "customer_phone": "+22370123456",
            "client_request_id": str(uuid4()),
            "items": [{"product_id": self.product.pk, "quantity": 2}],
            "delivery": _valid_delivery(),
        }

    def test_meme_client_request_id_renvoie_la_meme_commande_sans_double_debit(self):
        data = self._data()
        first = create_order(deepcopy(data))
        second = create_order(deepcopy(data))
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Order.service_objects.filter(client_request_id=data["client_request_id"]).count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_available, 8)

    def test_une_notification_ou_un_journal_en_panne_ne_bloque_pas_la_commande(self):
        data = self._data()
        with patch("core.models.audit", side_effect=RuntimeError("journal")), patch(
            "notifications.tasks.send_order_confirmation.delay", side_effect=RuntimeError("broker")
        ):
            order = create_order(data)
        self.assertTrue(Order.service_objects.filter(pk=order.pk).exists())
