"""Script scripts/inventory_before_first_wholesaler.py : lecture seule, sans section en erreur."""

from __future__ import annotations

import io
import runpy
from contextlib import redirect_stdout
from pathlib import Path

from django.conf import settings
from django.test import override_settings

from core.models import AuditLog
from distrib.tests_allocation import Base
from products.models import Product, StockMovement

SCRIPT = Path(settings.BASE_DIR) / "scripts" / "inventory_before_first_wholesaler.py"


@override_settings(DISTRIB_ENABLED=True)
class InventoryScriptTests(Base):
    def test_runs_without_error_and_writes_nothing(self):
        self.do_import(quantity=5)
        before = (Product.objects.count(), StockMovement.objects.count(), AuditLog.objects.count())
        out = io.StringIO()
        with redirect_stdout(out):
            runpy.run_path(str(SCRIPT))
        text = out.getvalue()
        self.assertNotIn("[!]", text)
        for marker in ("VENDEURS", "DISTRIB", "VENTES ET PRODUITS", "COMMANDES, PAIEMENTS", "FIN"):
            self.assertIn(marker, text)
        self.assertIn("Robe wax", text)
        self.assertEqual(before, (Product.objects.count(), StockMovement.objects.count(), AuditLog.objects.count()))
