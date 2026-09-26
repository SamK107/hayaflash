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
from analytics.services.cache import (
    flash_page_version_key,
    get_page_version,
    seller_stats_key,
)
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
from products.models import FlashSaleProduct, Product

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
            owner=self.seller,
            name="Sac wax",
            stock_available=5,
            stock_initial=5,
            price=Decimal("15000.00"),
        )
        FlashSaleProduct.objects.create(flash_sale=self.sale, product=self.product)
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
        other = SellerProfile.objects.create(
            user=other_user, business_name="Awa Boutique"
        )
        self.assertNotEqual(self.seller.public_slug, other.public_slug)

    def test_flash_sale_slug_from_title(self) -> None:
        self.assertTrue(self.sale.public_slug.startswith("mega-drop"))

    def test_slugify_helpers_are_deterministic_for_base(self) -> None:
        self.assertEqual(
            self.seller.public_slug, generate_unique_seller_public_slug(self.seller)
        )
        self.assertEqual(
            self.sale.public_slug, generate_unique_flash_sale_public_slug(self.sale)
        )


class ShareLinkTests(ViralGrowthFixture):
    def test_product_share_link_stable_token(self) -> None:
        link1 = get_or_create_product_share_link(
            flash_sale=self.sale, product=self.product
        )
        link2 = get_or_create_product_share_link(
            flash_sale=self.sale, product=self.product
        )
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
        self.assertTrue(
            mobile_desktop["desktop"].startswith("https://api.whatsapp.com/send")
        )

    def test_whatsapp_redirect_validation(self) -> None:
        good = build_whatsapp_share_url(message="Hi")
        self.assertTrue(validate_whatsapp_redirect_target(good))
        self.assertFalse(
            validate_whatsapp_redirect_target("https://evil.example/phish")
        )


