"""F-127 : sur /seller/, le bouton « Créer une vente flash » ne recouvre plus la ligne d'état sous 400 px.

Cause (mesurée dans un navigateur avec le CSS réel, avant correctif) : l'en-tête est une rangée flex sans retour à
la ligne ; le bouton (234 px, `shrink-0`) ne rétrécit pas et la colonne de texte (`min-w-0`) est écrasée à 30 px à
375 px de large. Les mots de « Rien à traiter pour le moment » débordent alors sous le bouton (recouvrement de
64 px à 320 px, 44 à 340, 24 à 360, 8 à 375 ; aucun à partir de 390 px). Correctif : `flex-wrap`, le bouton passe
sous le texte quand la place manque. Seules des classes déjà présentes dans le build Tailwind statique sont utilisées.

Un test unitaire ne mesure pas la mise en page : il verrouille la cause (la classe) et l'existence de la règle CSS.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.urls import reverse

from core.tests_seller_home import SellerHomeBase

CSS = Path(settings.BASE_DIR) / "static" / "vendor" / "tailwind" / "tailwind-hayaflash.css"


class SellerHomeHeaderLayoutTests(SellerHomeBase):
    def header_classes(self) -> list[str]:
        html = self.client.get(reverse("seller_home")).content.decode()
        # La rangée qui contient le bouton « Créer une vente flash » (lien vers flash_sales:create).
        match = re.search(r'<div class="([^"]*)">\s*<div class="flex items-center gap-4 min-w-0">', html)
        self.assertIsNotNone(match, "en-tête de l'accueil vendeur introuvable")
        return match.group(1).split()

    def test_the_header_row_wraps_so_the_button_never_covers_the_status_line(self):
        classes = self.header_classes()
        self.assertIn("flex", classes)
        self.assertIn("flex-wrap", classes)

    def test_the_text_column_can_still_shrink_and_the_button_keeps_its_size(self):
        html = self.client.get(reverse("seller_home")).content.decode()
        self.assertIn('class="flex items-center gap-4 min-w-0"', html)
        button = re.search(r'<a href="[^"]*"\s+class="([^"]*)">\s*<i data-lucide="plus"', html)
        self.assertIsNotNone(button)
        self.assertIn("shrink-0", button.group(1).split())

    def test_every_class_of_the_header_exists_in_the_static_tailwind_build(self):
        css = CSS.read_text(encoding="utf-8")
        for name in ("flex-wrap", "min-w-0", "shrink-0", "justify-between", "items-center", "gap-4"):
            self.assertRegex(css, rf"\.{re.escape(name)}\s*[{{,]", name)

    def test_the_button_label_is_unchanged(self):
        html = self.client.get(reverse("seller_home")).content.decode()
        self.assertIn("Créer une vente flash", html)
