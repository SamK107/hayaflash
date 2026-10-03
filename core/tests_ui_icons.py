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
