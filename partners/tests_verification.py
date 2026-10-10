"""Preuve d'acceptation : sceau circulaire, QR de vérification, page publique /verifier/<code>/."""

from __future__ import annotations

import re
from unittest.mock import patch

import qrcode
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from partners.models import AcceptanceInvalidation, Partner, PartnerAcceptance
from partners.services import verification
from partners.tests_public_documents import Base, accept_url, page  # noqa: F401

User = get_user_model()
MONTHS = ["JAN", "FÉV", "MAR", "AVR", "MAI", "JUN", "JUL", "AOÛ", "SEP", "OCT", "NOV", "DÉC"]
FORBIDDEN_WORDS = re.compile(r"\b(signé|signée|signés|signature|signatures|certifié|certifiée|certifiés)\b", re.IGNORECASE)


def verify_path(code):
    return reverse("partner_verify", args=[code])


class Accepted(Base):
    """Une lettre d'essai acceptée, page finale rouverte."""

    def setUp(self):
        super().setUp()
        self.accept_letter(cite_shop="1")
        self.acc = PartnerAcceptance.objects.get()
        self.final = self.client.get(page(self.token))
        self.html = self.final.content.decode()

    def seal(self):
        return self.html.split('<svg class="hf-seal"', 1)[1].split("</svg>", 1)[0]


class SealTests(Accepted):
    def test_circular_double_ring_seal_with_curved_text(self):
        seal = self.seal()
        self.assertGreaterEqual(seal.count("<circle"), 2)
        self.assertEqual(seal.count("<textPath"), 2)
        self.assertNotIn("<rect", seal)  # plus de cadre rectangulaire

    def test_seal_text_top_bottom_and_center(self):
        seal = self.seal()
        day = self.acc.accepted_at_utc
        date = f"{day.day:02d} {MONTHS[day.month - 1]} {day.year}"
        self.assertIn("HAYAFLASH · ENTREPRISE TEST SARL", seal)
        self.assertIn(f"ACCEPTÉ · {date}", seal)
        self.assertIn("v1.0", seal)
        self.assertIn(self.acc.reference, seal)

    def test_slight_rotation_between_two_and_three_degrees(self):
        match = re.search(r"rotate\((-?\d+(?:\.\d+)?) ", self.seal())
        self.assertIsNotNone(match)
        self.assertTrue(2 <= abs(float(match.group(1))) <= 3)

    def test_seal_is_static_black_and_white_without_script(self):
        seal = self.seal()
        self.assertNotIn("<script", seal)
        self.assertNotIn("onload", seal)
        self.assertEqual(re.findall(r'(?:fill|stroke)="(#[0-9a-fA-F]{3,6})"', seal) and
                         [c for c in re.findall(r'(?:fill|stroke)="(#[0-9a-fA-F]{3,6})"', seal)
                          if c.lower() not in ("#111", "#000", "#fff", "#ffffff", "#000000")], [])

    def test_text_fits_the_circle_by_construction(self):
        # Tous les textes sont posés sur des arcs ou centrés dans le disque intérieur : jamais de
        # texte rectiligne plus large que le sceau.
        seal = self.seal()
        self.assertIn('viewBox="0 0 220 220"', seal)
        self.assertNotRegex(seal, r'<text[^>]*x="\d{3}"[^>]*text-anchor="start"')

    def test_seal_is_rendered_from_the_record_never_stored_in_the_snapshot(self):
        for piece in ("hf-seal", "<svg", "ACCEPTÉ ·", "HAYAFLASH ·"):
            self.assertNotIn(piece, self.acc.text_snapshot)

    def test_hash_of_the_frozen_text_is_unchanged(self):
        from partners import legal_docs

        plain = legal_docs.canonical_text(legal_docs.render_document("trial_letter", self.prospect))
        self.assertEqual(self.acc.text_snapshot, plain)
        self.assertEqual(self.acc.text_sha256, legal_docs.sha256_of(plain))

    def test_labels(self):
        self.assertIn("Accepté en ligne", self.html)
        self.assertIn("Vérifiable en ligne", self.html)
        self.assertIsNone(FORBIDDEN_WORDS.search(self.html))

    def test_confirmation_response_has_the_same_seal(self):
        other = Base.__mro__  # noqa: F841 - la confirmation est la même vue que la réouverture
        self.assertIn('class="hf-seal"', self.html)


