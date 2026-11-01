"""Script scripts/purge_test_data.py : simulation sans ecriture, purge ciblee, garde-fous."""

from __future__ import annotations

import io
import json
import os
import runpy
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import override_settings

from accounts.models import SellerProfile, User
from core.models import AuditLog
from distrib.models import Distributor, ImportedProduct, ResellerInvite, WholesaleProduct
from distrib.tests_allocation import Base
from distrib.tests_models import make_seller
from products.models import Product
from products.services.crud import create_product

SCRIPT = Path(settings.BASE_DIR) / "scripts" / "purge_test_data.py"


def run_script(spec, **env):
    out = io.StringIO()
    env = {"PURGE_SPEC": json.dumps(spec), **env}
    with mock.patch.dict(os.environ, env, clear=False), redirect_stdout(out):
        runpy.run_path(str(SCRIPT))
    return out.getvalue()


@override_settings(DISTRIB_ENABLED=True)
class PurgeTestDataScriptTests(Base):
    def setUp(self):
        super().setUp()
        self.imported = self.do_import(quantity=5)
        self.doomed_seller = self.invite.seller
        self.clean = make_seller("+22370000009", "Clean")
        self.keep = make_seller("+22370000008", "Prot")
        create_product(owner=self.clean, name="Vieux produit", price=1000, stock=3)
        self.keep_product = create_product(owner=self.keep, name="Produit reel", price=2000, stock=4)
        self.spec = {
            "distributors": {str(self.d.pk): "Gros Bamako"},
            "delete_sellers": {str(self.doomed_seller.pk): self.doomed_seller.business_name},
            "clean_sellers": {str(self.clean.pk): self.clean.business_name},
            "protected_sellers": {str(self.keep.pk): self.keep.business_name},
            "expected_orders_clean_sellers": {str(self.clean.pk): 0},
        }

    def counts(self):
        return (
            Distributor.objects.count(), WholesaleProduct.objects.count(), ResellerInvite.objects.count(),
            ImportedProduct.objects.count(), Product.objects.count(), SellerProfile.objects.count(), User.objects.count(),
        )

    def test_simulation_writes_nothing(self):
        before = self.counts()
        out = run_script(self.spec)
        self.assertIn("SIMULATION", out)
        self.assertNotIn("ARRET", out)
        self.assertEqual(before, self.counts())
        self.assertFalse(AuditLog.objects.filter(action="platform.test_data_purged").exists())

    def test_apply_purges_targets_and_keeps_the_rest(self):
        out = run_script(self.spec, APPLY="1")
        self.assertIn("APPLIQUE", out)
        self.assertFalse(Distributor.objects.exists())
        self.assertFalse(ImportedProduct.objects.exists())
        self.assertFalse(WholesaleProduct.objects.exists())
        self.assertFalse(SellerProfile.objects.filter(pk=self.doomed_seller.pk).exists())
        self.assertTrue(SellerProfile.objects.filter(pk=self.clean.pk).exists())
        self.assertFalse(Product.objects.filter(owner=self.clean).exists())
        self.assertTrue(Product.objects.filter(pk=self.keep_product.pk).exists())
        self.assertTrue(SellerProfile.objects.filter(pk=self.keep.pk).exists())
        self.assertEqual(AuditLog.objects.filter(action="platform.test_data_purged").count(), 1)

    def test_name_mismatch_stops_everything(self):
        self.spec["delete_sellers"] = {str(self.doomed_seller.pk): "Autre nom"}
        before = self.counts()
        out = run_script(self.spec, APPLY="1")
        self.assertIn("ARRET", out)
        self.assertEqual(before, self.counts())

    def test_wrong_expected_order_count_stops(self):
        self.spec["expected_orders_clean_sellers"] = {str(self.clean.pk): 2}
        before = self.counts()
        out = run_script(self.spec, APPLY="1")
        self.assertIn("ARRET", out)
        self.assertEqual(before, self.counts())

    def test_staff_user_is_never_deleted(self):
        User.objects.filter(pk=self.d.user_id).update(is_staff=True)
        before = self.counts()
        out = run_script(self.spec, APPLY="1")
        self.assertIn("est staff", out)
        self.assertEqual(before, self.counts())

    def test_clean_seller_orders_deliveries_and_sales_are_removed_but_account_stays(self):
        from datetime import timedelta

        from django.utils import timezone

        from delivery.models import Delivery
        from flash_sales.models import FlashSale, FlashSaleStatus
        from orders.models import Order
        from orders.services.create_order import create_order
        from products.services.crud import attach_product_to_sale

        now = timezone.now()
        sale = FlashSale.objects.create(
            owner=self.clean, title="Demo", start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=1), status=FlashSaleStatus.LIVE,
        )
        product = Product.objects.get(owner=self.clean)
        attach_product_to_sale(flash_sale=sale, product=product)
        create_order(
            {
                "flash_sale_id": sale.pk, "customer_name": "C", "customer_phone": "+22376000000",
                "client_request_id": "purge-1", "items": [{"product_id": product.pk, "quantity": 1}],
                "delivery": {"address_text": "Hamdallaye ACI, Bamako", "geo_method": "manual"},
            }
        )
        self.assertEqual((Order.objects.count(), Delivery.objects.count()), (1, 1))
        self.spec["expected_orders_clean_sellers"] = {str(self.clean.pk): 1}
        out = run_script(self.spec, APPLY="1")
        self.assertIn("APPLIQUE", out)
        self.assertEqual((Order.objects.count(), Delivery.objects.count()), (0, 0))
        self.assertFalse(FlashSale.objects.filter(owner=self.clean).exists())
        self.assertTrue(SellerProfile.objects.filter(pk=self.clean.pk).exists())
