"""Circuit unique Commandes / Livraison.

Cause du bug « anciennes commandes qui ne réagissent plus sur Livraison » :
1. des commandes anciennes n'ont pas de fiche de livraison (elles avançaient dans
   Commandes mais restaient invisibles et sans action sur Livraison) ;
2. la page Commandes faisait avancer la commande sans la livraison (« livré » en
   groupe, synchro qui avalait ses erreurs) : statuts divergents, boutons absents ;
3. deux chemins de statuts : l'enregistrement des échecs (F-59) pouvait être contourné.

Désormais : Commandes = Confirmer / Annuler ; Livraison = tout le reste ; un seul service.
"""

from __future__ import annotations

from io import StringIO
from uuid import uuid4

from django.core.cache import cache
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from delivery.models import Delivery
from delivery.services.delivery import ensure_delivery_for_order
from delivery.tests import DeliveryTestFixture
from orders.models import Order, OrderItem, OrderStatus, UnhonoredOrder
from orders.services.dashboard import list_dashboard_order_rows


class Base(DeliveryTestFixture):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.c = Client()
        self.c.force_login(self.seller_user)

    def place(self, phone="+22370111111"):
        resp = self.api.post(
            "/api/v1/orders/",
            self._order_body(phone=phone, quantity=1, client_request_id=str(uuid4())),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        return Order.service_objects.get(pk=resp.data["id"])

    def legacy_order(self):
        """Commande ancienne : lignes mais aucune fiche de livraison."""
        order = Order.service_objects.create(
            flash_sale=self.sale, customer_name="Ancienne", customer_phone="+22370999999"
        )
        OrderItem.objects.create(
            order=order, product=self.product, product_name_snapshot="Widget",
            price_snapshot=1999, quantity=1,
        )
        return order

    def commande(self, order, name="seller_order_advance_status"):
        return self.c.post(reverse(f"orders:{name}", args=[order.pk]))

    def livraison(self, order, action, **data):
        delivery = Delivery.objects.get(order_id=order.pk)
        return self.c.post(
            reverse("orders:seller_delivery_action", args=[delivery.pk]),
            {"action": action, **data},
            HTTP_HX_REQUEST="true",
        )

    def refresh(self, *objs):
        for o in objs:
            o.refresh_from_db()


class LegacyOrdersTests(Base):
    def test_commande_ancienne_sans_fiche_confirme_puis_apparait_sur_livraison(self):
        order = self.legacy_order()
        self.assertFalse(Delivery.objects.filter(order=order).exists())
        self.assertEqual(self.commande(order).status_code, 200)
        self.refresh(order)
        self.assertEqual(order.status, OrderStatus.CONFIRMED)
        delivery = Delivery.objects.get(order=order)  # créée au passage, même service
        self.assertEqual(int(delivery.cod_amount), 1999)
        html = self.c.get(
            reverse("orders:seller_deliveries_list"), {"flash_sale_id": self.sale.pk}
        ).content.decode()
        self.assertIn(f"delivery-row-{delivery.pk}", html)

    def test_la_page_livraison_cree_les_fiches_manquantes_de_la_vente(self):
        order = self.legacy_order()
        Order.service_objects.filter(pk=order.pk).update(status=OrderStatus.CONFIRMED)
        html = self.c.get(
            reverse("orders:seller_deliveries_list"), {"flash_sale_id": self.sale.pk}
        ).content.decode()
        self.assertIn("Ancienne", html)
        self.assertEqual(
            self.livraison(order, "start_delivery", assigned_to="Moussa").status_code, 200
        )
        self.refresh(order)
        self.assertEqual(order.status, OrderStatus.OUT_FOR_DELIVERY)

    def test_ensure_delivery_est_idempotent(self):
        order = self.legacy_order()
        d1, created1 = ensure_delivery_for_order(order)
        d2, created2 = ensure_delivery_for_order(order)
        self.assertEqual((created1, created2, d1.pk), (True, False, d2.pk))


class RepairCommandTests(Base):
    def run_cmd(self, *args):
        out = StringIO()
        call_command("repair_order_deliveries", *args, stdout=out)
        return out.getvalue()

    def setUp(self):
        super().setUp()
        self.legacy = self.legacy_order()
        Order.service_objects.filter(pk=self.legacy.pk).update(status=OrderStatus.CONFIRMED)
        self.divergent = self.place("+22370222222")
        Order.service_objects.filter(pk=self.divergent.pk).update(status=OrderStatus.DELIVERED)
        self.cancelled = self.legacy_order()
        Order.service_objects.filter(pk=self.cancelled.pk).update(status=OrderStatus.CANCELLED)

    def test_dry_run_ne_modifie_rien(self):
        out = self.run_cmd("--dry-run")
        self.assertIn("[dry-run]", out)
        self.assertFalse(Delivery.objects.filter(order=self.legacy).exists())
        self.assertEqual(Delivery.objects.get(order=self.divergent).status, Delivery.Status.PENDING)

    def test_applique_puis_idempotent_sans_toucher_aux_annulees(self):
        self.run_cmd()
        self.assertTrue(Delivery.objects.filter(order=self.legacy).exists())
        self.assertFalse(Delivery.objects.filter(order=self.cancelled).exists())
        d = Delivery.objects.get(order=self.divergent)
        self.assertEqual(d.status, Delivery.Status.DELIVERED)
        self.assertFalse(d.cod_collected)  # jamais d'encaissement inventé
        out = self.run_cmd()
        self.assertIn("0 fiche(s) créée(s), 0 réalignée(s) 'livré', 0 réalignée(s) 'en livraison'", out)


class OrdersPageTransitionsTests(Base):
    def test_confirmer_puis_etapes_suivantes_refusees(self):
        order = self.place()
        self.assertEqual(self.commande(order).status_code, 200)
        self.refresh(order)
        self.assertEqual(order.status, OrderStatus.CONFIRMED)
        resp = self.commande(order)
        self.assertEqual(resp.status_code, 403)
        self.assertIn("page Livraison", resp.content.decode())
        self.refresh(order)
        self.assertEqual(order.status, OrderStatus.CONFIRMED)

    def test_livraison_groupee_refusee(self):
        order = self.place()
        Order.service_objects.filter(pk=order.pk).update(status=OrderStatus.CONFIRMED)
        resp = self.c.post(reverse("orders:bulk_mark_delivered"), {"order_ids": [order.pk]})
        self.assertEqual(resp.status_code, 403)
        self.refresh(order)
        self.assertEqual(order.status, OrderStatus.CONFIRMED)

    def test_annuler_rend_le_stock_une_seule_fois(self):
        order = self.place()
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_available, 9)
        self.assertEqual(self.commande(order, "seller_order_cancel").status_code, 200)
        self.refresh(order, self.product)
        self.assertEqual((order.status, self.product.stock_available), (OrderStatus.CANCELLED, 10))
        self.assertEqual(self.commande(order, "seller_order_cancel").status_code, 400)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_available, 10)

    def test_annuler_apres_mise_en_livraison_refuse(self):
        order = self.place()
        self.commande(order)
        self.livraison(order, "start_delivery", assigned_to="Moussa")
        resp = self.commande(order, "seller_order_cancel")
        self.assertEqual(resp.status_code, 400)
        self.refresh(order)
        self.assertEqual(order.status, OrderStatus.OUT_FOR_DELIVERY)

    def test_annuler_commande_d_une_autre_vendeuse_refuse(self):
        order = self.place()
        other = Client()
        other.force_login(self.other_user)
        self.assertEqual(
            other.post(reverse("orders:seller_order_cancel", args=[order.pk])).status_code, 403
        )
        self.refresh(order)
        self.assertEqual(order.status, OrderStatus.PENDING)

    def test_confirmer_en_groupe_passe_par_le_service(self):
        order = self.legacy_order()
        resp = self.c.post(reverse("orders:bulk_confirm_orders"), {"order_ids": [order.pk]})
        self.assertIn("1 commande(s) confirmée(s).", resp.content.decode())
        self.assertTrue(Delivery.objects.filter(order=order).exists())


