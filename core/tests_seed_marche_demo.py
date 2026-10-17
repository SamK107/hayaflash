"""Commande de dev seed_marche_demo : garde-fous, contenu, --reset / --clear."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import tempfile
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Sum
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import SellerProfile
from analytics.services.market import compute_market_snapshot
from core.management.commands.seed_marche_demo import (
    ALLOW_ENV_VAR,
    DEMO_CLIENT_PREFIX,
    DEMO_PHONE_PREFIX,
    load_catalogue,
)
from flash_sales.market_stats import compute_market_stats
from flash_sales.models import FlashSale, FlashSaleStatus
from flash_sales.services.ordering import live_now_q, recently_ended_q, upcoming_q
from orders.models import Order, OrderItem, OrderStatus
from products.models import Product, ProductMedia

User = get_user_model()
# 14 h 30 a Bamako (UTC+0) : la journee compte assez d'heures pour la sparkline.
NOW = datetime(2026, 10, 14, 14, 30, tzinfo=ZoneInfo("Africa/Bamako"))
STAGING_ENV = {ALLOW_ENV_VAR: "1"}


def seed(*args) -> None:
    with mock.patch("django.utils.timezone.now", return_value=NOW):
        call_command("seed_marche_demo", *args, verbosity=0)


class SeedGuardTests(TestCase):
    def setUp(self) -> None:
        cache.clear()

    def _assert_refused(self) -> None:
        with self.assertRaises(CommandError):
            call_command("seed_marche_demo", verbosity=0)
        self.assertFalse(User.objects.filter(phone__startswith=DEMO_PHONE_PREFIX).exists())

    @override_settings(DEBUG=False, ALLOWED_HOSTS=["staging.hayaflash.com"])
    def test_refuses_without_debug_nor_variable(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop(ALLOW_ENV_VAR, None)
            self._assert_refused()

    @override_settings(DEBUG=False, ALLOWED_HOSTS=["staging.hayaflash.com"])
    def test_refuses_with_variable_not_equal_to_one(self) -> None:
        with mock.patch.dict("os.environ", {ALLOW_ENV_VAR: "true"}):
            self._assert_refused()

    def test_refuses_with_variable_if_production_host_present(self) -> None:
        for hosts in (["hayaflash.com"], ["staging.x.com", "www.hayaflash.com"], [".hayaflash.com"], ["*"]):
            with (
                self.subTest(hosts=hosts),
                override_settings(DEBUG=False, ALLOWED_HOSTS=hosts),
                mock.patch.dict("os.environ", STAGING_ENV),
            ):
                self._assert_refused()

    @override_settings(DEBUG=False, ALLOWED_HOSTS=["staging.hayaflash.com", "127.0.0.1"])
    def test_works_with_variable_on_staging_host(self) -> None:
        with mock.patch.dict("os.environ", STAGING_ENV):
            seed()
            self.assertTrue(User.objects.filter(phone__startswith=DEMO_PHONE_PREFIX).exists())
            seed("--clear")
            self.assertFalse(User.objects.filter(phone__startswith=DEMO_PHONE_PREFIX).exists())

    @override_settings(DEBUG=False, ALLOWED_HOSTS=["hayaflash.com"])
    def test_clear_is_guarded_too(self) -> None:
        with self.assertRaises(CommandError):
            call_command("seed_marche_demo", "--clear", verbosity=0)


@override_settings(DEBUG=True)
class SeedContentTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.addCleanup(lambda: seed("--clear"))  # supprime aussi les avatars ecrits sur disque
        seed()

    def demo_sales(self):
        return FlashSale.objects.filter(owner__user__phone__startswith=DEMO_PHONE_PREFIX)

    def test_shops_are_clearly_demo_with_avatars(self) -> None:
        shops = SellerProfile.objects.filter(user__phone__startswith=DEMO_PHONE_PREFIX)
        self.assertEqual(shops.count(), 8)
        for shop in shops:
            self.assertTrue(shop.business_name.startswith("Démo "), shop.business_name)
            self.assertTrue(shop.avatar)
        self.assertGreaterEqual(len({s.category for s in shops}), 5)

    def test_sales_by_state_and_rules(self) -> None:
        sales = self.demo_sales()
        live = sales.filter(live_now_q(NOW))
        self.assertEqual(live.count(), 4)
        self.assertEqual(sales.filter(upcoming_q(NOW)).count(), 3)
        self.assertEqual(sales.filter(recently_ended_q(NOW)).count(), 3)
        # 4 fins echelonnees : rouge (< 5 min), orange (< 15 min), puis plus tard.
        mins = sorted(round((s.end_time - NOW).total_seconds() / 60) for s in live)
        self.assertEqual(mins, [4, 12, 45, 100])
        for sale in sales:
            self.assertLessEqual(sale.end_time - sale.start_time, timedelta(hours=2), sale.title)
        for sale in live:
            self.assertTrue(3 <= sale.flash_sale_products.count() <= 5)

    def test_live_progress_and_stock_consistency(self) -> None:
        snap = compute_market_snapshot(NOW)
        pcts = [v["percent_sold"] for v in snap["sales"].values()]
        self.assertEqual(len(pcts), 4)
        for pct in pcts:
            self.assertIsNotNone(pct)
            self.assertTrue(20 <= pct <= 85, pct)
        self.assertEqual(len(set(pcts)), 4)  # barres variees
        for product in Product.objects.filter(owner__user__phone__startswith=DEMO_PHONE_PREFIX):
            sold = (
                OrderItem.objects.filter(product=product)
                .exclude(order__status=OrderStatus.CANCELLED)
                .aggregate(q=Sum("quantity"))["q"]
                or 0
            )
            self.assertEqual(product.stock_available, product.stock_initial - sold, product.name)
            self.assertGreaterEqual(product.stock_available, 0)

    def test_orders_cover_statuses_and_stay_demo_scoped(self) -> None:
        orders = Order.service_objects.filter(flash_sale__in=self.demo_sales())
        self.assertGreater(orders.count(), 50)
        statuses = set(orders.values_list("status", flat=True))
        self.assertTrue({"pending", "confirmed", "out_for_delivery", "delivered", "cancelled"} <= statuses, statuses)
        for phone in orders.values_list("customer_phone", flat=True):
            self.assertTrue(phone.startswith(DEMO_CLIENT_PREFIX))
        spread = {o.created_at.replace(minute=0, second=0, microsecond=0) for o in orders}
        self.assertGreaterEqual(len(spread), 5)  # reparties sur ~6 h

    def test_indices_and_sparkline_not_masked(self) -> None:
        stats = compute_market_stats(NOW)
        self.assertIsNotNone(stats["orders_last_hour"])
        self.assertTrue(stats["top_categories"])
        self.assertIsNotNone(stats["deliveries_in_transit"])
        self.assertIsNotNone(stats["sparkline"])
        self.assertEqual(len(stats["sparkline"]["hours"]), NOW.hour + 1)

    def test_market_page_renders_demo(self) -> None:
        with mock.patch("django.utils.timezone.now", return_value=NOW):
            resp = self.client.get(reverse("flash_sale_calendar"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Démo Awa Mode")
        self.assertContains(resp, "Tendances du jour")
        self.assertContains(resp, "Vient de se terminer")

    def test_second_run_without_reset_refused_reset_recreates(self) -> None:
        with self.assertRaises(CommandError):
            seed()
        before = (self.demo_sales().count(), Order.service_objects.count())
        seed("--reset")
        self.assertEqual((self.demo_sales().count(), Order.service_objects.count()), before)
        self.assertEqual(User.objects.filter(phone__startswith=DEMO_PHONE_PREFIX).count(), 8)

    def test_clear_removes_only_demo_data(self) -> None:
        real_user = User.objects.create_user(phone="+22370000999", password="x", display_name="Vraie")
        real = SellerProfile.objects.create(user=real_user, business_name="Vraie Boutique")
        real_sale = FlashSale.objects.create(
            owner=real, title="Vraie vente", status=FlashSaleStatus.LIVE,
            start_time=NOW - timedelta(hours=1), end_time=NOW + timedelta(hours=1),
        )
        real_product = Product.objects.create(owner=real, name="Vrai produit", price=1000, stock_initial=5, stock_available=5)
        real_order = Order.service_objects.create(
            flash_sale=real_sale, customer_name="Vraie cliente", customer_phone="+22370111222",
            status=OrderStatus.PENDING, client_request_id="vraie-commande",
        )
        seed("--clear")
        self.assertFalse(User.objects.filter(phone__startswith=DEMO_PHONE_PREFIX).exists())
        self.assertFalse(FlashSale.objects.exclude(pk=real_sale.pk).exists())
        self.assertFalse(Order.service_objects.exclude(pk=real_order.pk).exists())
        self.assertEqual(Product.objects.count(), 1)
        self.assertTrue(Product.objects.filter(pk=real_product.pk).exists())
        self.assertTrue(SellerProfile.objects.filter(pk=real.pk).exists())
        seed()  # le cleanup final attend une demo a supprimer


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in sorted(root.rglob("*")) if f.is_file()
    }


def make_assets(root: Path) -> None:
    """Faux jeu de photos (WebP generes) + catalogue.csv : le depot n'embarque aucune photo tierce."""
    from PIL import Image

    entries = [
        ("mode", "robe-test-bleue", "Robe test bleue", 18000, "#2563EB"),
        ("mode", "robe-test-rouge", "Robe test rouge", 22000, "#E63946"),
        ("chaussures", "sandale-test", "Sandale test", 8500, "#B45309"),
        ("chaussures", "derby-test", "Derby test", 28000, "#7C3AED"),
        ("alimentation", "plat-test", "Plat test", 2500, "#15803D"),
        ("alimentation", "sardines-test", "Sardines test", 3500, "#0891B2"),
    ]
    lines = ["chemin,categorie,nom,prix"]
    for cat, slug, name, price, color in entries:
        (root / cat).mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (640, 480), color).save(root / cat / (slug + ".webp"), "WEBP", quality=80)
        lines.append(f"{cat}/{slug}.webp,{cat},{name},{price}")
    (root / "catalogue.csv").write_text(chr(10).join(lines) + chr(10), encoding="utf-8")


