"""F-67 : aucun fichier vendorise ne doit referencer un sourcemap absent (collectstatic Manifest echoue)."""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

PATTERN = re.compile(r"sourceMappingURL=([^\s*]+)")


class VendorSourceMapTests(SimpleTestCase):
    def test_no_dangling_sourcemap_reference(self) -> None:
        root = Path(settings.BASE_DIR) / "static" / "vendor"
        offenders = []
        for path in root.rglob("*"):
            if path.suffix not in {".js", ".css"}:
                continue
            for ref in PATTERN.findall(path.read_text(encoding="utf-8", errors="ignore")):
                if not ref.startswith("data:") and not (path.parent / ref).exists():
                    offenders.append(f"{path.relative_to(root)} -> {ref}")
        self.assertEqual(offenders, [])