class DeliveryPageTransitionsTests(Base):
    def test_confirmer_et_annuler_refuses_sur_la_page_livraison(self):
        order = self.place()
        for action in ("confirm", "cancel"):
            with self.subTest(action=action):
                resp = self.livraison(order, action)
                self.assertEqual(resp.status_code, 400)
                self.assertIn("Commandes", resp.content.decode())
        self.refresh(order)
        self.assertEqual(order.status, OrderStatus.PENDING)

    def test_pas_de_livraison_ni_echec_avant_confirmation(self):
        order = self.place()
        self.assertEqual(
            self.livraison(order, "start_delivery", assigned_to="Moussa").status_code, 400
        )
        self.assertEqual(self.livraison(order, "mark_failed").status_code, 400)
        self.assertEqual(UnhonoredOrder.objects.count(), 0)

    def test_parcours_complet_livre_et_paye(self):
        order = self.place()
        self.commande(order)
        self.assertEqual(
            self.livraison(order, "start_delivery", assigned_to="Moussa").status_code, 200
        )
        self.assertEqual(
            self.livraison(order, "mark_delivered", cod_collected="true").status_code, 200
        )
        self.refresh(order)
        d = Delivery.objects.get(order=order)
        self.assertEqual((order.status, d.status, d.cod_collected), (OrderStatus.DELIVERED, "delivered", True))

    def test_echec_declenche_f59(self):
        order = self.place("+22370333333")
        self.commande(order)
        self.assertEqual(self.livraison(order, "mark_failed").status_code, 200)
        record = UnhonoredOrder.objects.get()
        self.assertEqual(record.order_id, order.pk)
        self.assertEqual(Delivery.objects.get(order=order).status, Delivery.Status.FAILED)

    def test_la_page_livraison_n_affiche_plus_de_bouton_confirmer(self):
        self.place()
        html = self.c.get(
            reverse("orders:seller_deliveries_list"), {"flash_sale_id": self.sale.pk}
        ).content.decode()
        self.assertIn("À confirmer d", html)
        self.assertNotIn('"action": "confirm"', html)