@override_settings(DEBUG=True)
class SeedPhotosTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.addCleanup(lambda: seed("--clear"))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.assets = Path(tmp.name)
        make_assets(self.assets)
        patcher = mock.patch("core.management.commands.seed_marche_demo.DEMO_ASSETS_DIR", self.assets)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _photo_products(self):
        # Les photos du catalogue sont des .webp ; les images generees par Pillow, des .jpg.
        return ProductMedia.objects.filter(
            product__owner__user__phone__startswith=DEMO_PHONE_PREFIX, file__endswith=".webp"
        )

    def test_repository_ships_no_third_party_photo(self) -> None:
        """Le dossier versionne ne contient aucune photo : seules des images verifiees pourraient y entrer."""
        from PIL import Image

        repo_assets = Path(__file__).resolve().parent / "demo_assets" / "produits"
        for f in repo_assets.rglob("*"):
            if f.is_file() and "_ecartees" not in f.parts:
                self.assertTrue(f.suffix in (".webp", ".csv"), f)
                if f.suffix == ".webp":  # garde-fou si des images libres y sont ajoutees un jour
                    self.assertLess(f.stat().st_size, 300 * 1024, f.name)
                    with Image.open(f) as img:
                        self.assertLessEqual(max(img.size), 1200)
                        self.assertFalse(img.getexif())
        self.assertTrue((Path(__file__).resolve().parent / "demo_assets" / "CREDITS.md").is_file())

    def test_seed_uses_catalogue_photos_spread_across_shops_with_thumbnails(self) -> None:
        seed()
        rows, warnings = load_catalogue(self.assets)
        self.assertEqual(warnings, [])
        photos = self._photo_products()
        self.assertEqual(photos.count(), len(rows))  # chaque photo utilisee une fois
        names = set(
            Product.objects.filter(owner__user__phone__startswith=DEMO_PHONE_PREFIX).values_list("name", flat=True)
        )
        for row in rows:
            self.assertIn(row["name"], names)
        for cat in {r["category"] for r in rows}:  # >= 2 boutiques par categorie photographiee
            self.assertGreaterEqual(
                SellerProfile.objects.filter(user__phone__startswith=DEMO_PHONE_PREFIX, category=cat).count(), 2
            )
        snap = compute_market_snapshot(NOW)
        mains = [sc["main"] for sc in snap["showcase"].values() if sc["main"]]
        self.assertTrue(any(m["image"] for m in mains))  # miniatures 480 px generees
        for media in photos:  # copies dans media/, format d'origine conserve
            self.assertTrue(media.file.name.endswith(".webp"))
            self.assertTrue(media.file.storage.exists(media.file.name))

    def test_seed_without_catalogue_uses_generated_images(self) -> None:
        with tempfile.TemporaryDirectory() as empty, mock.patch(
            "core.management.commands.seed_marche_demo.DEMO_ASSETS_DIR", Path(empty)
        ):
            seed()
        self.assertEqual(self._photo_products().count(), 0)
        total = ProductMedia.objects.filter(product__owner__user__phone__startswith=DEMO_PHONE_PREFIX)
        self.assertGreater(total.count(), 20)
        self.assertTrue(all(m.file.name.endswith(".jpg") for m in total))
        stats = compute_market_stats(NOW)
        self.assertIsNotNone(stats["sparkline"])

    def test_clear_never_touches_demo_assets(self) -> None:
        before = _tree_hashes(self.assets)
        self.assertTrue(before)
        seed()
        seed("--reset")
        seed("--clear")
        self.assertEqual(_tree_hashes(self.assets), before)
        self.assertEqual(ProductMedia.objects.count(), 0)

    def test_invalid_catalogue_rows_are_skipped_with_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mode").mkdir()
            (root / "mode" / "ok.webp").write_bytes(b"x")
            (root.parent / "dehors.webp").write_bytes(b"x")
            (root / "catalogue.csv").write_text(
                "chemin,categorie,nom,prix\n"
                "mode/ok.webp,mode,Bon produit,5000\n"
                "mode/ok.webp,plats,Categorie inconnue,5000\n"
                "mode/ok.webp,mode,Prix decimal,12.5\n"
                "mode/absent.webp,mode,Image absente,5000\n"
                "../dehors.webp,mode,Hors dossier,5000\n"
                "mode/ok.webp,mode,Prix nul,0\n",
                encoding="utf-8",
            )
            rows, warnings = load_catalogue(root)
            (root.parent / "dehors.webp").unlink()
        self.assertEqual([r["name"] for r in rows], ["Bon produit"])
        self.assertEqual(len(warnings), 5)

    def test_missing_catalogue_file_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_catalogue(Path(tmp)), ([], []))

    def test_demo_assets_are_neither_served_nor_collected(self) -> None:
        from django.conf import settings
        from django.contrib.staticfiles import finders

        for directory in settings.STATICFILES_DIRS:
            self.assertNotIn("demo_assets", str(directory))
        self.assertNotIn("demo_assets", str(settings.MEDIA_ROOT))
        self.assertIsNone(finders.find("produits/catalogue.csv"))
        self.assertIsNone(finders.find("demo_assets/produits/catalogue.csv"))
        for finder in finders.get_finders():
            for path, _storage in finder.list([]):
                self.assertNotIn("demo_assets", str(path))