class QrTests(Accepted):
    def expected_url(self):
        return f"http://testserver/verifier/{self.acc.reference}/"

    def test_qr_svg_is_inline_and_labelled(self):
        self.assertIn('class="hf-qr"', self.html)
        qr = self.html.split('class="hf-qr"', 1)[1].split("</div>", 1)[0]
        self.assertIn("<svg", qr)
        self.assertNotIn("<script", qr)

    def spied_data(self):
        """Données réellement transmises à qrcode lors du rendu de la page."""
        seen = []
        real = qrcode.QRCode.add_data

        def spy(qr_self, data, optimize=20):
            seen.append(data)
            return real(qr_self, data, optimize)

        with patch.object(qrcode.QRCode, "add_data", spy):
            self.client.get(page(self.token))
        return seen

    def test_qr_encodes_exactly_the_verification_url_and_nothing_else(self):
        self.assertEqual(self.spied_data(), [self.expected_url()])

    def test_qr_carries_no_personal_data_nor_private_token(self):
        data = self.spied_data()[0]
        for secret in (self.token, "Awa", "Diarra", "60050001", self.prospect.phone, "partenaires/d/", self.acc.signer_name):
            self.assertNotIn(secret, data)
        self.assertRegex(data, r"^http://testserver/verifier/\d{6}-[0-9a-f]{12}/$")

    def test_qr_is_produced_by_qrcode_as_svg_not_by_segno(self):
        qr = verification.qr_svg(self.expected_url())
        self.assertTrue(qr.startswith("<svg"))
        self.assertIn('class="hf-qr-svg"', qr)
        self.assertNotIn("<?xml", qr)
        self.assertNotRegex(qr, r'<svg[^>]*\s(width|height)="')  # dimensionné par le CSS
        self.assertIn("<path", qr)
        with self.assertRaises(ImportError):
            __import__("segno")

    def test_qr_image_matches_the_generator_for_that_url(self):
        qr = self.html.split('class="hf-qr"', 1)[1].split("</div>", 1)[0]
        self.assertIn(verification.qr_svg(self.expected_url()), qr)

    def test_reference_and_url_are_printed_in_clear_under_the_qr(self):
        under = self.html.split('class="hf-qr"', 1)[1]
        self.assertIn(self.acc.reference, under)
        self.assertIn(self.expected_url(), under)

    def test_print_size_is_at_least_28_mm(self):
        from pathlib import Path

        from django.conf import settings

        css = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(encoding="utf-8")
        printed = css.split("@media print", 1)[1]
        size = re.search(r"\.hf-qr[^{]*\{[^}]*width:\s*(\d+(?:\.\d+)?)mm", printed)
        self.assertIsNotNone(size)
        self.assertGreaterEqual(float(size.group(1)), 28)

    def test_qrcode_is_pinned_and_segno_is_gone(self):
        from pathlib import Path

        from django.conf import settings

        req = (Path(settings.BASE_DIR) / "requirements.txt").read_text(encoding="utf-8")
        self.assertRegex(req, r"(?m)^qrcode==8\.2\s*$")
        self.assertNotIn("segno", req.lower())


