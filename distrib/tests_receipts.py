"""P6b : confirmation par la cliente (SPEC_03 §15.3) — test 16, 17 et garde-fous des deux includes."""

from __future__ import annotations

import re
from decimal import Decimal

from django.core.cache import cache
from django.test import Client, override_settings
from django.utils import timezone

from core.models import AuditLog
from distrib.models import DistribSettlement
from distrib.services import receipts
from distrib.services import settlement as svc
from distrib.tests_settlement import SettlementBase
from orders.models import OrderStatus

S = DistribSettlement.Status
PHONE = "+22376000001"


class ReceiptBase(SettlementBase):
    def setUp(self):
        super().setUp()
        cache.clear()  # compteurs de debit
        self.order = self.place(phone=PHONE)
        self.line_ = self.line(self.order)
        DistribSettlement.objects.filter(pk=self.line_.pk).update(receipt_code="4821")
        self.line_.refresh_from_db()

    def cookie(self, client=None, *tokens):
        client = client or self.client
        client.cookies[receipts.COOKIE_NAME] = ".".join(tokens or [self.line_.receipt_token])
        return client

    def lookup(self, phone="76 00 00 01", code="4821", calling_code="223", client=None):
        return (client or self.client).post(
            "/distrib/confirmer/", {"calling_code": calling_code, "phone": phone, "code": code}
        )

    def refresh(self):
        self.line_.refresh_from_db()
        return self.line_


class CodeGenerationTests(ReceiptBase):
    def test_code_and_token_shape(self):
        fresh = self.line(self.place(phone="+22376000002"))
        self.assertRegex(fresh.receipt_code, r"^\d{4}$")
        self.assertGreaterEqual(len(fresh.receipt_token), 22)
        self.assertNotEqual(fresh.receipt_token, self.refresh().receipt_token)

    def test_code_is_unique_among_the_open_lines_of_one_customer(self):
        DistribSettlement.objects.all().delete()
        codes = {self.line(self.place(phone="+22376000009")).receipt_code for _ in range(1)}
        for _ in range(12):
            line = DistribSettlement.objects.filter(order=self.place(phone="+22376000009")).get()
            self.assertNotIn(line.receipt_code, codes)
            codes.add(line.receipt_code)

    def test_code_is_never_shown_on_the_distributor_or_reseller_side(self):
        for user, urls in (
            (self.d.user, ["/distrib/", "/distrib/commandes/", "/distrib/stock/", "/distrib/resellers/"]),
            (self.seller.user, ["/seller/", "/distrib/mes-grossistes/", f"/distrib/mes-grossistes/{self.invite.pk}/"]),
        ):
            self.client.force_login(user)
            for url in urls:
                page = self.client.get(url.replace("resellers", "revendeurs"))
                self.assertNotContains(page, "4821", msg_prefix=url)
                self.assertNotContains(page, self.line_.receipt_token, msg_prefix=url)


