"""F-22 : en Nginx, un `add_header` dans un bloc `location` desactive l'heritage
de TOUS les `add_header` du bloc `server`. Les locations /static/ et /media/
(qui posent Cache-Control) doivent donc repeter les en-tetes de securite.
Lecture texte de infra/nginx/prod.conf (test de non-regression) ; la preuve
fonctionnelle (curl sur un conteneur) est dans le suivi de release.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

CONF = Path(__file__).resolve().parents[1] / "infra" / "nginx" / "prod.conf"
SECURITY_HEADERS = (
    "Strict-Transport-Security",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
)


def _blocks(text: str):
    """Yield (nom, corps) de chaque `location ... {` (pas d'accolades imbriquees)."""
    for m in re.finditer(r"location\s+([^{]+?)\s*\{(.*?)\n    \}", text, re.S):
        yield m.group(1).strip(), m.group(2)


class NginxSecurityHeadersTests(SimpleTestCase):
    def setUp(self):
        self.text = CONF.read_text(encoding="utf-8").replace("\r\n", "\n")

    def test_server_block_defines_the_security_headers(self):
        for header in SECURITY_HEADERS:
            self.assertRegex(self.text, rf"add_header\s+{header}\s.*always;")

    def test_every_location_with_its_own_add_header_repeats_them(self):
        blocks = dict(_blocks(self.text))
        self.assertIn("/static/", blocks)
        self.assertIn("/media/", blocks)
        checked = 0
        for name, body in blocks.items():
            if "add_header" not in body:
                continue  # herite du bloc server : rien a repeter
            checked += 1
            for header in SECURITY_HEADERS:
                with self.subTest(location=name, header=header):
                    self.assertRegex(
                        body,
                        rf"add_header\s+{header}\s.*always;",
                        f"location {name} : {header} perdu (heritage add_header)",
                    )
        self.assertGreaterEqual(checked, 2)
