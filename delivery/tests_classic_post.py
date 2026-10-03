"""F-72 : un envoi de formulaire classique (sans HTMX) ne doit jamais afficher un fragment nu."""

from __future__ import annotations

from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from delivery.models import Delivery
from delivery.tests import DeliveryTestFixture
from orders.models import Order, OrderStatus

HTMX = {"HTTP_HX_REQUEST": "true"}


class ClassicVsHtmxActionPostTests(DeliveryTestFixture):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        resp = self.api.post("/api/v1/orders/", self._order_body(), format="json")
        self.assertEqual(resp.status_code, 201)
        self.order = Order.service_objects.get(pk=resp.data["id"])
        self.delivery = Delivery.objects.get(order_id=self.order.pk)
        self.order.status = OrderStatus.CONFIRMED
        self.order.save(update_fields=["status"])
        self.client = Client()
        self.client.force_login(self.seller_user)
        self.url = reverse(
            "orders:seller_delivery_action", kwargs={"delivery_id": self.delivery.pk}
        )
        self.page = (
            reverse("orders:seller_deliveries_dashboard")
            + f"?flash_sale_id={self.sale.pk}"
        )

    @staticmethod
    def _texts(response) -> list[str]:
        return [str(m) for m in get_messages(response.wsgi_request)]

    def test_classic_post_redirects_to_full_page_with_success_message(self) -> None:
        resp = self.client.post(
            self.url, {"action": "start_delivery", "assigned_to": "Moussa"}
        )
        self.assertRedirects(resp, self.page, fetch_redirect_response=False)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, Delivery.Status.IN_TRANSIT)
        self.assertEqual(self.delivery.assigned_to, "Moussa")
        self.assertEqual(self._texts(resp), ["Livraison démarrée."])
        page = self.client.get(self.page)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Livraison démarrée.")

    def test_htmx_post_still_returns_the_row_fragment(self) -> None:
        resp = self.client.post(
            self.url, {"action": "start_delivery", "assigned_to": "Moussa"}, **HTMX
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f'id="delivery-row-{self.delivery.pk}"')
        self.assertNotContains(resp, "<html")

    def test_classic_validation_error_redirects_with_french_message(self) -> None:
        resp = self.client.post(self.url, {"action": "start_delivery"})
        self.assertRedirects(resp, self.page, fetch_redirect_response=False)
        self.assertEqual(self._texts(resp), ["Indiquez le nom du livreur."])
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, Delivery.Status.PENDING)

    def test_htmx_validation_error_stays_400_in_french(self) -> None:
        resp = self.client.post(self.url, {"action": "start_delivery"}, **HTMX)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.content.decode(), "Indiquez le nom du livreur.")

    def test_classic_wrong_state_error_is_french(self) -> None:
        resp = self.client.post(self.url, {"action": "confirm"})
        self.assertRedirects(resp, self.page, fetch_redirect_response=False)
        (msg,) = self._texts(resp)
        self.assertRegex(msg, r"confirmée")
        self.assertNotRegex(msg, r"[Oo]rder")

    def test_classic_missing_action_redirects_with_message(self) -> None:
        resp = self.client.post(self.url, {})
        self.assertRedirects(resp, self.page, fetch_redirect_response=False)
        self.assertEqual(self._texts(resp), ["L'action demandée est manquante."])

    def test_start_delivery_form_is_wired_for_htmx(self) -> None:
        import re

        cache.clear()
        resp = self.client.get(
            reverse("orders:seller_deliveries_list"), {"flash_sale_id": self.sale.pk}
        )
        form = re.search(r"<form[^>]*>", resp.content.decode(), re.S)
        self.assertIsNotNone(form)
        tag = form.group(0)
        self.assertIn(f'hx-post="{self.url}"', tag)
        self.assertIn(f'hx-target="#delivery-row-{self.delivery.pk}"', tag)
        self.assertIn('hx-swap="outerHTML"', tag)
        # Repli sans JS conserve, et champ « nom du livreur » toujours requis.
        self.assertIn('method="POST"', tag)
        self.assertRegex(resp.content.decode(), r'name="assigned_to"[^>]*required|required[^>]*name="assigned_to"')
