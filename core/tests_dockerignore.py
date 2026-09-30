"""F-25 : .dockerignore present et coherent.

Sans lui, `COPY . .` embarque tout le contexte de build : .git (historique
complet), .venv, bases SQLite locales, medias, et surtout `.env` (secrets) lors
d'un build local. Lecture texte du fichier ; la preuve fonctionnelle (contenu
reel du contexte) est dans le suivi de release.
"""

from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[1]
IGNORE = ROOT / ".dockerignore"

# Ce que l'image n'a jamais besoin d'embarquer (au minimum demande par F-25).
MUST_IGNORE = (
    ".git",
    ".venv",
    "__pycache__",
    "*.pyc",
    "node_modules",
    "docs/releases/reports/",
    ".env",
)
# Ce dont Dockerfile (COPY requirements.txt, COPY . .) et l'application ont besoin.
MUST_KEEP = (
    "manage.py",
    "requirements.txt",
    "config",
    "static",
    "templates",
    "core",
    "flash_sales",
    "subscriptions",
    "infra",
)


def _patterns() -> list[str]:
    assert IGNORE.exists(), ".dockerignore manquant a la racine du depot"
    lines = IGNORE.read_text(encoding="utf-8").replace("\r\n", "\n").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def _normalized(pattern: str) -> str:
    """`**/x` (tout niveau) et `x` (racine) comptent pour « x »."""
    pattern = pattern.lstrip("/")
    if pattern.startswith("**/"):
        pattern = pattern[3:]
    return pattern.rstrip("/")


class DockerignoreTests(SimpleTestCase):
    def test_required_exclusions_are_present(self):
        present = {_normalized(p) for p in _patterns()}
        for entry in MUST_IGNORE:
            with self.subTest(entry=entry):
                self.assertIn(_normalized(entry), present)

    def test_nothing_needed_by_the_build_is_excluded(self):
        excluded = {_normalized(p) for p in _patterns() if not p.startswith("!")}
        for needed in MUST_KEEP:
            with self.subTest(needed=needed):
                self.assertNotIn(needed, excluded)
                self.assertNotIn(needed + "/**", excluded)
                self.assertTrue((ROOT / needed).exists(), f"{needed} attendu dans le depot")

    def test_nested_python_caches_are_excluded_at_any_depth(self):
        """Sans `**/`, seul le cache a la racine serait ignore (piege dockerignore)."""
        patterns = _patterns()
        self.assertIn("**/__pycache__", patterns)
        self.assertIn("**/*.pyc", patterns)

    def test_env_files_are_excluded_but_the_documented_example_is_not_required(self):
        patterns = _patterns()
        self.assertIn(".env", patterns)
        self.assertIn(".env.*", patterns)  # .env.local, .env.production, etc.
