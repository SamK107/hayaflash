from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from urllib.parse import unquote
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import SellerProfile
from accounts.services.slugs import generate_unique_seller_public_slug
from analytics.models import ShareEvent, ShareEventType, ShareLinkType
from analytics.services.cache import flash_page_version_key, get_page_version, seller_stats_key
from analytics.services.share_links import (
    build_order_share_urls,
    build_whatsapp_message,
    build_whatsapp_share_url,
    build_whatsapp_urls,
    get_or_create_product_share_link,
    validate_whatsapp_redirect_target,
)
from analytics.services.view_tracking import resolve_share_link_by_token
from core.services.slugs import slugify_text
from flash_sales.models import FlashSale, FlashSaleStatus
from flash_sales.services.slugs import generate_unique_flash_sale_public_slug
from orders.models import Order
from orders.services.create_order import create_order
from products.models import Product

User = get_user_model()


class ViralGrowthFixture(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.seller_user = User.objects.create_user(
            phone="+15550001111",
            password="x",
            display_name="Awa Shop",
        )
        self.seller = SellerProfile.objects.create(
            user=self.seller_user,
            business_name="Awa Boutique",
        )
        now = timezone.now()
        self.sale = FlashSale.objects.create(
            title="Mega Drop Afrique",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            status=FlashSaleStatus.LIVE,
            owner=self.seller,
        )
        self.product = Product.objects.create(
            flash_sale=self.sale,
            name="Sac wax",
            stock_available=5, stock_initial=5,
            price=Decimal("15000.00"),
        )
        self.client = Client()
        self.api = APIClient()

    def _payload(self, **overrides):
        base = {
            "flash_sale_id": self.sale.pk,
            "customer_name": "Client",
            "customer_phone": "+15559991234",
            "client_request_id": str(uuid4()),
            "items": [{"product_id": self.product.pk, "quantity": 1}],
            "delivery": {
                "address_text": "Hamdallaye ACI, Rue 312, Bamako",
                "geo_method": "manual",
            },
        }
        base.update(overrides)
        return base


class SlugGenerationTests(ViralGrowthFixture):
    def test_core_slugify_single_source(self) -> None:
        self.assertEqual(slugify_text("Mega Drop!", fallback="x"), "mega-drop")

    def test_seller_slug_generated_and_unique(self) -> None:
        self.assertTrue(self.seller.public_slug)
        other_user = User.objects.create_user(
            phone="+15550002222",
            password="x",
            display_name="Awa Shop",
        )
        other = SellerProfile.objects.create(user=other_user, business_name="Awa Boutique")
        self.assertNotEqual(self.seller.public_slug, other.public_slug)

    def test_flash_sale_slug_from_title(self) -> None:
        self.assertTrue(self.sale.public_slug.startswith("mega-drop"))

    def test_slugify_helpers_are_deterministic_for_base(self) -> None:
        self.assertEqual(self.seller.public_slug, generate_unique_seller_public_slug(self.seller))
        self.assertEqual(self.sale.public_slug, generate_unique_flash_sale_public_slug(self.sale))


class ShareLinkTests(ViralGrowthFixture):
    def test_product_share_link_stable_token(self) -> None:
        link1 = get_or_create_product_share_link(flash_sale=self.sale, product=self.product)
        link2 = get_or_create_product_share_link(flash_sale=self.sale, product=self.product)
        self.assertEqual(link1.pk, link2.pk)
        self.assertEqual(link1.link_type, ShareLinkType.PRODUCT)

    def test_whatsapp_urls_absolute_and_encoded(self) -> None:
        urls = build_order_share_urls(None, flash_sale=self.sale, product=self.product)
        wa = urls["whatsapp_url"]
        self.assertTrue(wa.startswith("https://wa.me/?text="))
        decoded = unquote(wa.split("text=", 1)[1])
        self.assertIn("HayaFlash", decoded)
        self.assertIn("Sac wax", decoded)
        mobile_desktop = build_whatsapp_urls(message=decoded)
        self.assertTrue(mobile_desktop["desktop"].startswith("https://api.whatsapp.com/send"))

    def test_whatsapp_redirect_validation(self) -> None:
        good = build_whatsapp_share_url(message="Hi")
        self.assertTrue(validate_whatsapp_redirect_target(good))
        self.assertFalse(validate_whatsapp_redirect_target("https://evil.example/phish"))


class PublicPageTests(ViralGrowthFixture):
    def test_seller_public_page_anonymous_200_with_seo(self) -> None:
        url = reverse("public_seller", kwargs={"slug": self.seller.public_slug})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Awa Boutique")
        self.assertContains(resp, "HayaFlash")
        self.assertContains(resp, 'rel="canonical"')
        self.assertContains(resp, "application/ld+json")
        self.assertNotContains(resp, self.seller_user.phone)
        self.assertIn("Cache-Control", resp)
        self.assertIn("ETag", resp)

    def test_flash_sale_public_page_lists_product(self) -> None:
        url = reverse("public_flash_sale", kwargs={"slug": self.sale.public_slug})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Sac wax")
        self.assertContains(resp, "Mega Drop")

    def test_unknown_slug_returns_404(self) -> None:
        resp = self.client.get(reverse("public_seller", kwargs={"slug": "does-not-exist"}))
        self.assertEqual(resp.status_code, 404)

    def test_page_view_increments_click_count(self) -> None:
        link = get_or_create_product_share_link(flash_sale=self.sale, product=self.product)
        self.client.get(
            reverse("client_order"),
            {"flash_sale_id": self.sale.pk, "product_id": self.product.pk, "ref": link.token},
        )
        link.refresh_from_db()
        self.assertGreaterEqual(link.click_count, 1)


class TrackingConversionTests(ViralGrowthFixture):
    def test_order_with_ref_records_conversion(self) -> None:
        link = get_or_create_product_share_link(flash_sale=self.sale, product=self.product)
        rid = str(uuid4())
        resp = self.api.post(
            "/api/v1/orders/",
            {
                "flash_sale_id": self.sale.pk,
                "product_id": self.product.pk,
                "name": "Client",
                "phone": "+15559991234",
                "quantity": 1,
                "client_request_id": rid,
                "share_ref": link.token,
                "src": "whatsapp",
                "delivery": {
                    "address_text": "Hamdallaye ACI, Rue 312, Bamako",
                    "geo_method": "manual",
                },
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertTrue(resp.data.get("referral", {}).get("available"))
        order = Order.service_objects.get(client_request_id=rid)
        self.assertTrue(
            ShareEvent.objects.filter(
                share_link=link,
                event_type=ShareEventType.CONVERSION,
                order=order,
            ).exists()
        )
        link.refresh_from_db()
        self.assertEqual(link.conversion_count, 1)

    def test_idempotent_order_does_not_double_count_conversion(self) -> None:
        link = get_or_create_product_share_link(flash_sale=self.sale, product=self.product)
        body = {
            "flash_sale_id": self.sale.pk,
            "product_id": self.product.pk,
            "name": "Dup",
            "phone": "+15559991235",
            "quantity": 1,
            "client_request_id": str(uuid4()),
            "share_ref": link.token,
            "delivery": {
                "address_text": "Hamdallaye ACI, Rue 312, Bamako",
                "geo_method": "manual",
            },
        }
        self.api.post("/api/v1/orders/", body, format="json")
        self.api.post("/api/v1/orders/", body, format="json")
        link.refresh_from_db()
        self.assertEqual(link.conversion_count, 1)

    def test_invalid_ref_token_ignored(self) -> None:
        self.assertIsNone(resolve_share_link_by_token("not-a-real-token-xx"))


class WhatsAppTrackingRedirectTests(ViralGrowthFixture):
    def test_track_whatsapp_share_redirect_and_event(self) -> None:
        link = get_or_create_product_share_link(flash_sale=self.sale, product=self.product)
        msg = build_whatsapp_message(headline="X", url="https://example.com")
        wa_target = build_whatsapp_share_url(message=msg)
        track_url = reverse("track_whatsapp_share")
        resp = self.client.get(
            track_url,
            {"ref": link.token, "to": wa_target, "src": "whatsapp"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], wa_target)
        link.refresh_from_db()
        self.assertEqual(link.share_count, 1)

    def test_spam_whatsapp_clicks_deduped(self) -> None:
        link = get_or_create_product_share_link(flash_sale=self.sale, product=self.product)
        wa_target = build_whatsapp_share_url(message="x")
        track_url = reverse("track_whatsapp_share")
        for _ in range(5):
            self.client.get(track_url, {"ref": link.token, "to": wa_target})
        link.refresh_from_db()
        self.assertEqual(link.share_count, 1)

    def test_track_rejects_non_whatsapp_target(self) -> None:
        link = get_or_create_product_share_link(flash_sale=self.sale, product=self.product)
        resp = self.client.get(
            reverse("track_whatsapp_share"),
            {"ref": link.token, "to": "https://evil.example/phish"},
        )
        self.assertEqual(resp.status_code, 404)


class CacheInvalidationTests(ViralGrowthFixture):
    def test_order_invalidates_seller_stats_cache(self) -> None:
        cache.set(seller_stats_key(self.seller.pk), {"total_orders": 0, "products_sold": 0}, 300)
        create_order(self._payload())
        self.assertIsNone(cache.get(seller_stats_key(self.seller.pk)))

    def test_order_bumps_flash_page_version(self) -> None:
        key = flash_page_version_key(self.sale.public_slug)
        before = get_page_version(key)
        create_order(self._payload())
        after = get_page_version(key)
        self.assertGreater(after, before)

    def test_etag_returns_304_when_unchanged(self) -> None:
        url = reverse("public_seller", kwargs={"slug": self.seller.public_slug})
        first = self.client.get(url)
        etag = first["ETag"].strip('"')
        second = self.client.get(url, HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(second.status_code, 304)
