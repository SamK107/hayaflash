"""Actions vendeur sur les commandes : export CSV, confirmation et livraison groupees.

Chaque action doit rester limitee aux ventes du vendeur connecte et aux statuts
attendus (une commande en attente ne passe pas directement a « livree »).
"""

from __future__ import annotations

import csv
import io
from uuid import uuid4

from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from delivery.tests import DeliveryTestFixture
from orders.models import Order, OrderStatus


class SellerActionsBase(DeliveryTestFixture):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.client = Client()
        self.client.force_login(self.seller_user)

    def _place(self, name, phone, sale=None):
        """Commande creee par la voie publique (API), donc avec lignes et livraison."""
        body = self._order_body(
            name=name, phone=phone, client_request_id=str(uuid4()), quantity=1
        )
        if sale is not None:
            body["flash_sale_id"] = sale.pk
        resp = self.api.post("/api/v1/orders/", body, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        return Order.service_objects.get(pk=resp.data["id"])

    def _foreign_order(self):
        from datetime import timedelta

        from django.utils import timezone

        from flash_sales.models import FlashSale, FlashSaleStatus

        now = timezone.now()
        sale = FlashSale.objects.create(
            title="Vente etrangere",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            status=FlashSaleStatus.LIVE,
            owner=self.other_user.seller_profile,
        )
        return Order.service_objects.create(
            flash_sale=sale, customer_name="Intrus", customer_phone="+22370000999"
        )


class ExportCsvTests(SellerActionsBase):
    def _url(self, sale):
        return reverse("orders:export_orders_csv", args=[sale.pk])

    def test_exporte_les_commandes_de_la_vente(self):
        self._place("Aminata", "+22370111111")
        self._place("Fanta", "+22370222222")
        resp = self.client.get(self._url(self.sale))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        self.assertIn(f"commandes-{self.sale.public_slug}.csv", resp["Content-Disposition"])
        rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig"))))
        self.assertEqual(rows[0][:3], ["#", "Client", "Téléphone"])
        self.assertEqual([r[1] for r in rows[1:]], ["Aminata", "Fanta"])
        self.assertIn("Widget x1", rows[1][3])
        self.assertEqual(rows[1][4], "1999")
        self.assertEqual(rows[1][5], "En attente")

    def test_vente_d_un_autre_vendeur_est_introuvable(self):
        foreign = self._foreign_order().flash_sale
        self.assertEqual(self.client.get(self._url(foreign)).status_code, 404)

    def test_compte_sans_boutique_est_redirige_sans_erreur(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(
            phone="+22390000077", password="x", display_name="Sans boutique"
        )
        self.client.force_login(user)
        resp = self.client.get(self._url(self.sale))
        self.assertEqual(resp.status_code, 302)

    def test_post_refuse(self):
        self.assertEqual(self.client.post(self._url(self.sale)).status_code, 405)


class BulkActionsTests(SellerActionsBase):
    def test_confirmation_groupee_ne_touche_que_mes_commandes_en_attente(self):
        mine1 = self._place("A", "+22370333331")
        mine2 = self._place("B", "+22370333332")
        already = self._place("C", "+22370333333")
        Order.service_objects.filter(pk=already.pk).update(status=OrderStatus.DELIVERED)
        foreign = self._foreign_order()
        resp = self.client.post(
            reverse("orders:bulk_confirm_orders"),
            {"order_ids": [mine1.pk, mine2.pk, already.pk, foreign.pk]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("2 commande(s) confirmée(s).", resp.content.decode())
        for o in (mine1, mine2, already, foreign):
            o.refresh_from_db()
        self.assertEqual(mine1.status, OrderStatus.CONFIRMED)
        self.assertEqual(mine2.status, OrderStatus.CONFIRMED)
        self.assertEqual(already.status, OrderStatus.DELIVERED)
        self.assertEqual(foreign.status, OrderStatus.PENDING)

    def test_livraison_groupee_exige_le_statut_confirme(self):
        pending = self._place("D", "+22370444441")
        confirmed = self._place("E", "+22370444442")
        Order.service_objects.filter(pk=confirmed.pk).update(status=OrderStatus.CONFIRMED)
        resp = self.client.post(
            reverse("orders:bulk_mark_delivered"),
            {"order_ids": [pending.pk, confirmed.pk]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("1 commande(s) marquée(s) livrée(s).", resp.content.decode())
        pending.refresh_from_db()
        confirmed.refresh_from_db()
        self.assertEqual(pending.status, OrderStatus.PENDING)
        self.assertEqual(confirmed.status, OrderStatus.DELIVERED)

    def test_selection_vide_refusee(self):
        for name in ("orders:bulk_confirm_orders", "orders:bulk_mark_delivered"):
            with self.subTest(name=name):
                resp = self.client.post(reverse(name), {})
                self.assertEqual(resp.status_code, 400)

    def test_compte_sans_boutique_recoit_403(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(
            phone="+22390000078", password="x", display_name="Sans boutique"
        )
        self.client.force_login(user)
        for name in ("orders:bulk_confirm_orders", "orders:bulk_mark_delivered"):
            with self.subTest(name=name):
                resp = self.client.post(reverse(name), {"order_ids": [1]})
                self.assertEqual(resp.status_code, 403)

    def test_get_refuse(self):
        self.assertEqual(self.client.get(reverse("orders:bulk_confirm_orders")).status_code, 405)


class AdvanceStatusViewTests(SellerActionsBase):
    def _url(self, order):
        return reverse("orders:seller_order_advance_status", args=[order.pk])

    def test_fait_avancer_la_commande_et_renvoie_la_ligne(self):
        order = self._place("F", "+22370555551")
        resp = self.client.post(self._url(order))
        self.assertEqual(resp.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CONFIRMED)

    def test_commande_d_un_autre_vendeur_est_refusee(self):
        foreign = self._foreign_order()
        resp = self.client.post(self._url(foreign))
        self.assertIn(resp.status_code, (400, 403))
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, OrderStatus.PENDING)

    def test_compte_sans_boutique_recoit_403(self):
        from django.contrib.auth import get_user_model

        order = self._place("G", "+22370555552")
        user = get_user_model().objects.create_user(
            phone="+22390000079", password="x", display_name="Sans boutique"
        )
        self.client.force_login(user)
        self.assertEqual(self.client.post(self._url(order)).status_code, 403)
