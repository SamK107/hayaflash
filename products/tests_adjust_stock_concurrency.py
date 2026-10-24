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
import pytest
from django.db import close_old_connections, connection
from django.db.models import Sum
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order
from orders.services.create_order import create_order
from products.models import Product, StockMovement
from products.services.crud import adjust_stock, attach_product_to_sale, create_product

User = get_user_model()

START_STOCK = 20

INCIDENT = xfail_marker = pytest.mark.xfail(
    strict=True,
    reason="docs/INCIDENTS.md « adjust_stock : mise à jour perdue » (delta calcule sans verrou) - retire avec le correctif",
)


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

    @INCIDENT
    def test_stale_product_instance_gives_a_correct_movement(self):
        stale = Product.objects.get(pk=self.product.pk)  # voit 20, comme la vue Publication rapide
        for n in range(3):
            self.order(n)  # base : 17
        adjust_stock(product=stale, new_stock_available=25)
        product = self.assert_stock_matches_movements()
        self.assertEqual(product.stock_available, 25)
        last = StockMovement.objects.filter(product=product, movement_type="correction").get()
        self.assertEqual(last.quantity_change, 8)  # 25 - 17 reellement en base, pas 25 - 20

    @INCIDENT
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

    @INCIDENT
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
