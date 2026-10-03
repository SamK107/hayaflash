"""F-72 : cloture d'une livraison (« Livree » / « Echec ») cablee de bout en bout.

On part du HTML reellement rendu par la liste des livraisons, on en extrait
les parametres hx-vals du bouton, et on les poste a la vraie vue : un nom
d'action ou de drapeau errone dans le gabarit fait donc echouer le test.
"""

from __future__ import annotations

import html
import json
import re

from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from delivery.models import Delivery
from delivery.tests import DeliveryTestFixture
from orders.models import Order, OrderStatus

BUTTON_RE = re.compile(
    r"<button[^>]*hx-vals='([^']+)'[^>]*>\s*([^<]+?)\s*</button>", re.S
)
HTMX = {"HTTP_HX_REQUEST": "true"}


class DeliveryClosureWiringTests(DeliveryTestFixture):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        resp = self.api.post("/api/v1/orders/", self._order_body(), format="json")
        self.assertEqual(resp.status_code, 201)
        self.order = Order.service_objects.get(pk=resp.data["id"])
        self.delivery = Delivery.objects.get(order_id=self.order.pk)
        self.client = Client()
        self.client.force_login(self.seller_user)
        self.action_url = reverse(
            "orders:seller_delivery_action", kwargs={"delivery_id": self.delivery.pk}
        )

    def _post(self, data: dict):
        return self.client.post(self.action_url, data, **HTMX)

    def _buttons(self) -> dict[str, dict]:
        cache.clear()
        resp = self.client.get(
            reverse("orders:seller_deliveries_list"), {"flash_sale_id": self.sale.pk}
        )
        self.assertEqual(resp.status_code, 200)
        text = resp.content.decode()
        return {
            re.sub(r"\s+", " ", label): json.loads(html.unescape(vals))
            for vals, label in BUTTON_RE.findall(text)
        }

    def _start_delivery(self) -> None:
        self.assertEqual(self._post({"action": "confirm"}).status_code, 200)
        resp = self._post({"action": "start_delivery", "assigned_to": "Moussa"})
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_closure_buttons_are_displayed_when_in_transit(self) -> None:
        self._start_delivery()
        buttons = self._buttons()
        labels = list(buttons)
        self.assertTrue(any(l.startswith("Livrée") for l in labels), labels)
        self.assertIn("Échec", labels)

    def test_closure_buttons_hidden_before_delivery_starts(self) -> None:
        labels = list(self._buttons())
        self.assertFalse(any(l.startswith("Livrée") for l in labels), labels)

    def test_delivered_cod_collected_end_to_end(self) -> None:
        self._start_delivery()
        vals = self._buttons()["Livrée · encaissée"]
        self.assertEqual(vals["action"], "mark_delivered")
        resp = self._post(vals)
        self.assertEqual(resp.status_code, 200, resp.content)

        self.order.refresh_from_db()
        self.delivery.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.DELIVERED)
        self.assertEqual(self.delivery.status, Delivery.Status.DELIVERED)
        self.assertTrue(self.delivery.cod_collected)
        self.assertEqual(self.delivery.cod_confirmed_by, self.seller_user)

        cache.clear()
        summary = self.client.get(
            reverse("orders:seller_deliveries_summary"),
            {"flash_sale_id": self.sale.pk},
        )
        # 2 x 1 999 = 3 998 FCFA : passe de « a collecter » a « collecte ».
        text = summary.content.decode()
        self.assertEqual(
            Delivery.objects.get(pk=self.delivery.pk).cod_amount, self.order.total_amount
        )
        self.assertEqual(text.count("FCFA"), 2)
        self.assertRegex(text, r">3[\s  ]998\s*<span[^>]*> FCFA")

        # Une livraison close n'a plus de boutons de cloture.
        labels = list(self._buttons())
        self.assertFalse(any(l.startswith("Livrée") for l in labels), labels)
        self.assertNotIn("Échec", labels)

    def test_delivered_cod_not_collected(self) -> None:
        self._start_delivery()
        resp = self._post(self._buttons()["Livrée · non encaissée"])
        self.assertEqual(resp.status_code, 200, resp.content)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, Delivery.Status.DELIVERED)
        self.assertFalse(self.delivery.cod_collected)

    def test_failed_end_to_end(self) -> None:
        self._start_delivery()
        vals = self._buttons()["Échec"]
        self.assertEqual(vals["action"], "mark_failed")
        resp = self._post(vals)
        self.assertEqual(resp.status_code, 200, resp.content)

        self.delivery.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.delivery.status, Delivery.Status.FAILED)
        self.assertFalse(self.delivery.cod_collected)
        # Regle metier inchangee : advance_delivery ne touche pas la commande.
        self.assertEqual(self.order.status, OrderStatus.OUT_FOR_DELIVERY)

        labels = list(self._buttons())
        self.assertNotIn("Échec", labels)
