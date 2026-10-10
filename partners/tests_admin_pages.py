"""BLOC F : pages admin du programme partenaires (staff uniquement)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import SellerProfile
from partners.models import (
    CommissionEntry,
    Partner,
    PartnerClick,
    Payout,
    Referral,
)
from partners.services.dates import add_months
from partners.services.payouts import build_payout
from partners.tests_commissions import pay
from partners.tests_models import make_partner, make_seller

User = get_user_model()
PLATFORM = "/platform-admin/"


def at(y, m, d=10):
    return datetime(y, m, d, 12, tzinfo=dt_timezone.utc)


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user(
            phone="+22379000001", password="x", display_name="Equipe", is_staff=True
        )
        self.seller_user = User.objects.create_user(phone="+22379000002", password="x", display_name="Vendeur")
        SellerProfile.objects.create(user=self.seller_user)
        self.client = Client()
        self.client.force_login(self.staff)
        self.partner = make_partner(code="AWA2026", name="Awa Créatrice", accept=False)
        self._n = 0

    def referral(self, partner=None, *, name="Boutique Fanta", flagged=False):
        self._n += 1
        s = make_seller(f"+223702100{self._n:02d}")
        SellerProfile.objects.filter(pk=s.pk).update(business_name=name)
        return Referral.objects.create(
            partner=partner or self.partner, seller=s, flagged=flagged,
            attributed_at=timezone.now(), first_paid_at=at(2026, 10), commission_ends_at=at(2027, 10),
        )

    def entry(self, referral, *, commission=2500, status="validated", when=None):
        when = when or timezone.now()
        net = max(1980, commission)
        gross = max(2000, net)
        return CommissionEntry.objects.create(
            referral=referral, payment=pay(referral.seller, amount=gross, paid_at=when),
            gross_fcfa=gross, net_fcfa=net, percent=30, commission_fcfa=commission, status=status,
        )

    def url(self, name, *args):
        return reverse(name, args=args)


class AccessTests(Base):
    def urls(self):
        r = self.referral()
        self.entry(r)
        po = Payout.objects.create(partner=self.partner, period="2026-10", total_fcfa=2500)
        pk = self.partner.pk
        return {
            "get": [
                self.url("partners_dashboard"),
                self.url("partners_list"),
                self.url("partners_detail", pk),
                self.url("partners_csv_partner", pk) + "?period=2026-10",
                self.url("partners_csv_internal", pk) + "?period=2026-10",
            ],
            "post": [
                self.url("partners_release", pk),
                self.url("partners_validate", pk),
                self.url("partners_build_payout", pk),
                self.url("partners_mark_paid", po.pk),
            ],
        }

    def test_anonymous_gets_the_same_answer_as_the_platform_page(self):
        platform = Client().get(PLATFORM)
        urls = self.urls()
        for url in urls["get"]:
            with self.subTest(url=url):
                resp = Client().get(url)
                self.assertEqual(resp.status_code, platform.status_code)
                self.assertEqual(resp["Location"].split("?")[0], platform["Location"].split("?")[0])
        for url in urls["post"]:
            with self.subTest(url=url):
                resp = Client().post(url)
                self.assertEqual(resp.status_code, platform.status_code)

    def test_seller_gets_the_same_answer_as_the_platform_page(self):
        client = Client()
        client.force_login(self.seller_user)
        platform = client.get(PLATFORM)
        urls = self.urls()
        for url in urls["get"]:
            with self.subTest(url=url):
                resp = client.get(url)
                self.assertEqual(resp.status_code, platform.status_code)
                self.assertEqual(resp["Location"].split("?")[0], platform["Location"].split("?")[0])
        for url in urls["post"]:
            with self.subTest(url=url):
                self.assertEqual(client.post(url).status_code, platform.status_code)

    def test_staff_can_open_every_page(self):
        for url in self.urls()["get"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_actions_refuse_get(self):
        for url in self.urls()["post"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)

    def test_actions_require_csrf(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.staff)
        for url in self.urls()["post"]:
            with self.subTest(url=url):
                self.assertEqual(strict.post(url).status_code, 403)

    def test_unknown_partner_is_404_for_staff(self):
        self.assertEqual(self.client.get(self.url("partners_detail", 99999)).status_code, 404)


class DashboardTests(Base):
    def test_empty_state(self):
        Partner.objects.all().delete()
        page = self.client.get(self.url("partners_dashboard"))
        self.assertContains(page, "Aucun partenaire")
        self.assertContains(page, "0 / 20")

    def test_kpis(self):
        for i in range(7):
            make_partner(code=f"FND{i:03d}", phone=f"+2236100{i:04d}", is_founder=True)
        r = self.referral()
        PartnerClick.objects.create(partner=self.partner, ip_hash="a" * 16)
        PartnerClick.objects.create(partner=self.partner, ip_hash="b" * 16)
        self.entry(r, commission=2500, status="validated")
        self.entry(self.referral(), commission=600, status="pending")
        page = self.client.get(self.url("partners_dashboard"))
        self.assertContains(page, "7 / 20")
        self.assertEqual(page.context["stats"]["clicks"], 2)
        self.assertEqual(page.context["stats"]["referrals"], 2)
        self.assertEqual(page.context["stats"]["payers"], 2)
        self.assertEqual(page.context["stats"]["to_validate_fcfa"], 600)
        self.assertEqual(page.context["stats"]["to_pay_fcfa"], 2500)
        # revenu attribué du mois = net des paiements du mois, en FCFA
        self.assertEqual(page.context["stats"]["attributed_net_fcfa"], 2500 + 1980)
        self.assertContains(page, "(FCFA)")

    def test_funnel_rates(self):
        r = self.referral()
        for i in range(4):
            PartnerClick.objects.create(partner=self.partner, ip_hash=f"{i}" * 16)
        self.entry(r)
        rows = {row["partner"].code: row for row in self.client.get(self.url("partners_dashboard")).context["funnel"]}
        row = rows["AWA2026"]
        self.assertEqual((row["clicks"], row["signups"], row["payers"]), (4, 1, 1))
        self.assertEqual(row["signup_rate"], 25)
        self.assertEqual(row["payer_rate"], 100)

    def test_query_count_does_not_grow_with_the_data(self):
        self.client.get(self.url("partners_dashboard"))  # chauffe les caches de session
        with CaptureQueriesContext(connection) as small:
            self.client.get(self.url("partners_dashboard"))
        for i in range(8):
            p = make_partner(code=f"CRE{i:03d}", phone=f"+2236200{i:04d}")
            for _ in range(3):
                r = self.referral(p)
                self.entry(r, commission=2500)
                PartnerClick.objects.create(partner=p, ip_hash="z" * 16)
        with CaptureQueriesContext(connection) as large:
            self.client.get(self.url("partners_dashboard"))
        self.assertLessEqual(len(large), len(small) + 2)
        self.assertLessEqual(len(large), 25)


class AlertsTests(Base):
    def alerts(self):
        return self.client.get(self.url("partners_dashboard")).context["alerts"]

    def test_inactive_for_sixty_days(self):
        Partner.objects.filter(pk=self.partner.pk).update(
            contract_start=timezone.localdate() - timedelta(days=100)
        )
        self.assertEqual([p.code for p in self.alerts()["inactive"]], ["AWA2026"])

    def test_recent_activity_clears_the_alert(self):
        Partner.objects.filter(pk=self.partner.pk).update(contract_start=timezone.localdate() - timedelta(days=100))
        PartnerClick.objects.create(partner=self.partner, ip_hash="a" * 16)
        self.assertEqual(self.alerts()["inactive"], [])

    def test_young_partner_without_activity_is_not_inactive_yet(self):
        self.assertEqual(self.alerts()["inactive"], [])

    def test_flagged_referrals(self):
        self.referral(flagged=True)
        self.assertEqual(len(self.alerts()["flagged"]), 1)

    def test_releasable_slots(self):
        Partner.objects.filter(pk=self.partner.pk).update(
            contract_start=add_months(timezone.localdate(), -10),
            contract_end=add_months(timezone.localdate(), 2),
        )
        self.assertEqual([p.code for p in self.alerts()["releasable"]], ["AWA2026"])

    def test_overdue_payouts(self):
        Payout.objects.create(partner=self.partner, period="2025-01", total_fcfa=2500)
        Payout.objects.create(partner=self.partner, period="2099-01", total_fcfa=2500)
        self.assertEqual([p.period for p in self.alerts()["overdue"]], ["2025-01"])

    def test_paid_payout_is_not_overdue(self):
        Payout.objects.create(partner=self.partner, period="2025-01", total_fcfa=2500, status="paid")
        self.assertEqual(self.alerts()["overdue"], [])


class ListTests(Base):
    def test_list_shows_status_contract_and_amounts(self):
        r = self.referral()
        self.entry(r, commission=2500, status="validated")
        self.entry(self.referral(), commission=700, status="paid")
        page = self.client.get(self.url("partners_list"))
        self.assertContains(page, "Awa Créatrice")
        self.assertContains(page, "Actif")
        self.assertContains(page, f"{self.partner.contract_end:%d/%m/%Y}")
        row = page.context["rows"][0]
        self.assertEqual((row["due_fcfa"], row["paid_fcfa"]), (2500, 700))

    def test_list_flags_the_quarterly_warning(self):
        Partner.objects.filter(pk=self.partner.pk).update(
            contract_start=add_months(timezone.localdate(), -7), contract_end=add_months(timezone.localdate(), 5)
        )
        page = self.client.get(self.url("partners_list"))
        self.assertTrue(page.context["rows"][0]["quarterly"]["warning"])
        self.assertContains(page, "Avertissement")

    def test_empty_list(self):
        Partner.objects.all().delete()
        self.assertContains(self.client.get(self.url("partners_list")), "Aucun partenaire")


class DetailTests(Base):
    def test_staff_sees_seller_names_commissions_and_payouts(self):
        r = self.referral(name="Boutique Fanta")
        self.entry(r, commission=2500)
        build_payout(self.partner, timezone.localtime(timezone.now()).strftime("%Y-%m"))
        page = self.client.get(self.url("partners_detail", self.partner.pk))
        self.assertContains(page, "Boutique Fanta")
        self.assertContains(page, "2 500")
        self.assertContains(page, "(FCFA)")

    def test_statement_zone_is_copyable_and_anonymous(self):
        r = self.referral(name="Boutique Fanta")
        self.entry(r, commission=2500)
        period = timezone.localtime(timezone.now()).strftime("%Y-%m")
        page = self.client.get(self.url("partners_detail", self.partner.pk), {"period": period})
        self.assertContains(page, 'id="releve-texte"')
        self.assertContains(page, 'data-hf-copy-from="#releve-texte"')
        statement = page.context["statement"]
        self.assertIn("Vendeur 1", statement)
        self.assertNotIn("Fanta", statement)

    def test_invalid_period_falls_back_to_current_month(self):
        page = self.client.get(self.url("partners_detail", self.partner.pk), {"period": "n'importe quoi"})
        self.assertEqual(page.status_code, 200)

    def test_buttons_are_post_forms_with_csrf_and_confirmation(self):
        self.entry(self.referral())
        html = self.client.get(self.url("partners_detail", self.partner.pk)).content.decode()
        self.assertIn("csrfmiddlewaretoken", html)
        self.assertIn("data-hf-confirm", html)
        self.assertIn(self.url("partners_validate", self.partner.pk), html)
        self.assertIn(self.url("partners_build_payout", self.partner.pk), html)

    def test_validate_action(self):
        period = timezone.localtime(timezone.now()).strftime("%Y-%m")
        e = self.entry(self.referral(), status="pending")
        resp = self.client.post(self.url("partners_validate", self.partner.pk), {"period": period})
        self.assertEqual(resp.status_code, 302)
        e.refresh_from_db()
        self.assertEqual(e.status, "validated")

    def test_build_payout_then_mark_paid_requires_reference(self):
        period = timezone.localtime(timezone.now()).strftime("%Y-%m")
        self.entry(self.referral(), commission=2500)
        self.client.post(self.url("partners_build_payout", self.partner.pk), {"period": period})
        payout = Payout.objects.get()
        resp = self.client.post(self.url("partners_mark_paid", payout.pk), {"reference": ""})
        self.assertEqual(resp.status_code, 302)
        payout.refresh_from_db()
        self.assertEqual(payout.status, "due")
        self.assertTrue(any("référence" in str(m) for m in get_messages(resp.wsgi_request)))
        self.client.post(self.url("partners_mark_paid", payout.pk), {"reference": "OM-77"})
        payout.refresh_from_db()
        self.assertEqual((payout.status, payout.orange_reference), ("paid", "OM-77"))
        self.client.post(self.url("partners_mark_paid", payout.pk), {"reference": "OM-88"})
        payout.refresh_from_db()
        self.assertEqual(payout.orange_reference, "OM-77")

    def test_release_refused_below_threshold(self):
        resp = self.client.post(self.url("partners_release", self.partner.pk))
        self.assertEqual(resp.status_code, 302)
        self.partner.refresh_from_db()
        self.assertEqual(self.partner.status, "active")
        self.assertTrue(any("seuil" in str(m) for m in get_messages(resp.wsgi_request)))

    def test_release_when_threshold_reached(self):
        Partner.objects.filter(pk=self.partner.pk).update(
            contract_start=add_months(timezone.localdate(), -10), contract_end=add_months(timezone.localdate(), 2)
        )
        self.client.post(self.url("partners_release", self.partner.pk))
        self.partner.refresh_from_db()
        self.assertEqual(self.partner.status, "slot_released")

    def test_csv_downloads(self):
        self.entry(self.referral(name="Boutique Fanta"), commission=2500)
        period = timezone.localtime(timezone.now()).strftime("%Y-%m")
        mine = self.client.get(self.url("partners_csv_partner", self.partner.pk), {"period": period})
        full = self.client.get(self.url("partners_csv_internal", self.partner.pk), {"period": period})
        for resp in (mine, full):
            self.assertEqual(resp.status_code, 200)
            self.assertIn("text/csv", resp["Content-Type"])
            self.assertIn("attachment", resp["Content-Disposition"])
        self.assertNotEqual(mine["Content-Disposition"], full["Content-Disposition"])
        self.assertNotIn("Fanta", mine.content.decode("utf-8"))
        self.assertIn("Fanta", full.content.decode("utf-8"))

    def test_csv_bad_period_is_a_clean_400(self):
        resp = self.client.get(self.url("partners_csv_partner", self.partner.pk), {"period": "xx"})
        self.assertEqual(resp.status_code, 400)


class DjangoAdminTests(Base):
    def setUp(self):
        super().setUp()
        self.superuser = User.objects.create_superuser(phone="+22379000009", password="x", display_name="Root")
        self.client.force_login(self.superuser)

    def test_models_are_registered_in_french(self):
        for model in (Partner, PartnerClick, Referral, CommissionEntry, Payout):
            self.assertIn(model, django_admin.site._registry, model)
        self.assertEqual(Partner._meta.verbose_name_plural, "Partenaires")

    def test_commission_and_payout_are_read_only(self):
        request = self.client.get("/admin/").wsgi_request
        request.user = self.superuser
        for model in (CommissionEntry, Payout):
            model_admin = django_admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(request), model)
            self.assertFalse(model_admin.has_change_permission(request), model)
            self.assertFalse(model_admin.has_delete_permission(request), model)

    def test_changelists_open(self):
        self.entry(self.referral())
        Payout.objects.create(partner=self.partner, period="2026-10", total_fcfa=2500)
        for model in ("partner", "partnerclick", "referral", "commissionentry", "payout"):
            with self.subTest(model=model):
                resp = self.client.get(f"/admin/partners/{model}/")
                self.assertEqual(resp.status_code, 200)


class HygieneTests(Base):
    def test_pages_have_no_inline_script_or_handlers_and_scroll_wrappers(self):
        self.entry(self.referral())
        for url in (self.url("partners_dashboard"), self.url("partners_list"), self.url("partners_detail", self.partner.pk)):
            html = self.client.get(url).content.decode()
            self.assertNotIn(" onclick=", html)
            self.assertNotIn("<script>", html.replace("<script src", ""))
            self.assertIn("hf-p-scroll", html)

    def test_platform_page_links_to_partners(self):
        self.assertContains(self.client.get(PLATFORM), self.url("partners_dashboard"))
