"""Liens casses sur les pages publiques (href / src internes + sitemap).

- /static/... : verifie via staticfiles.finders.find() (pas de collectstatic).
- /media/...  : non servi par Django en DEBUG=False (nginx en prod) ; on
  verifie que le fichier existe dans le stockage par defaut.
- autres URL internes : GET anonyme, statut < 400 (301/302 acceptes).
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, modify_settings, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from products.models import FlashSaleProduct, Product, ProductMedia

User = get_user_model()

TEST_HOSTS = ("testserver", "http://testserver", "https://testserver")
EXCLUDED_PREFIXES = (
    "/seller/",
    "/admin/",
    "/platform-admin/",
    "/billing/",
    "/api/",
    "/logout/",
    "/orders/",
)
EXCLUDED_SCHEMES = ("#", "mailto:", "tel:", "https://wa.me/", "javascript:", "data:")

_MEDIA_ROOT = tempfile.mkdtemp(prefix="hf-links-media-")


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ("href", "src") and value:
                self.links.append(value.strip())


def _internal_path(link: str) -> str | None:
    if link.startswith(EXCLUDED_SCHEMES):
        return None
    parsed = urlparse(link)
    if parsed.scheme or parsed.netloc:
        if parsed.netloc != "testserver":
            return None  # lien externe
    elif not link.startswith("/") or link.startswith("//"):
        return None
    path = parsed.path or "/"
    if path.startswith(EXCLUDED_PREFIXES):
        return None
    return path + (f"?{parsed.query}" if parsed.query else "")


def _tiny_png(name: str) -> SimpleUploadedFile:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), (255, 77, 46)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


# config/settings/test.py n'herite pas de base.py et n'a pas django.contrib.sitemaps
# (templates du sitemap) : ajoute ici, comme en dev/prod.
@modify_settings(INSTALLED_APPS={"append": "django.contrib.sitemaps"})
@override_settings(
    DEBUG=False,
    MEDIA_ROOT=_MEDIA_ROOT,
    STATICFILES_DIRS=[settings.BASE_DIR / "static"],
)
class BrokenLinksTests(TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self) -> None:
        cache.clear()
        user = User.objects.create_user(
            phone="+15550003333", password="x", display_name="Awa Shop"
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
        ProductMedia.objects.create(
            product=product,
            media_type=ProductMedia.MediaType.IMAGE,
            file=_tiny_png("sac.png"),
        )
        FlashSaleProduct.objects.create(flash_sale=self.sale, product=product)

    def _start_pages(self) -> list[str]:
        return [
            "/",
            "/ventes/",
            "/cgu/",
            "/confidentialite/",
            "/mentions-legales/",
            reverse("public_flash_sale", kwargs={"slug": self.sale.public_slug}),
            reverse("public_seller", kwargs={"slug": self.seller.public_slug}),
            "/sitemap.xml",
            "/robots.txt",
        ]

    def _check_path(self, path: str) -> int | str:
        """Statut HTTP, ou "ok"/"absent" pour les fichiers statiques / media."""
        clean = unquote(path.split("?", 1)[0])
        if clean.startswith(settings.STATIC_URL):
            found = finders.find(clean[len(settings.STATIC_URL):])
            return "ok" if found else "absent"
        if clean.startswith(settings.MEDIA_URL):
            name = clean[len(settings.MEDIA_URL):]
            return "ok" if default_storage.exists(name) else "absent"
        return self.client.get(path).status_code

    def test_public_pages_have_no_broken_internal_links(self) -> None:
        broken: list[str] = []
        checked: dict[str, int | str] = {}
        for page in self._start_pages():
            response = self.client.get(page)
            if response.status_code >= 400:
                broken.append(f"{page} → (page de départ) → {response.status_code}")
                continue
            if "html" not in response.get("Content-Type", ""):
                continue
            parser = _LinkParser()
            parser.feed(response.content.decode("utf-8"))
            for link in parser.links:
                path = _internal_path(link)
                if path is None:
                    continue
                if path not in checked:
                    checked[path] = self._check_path(path)
                status = checked[path]
                if status == "absent" or (isinstance(status, int) and status >= 400):
                    broken.append(f"{page} → {link} → {status}")
        self.assertGreater(len(checked), 10, "trop peu de liens trouvés : extraction cassée ?")
        self.assertEqual(broken, [], "\n" + "\n".join(broken))

    def test_all_sitemap_urls_return_200(self) -> None:
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [
            el.text for el in ElementTree.fromstring(response.content).findall("sm:url/sm:loc", ns)
        ]
        self.assertGreaterEqual(len(locs), 7)  # home, /ventes/, 3 légales, vente, boutique
        broken = []
        for loc in locs:
            status = self.client.get(urlparse(loc).path).status_code
            if status != 200:
                broken.append(f"/sitemap.xml → {loc} → {status}")
        self.assertEqual(broken, [], "\n" + "\n".join(broken))