class HintEndpointTests(ReceiptBase):
    """Acces 1 : le code revient a la cliente qui vient de commander, et le cookie est pose."""

    def hint(self, order_id=None, phone=PHONE, client=None):
        return (client or self.client).post(
            "/distrib/recu/", {"order_id": order_id or self.order.pk, "phone": phone}
        )

    def test_returns_the_code_and_sets_the_httponly_cookie(self):
        resp = self.hint()
        self.assertEqual(resp.json(), {"lines": [{"name": "Robe wax", "code": "4821"}]})
        cookie = resp.cookies[receipts.COOKIE_NAME]
        self.assertEqual(cookie.value, self.line_.receipt_token)
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(int(cookie["max-age"]), 30 * 24 * 3600)
        self.assertEqual(resp["Cache-Control"], "private, no-store")
        # Drapeau lisible par le JS : aucune donnee.
        flag = resp.cookies[receipts.COOKIE_FLAG_NAME]
        self.assertEqual((flag.value, flag["httponly"]), ("1", ""))

    def test_phone_format_does_not_matter_but_the_number_must_match(self):
        for phone in ("76 00 00 01", "+223 76 00 00 01", "0022376000001"):
            self.assertEqual(len(self.hint(phone=phone).json()["lines"]), 1, phone)
        cache.clear()
        resp = self.hint(phone="+22377777777")
        self.assertEqual(resp.json(), {"lines": []})
        self.assertNotIn(receipts.COOKIE_NAME, resp.cookies)

    def test_wrong_or_unknown_order_gives_the_same_empty_answer(self):
        self.assertEqual(self.hint(order_id=999999).json(), {"lines": []})
        self.assertEqual(self.hint(order_id="abc").json(), {"lines": []})
        self.assertEqual(self.hint(phone="").json(), {"lines": []})

    def test_order_without_imported_product_gives_nothing(self):
        from products.services.crud import attach_product_to_sale, create_product

        normal = create_product(owner=self.seller, name="Sac", price=Decimal("2000"), stock=5)
        attach_product_to_sale(flash_sale=self.sale, product=normal)
        other = self.place(product=normal, phone="+22376000044")
        self.assertEqual(self.hint(order_id=other.pk, phone="+22376000044").json(), {"lines": []})

    def test_only_open_lines(self):
        svc.distributor_confirm(self.line_, self.d.user)
        self.assertEqual(self.hint().json(), {"lines": []})

    def test_cookie_keeps_the_five_latest_tokens_only_and_no_personal_data(self):
        client = Client()
        tokens = []
        for n in range(7):
            phone = f"+2237600{n:04d}"
            order = self.place(phone=phone)
            line = self.line(order)
            tokens.append(line.receipt_token)
            self.hint(order_id=order.pk, phone=phone, client=client)
            cache.clear()
        value = client.cookies[receipts.COOKIE_NAME].value
        self.assertEqual(value.split("."), list(reversed(tokens))[:5])
        self.assertNotIn("7600", value)
        self.assertNotIn("Cliente", value)

    def test_rate_limit_per_phone(self):
        for _ in range(5):
            self.assertEqual(self.hint().status_code, 200)
        self.assertEqual(self.hint().status_code, 429)

    def test_csrf_is_enforced_and_works_from_the_order_page_token(self):
        client = Client(enforce_csrf_checks=True)
        refused = client.post("/distrib/recu/", {"order_id": self.order.pk, "phone": PHONE})
        self.assertEqual(refused.status_code, 403)
        page = client.get("/order/", {"flash_sale_id": self.sale.pk, "product_id": self.imported.product_id})
        token = re.search(r'data-distrib-csrf="([^"]+)"', page.content.decode()).group(1)
        resp = client.post(
            "/distrib/recu/", {"order_id": self.order.pk, "phone": PHONE}, HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["lines"]), 1)

    def test_switch_off_means_404(self):
        with override_settings(DISTRIB_ENABLED=False):
            self.assertEqual(self.hint().status_code, 404)


