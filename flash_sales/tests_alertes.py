"""F-81 : « M'alerter » — promesse tenue (textes exacts, plus de faux « Notification activée »)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from products.models import FlashSaleProduct, Product

User = get_user_model()


def _static_text(path: str) -> str:
    return (settings.BASE_DIR / "static" / path).read_text(encoding="utf-8")


class AlertFixture(TestCase):
    """Un vendeur, une vente (statut/horaires au choix), un client anonyme."""

    def setUp(self) -> None:
        cache.clear()
        self.user = User.objects.create_user(
            phone="+22370000001", password="x", display_name="Awa"
        )
        self.seller = SellerProfile.objects.create(
            user=self.user, business_name="Awa Boutique"
        )
        self.client = Client()

    def make_sale(self, *, title="Drop", status=FlashSaleStatus.SCHEDULED,
                  start_in_h=2.0, duration_h=1.0, owner=None) -> FlashSale:
        now = timezone.now()
        start = now + timedelta(hours=start_in_h)
        sale = FlashSale.objects.create(
            title=title,
            start_time=start,
            end_time=start + timedelta(hours=duration_h),
            status=status,
            owner=owner or self.seller,
        )
        product = Product.objects.create(
            owner=owner or self.seller, name="Sac", stock_available=5,
            stock_initial=5, price=Decimal("1000"),
        )
        FlashSaleProduct.objects.create(flash_sale=sale, product=product)
        return sale

    def page(self, sale: FlashSale) -> str:
        cache.clear()
        resp = self.client.get(reverse("public_flash_sale", kwargs={"slug": sale.public_slug}))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()


FORBIDDEN = ("vous appellera", "vous contactera", "Notification activ")


def drawers(html: str) -> str:
    """Texte des tiroirs « M'alerter » uniquement (hors confirmation de commande)."""
    out, pos = [], 0
    while True:
        start = html.find('id="interest-drawer-', pos)
        if start == -1:
            return "".join(out)
        end = html.find('id="interest-overlay-', start)
        out.append(html[start:end])
        pos = end


class AlertTextsTests(AlertFixture):
    def test_waiting_page_has_exact_texts(self) -> None:
        html = drawers(self.page(self.make_sale(start_in_h=3)))
        for bad in FORBIDDEN:
            self.assertNotIn(bad, html)
        self.assertIn("Awa Boutique vous préviendra sur WhatsApp dès l'ouverture.", html)

    def test_closed_page_has_exact_texts(self) -> None:
        sale = self.make_sale(status=FlashSaleStatus.CLOSED, start_in_h=-3, duration_h=1)
        html = drawers(self.page(sale))
        for bad in FORBIDDEN:
            self.assertNotIn(bad, html)
        self.assertIn("Awa Boutique vous préviendra sur WhatsApp dès la prochaine vente flash.", html)

    def test_live_page_end_drawer_has_exact_texts(self) -> None:
        sale = self.make_sale(status=FlashSaleStatus.LIVE, start_in_h=-1, duration_h=3)
        html = drawers(self.page(sale))
        self.assertIn("interest-drawer-end", html)
        for bad in FORBIDDEN:
            self.assertNotIn(bad, html)
        self.assertIn("dès la prochaine vente flash.", html)

    def test_no_activee_anywhere_in_templates_or_js(self) -> None:
        base = settings.BASE_DIR
        offenders = []
        for path in list((base / "templates").rglob("*.html")) + list((base / "static" / "js").rglob("*.js")):
            if "activee" in path.read_text(encoding="utf-8").lower():
                offenders.append(str(path.relative_to(base)))
        self.assertEqual(offenders, [])


class WaitingButtonJsTests(AlertFixture):
    def test_js_no_longer_fakes_a_notification(self) -> None:
        js = _static_text("js/hf-public.js")
        self.assertNotIn("requestPermission", js)
        self.assertNotIn("new Notification", js)
        self.assertNotIn("Notification activ", js)

    def test_waiting_button_always_opens_the_phone_drawer(self) -> None:
        js = _static_text("js/hf-public.js")
        start = js.index("function hfWaitingAlert")
        body = js[start:js.index("\n}\n", start)]
        self.assertIn("interest-drawer-w", body)
        self.assertIn("classList.add('open')", body)
        self.assertNotIn("Notification", body)
