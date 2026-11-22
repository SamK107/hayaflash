"""Signalement public d'une boutique (/signaler/<slug>/) : formulaire, anti-bot, limite, neutralite."""

from __future__ import annotations

import time
from decimal import Decimal

from django.core.cache import cache
from django.db.models import ProtectedError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import SellerProfile, ShopReport, User
from core.services import honeypot
from products.models import Product

SENT = "Merci, ton signalement a bien été reçu."
RATE = "Trop de signalements depuis ce réseau."


class ShopReportTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        user = User.objects.create_user(phone="+22370000301", password="x", display_name="Awa")
        self.shop = SellerProfile.objects.create(
            user=user, business_name="Awa Boutique", public_slug="awa-boutique",
        )
        self.url = reverse("shop_report", kwargs={"slug": "awa-boutique"})

    def _data(self, **overrides):
        base = {
            "reason": ShopReport.Reason.NOT_DELIVERED,
            "message": "Commande payée, rien reçu.",
            "contact": "",
            "website": "",
            honeypot.TIMESTAMP_FIELD: honeypot.make_token(issued_at=time.time() - 10),
        }
        base.update(overrides)
        return base

    def test_get_active_shop_shows_form(self) -> None:
        resp = Client().get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Motif")
        self.assertContains(resp, 'name="csrfmiddlewaretoken"')
        self.assertEqual(ShopReport.objects.count(), 0)

    def test_unknown_or_inactive_shop_is_404(self) -> None:
        self.assertEqual(Client().get(reverse("shop_report", kwargs={"slug": "inconnue"})).status_code, 404)
        self.shop.is_active = False
        self.shop.save()
        self.assertEqual(Client().get(self.url).status_code, 404)
        self.assertEqual(Client().post(self.url, self._data()).status_code, 404)
        self.assertEqual(ShopReport.objects.count(), 0)

    def test_valid_post_creates_new_report_and_neutral_answer(self) -> None:
        resp = Client().post(self.url, self._data(contact="  +22370000399  "))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, SENT)
        report = ShopReport.objects.get()
        self.assertEqual(report.shop, self.shop)
        self.assertEqual(report.reason, ShopReport.Reason.NOT_DELIVERED)
        self.assertEqual(report.status, ShopReport.Status.NEW)
        self.assertEqual(report.contact, "+22370000399")
        self.assertEqual(report.message, "Commande payée, rien reçu.")
        # Reponse neutre : aucune donnee de la vendeuse hors nom affiche deja sur la page.
        self.assertNotContains(resp, "+22370000301")

    def test_csrf_is_enforced(self) -> None:
        resp = Client(enforce_csrf_checks=True).post(self.url, self._data())
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(ShopReport.objects.count(), 0)

    def test_honeypot_filled_is_rejected_without_saving(self) -> None:
        resp = Client().post(self.url, self._data(website="http://spam.example"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, SENT)
        self.assertEqual(ShopReport.objects.count(), 0)

    def test_invalid_reason_or_too_long_message_rejected(self) -> None:
        self.assertEqual(Client().post(self.url, self._data(reason="inconnu")).status_code, 200)
        self.assertEqual(Client().post(self.url, self._data(message="x" * 501)).status_code, 200)
        self.assertEqual(Client().post(self.url, self._data(contact="c" * 121)).status_code, 200)
        self.assertEqual(ShopReport.objects.count(), 0)

    @override_settings(RATELIMIT_ENABLE=True, RATELIMIT_SHOP_REPORT_IP=(2, 3600))
    def test_rate_limit_per_ip_blocks_third_submission(self) -> None:
        client = Client(REMOTE_ADDR="198.51.100.7")
        for _ in range(2):
            self.assertContains(client.post(self.url, self._data()), SENT)
        resp = client.post(self.url, self._data())
        self.assertEqual(resp.status_code, 429)
        self.assertContains(resp, RATE, status_code=429)
        self.assertEqual(ShopReport.objects.count(), 2)

    def test_shop_with_reports_cannot_be_deleted(self) -> None:
        ShopReport.objects.create(shop=self.shop, reason=ShopReport.Reason.OTHER)
        with self.assertRaises(ProtectedError):
            self.shop.delete()
        self.assertEqual(ShopReport.objects.count(), 1)

    def test_reports_do_not_touch_products_or_sales(self) -> None:
        product = Product.objects.create(
            owner=self.shop, name="Sac", stock_available=3, stock_initial=3, price=Decimal("5000.00"),
        )
        Client().post(self.url, self._data())
        product.refresh_from_db()
        self.assertEqual(product.stock_available, 3)
        self.shop.refresh_from_db()
        self.assertTrue(self.shop.is_active)


class ShopReportAdminTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.admin_user = User.objects.create_superuser(
            phone="+22370000390", password="x", display_name="Equipe",
        )
        user = User.objects.create_user(phone="+22370000391", password="x", display_name="Awa")
        self.shop = SellerProfile.objects.create(user=user, business_name="Awa Boutique")
        other_user = User.objects.create_user(phone="+22370000392", password="x", display_name="Bah")
        self.other = SellerProfile.objects.create(user=other_user, business_name="Bah Boutique")
        ShopReport.objects.create(shop=self.shop, reason=ShopReport.Reason.NOT_CONFORM)
        ShopReport.objects.create(shop=self.shop, reason=ShopReport.Reason.SCAM_SUSPECTED,
                                  status=ShopReport.Status.HANDLED)
        ShopReport.objects.create(shop=self.other, reason=ShopReport.Reason.OTHER)
        self.client.force_login(self.admin_user)

    def test_changelist_filters_by_status_and_shop(self) -> None:
        url = reverse("admin:accounts_shopreport_changelist")
        resp = self.client.get(url + "?status__exact=new")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["cl"].result_list), 2)
        resp = self.client.get(url + f"?shop__id__exact={self.shop.pk}")
        self.assertEqual(len(resp.context["cl"].result_list), 2)
        self.assertContains(resp, "2")  # compteur par boutique

    def test_seller_changelist_counts_reports(self) -> None:
        resp = self.client.get(reverse("admin:accounts_sellerprofile_changelist"))
        self.assertEqual(resp.status_code, 200)
        counts = {row.pk: row._reports_count for row in resp.context["cl"].result_list}
        self.assertEqual(counts[self.shop.pk], 2)
        self.assertEqual(counts[self.other.pk], 1)

    def test_no_add_or_delete_for_reports(self) -> None:
        url = reverse("admin:accounts_shopreport_add")
        self.assertEqual(self.client.get(url).status_code, 403)
        report = ShopReport.objects.first()
        delete_url = reverse("admin:accounts_shopreport_delete", args=[report.pk])
        self.assertEqual(self.client.get(delete_url).status_code, 403)
