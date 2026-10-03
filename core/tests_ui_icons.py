"""PR 3 : icones Lucide a la place des emojis, garde-fou emojis monetaires."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase

# Emojis de devise (dont devises etrangeres) : l'application est en FCFA.
MONETARY_EMOJIS = ("💵", "💰", "💸", "💴", "💶", "💷", "🪙")


class NoMonetaryEmojiTests(SimpleTestCase):
    def test_no_monetary_emoji_in_templates_or_js(self) -> None:
        base = Path(settings.BASE_DIR)
        files = list((base / "templates").rglob("*.html")) + [
            p for p in (base / "static" / "js").rglob("*.js")
        ]
        self.assertGreater(len(files), 20)
        offenders = []
        for path in files:
            text = path.read_text(encoding="utf-8")
            for emoji in MONETARY_EMOJIS:
                if emoji in text:
                    offenders.append(f"{path.relative_to(base)}: {emoji}")
        self.assertEqual(
            offenders,
            [],
            "Emoji monetaire interdit : utiliser une icone Lucide neutre "
            "(banknote, wallet, hand-coins).",
        )


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
