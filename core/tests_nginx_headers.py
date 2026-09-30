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


class NginxMediaAntiExecutionTests(SimpleTestCase):
    """F-04 : /media/ (contenu uploade) ne doit jamais etre rendu comme une page."""

    def setUp(self):
        self.text = CONF.read_text(encoding="utf-8").replace("\r\n", "\n")
        self.media = dict(_blocks(self.text))["/media/"]

    def test_media_forces_sandbox_csp(self):
        self.assertRegex(
            self.media,
            r"add_header\s+Content-Security-Policy\s+\"[^\"]*sandbox[^\"]*\"\s+always;",
        )

    def test_media_sets_content_disposition_from_map(self):
        self.assertRegex(
            self.media, r"add_header\s+Content-Disposition\s+\$hf_media_disposition\s+always;"
        )

    def test_map_serves_inline_only_expected_types_else_attachment(self):
        m = re.search(r"map\s+\$uri\s+\$hf_media_disposition\s*\{(.*?)\n\}", self.text, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertRegex(body, r"default\s+\"attachment\";")
        for ext in ("jpe?g", "png", "webp", "webm", "ogg", "mp3", "m4a", "wav"):
            self.assertIn(ext, body)
        for forbidden in ("html", "svg", "js", "php", "pdf"):
            self.assertNotRegex(body.split("inline")[0], forbidden)

    def test_media_headers_are_not_duplicated(self):
        # Nginx concatene (ne fusionne pas) les add_header d'un meme nom.
        names = re.findall(r"add_header\s+(\S+)", self.media)
        self.assertEqual(len(names), len(set(names)), names)
