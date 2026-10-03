"""F-81 bloc 4 : marqueur « déjà prévenu » (contacted_at), HTMX, propriété (IDOR), CSRF."""

from __future__ import annotations

import re

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounts.models import SellerProfile
from flash_sales.models import FlashSaleStatus, SaleInterest
from flash_sales.services.notify_interests import interests_to_notify
from flash_sales.tests_alertes import AlertFixture

User = get_user_model()
HTMX = {"HTTP_HX_REQUEST": "true"}


class ContactedBase(AlertFixture):
    def setUp(self) -> None:
        super().setUp()
        self.page_url = reverse("flash_sales:interests")
        self.mark_url = reverse("flash_sales:interest_contacted")
        self.closed = self.make_sale(title="Ancienne", status=FlashSaleStatus.CLOSED, start_in_h=-9)
        self.next = self.make_sale(title="Super Drop", start_in_h=26)
        self.client.force_login(self.user)

        self.b_user = User.objects.create_user(phone="+22370000002", password="x", display_name="B")
        self.b = SellerProfile.objects.create(user=self.b_user, business_name="Boutique B")
        self.b_sale = self.make_sale(title="Chez B", start_in_h=5, owner=self.b)
        self.b_client = Client()
        self.b_client.force_login(self.b_user)

    def key(self, phone: str) -> str:
        return phone.lstrip("+")


class MarkContactedTests(ContactedBase):
    def test_marks_all_rows_of_the_same_number(self) -> None:
        a = SaleInterest.objects.create(flash_sale=self.closed, phone="+223 70 00 00 01")
        b = SaleInterest.objects.create(flash_sale=self.next, phone="00223 70 00 00 01")
        other = SaleInterest.objects.create(flash_sale=self.next, phone="+22371111111")
        resp = self.client.post(self.mark_url, {"key": "22370000001"}, **HTMX)
        self.assertEqual(resp.status_code, 200, resp.content)
        for row in (a, b, other):
            row.refresh_from_db()
        self.assertIsNotNone(a.contacted_at)
        self.assertIsNotNone(b.contacted_at)
        self.assertIsNone(other.contacted_at)

    def test_response_is_the_greyed_row_without_the_button(self) -> None:
        SaleInterest.objects.create(flash_sale=self.closed, phone="+22370000001", name="Awa")
        resp = self.client.post(self.mark_url, {"key": "22370000001"}, **HTMX)
        html = resp.content.decode()
        self.assertNotIn("<html", html)
        self.assertIn("opacity-50", html)
        self.assertIn("Prévenu", html)
        self.assertNotIn("Marquer comme prévenu", html)

    def test_page_shows_button_for_pending_and_grey_for_contacted(self) -> None:
        SaleInterest.objects.create(flash_sale=self.closed, phone="+22370000001", name="Awa")
        SaleInterest.objects.create(flash_sale=self.closed, phone="+22371111111", name="Moussa")
        self.client.post(self.mark_url, {"key": "22370000001"}, **HTMX)
        html = self.client.get(self.page_url).content.decode()
        self.assertEqual(html.count("Marquer comme prévenu"), 1)
        self.assertEqual(html.count("opacity-50"), 1)
        tag = re.search(r"<button[^>]*hx-post=\"%s\"[^>]*>" % re.escape(self.mark_url), html).group(0)
        self.assertIn('hx-target="#notify-22371111111"', tag)
        self.assertIn('hx-swap="outerHTML"', tag)

    def test_legacy_number_without_country_code_can_be_marked(self) -> None:
        row = SaleInterest.objects.create(flash_sale=self.closed, phone="70 00 00 01")
        (inv,) = interests_to_notify(self.seller)
        self.assertEqual(self.client.post(self.mark_url, {"key": inv.key}, **HTMX).status_code, 200)
        row.refresh_from_db()
        self.assertIsNotNone(row.contacted_at)

    def test_hx_vals_stays_valid_json_for_odd_legacy_numbers(self) -> None:
        import json
        from html import unescape

        SaleInterest.objects.create(flash_sale=self.closed, phone='70"00')
        html = self.client.get(self.page_url).content.decode()
        raw = re.search(r"hx-vals='([^']*)'", html).group(1)
        self.assertEqual(list(json.loads(unescape(raw))), ["key"])

    def test_unknown_key_is_404(self) -> None:
        SaleInterest.objects.create(flash_sale=self.closed, phone="+22370000001")
        self.assertEqual(self.client.post(self.mark_url, {"key": "99999999999"}, **HTMX).status_code, 404)
        self.assertEqual(self.client.post(self.mark_url, {}, **HTMX).status_code, 404)

    def test_new_signup_after_contact_is_pending_again(self) -> None:
        SaleInterest.objects.create(flash_sale=self.closed, phone="+22370000001")
        self.client.post(self.mark_url, {"key": "22370000001"}, **HTMX)
        self.assertIsNotNone(interests_to_notify(self.seller)[0].contacted_at)
        SaleInterest.objects.create(flash_sale=self.next, phone="+22370000001")
        self.assertIsNone(interests_to_notify(self.seller)[0].contacted_at)

    def test_plain_post_redirects_instead_of_showing_a_bare_fragment(self) -> None:
        SaleInterest.objects.create(flash_sale=self.closed, phone="+22370000001")
        resp = self.client.post(self.mark_url, {"key": "22370000001"})
        self.assertRedirects(resp, self.page_url, fetch_redirect_response=False)

    def test_get_is_not_allowed(self) -> None:
        self.assertEqual(self.client.get(self.mark_url).status_code, 405)


