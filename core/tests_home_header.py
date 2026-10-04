"""Accueil connecte : le bouton « Mon dashboard » reste sur une ligne (mobile)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

User = get_user_model()


class HomeHeaderMobileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            phone="+22370000123", password="x", display_name="Aminata Traoré"
        )
        self.client.force_login(self.user)

    def test_dashboard_button_and_number_have_dedicated_classes(self):
        html = self.client.get("/").content.decode()
        self.assertIn("hf-nav-dash", html)
        self.assertIn("hf-nav-user", html)
        self.assertIn("Mon dashboard", html)

    def test_css_keeps_label_on_one_line_and_hides_number_on_small_screens(self):
        html = self.client.get("/").content.decode()
        css = html.split(".hf-nav-dash", 1)[1]
        self.assertIn("white-space: nowrap", css.split("}", 1)[0])
        self.assertIn("max-width: 399px", html)
        self.assertIn("text-overflow: ellipsis", html)

    def test_anonymous_has_no_dashboard_button(self):
        self.client.logout()
        html = self.client.get("/").content.decode()
        self.assertNotIn("hf-nav-dash", html.split("</style>")[-1])