class BannerTests(ReceiptBase):
    def test_banner_only_with_the_cookie_and_an_open_line(self):
        self.assertEqual(self.client.get("/distrib/bandeau/").status_code, 204)
        client = self.cookie(Client())
        resp = client.get("/distrib/bandeau/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Tu as reçu ta commande")
        self.assertContains(resp, f"/distrib/recu/{self.line_.receipt_token}/")
        self.assertIn("no-store", resp["Cache-Control"])
        self.assertIn("private", resp["Cache-Control"])
        self.assertIn("Cookie", resp["Vary"])

    def test_no_banner_once_confirmed_cancelled_or_paid(self):
        client = self.cookie(Client())
        for transition in ("paid", "cancelled", "customer"):
            DistribSettlement.objects.filter(pk=self.line_.pk).update(
                status=S.ORDERED, customer_confirmed_at=None
            )
            self.assertEqual(client.get("/distrib/bandeau/").status_code, 200, transition)
            if transition == "paid":
                DistribSettlement.objects.filter(pk=self.line_.pk).update(status=S.PAID_CONFIRMED)
            elif transition == "cancelled":
                DistribSettlement.objects.filter(pk=self.line_.pk).update(status=S.CANCELLED)
            else:
                DistribSettlement.objects.filter(pk=self.line_.pk).update(customer_confirmed_at=timezone.now())
            self.assertEqual(client.get("/distrib/bandeau/").status_code, 204, transition)

    def test_a_not_delivered_line_still_shows_the_banner(self):
        svc.declare_not_delivered(self.line_, self.d.user, reason="absent")
        self.assertEqual(self.cookie(Client()).get("/distrib/bandeau/").status_code, 200)

    def test_forged_or_unknown_tokens_show_nothing(self):
        client = Client()
        client.cookies[receipts.COOKIE_NAME] = "abc.%3Cscript%3E.zzzzzzzzzzzzzzzzzzzzzzzz"
        self.assertEqual(client.get("/distrib/bandeau/").status_code, 204)

    def test_only_one_banner_the_most_recent_line(self):
        second = self.line(self.place(phone="+22376000002"))
        client = self.cookie(Client(), self.line_.receipt_token, second.receipt_token)
        resp = client.get("/distrib/bandeau/")
        self.assertEqual(resp.content.decode().count("Tu as reçu ta commande"), 1)
        self.assertContains(resp, second.receipt_token)

    def test_off_means_404(self):
        with override_settings(DISTRIB_ENABLED=False):
            self.assertEqual(self.cookie(Client()).get("/distrib/bandeau/").status_code, 404)

    def test_confirmation_page_from_the_banner_needs_the_cookie(self):
        url = f"/distrib/recu/{self.line_.receipt_token}/"
        self.assertContains(self.client.get(url), "Rien à confirmer")
        self.assertContains(self.cookie(Client()).get(url), "J'ai reçu ma commande")


class PublicHooksTests(ReceiptBase):
    """Includes de base.html (lien + conteneur) et de client_order.html (code)."""

    def test_link_and_container_on_public_pages_only(self):
        for url in ("/ventes/", f"/f/{self.sale.public_slug}/", "/"):
            page = self.client.get(url)
            self.assertContains(page, "Confirmer un paiement", msg_prefix=url)
            self.assertContains(page, 'id="hf-distrib-banner"', msg_prefix=url)
            self.assertContains(page, "distrib/banner.js", msg_prefix=url)
        self.client.force_login(self.seller.user)
        self.assertNotContains(self.client.get("/seller/"), "Confirmer un paiement")
        self.assertNotContains(self.client.get("/distrib/mes-grossistes/"), "hf-distrib-banner")

    def test_fragment_is_identical_for_every_visitor(self):
        anonymous = self.client.get("/ventes/").content.decode()
        with_cookie = self.cookie(Client()).get("/ventes/").content.decode()
        block = lambda html: re.search(r'<div id="hf-distrib-banner".*?banner\.js', html, re.S).group(0)  # noqa: E731
        self.assertEqual(block(anonymous), block(with_cookie))
        self.assertNotIn(self.line_.receipt_token, with_cookie)  # le cookie ne fuit jamais dans la page

    def test_switch_off_means_no_link_no_banner_no_page(self):
        with override_settings(DISTRIB_ENABLED=False):
            page = self.client.get("/ventes/")
            self.assertNotContains(page, "Confirmer un paiement")
            self.assertNotContains(page, "hf-distrib-banner")
            self.assertEqual(self.client.get("/distrib/confirmer/").status_code, 404)
            order_page = self.client.get(
                "/order/", {"flash_sale_id": self.sale.pk, "product_id": self.imported.product_id}
            )
            self.assertEqual(order_page.status_code, 200)
            self.assertNotContains(order_page, "distrib-hint-url")

    def test_order_page_carries_the_hint_once_inside_the_alpine_scope(self):
        page = self.client.get("/order/", {"flash_sale_id": self.sale.pk, "product_id": self.imported.product_id})
        html = page.content.decode()
        self.assertEqual(html.count("data-distrib-hint-url"), 1)
        self.assertIn("distrib/receipt.js", html)
        start = html.index('x-data="clientOrderForm(')
        self.assertLess(start, html.index("data-distrib-hint-url"))

    def test_no_inline_script_or_handler_in_the_new_fragments(self):
        html = self.client.get("/order/", {"flash_sale_id": self.sale.pk, "product_id": self.imported.product_id}).content.decode()
        fragment = html[html.index('x-data="{ hfRc'):html.index("receipt.js")]
        self.assertNotRegex(fragment, r"<script(?![^>]*\bsrc=)")
        self.assertNotRegex(fragment, r"\son[a-z]+\s*=")


