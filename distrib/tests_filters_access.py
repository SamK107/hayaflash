"""Filtres Stock/Relevés et accès sans saisir d'URL (lien Grossistes, PWA, redirection)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from distrib.tests_catalog import make_wholesale
from distrib.tests_models import make_distributor, make_seller

User = get_user_model()


@override_settings(DISTRIB_ENABLED=True)
class FilterBarTests(TestCase):
    def setUp(self):
        self.distributor = make_distributor()
        self.client.force_login(self.distributor.user)

    def test_stock_has_no_filter_bar_for_a_single_product(self):
        make_wholesale(self.distributor)
        resp = self.client.get("/distrib/stock/")
        self.assertNotContains(resp, "data-dx-filter")
        self.assertContains(resp, "data-dx-item")

    def test_stock_filter_lists_every_product(self):
        a = make_wholesale(self.distributor, name="Robe wax")
        b = make_wholesale(self.distributor, name="Pagne bazin")
        resp = self.client.get("/distrib/stock/")
        self.assertContains(resp, 'data-dx-filter="#dx-stock-list"')
        self.assertContains(resp, f'<option value="{a.pk}">Robe wax</option>', html=True)
        self.assertContains(resp, f'<option value="{b.pk}">Pagne bazin</option>', html=True)
        self.assertContains(resp, f'data-product="{b.pk}"')
        self.assertContains(resp, "distrib/filter.js")

    def test_statements_page_renders_with_status_choices(self):
        resp = self.client.get("/distrib/releves/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "distrib/filter.js")


@override_settings(DISTRIB_ENABLED=True)
class AccessWithoutTypingUrlTests(TestCase):
    def test_distributor_lands_on_distrib_home_after_plain_login(self):
        d = make_distributor()
        d.user.set_password("secret-123-xyz")
        d.user.save()
        resp = self.client.post("/login/", {"phone": "+22371000001", "password": "secret-123-xyz"})
        self.assertRedirects(resp, "/distrib/", fetch_redirect_response=False)

    def test_seller_still_lands_on_seller_home(self):
        s = make_seller()
        s.user.set_password("secret-123-xyz")
        s.user.save()
        resp = self.client.post("/login/", {"phone": "+22370000001", "password": "secret-123-xyz"})
        self.assertRedirects(resp, "/seller/", fetch_redirect_response=False)

    def test_login_page_links_to_distrib_space(self):
        self.assertContains(self.client.get("/login/"), "/distrib/connexion/")
        self.assertNotContains(self.client.get("/login/?next=/distrib/"), "Espace grossiste")

    def test_distrib_pages_use_the_distrib_manifest(self):
        d = make_distributor()
        self.client.force_login(d.user)
        self.assertContains(self.client.get("/distrib/"), "/static/manifest-distrib.json")
        self.client.logout()
        self.assertNotContains(self.client.get("/login/"), "manifest-distrib.json")

    def test_platform_admin_links_to_pilotage(self):
        staff = User.objects.create_user(phone="+22390000009", password="x", display_name="E", is_staff=True)
        self.client.force_login(staff)
        self.assertContains(self.client.get("/platform-admin/"), "/distrib/pilotage/")


class DistribOffTests(TestCase):
    def test_no_distrib_link_or_redirect_when_switched_off(self):
        staff = User.objects.create_user(phone="+22390000009", password="x", display_name="E", is_staff=True)
        self.client.force_login(staff)
        self.assertNotContains(self.client.get("/platform-admin/"), "/distrib/pilotage/")
        self.client.logout()
        self.assertNotContains(self.client.get("/login/"), "Espace grossiste")
