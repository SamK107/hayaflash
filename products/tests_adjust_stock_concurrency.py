"""`adjust_stock` face aux commandes simultanees (docs/INCIDENTS.md, « À évaluer — hors Distrib »).

Defaut : `adjust_stock` calculait son delta sur la valeur lue EN MEMOIRE (sans verrou) puis ecrivait
une valeur absolue. Une commande (ou un autre ajustement) passee entre la lecture et l'ecriture
rendait le `StockMovement` faux : la somme des mouvements ne correspondait plus au stock.

Invariant verifie : `stock_available == somme des StockMovement` (le stock initial est un mouvement),
stock jamais negatif, aucune survente.

La classe de concurrence exige PostgreSQL (SQLite verrouille toute la base et ignore
`select_for_update`) : elle est ignoree en SQLite et s'execute avec
`pytest --ds=config.settings.test_pg products/tests_adjust_stock_concurrency.py`.
"""

from __future__ import annotations

import threading
from datetime import timedelta
from decimal import Decimal
from unittest import skipIf

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.db.models import Sum
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order
from orders.services.create_order import create_order
from products.models import Product, StockMovement
from products.services.crud import adjust_stock, attach_product_to_sale, create_product

User = get_user_model()

START_STOCK = 20



class AdjustStockFixture:
    def make_fixture(self):
        user = User.objects.create_user(phone="+22370000001", password="x", display_name="Awa")
        self.seller = SellerProfile.objects.create(user=user, business_name="Boutique Awa")
        now = timezone.now()
        self.sale = FlashSale.objects.create(
            owner=self.seller, title="Live", start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=1), status=FlashSaleStatus.LIVE,
        )
        self.product = create_product(
            owner=self.seller, name="Robe", price=Decimal("5000"), stock=START_STOCK
        )
        attach_product_to_sale(flash_sale=self.sale, product=self.product)

    def order(self, n: int, qty: int = 1) -> None:
        create_order(
            {
                "flash_sale_id": self.sale.pk, "customer_name": "Cliente",
                "customer_phone": f"+2237600{n:04d}", "client_request_id": f"adj-{n}",
                "items": [{"product_id": self.product.pk, "quantity": qty}],
                "delivery": {"address_text": "Hamdallaye ACI, Bamako", "geo_method": "manual"},
            }
        )

    def assert_stock_matches_movements(self):
        product = Product.objects.get(pk=self.product.pk)
        moved = StockMovement.objects.filter(product=product).aggregate(t=Sum("quantity_change"))["t"]
        self.assertGreaterEqual(product.stock_available, 0)
        self.assertEqual(
            moved, product.stock_available,
            "la somme des mouvements de stock ne correspond plus au stock disponible",
        )
        return product


class AdjustStockStaleValueTests(AdjustStockFixture, TestCase):
    """Cas de la valeur perimee en memoire (deterministe, sans thread : tourne aussi en SQLite)."""

    def setUp(self):
        self.make_fixture()

    def test_stale_product_instance_gives_a_correct_movement(self):
        stale = Product.objects.get(pk=self.product.pk)  # voit 20, comme la vue Publication rapide
        for n in range(3):
            self.order(n)  # base : 17
        adjust_stock(product=stale, new_stock_available=25)
        product = self.assert_stock_matches_movements()
        self.assertEqual(product.stock_available, 25)
        last = StockMovement.objects.filter(product=product, movement_type="correction").get()
        self.assertEqual(last.quantity_change, 8)  # 25 - 17 reellement en base, pas 25 - 20

    def test_stale_decrease_never_goes_negative_nor_loses_orders(self):
        stale = Product.objects.get(pk=self.product.pk)
        for n in range(5):
            self.order(n)  # base : 15
        adjust_stock(product=stale, new_stock_available=2)
        product = self.assert_stock_matches_movements()
        self.assertEqual(product.stock_available, 2)

    def test_returned_product_reflects_the_new_stock(self):
        result = adjust_stock(product=self.product, new_stock_available=7)
        self.assertEqual(result.stock_available, 7)
        self.assertEqual(Product.objects.get(pk=self.product.pk).stock_available, 7)

    def test_noop_and_negative_behaviour_is_unchanged(self):
        adjust_stock(product=self.product, new_stock_available=START_STOCK)
        self.assertFalse(StockMovement.objects.filter(movement_type="correction").exists())
        with self.assertRaises(ValidationError):
            adjust_stock(product=self.product, new_stock_available=-1)
        self.assertEqual(Product.objects.get(pk=self.product.pk).stock_available, START_STOCK)


