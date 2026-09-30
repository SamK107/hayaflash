"""Zones limit_req du Nginx conteneur (lecture texte de infra/nginx/prod.conf)."""

from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase

from core.tests_nginx_headers import _blocks

CONF = Path(__file__).resolve().parents[1] / "infra" / "nginx" / "prod.conf"


class NginxRateLimitZonesTests(SimpleTestCase):
    def setUp(self):
        self.text = CONF.read_text(encoding="utf-8").replace("\r\n", "\n")
        self.blocks = dict(_blocks(self.text))

    def test_auth_zone_is_10_per_minute_keyed_on_client_ip(self):
        self.assertRegex(
            self.text, r"limit_req_zone \$binary_remote_addr zone=auth:\w+ rate=10r/m;"
        )

    def test_login_register_and_api_auth_use_the_auth_zone_with_429(self):
        html = next(b for n, b in self.blocks.items() if n.startswith("~ ^/(login|register"))
        api = self.blocks["/api/v1/accounts/auth/"]
        for body in (html, api):
            self.assertRegex(body, r"limit_req zone=auth burst=5")
            self.assertIn("limit_req_status 429;", body)

    def test_static_and_media_have_no_rate_limit(self):
        for name in ("/static/", "/media/"):
            self.assertNotIn("limit_req", self.blocks[name])

    def test_api_locations_answer_429_in_json(self):
        self.assertRegex(self.text, r"location @rate_limited_json \{[^}]*application/json")
        for name in ("/api/v1/orders/", "/api/v1/accounts/auth/"):
            self.assertRegex(self.blocks[name], r"error_page 429 = @rate_limited_json;")

    def test_real_ip_is_read_from_forwarded_for_recursively(self):
        self.assertRegex(self.text, r"real_ip_header\s+X-Forwarded-For;")
        self.assertRegex(self.text, r"real_ip_recursive\s+on;")


class NginxOrdersZoneTests(SimpleTestCase):
    """Zone commandes alignee sur la limite Django (120/min/IP, CGNAT)."""

    def setUp(self):
        self.text = CONF.read_text(encoding="utf-8").replace("\r\n", "\n")

    def test_orders_zone_is_120_per_minute_burst_40(self):
        self.assertRegex(
            self.text, r"limit_req_zone \$binary_remote_addr zone=api_orders:\w+ rate=120r/m;"
        )
        body = dict(_blocks(self.text))["/api/v1/orders/"]
        self.assertIn("limit_req zone=api_orders burst=40 nodelay;", body)

    def test_django_ip_cap_matches_nginx(self):
        from orders.services import client_order

        self.assertEqual(client_order.ORDER_SUBMIT_RATE_MAX_PER_WINDOW, 120)
        self.assertEqual(client_order.ORDER_SUBMIT_RATE_WINDOW_SECONDS, 60)
