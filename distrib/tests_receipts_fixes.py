"""Correctifs de la recette locale (26/10) : parcours /f/ (tiroir), quotas d'echecs, 429, cookie hf_rc."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import Client, override_settings

from distrib.models import DistribSettlement
from distrib.services import receipts
from distrib.tests_receipts import PHONE, ReceiptBase
from orders.models import OrderStatus

BASE = Path(settings.BASE_DIR)
RECEIPT_JS = BASE / "distrib" / "static" / "distrib" / "receipt.js"
PUBLIC_JS = BASE / "static" / "js" / "hf-public.js"

LOOKUP = {"calling_code": "223", "phone": "76 00 00 01"}


class DrawerParcoursTests(ReceiptBase):
    """Anomalie 1 : le tiroir de /f/<slug>/ doit donner le meme code que /order/."""

    def page(self):
        return self.client.get(f"/f/{self.sale.public_slug}/")

    def test_public_sale_page_carries_the_receipt_hint_bound_to_the_drawer(self):
        html = self.page().content.decode()
        self.assertIn("data-distrib-hint-url", html)
        self.assertIn("$watch('orderSuccess'", html)
        self.assertIn("$data.submittedPhone", html)
        self.assertIn("distrib/receipt.js", html)

    def test_public_sale_page_embeds_no_csrf_token_it_is_served_from_cache(self):
        resp = self.page()
        self.assertEqual(re.search(r'data-distrib-csrf="([^"]*)"', resp.content.decode()).group(1), "")
        self.assertNotIn("csrftoken", resp.cookies)

    def test_drawer_stores_the_order_response_for_receipt_js(self):
        js = PUBLIC_JS.read_text(encoding="utf-8")
        self.assertIn("orderResult: null", js)
        self.assertIn("this.orderResult = data", js)

    @override_settings(DISTRIB_ENABLED=False)
    def test_switch_off_means_no_hint_on_the_public_sale_page(self):
        self.assertNotIn("data-distrib-hint-url", self.page().content.decode())

    def test_csrf_endpoint_lets_a_cookieless_visitor_fetch_the_code(self):
        client = Client(enforce_csrf_checks=True)
        refused = client.post("/distrib/recu/", {"order_id": self.order.pk, "phone": PHONE})
        self.assertEqual(refused.status_code, 403)
        token = client.get("/distrib/jeton/").json()["csrf"]
        self.assertTrue(token)
        ok = client.post("/distrib/recu/", {"order_id": self.order.pk, "phone": PHONE}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(ok.json()["lines"][0]["code"], "4821")


class CsrfEndpointRateLimitTests(ReceiptBase):
    def test_csrf_endpoint_is_limited_per_ip(self):
        for _ in range(receipts.CSRF_TOKENS_PER_WINDOW):
            self.assertEqual(self.client.get("/distrib/jeton/").status_code, 200)
        blocked = self.client.get("/distrib/jeton/")
        self.assertEqual((blocked.status_code, blocked.json()), (429, {"csrf": ""}))
        self.assertEqual(blocked["Cache-Control"].split(",")[0], "private")

    def test_csrf_endpoint_is_post_free_and_404_when_the_switch_is_off(self):
        with override_settings(DISTRIB_ENABLED=False):
            self.assertEqual(self.client.get("/distrib/jeton/").status_code, 404)


class QuotaTests(ReceiptBase):
    """Anomalie 2 : seuls les echecs comptent."""

    def hint(self, order_id=None, phone=PHONE):
        return self.client.post("/distrib/recu/", {"order_id": order_id or self.order.pk, "phone": phone})

    def lookup_post(self, code):
        return self.client.post("/distrib/confirmer/", {**LOOKUP, "code": code})

    def test_successful_hints_never_consume_the_quota(self):
        for _ in range(15):
            self.assertEqual(self.hint().status_code, 200)
        self.assertEqual(len(self.hint().json()["lines"]), 1)

    def test_orders_without_imported_product_do_not_burn_the_quota(self):
        from products.services.crud import attach_product_to_sale, create_product

        normal = create_product(owner=self.seller, name="Sac", price=Decimal("2000"), stock=50)
        attach_product_to_sale(flash_sale=self.sale, product=normal)
        for n in range(8):  # chaque commande ordinaire appelait /recu/ jusqu'a 3 fois
            phone = f"+2237611{n:04d}"
            order = self.place(product=normal, phone=phone)
            resp = self.hint(order_id=order.pk, phone=phone)
            self.assertEqual((resp.status_code, resp.json()), (200, {"lines": []}))
        self.assertEqual(len(self.hint().json()["lines"]), 1)

    def test_retry_flag_only_when_the_tracking_line_is_not_created_yet(self):
        self.assertNotIn("retry", self.hint().json())
        DistribSettlement.objects.filter(order=self.order).delete()
        self.assertTrue(self.hint().json()["retry"])

    def test_lookup_successes_do_not_consume_the_quota(self):
        for _ in range(receipts.FAILURES_PER_HOUR_PER_PHONE - 1):
            self.lookup_post("0000")
        for _ in range(10):
            resp = self.lookup_post("4821")
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "J'ai reçu ma commande")

    def test_abuse_is_still_blocked_even_with_the_right_code(self):
        for _ in range(receipts.FAILURES_PER_HOUR_PER_PHONE):
            self.lookup_post("0000")
        self.assertEqual(self.lookup_post("4821").status_code, 429)

    def test_quota_is_per_phone_other_customers_are_not_blocked(self):
        for _ in range(receipts.FAILURES_PER_HOUR_PER_PHONE):
            self.hint(phone="+22376999999")
        self.assertEqual(self.hint(phone="+22376999999").status_code, 429)
        self.assertEqual(self.hint().status_code, 200)


class ReceiptJsTests(ReceiptBase):
    """Anomalie 3a : le 429 est visible et ne declenche aucune boucle de nouvelles tentatives."""

    def test_receipt_js_stops_on_429_and_only_retries_when_the_server_asks(self):
        js = RECEIPT_JS.read_text(encoding="utf-8")
        self.assertIn("res.status === 429", js)
        self.assertIn("blocked: true", js)
        self.assertIn("data.retry", js)
        self.assertNotIn("data.lines.length && triesLeft", js)

    def test_hint_template_shows_a_message_when_blocked(self):
        page = self.client.get("/order/", {"flash_sale_id": self.sale.pk, "product_id": self.imported.product_id})
        html = page.content.decode()
        self.assertIn("data-distrib-blocked", html)
        self.assertIn("hfBlocked", html)

    def test_blocked_hint_answer_carries_the_flag(self):
        for _ in range(receipts.FAILURES_PER_HOUR_PER_PHONE):
            self.client.post("/distrib/recu/", {"order_id": 999999, "phone": PHONE})
        resp = self.client.post("/distrib/recu/", {"order_id": self.order.pk, "phone": PHONE})
        self.assertEqual((resp.status_code, resp.json()), (429, {"lines": [], "blocked": True}))


class FlagCookieTests(ReceiptBase):
    """Anomalie 3b : hf_rc / hf_receipts s'effacent quand plus aucun recu n'est ouvert."""

    def cookies_deleted(self, resp):
        return all(
            name in resp.cookies and resp.cookies[name]["max-age"] == 0
            for name in (receipts.COOKIE_NAME, receipts.COOKIE_FLAG_NAME)
        )

    def with_cookies(self):
        client = Client()
        client.cookies[receipts.COOKIE_NAME] = self.line_.receipt_token
        client.cookies[receipts.COOKIE_FLAG_NAME] = "1"
        return client

    def test_banner_keeps_cookies_while_a_receipt_is_open(self):
        resp = self.with_cookies().get("/distrib/bandeau/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(receipts.COOKIE_FLAG_NAME, resp.cookies)

    def test_customer_confirmation_clears_the_cookies(self):
        client = self.with_cookies()
        resp = client.post("/distrib/confirmer/valider/", {"token": self.line_.receipt_token})
        self.assertTrue(self.cookies_deleted(resp))
        self.assertEqual(client.get("/distrib/bandeau/").status_code, 204)

    def test_banner_clears_the_cookies_when_the_order_was_cancelled(self):
        self.order.status = OrderStatus.CANCELLED
        with self.captureOnCommitCallbacks(execute=True):
            self.order.save()
        resp = self.with_cookies().get("/distrib/bandeau/")
        self.assertEqual(resp.status_code, 204)
        self.assertTrue(self.cookies_deleted(resp))

    def test_another_open_receipt_keeps_the_flag(self):
        other = self.line(self.place(phone="+22376000002"))
        client = self.with_cookies()
        client.cookies[receipts.COOKIE_NAME] = f"{self.line_.receipt_token}.{other.receipt_token}"
        resp = client.post("/distrib/confirmer/valider/", {"token": self.line_.receipt_token})
        self.assertNotIn(receipts.COOKIE_FLAG_NAME, resp.cookies)

    def test_no_cookie_no_set_cookie(self):
        resp = Client().get("/distrib/bandeau/")
        self.assertEqual(resp.status_code, 204)
        self.assertNotIn(receipts.COOKIE_FLAG_NAME, resp.cookies)
