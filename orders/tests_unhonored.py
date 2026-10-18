"""F-59 / D2 : blocage d'un numero apres 3 commandes non honorees en 30 jours.

« Non honoree » = livraison marquee « Echec » par la vendeuse (refusee ou
cliente injoignable). Une commande annulee par la vendeuse ne compte pas.
Le blocage vaut pour toutes les boutiques ; une vendeuse le leve pour la sienne,
l'administration pour toutes.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from delivery.models import Delivery
from delivery.tests import DeliveryTestFixture
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order, OrderStatus, PhoneUnblock, UnhonoredOrder
from orders.services.unhonored import (
    PHONE_BLOCKED_MESSAGE,
    UNHONORED_ORDERS_THRESHOLD,
    UNHONORED_WINDOW_DAYS,
    is_phone_blocked,
    phone_key,
)
from products.models import FlashSaleProduct, Product

PHONE = "+22370123456"
ORDERS_URL = "/api/v1/orders/"


class UnhonoredBase(DeliveryTestFixture):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.seller_client = Client()
        self.seller_client.force_login(self.seller_user)

    def place(self, phone=PHONE, sale=None, product=None):
        body = self._order_body(phone=phone, quantity=1, client_request_id=str(uuid4()))
        if sale is not None:
            body["flash_sale_id"] = sale.pk
        if product is not None:
            body["product_id"] = product.pk
        return self.api.post(ORDERS_URL, body, format="json")

    def fail_delivery(self, order_id, client=None):
        delivery = Delivery.objects.get(order_id=order_id)
        resp = (client or self.seller_client).post(
            reverse("orders:seller_delivery_action", args=[delivery.pk]),
            {"action": "mark_failed"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        return delivery

    def fail_n(self, n, phone=PHONE):
        ids = []
        for _ in range(n):
            resp = self.place(phone)
            self.assertEqual(resp.status_code, 201, resp.content)
            self.fail_delivery(resp.data["id"])
            ids.append(resp.data["id"])
        return ids

    def second_seller(self):
        """Autre boutique avec une vente en direct (l'autre vendeuse du fixture)."""
        now = timezone.now()
        sale = FlashSale.objects.create(
            title="Vente B", start_time=now - timedelta(hours=1), end_time=now + timedelta(hours=1),
            status=FlashSaleStatus.LIVE, owner=self.other_user.seller_profile,
        )
        product = Product.objects.create(
            owner=self.other_user.seller_profile, name="Autre", stock_available=10,
            stock_initial=10, price=1000,
        )
        FlashSaleProduct.objects.create(flash_sale=sale, product=product)
        return sale, product


class BlockingRuleTests(UnhonoredBase):
    def test_constantes_de_la_decision(self):
        self.assertEqual(UNHONORED_ORDERS_THRESHOLD, 3)
        self.assertEqual(UNHONORED_WINDOW_DAYS, 30)

    def test_pas_bloque_avant_le_troisieme_echec(self):
        self.fail_n(2)
        self.assertFalse(is_phone_blocked(PHONE, self.seller.pk))
        self.assertEqual(self.place().status_code, 201)

    def test_bloque_au_troisieme_echec_avec_message_neutre(self):
        self.fail_n(3)
        self.assertTrue(is_phone_blocked(PHONE, self.seller.pk))
        resp = self.place()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["detail"], [PHONE_BLOCKED_MESSAGE])
        self.assertEqual(PHONE_BLOCKED_MESSAGE, "Ce numéro ne peut plus commander pour le moment. Contacte la boutique.")

    def test_les_formats_du_numero_comptent_pareil(self):
        self.fail_n(3)
        for variant in ("70 12 34 56", "+223 70 12 34 56", "0022370123456"):
            with self.subTest(variant=variant):
                self.assertTrue(is_phone_blocked(variant, self.seller.pk))
        self.assertEqual(phone_key("+223 70 12 34 56"), "70123456")

    def test_un_autre_numero_n_est_pas_touche(self):
        self.fail_n(3)
        self.assertEqual(self.place("+22371999999").status_code, 201)

    def test_un_rejeu_idempotent_n_est_pas_refuse(self):
        first = self.place()
        self.assertEqual(first.status_code, 201)
        cid = first.data["client_request_id"]
        self.fail_n(3)
        body = self._order_body(phone=PHONE, quantity=1, client_request_id=cid)
        again = self.api.post(ORDERS_URL, body, format="json")
        self.assertEqual(again.status_code, 200, again.content)
        self.assertTrue(again.data.get("already_exists"))

    def test_le_blocage_vaut_pour_les_autres_boutiques(self):
        self.fail_n(3)
        sale, product = self.second_seller()
        resp = self.place(sale=sale, product=product)
        self.assertEqual(resp.status_code, 400)

    def test_un_echec_marque_deux_fois_ne_compte_qu_une_fois(self):
        ids = self.fail_n(2)
        order = Order.service_objects.get(pk=ids[0])
        from orders.services.unhonored import record_unhonored_order

        record_unhonored_order(order)
        self.assertEqual(UnhonoredOrder.objects.filter(order=order).count(), 1)
        self.assertFalse(is_phone_blocked(PHONE, self.seller.pk))

    def test_une_livraison_reussie_ne_compte_pas(self):
        for _ in range(3):
            resp = self.place()
            Order.service_objects.filter(pk=resp.data["id"]).update(status=OrderStatus.DELIVERED)
        self.assertEqual(UnhonoredOrder.objects.count(), 0)
        self.assertEqual(self.place().status_code, 201)


