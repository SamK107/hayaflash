"""Le Marche, vitrine : vedette, vignettes, « Produits du moment », miniatures, entree d'accueil."""

from __future__ import annotations

import io
import re
import shutil
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from analytics.services.market import compute_market_snapshot
from core.demo_data import DEMO_PHONE_PREFIX
from core.services.thumbnails import THUMB_MAIN, THUMB_SMALL, delete_thumbnails, get_thumbnail, thumbnail_name
from flash_sales.market_entry import compute_market_entry
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order, OrderItem, OrderStatus
from products.models import FlashSaleProduct, Product, ProductMedia

User = get_user_model()
MEDIA = tempfile.mkdtemp(prefix="hf-test-media-")
TZ = ZoneInfo("Africa/Bamako")


def tearDownModule() -> None:  # noqa: N802
    shutil.rmtree(MEDIA, ignore_errors=True)


def png(width=1200, height=900) -> ContentFile:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), "#336699").save(buf, "PNG")
    return ContentFile(buf.getvalue())


@override_settings(MEDIA_ROOT=MEDIA)
class VitrineBase(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self._n = 0
        self.now = timezone.now()

    def shop(self, name="Boutique", category="mode") -> SellerProfile:
        self._n += 1
        user = User.objects.create_user(phone=f"+2237300000{self._n}", password="x", display_name=name)
        return SellerProfile.objects.create(user=user, business_name=f"{name} {self._n}", category=category)

    def live_sale(self, seller, ends_in=60) -> FlashSale:
        return FlashSale.objects.create(
            owner=seller, title=f"Vente {seller.business_name}", status=FlashSaleStatus.LIVE,
            start_time=self.now - timedelta(minutes=30), end_time=self.now + timedelta(minutes=ends_in),
        )

    def product(self, sale, name, *, price=10000, promo=None, stock=5, order=0, image=False,
                link_active=True, product_active=True) -> Product:
        self._n += 1
        product = Product.objects.create(
            owner=sale.owner, name=name, price=Decimal(price), stock_initial=20,
            stock_available=stock, is_active=product_active,
        )
        FlashSaleProduct.objects.create(
            flash_sale=sale, product=product, display_order=order, is_active=link_active,
            promo_price=Decimal(promo) if promo is not None else None,
        )
        if image:
            media = ProductMedia(product=product, media_type=ProductMedia.MediaType.IMAGE, order=0)
            media.file.save(f"t{self._n}.png", png(), save=False)
            media.save()
        return product

    def order(self, sale, product, *, status=OrderStatus.PENDING) -> None:
        self._n += 1
        o = Order.service_objects.create(
            flash_sale=sale, customer_name="C", customer_phone=f"+22374{self._n:06d}",
            status=status, client_request_id=f"vt-{self._n}",
        )
        OrderItem.objects.create(
            order=o, product=product, product_name_snapshot=product.name,
            price_snapshot=product.price, quantity=1,
        )


class FeaturedAndThumbsTests(VitrineBase):
    def test_order_stock_inactive_and_featured_with_image(self) -> None:
        sale = self.live_sale(self.shop())
        self.product(sale, "Rupture", order=0, stock=0, image=True)
        self.product(sale, "Lien retire", order=1, link_active=False, image=True)
        self.product(sale, "Produit inactif", order=2, product_active=False, image=True)
        self.product(sale, "Sans image", order=3)
        featured = self.product(sale, "Vedette", order=4, image=True)
        names = [self.product(sale, f"Suivant {i}", order=5 + i).name for i in range(4)]
        sc = compute_market_snapshot(self.now)["showcase"][sale.pk]
        self.assertEqual(sc["main"]["id"], featured.pk)  # 1er actif, en stock, avec image
        self.assertTrue(sc["main"]["image"])
        # vignettes = les 3 suivants dans l'ordre d'affichage (le produit « Sans image » vient d'abord)
        self.assertEqual([t["name"] for t in sc["thumbs"]], ["Sans image", names[0], names[1]])
        self.assertEqual(sc["more"], 2)
        self.assertEqual(sc["count"], 6)
        everything = [sc["main"]["name"]] + [t["name"] for t in sc["thumbs"]]
        for hidden in ("Rupture", "Lien retire", "Produit inactif"):
            self.assertNotIn(hidden, everything)

    def test_no_image_falls_back_to_first_product_placeholder(self) -> None:
        sale = self.live_sale(self.shop())
        first = self.product(sale, "Robe verte", order=0)
        sc = compute_market_snapshot(self.now)["showcase"][sale.pk]
        self.assertEqual(sc["main"]["id"], first.pk)
        self.assertIsNone(sc["main"]["image"])
        self.assertEqual(sc["main"]["initials"], "RV")
        resp = self.client.get(reverse("flash_sale_calendar"))
        self.assertContains(resp, "hfc-ph")
        self.assertContains(resp, ">RV<")

    def test_promo_price_and_discount_pill(self) -> None:
        sale = self.live_sale(self.shop())
        self.product(sale, "Vedette", order=0, image=True)
        self.product(sale, "Promo", price=10000, promo=7500, order=1)
        self.product(sale, "Promo egal", price=10000, promo=10000, order=2)
        self.product(sale, "Sans promo", price=4000, order=3)
        thumbs = {t["name"]: t for t in compute_market_snapshot(self.now)["showcase"][sale.pk]["thumbs"]}
        self.assertEqual((thumbs["Promo"]["price"], thumbs["Promo"]["old_price"], thumbs["Promo"]["discount"]), (7500, 10000, 25))
        self.assertIsNone(thumbs["Promo egal"]["discount"])
        self.assertIsNone(thumbs["Sans promo"]["discount"])
        self.assertEqual(thumbs["Sans promo"]["price"], 4000)
        html = self.client.get(reverse("flash_sale_calendar")).content.decode()
        self.assertEqual(html.count("&minus;25 %"), 1)  # vignette (la vedette n'a pas de promo)
        self.assertIn("7 500", html)

    def test_thumbs_link_to_product_anchor(self) -> None:
        sale = self.live_sale(self.shop())
        self.product(sale, "Vedette", order=0, image=True)
        other = self.product(sale, "Autre", order=1)
        html = self.client.get(reverse("flash_sale_calendar")).content.decode()
        self.assertIn(f"/f/{sale.public_slug}/#p-{other.pk}", html)

    def test_public_sale_page_has_product_anchor(self) -> None:
        sale = self.live_sale(self.shop())
        p = self.product(sale, "Ancre", order=0)
        resp = self.client.get(reverse("public_flash_sale", kwargs={"slug": sale.public_slug}))
        self.assertContains(resp, f'id="p-{p.pk}"')
        self.assertContains(resp, ":target")


class MomentTests(VitrineBase):
    def _fill(self, shops=3, per_shop=4):
        sales = []
        for i in range(shops):
            sale = self.live_sale(self.shop(category=("mode", "beaute", "maison")[i % 3]))
            for i in range(per_shop):
                self.product(sale, f"P{sale.pk}-{i}", order=i, image=(i == 0))
            sales.append(sale)
        return sales

    def test_at_most_two_per_shop_and_ranking(self) -> None:
        a, b, c = self._fill()
        ranked = {p.name: p for p in Product.objects.all()}
        top = ranked[f"P{c.pk}-3"]
        for _ in range(3):
            self.order(c, top)
        self.order(b, ranked[f"P{b.pk}-2"])
        # promo : b-1 (50 %) devant a-1 (10 %) a commandes egales (0)
        FlashSaleProduct.objects.filter(product=ranked[f"P{b.pk}-1"]).update(promo_price=Decimal("5000"))
        FlashSaleProduct.objects.filter(product=ranked[f"P{a.pk}-1"]).update(promo_price=Decimal("9000"))
        # une commande annulee ne compte pas
        for _ in range(5):
            self.order(a, ranked[f"P{a.pk}-3"], status=OrderStatus.CANCELLED)
        moment = compute_market_snapshot(self.now)["moment"]
        per_shop = {}
        for m in moment:
            per_shop[m["sale_id"]] = per_shop.get(m["sale_id"], 0) + 1
        self.assertTrue(all(n <= 2 for n in per_shop.values()), per_shop)
        self.assertEqual(len(moment), 6)
        self.assertEqual(moment[0]["id"], top.pk)                      # 3 commandes
        self.assertEqual(moment[1]["id"], ranked[f"P{b.pk}-2"].pk)     # 1 commande
        names = [m["name"] for m in moment]
        self.assertLess(names.index(f"P{b.pk}-1"), names.index(f"P{a.pk}-1"))  # promo 50 % avant 10 %
        self.assertNotIn(f"P{a.pk}-3", names[:2])  # annulees ignorees

    def test_hidden_under_four_products_and_shown_above(self) -> None:
        self._fill(shops=1, per_shop=6)  # 1 boutique -> 2 produits eligibles seulement
        resp = self.client.get(reverse("flash_sale_calendar"))
        self.assertEqual(resp.context["moment"], [])
        self.assertNotContains(resp, 'class="hfc-moment"')
        cache.clear()
        self._fill(shops=2, per_shop=3)  # 3 boutiques -> 6 produits
        resp = self.client.get(reverse("flash_sale_calendar"))
        self.assertEqual(len(resp.context["moment"]), 6)
        self.assertContains(resp, 'class="hfc-moment"')
        html = resp.content.decode()
        self.assertLess(html.index('class="hfc-moment"'), html.index('class="hfc-chips"'))

    def test_moment_items_link_to_product_and_drop_ended_sales(self) -> None:
        sales = self._fill(shops=3, per_shop=3)
        html = self.client.get(reverse("flash_sale_calendar")).content.decode()
        p = FlashSaleProduct.objects.filter(flash_sale=sales[0]).first().product
        self.assertIn(f"/f/{sales[0].public_slug}/#p-{p.pk}", html)
        # La vente se termine alors que le snapshot est en cache : le bandeau l'ignore.
        FlashSale.objects.filter(pk=sales[0].pk).update(end_time=self.now - timedelta(minutes=1))
        resp = self.client.get(reverse("flash_sale_calendar"))
        self.assertTrue(all(m["sale_id"] != sales[0].pk for m in resp.context["moment"]))


class QueryAndImageTests(VitrineBase):
    def _count(self) -> int:
        cache.clear()
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(reverse("flash_sale_calendar")).status_code, 200)
        return len(ctx)

    def _grow(self, sales: int, products: int) -> None:
        for _ in range(sales):
            sale = self.live_sale(self.shop())
            for i in range(products):
                self.product(sale, f"Produit {i}", order=i, image=(i < 2))

    def test_query_count_independent_of_sales_and_products(self) -> None:
        self._grow(3, 3)
        small = self._count()
        self._grow(7, 30)
        large = self._count()
        self.assertEqual(small, large)

    def test_html_uses_only_thumbnails_with_lazy_width_height(self) -> None:
        self._grow(3, 5)
        originals = [m.file.url for m in ProductMedia.objects.all()]
        self.assertTrue(originals)
        for kwargs in ({}, {"HTTP_HX_REQUEST": "true"}):
            html = self.client.get(reverse("flash_sale_calendar"), **kwargs).content.decode()
            for url in originals:
                self.assertNotIn(url, html)
            imgs = re.findall(r"<img\b[^>]*>", html)
            self.assertTrue(any("/thumbs/" in i for i in imgs))
            for tag in imgs:
                if "base.html" in tag:
                    continue
                if 'src="/static/' in tag:
                    continue  # pictos du gabarit de base, hors Marche
                self.assertIn('loading="lazy"', tag, tag)
                self.assertIn('decoding="async"', tag, tag)
                self.assertRegex(tag, r'width="\d+"')
                self.assertRegex(tag, r'height="\d+"')
                if "/thumbs/" in tag:
                    self.assertIn(".webp", tag)


