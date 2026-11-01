"""Script scripts/fix_stock_initial.py : simulation par defaut, arret s'il y a des commandes."""

from __future__ import annotations

import io
import os
import runpy
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import override_settings

from core.models import AuditLog
from distrib.tests_allocation import Base
from products.models import Product, StockMovement

SCRIPT = Path(settings.BASE_DIR) / "scripts" / "fix_stock_initial.py"


def run_script(**env):
    out = io.StringIO()
    with mock.patch.dict(os.environ, env, clear=False), redirect_stdout(out):
        runpy.run_path(str(SCRIPT))
    return out.getvalue()


@override_settings(DISTRIB_ENABLED=True)
class FixStockInitialScriptTests(Base):
    def setUp(self):
        super().setUp()
        self.imported = self.do_import(quantity=5)
        self.product = self.imported.product
        Product.objects.filter(pk=self.product.pk).update(stock_initial=10)

    def test_simulation_by_default_writes_nothing(self):
        out = run_script(PRODUCT_ID=str(self.product.pk), APPLY="")
        self.assertIn("10 -> 5", out)
        self.assertIn("SIMULATION", out)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_initial, 10)
        self.assertFalse(AuditLog.objects.filter(action="products.stock_initial_regularized").exists())

    def test_apply_fixes_stock_initial_and_leaves_the_rest(self):
        run_script(PRODUCT_ID=str(self.product.pk), APPLY="1")
        self.product.refresh_from_db()
        self.assertEqual((self.product.stock_initial, self.product.stock_available), (5, 5))
        self.assertEqual(self.product.stock_movements.count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="products.stock_initial_regularized").count(), 1)
        # Idempotent.
        self.assertIn("deja correct", run_script(PRODUCT_ID=str(self.product.pk), APPLY="1"))

    def test_stops_when_history_does_not_confirm_target(self):
        StockMovement.objects.create(
            product=self.product, quantity_change=3, movement_type=StockMovement.MovementType.CORRECTION
        )
        out = run_script(PRODUCT_ID=str(self.product.pk), APPLY="1")
        self.assertIn("ARRET", out)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_initial, 10)

    def test_missing_product_id_stops(self):
        self.assertIn("ARRET", run_script(PRODUCT_ID="", APPLY="1"))