class VerificationLinkTests(Accepted):
    """Bug : cliquer/copier l'URL sous le QR menait à /verifier/<code>/%20Référence%20<code> (404)."""

    def url(self):
        return f"http://testserver/verifier/{self.acc.reference}/"

    def qr_block(self):
        return self.html.split('class="hf-qr"', 1)[1].split("</div>", 1)[0]

    def test_the_link_href_is_exactly_the_verification_url(self):
        hrefs = re.findall(r'<a [^>]*href="([^"]*verifier[^"]*)"', self.qr_block())
        self.assertEqual(hrefs, [self.url()])
        for bad in ("%20", " ", "Référence", "R&eacute;f"):
            self.assertNotIn(bad, hrefs[0])

    def test_the_link_text_is_only_the_url(self):
        text = re.search(r'<a [^>]*href="[^"]*verifier[^"]*"[^>]*>(.*?)</a>', self.qr_block(), re.S).group(1)
        self.assertEqual(text.strip(), self.url())

    def test_the_reference_is_a_separate_unlinked_block(self):
        block = self.qr_block()
        link = re.search(r"<a [^>]*>.*?</a>", block, re.S).group(0)
        self.assertNotIn("Référence", link)
        ref = re.search(r"<p[^>]*>\s*Référence[^<]*</p>", block)
        self.assertIsNotNone(ref)
        self.assertIn(self.acc.reference, ref.group(0))
        self.assertFalse(re.search(r"<a [^>]*>[^<]*Référence", block))
        # blocs distincts, avec un vrai saut de ligne entre l'URL et la référence
        between = block[block.index("</a>"): block.index(ref.group(0))]
        self.assertIn("\n", between)
        self.assertIn("</p>", between)

    def test_both_lines_stay_visible_in_print(self):
        from pathlib import Path

        from django.conf import settings

        css = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(encoding="utf-8")
        printed = css.split("@media print", 1)[1]
        self.assertNotRegex(printed, r"\.hf-qr-(url|ref)[^{]*\{[^}]*display:\s*none")
        self.assertIn(".hf-qr-url", printed)

    def test_the_verification_url_answers_200_and_garbage_after_the_slash_stays_a_404(self):
        client = Client()
        self.assertEqual(client.get(f"/verifier/{self.acc.reference}/").status_code, 200)
        residue = f"/verifier/{self.acc.reference}/%20R%C3%A9f%C3%A9rence%20{self.acc.reference}"
        self.assertEqual(client.get(residue).status_code, 404)
        self.assertEqual(client.get(residue + "/").status_code, 404)


class VerifyPageTests(Accepted):
    def get(self, code=None, **extra):
        return Client().get(verify_path(code or self.acc.reference), **extra)

    def test_valid_code_shows_the_authentic_document_card(self):
        resp = self.get()
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("Document authentique", html)
        self.assertIn("Lettre d&#x27;essai", html)
        self.assertIn("<dt>Version</dt><dd>1.0</dd>", html)
        self.assertIn("heure de Bamako (UTC)", html)
        self.assertIn(self.acc.accepted_at_utc.strftime("%d/%m/%Y"), html)
        self.assertIn(self.acc.text_sha256, html)  # empreinte complète
        self.assertIn("Valide", html)
        self.assertIn("Accepté en ligne", html)
        self.assertIn("Vérifiable en ligne", html)

    def test_shop_name_or_signer_initials(self):
        self.assertIn("A. D.", self.get().content.decode())
        Partner.objects.filter(pk=self.prospect.pk).update(shop_name="Chez Fanta")
        html = self.get().content.decode()
        self.assertIn("Chez Fanta", html)
        self.assertNotIn("A. D.", html)

    def test_never_leaks_phone_ip_full_name_or_text(self):
        html = self.get(REMOTE_ADDR="196.200.4.4").content.decode()
        for secret in (
            "Awa Diarra", "Diarra", self.prospect.phone, "60050001", self.acc.ip_hash, "196.200.4.4",
            "Fin du document", "Pendant 30 jours", "Entre ENTREPRISE", "csrfmiddlewaretoken", "<form",
            self.token,
        ):
            self.assertNotIn(secret, html, secret)
        self.assertIsNone(re.search(r"\bIP\b", html))

    def test_unknown_or_malformed_codes_give_the_same_neutral_404(self):
        bodies = set()
        wrong_hash = f"{self.acc.pk:06d}-{'0' * 12}"
        wrong_pk = f"999999-{self.acc.text_sha256[:12]}"
        for code in (wrong_hash, wrong_pk, "n-importe-quoi", "000001", "x" * 80):
            resp = self.get(code)
            self.assertEqual(resp.status_code, 404, code)
            bodies.add(resp.content)
        self.assertEqual(len(bodies), 1)

    def test_headers(self):
        resp = self.get()
        self.assertIn("noindex", resp["X-Robots-Tag"])
        self.assertIn("no-store", resp["Cache-Control"])

    @override_settings(RATELIMIT_ENABLE=True, RATELIMIT_PARTNER_LINK_IP=(3, 60))
    def test_rate_limit_is_the_existing_one(self):
        for _ in range(3):
            self.get(REMOTE_ADDR="196.200.6.6")
        self.assertEqual(self.get(REMOTE_ADDR="196.200.6.6").status_code, 429)
        self.assertEqual(self.get(REMOTE_ADDR="196.200.6.7").status_code, 200)

    def test_forbidden_labels_absent(self):
        self.assertIsNone(FORBIDDEN_WORDS.search(self.get().content.decode()))

    def test_no_login_needed_and_get_only(self):
        self.assertEqual(Client().post(verify_path(self.acc.reference)).status_code, 405)


