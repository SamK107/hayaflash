"""PR 2 : vocabulaire francais de l'interface (F-85) et promesses d'annulation
de commande fausses (F-70)."""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

COD_WORD = re.compile(r"\bCOD\b")
DJANGO_COMMENT = re.compile(r"\{#.*?#\}", re.S)
DJANGO_BLOCK_COMMENT = re.compile(r"\{% comment %\}.*?\{% endcomment %\}", re.S)


def _ui_files():
    base = Path(settings.BASE_DIR)
    return list((base / "templates").rglob("*.html")) + list(
        (base / "static" / "js").rglob("*.js")
    )


class NoCodAcronymTests(SimpleTestCase):
    """F-85 : le sigle anglais « COD » ne doit apparaitre dans aucun libelle."""

    def test_cod_acronym_absent_from_templates_and_js(self):
        base = Path(settings.BASE_DIR)
        files = _ui_files()
        self.assertGreater(len(files), 20)
        offenders = []
        for path in files:
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".html":
                text = DJANGO_COMMENT.sub("", text)
                text = DJANGO_BLOCK_COMMENT.sub("", text)
            for n, line in enumerate(text.splitlines(), 1):
                if COD_WORD.search(line):
                    offenders.append(f"{path.relative_to(base)}: {line.strip()[:80]}")
        self.assertEqual(offenders, [], "Utiliser « Paiement à la livraison » / « À encaisser ».")

    def test_delivery_summary_uses_french_labels(self):
        base = Path(settings.BASE_DIR)
        html = (base / "templates/delivery/partials/delivery_summary.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("À encaisser", html)
        self.assertIn("Encaissé", html)


class NoFalseCancellationPromiseTests(SimpleTestCase):
    """F-70 : aucune action d'annulation de commande n'existe, on ne la promet pas."""

    def _read(self, rel):
        return (Path(settings.BASE_DIR) / rel).read_text(encoding="utf-8")

    def test_home_does_not_promise_cancel(self):
        html = self._read("templates/core/home.html")
        self.assertNotIn("annulez", html)
        self.assertIn("Vous confirmez en un tap.", html)

    def test_public_drawer_does_not_promise_cancel(self):
        html = self._read("templates/analytics/flash_sale_public.html")
        self.assertNotIn("Annulation possible", html)
        self.assertIn("Paiement à la livraison", html)


class AmountLabelsGuardTests(SimpleTestCase):
    """Libelles de montants : « Encaisse (FCFA) » / « En cours d'encaissement (FCFA) »."""

    OLD_LABELS = ("FCFA encaissé", "FCFA en cours")

    def test_old_amount_labels_are_gone(self) -> None:
        base = Path(settings.BASE_DIR)
        files = list((base / "templates").rglob("*.html")) + list(
            (base / "static" / "js").rglob("*.js")
        )
        offenders = [
            f"{p.relative_to(base)}: {label}"
            for p in files
            for label in self.OLD_LABELS
            if label.lower() in p.read_text(encoding="utf-8").lower()
        ]
        self.assertEqual(offenders, [])


class NoMultilineTemplateCommentTests(SimpleTestCase):
    """`{# ... #}` ne couvre qu'une ligne : sur plusieurs lignes, le commentaire
    s'affiche tel quel dans la page. Utiliser `{% comment %}` dans ce cas."""

    def test_no_multiline_brace_hash_comment(self) -> None:
        base = Path(settings.BASE_DIR)
        offenders = [
            str(p.relative_to(base))
            for p in (base / "templates").rglob("*.html")
            if re.search(r"\{#(?:(?!#\}).)*\n", p.read_text(encoding="utf-8"))
        ]
        self.assertEqual(offenders, [])
