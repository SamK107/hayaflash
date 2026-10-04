"""PR 3 / PR 4 : icones Lucide a la place des emojis, garde-fou emojis decoratifs."""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase

# Emojis decoratifs : l'interface utilise des icones Lucide (voir
# docs/releases/reports/ui-pr4-proposition.md). Sont consideres comme emojis :
# les pictogrammes U+1F000-1FAFF, les symboles divers/dingbats U+2600-27BF, les
# symboles techniques U+23E9-23FA (dont le chronometre), U+2B00-2BFF et le
# selecteur de variante U+FE0F. Les fleches (U+2192, U+2190) et la ponctuation ne
# sont pas des emojis.
DECORATIVE_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⏩-⏺⬀-⯿️]"
)
# Exceptions ecrites : glyphes typographiques autorises partout
# (coche U+2713, croix U+2715, etoile U+2605)...
ALLOWED_GLYPHS = frozenset("✓✕★")
# ... et emojis des textes de partage WhatsApp / Web Share (lignes `text: '...'`
# des gabarits ; analytics/services/share_links.py est du Python, hors perimetre) :
# flamme U+1F525 et eclair U+26A1.
SHARE_TEXT_EMOJIS = frozenset("\U0001F525⚡")
# Pages legales : volontairement non touchees par la PR 4.
EXCLUDED_DIRS = (("templates", "core", "legal"),)


def _is_share_text_line(line: str) -> bool:
    return line.lstrip().startswith("text:")


class NoDecorativeEmojiTests(SimpleTestCase):
    def test_no_decorative_emoji_in_templates_or_js(self) -> None:
        base = Path(settings.BASE_DIR)
        files = [
            p
            for p in (
                list((base / "templates").rglob("*.html"))
                + list((base / "static" / "js").rglob("*.js"))
            )
            if not any(
                p.relative_to(base).parts[: len(ex)] == ex for ex in EXCLUDED_DIRS
            )
        ]
        self.assertGreater(len(files), 20)
        offenders = []
        for path in files:
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                for match in DECORATIVE_EMOJI_RE.finditer(line):
                    char = match.group()
                    if char in ALLOWED_GLYPHS:
                        continue
                    if char in SHARE_TEXT_EMOJIS and _is_share_text_line(line):
                        continue
                    offenders.append(
                        f"{path.relative_to(base)}:{lineno}: U+{ord(char):04X}"
                    )
        self.assertEqual(
            offenders,
            [],
            "Emoji decoratif interdit : utiliser une icone Lucide "
            "(.hf-icon-badge) ou un mot. Exceptions : voir ALLOWED_GLYPHS et "
            "SHARE_TEXT_EMOJIS.",
        )

    def test_guard_regex_catches_known_emojis(self) -> None:
        # main qui salue, mains jointes, chronometre, avertissement, billet
        for emoji in ("\U0001F44B", "\U0001F64F", "⏱", "⚠️", "\U0001F4B5"):
            self.assertTrue(DECORATIVE_EMOJI_RE.search(emoji), repr(emoji))
        for ok in ("→", "←", "é", "FCFA"):
            self.assertIsNone(DECORATIVE_EMOJI_RE.search(ok), repr(ok))


class HomeIconBadgesTests(TestCase):
    def test_home_uses_lucide_badges_not_emojis(self) -> None:
        html = Client().get("/").content.decode()
        self.assertGreaterEqual(html.count("hf-icon-badge--lg"), 25)
        for name in ("wallet", "banknote", "hand-coins", "bike", "hourglass"):
            self.assertIn(f'data-lucide="{name}"', html)
        for emoji in ("📓", "📱", "💬", "📦", "🚚", "📥", "🛵", "📊", "🔔", "⏳",
                      "🧠", "🤝", "📈", "💡", "📲", "🏍"):
            self.assertNotIn(emoji, html)

    def test_badge_icons_are_aria_hidden(self) -> None:
        import re

        html = Client().get("/").content.decode()
        icons = re.findall(r'class="hf-icon-badge[^"]*"[^>]*><i ([^>]*)>', html)
        self.assertGreaterEqual(len(icons), 25)
        for attrs in icons:
            self.assertIn('aria-hidden="true"', attrs)


class FcfaUnitTests(SimpleTestCase):
    """Chaque montant affiche porte l'unite « FCFA » (jamais « F » seul, jamais sans unite)."""

    # (gabarit, expression de montant) : l'expression doit etre suivie de FCFA.
    AMOUNTS = (
        ("accounts/profile.html", "stats.total_revenue"),
        ("flash_sales/analytics_dashboard.html", "p.total_revenue"),
        ("orders/partials/order_row.html", "item.price_snapshot"),
        ("delivery/partials/delivery_summary.html", "summary.total_cod_pending"),
        ("delivery/partials/delivery_summary.html", "summary.total_cod_collected"),
        ("core/platform_admin.html", "orange.month.total_collected"),
        ("core/platform_admin.html", "orange.month.commission"),
        ("core/platform_admin.html", "orange.all_time.total_collected"),
        ("core/platform_admin.html", "orange.all_time.commission"),
        ("core/platform_admin.html", "p.amount"),
    )

    def test_amounts_are_followed_by_fcfa(self) -> None:
        import re

        base = Path(settings.BASE_DIR) / "templates"
        for tpl, expr in self.AMOUNTS:
            text = (base / tpl).read_text(encoding="utf-8")
            m = re.search(r"\{\{\s*" + re.escape(expr) + r"[^}]*\}\}(.{0,80})", text, re.S)
            self.assertIsNotNone(m, f"{tpl}: {expr} introuvable")
            self.assertIn("FCFA", m.group(1), f"{tpl}: {expr} sans unite FCFA")

    def test_no_bare_f_unit(self) -> None:
        import re

        base = Path(settings.BASE_DIR) / "templates"
        offenders = []
        for tpl in {t for t, _ in self.AMOUNTS}:
            text = (base / tpl).read_text(encoding="utf-8")
            if re.search(r"\}\}\s*(<span[^>]*>)?\s+F\s*(</span>|\n)", text):
                offenders.append(tpl)
        self.assertEqual(offenders, [])

    def test_delivery_summary_renders_fcfa(self) -> None:
        from django.template.loader import render_to_string

        html = render_to_string(
            "delivery/partials/delivery_summary.html",
            {"summary": {"total_orders": 3, "total_cod_pending": 12500, "total_cod_collected": 4000}},
        )
        self.assertEqual(html.count("FCFA"), 2)
