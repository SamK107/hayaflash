"""Balises Open Graph par defaut (base.html, bloc og_meta) et specifiques (/f/, /s/).

hf_block_text (core/templatetags/hf_seo.py) s'appuie sur une API interne de
Django (BLOCK_CONTEXT_KEY) pour reprendre le bloc title dans og:title : ces
tests comparent og:title au vrai <title> pour qu'une montee de version de
Django qui la casserait fasse echouer la CI, pas la prod.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import urlparse

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from products.models import FlashSaleProduct, Product

User = get_user_model()


class _HeadParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metas: list[dict[str, str]] = []
        self.canonicals: list[str] = []
        self.json_ld = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = {k: v or "" for k, v in attrs}
        if tag == "meta":
            self.metas.append(attrs)
        elif tag == "link" and attrs.get("rel") == "canonical":
            self.canonicals.append(attrs.get("href", ""))
        elif tag == "script" and attrs.get("type") == "application/ld+json":
            self.json_ld += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data

    def values(self, key: str) -> list[str]:
        return [
            m.get("content", "")
            for m in self.metas
            if m.get("property") == key or m.get("name") == key
        ]


def _parse(response) -> _HeadParser:
    parser = _HeadParser()
    parser.feed(response.content.decode("utf-8"))
    return parser


class OgMetaTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        user = User.objects.create_user(
            phone="+15550002222", password="x", display_name="Awa Shop"
        )
        self.seller = SellerProfile.objects.create(
            user=user, business_name="Awa Boutique"
        )
        now = timezone.now()
        self.sale = FlashSale.objects.create(
            title="Mega Drop Afrique",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            status=FlashSaleStatus.LIVE,
            owner=self.seller,
        )
        product = Product.objects.create(
            owner=self.seller,
            name="Sac wax",
            stock_available=5,
            stock_initial=5,
            price=Decimal("15000"),
        )
        FlashSaleProduct.objects.create(flash_sale=self.sale, product=product)
        self.sale_url = reverse("public_flash_sale", kwargs={"slug": self.sale.public_slug})
        self.seller_url = reverse("public_seller", kwargs={"slug": self.seller.public_slug})

    def _get(self, url: str) -> _HeadParser:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return _parse(response)

    def _assert_single_share_tags(self, head: _HeadParser, url: str) -> None:
        self.assertEqual(len(head.values("og:title")), 1, url)
        self.assertEqual(len(head.values("og:image")), 1, url)
        self.assertLessEqual(len(head.canonicals), 1, url)
        self.assertTrue(head.values("og:image")[0].startswith("http"), url)
        self.assertTrue(head.values("og:url")[0].startswith("http"), url)

    def test_default_pages_have_one_set_of_share_tags(self) -> None:
        for url in ("/", "/ventes/", "/cgu/"):
            with self.subTest(url=url):
                head = self._get(url)
                self._assert_single_share_tags(head, url)
                self.assertEqual(len(head.canonicals), 1, url)
                self.assertEqual(head.values("twitter:card"), ["summary_large_image"])
                self.assertEqual(head.values("og:locale"), ["fr_FR"])
                self.assertTrue(
                    head.values("og:image")[0].endswith("/static/img/og-default.png")
                )

    def test_og_title_repeats_real_page_title(self) -> None:
        # Garde-fou de hf_block_text (API interne BLOCK_CONTEXT_KEY).
        for url in ("/", "/ventes/", "/cgu/", self.sale_url):
            with self.subTest(url=url):
                head = self._get(url)
                title = " ".join(head.title.split())
                self.assertNotEqual(title, "HayaFlash")
                self.assertEqual(head.values("og:title"), [title])

    def test_og_description_repeats_meta_description(self) -> None:
        head = self._get("/")
        descriptions = [
            m["content"] for m in head.metas if m.get("name") == "description"
        ]
        self.assertEqual(head.values("og:description"), descriptions)
        self.assertIn("Commandes en temps réel", descriptions[0])

    def test_flash_sale_page_keeps_specific_tags(self) -> None:
        head = self._get(self.sale_url)
        self._assert_single_share_tags(head, self.sale_url)
        self.assertEqual(len(head.canonicals), 1)
        self.assertIn("Mega Drop Afrique", head.values("og:title")[0])
        self.assertTrue(head.values("og:url")[0].endswith(self.sale_url))
        self.assertGreaterEqual(head.json_ld, 1)

    def test_seller_page_keeps_specific_tags(self) -> None:
        head = self._get(self.seller_url)
        self._assert_single_share_tags(head, self.seller_url)
        self.assertEqual(len(head.canonicals), 1)
        self.assertIn("Awa Boutique", head.values("og:title")[0])
        self.assertTrue(head.values("og:url")[0].endswith(self.seller_url))
        self.assertGreaterEqual(head.json_ld, 1)

    def test_share_image_file_really_exists(self) -> None:
        # config/settings/test.py a STATICFILES_DIRS vide : on pointe sur static/.
        from django.conf import settings
        from django.contrib.staticfiles import finders
        from django.test import override_settings

        with override_settings(STATICFILES_DIRS=[settings.BASE_DIR / "static"]):
            for url in ("/", self.sale_url, self.seller_url):
                with self.subTest(url=url):
                    image = self._get(url).values("og:image")[0]
                    path = urlparse(image).path
                    self.assertTrue(path.startswith(settings.STATIC_URL), image)
                    relative = path[len(settings.STATIC_URL):]
                    self.assertIsNotNone(finders.find(relative), image)

    def test_error_page_has_no_share_tags_nor_canonical(self) -> None:
        response = self.client.get("/cette-url-n-existe-pas/")
        self.assertEqual(response.status_code, 404)
        head = _parse(response)
        self.assertEqual(head.values("og:title"), [])
        self.assertEqual(head.canonicals, [])
