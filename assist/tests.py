"""Saisie assistee : l'equipe cree une vente flash et ses produits POUR un
vendeur, sans se connecter a son compte (docs/specs/SPEC_00_SAISIE_ASSISTEE.md).
"""

from __future__ import annotations

import io
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import SellerProfile
from core.models import AuditLog
from flash_sales.models import FlashSale, FlashSaleStatus
from products.models import FlashSaleProduct, Product, StockMovement

User = get_user_model()


def _photo(name="p.jpg", color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (60, 60), color).save(buf, "JPEG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


def _local(dt):
    return timezone.localtime(dt).strftime("%Y-%m-%dT%H:%M")


class AssistBase(TestCase):
    def setUp(self):
        self.seller_user = User.objects.create_user(
            phone="+22370000001", password="x", display_name="Awa"
        )
        self.seller = SellerProfile.objects.create(
            user=self.seller_user, business_name="Boutique Awa"
        )
        self.other_user = User.objects.create_user(
            phone="+22370000002", password="x", display_name="Fanta"
        )
        self.other = SellerProfile.objects.create(user=self.other_user)
        self.staff = User.objects.create_user(
            phone="+22370000009", password="x", display_name="Equipe", is_staff=True
        )

    def login_staff(self):
        self.client.force_login(self.staff)

    def sale_payload(self, **over):
        data = {
            "title": "Robes wax",
            "description": "",
            "start_time": _local(timezone.now() + timedelta(hours=3)),
            "duration_preset": "60",
            "custom_duration_minutes": "",
            "delivery_zone": "Bamako",
            "category": "",
            "max_orders": "",
            "whatsapp_ref": "WhatsApp 22/10 18h05",
        }
        data.update(over)
        return data

    def make_sale(self, owner=None, hours=3):
        now = timezone.now()
        return FlashSale.objects.create(
            owner=owner or self.seller,
            title="Vente existante",
            start_time=now + timedelta(hours=hours),
            end_time=now + timedelta(hours=hours + 1),
            status=FlashSaleStatus.SCHEDULED,
        )


class AccessTests(AssistBase):
    def test_anonymous_is_redirected_to_login(self):
        r = self.client.get(reverse("assist:start", args=[self.seller.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(FlashSale.objects.exists())

    def test_seller_without_staff_is_refused(self):
        self.client.force_login(self.seller_user)
        for url in (
            reverse("assist:start", args=[self.seller.pk]),
            reverse("assist:products", args=[self.seller.pk, self.make_sale().pk]),
        ):
            r = self.client.get(url)
            self.assertNotEqual(r.status_code, 200, url)
        r = self.client.post(reverse("assist:start", args=[self.seller.pk]), self.sale_payload())
        self.assertEqual(FlashSale.objects.filter(title="Robes wax").count(), 0)

    def test_staff_sees_banner_with_shop_name(self):
        self.login_staff()
        r = self.client.get(reverse("assist:start", args=[self.seller.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Saisie assistée pour")
        self.assertContains(r, "Boutique Awa")

    def test_sale_of_another_seller_is_404(self):
        self.login_staff()
        foreign = self.make_sale(owner=self.other)
        r = self.client.get(reverse("assist:products", args=[self.seller.pk, foreign.pk]))
        self.assertEqual(r.status_code, 404)

    def test_no_sensitive_fields_on_pages(self):
        self.login_staff()
        sale = self.make_sale()
        for url in (
            reverse("assist:start", args=[self.seller.pk]),
            reverse("assist:products", args=[self.seller.pk, sale.pk]),
            reverse("assist:done", args=[self.seller.pk, sale.pk]),
        ):
            html = self.client.get(url).content.decode()
            for forbidden in ('name="password', 'name="phone"', "orange", "Orange Money"):
                self.assertNotIn(forbidden, html, url)


class SaleStepTests(AssistBase):
    def test_creates_sale_for_seller_with_audit(self):
        self.login_staff()
        r = self.client.post(reverse("assist:start", args=[self.seller.pk]), self.sale_payload())
        sale = FlashSale.objects.get(title="Robes wax")
        self.assertRedirects(r, reverse("assist:products", args=[self.seller.pk, sale.pk]))
        self.assertEqual(sale.owner, self.seller)
        self.assertEqual(sale.status, FlashSaleStatus.SCHEDULED)
        self.assertEqual((sale.end_time - sale.start_time), timedelta(minutes=60))
        log = AuditLog.objects.get(action="assist.flash_sale_created", entity_id=sale.pk)
        self.assertEqual(log.actor, self.staff)
        self.assertTrue(log.metadata["is_admin_action"])
        self.assertEqual(log.metadata["acting_for_seller_id"], self.seller.pk)
        self.assertEqual(log.metadata["whatsapp_ref"], "WhatsApp 22/10 18h05")

    def test_whatsapp_reference_is_required(self):
        self.login_staff()
        self.client.post(
            reverse("assist:start", args=[self.seller.pk]), self.sale_payload(whatsapp_ref="")
        )
        self.assertFalse(FlashSale.objects.exists())

    def test_past_start_refused(self):
        self.login_staff()
        r = self.client.post(
            reverse("assist:start", args=[self.seller.pk]),
            self.sale_payload(start_time=_local(timezone.now() - timedelta(hours=2))),
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "passé")
        self.assertFalse(FlashSale.objects.exists())

    def test_duration_over_two_hours_refused(self):
        self.login_staff()
        self.client.post(
            reverse("assist:start", args=[self.seller.pk]),
            self.sale_payload(duration_preset="custom", custom_duration_minutes="150"),
        )
        self.assertFalse(FlashSale.objects.exists())

    def test_overlap_refused_like_seller_interface(self):
        self.login_staff()
        existing = self.make_sale()
        self.client.post(
            reverse("assist:start", args=[self.seller.pk]),
            self.sale_payload(start_time=_local(existing.start_time + timedelta(minutes=10))),
        )
        self.assertEqual(FlashSale.objects.count(), 1)

    def test_monthly_quota_applies(self):
        """Plan gratuit : 3 ventes par mois -> la 4e est refusee."""
        self.login_staff()
        base = timezone.now() + timedelta(days=1)
        for i in range(3):
            FlashSale.objects.create(
                owner=self.seller, title=f"V{i}",
                start_time=base + timedelta(hours=3 * i),
                end_time=base + timedelta(hours=3 * i + 1),
                status=FlashSaleStatus.SCHEDULED,
            )
        r = self.client.post(
            reverse("assist:start", args=[self.seller.pk]),
            self.sale_payload(start_time=_local(base + timedelta(days=2))),
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(FlashSale.objects.count(), 3)

    def test_start_page_lists_open_sales_of_the_seller_only(self):
        self.login_staff()
        mine = self.make_sale()
        foreign = self.make_sale(owner=self.other, hours=5)
        r = self.client.get(reverse("assist:start", args=[self.seller.pk]))
        self.assertContains(r, reverse("assist:products", args=[self.seller.pk, mine.pk]))
        self.assertNotContains(r, reverse("assist:products", args=[self.seller.pk, foreign.pk]))


class ProductStepTests(AssistBase):
    def setUp(self):
        super().setUp()
        self.sale = self.make_sale()
        self.url = reverse("assist:products", args=[self.seller.pk, self.sale.pk])

    def post_products(self, rows, photos=None, ref="WhatsApp 22/10 18h10"):
        data = {"whatsapp_ref": ref, "count": str(len(rows))}
        for i, row in enumerate(rows):
            for k, v in row.items():
                data[f"{k}_{i}"] = v
        data["photos"] = photos if photos is not None else [_photo(f"p{i}.jpg") for i in range(len(rows))]
        return self.client.post(self.url, data)

    def test_creates_products_with_stock_movement_and_promo(self):
        self.login_staff()
        r = self.post_products([
            {"name": "Robe bleue", "price": "10000", "promo_price": "7500", "stock": "5", "unit": ""},
            {"name": "Sac noir", "price": "15000", "promo_price": "", "stock": "2", "unit": "pièce"},
        ])
        self.assertRedirects(r, reverse("assist:done", args=[self.seller.pk, self.sale.pk]))
        robe = Product.objects.get(name="Robe bleue")
        self.assertEqual(robe.owner, self.seller)
        self.assertEqual(robe.stock_available, 5)
        self.assertEqual(robe.unit, "pièce")
        self.assertEqual(robe.media.count(), 1)
        self.assertTrue(StockMovement.objects.filter(
            product=robe, movement_type=StockMovement.MovementType.INITIAL, quantity_change=5
        ).exists())
        link = FlashSaleProduct.objects.get(flash_sale=self.sale, product=robe)
        self.assertEqual(int(link.promo_price), 7500)
        self.assertIsNone(FlashSaleProduct.objects.get(product__name="Sac noir").promo_price)
        logs = AuditLog.objects.filter(action="assist.product_created")
        self.assertEqual(logs.count(), 2)
        self.assertTrue(all(lg.actor == self.staff and lg.metadata["is_admin_action"] for lg in logs))

    def test_invalid_row_creates_nothing(self):
        self.login_staff()
        r = self.post_products([
            {"name": "Robe bleue", "price": "10000", "promo_price": "", "stock": "5", "unit": ""},
            {"name": "Gratuit", "price": "0", "promo_price": "", "stock": "1", "unit": ""},
        ])
        self.assertContains(r, "Produit 2", status_code=400)
        self.assertFalse(Product.objects.exists())

    def test_negative_stock_refused(self):
        self.login_staff()
        self.post_products([{"name": "X", "price": "1000", "promo_price": "", "stock": "-1", "unit": ""}])
        self.assertFalse(Product.objects.exists())

    def test_promo_must_be_below_price(self):
        self.login_staff()
        r = self.post_products([{"name": "X", "price": "1000", "promo_price": "1000", "stock": "1", "unit": ""}])
        self.assertContains(r, "Produit 1", status_code=400)
        self.assertFalse(Product.objects.exists())

    def test_photo_count_must_match_rows(self):
        self.login_staff()
        self.post_products(
            [{"name": "X", "price": "1000", "promo_price": "", "stock": "1", "unit": ""}],
            photos=[],
        )
        self.assertFalse(Product.objects.exists())

    def test_whatsapp_reference_required(self):
        self.login_staff()
        self.post_products(
            [{"name": "X", "price": "1000", "promo_price": "", "stock": "1", "unit": ""}], ref=""
        )
        self.assertFalse(Product.objects.exists())

    def test_ended_sale_refused(self):
        self.login_staff()
        now = timezone.now()
        ended = FlashSale.objects.create(
            owner=self.seller, title="Finie",
            start_time=now - timedelta(hours=3), end_time=now - timedelta(hours=2),
            status=FlashSaleStatus.CLOSED,
        )
        r = self.client.get(reverse("assist:products", args=[self.seller.pk, ended.pk]))
        self.assertEqual(r.status_code, 404)

    def test_seller_then_sees_products_in_own_sale(self):
        self.login_staff()
        self.post_products([{"name": "Robe bleue", "price": "10000", "promo_price": "7500", "stock": "5", "unit": ""}])
        self.client.force_login(self.seller_user)
        r = self.client.get(reverse("flash_sales:detail", args=[self.sale.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Robe bleue")

    def test_done_page_gives_public_link(self):
        self.login_staff()
        r = self.client.get(reverse("assist:done", args=[self.seller.pk, self.sale.pk]))
        self.assertContains(r, f"/f/{self.sale.public_slug}/")


class EntryLinksTests(AssistBase):
    def test_platform_admin_shops_links_to_assist(self):
        self.login_staff()
        r = self.client.get(reverse("platform_admin_shops"))
        self.assertContains(r, reverse("assist:start", args=[self.seller.pk]))

    def test_django_admin_seller_list_links_to_assist(self):
        self.staff.is_superuser = True
        self.staff.save()
        self.login_staff()
        r = self.client.get(reverse("admin:accounts_sellerprofile_changelist"))
        self.assertContains(r, reverse("assist:start", args=[self.seller.pk]))


class AtomicityTests(AssistBase):
    def test_bad_photo_rolls_back_whole_batch(self):
        self.client.force_login(self.staff)
        sale = self.make_sale()
        bad = SimpleUploadedFile("x.jpg", b"not an image", content_type="image/jpeg")
        data = {"whatsapp_ref": "WA 1", "count": "2", "photos": [_photo(), bad]}
        for i in range(2):
            data.update({f"name_{i}": f"P{i}", f"price_{i}": "1000", f"promo_price_{i}": "",
                         f"stock_{i}": "1", f"unit_{i}": ""})
        r = self.client.post(reverse("assist:products", args=[self.seller.pk, sale.pk]), data)
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Product.objects.exists())
        self.assertFalse(StockMovement.objects.exists())
        self.assertFalse(AuditLog.objects.filter(action="assist.product_created").exists())

    def test_decimal_price_refused(self):
        self.client.force_login(self.staff)
        sale = self.make_sale()
        data = {"whatsapp_ref": "WA 1", "count": "1", "photos": [_photo()],
                "name_0": "P", "price_0": "1000.5", "promo_price_0": "", "stock_0": "1", "unit_0": ""}
        r = self.client.post(reverse("assist:products", args=[self.seller.pk, sale.pk]), data)
        self.assertContains(r, "prix invalide", status_code=400)
        self.assertFalse(Product.objects.exists())

    def test_products_page_loads_static_script(self):
        self.client.force_login(self.staff)
        sale = self.make_sale()
        r = self.client.get(reverse("assist:products", args=[self.seller.pk, sale.pk]))
        self.assertContains(r, "js/hf-assist.js")
