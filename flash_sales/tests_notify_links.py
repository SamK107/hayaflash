"""F-81 bloc 3 : liens wa.me « Prévenir » sur la page des réservations du vendeur."""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.urls import reverse

from accounts.models import SellerProfile
from flash_sales.models import FlashSaleStatus, SaleInterest
from flash_sales.tests_alertes import AlertFixture

User = get_user_model()


class NotifyLinksTests(AlertFixture):
    def setUp(self) -> None:
        super().setUp()
        self.url = reverse("flash_sales:interests")
        self.client.force_login(self.user)
        self.closed = self.make_sale(
            title="Ancienne", status=FlashSaleStatus.CLOSED, start_in_h=-9
        )
        self.next = self.make_sale(title="Super Drop", start_in_h=26)

    def _links(self, html: str) -> list[str]:
        return [unescape(m) for m in re.findall(r'href="(https://wa\.me/[^"]+)"', html)]

    def _message(self, link: str) -> str:
        return parse_qs(urlparse(link).query)["text"][0]

    def test_link_and_prefilled_french_message(self) -> None:
        SaleInterest.objects.create(flash_sale=self.closed, phone="+223 70 00 00 01", name="Fatoumata Traoré")
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        (link,) = self._links(resp.content.decode())
        self.assertTrue(link.startswith("https://wa.me/22370000001?text="), link)
        msg = self._message(link)
        self.assertIn("Bonjour Fatoumata,", msg)
        self.assertIn("Awa Boutique", msg)
        self.assertIn("Super Drop", msg)
        self.assertRegex(msg, r"Ouverture \w+ \d{1,2} \w+ à \d{1,2} h")
        self.assertIn(f"http://testserver/f/{self.next.public_slug}/", msg)

    def test_message_is_url_encoded(self) -> None:
        SaleInterest.objects.create(flash_sale=self.closed, phone="+22370000001", name="A&B é")
        (link,) = self._links(self.client.get(self.url).content.decode())
        raw_query = urlparse(link).query
        self.assertNotIn(" ", raw_query)
        self.assertNotIn("&B", raw_query.replace("%26B", ""))  # « & » du prénom encodé
        self.assertIn("%C3%A0", raw_query)  # « à » encodé en UTF-8

    def test_anchor_opens_in_new_tab_safely(self) -> None:
        SaleInterest.objects.create(flash_sale=self.closed, phone="+22370000001")
        html = self.client.get(self.url).content.decode()
        tag = re.search(r'<a [^>]*href="https://wa\.me/[^"]+"[^>]*>', html).group(0)
        self.assertIn('target="_blank"', tag)
        self.assertIn('rel="noopener"', tag)

    def test_no_name_greeting(self) -> None:
        SaleInterest.objects.create(flash_sale=self.closed, phone="+22370000001")
        (link,) = self._links(self.client.get(self.url).content.decode())
        self.assertTrue(self._message(link).startswith("Bonjour,"))

    def test_invalid_number_shows_number_without_link(self) -> None:
        SaleInterest.objects.create(flash_sale=self.closed, phone="1234567", name="Douteux")
        html = self.client.get(self.url).content.decode()
        self.assertEqual(self._links(html), [])
        self.assertIn("numéro à vérifier", html)
        self.assertIn("1234567", html)

    def test_duplicates_give_one_link(self) -> None:
        SaleInterest.objects.create(flash_sale=self.closed, phone="+22370000001")
        SaleInterest.objects.create(flash_sale=self.next, phone="70 00 00 01")
        self.assertEqual(len(self._links(self.client.get(self.url).content.decode())), 1)

    def test_no_scheduled_sale_says_so_and_has_no_link(self) -> None:
        self.next.delete()
        SaleInterest.objects.create(flash_sale=self.closed, phone="+22370000001")
        html = self.client.get(self.url).content.decode()
        self.assertEqual(self._links(html), [])
        self.assertIn("Vous n'avez aucune vente programmée", unescape(html))

    def test_never_shows_another_sellers_subscribers(self) -> None:
        other_user = User.objects.create_user(phone="+22370000002", password="x", display_name="B")
        other = SellerProfile.objects.create(user=other_user, business_name="Boutique B")
        other_sale = self.make_sale(title="Chez B", start_in_h=5, owner=other)
        SaleInterest.objects.create(flash_sale=other_sale, phone="+22379999999", name="ClientDeB")
        SaleInterest.objects.create(flash_sale=self.closed, phone="+22370000001", name="Mon client")
        html = self.client.get(self.url).content.decode()
        self.assertNotIn("22379999999", html)
        self.assertNotIn("ClientDeB", html)
        self.assertIn("Mon client", html)
        self.assertEqual(len(self._links(html)), 1)

    def test_page_requires_login(self) -> None:
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