class ThumbnailTests(VitrineBase):
    def test_creates_small_webp_once_and_never_upscales(self) -> None:
        sale = self.live_sale(self.shop())
        p = self.product(sale, "Photo", image=True)
        f = p.media.first().file
        small = get_thumbnail(f, THUMB_SMALL)
        self.assertEqual(max(small["width"], small["height"]), THUMB_SMALL)
        self.assertTrue(small["url"].endswith(".webp"))
        self.assertIn("/thumbs/200/", small["url"])
        main = get_thumbnail(f, THUMB_MAIN)
        self.assertEqual(max(main["width"], main["height"]), THUMB_MAIN)
        self.assertTrue(f.storage.exists(thumbnail_name(f.name, THUMB_SMALL)))
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(get_thumbnail(f, THUMB_SMALL), small)  # cache : pas de recalcul
        self.assertEqual(len(ctx), 0)
        delete_thumbnails(f)
        self.assertFalse(f.storage.exists(thumbnail_name(f.name, THUMB_SMALL)))
        self.assertTrue(f.storage.exists(f.name))  # l'original est intact

    def test_failure_returns_none_not_original(self) -> None:
        sale = self.live_sale(self.shop())
        p = self.product(sale, "Cassee", image=True)
        f = p.media.first().file
        f.storage.delete(f.name)
        self.assertIsNone(get_thumbnail(f, THUMB_SMALL))
        sc = compute_market_snapshot(self.now)["showcase"][sale.pk]
        self.assertIsNone(sc["main"]["image"])  # bloc de couleur, jamais l'original


