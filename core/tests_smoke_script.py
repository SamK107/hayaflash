"""F-35 : infra/scripts/smoke_test.sh doit detecter une reponse non-2xx.

Ancien bug : `curl -sf ... || echo "000"` concatenait le code HTTP et « 000 »
(500 -> "500000", connexion refusee -> "000000"), jamais egal a "000" : toute
erreur serveur, voire une connexion impossible, passait pour un succes sur les
URL sans motif, et le rollback automatique de deploy.sh ne se declenchait
jamais. On execute le VRAI script contre un faux serveur HTTP local.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "infra" / "scripts" / "smoke_test.sh"
CRLF, LF = b"\r\n", b"\n"

BODIES = {
    "/health/": b'{"status":"ok","service":"HayaFlash","checks":{"database":"ok"}}',
    "/": b"<h1>HayaFlash</h1>",
    "/login/": b"Se connecter",
    "/ventes/": b"ok",
    "/api/v1/flash-sales/": b"[]",
    "/static/manifest.json": b'{"name": "HayaFlash"}',
}


def _server(overrides: dict[str, int], bodies: dict[str, bytes] | None = None):
    pages = bodies if bodies is not None else BODIES
    seen: list[dict[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen.append({k.lower(): v for k, v in self.headers.items()})
            code = overrides.get(self.path, 200)
            body = pages.get(self.path, b"") if code == 200 else b"err"
            self.send_response(code)
            if code in (301, 302):
                self.send_header("Location", "https://example.test/")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    httpd.seen_headers = seen
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _find_bash() -> str:
    """bash utilisable : evite le lanceur WSL de System32 (il ne joint pas le
    127.0.0.1 de Windows)."""
    found = shutil.which("bash")
    if found and "system32" not in found.lower():
        return found
    for candidate in (
        os.environ.get("HF_TEST_BASH", ""),
        "C:/Program Files/Git/bin/bash.exe",
        "C:/Program Files/Git/usr/bin/bash.exe",
    ):
        if candidate and Path(candidate).exists():
            return candidate
    raise AssertionError(
        "Aucun bash utilisable : definir HF_TEST_BASH (Git Bash) pour tester smoke_test.sh"
    )


def _run(base_url: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    # .gitattributes force les .sh en LF (F-53), mais une copie de travail
    # extraite AVANT ce fichier peut encore etre en CRLF (que bash refuse) : on
    # execute une copie normalisee en LF du MEME script. Il est passe sur stdin
    # (`bash -s`), donc sans chemin a traduire selon le bash trouve.
    source = SCRIPT.read_bytes().replace(CRLF, LF)
    result = subprocess.run(
        [_find_bash(), "-s", "--", base_url],
        input=source,
        capture_output=True,
        timeout=60,
        cwd=REPO_ROOT,
        env={**os.environ, **(env or {})},
    )
    result.stdout = result.stdout.decode("utf-8", "replace")
    result.stderr = result.stderr.decode("utf-8", "replace")
    return result


class SmokeScriptTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not shutil.which("curl"):
            raise AssertionError("curl est requis pour tester smoke_test.sh")

    def _against(self, overrides, bodies=None, env=None):
        httpd = _server(overrides, bodies)
        # addCleanup s'execute en ordre INVERSE : on enregistre server_close en
        # premier pour que shutdown() arrete la boucle serve_forever AVANT la
        # fermeture du socket (sinon WinError 10038 dans le thread du serveur).
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.httpd = httpd
        return _run(f"http://127.0.0.1:{httpd.server_address[1]}", env)

    def test_all_2xx_passes(self):
        r = self._against({})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("SMOKE TEST PASSED", r.stdout)

    def test_server_error_on_url_without_pattern_fails(self):
        """/ventes/ n'a pas de motif : c'etait le cas ou le 500 passait en OK."""
        r = self._against({"/ventes/": 500})
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("FAIL [Page ventes publiq.]", r.stdout)
        self.assertIn("HTTP 500", r.stdout)
        self.assertNotIn("SMOKE TEST PASSED", r.stdout)

    def test_client_error_redirect_and_5xx_are_failures(self):
        for code in (404, 403, 301, 302, 503):
            with self.subTest(code=code):
                r = self._against({"/api/v1/flash-sales/": code})
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn(f"HTTP {code}", r.stdout)

    def test_connection_refused_fails_on_every_url(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]  # port libre, personne n'y ecoute
        r = _run(f"http://127.0.0.1:{port}")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertNotIn("OK   [", r.stdout)  # ancien bug : « HTTP 000000 » compte OK
        # une ligne par URL testee, /health/ comprise (6)
        self.assertEqual(r.stdout.count("connexion impossible"), 6)

    def test_2xx_with_missing_pattern_still_fails(self):
        r = self._against({}, {**BODIES, "/": b"page vide"})
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("pattern", r.stdout)

    def test_proxy_headers_are_sent_like_the_host_nginx_would(self):
        r = self._against({}, env={"SMOKE_HOST": "hayaflash.example"})
        self.assertEqual(r.returncode, 0, r.stdout)
        for headers in self.httpd.seen_headers:
            self.assertEqual(headers["x-forwarded-proto"], "https")
            self.assertEqual(headers["host"], "hayaflash.example")

    def test_health_endpoint_is_checked(self):
        """F-52 : /health/ (DB + cache) fait partie du smoke test."""
        for code in (503, 500, 301, 404):
            with self.subTest(code=code):
                r = self._against({"/health/": code})
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn("FAIL [Health", r.stdout)
                self.assertIn(f"HTTP {code}", r.stdout)

    def test_health_200_but_not_ok_status_fails(self):
        r = self._against({}, {**BODIES, "/health/": b'{"status":"degraded"}'})
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("FAIL [Health", r.stdout)
        self.assertIn("pattern", r.stdout)