class PublicPageTests(ViralGrowthFixture):
    def test_flash_sale_page_state_follows_time_window(self) -> None:
        # Vente SCHEDULED dont l'heure est passee (Celery beat arrete) : elle
        # accepte les commandes, la page ne doit pas rester en "attente"
        # (boucle de rechargement toutes les 10 s constatee le 23/09).
        now = timezone.now()
        url = reverse("public_flash_sale", kwargs={"slug": self.sale.public_slug})

        self.sale.status = FlashSaleStatus.SCHEDULED
        self.sale.save()
        cache.clear()
        resp = self.client.get(url)
        self.assertEqual(resp.context["page_state"], "live")
        self.assertNotContains(resp, 'data-page-state="waiting"')

        self.sale.start_time = now + timedelta(hours=1)
        self.sale.end_time = now + timedelta(hours=2)
        self.sale.save()
        cache.clear()
        resp = self.client.get(url)
        self.assertEqual(resp.context["page_state"], "waiting")
        self.assertContains(resp, 'data-page-state="waiting"')

        self.sale.start_time = now - timedelta(hours=2)
        self.sale.end_time = now - timedelta(hours=1)
        self.sale.save()
        cache.clear()
        resp = self.client.get(url)
        self.assertEqual(resp.context["page_state"], "ended")

        self.sale.status = FlashSaleStatus.CANCELLED
        self.sale.start_time = now - timedelta(hours=1)
        self.sale.end_time = now + timedelta(hours=1)
        self.sale.save()
        cache.clear()
        resp = self.client.get(url)
        self.assertEqual(resp.context["page_state"], "ended")

    def test_buyer_pages_use_buyer_pwa_manifest(self) -> None:
        # Phase 10.2 : installer l'app depuis une page acheteur ne doit plus
        # ouvrir l'espace vendeur (manifest vendeur start_url=/seller/).
        for url in (
            reverse("public_flash_sale", kwargs={"slug": self.sale.public_slug}),
            reverse("public_seller", kwargs={"slug": self.seller.public_slug}),
            reverse("flash_sale_calendar"),
        ):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
            self.assertContains(resp, "/static/manifest-buyer.json")
            self.assertNotContains(resp, 'href="/static/manifest.json"')

    def test_brand_icons_wired(self) -> None:
        resp = self.client.get(
            reverse("public_flash_sale", kwargs={"slug": self.sale.public_slug})
        )
        self.assertContains(resp, "img/brand/bolt.svg")
        self.assertContains(resp, "/static/img/apple-touch-icon-buyer.png")
        self.assertContains(resp, "/static/favicon.ico")
        fav = self.client.get("/favicon.ico")
        self.assertEqual(fav.status_code, 301)
        self.assertEqual(fav["Location"], "/static/favicon.ico")

    def test_install_invite_wired(self) -> None:
        # Bandeau d'installation : script charge partout, declenche apres
        # commande/alerte cote acheteur. Cote vendeur, PLUS sur chaque page :
        # uniquement apres creation d'une vente (flag de session, voir
        # SellerInstallInviteTest dans flash_sales/tests.py).
        resp = self.client.get(
            reverse("public_flash_sale", kwargs={"slug": self.sale.public_slug})
        )
        self.assertContains(resp, "js/hf-install.js")
        self.assertContains(resp, "hfInstallInvite('buyer'")
        self.client.force_login(self.seller_user)
        resp = self.client.get(reverse("seller_home"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "hfInstallInvite('seller'")

    def test_buyer_manifest_chosen_by_url_prefix(self) -> None:
        # Toute page sous un prefixe acheteur recoit le manifest acheteur, sans
        # surcharge dans le template (ex. futur espace client sous /ventes/).
        from django.test import RequestFactory

        from core.context_processors import pwa_install

        rf = RequestFactory()
        for path in ("/f/x/", "/s/x/", "/ventes/", "/ventes/nouvelle-page/", "/order/"):
            self.assertEqual(pwa_install(rf.get(path))["pwa_app"], "buyer", path)
        for path in ("/", "/login/", "/seller/", "/orders/dashboard/", "/billing/"):
            self.assertEqual(pwa_install(rf.get(path))["pwa_app"], "seller", path)

    def test_interest_post_works_without_csrf_cookie(self) -> None:
        # Visiteur anonyme sans cookie csrftoken (page publique en cache) :
        # "M'alerter" doit fonctionner (403 CSRF constate le 23/09).
        from flash_sales.models import SaleInterest

        strict = Client(enforce_csrf_checks=True)
        resp = strict.post(
            reverse("flash_sale_interest", kwargs={"slug": self.sale.public_slug}),
            data='{"phone": "+223 70 00 00 01", "name": "Awa"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertTrue(
            SaleInterest.objects.filter(flash_sale=self.sale, name="Awa").exists()
        )

    def test_service_worker_served_at_root(self) -> None:
        resp = self.client.get("/sw.js")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Service-Worker-Allowed"], "/")
        self.assertIn("javascript", resp["Content-Type"])
        page = self.client.get(
            reverse("public_flash_sale", kwargs={"slug": self.sale.public_slug})
        )
        self.assertContains(page, "register('/sw.js'")

    def test_seller_pages_keep_seller_pwa_manifest(self) -> None:
        resp = self.client.get(reverse("login"))
        self.assertContains(resp, 'href="/static/manifest.json"')

    def test_seller_public_page_lists_upcoming_scheduled_sales(self) -> None:
        now = timezone.now()
        upcoming = FlashSale.objects.create(
            title="Vente de samedi",
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=2, hours=1),
            status=FlashSaleStatus.SCHEDULED,
            owner=self.seller,
        )
        cancelled = FlashSale.objects.create(
            title="Vente annulee",
            start_time=now + timedelta(days=3),
            end_time=now + timedelta(days=3, hours=1),
            status=FlashSaleStatus.CANCELLED,
            owner=self.seller,
        )
        url = reverse("public_seller", kwargs={"slug": self.seller.public_slug})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Prochainement")
        self.assertContains(resp, "Vente de samedi")
        self.assertContains(
            resp, reverse("public_flash_sale", kwargs={"slug": upcoming.public_slug})
        )
        self.assertNotContains(resp, cancelled.title)

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
        resp = self.client.get(
            reverse("public_seller", kwargs={"slug": "does-not-exist"})
        )
        self.assertEqual(resp.status_code, 404)

    def test_page_view_increments_click_count(self) -> None:
        link = get_or_create_product_share_link(
            flash_sale=self.sale, product=self.product
        )
        self.client.get(
            reverse("client_order"),
            {
                "flash_sale_id": self.sale.pk,
                "product_id": self.product.pk,
                "ref": link.token,
            },
        )
        link.refresh_from_db()
        self.assertGreaterEqual(link.click_count, 1)