class MarketEntryTests(VitrineBase):
    def at(self, y, mo, d, h, mi=0):
        return datetime(y, mo, d, h, mi, tzinfo=TZ)

    def sale(self, start, end, *, status=FlashSaleStatus.SCHEDULED, seller=None) -> FlashSale:
        return FlashSale.objects.create(
            owner=seller or self.shop(), title="Vente", status=status, start_time=start, end_time=end,
        )

    def test_live_state_counts_real_sales(self) -> None:
        now = self.at(2026, 10, 14, 14, 30)
        self.sale(now - timedelta(minutes=10), now + timedelta(hours=1), status=FlashSaleStatus.LIVE)
        self.sale(now - timedelta(minutes=5), now + timedelta(hours=1), status=FlashSaleStatus.LIVE)
        entry = compute_market_entry(now)
        self.assertEqual((entry["state"], entry["live"]), ("live", 2))
        self.assertEqual(entry["label"], "Le Marché · 2 en direct")

    def test_soon_state_today_and_tomorrow(self) -> None:
        now = self.at(2026, 10, 14, 14, 30)
        self.sale(self.at(2026, 10, 14, 20), self.at(2026, 10, 14, 21))
        self.assertEqual(compute_market_entry(now)["label"], "Prochaine vente : aujourd'hui 20 h")
        FlashSale.objects.all().delete()
        later = self.at(2026, 10, 14, 21)
        self.sale(self.at(2026, 10, 15, 18, 30), self.at(2026, 10, 15, 19, 30))
        entry = compute_market_entry(later)
        self.assertEqual((entry["state"], entry["label"]), ("soon", "Prochaine vente : demain 18 h 30"))

    def test_idle_when_nothing_in_next_24h(self) -> None:
        now = self.at(2026, 10, 14, 14, 30)
        self.assertEqual(compute_market_entry(now), {"state": "idle", "live": 0, "label": "Le Marché"})
        self.sale(self.at(2026, 10, 16, 10), self.at(2026, 10, 16, 11))  # dans plus de 24 h
        self.sale(now - timedelta(hours=3), now - timedelta(hours=1), status=FlashSaleStatus.COMPLETED)
        self.assertEqual(compute_market_entry(now)["state"], "idle")

    def test_single_aggregated_query(self) -> None:
        now = self.at(2026, 10, 14, 14, 30)
        for i in range(5):
            self.sale(now - timedelta(minutes=5), now + timedelta(hours=1), status=FlashSaleStatus.LIVE)
        with CaptureQueriesContext(connection) as ctx:
            compute_market_entry(now)
        self.assertEqual(len(ctx), 1)

    def test_demo_shops_never_counted_in_production(self) -> None:
        now = self.at(2026, 10, 14, 14, 30)
        user = User.objects.create_user(phone=f"{DEMO_PHONE_PREFIX}901", password=None, display_name="Démo")
        demo = SellerProfile.objects.create(user=user, business_name="Démo Test")
        self.sale(now - timedelta(minutes=5), now + timedelta(hours=1), status=FlashSaleStatus.LIVE, seller=demo)
        with override_settings(DEBUG=False), self.settings():
            with self.subTest("production"):
                import os
                from unittest import mock

                with mock.patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("HAYAFLASH_ALLOW_DEMO_SEED", None)
                    self.assertEqual(compute_market_entry(now)["state"], "idle")
                with mock.patch.dict(os.environ, {"HAYAFLASH_ALLOW_DEMO_SEED": "1"}):
                    self.assertEqual(compute_market_entry(now)["state"], "live")  # staging
        with override_settings(DEBUG=True):
            self.assertEqual(compute_market_entry(now)["state"], "live")  # dev

    def test_home_shows_entry_with_live_dot_and_cached(self) -> None:
        now = timezone.now()
        self.sale(now - timedelta(minutes=5), now + timedelta(hours=1), status=FlashSaleStatus.LIVE)
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, "Le Marché · 1 en direct")
        self.assertContains(resp, "hf-livedot")
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse("home"))
        self.assertFalse([q for q in ctx.captured_queries if "flash_sales_flashsale" in q["sql"]])

    def test_home_idle_is_plain_link(self) -> None:
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, 'class="nav-market nav-market--idle"')
        self.assertNotContains(resp, 'class="hf-livedot"')
