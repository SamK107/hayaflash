from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from flash_sales.services.crud import clone_flash_sale
from orders.services.create_order import create_order
from products.models import FlashSaleProduct, Product, StockMovement
from products.services.crud import (
    add_product_image,
    adjust_stock,
    attach_product_to_sale,
    create_product,
    products_for_sale,
)

User = get_user_model()


def _valid_delivery(**overrides):
    base = {"address_text": "Hamdallaye ACI, Bamako", "geo_method": "manual"}
    base.update(overrides)
    return base


class CatalogBaseTestCase(TestCase):
    def setUp(self) -> None:
        self.seller_user = User.objects.create_user(
            phone="+22300000101", password="x", display_name="Seller1"
        )
        self.seller = SellerProfile.objects.create(user=self.seller_user)

        self.other_user = User.objects.create_user(
            phone="+22300000102", password="x", display_name="Seller2"
        )
        self.other_seller = SellerProfile.objects.create(user=self.other_user)

        self.staff_user = User.objects.create_user(
            phone="+22300000103", password="x", display_name="Staff", is_staff=True
        )

        now = timezone.now()
        self.sale = FlashSale.objects.create(
            owner=self.seller,
            title="Vente A",
            start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=1),
            status=FlashSaleStatus.LIVE,
        )
        self.other_sale = FlashSale.objects.create(
            owner=self.seller,
            title="Vente B (precedente)",
            start_time=now - timedelta(days=2),
            end_time=now - timedelta(days=2) + timedelta(hours=1),
            status=FlashSaleStatus.COMPLETED,
        )

        self.api = APIClient()


class ModelTests(CatalogBaseTestCase):
    def test_product_no_longer_has_flash_sale_field(self) -> None:
        self.assertFalse(hasattr(Product, "flash_sale"))

    def test_flash_sale_product_unique_together(self) -> None:
        product = create_product(owner=self.seller, name="Sac", price=Decimal("100"), stock=5)
        FlashSaleProduct.objects.create(flash_sale=self.sale, product=product)
        with self.assertRaises(Exception):
            FlashSaleProduct.objects.create(flash_sale=self.sale, product=product)

    def test_effective_price_falls_back_to_catalog_price(self) -> None:
        product = create_product(owner=self.seller, name="Sac", price=Decimal("1000"), stock=5)
        link = FlashSaleProduct.objects.create(flash_sale=self.sale, product=product)
        self.assertEqual(link.effective_price, Decimal("1000"))

        link.promo_price = Decimal("750")
        link.save()
        self.assertEqual(link.effective_price, Decimal("750"))

    def test_products_for_sale_applies_effective_price_and_order(self) -> None:
        p1 = create_product(owner=self.seller, name="A", price=Decimal("100"), stock=5)
        p2 = create_product(owner=self.seller, name="B", price=Decimal("200"), stock=5)
        FlashSaleProduct.objects.create(
            flash_sale=self.sale, product=p1, promo_price=Decimal("80"), display_order=2
        )
        FlashSaleProduct.objects.create(flash_sale=self.sale, product=p2, display_order=1)

        products = products_for_sale(self.sale, only_active=True)
        self.assertEqual([p.pk for p in products], [p2.pk, p1.pk])
        self.assertEqual(products[1].price, Decimal("80"))  # p1 : promo appliquee
        self.assertEqual(products[0].price, Decimal("200"))  # p2 : pas de promo

    def test_products_for_sale_excludes_inactive_link_when_only_active(self) -> None:
        p1 = create_product(owner=self.seller, name="A", price=Decimal("100"), stock=5)
        FlashSaleProduct.objects.create(flash_sale=self.sale, product=p1, is_active=False)
        self.assertEqual(products_for_sale(self.sale, only_active=True), [])
        self.assertEqual(len(products_for_sale(self.sale, only_active=False)), 1)

    def test_catalog_product_reused_across_two_sales(self) -> None:
        """Le point central du refactor : un meme Product peut etre lie a
        plusieurs FlashSale."""
        product = create_product(owner=self.seller, name="Reutilisable", price=Decimal("500"), stock=5)
        FlashSaleProduct.objects.create(flash_sale=self.sale, product=product)
        FlashSaleProduct.objects.create(flash_sale=self.other_sale, product=product)
        self.assertEqual(product.flash_sale_links.count(), 2)

    def test_adjust_stock_records_correction_movement(self) -> None:
        product = create_product(owner=self.seller, name="Stocky", price=Decimal("100"), stock=10)
        adjust_stock(product=product, new_stock_available=25)
        product.refresh_from_db()
        self.assertEqual(product.stock_available, 25)
        movement = StockMovement.objects.filter(
            product=product, movement_type=StockMovement.MovementType.CORRECTION
        ).latest("created_at")
        self.assertEqual(movement.quantity_change, 15)

    def test_adjust_stock_rejects_negative(self) -> None:
        product = create_product(owner=self.seller, name="Stocky2", price=Decimal("100"), stock=10)
        with self.assertRaises(ValidationError):
            adjust_stock(product=product, new_stock_available=-1)


