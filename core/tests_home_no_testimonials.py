"""F-115 : aucun témoignage non vérifiable sur les pages publiques.

La page d'accueil affichait trois témoignages (noms, étoiles, gains chiffrés « 2 heures par vente »,
« 3× plus vite ») dont l'origine n'est pas établie. Ils ne doivent pas revenir.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase

REMOVED_PHRASES = (
    "Fatoumata T.",
    "Modibo K.",
    "Aminata D.",
    "2 heures",
    "3×",
    "3x plus vite",
    "ne reviendront pas",
    "arrêté le cahier",
    "Preuve sociale",
    "★",
    "aggregateRating",
    "ratingValue",
)

STARS = re.compile(r"★{2,}|☆{2,}|(?:&#9733;|&#x2605;|&starf;){2,}|(?:⭐\s*){2,}")
QUOTED = re.compile(r"[\"«“][^\"»”]{25,}[\"»”]")
FIGURE = re.compile(r"\d+\s*(?:×|x\b|fois|heures?\b|h\b|%)|plus vite|gagn\w+", re.I)


def templates():
    root = Path(settings.BASE_DIR) / "templates"
    return sorted(root.rglob("*.html"))


def numbered_testimonial(text: str) -> bool:
    plain = re.sub(r"<[^>]*>|\{[{%#].*?[}%#]\}", " ", text, flags=re.S)  # balises et balises de gabarit
    plain = re.sub(r"\s+", " ", plain)
    return bool(STARS.search(text) and QUOTED.search(plain) and FIGURE.search(plain))


class HomeHasNoTestimonialsTests(TestCase):
    def test_home_answers_200_and_contains_none_of_the_removed_phrases(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        for phrase in REMOVED_PHRASES:
            self.assertNotIn(phrase, html, phrase)

    def test_home_shows_the_why_block(self):
        html = self.client.get("/").content.decode()
        self.assertIn("Pourquoi HayaFlash", html)
        self.assertIn("mis à jour en direct", html)
        self.assertNotIn("garanti", html.lower())


class PublicTemplatesHaveNoNumberedTestimonialsTests(SimpleTestCase):
    def test_detector_recognises_a_numbered_testimonial(self):
        sample = '<span>★★★★★</span><p>"Mes produits partent <strong>3× plus vite qu\'avant.</strong>"</p>'
        self.assertTrue(numbered_testimonial(sample))
        self.assertFalse(numbered_testimonial("<p>Note du produit : ★★★★★</p>"))
        self.assertFalse(numbered_testimonial('<p>"Un texte entre guillemets sans résultat chiffré ni etoile."</p>'))

    def test_no_template_combines_stars_quotes_and_a_figure(self):
        offenders = [
            str(p.relative_to(settings.BASE_DIR))
            for p in templates()
            if numbered_testimonial(p.read_text(encoding="utf-8"))
        ]
        self.assertEqual(offenders, [], "témoignage chiffré dans un template public")
