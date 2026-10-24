"""P4 : catalogue de gros et images (spec §4, §5.3, §6)."""

from __future__ import annotations

import io
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from distrib.models import ImportedProduct, ResellerInvite, WholesaleProduct, WholesaleProductImage
from distrib.services import catalog
from distrib.tests_models import make_distributor, make_seller
from products.models import Product


def photo(name="p.jpg", color=(200, 30, 30), size=(60, 60)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


def make_wholesale(distributor, **over):
    data = dict(
        distributor=distributor, name="Robe wax", wholesale_price=3000,
        min_retail_price=4500, stock_total=20,
    )
    data.update(over)
    return catalog.create_wholesale_product(**data)


def allocate_raw(wp, distributor, qty, phone="+22370000001"):
    """Pose une allocation directement en base (les services d'allocation sont testes en P5)."""
    seller = make_seller(phone)
    invite = ResellerInvite.objects.create(
        distributor=distributor, display_name="Awa", phone=phone, status="accepted", seller=seller
    )
    product = Product.objects.create(owner=seller, name="x", price=4500)
    return ImportedProduct.objects.create(wholesale_product=wp, invite=invite, product=product, allocated_qty=qty)


class CatalogServiceTests(TestCase):
    def setUp(self):
        self.d = make_distributor()

    def test_create_stores_whole_fcfa(self):
        wp = make_wholesale(self.d, wholesale_price="3000", min_retail_price=4500)
        self.assertEqual(
            (wp.wholesale_price, wp.min_retail_price, wp.stock_total),
            (Decimal("3000"), Decimal("4500"), 20),
        )
        self.assertTrue(wp.is_active)

    def test_rejects_bad_amounts(self):
        for over in (
            {"wholesale_price": 0},
            {"wholesale_price": "3000.50"},
            {"wholesale_price": "abc"},
            {"min_retail_price": 2999},  # sous le prix de gros : aucune marge
            {"stock_total": -1},
            {"name": "  "},
        ):
            with self.assertRaises(ValidationError, msg=str(over)):
                make_wholesale(self.d, **over)
        self.assertEqual(WholesaleProduct.objects.count(), 0)

    def test_available_is_total_minus_allocated(self):
        wp = make_wholesale(self.d)
        self.assertEqual(catalog.available_qty(wp), 20)
        allocate_raw(wp, self.d, 7)
        self.assertEqual(catalog.allocated_total(wp), 7)
        self.assertEqual(catalog.available_qty(wp), 13)

    def test_stock_total_cannot_drop_below_allocated(self):
        wp = make_wholesale(self.d)
        allocate_raw(wp, self.d, 7)
        fields = dict(wholesale_product=wp, name=wp.name, wholesale_price=3000, min_retail_price=4500)
        with self.assertRaisesMessage(ValidationError, "7 unité"):
            catalog.update_wholesale_product(stock_total=6, **fields)
        wp.refresh_from_db()
        self.assertEqual(wp.stock_total, 20)
        catalog.update_wholesale_product(stock_total=7, **fields)
        wp.refresh_from_db()
        self.assertEqual(wp.stock_total, 7)

    def test_images_limit_and_reorder(self):
        wp = make_wholesale(self.d)
        imgs = [
            catalog.add_wholesale_image(wholesale_product=wp, image_file=photo(f"{i}.jpg")) for i in range(5)
        ]
        with self.assertRaisesMessage(ValidationError, "Cinq photos"):
            catalog.add_wholesale_image(wholesale_product=wp, image_file=photo("6.jpg"))
        catalog.delete_wholesale_image(image=imgs[1])
        self.assertEqual(list(wp.images.values_list("order", flat=True)), [0, 1, 2, 3])

    def test_image_content_is_checked(self):
        wp = make_wholesale(self.d)
        fake = SimpleUploadedFile("evil.jpg", b"<?php echo 1;", content_type="image/jpeg")
        with self.assertRaises(ValidationError):
            catalog.add_wholesale_image(wholesale_product=wp, image_file=fake)
        self.assertEqual(WholesaleProductImage.objects.count(), 0)


@override_settings(DISTRIB_ENABLED=True)
class CatalogViewTests(TestCase):
    def setUp(self):
        self.d = make_distributor()
        self.client.force_login(self.d.user)

    def payload(self, **over):
        data = {
            "name": "Robe wax", "description": "Coton", "category": "mode",
            "wholesale_price": "3000", "min_retail_price": "4500", "stock_total": "20",
            "is_active": "on",
        }
        data.update(over)
        return data

    def test_create_with_a_photo(self):
        resp = self.client.post("/distrib/catalogue/nouveau/", {**self.payload(), "image": photo()})
        wp = WholesaleProduct.objects.get()
        self.assertRedirects(resp, f"/distrib/catalogue/{wp.pk}/")
        self.assertEqual((wp.distributor, wp.category, wp.images.count()), (self.d, "mode", 1))

    def test_create_refuses_decimals_and_low_minimum(self):
        for over in ({"wholesale_price": "3000.5"}, {"min_retail_price": "1000"}, {"stock_total": "-3"}):
            resp = self.client.post("/distrib/catalogue/nouveau/", self.payload(**over))
            self.assertEqual(resp.status_code, 200, over)
        self.assertEqual(WholesaleProduct.objects.count(), 0)

    def test_failed_image_rolls_back_the_product(self):
        bad = SimpleUploadedFile("x.jpg", b"not an image", content_type="image/jpeg")
        resp = self.client.post("/distrib/catalogue/nouveau/", {**self.payload(), "image": bad})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(WholesaleProduct.objects.count(), 0)

    def test_edit_and_hide(self):
        wp = make_wholesale(self.d)
        payload = self.payload(name="Robe wax v2", wholesale_price="3200", min_retail_price="5000")
        payload.pop("is_active")  # case decochee = masque
        resp = self.client.post(f"/distrib/catalogue/{wp.pk}/", payload)
        self.assertRedirects(resp, f"/distrib/catalogue/{wp.pk}/")
        wp.refresh_from_db()
        self.assertEqual(
            (wp.name, wp.wholesale_price, wp.min_retail_price, wp.is_active),
            ("Robe wax v2", 3200, 5000, False),
        )

    def test_edit_below_allocated_shows_an_error(self):
        wp = make_wholesale(self.d)
        allocate_raw(wp, self.d, 9)
        resp = self.client.post(f"/distrib/catalogue/{wp.pk}/", self.payload(stock_total="5"))
        self.assertContains(resp, "déjà")
        wp.refresh_from_db()
        self.assertEqual(wp.stock_total, 20)

    def test_add_and_remove_photo(self):
        wp = make_wholesale(self.d)
        self.client.post(f"/distrib/catalogue/{wp.pk}/photos/", {"image": photo()})
        self.assertEqual(wp.images.count(), 1)
        img = wp.images.get()
        self.client.post(f"/distrib/catalogue/{wp.pk}/photos/{img.pk}/retirer/")
        self.assertEqual(wp.images.count(), 0)

    def test_list_shows_stock_figures(self):
        make_wholesale(self.d, name="Sac cuir")
        resp = self.client.get("/distrib/catalogue/")
        self.assertContains(resp, "Sac cuir")
        self.assertContains(resp, "disponible 20")

    def test_cloisonnement(self):
        other = make_distributor("+22371000002", "Autre gros")
        foreign = make_wholesale(other, name="Produit voisin")
        foreign_img = catalog.add_wholesale_image(wholesale_product=foreign, image_file=photo())
        self.assertNotContains(self.client.get("/distrib/catalogue/"), "Produit voisin")
        self.assertEqual(self.client.get(f"/distrib/catalogue/{foreign.pk}/").status_code, 404)
        self.assertEqual(
            self.client.post(f"/distrib/catalogue/{foreign.pk}/", self.payload(name="Pirate")).status_code, 404
        )
        self.assertEqual(
            self.client.post(f"/distrib/catalogue/{foreign.pk}/photos/", {"image": photo()}).status_code, 404
        )
        # Image d'un autre produit via son propre produit : introuvable aussi.
        mine = make_wholesale(self.d)
        self.assertEqual(
            self.client.post(f"/distrib/catalogue/{mine.pk}/photos/{foreign_img.pk}/retirer/").status_code, 404
        )
        foreign.refresh_from_db()
        self.assertEqual(foreign.name, "Produit voisin")
        self.assertEqual(foreign.images.count(), 1)

    def test_access_rules(self):
        self.client.logout()
        self.assertEqual(self.client.get("/distrib/catalogue/").status_code, 302)
        self.client.force_login(make_seller().user)
        self.assertEqual(self.client.get("/distrib/catalogue/").status_code, 403)
        with override_settings(DISTRIB_ENABLED=False):
            self.client.force_login(self.d.user)
            self.assertEqual(self.client.get("/distrib/catalogue/").status_code, 404)