@skipIf(connection.vendor == "sqlite", "La concurrence exige PostgreSQL (--ds=config.settings.test_pg)")
class AdjustStockConcurrencyTests(AdjustStockFixture, TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.make_fixture()

    def test_simultaneous_adjustments_and_orders(self):
        targets = [15, 18, 12, 25]
        orders = 6
        # Comme la vue Publication rapide : chaque ajustement part d'une instance lue AVANT les autres.
        stale = [Product.objects.get(pk=self.product.pk) for _ in targets]
        jobs = [("order", lambda n=n: self.order(n)) for n in range(orders)] + [
            ("adjust", lambda p=p, t=t: adjust_stock(product=p, new_stock_available=t))
            for p, t in zip(stale, targets)
        ]
        barrier = threading.Barrier(len(jobs))
        results: list[tuple[str, bool]] = []
        lock = threading.Lock()

        def worker(kind, fn):
            close_old_connections()
            try:
                barrier.wait()
                try:
                    fn()
                    ok = True
                except ValidationError:
                    ok = False  # refus metier legitime (stock insuffisant)
                with lock:
                    results.append((kind, ok))
            finally:
                close_old_connections()

        threads = [threading.Thread(target=worker, args=job) for job in jobs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), len(jobs), "un thread a plante avec une exception inattendue")
        orders_ok = sum(1 for k, ok in results if k == "order" and ok)
        self.assertEqual(Order.service_objects.count(), orders_ok)
        self.assert_stock_matches_movements()
        # Aucune survente : jamais plus d'unites reservees que de stock mis a disposition.
        reserved = -StockMovement.objects.filter(
            product=self.product, movement_type="reservation"
        ).aggregate(t=Sum("quantity_change"))["t"]
        self.assertEqual(reserved, orders_ok)


def _mutations(products_and_stocks):
    return {"mutations": [{"product_id": p.pk, "stock": s} for p, s in products_and_stocks]}