class LookupPageTests(ReceiptBase):
    """Acces 2 : numero + code a 4 chiffres."""

    def test_right_pair_shows_the_confirmation_button(self):
        resp = self.lookup()
        self.assertContains(resp, "J'ai reçu ma commande")
        self.assertContains(resp, "Référence Orange Money (facultatif)")
        self.assertNotContains(resp, "4821")  # le code n'est pas rendu en retour

    def test_wrong_code_wrong_phone_and_unknown_phone_get_the_same_neutral_answer(self):
        answers = []
        for kwargs in ({"code": "0000"}, {"phone": "77 77 77 77"}, {"phone": "70 12 34 56", "code": "1111"}):
            resp = self.lookup(**kwargs)
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, receipts_neutral())
            # Seules les valeurs saisies (renvoyees dans le formulaire) peuvent differer.
            answers.append(re.sub(r'value="[^"]*"', 'value=""', resp.content.decode()))
        self.assertEqual(len(set(answers)), 1)

    def test_bad_formats_are_rejected_by_the_form(self):
        for kwargs in ({"code": "12"}, {"code": "abcd"}, {"phone": "123"}, {"calling_code": "999"}):
            resp = self.lookup(**kwargs)
            self.assertNotContains(resp, "J'ai reçu ma commande")

    def test_rate_limit_five_attempts_per_hour_per_number(self):
        for _ in range(5):
            self.assertEqual(self.lookup(code="0000").status_code, 200)
        blocked = self.lookup()  # meme avec le bon code
        self.assertEqual(blocked.status_code, 429)
        self.assertNotContains(blocked, "J'ai reçu ma commande", status_code=429)

    def test_rate_limit_per_ip_across_numbers(self):
        for n in range(5):
            self.lookup(phone=f"7{n} 00 00 0{n}", code="0000")
        self.assertEqual(self.lookup(phone="70 99 99 99", code="0000").status_code, 429)

    def test_phone_of_another_customer_with_the_same_code_does_not_match(self):
        other = self.place(phone="+22376000002")
        DistribSettlement.objects.filter(order=other).update(receipt_code="4821")
        resp = self.lookup(phone="76 00 00 02")
        self.assertEqual(resp.context["line"].order_id, other.pk)

    def test_locked_when_not_open(self):
        svc.distributor_confirm(self.line_, self.d.user)
        self.assertContains(self.lookup(), receipts_neutral())


def receipts_neutral():
    from distrib.views_receipts import NEUTRAL_MESSAGE

    return NEUTRAL_MESSAGE