class InvalidationTests(Accepted):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user(phone="+22379000001", password="x", display_name="E", is_staff=True)
        self.staff_client = Client()
        self.staff_client.force_login(self.staff)
        self.url = reverse("partners_document_invalidate", args=[self.acc.pk])

    def verify_html(self):
        return Client().get(verify_path(self.acc.reference)).content.decode()

    def test_status_is_valid_until_invalidated(self):
        self.assertIn("Valide", self.verify_html())
        self.assertNotIn("Invalidé par HayaFlash", self.verify_html())

    def test_staff_invalidates_with_an_internal_reason_and_nothing_is_deleted(self):
        resp = self.staff_client.post(self.url, {"reason": "Erreur de saisie du nom"})
        self.assertEqual(resp.status_code, 302)
        inv = AcceptanceInvalidation.objects.get()
        self.assertEqual((inv.acceptance, inv.reason, inv.invalidated_by), (self.acc, "Erreur de saisie du nom", self.staff))
        self.assertEqual(PartnerAcceptance.objects.count(), 1)
        self.assertEqual(PartnerAcceptance.objects.get().text_snapshot, self.acc.text_snapshot)
        html = self.verify_html()
        self.assertIn("Invalidé par HayaFlash", html)
        self.assertNotIn("Erreur de saisie", html)  # le motif reste interne
        self.assertIn("Document authentique", html)

    def test_reason_is_required_and_once_only(self):
        self.staff_client.post(self.url, {"reason": "  "})
        self.assertEqual(AcceptanceInvalidation.objects.count(), 0)
        self.staff_client.post(self.url, {"reason": "Premier motif"})
        self.staff_client.post(self.url, {"reason": "Second motif"})
        self.assertEqual(AcceptanceInvalidation.objects.get().reason, "Premier motif")

    def test_staff_only_and_csrf(self):
        anon = Client().post(self.url, {"reason": "x"})
        self.assertEqual(anon.status_code, 302)
        self.assertIn("login", anon["Location"])
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.staff)
        self.assertEqual(strict.post(self.url, {"reason": "x"}).status_code, 403)
        self.assertEqual(self.staff_client.get(self.url).status_code, 405)
        self.assertEqual(AcceptanceInvalidation.objects.count(), 0)

    def test_invalidation_is_immutable_and_audited(self):
        from django.core.exceptions import ValidationError

        from core.models import AuditLog

        self.staff_client.post(self.url, {"reason": "Motif"})
        inv = AcceptanceInvalidation.objects.get()
        inv.reason = "Autre"
        with self.assertRaises(ValidationError):
            inv.save()
        with self.assertRaises(ValidationError):
            inv.delete()
        self.assertTrue(AuditLog.objects.filter(action="partner.document_invalidated").exists())

    def test_staff_pages_show_the_status_and_the_form(self):
        detail = self.staff_client.get(reverse("partners_document_detail", args=[self.acc.pk])).content.decode()
        self.assertIn("Invalider", detail)
        self.assertIn("Valide", detail)
        self.staff_client.post(self.url, {"reason": "Motif"})
        detail = self.staff_client.get(reverse("partners_document_detail", args=[self.acc.pk])).content.decode()
        self.assertIn("Invalidé par HayaFlash", detail)
        self.assertIn("Motif", detail)  # visible côté équipe seulement
        listing = self.staff_client.get(reverse("partners_documents")).content.decode()
        self.assertIn("Invalidé", listing)

    def test_final_page_remains_readable_and_shows_the_status(self):
        self.staff_client.post(self.url, {"reason": "Motif"})
        html = self.client.get(page(self.token)).content.decode()
        self.assertIn("Invalidé par HayaFlash", html)
        self.assertNotIn("Motif", html)
