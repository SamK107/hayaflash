"""F-53 : les scripts shell doivent rester en LF quel que soit le poste.

Sans .gitattributes, `autocrlf` (Windows) extrait les .sh en CRLF et bash refuse
de les executer (« $'\r': command not found »). On interroge git lui-meme.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30, check=True
    ).stdout


class ShellScriptsAreLfTests(SimpleTestCase):
    def test_gitattributes_forces_lf_on_every_tracked_shell_script(self):
        scripts = [p for p in _git("ls-files", "*.sh").splitlines() if p]
        self.assertTrue(scripts, "aucun .sh suivi : test sans objet")
        for script in scripts:
            with self.subTest(script=script):
                out = _git("check-attr", "eol", "text", "--", script)
                self.assertIn("eol: lf", out)
                self.assertNotIn("text: unset", out)

    def test_no_shell_script_is_committed_with_crlf(self):
        # i/<eol> = fins de ligne dans l'INDEX (ce qui est commite)
        for line in _git("ls-files", "--eol", "*.sh").splitlines():
            with self.subTest(line=line):
                self.assertTrue(line.split()[0] in ("i/lf", "i/none"), line)
