"""QR du lien de recommandation /r/<code>/ sur la fiche partenaire (équipe uniquement).

Généré à la volée (aucune image stockée, aucune migration). L'URL encodée ne contient que le code.
Aucun décodeur de QR n'est installé : le contrôle de l'URL encodée compare les modules lus dans
l'image téléchargée à ceux du QR de l'URL attendue (l'encodage est déterministe : mêmes modules =
mêmes données).
"""

from __future__ import annotations

import io
import re
from datetime import timedelta

import qrcode
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from partners.models import Partner
from partners.tests_documents_admin import Base
from partners.tests_models import make_partner

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def expected_matrix(url: str) -> list[list[bool]]:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.get_matrix()


def modules_from_png(content: bytes, side_in_modules: int) -> list[list[bool]]:
    image = Image.open(io.BytesIO(content)).convert("L")
    width, height = image.size
    assert width == height and width % side_in_modules == 0, (width, height, side_in_modules)
    box = width // side_in_modules
    return [
        [image.getpixel((x * box + box // 2, y * box + box // 2)) < 128 for x in range(side_in_modules)]
        for y in range(side_in_modules)
    ]


class QrBase(Base):
    def qr_url(self, partner=None, fmt="png"):
        return reverse("partners_referral_qr", args=[(partner or self.partner).pk, fmt])

    def get(self, partner=None, fmt="png"):
        return self.client.get(self.qr_url(partner, fmt))


class AccessTests(QrBase):
    def test_non_staff_and_anonymous_are_refused(self):
        seller_client = Client()
        seller_client.force_login(
            type(self.staff).objects.create_user(phone="+22379000002", password="x", display_name="V")
        )
        for fmt in ("png", "svg"):
            for client in (Client(), seller_client):
                response = client.get(self.qr_url(fmt=fmt))
                self.assertEqual(response.status_code, 302, fmt)
                self.assertIn("login", response["Location"])
                self.assertNotIn("attachment", response.get("Content-Disposition", ""))

    def test_unknown_partner_is_a_404(self):
        response = self.client.get(reverse("partners_referral_qr", args=[999999, "png"]))
        self.assertEqual(response.status_code, 404)

    def test_unknown_format_is_a_404(self):
        self.assertEqual(self.client.get(self.qr_url(fmt="gif")).status_code, 404)

    def test_only_get_is_accepted(self):
        self.assertEqual(self.client.post(self.qr_url()).status_code, 405)


class UnavailablePartnerTests(QrBase):
    def assertRefused(self, partner, expected_word):
        for fmt in ("png", "svg"):
            response = self.get(partner, fmt)
            self.assertEqual(response.status_code, 403, (partner.status, fmt))
            self.assertNotIn("attachment", response.get("Content-Disposition", ""))
            self.assertNotIn(PNG_SIGNATURE, response.content[:8])
            self.assertNotIn(b"<svg", response.content)
            self.assertIn(expected_word, response.content.decode().lower())
            self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_paused_partner(self):
        self.partner.status = "paused"
        self.partner.save()
        self.assertRefused(self.partner, "pause")

    def test_released_slot(self):
        self.partner.status = "slot_released"
        self.partner.save()
        self.assertRefused(self.partner, "libérée")

    def test_ended_partner(self):
        self.partner.status = "ended"
        self.partner.save()
        self.assertRefused(self.partner, "terminé")

    def test_expired_contract(self):
        self.partner.contract_end = timezone.localdate() - timedelta(days=1)
        self.partner.save()
        self.assertRefused(self.partner, "expiré")

    def test_prospect_has_no_link_yet(self):
        self.assertRefused(self.prospect, "contrat")

    def test_the_sheet_shows_the_message_instead_of_the_buttons(self):
        self.partner.status = "paused"
        self.partner.save()
        html = self.client.get(reverse("partners_detail", args=[self.partner.pk])).content.decode()
        self.assertIn("pause", html.lower())
        self.assertNotIn(self.qr_url(fmt="png"), html)
        self.assertNotIn(self.qr_url(fmt="svg"), html)


class PngDownloadTests(QrBase):
    def test_png_headers_signature_and_size(self):
        response = self.get(fmt="png")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="hayaflash-AWA2026.png"')
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertTrue(response.content.startswith(PNG_SIGNATURE))
        image = Image.open(io.BytesIO(response.content))
        self.assertGreaterEqual(min(image.size), 1000)
        self.assertEqual(image.size[0], image.size[1])

    def test_encoded_url_is_exactly_the_referral_link(self):
        url = "http://testserver/r/AWA2026/"
        expected = expected_matrix(url)
        self.assertEqual(modules_from_png(self.get(fmt="png").content, len(expected)), expected)

    def test_the_encoded_url_follows_the_requested_host(self):
        url = "https://hayaflash.example/r/AWA2026/"
        with self.settings(ALLOWED_HOSTS=["hayaflash.example"]):
            response = self.client.get(self.qr_url(), secure=True, HTTP_HOST="hayaflash.example")
        expected = expected_matrix(url)
        self.assertEqual(modules_from_png(response.content, len(expected)), expected)

    def test_white_background_black_modules_and_quiet_zone(self):
        content = self.get(fmt="png").content
        image = Image.open(io.BytesIO(content)).convert("RGB")
        matrix = expected_matrix("http://testserver/r/AWA2026/")
        box = image.size[0] // len(matrix)
        colors = {c for _, c in image.getcolors(maxcolors=10)}
        self.assertEqual(colors, {(0, 0, 0), (255, 255, 255)})
        quiet = 4 * box
        w, h = image.size
        for region in ((0, 0, w, quiet), (0, h - quiet, w, h), (0, 0, quiet, h), (w - quiet, 0, w, h)):
            self.assertEqual(image.crop(region).getcolors(), [((region[2] - region[0]) * (region[3] - region[1]), (255, 255, 255))])

    def test_error_correction_is_at_least_m(self):
        # Les modules de format (niveau de correction) sont ceux d'un QR en niveau M.
        url = "http://testserver/r/AWA2026/"
        expected = expected_matrix(url)
        higher = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, border=4)
        higher.add_data(url)
        higher.make(fit=True)
        self.assertNotEqual(expected, higher.get_matrix())
        self.assertEqual(modules_from_png(self.get(fmt="png").content, len(expected)), expected)


class SvgDownloadTests(QrBase):
    def test_svg_headers_and_markup(self):
        response = self.get(fmt="svg")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/svg+xml")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="hayaflash-AWA2026.svg"')
        self.assertEqual(response["Cache-Control"], "private, no-store")
        text = response.content.decode()
        self.assertIn("<svg", text)
        self.assertIn("</svg>", text)
        self.assertNotIn("<script", text)

    def test_svg_has_a_white_background_and_black_modules(self):
        text = self.get(fmt="svg").content.decode()
        self.assertRegex(text, r'<rect[^>]*fill="#?(?:fff|ffffff|white)"')
        fills = set(re.findall(r'fill="([^"]+)"', text))
        self.assertTrue(fills <= {"#fff", "#ffffff", "white", "#000", "#000000", "black"}, fills)

    def test_svg_matrix_equals_the_one_of_the_referral_link(self):
        text = self.get(fmt="svg").content.decode()
        expected = expected_matrix("http://testserver/r/AWA2026/")
        cells = {
            (int(x), int(y))
            for x, y in re.findall(r"M(\d+),(\d+)H\d+V\d+H\d+z", re.search(r'<path[^>]*\sd="([^"]+)"', text).group(1))
        }
        drawn = {(x, y) for y, row in enumerate(expected) for x, on in enumerate(row) if on}
        self.assertEqual(cells, drawn)
        self.assertIn(f'viewBox="0 0 {len(expected)} {len(expected)}"', text)  # marge de 4 modules incluse


class NoPersonalDataTests(QrBase):
    def test_no_name_phone_or_shop_in_content_or_file_name(self):
        partner = make_partner(code="LEA2026", phone="+22360123456", name="Léa Boutique Diarra")
        forbidden = ["22360123456", "60123456", "Léa", "Boutique", "Diarra"]
        for fmt in ("png", "svg"):
            response = self.get(partner, fmt)
            self.assertEqual(response.status_code, 200)
            disposition = response["Content-Disposition"]
            self.assertEqual(disposition, f'attachment; filename="hayaflash-LEA2026.{fmt}"')
            body = response.content
            for word in forbidden:
                self.assertNotIn(word, disposition)
                self.assertNotIn(word.encode(), body)
        # Le QR n'encode que l'URL du lien : mêmes modules que le lien seul.
        expected = expected_matrix("http://testserver/r/LEA2026/")
        self.assertEqual(modules_from_png(self.get(partner, "png").content, len(expected)), expected)

    def test_nothing_is_stored(self):
        before = Partner.objects.count()
        self.get(fmt="png")
        self.get(fmt="svg")
        self.assertEqual(Partner.objects.count(), before)


class SheetTests(QrBase):
    def test_the_sheet_shows_the_full_link_and_both_downloads(self):
        html = self.client.get(reverse("partners_detail", args=[self.partner.pk])).content.decode()
        self.assertIn("http://testserver/r/AWA2026/", html)
        self.assertIn(self.qr_url(fmt="png"), html)
        self.assertIn(self.qr_url(fmt="svg"), html)
        self.assertIn("<svg", html)  # aperçu en ligne

    def test_the_preview_does_not_leak_personal_data(self):
        html = self.client.get(reverse("partners_detail", args=[self.partner.pk])).content.decode()
        preview = re.search(r'<svg class="hf-qr-svg".*?</svg>', html, flags=re.S).group(0)
        self.assertNotIn("Awa", preview)
        self.assertNotIn("2236000", preview)
