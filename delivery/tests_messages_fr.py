"""PR 2 (F-79, audit UI section A, lignes « mineur ») : messages de l'espace
vendeur, des API internes et libelles de modeles en francais."""

from __future__ import annotations

from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

from delivery.tests import DeliveryTestFixture
from orders.models import Order

User = get_user_model()

ENGLISH_MARKERS = (
    "not found",
    "not allowed",
    "required",
    "must be",
    "Invalid",
    "cannot be",
    "not accessible",
)


def _assert_french(testcase, text):
    for marker in ENGLISH_MARKERS:
        testcase.assertNotIn(marker.lower(), text.lower(), text)


class SellerSpaceMessagesFrenchTests(DeliveryTestFixture):
    """Vues vendeur HTMX : 400/403 en texte brut, en francais."""

    def setUp(self):
        super().setUp()
        self.buyer = User.objects.create_user(
            phone="+15550001111", password="x", display_name="Acheteur"
        )

    def _order(self):
        return Order.service_objects.create(
            flash_sale=self.sale, customer_name="Ada", customer_phone="+22370000009"
        )

    def test_user_without_seller_profile_gets_french_403(self):
        c = Client()
        c.force_login(self.buyer)
        order = self._order()
        resp = c.post(
            reverse("orders:seller_order_advance_status", args=[order.pk])
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.content.decode(), "Profil vendeur requis.")

    def test_other_seller_gets_french_403_on_foreign_order(self):
        c = Client()
        c.force_login(self.other_user)
        order = self._order()
        resp = c.post(
            reverse("orders:seller_order_advance_status", args=[order.pk])
        )
        self.assertEqual(resp.status_code, 403)
        _assert_french(self, resp.content.decode())
        self.assertEqual(resp.content.decode(), "Action non autorisée.")

    def test_missing_flash_sale_id_is_french_400(self):
        c = Client()
        c.force_login(self.seller_user)
        resp = c.get(reverse("orders:seller_deliveries_summary"))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.content.decode(), "Le paramètre flash_sale_id est obligatoire."
        )

    def test_unknown_delivery_action_is_french(self):
        c = Client()
        c.force_login(self.seller_user)
        resp = c.post(
            reverse("orders:seller_delivery_action", kwargs={"delivery_id": uuid4()}),
            {"action": "mark_delivered"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp.status_code, 400)
        _assert_french(self, resp.content.decode())

    def test_service_errors_are_french(self):
        from django.core.exceptions import PermissionDenied

        from delivery.services.seller_dashboard import get_delivery_summary

        with self.assertRaises(PermissionDenied) as cm:
            get_delivery_summary(user=self.other_user, flash_sale_id=self.sale.pk)
        self.assertEqual(str(cm.exception), "Vente flash introuvable ou inaccessible.")


class ApiMessagesFrenchTests(DeliveryTestFixture):
    """API sans interface directe : messages destines a un humain en francais."""

    def test_delivery_list_missing_flash_sale_id(self):
        self.api.force_authenticate(self.seller_user)
        resp = self.api.get("/api/v1/delivery/")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json()["detail"], "Le paramètre flash_sale_id est obligatoire."
        )

    def test_delivery_list_non_integer_flash_sale_id(self):
        self.api.force_authenticate(self.seller_user)
        resp = self.api.get("/api/v1/delivery/?flash_sale_id=abc")
        self.assertEqual(resp.json()["detail"], "flash_sale_id doit être un nombre entier.")

    def test_create_order_payload_errors_are_french(self):
        resp = self.api.post("/api/v1/orders/", {"flash_sale_id": self.sale.pk}, format="json")
        self.assertEqual(resp.status_code, 400)
        _assert_french(self, str(resp.json()))

    def test_create_order_service_validation_is_french(self):
        from orders.services.create_order import create_order

        with self.assertRaises(ValidationError) as cm:
            create_order({"items": []})
        _assert_french(self, str(cm.exception))

    def test_login_failure_message_is_french(self):
        resp = self.api.post(
            "/api/v1/auth/login/",
            {"phone": "+22370000000", "password": "mauvais"},
            format="json",
        )
        _assert_french(self, str(resp.content.decode()))
