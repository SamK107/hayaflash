"""F-56 : le HEALTHCHECK Docker doit reellement executer la vue /health/.

Bug : en production SECURE_SSL_REDIRECT repond 301 a /health/ tant que la
requete n'a pas X-Forwarded-Proto: https. `curl -f` (sans -L) ne traite pas un
301 comme une erreur : le conteneur etait declare sain sans que la vue (base +
cache) ne s'execute jamais. `curl -L` n'est pas une solution : la redirection
pointe vers https://localhost:8000/ alors que Gunicorn ne parle qu'en HTTP
(echec SSL, code 35 : le conteneur serait toujours « unhealthy »).

On execute la VRAIE commande de chaque healthcheck (Dockerfile et service `web`
de docker-compose.production.yml) contre l'application servie sous redirection
SSL, avec une dependance volontairement cassee.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from unittest import mock

from django.test import LiveServerTestCase, override_settings

from core.tests_smoke_script import _find_bash

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "Dockerfile": ROOT / "Dockerfile",
    "docker-compose.production.yml (web)": ROOT / "docker-compose.production.yml",
}


def _healthcheck_command(path: Path) -> str:
    """Commande `curl ... http://localhost:8000/health/` du healthcheck (pas les commentaires)."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = re.search(r"curl\s[^\n\"|#]*?http://localhost:8000/health/", text)
    assert match, f"commande curl /health/ introuvable dans {path.name}"
    return match.group(0)


@override_settings(
    SECURE_SSL_REDIRECT=True,
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"],
)
class DockerHealthcheckTests(LiveServerTestCase):
    host = "127.0.0.1"

    def _run(self, command: str) -> subprocess.CompletedProcess:
        port = self.live_server_url.rsplit(":", 1)[1]
        command = command.replace("localhost:8000", f"localhost:{port}")
        return subprocess.run(
            [_find_bash(), "-c", command + " --max-time 15"],
            capture_output=True, text=True, timeout=60,
        )

    def test_healthy_app_passes_the_healthcheck(self):
        for name, path in SOURCES.items():
            with self.subTest(source=name):
                r = self._run(_healthcheck_command(path))
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_broken_dependency_makes_the_healthcheck_fail(self):
        """La vue tourne vraiment : cache HS -> 503 -> conteneur « unhealthy »."""
        broken = mock.MagicMock()
        broken.set.side_effect = ConnectionError("redis down")
        with mock.patch("config.api_urls.cache", broken):
            for name, path in SOURCES.items():
                with self.subTest(source=name):
                    r = self._run(_healthcheck_command(path))
                    self.assertNotEqual(
                        r.returncode, 0,
                        f"{name} : healthcheck vert alors que le cache est HS "
                        "(la vue n'a jamais ete executee ?)",
                    )

    def test_healthcheck_does_not_rely_on_following_redirects(self):
        # -L echouerait toujours : la redirection vise https://localhost:8000 (HTTP nu).
        for name, path in SOURCES.items():
            with self.subTest(source=name):
                self.assertNotRegex(_healthcheck_command(path), r"\s-\w*L\b|--location")