class TrackingConversionTests(ViralGrowthFixture):
    def test_order_with_ref_records_conversion(self) -> None:
        link = get_or_create_product_share_link(
            flash_sale=self.sale, product=self.product
        )
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
        link = get_or_create_product_share_link(
            flash_sale=self.sale, product=self.product
        )
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
        link = get_or_create_product_share_link(
            flash_sale=self.sale, product=self.product
        )
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
        link = get_or_create_product_share_link(
            flash_sale=self.sale, product=self.product
        )
        wa_target = build_whatsapp_share_url(message="x")
        track_url = reverse("track_whatsapp_share")
        for _ in range(5):
            self.client.get(track_url, {"ref": link.token, "to": wa_target})
        link.refresh_from_db()
        self.assertEqual(link.share_count, 1)

    def test_track_rejects_non_whatsapp_target(self) -> None:
        link = get_or_create_product_share_link(
            flash_sale=self.sale, product=self.product
        )
        resp = self.client.get(
            reverse("track_whatsapp_share"),
            {"ref": link.token, "to": "https://evil.example/phish"},
        )
        self.assertEqual(resp.status_code, 404)


class CacheInvalidationTests(ViralGrowthFixture):
    def test_order_invalidates_seller_stats_cache(self) -> None:
        cache.set(
            seller_stats_key(self.seller.pk),
            {"total_orders": 0, "products_sold": 0},
            300,
        )
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


class PublicVisibilityByTimeTests(ViralGrowthFixture):
    """Ventes terminees/fermees invisibles cote acheteur meme si le statut n'a
    pas ete mis a jour (Celery beat arrete ou en retard, dev sans Celery)."""

    def setUp(self) -> None:
        super().setUp()
        now = timezone.now()
        # Terminee depuis des semaines mais restee LIVE (auto_close non passe).
        self.stale = FlashSale.objects.create(
            title="Vieille vente restee LIVE",
            start_time=now - timedelta(days=30, hours=2),
            end_time=now - timedelta(days=30),
            status=FlashSaleStatus.LIVE,
            owner=self.seller,
        )
        # Programmee dont l'heure est passee (auto_open non passe) : en cours.
        self.late_open = FlashSale.objects.create(
            title="Ouverte sans Celery",
            start_time=now - timedelta(minutes=10),
            end_time=now + timedelta(hours=1),
            status=FlashSaleStatus.SCHEDULED,
            owner=self.seller,
        )
        # Fermee par le vendeur avant l'heure de fin.
        self.closed_early = FlashSale.objects.create(
            title="Fermee par le vendeur",
            start_time=now - timedelta(minutes=30),
            end_time=now + timedelta(hours=1),
            status=FlashSaleStatus.CLOSED,
            owner=self.seller,
        )

    def test_calendar_lists_only_orderable_live_and_upcoming(self) -> None:
        resp = self.client.get(reverse("flash_sale_calendar"))
        groups = {g["key"]: g["sales"] for g in resp.context["groups"]}
        live = groups.get("live", [])
        self.assertIn(self.sale, live)
        self.assertIn(self.late_open, live)
        self.assertNotIn(self.stale, live)
        self.assertNotIn(self.closed_early, live)
        self.assertNotContains(resp, "Vieille vente restee LIVE")

    def test_old_detail_url_redirects_to_canonical_page(self) -> None:
        resp = self.client.get(f"/ventes/{self.stale.public_slug}/")
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(
            resp["Location"],
            reverse("public_flash_sale", kwargs={"slug": self.stale.public_slug}),
        )

    def test_public_page_state_follows_order_rule(self) -> None:
        for sale, state in (
            (self.stale, "ended"),
            (self.closed_early, "ended"),
            (self.late_open, "live"),
        ):
            cache.clear()
            resp = self.client.get(
                reverse("public_flash_sale", kwargs={"slug": sale.public_slug})
            )
            self.assertEqual(resp.context["page_state"], state, sale.title)

    def test_seller_public_page_and_api_hide_ended_sales(self) -> None:
        resp = self.client.get(
            reverse("public_seller", kwargs={"slug": self.seller.public_slug})
        )
        self.assertNotContains(resp, "Vieille vente restee LIVE")
        self.assertNotContains(resp, "Fermee par le vendeur")
        titles = {s["title"] for s in self.api.get("/api/v1/flash-sales/").json()}
        self.assertNotIn(self.stale.title, titles)
        self.assertIn(self.late_open.title, titles)


