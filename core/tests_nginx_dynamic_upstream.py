"""F-83 : nginx doit resoudre `web` a chaque requete (sinon 502 apres recreation de web)."""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

CONF = Path(__file__).resolve().parents[1] / "infra" / "nginx" / "prod.conf"


class DynamicUpstreamTests(SimpleTestCase):
    def setUp(self):
        self.conf = CONF.read_text(encoding="utf-8")

    def test_docker_resolver_is_declared(self):
        self.assertRegex(self.conf, r"(?m)^resolver\s+127\.0\.0\.11\s+valid=10s")

    def test_no_static_upstream_block(self):
        self.assertNotRegex(self.conf, r"(?m)^upstream\s+django")

    def test_every_proxy_pass_goes_through_the_variable(self):
        targets = re.findall(r"(?m)^\s*proxy_pass\s+(\S+);", self.conf)
        self.assertGreaterEqual(len(targets), 5)
        self.assertEqual(set(targets), {"http://$hf_upstream"})

    def test_variable_points_to_the_web_service(self):
        self.assertRegex(self.conf, r'set\s+\$hf_upstream\s+"web:8000";')