class OrderCardTests(Base):
    def card(self, order):
        row = next(
            r for r in list_dashboard_order_rows(self.seller_user) if r["order"].pk == order.pk
        )
        return row, self.c.get(reverse("orders:seller_dashboard_orders")).content.decode()

    def test_en_attente_confirmer_et_annuler(self):
        order = self.place()
        row, html = self.card(order)
        self.assertEqual(row["state_label"], "En attente")
        self.assertTrue(row["can_confirm"] and row["can_cancel"])
        self.assertIn(reverse("orders:seller_order_cancel", args=[order.pk]), html)

    def test_confirmee_a_livrer_avec_lien_vers_la_livraison(self):
        order = self.place()
        self.commande(order)
        row, html = self.card(order)
        delivery = Delivery.objects.get(order=order)
        self.assertEqual(row["state_label"], "À livrer")
        expected = (
            f"{reverse('orders:seller_deliveries_dashboard')}"
            f"?flash_sale_id={self.sale.pk}#delivery-row-{delivery.pk}"
        )
        self.assertEqual(row["delivery_url"], expected)
        self.assertIn("Gérer la livraison →", html)
        self.assertIn(expected, html)
        self.assertNotIn(reverse("orders:seller_order_advance_status", args=[order.pk]), html)

    def test_etats_en_lecture_seule(self):
        cases = [
            (OrderStatus.OUT_FOR_DELIVERY, Delivery.Status.IN_TRANSIT, False, "En livraison", "gray"),
            (OrderStatus.DELIVERED, Delivery.Status.DELIVERED, True, "Livré et payé", "green"),
            (OrderStatus.DELIVERED, Delivery.Status.DELIVERED, False, "Livré, à encaisser", "amber"),
            (OrderStatus.OUT_FOR_DELIVERY, Delivery.Status.FAILED, False, "Échec", "red"),
        ]
        for i, (o_status, d_status, collected, label, tone) in enumerate(cases):
            with self.subTest(label=label, collected=collected):
                order = self.place(f"+2237044000{i}")
                self.commande(order)
                Order.service_objects.filter(pk=order.pk).update(status=o_status)
                Delivery.objects.filter(order=order).update(status=d_status, cod_collected=collected)
                row, html = self.card(order)
                self.assertEqual((row["state_label"], row["state_tone"]), (label, tone))
                self.assertFalse(row["can_confirm"] or row["show_delivery_link"])
                self.assertNotIn(reverse("orders:seller_order_advance_status", args=[order.pk]), html)

    def test_badge_livraison_compte_les_commandes_a_livrer(self):
        from core.context_processors import _compute_nav_counts

        a, b = self.place("+22370555551"), self.place("+22370555552")
        self.place("+22370555553")  # reste en attente : non comptée
        self.commande(a)
        self.commande(b)
        self.livraison(b, "mark_failed")  # échec : n'est plus « à livrer »
        self.assertEqual(_compute_nav_counts(self.seller)["deliveries_active_count"], 1)
        html = self.c.get(reverse("orders:seller_dashboard")).content.decode()
        self.assertIn('data-nav-badge="deliveries"', html)