class BulkUpdateLockOrderTests(AdjustStockFixture, TestCase):
    """bulk_update verrouille les produits comme create_order (ids croissants) sans changer la reponse."""

    def setUp(self):
        self.make_fixture()
        self.a = self.product
        self.b = create_product(owner=self.seller, name="Sac", price=Decimal("3000"), stock=10)
        self.c = create_product(owner=self.seller, name="Pagne", price=Decimal("2000"), stock=10)
        self.assertLess(self.a.pk, self.b.pk)
        self.assertLess(self.b.pk, self.c.pk)
        self.api = APIClient()
        self.api.force_authenticate(user=self.seller.user)
        self.url = reverse("flashsaleproduct-bulk-update", kwargs={"flash_sale_pk": self.sale.pk})

    def test_products_are_locked_in_ascending_id_order_before_any_write(self):
        payload = _mutations([(self.c, 5), (self.a, 6), (self.b, 7)])  # ordre d'envoi decroissant/melange
        with CaptureQueriesContext(connection) as ctx:
            res = self.api.post(self.url, payload, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        sqls = [q["sql"] for q in ctx.captured_queries]
        lock_idx = next(
            i for i, s in enumerate(sqls)
            if s.startswith("SELECT") and '"products_product"' in s and ' IN (' in s and "ORDER BY" in s
        )
        lock_sql = sqls[lock_idx]
        self.assertRegex(lock_sql, r'ORDER BY (1|"products_product"\."id") ASC')
        if connection.features.has_select_for_update:
            self.assertIn("FOR UPDATE", lock_sql)
        # Rien n'est ecrit sur un produit avant que tous les verrous soient poses.
        first_write = next(i for i, s in enumerate(sqls) if s.startswith('UPDATE "products_product"'))
        self.assertLess(lock_idx, first_write)

    def test_response_order_and_content_follow_the_request_order(self):
        payload = _mutations([(self.c, 5), (self.a, 6), (self.b, 7)])
        res = self.api.post(self.url, payload, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(
            res.data["results"],
            [
                {"index": 0, "product_id": self.c.pk},
                {"index": 1, "product_id": self.a.pk},
                {"index": 2, "product_id": self.b.pk},
            ],
        )
        self.assertEqual((res.data["created_count"], res.data["updated_count"]), (0, 3))
        for product, stock in ((self.a, 6), (self.b, 7), (self.c, 5)):
            self.assertEqual(Product.objects.get(pk=product.pk).stock_available, stock)

    def test_mixed_new_and_existing_and_foreign_ids_keep_working(self):
        foreign = create_product(owner=SellerProfile.objects.create(
            user=User.objects.create_user(phone="+22370000009", password="x", display_name="Autre")),
            name="Autre", price=Decimal("100"), stock=3)
        payload = {
            "mutations": [
                {"product_new": {"name": "Neuf", "price": "1500", "stock": 4}},
                {"product_id": self.b.pk, "stock": 2},
                {"product_id": foreign.pk, "stock": 99},  # pas a moi : erreur par ligne, lot annule
            ]
        }
        res = self.api.post(self.url, payload, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual([e["index"] for e in res.data["errors"]], [2])
        self.assertFalse(Product.objects.filter(name="Neuf").exists())
        self.assertEqual(Product.objects.get(pk=self.b.pk).stock_available, 10)
        self.assertEqual(Product.objects.get(pk=foreign.pk).stock_available, 3)


@skipIf(connection.vendor == "sqlite", "La concurrence exige PostgreSQL (--ds=config.settings.test_pg)")
class BulkUpdateDeadlockTests(AdjustStockFixture, TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.make_fixture()
        self.b = create_product(owner=self.seller, name="Sac", price=Decimal("3000"), stock=10)
        attach_product_to_sale(flash_sale=self.sale, product=self.b)
        self.api = APIClient()
        self.api.force_authenticate(user=self.seller.user)
        self.url = reverse("flashsaleproduct-bulk-update", kwargs={"flash_sale_pk": self.sale.pk})

    def test_descending_bulk_vs_multi_product_order_never_deadlocks(self):
        rounds = 25
        failures: list[str] = []
        for rnd in range(rounds):
            Product.objects.filter(pk__in=[self.product.pk, self.b.pk]).update(stock_available=50)
            barrier = threading.Barrier(2)

            def bulk():
                close_old_connections()
                try:
                    barrier.wait()
                    # Ordre d'envoi DECROISSANT : B puis A.
                    res = self.api.post(self.url, _mutations([(self.b, 40), (self.product, 41)]), format="json")
                    if res.status_code != 200:
                        failures.append(f"bulk {res.status_code}")
                except Exception as exc:  # interblocage detecte par PostgreSQL = echec du test
                    failures.append(f"bulk {type(exc).__name__}")
                finally:
                    close_old_connections()

            def order():
                close_old_connections()
                try:
                    barrier.wait()
                    create_order(
                        {
                            "flash_sale_id": self.sale.pk, "customer_name": "C",
                            "customer_phone": f"+2237600{rnd:04d}", "client_request_id": f"dl-{rnd}",
                            "items": [
                                {"product_id": self.product.pk, "quantity": 1},
                                {"product_id": self.b.pk, "quantity": 1},
                            ],
                            "delivery": {"address_text": "Hamdallaye ACI, Bamako", "geo_method": "manual"},
                        }
                    )
                except ValidationError:
                    pass  # stock insuffisant legitime
                except Exception as exc:
                    failures.append(f"order {type(exc).__name__}")
                finally:
                    close_old_connections()

            threads = [threading.Thread(target=bulk), threading.Thread(target=order)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(failures, [])
