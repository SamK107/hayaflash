"""F-81 : inscription « M'alerter » au format international, selecteur d'indicatif."""

from __future__ import annotations

import json
import re

from django.core.cache import cache
from django.urls import reverse

from flash_sales.models import FlashSaleStatus, SaleInterest
from flash_sales.tests_alertes import AlertFixture, _static_text


class InterestPhoneEndpointTests(AlertFixture):
    def setUp(self) -> None:
        super().setUp()
        self.sale = self.make_sale(start_in_h=3)
        self.url = reverse("flash_sale_interest", kwargs={"slug": self.sale.public_slug})

    def _post(self, phone, name="Awa"):
        cache.clear()
        return self.client.post(
            self.url,
            data=json.dumps({"phone": phone, "name": name}),
            content_type="application/json",
        )

    def test_stores_full_international_number(self) -> None:
        resp = self._post("+223 70 00 00 01")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(SaleInterest.objects.get().phone, "+22370000001")

    def test_00_prefix_is_normalised(self) -> None:
        self.assertEqual(self._post("00221 77 123 45 67").status_code, 201)
        self.assertEqual(SaleInterest.objects.get().phone, "+221771234567")

    def test_number_without_country_code_is_refused_in_french(self) -> None:
        resp = self._post("70 00 00 01")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("indicatif", resp.json()["error"])
        self.assertEqual(SaleInterest.objects.count(), 0)

    def test_wrong_length_for_country_is_refused(self) -> None:
        resp = self._post("+225 70 00 00 01")  # Cote d'Ivoire : 10 chiffres attendus
        self.assertEqual(resp.status_code, 400)
        self.assertIn("10 chiffres", resp.json()["error"])

    def test_unknown_country_is_refused(self) -> None:
        resp = self._post("+33 6 12 34 56 78")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("non pris en charge", resp.json()["error"])


class InterestDrawerCountrySelectTests(AlertFixture):
    def _page(self, sale) -> str:
        cache.clear()
        url = reverse("public_flash_sale", kwargs={"slug": sale.public_slug})
        return self.client.get(url).content.decode()

    def test_waiting_and_end_drawers_have_the_selector(self) -> None:
        html = self._page(self.make_sale(start_in_h=3))
        self.assertIn('id="interest-cc-w"', html)
        live = self._page(self.make_sale(status=FlashSaleStatus.LIVE, start_in_h=-1, duration_h=3))
        self.assertIn('id="interest-cc-end"', live)
        sel = re.search(r'<select[^>]*id="interest-cc-w".*?</select>', html, re.S).group(0)
        self.assertEqual(len(re.findall(r"<option", sel)), 9)
        self.assertRegex(sel, r'<option value="\+223"\s+selected')
        for code in ("+221", "+225", "+226", "+227", "+224", "+228", "+229", "+222"):
            self.assertIn(f'value="{code}"', sel)

    def test_closed_page_drawer_has_the_selector(self) -> None:
        sale = self.make_sale(status=FlashSaleStatus.CLOSED, start_in_h=-9)
        self.assertIn('id="interest-cc-end"', self._page(sale))

    def test_js_sends_the_full_international_number(self) -> None:
        js = _static_text("js/hf-public.js")
        body = js[js.index("async function submitInterest"):js.index("function hfOpenInterestEnd")]
        self.assertIn("interest-cc", body)
