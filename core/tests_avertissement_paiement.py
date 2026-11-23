"""Avertissement de paiement cote cliente (EXECUTION_V2 § 3 « Confiance et paiement »).

Le texte est ecrit une seule fois, dans templates/partials/_payment_warning.html,
et inclus sur la page de vente, le formulaire de commande et la confirmation.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.urls import reverse

from analytics.tests import ViralGrowthFixture

WARNING = (
    "Paie à la livraison, une fois le produit vérifié et conforme. Si tu choisis de payer avant, "
    "c'est sous ta propre responsabilité et en connaissance des risques. HayaFlash ne reçoit aucun "
    "paiement et ne garantit pas les transactions entre toi et la vendeuse."
)
PARTIAL = "partials/_payment_warning.html"
TEMPLATES_DIR = Path(settings.BASE_DIR) / "templates"
GABARITS = (
    TEMPLATES_DIR / "analytics" / "flash_sale_public.html",
    TEMPLATES_DIR / "orders" / "client_order.html",
)


class PaymentWarningTemplateTests(ViralGrowthFixture):
    def test_text_written_once_in_templates(self) -> None:
        # La phrase n'apparait que dans le partiel : pas de copie dans une page.
        hits = [
            p for p in TEMPLATES_DIR.rglob("*.html")
            if "Paie à la livraison, une fois" in p.read_text(encoding="utf-8")
        ]
        self.assertEqual(hits, [TEMPLATES_DIR / "partials" / "_payment_warning.html"])

    def test_gabarits_include_the_partial(self) -> None:
        for path in GABARITS:
            with self.subTest(gabarit=path.name):
                self.assertIn('{% include "' + PARTIAL + '" %}', path.read_text(encoding="utf-8"))

    def test_no_misspelled_payment_label_in_gabarits(self) -> None:
        for path in GABARITS:
            with self.subTest(gabarit=path.name):
                self.assertNotIn("a la livraison", path.read_text(encoding="utf-8"))


class PaymentWarningPagesTests(ViralGrowthFixture):
    def test_sale_page_shows_warning(self) -> None:
        url = reverse("public_flash_sale", kwargs={"slug": self.sale.public_slug})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        # Formulaire de commande (tiroir) + confirmation du tiroir.
        self.assertContains(resp, WARNING, count=2)
        self.assertNotContains(resp, "a la livraison")

    def test_order_form_and_confirmation_show_warning(self) -> None:
        url = reverse("client_order") + f"?flash_sale_id={self.sale.pk}&product_id={self.product.pk}"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        # Formulaire + confirmation.
        self.assertContains(resp, WARNING, count=2)
        self.assertNotContains(resp, "a la livraison")


class ReportLinkOnConfirmationTests(ViralGrowthFixture):
    def test_sale_page_confirmation_links_to_report_form(self) -> None:
        url = reverse("public_flash_sale", kwargs={"slug": self.sale.public_slug})
        resp = self.client.get(url)
        report_url = reverse("shop_report", kwargs={"slug": self.seller.public_slug})
        self.assertContains(resp, f'href="{report_url}"')
        self.assertContains(resp, "Signale-la ici")

    def test_order_confirmation_links_to_report_form(self) -> None:
        url = reverse("client_order") + f"?flash_sale_id={self.sale.pk}&product_id={self.product.pk}"
        resp = self.client.get(url)
        report_url = reverse("shop_report", kwargs={"slug": self.seller.public_slug})
        self.assertContains(resp, f'href="{report_url}"')
