"""F-109 : le jeton des liens privés (/partenaires/d/<jeton>/) ne doit apparaître dans aucun journal du dépôt.

Quatre endroits le voyaient : le journal d'accès Nginx du conteneur (URI et Referer, car les ressources de la page
envoient `Referer: https://…/partenaires/d/<jeton>/`), le journal d'accès Gunicorn (ligne de requête et Referer),
le journal `django.request` d'un 404 (« Not Found: /partenaires/d/<jeton>/ ») et le Nginx de l'hôte (hors dépôt :
voir infra/nginx/hestia_masque_jeton.conf). Les tests verrouillent le masquage côté dépôt ; le fonctionnement réel de
Nginx et de Gunicorn est vérifié dans des conteneurs (rapport de la branche).
"""

from __future__ import annotations

import io
import json
import logging
import os
import py_compile
import re
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase

from core.logging_mask import MASK, MaskPrivateTokensFilter, mask_private_tokens

ROOT = Path(settings.BASE_DIR)
TOKEN = "k3J9xQ2mVn8LpR5tYw7ZaB4cD6eFgH1iJ0uOs-_AbCdE"


class MaskFunctionTests(SimpleTestCase):
    def test_masks_the_token_in_every_form_it_appears(self):
        for raw in (
            f"/partenaires/d/{TOKEN}/",
            f"/partenaires/d/{TOKEN}/accepter/",
            f"/partenaires/d/{TOKEN}",
            f"/partenaires/d/{TOKEN}/?x=1",
            f'GET /partenaires/d/{TOKEN}/ HTTP/1.1',
            f"https://hayaflash.example/partenaires/d/{TOKEN}/accepter/",
            f"Not Found: /partenaires/d/{TOKEN}/",
        ):
            with self.subTest(raw=raw):
                masked = mask_private_tokens(raw)
                self.assertNotIn(TOKEN, masked)
                self.assertNotIn(TOKEN[:12], masked)
                self.assertIn(f"/partenaires/d/{MASK}", masked)

    def test_keeps_the_rest_of_the_line_readable(self):
        self.assertEqual(
            mask_private_tokens(f"GET /partenaires/d/{TOKEN}/accepter/ HTTP/1.1"),
            f"GET /partenaires/d/{MASK}/accepter/ HTTP/1.1",
        )
        self.assertEqual(
            mask_private_tokens(f"/partenaires/d/{TOKEN}/?x=1"), f"/partenaires/d/{MASK}/?x=1"
        )

    def test_masks_several_tokens_in_one_line(self):
        line = f'"GET /partenaires/d/{TOKEN}/ HTTP/1.1" 200 "https://x.example/partenaires/d/{TOKEN}A/"'
        self.assertNotIn("k3J9xQ2m", mask_private_tokens(line))

    def test_other_paths_and_values_are_untouched(self):
        for raw in ("/", "/partenaires/", "/r/AWA2026/", "/verifier/000012-abcdef123456/", "/platform-admin/partenaires/1/"):
            self.assertEqual(mask_private_tokens(raw), raw)
        self.assertEqual(mask_private_tokens(42), 42)
        self.assertIsNone(mask_private_tokens(None))

    def test_masking_is_idempotent(self):
        once = mask_private_tokens(f"/partenaires/d/{TOKEN}/")
        self.assertEqual(mask_private_tokens(once), once)


class LogFilterTests(SimpleTestCase):
    def record(self, msg, args):
        return logging.LogRecord("django.request", logging.WARNING, __file__, 1, msg, args, None)

    def test_masks_message_and_tuple_arguments(self):
        rec = self.record("%s: %s", ("Not Found", f"/partenaires/d/{TOKEN}/"))
        self.assertTrue(MaskPrivateTokensFilter().filter(rec))
        self.assertNotIn(TOKEN, rec.getMessage())
        self.assertIn(f"/partenaires/d/{MASK}/", rec.getMessage())

    def test_masks_mapping_arguments_and_a_token_in_the_message(self):
        rec = self.record("vu %(path)s", ({"path": f"/partenaires/d/{TOKEN}/"},))
        MaskPrivateTokensFilter().filter(rec)
        self.assertNotIn(TOKEN, rec.getMessage())
        rec = self.record(f"Not Found: /partenaires/d/{TOKEN}/", None)
        MaskPrivateTokensFilter().filter(rec)
        self.assertNotIn(TOKEN, rec.getMessage())

    def test_never_drops_a_record_and_never_raises(self):
        rec = self.record("%s", (object(),))
        self.assertTrue(MaskPrivateTokensFilter().filter(rec))
        self.assertTrue(MaskPrivateTokensFilter().filter(self.record("%d", (3,))))