class CloneFlashSaleTests(CatalogBaseTestCase):
    def test_clone_reuses_catalog_products_instead_of_duplicating(self) -> None:
        product = create_product(owner=self.seller, name="Clonable", price=Decimal("300"), stock=5)
        attach_product_to_sale(flash_sale=self.sale, product=product, promo_price=Decimal("250"))

        clone = clone_flash_sale(sale=self.sale, seller=self.seller)

        self.assertEqual(Product.objects.filter(owner=self.seller).count(), 1)  # pas de doublon
        link = FlashSaleProduct.objects.get(flash_sale=clone, product=product)
        self.assertEqual(link.promo_price, Decimal("250"))


class BulkUpdateAPITests(CatalogBaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.api.force_authenticate(user=self.seller_user)
        self.url = reverse(
            "flashsaleproduct-bulk-update", kwargs={"flash_sale_pk": self.sale.pk}
        )

    def test_creates_new_catalog_product_and_links_it(self) -> None:
        payload = {
            "mutations": [
                {
                    "product_new": {"name": "Nouveau", "price": "1500", "stock": 12},
                    "promo_price": "1200",
                    "display_order": 1,
                }
            ]
        }
        res = self.api.post(self.url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(res.data["created_count"], 1)
        product = Product.objects.get(owner=self.seller, name="Nouveau")
        self.assertEqual(product.stock_available, 12)
        link = FlashSaleProduct.objects.get(flash_sale=self.sale, product=product)
        self.assertEqual(link.promo_price, Decimal("1200"))

    def test_response_includes_results_mapping_mutation_index_to_product_id(self) -> None:
        # Le front s'appuie sur `results` (index -> product_id, dans l'ordre
        # d'envoi des mutations) pour retrouver l'id des produits nouvellement
        # crees et leur attacher une photo restee en attente (upload groupe
        # sans correspondance -> nouvelle ligne, cf. quick_publish.html).
        existing = create_product(owner=self.seller, name="Existant", price=Decimal("100"), stock=5)
        payload = {
            "mutations": [
                {"product_id": existing.pk, "promo_price": "80", "stock": 5},
                {"product_new": {"name": "Tout Nouveau", "price": "500", "stock": 3}},
            ]
        }
        res = self.api.post(self.url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(len(res.data["results"]), 2)
        self.assertEqual(res.data["results"][0], {"index": 0, "product_id": existing.pk})
        new_product = Product.objects.get(owner=self.seller, name="Tout Nouveau")
        self.assertEqual(res.data["results"][1], {"index": 1, "product_id": new_product.pk})

    def test_updates_existing_catalog_product_link(self) -> None:
        product = create_product(owner=self.seller, name="Existant", price=Decimal("100"), stock=5)
        payload = {
            "mutations": [
                {"product_id": product.pk, "promo_price": "80", "stock": 40, "display_order": 3}
            ]
        }
        res = self.api.post(self.url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(res.data["updated_count"], 1)
        link = FlashSaleProduct.objects.get(flash_sale=self.sale, product=product)
        self.assertEqual(link.promo_price, Decimal("80"))
        self.assertEqual(link.display_order, 3)
        product.refresh_from_db()
        self.assertEqual(product.stock_available, 40)

    def test_rejects_other_sellers_product_and_rolls_back_whole_batch(self) -> None:
        mine = create_product(owner=self.seller, name="Mine", price=Decimal("100"), stock=5)
        theirs = create_product(owner=self.other_seller, name="Theirs", price=Decimal("50"), stock=5)

        payload = {
            "mutations": [
                {"product_id": mine.pk, "promo_price": "90"},
                {"product_id": theirs.pk, "promo_price": "40"},
            ]
        }
        res = self.api.post(self.url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        # Rollback complet : meme la ligne valide n'a pas ete appliquee.
        self.assertFalse(FlashSaleProduct.objects.filter(flash_sale=self.sale, product=mine).exists())

    def test_cannot_bulk_update_another_sellers_sale(self) -> None:
        self.api.force_authenticate(user=self.other_user)
        res = self.api.post(self.url, {"mutations": []}, format="json")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_anonymous_is_rejected(self) -> None:
        self.api.force_authenticate(user=None)
        res = self.api.post(self.url, {"mutations": []}, format="json")
        self.assertIn(res.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


class CatalogEndpointTests(CatalogBaseTestCase):
    def test_catalog_lists_vendor_products_and_current_links(self) -> None:
        self.api.force_authenticate(user=self.seller_user)
        product = create_product(owner=self.seller, name="Visible", price=Decimal("100"), stock=5)
        attach_product_to_sale(flash_sale=self.sale, product=product)

        url = reverse("flashsaleproduct-catalog", kwargs={"flash_sale_pk": self.sale.pk})
        res = self.api.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data["catalog"]), 1)
        self.assertEqual(res.data["existing_product_ids"], [product.pk])


class ArchiveAndDeleteProductAPITests(CatalogBaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.api.force_authenticate(user=self.seller_user)
        self.archive_url = reverse(
            "flashsaleproduct-archive-product", kwargs={"flash_sale_pk": self.sale.pk}
        )
        self.delete_url = reverse(
            "flashsaleproduct-delete-product", kwargs={"flash_sale_pk": self.sale.pk}
        )
        self.catalog_url = reverse(
            "flashsaleproduct-catalog", kwargs={"flash_sale_pk": self.sale.pk}
        )

    def test_archiving_hides_product_from_default_catalog(self) -> None:
        product = create_product(owner=self.seller, name="A masquer", price=Decimal("100"), stock=5)
        res = self.api.post(
            self.archive_url, {"product_id": product.pk, "is_active": False}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        product.refresh_from_db()
        self.assertFalse(product.is_active)

        catalog = self.api.get(self.catalog_url).data["catalog"]
        self.assertNotIn(product.pk, [p["id"] for p in catalog])

        catalog_with_archived = self.api.get(self.catalog_url + "?include_archived=1").data["catalog"]
        self.assertIn(product.pk, [p["id"] for p in catalog_with_archived])

    def test_archived_product_stays_visible_if_already_linked_to_this_sale(self) -> None:
        product = create_product(owner=self.seller, name="Deja liee", price=Decimal("100"), stock=5)
        attach_product_to_sale(flash_sale=self.sale, product=product)
        self.api.post(self.archive_url, {"product_id": product.pk, "is_active": False}, format="json")

        catalog = self.api.get(self.catalog_url).data["catalog"]
        self.assertIn(product.pk, [p["id"] for p in catalog])

    def test_reactivating_makes_product_visible_again(self) -> None:
        product = create_product(owner=self.seller, name="Va revenir", price=Decimal("100"), stock=5)
        self.api.post(self.archive_url, {"product_id": product.pk, "is_active": False}, format="json")
        res = self.api.post(
            self.archive_url, {"product_id": product.pk, "is_active": True}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        catalog = self.api.get(self.catalog_url).data["catalog"]
        self.assertIn(product.pk, [p["id"] for p in catalog])

    def test_cannot_archive_another_sellers_product(self) -> None:
        theirs = create_product(owner=self.other_seller, name="PasAMoi", price=Decimal("50"), stock=5)
        res = self.api.post(
            self.archive_url, {"product_id": theirs.pk, "is_active": False}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_deletes_product_with_no_orders(self) -> None:
        product = create_product(owner=self.seller, name="Jamais vendu", price=Decimal("100"), stock=5)
        res = self.api.post(self.delete_url, {"product_id": product.pk}, format="json")
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())

    def test_delete_is_refused_when_product_has_orders(self) -> None:
        product = create_product(owner=self.seller, name="Deja vendu", price=Decimal("100"), stock=5)
        attach_product_to_sale(flash_sale=self.sale, product=product)
        create_order(
            {
                "flash_sale_id": self.sale.pk,
                "customer_name": "Client",
                "customer_phone": "+22300000300",
                "client_request_id": "delete-refused-test-1",
                "items": [{"product_id": product.pk, "quantity": 1}],
                "delivery": _valid_delivery(),
            }
        )
        res = self.api.post(self.delete_url, {"product_id": product.pk}, format="json")
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())

    def test_cannot_delete_another_sellers_product(self) -> None:
        theirs = create_product(owner=self.other_seller, name="PasAMoi", price=Decimal("50"), stock=5)
        res = self.api.post(self.delete_url, {"product_id": theirs.pk}, format="json")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Product.objects.filter(pk=theirs.pk).exists())


class DuplicateFromAPITests(CatalogBaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.api.force_authenticate(user=self.seller_user)
        self.product = create_product(owner=self.seller, name="Dup", price=Decimal("500"), stock=10)
        attach_product_to_sale(
            flash_sale=self.other_sale, product=self.product, promo_price=Decimal("400")
        )
        self.url = reverse(
            "flashsaleproduct-duplicate-from", kwargs={"flash_sale_pk": self.sale.pk}
        )

    def test_duplicates_products_from_previous_sale(self) -> None:
        res = self.api.post(self.url, {"previous_sale_id": self.other_sale.pk}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(res.data["duplicated_count"], 1)
        link = FlashSaleProduct.objects.get(flash_sale=self.sale, product=self.product)
        self.assertEqual(link.promo_price, Decimal("400"))

    def test_duplicate_is_idempotent(self) -> None:
        self.api.post(self.url, {"previous_sale_id": self.other_sale.pk}, format="json")
        res = self.api.post(self.url, {"previous_sale_id": self.other_sale.pk}, format="json")
        self.assertEqual(res.data["duplicated_count"], 0)
        self.assertEqual(
            FlashSaleProduct.objects.filter(flash_sale=self.sale, product=self.product).count(), 1
        )

    def test_cannot_duplicate_from_sale_owned_by_someone_else(self) -> None:
        foreign_sale = FlashSale.objects.create(
            owner=self.other_seller,
            title="Pas a moi",
            start_time=timezone.now(),
            end_time=timezone.now() + timedelta(hours=1),
        )
        res = self.api.post(self.url, {"previous_sale_id": foreign_sale.pk}, format="json")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)


class AdminModeTests(CatalogBaseTestCase):
    def test_staff_with_seller_id_can_read_catalog(self) -> None:
        self.api.force_authenticate(user=self.staff_user)
        product = create_product(owner=self.seller, name="ViaAdmin", price=Decimal("100"), stock=5)
        url = reverse("flashsaleproduct-catalog", kwargs={"flash_sale_pk": self.sale.pk})
        res = self.api.get(url, {"seller_id": self.seller.pk})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["catalog"][0]["id"], product.pk)

    def test_staff_without_seller_id_is_forbidden(self) -> None:
        self.api.force_authenticate(user=self.staff_user)
        url = reverse("flashsaleproduct-catalog", kwargs={"flash_sale_pk": self.sale.pk})
        res = self.api.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_staff_non_seller_is_forbidden(self) -> None:
        buyer = User.objects.create_user(phone="+22300000199", password="x", display_name="Buyer")
        self.api.force_authenticate(user=buyer)
        url = reverse("flashsaleproduct-catalog", kwargs={"flash_sale_pk": self.sale.pk})
        res = self.api.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_quick_publish_view_renders(self) -> None:
        client_django = self.client
        client_django.force_login(self.staff_user)
        url = reverse(
            "products:admin_quick_publish",
            kwargs={"seller_id": self.seller.pk, "flash_sale_pk": self.sale.pk},
        )
        res = client_django.get(url)
        self.assertEqual(res.status_code, 200)

    def test_admin_quick_publish_view_blocked_for_non_staff(self) -> None:
        client_django = self.client
        client_django.force_login(self.seller_user)
        url = reverse(
            "products:admin_quick_publish",
            kwargs={"seller_id": self.seller.pk, "flash_sale_pk": self.sale.pk},
        )
        res = client_django.get(url)
        self.assertNotEqual(res.status_code, 200)


class QuickPublishViewTests(CatalogBaseTestCase):
    def test_owner_can_view_quick_publish_page(self) -> None:
        self.client.force_login(self.seller_user)
        url = reverse("products:quick_publish", kwargs={"flash_sale_pk": self.sale.pk})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

    def test_non_owner_gets_404(self) -> None:
        self.client.force_login(self.other_user)
        url = reverse("products:quick_publish", kwargs={"flash_sale_pk": self.sale.pk})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 404)


class CheckoutUsesEffectivePriceTests(CatalogBaseTestCase):
    """Non-regression : le prix promo defini via Publication rapide doit
    bien etre applique a la commande (pas le prix catalogue brut)."""

    def test_order_snapshot_price_is_promo_price(self) -> None:
        product = create_product(owner=self.seller, name="Promo", price=Decimal("1000"), stock=5)
        attach_product_to_sale(flash_sale=self.sale, product=product, promo_price=Decimal("700"))

        order = create_order(
            {
                "flash_sale_id": self.sale.pk,
                "customer_name": "Client",
                "customer_phone": "+22300000200",
                "client_request_id": "promo-price-test-1",
                "items": [{"product_id": product.pk, "quantity": 1}],
                "delivery": _valid_delivery(),
            }
        )
        item = order.items.first()
        self.assertEqual(item.price_snapshot, Decimal("700"))

    def test_order_rejects_product_not_linked_to_this_sale(self) -> None:
        # Produit du catalogue du vendeur mais PAS rattache a self.sale.
        product = create_product(owner=self.seller, name="NonLie", price=Decimal("100"), stock=5)
        with self.assertRaises(ValidationError):
            create_order(
                {
                    "flash_sale_id": self.sale.pk,
                    "customer_name": "Client",
                    "customer_phone": "+22300000201",
                    "client_request_id": "unlinked-product-test-1",
                    "items": [{"product_id": product.pk, "quantity": 1}],
                    "delivery": _valid_delivery(),
                }
            )


class BulkUploadImagesAPITests(CatalogBaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.api.force_authenticate(user=self.seller_user)
        self.url = reverse(
            "flashsaleproduct-bulk-upload-images", kwargs={"flash_sale_pk": self.sale.pk}
        )

    @staticmethod
    def _tiny_png(name: str) -> SimpleUploadedFile:
        # 1x1 PNG valide (assez pour que Pillow/le hook de resize l'acceptent).
        content = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15"
            "c4890000000a49444154789c6300010000050001a5f645400000000049454e"
            "44ae426082"
        )
        return SimpleUploadedFile(name, content, content_type="image/png")

    def test_auto_assigns_image_by_matching_filename(self) -> None:
        create_product(owner=self.seller, name="sac-rouge", price=Decimal("100"), stock=5)
        res = self.api.post(
            self.url, {"files": [self._tiny_png("sac-rouge.png")]}, format="multipart"
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertEqual(len(res.data["uploads"]), 1)
        self.assertEqual(res.data["errors"], [])

    def test_matches_filename_with_underscores_or_hyphens_instead_of_spaces(self) -> None:
        create_product(owner=self.seller, name="carte noir", price=Decimal("100"), stock=5)
        res = self.api.post(
            self.url, {"files": [self._tiny_png("carte_noir.png")]}, format="multipart"
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertEqual(len(res.data["uploads"]), 1)

        res2 = self.api.post(
            self.url, {"files": [self._tiny_png("Carte-Noir.png")]}, format="multipart"
        )
        self.assertEqual(res2.status_code, status.HTTP_201_CREATED, res2.data)

    def test_unmatched_filename_is_reported_as_error_not_crash(self) -> None:
        res = self.api.post(
            self.url, {"files": [self._tiny_png("inconnu.png")]}, format="multipart"
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(len(res.data["errors"]), 1)
        self.assertEqual(res.data["uploads"], [])

    def test_rejects_more_than_max_files(self) -> None:
        files = [self._tiny_png(f"f{i}.png") for i in range(31)]
        res = self.api.post(self.url, {"files": files}, format="multipart")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_falls_back_to_product_order_when_filename_does_not_match(self) -> None:
        # Photos prises au telephone (IMG_xxxx.jpg) : pas de correspondance
        # par nom possible. Le vendeur les depose dans le meme ordre que ses
        # lignes -> `product_order` sert de filet de secours positionnel.
        p1 = create_product(owner=self.seller, name="Produit A", price=Decimal("100"), stock=5)
        p2 = create_product(owner=self.seller, name="Produit B", price=Decimal("100"), stock=5)
        res = self.api.post(
            self.url,
            {
                "files": [self._tiny_png("IMG_0001.jpg"), self._tiny_png("IMG_0002.jpg")],
                "product_order": json.dumps([p1.pk, p2.pk]),
            },
            format="multipart",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertEqual(len(res.data["uploads"]), 2)
        self.assertEqual(res.data["errors"], [])
        by_product = {u["auto_assigned_product_id"]: u for u in res.data["uploads"]}
        self.assertEqual(by_product[p1.pk]["match_kind"], "position")
        self.assertEqual(by_product[p2.pk]["match_kind"], "position")
        self.assertTrue(p1.media.exists())
        self.assertTrue(p2.media.exists())

    def test_filename_match_takes_priority_over_position(self) -> None:
        ordered = create_product(owner=self.seller, name="Sera Rattache Par Position", price=Decimal("100"), stock=5)
        named = create_product(owner=self.seller, name="sac-rouge", price=Decimal("100"), stock=5)
        res = self.api.post(
            self.url,
            {
                # "sac-rouge.png" matche par nom malgre sa position dans la
                # liste envoyee -- le nom reste prioritaire quand il matche.
                "files": [self._tiny_png("sac-rouge.png")],
                "product_order": json.dumps([ordered.pk, named.pk]),
            },
            format="multipart",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertEqual(res.data["uploads"][0]["auto_assigned_product_id"], named.pk)
        self.assertEqual(res.data["uploads"][0]["match_kind"], "filename")
        self.assertFalse(ordered.media.exists())

    def test_position_fallback_skips_products_that_already_have_a_photo(self) -> None:
        has_photo = create_product(owner=self.seller, name="Deja Une Photo", price=Decimal("100"), stock=5)
        add_product_image(product=has_photo, image_file=self._tiny_png("existante.png"))
        empty = create_product(owner=self.seller, name="Sans Photo", price=Decimal("100"), stock=5)
        res = self.api.post(
            self.url,
            {
                "files": [self._tiny_png("IMG_9999.jpg")],
                "product_order": json.dumps([has_photo.pk, empty.pk]),
            },
            format="multipart",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertEqual(res.data["uploads"][0]["auto_assigned_product_id"], empty.pk)
        self.assertEqual(has_photo.media.count(), 1)  # inchangee, pas remplacee


class AssignImageAPITests(CatalogBaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.api.force_authenticate(user=self.seller_user)
        self.url = reverse(
            "flashsaleproduct-assign-image", kwargs={"flash_sale_pk": self.sale.pk}
        )

    def test_assigns_image_to_specific_product_regardless_of_filename(self) -> None:
        product = create_product(owner=self.seller, name="Peu importe le nom", price=Decimal("100"), stock=5)
        png = BulkUploadImagesAPITests._tiny_png("photo-quelconque.png")
        res = self.api.post(
            self.url, {"file": png, "product_id": product.pk}, format="multipart"
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertTrue(product.media.exists())

    def test_cannot_assign_image_to_another_sellers_product(self) -> None:
        theirs = create_product(owner=self.other_seller, name="PasAMoi", price=Decimal("50"), stock=5)
        png = BulkUploadImagesAPITests._tiny_png("x.png")
        res = self.api.post(
            self.url, {"file": png, "product_id": theirs.pk}, format="multipart"
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_reuploading_replaces_previous_image_instead_of_stacking(self) -> None:
        # Regression : deux photos avec `order=0` (l'API n'en pose jamais
        # d'autre) rendaient le choix de media[0] ambigu -- une ancienne
        # photo pouvait rester affichee/renvoyee a la place de la nouvelle
        # apres un second envoi (ex. rattachement manuel apres un echec de
        # correspondance auto). On attend desormais une seule photo par
        # produit : la plus recente remplace la precedente.
        product = create_product(owner=self.seller, name="Carte Noir", price=Decimal("100"), stock=5)
        first = self.api.post(
            self.url,
            {"file": BulkUploadImagesAPITests._tiny_png("premiere.png"), "product_id": product.pk},
            format="multipart",
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)
        self.assertEqual(product.media.count(), 1)

        second = self.api.post(
            self.url,
            {"file": BulkUploadImagesAPITests._tiny_png("deuxieme.png"), "product_id": product.pk},
            format="multipart",
        )
        self.assertEqual(second.status_code, status.HTTP_201_CREATED, second.data)
        self.assertEqual(product.media.count(), 1)
        self.assertNotEqual(first.data["media_id"], second.data["media_id"])
        self.assertIn("deuxieme", product.media.first().file.name)

    def test_catalog_response_reflects_the_most_recently_assigned_image(self) -> None:
        product = create_product(owner=self.seller, name="Carte Noir", price=Decimal("100"), stock=5)
        self.api.post(
            self.url,
            {"file": BulkUploadImagesAPITests._tiny_png("premiere.png"), "product_id": product.pk},
            format="multipart",
        )
        second = self.api.post(
            self.url,
            {"file": BulkUploadImagesAPITests._tiny_png("deuxieme.png"), "product_id": product.pk},
            format="multipart",
        )

        catalog_url = reverse(
            "flashsaleproduct-catalog", kwargs={"flash_sale_pk": self.sale.pk}
        )
        res = self.api.get(catalog_url)
        entry = next(p for p in res.data["catalog"] if p["id"] == product.pk)
        self.assertEqual(len(entry["media"]), 1)
        self.assertEqual(entry["media"][0]["id"], second.data["media_id"])