class ContactedOwnershipTests(ContactedBase):
    """IDOR : un vendeur ne marque que ses propres inscrits."""

    def test_seller_b_cannot_mark_seller_a_subscriber(self) -> None:
        a_row = SaleInterest.objects.create(flash_sale=self.closed, phone="+22370000001")
        resp = self.b_client.post(self.mark_url, {"key": "22370000001"}, **HTMX)
        self.assertEqual(resp.status_code, 404)
        a_row.refresh_from_db()
        self.assertIsNone(a_row.contacted_at)

    def test_same_number_at_both_sellers_only_marks_own_rows(self) -> None:
        a_row = SaleInterest.objects.create(flash_sale=self.closed, phone="+22370000001")
        b_row = SaleInterest.objects.create(flash_sale=self.b_sale, phone="+22370000001")
        self.assertEqual(self.b_client.post(self.mark_url, {"key": "22370000001"}, **HTMX).status_code, 200)
        a_row.refresh_from_db()
        b_row.refresh_from_db()
        self.assertIsNone(a_row.contacted_at)
        self.assertIsNotNone(b_row.contacted_at)

    def test_anonymous_is_redirected_and_changes_nothing(self) -> None:
        row = SaleInterest.objects.create(flash_sale=self.closed, phone="+22370000001")
        resp = Client().post(self.mark_url, {"key": "22370000001"}, **HTMX)
        self.assertEqual(resp.status_code, 302)
        row.refresh_from_db()
        self.assertIsNone(row.contacted_at)

    def test_user_without_seller_profile_is_refused(self) -> None:
        row = SaleInterest.objects.create(flash_sale=self.closed, phone="+22370000001")
        buyer = User.objects.create_user(phone="+22370000003", password="x", display_name="C")
        c = Client()
        c.force_login(buyer)
        resp = c.post(self.mark_url, {"key": "22370000001"}, **HTMX)
        self.assertIn(resp.status_code, (302, 403))
        row.refresh_from_db()
        self.assertIsNone(row.contacted_at)


class ContactedCsrfTests(ContactedBase):
    def test_csrf_is_enforced(self) -> None:
        SaleInterest.objects.create(flash_sale=self.closed, phone="+22370000001")
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.user)
        self.assertEqual(c.post(self.mark_url, {"key": "22370000001"}, **HTMX).status_code, 403)
        c.get(self.page_url)  # pose le cookie csrftoken
        token = c.cookies["csrftoken"].value
        resp = c.post(self.mark_url, {"key": "22370000001"}, HTTP_X_CSRFTOKEN=token, **HTMX)
        self.assertEqual(resp.status_code, 200)