class WindowAndCancelTests(UnhonoredBase):
    def test_les_echecs_de_plus_de_30_jours_expirent(self):
        self.fail_n(3)
        UnhonoredOrder.objects.update(created_at=timezone.now() - timedelta(days=UNHONORED_WINDOW_DAYS + 1))
        self.assertFalse(is_phone_blocked(PHONE, self.seller.pk))
        self.assertEqual(self.place().status_code, 201)

    def test_un_echec_juste_dans_la_fenetre_compte_encore(self):
        self.fail_n(3)
        UnhonoredOrder.objects.update(created_at=timezone.now() - timedelta(days=UNHONORED_WINDOW_DAYS - 1))
        self.assertTrue(is_phone_blocked(PHONE, self.seller.pk))

    def test_une_commande_annulee_par_la_vendeuse_ne_compte_pas(self):
        ids = self.fail_n(3)
        self.assertTrue(is_phone_blocked(PHONE, self.seller.pk))
        Order.service_objects.filter(pk=ids[0]).update(status=OrderStatus.CANCELLED)
        self.assertFalse(is_phone_blocked(PHONE, self.seller.pk))
        self.assertEqual(self.place().status_code, 201)


class UnblockTests(UnhonoredBase):
    def unblock_url(self, order_id):
        return reverse("orders:seller_unblock_phone", args=[order_id])

    def test_la_vendeuse_voit_le_blocage_dans_ses_commandes(self):
        self.fail_n(3)
        html = self.seller_client.get(reverse("orders:seller_dashboard_orders")).content.decode()
        self.assertIn("Numéro bloqué pour les nouvelles commandes", html)
        self.assertIn("Débloquer ce numéro pour ma boutique", html)

    def test_pas_de_bandeau_sans_blocage(self):
        self.fail_n(1)
        html = self.seller_client.get(reverse("orders:seller_dashboard_orders")).content.decode()
        self.assertNotIn("Numéro bloqué", html)

    def test_la_vendeuse_debloque_pour_sa_boutique_seulement(self):
        ids = self.fail_n(3)
        resp = self.seller_client.post(self.unblock_url(ids[0]), HTTP_HX_REQUEST="true")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("Numéro bloqué", resp.content.decode())
        self.assertEqual(self.place().status_code, 201)
        # L'autre boutique reste protegee.
        sale, product = self.second_seller()
        self.assertEqual(self.place(sale=sale, product=product).status_code, 400)

    def test_apres_deblocage_un_nouveau_cycle_de_3_echecs_rebloque(self):
        ids = self.fail_n(3)
        self.seller_client.post(self.unblock_url(ids[0]))
        self.fail_n(2)
        self.assertFalse(is_phone_blocked(PHONE, self.seller.pk))
        self.fail_n(1)
        self.assertTrue(is_phone_blocked(PHONE, self.seller.pk))

    def test_une_vendeuse_ne_peut_pas_debloquer_via_la_commande_d_une_autre(self):
        ids = self.fail_n(3)
        other = Client()
        other.force_login(self.other_user)
        resp = other.post(self.unblock_url(ids[0]))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(PhoneUnblock.objects.count(), 0)
        self.assertTrue(is_phone_blocked(PHONE, self.seller.pk))

    def test_compte_sans_boutique_recoit_403(self):
        ids = self.fail_n(3)
        user = get_user_model().objects.create_user(phone="+22390000055", password="x", display_name="X")
        c = Client()
        c.force_login(user)
        self.assertEqual(c.post(self.unblock_url(ids[0])).status_code, 403)

    def test_get_refuse(self):
        ids = self.fail_n(3)
        self.assertEqual(self.seller_client.get(self.unblock_url(ids[0])).status_code, 405)

    def test_l_admin_debloque_globalement(self):
        self.fail_n(3)
        admin = get_user_model().objects.create_superuser(phone="+22390000099", password="x", display_name="Admin")
        c = Client()
        c.force_login(admin)
        record = UnhonoredOrder.objects.first()
        resp = c.post(
            reverse("admin:orders_unhonoredorder_changelist"),
            {"action": "unblock_selected_phones", "_selected_action": [record.pk]},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PhoneUnblock.objects.filter(seller__isnull=True).count(), 1)
        self.assertFalse(is_phone_blocked(PHONE, self.seller.pk))
        sale, product = self.second_seller()
        self.assertEqual(self.place(sale=sale, product=product).status_code, 201)


class VerificationCostTests(UnhonoredBase):
    def test_la_verification_a_la_commande_reste_legere(self):
        with self.assertNumQueries(1):
            self.assertFalse(is_phone_blocked(PHONE, self.seller.pk))

    def test_la_liste_des_commandes_ne_fait_pas_de_requete_par_ligne(self):
        from orders.services.dashboard import list_dashboard_order_rows

        for i in range(6):
            self.place(f"+2237012000{i}")
        with self.assertNumQueries(3):  # commandes, lignes, comptage des echecs
            rows = list_dashboard_order_rows(self.seller_user)
        self.assertEqual(len(rows), 6)
        self.assertFalse(any(r["phone_blocked"] for r in rows))
