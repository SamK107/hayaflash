from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.guide import SLIDES


class GuidePremiereVenteTests(TestCase):
    url = "/guide/premiere-vente/"

    def test_route_nommee(self):
        self.assertEqual(reverse("guide_premiere_vente"), self.url)

    def test_page_publique_24_etapes(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(SLIDES), 24)
        self.assertContains(resp, 'class="hg-slide', count=24)
        self.assertContains(resp, "Excellente opération")

    def test_bouton_fin_visiteur(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, "Commence gratuitement")
        self.assertContains(resp, reverse("register"))
        self.assertContains(resp, f"{reverse('login')}?next={reverse('flash_sales:create')}")
        self.assertNotContains(resp, "Lance ta prochaine vente flash")

    def test_bouton_fin_connectee(self):
        user = get_user_model().objects.create_user(
            phone="+22370009999", password="Test-guide-2026", display_name="Awa Style"
        )
        self.client.force_login(user)
        resp = self.client.get(self.url)
        self.assertContains(resp, "Lance ta prochaine vente flash")
        self.assertContains(resp, reverse("flash_sales:create"))
        self.assertNotContains(resp, "Commence gratuitement")

    def test_images_presentes(self):
        guide_dir = Path(settings.BASE_DIR) / "static" / "guide"
        for s in SLIDES:
            if s["img"]:
                self.assertTrue((guide_dir / s["img"]).is_file(), s["img"])

    def test_lien_depuis_accueil(self):
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, self.url)