class ConfirmationTests(ReceiptBase):
    def validate(self, token=None, om="", client=None):
        return (client or self.client).post(
            "/distrib/confirmer/valider/", {"token": token or self.line_.receipt_token, "om_reference": om}
        )

    def test_customer_confirms_a_line_that_was_not_yet_confirmed(self):
        resp = self.validate()
        self.assertContains(resp, "Merci")
        line = self.refresh()
        self.assertEqual((line.status, line.confirmation_source), (S.PAID_CONFIRMED, "customer"))
        self.assertIsNotNone(line.customer_confirmed_at)
        self.assertIsNotNone(line.paid_confirmed_at)
        self.assertEqual((line.commission_amount, line.commission_billable), (Decimal("288"), True))
        self.assertEqual(line.receipt_code, "")  # code invalide apres confirmation

    def test_code_is_invalidated_after_confirmation(self):
        self.validate()
        self.assertContains(self.lookup(), receipts_neutral())

    def test_double_confirmation_has_no_effect(self):
        self.validate(om="OM111")
        stamp = self.refresh().paid_confirmed_at
        self.validate(om="OM222")
        line = self.refresh()
        self.assertEqual((line.customer_om_reference, line.paid_confirmed_at), ("OM111", stamp))
        self.assertEqual(DistribSettlement.objects.filter(status=S.PAID_CONFIRMED).count(), 1)

    def test_not_delivered_line_gets_a_conflict_flag_and_no_status_change(self):
        svc.declare_not_delivered(self.line_, self.d.user, reason="absent")
        self.validate(om="OM9")
        line = self.refresh()
        self.assertEqual(line.status, S.NOT_DELIVERED)
        self.assertTrue(line.conflict_flag)
        self.assertIsNone(line.paid_confirmed_at)
        self.assertEqual((line.commission_amount, line.confirmation_source), (Decimal("0"), ""))
        self.assertTrue(AuditLog.objects.filter(action="distrib.signal.customer_confirmed_not_delivered").exists())
        # La cliente a pu se manifester par la page de secours aussi : meme resultat.

    def test_not_delivered_is_reachable_through_the_lookup_page(self):
        svc.declare_not_delivered(self.line_, self.d.user, reason="refused")
        self.assertContains(self.lookup(), "J'ai reçu ma commande")

    def test_already_paid_line_only_records_the_reference(self):
        svc.distributor_confirm(self.line_, self.d.user)
        self.validate(om="OM42")
        line = self.refresh()
        self.assertEqual((line.status, line.confirmation_source, line.customer_om_reference), (S.PAID_CONFIRMED, "distributor", "OM42"))

    def test_cancelled_order_is_closed(self):
        self.set_order_status(self.order, OrderStatus.CANCELLED)
        resp = self.validate()
        self.assertContains(resp, "Rien à confirmer")
        self.assertEqual(self.refresh().status, S.CANCELLED)

    def test_unknown_or_malformed_token_is_neutral(self):
        for token in ("nope", "x" * 30, "<script>"):
            self.assertContains(self.validate(token=token), "Rien à confirmer")

    def test_test17_om_reference_is_optional_cleaned_and_bounded(self):
        self.assertEqual(receipts.clean_om_reference("  MP 24.10.26 / ab-12 "), "MP241026ab12")
        self.assertEqual(receipts.clean_om_reference("<b>x</b>"), "bxb")
        self.assertEqual(len(receipts.clean_om_reference("A" * 200)), receipts.OM_MAX_LENGTH)
        self.assertEqual(receipts.clean_om_reference(None), "")
        self.validate(om="")  # facultatif
        self.assertEqual(self.refresh().customer_om_reference, "")

    def test_test17_reference_is_visible_to_the_three_parties(self):
        self.validate(om="OM777")
        self.client.force_login(self.d.user)
        self.assertContains(self.client.get("/distrib/commandes/"), "OM777")
        self.assertContains(self.client.get("/distrib/commandes/"), "La cliente a confirmé la réception")
        staff = self.d.user
        staff.is_staff = True
        staff.save()
        DistribSettlement.objects.filter(pk=self.line_.pk).update(conflict_flag=True)
        self.client.force_login(staff)
        self.assertContains(self.client.get("/distrib/pilotage/signaux/"), "La cliente a confirmé la réception")

    def test_full_flow_via_banner_cookie(self):
        client = Client()
        hint = client.post("/distrib/recu/", {"order_id": self.order.pk, "phone": PHONE})
        self.assertEqual(len(hint.json()["lines"]), 1)
        self.assertEqual(client.get("/distrib/bandeau/").status_code, 200)
        page = client.get(f"/distrib/recu/{self.line_.receipt_token}/")
        self.assertContains(page, "J'ai reçu ma commande")
        client.post("/distrib/confirmer/valider/", {"token": self.line_.receipt_token})
        self.assertEqual(self.refresh().status, S.PAID_CONFIRMED)
        self.assertEqual(client.get("/distrib/bandeau/").status_code, 204)