class CalendarListAndEndedPageTests(ViralGrowthFixture):
    def _sale(self, title, start, end, status=FlashSaleStatus.SCHEDULED, **kw):
        return FlashSale.objects.create(
            title=title, start_time=start, end_time=end, status=status,
            owner=self.seller, **kw,
        )

    def test_calendar_groups_order_and_category(self) -> None:
        from core.choices import SaleCategory

        now = timezone.now()
        self.seller.category = SaleCategory.CHAUSSURES
        self.seller.save()
        soon = self._sale("Dans 20 min", now + timedelta(minutes=20), now + timedelta(hours=1))
        later = self._sale(
            "Dans 3 jours", now + timedelta(days=3), now + timedelta(days=3, hours=1),
            category=SaleCategory.BEAUTE,
        )
        resp = self.client.get(reverse("flash_sale_calendar"))
        keys = [g["key"] for g in resp.context["groups"]]
        self.assertEqual(keys[0], "live")
        self.assertEqual(keys[1], "soon")
        self.assertEqual(keys[-1], timezone.localtime(later.start_time).date().isoformat())
        self.assertIn(soon, resp.context["groups"][1]["sales"])
        # Categorie : celle de la vente, sinon celle de la boutique.
        self.assertContains(resp, "<b>Beauté</b>")
        self.assertContains(resp, "<b>Chaussures</b>")
        # Rafraichissement HTMX : seulement la liste.
        part = self.client.get(reverse("flash_sale_calendar"), HTTP_HX_REQUEST="true")
        self.assertNotContains(part, "<html")
        self.assertContains(part, "hfc-row")

    def test_ended_page_social_proof_and_next_sale(self) -> None:
        now = timezone.now()
        order = create_order(self._payload())
        self.sale.start_time = now - timedelta(hours=3)
        self.sale.end_time = now - timedelta(hours=2)
        self.sale.save()
        nxt = self._sale("Vente de demain", now + timedelta(days=1), now + timedelta(days=1, hours=1))
        cache.clear()
        resp = self.client.get(reverse("public_flash_sale", kwargs={"slug": self.sale.public_slug}))
        self.assertEqual(resp.context["page_state"], "ended")
        self.assertEqual(resp.context["ended_stats"]["items_sold"], order.items.first().quantity)
        self.assertEqual(resp.context["next_sale"], nxt)
        self.assertContains(resp, "Vente de demain")
        self.assertContains(resp, "vendu")
        # Plus de prix ni de bouton Commander sur une vente terminee.
        self.assertNotContains(resp, "15 000")


