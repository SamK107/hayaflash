"""Garde-fous CSP (GOVERNANCE_SECURITE.md categorie 4, sprint gouvernance B).

script-src n'autorise plus 'unsafe-inline' : un <script> inline ou un attribut
on*= reintroduit dans un template serait bloque des le passage en mode
bloquant (CSP_REPORT_ONLY=False) -- silencieusement, juste une violation dans
la console. Ces tests cassent la CI avant.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import Client, TestCase, modify_settings, override_settings

# Attribut gestionnaire d'evenement inline : onclick=, onsubmit=, ondblclick=...
# (les directives Alpine x-on:/@click ne sont pas concernees).
INLINE_HANDLER_RE = re.compile(r"""\son[a-z]+\s*=\s*["']""", re.IGNORECASE)
SCRIPT_TAG_RE = re.compile(r"<script\b([^>]*)>", re.IGNORECASE)
# Blocs de donnees non executes par le navigateur, donc hors script-src.
DATA_SCRIPT_TYPES = ("application/json", "application/ld+json")


def _template_files() -> list[Path]:
    roots = [Path(d) for d in settings.TEMPLATES[0]["DIRS"]]
    roots += sorted(Path(settings.BASE_DIR).glob("*/templates"))
    files: set[Path] = set()
    for root in roots:
        files.update(root.rglob("*.html"))
    return sorted(files)


class InlineScriptGuardTests(TestCase):
    def test_templates_are_found(self) -> None:
        self.assertGreater(len(_template_files()), 20)

    def test_no_inline_event_handler_attributes(self) -> None:
        offenders = []
        for path in _template_files():
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if INLINE_HANDLER_RE.search(line):
                    offenders.append(f"{path}:{lineno}: {line.strip()[:120]}")
        self.assertEqual(
            offenders,
            [],
            "Attribut on*= interdit (CSP) : utiliser un attribut data-hf-* "
            "(static/js/hf-base.js) ou addEventListener dans static/js/.",
        )

    def test_no_inline_script_without_src(self) -> None:
        offenders = []
        for path in _template_files():
            text = path.read_text(encoding="utf-8")
            for m in SCRIPT_TAG_RE.finditer(text):
                attrs = m.group(1).lower()
                if "src=" in attrs or any(t in attrs for t in DATA_SCRIPT_TYPES):
                    continue
                lineno = text.count("\n", 0, m.start()) + 1
                offenders.append(f"{path}:{lineno}: {m.group(0)}")
        self.assertEqual(
            offenders,
            [],
            "<script> inline interdit (CSP) : deplacer le code dans static/js/*.js, "
            "passer les donnees serveur via |json_script ou data-*.",
        )


# config/settings/test.py redefinit MIDDLEWARE sans CSPMiddleware.
@modify_settings(MIDDLEWARE={"append": "csp.middleware.CSPMiddleware"})
class CspHeaderTests(TestCase):
    def _policy(self, resp) -> str:
        return resp.get("Content-Security-Policy-Report-Only") or resp.get(
            "Content-Security-Policy", ""
        )

    def test_script_src_has_no_unsafe_inline(self) -> None:
        resp = Client().get("/")
        script_src = next(
            d for d in self._policy(resp).split(";") if d.strip().startswith("script-src")
        )
        self.assertIn("'self'", script_src)
        self.assertIn("'unsafe-eval'", script_src)  # Alpine.js standard
        self.assertNotIn("'unsafe-inline'", script_src)

    def test_report_only_by_default(self) -> None:
        resp = Client().get("/")
        self.assertIn("Content-Security-Policy-Report-Only", resp)

    @override_settings(CSP_REPORT_URI=["https://example.invalid/csp"])
    def test_report_uri_emitted_when_configured(self) -> None:
        resp = Client().get("/")
        self.assertIn("report-uri https://example.invalid/csp", self._policy(resp))

    def test_no_report_uri_by_default(self) -> None:
        resp = Client().get("/")
        self.assertNotIn("report-uri", self._policy(resp))