class DjangoNotFoundLogTests(TestCase):
    def test_an_unknown_token_404_is_logged_without_the_token(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(MaskPrivateTokensFilter())
        logger = logging.getLogger("django.request")
        old_level, old_propagate, old_disabled = logger.level, logger.propagate, logger.disabled
        logger.disabled = False  # les réglages de test désactivent les journaux existants
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
        logger.propagate = False
        try:
            response = self.client.get(f"/partenaires/d/{TOKEN}/")
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old_level)
            logger.propagate = old_propagate
            logger.disabled = old_disabled
        self.assertEqual(response.status_code, 404)
        output = stream.getvalue()
        self.assertIn("Not Found", output)  # la ligne existe bien...
        self.assertNotIn(TOKEN, output)  # ...sans le jeton
        self.assertIn(f"/partenaires/d/{MASK}/", output)


class ProjectLoggingConfigTests(SimpleTestCase):
    def test_base_settings_attach_the_filter_to_the_console_handler(self):
        code = (
            "import json; from django.conf import settings as s; "
            "print(json.dumps({'filters': s.LOGGING.get('filters', {}), 'handler': s.LOGGING['handlers']['console'].get('filters', [])}))"
        )
        env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.base"}
        out = subprocess.run(
            [sys.executable, "-c", code], env=env, cwd=ROOT, capture_output=True, text=True, check=True, timeout=120
        ).stdout
        data = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(data["filters"]["mask_private_tokens"]["()"], "core.logging_mask.MaskPrivateTokensFilter")
        self.assertIn("mask_private_tokens", data["handler"])


class NginxContainerLogTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.conf = (ROOT / "infra" / "nginx" / "prod.conf").read_text(encoding="utf-8")

    def test_the_uri_and_the_referer_are_masked_by_a_map(self):
        self.assertRegex(self.conf, r"map\s+\$request_uri\s+\$hf_logged_uri\s*\{")
        self.assertRegex(self.conf, r"map\s+\$http_referer\s+\$hf_logged_referer\s*\{")
        self.assertIn("/partenaires/d/", self.conf)

    def test_the_log_format_never_logs_the_raw_request_line_uri_or_referer(self):
        match = re.search(r"log_format\s+hf_masked\s+(.*?);", self.conf, re.S)
        self.assertIsNotNone(match, "log_format hf_masked absent")
        fmt = match.group(1)
        self.assertIn("$hf_logged_uri", fmt)
        self.assertIn("$hf_logged_referer", fmt)
        for raw in ("$request ", "$request\"", "$request_uri", "$uri", "$http_referer", "$args", "$query_string"):
            self.assertNotIn(raw, fmt + " ", raw)

    def test_the_server_uses_the_masked_format_and_no_other_access_log(self):
        self.assertRegex(self.conf, r"access_log\s+/var/log/nginx/access\.log\s+hf_masked\s*;")
        for line in self.conf.splitlines():
            stripped = line.strip()
            if stripped.startswith("access_log"):
                self.assertTrue(
                    stripped.rstrip(";").endswith(("off", "hf_masked")), f"journal d'accès non masqué : {stripped}"
                )

    def test_token_urls_have_their_own_location_with_a_raised_error_log_level(self):
        # Le journal d'erreur de Nginx cite requête, URL amont et Referer en clair quand Django est injoignable.
        match = re.search(r"location\s+\^~\s+/partenaires/d/\s*\{(.*?)\n    \}", self.conf, re.S)
        self.assertIsNotNone(match, "location ^~ /partenaires/d/ absente")
        body = match.group(1)
        self.assertRegex(body, r"error_log\s+/var/log/nginx/error\.log\s+crit\s*;")
        self.assertIn("proxy_pass         http://$hf_upstream;", body)
        self.assertIn("limit_req zone=general", body)  # même limitation que « Tout le reste »

    def test_the_masking_map_does_not_touch_other_urls(self):
        # La valeur par défaut des maps reprend l'URI telle quelle.
        self.assertRegex(self.conf, r"default\s+\$request_uri\s*;")
        self.assertRegex(self.conf, r"default\s+\$http_referer\s*;")


class GunicornAccessLogTests(SimpleTestCase):
    def test_the_logger_class_masks_every_atom(self):
        path = ROOT / "config" / "gunicorn_logging.py"
        self.assertTrue(path.exists())
        py_compile.compile(str(path), doraise=True)
        source = path.read_text(encoding="utf-8")
        self.assertIn("mask_private_tokens", source)
        self.assertIn("class MaskedLogger", source)

    def test_gunicorn_is_started_with_the_masking_logger_everywhere(self):
        for name in ("Dockerfile", "docker-compose.production.yml"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("--logger-class config.gunicorn_logging.MaskedLogger", text, name)
        compose = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")
        self.assertIn("--access-logfile -", compose)  # le journal d'accès reste actif, mais masqué


class HostNginxSnippetTests(SimpleTestCase):
    def test_the_snippet_for_the_host_exists_and_masks_uri_and_referer(self):
        text = (ROOT / "infra" / "nginx" / "hestia_masque_jeton.conf").read_text(encoding="utf-8")
        self.assertIn("map $request_uri $hf_logged_uri", text)
        self.assertIn("map $http_referer $hf_logged_referer", text)
        self.assertIn("log_format hf_masked", text)
        self.assertIn("/partenaires/d/", text)