class LivePulseTests(ViralGrowthFixture):
    """GET /f/<slug>/pulse/ : stock reel + preuve sociale (Phase 10.1/10.3)."""

    def _pulse(self, slug=None):
        cache.clear()
        return self.client.get(
            reverse("flash_sale_pulse", kwargs={"slug": slug or self.sale.public_slug})
        )

    def _interest(self, phone, sale=None):
        from flash_sales.models import SaleInterest

        SaleInterest.objects.create(flash_sale=sale or self.sale, phone=phone)

    def test_live_pulse_reports_real_stock_and_orders(self) -> None:
        create_order(self._payload())
        resp = self._pulse()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Cache-Control"], "no-store")
        data = resp.json()
        self.assertEqual(data["state"], "live")
        self.assertEqual(data["stock"], {str(self.product.pk): 4})
        self.assertEqual(data["orders"], 1)
        self.assertEqual(data["items_sold"], 1)
        self.assertEqual(data["recent_orders"], 1)
        self.assertIsNotNone(data["last_order_seconds_ago"])

    def test_pulse_exposes_no_buyer_personal_data(self) -> None:
        create_order(self._payload())
        self._interest("+22370009999")
        body = self._pulse().content.decode()
        for secret in ("+15559991234", "+22370009999", "Client", "Hamdallaye"):
            self.assertNotIn(secret, body)

    def test_interested_counts_distinct_phones(self) -> None:
        for phone in ("+22370000001", "+22370000001", "+22370000002"):
            self._interest(phone)
        self.assertEqual(self._pulse().json()["interested"], 2)

    def test_cancelled_orders_are_not_counted(self) -> None:
        from orders.models import OrderStatus

        order = create_order(self._payload())
        Order.service_objects.filter(pk=order.pk).update(status=OrderStatus.CANCELLED)
        self.assertEqual(self._pulse().json()["orders"], 0)

    def test_ended_sale_has_no_stock(self) -> None:
        now = timezone.now()
        self.sale.start_time = now - timedelta(hours=3)
        self.sale.end_time = now - timedelta(hours=1)
        self.sale.save()
        data = self._pulse().json()
        self.assertEqual(data["state"], "ended")
        self.assertEqual(data["stock"], {})

    def test_unknown_slug_404(self) -> None:
        self.assertEqual(self._pulse("nexiste-pas").status_code, 404)

    def test_pulse_is_cached_per_sale(self) -> None:
        cache.clear()
        url = reverse("flash_sale_pulse", kwargs={"slug": self.sale.public_slug})
        self.assertEqual(self.client.get(url).json()["orders"], 0)
        create_order(self._payload())
        # Meme fenetre de cache (5 s) : pas de recalcul par visiteur.
        self.assertEqual(self.client.get(url).json()["orders"], 0)

    def test_social_proof_thresholds(self) -> None:
        from analytics.services.live_pulse import compute_live_pulse, social_proof_lines

        lines = social_proof_lines(compute_live_pulse(self.sale))
        self.assertEqual(lines, {"live": "", "live_sub": "", "waiting": ""})
        self._interest("+22370000001")
        self._interest("+22370000002")
        # 2 inscrits < seuil de 3 : rien d'affiche ("2 personnes" dessert la vente).
        self.assertEqual(social_proof_lines(compute_live_pulse(self.sale))["live"], "")
        self._interest("+22370000003")
        self.assertIn("3 personnes", social_proof_lines(compute_live_pulse(self.sale))["live"])
        create_order(self._payload())
        lines = social_proof_lines(compute_live_pulse(self.sale))
        self.assertEqual(lines["live"], "1 commande")
        self.assertEqual(lines["live_sub"], "Dernière commande à l'instant")

    def test_public_page_renders_initial_social_proof(self) -> None:
        create_order(self._payload())
        cache.clear()
        resp = self.client.get(reverse("public_flash_sale", kwargs={"slug": self.sale.public_slug}))
        self.assertEqual(resp.context["social_proof"]["live"], "1 commande")
        self.assertContains(resp, 'id="hf-pulse"')
        self.assertContains(resp, "hf-live-pulse.js")
        self.assertContains(resp, 'data-stock="4"')

