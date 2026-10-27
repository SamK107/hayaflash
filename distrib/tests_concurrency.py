"""Concurrence : allocation / reprise et commandes simultanees sur le meme produit.

Comme `orders/tests.py`, ce test exige PostgreSQL (SQLite verrouille toute la base et
`select_for_update` y est sans effet) : il est ignore en SQLite et s'execute avec
`--ds=config.settings.test_pg` (conteneur `hf-pg-test`).
"""

from __future__ import annotations

import threading
from datetime import timedelta
from unittest import skipIf

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.db.models import Sum
from django.test import TransactionTestCase
from django.utils import timezone

from distrib.models import AllocationMovement, ImportedProduct, ResellerInvite
from distrib.services import allocation
from distrib.tests_catalog import make_wholesale
from distrib.tests_models import make_distributor, make_seller
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order
from orders.services.create_order import create_order
from products.models import Product, StockMovement
from products.services.crud import attach_product_to_sale

START_STOCK = 10
ORDERS = 8
ALLOCATIONS = 3  # de 3 unites chacune
TAKE_BACKS = 3  # de 4 unites chacune


@skipIf(connection.vendor == "sqlite", "La concurrence exige PostgreSQL (--ds=config.settings.test_pg)")
class AllocationVsOrdersConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.d = make_distributor()
        self.wp = make_wholesale(self.d, stock_total=100)
        seller = make_seller()
        self.invite = ResellerInvite.objects.create(
            distributor=self.d, display_name="Awa", phone=seller.user.phone,
            status=ResellerInvite.Status.ACCEPTED, seller=seller,
        )
        self.imported = allocation.import_product(
            invite=self.invite, wholesale_product=self.wp, retail_price=4500,
            actor=self.d.user, quantity=START_STOCK,
        )
        now = timezone.now()
        self.sale = FlashSale.objects.create(
            owner=seller, title="Live", start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=1), status=FlashSaleStatus.LIVE,
        )
        attach_product_to_sale(flash_sale=self.sale, product=self.imported.product)

    def _order(self, n: int) -> None:
        create_order(
            {
                "flash_sale_id": self.sale.pk, "customer_name": "Cliente", "customer_phone": f"+2237600{n:04d}",
                "client_request_id": f"conc-{n}",
                "items": [{"product_id": self.imported.product_id, "quantity": 1}],
                "delivery": {"address_text": "Hamdallaye ACI, Bamako", "geo_method": "manual"},
            }
        )

    def test_no_negative_stock_no_oversell_no_lost_update(self):
        jobs = (
            [("order", lambda n=n: self._order(n)) for n in range(ORDERS)]
            + [("alloc", lambda: allocation.allocate(imported=self.imported, quantity=3, actor=self.d.user))] * ALLOCATIONS
            + [("back", lambda: allocation.take_back(imported=self.imported, quantity=4, actor=self.d.user))] * TAKE_BACKS
        )
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
        done = lambda kind: sum(1 for k, ok in results if k == kind and ok)  # noqa: E731
        orders_ok, allocs_ok, backs_ok = done("order"), done("alloc"), done("back")

        product = Product.objects.get(pk=self.imported.product_id)
        imported = ImportedProduct.objects.get(pk=self.imported.pk)

        # Jamais de stock negatif, jamais de survente.
        self.assertGreaterEqual(product.stock_available, 0)
        self.assertEqual(Order.service_objects.count(), orders_ok)
        # Aucune mise a jour perdue : le stock est exactement la somme des operations reussies.
        expected_stock = START_STOCK + 3 * allocs_ok - 4 * backs_ok - orders_ok
        self.assertEqual(product.stock_available, expected_stock)
        self.assertEqual(imported.allocated_qty, START_STOCK + 3 * allocs_ok - 4 * backs_ok)
        # Les journaux racontent la meme histoire que le stock.
        moved = StockMovement.objects.filter(product=product).aggregate(t=Sum("quantity_change"))["t"]
        self.assertEqual(moved, product.stock_available)
        journal = AllocationMovement.objects.filter(imported_product=imported).aggregate(t=Sum("quantity_change"))["t"]
        self.assertEqual(journal, imported.allocated_qty)
        # Le catalogue du grossiste n'est jamais depasse.
        self.assertLessEqual(imported.allocated_qty, self.wp.stock_total)
