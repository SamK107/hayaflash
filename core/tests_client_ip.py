"""F-26 : une seule extraction d'IP client, qui ne fait confiance qu'a l'en-tete
pose par le proxy de confiance (settings.TRUSTED_PROXY_NETWORKS)."""

from __future__ import annotations

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

FACTORY = RequestFactory()
DOCKER_PROXY = "172.18.0.5"  # Nginx du conteneur, vu par Gunicorn
TRUSTED = ["172.16.0.0/12"]


class SpoofingReproTests(SimpleTestCase):
    """Reproduction du contournement : REMOTE_ADDR = un client direct (aucun
    proxy de confiance), qui ecrit lui-meme X-Forwarded-For / X-Real-IP."""

    def _forged(self):
        return FACTORY.get(
            "/",
            REMOTE_ADDR="196.200.9.9",
            HTTP_X_FORWARDED_FOR="6.6.6.6",
            HTTP_X_REAL_IP="7.7.7.7",
        )

    def test_every_reader_ignores_forged_headers(self):
        from analytics.services.abuse import request_fingerprint
        from core.legal import acceptance_ip
        from core.services.client_ip import get_client_ip

        self.assertEqual(get_client_ip(self._forged()), "196.200.9.9")
        self.assertEqual(acceptance_ip(self._forged()), "196.200.9.9")
        honest = FACTORY.get("/", REMOTE_ADDR="196.200.9.9")
        self.assertEqual(
            request_fingerprint(self._forged()), request_fingerprint(honest)
        )


@override_settings(TRUSTED_PROXY_NETWORKS=TRUSTED)
class GetClientIpTests(SimpleTestCase):
    def ip(self, **meta):
        from core.services.client_ip import get_client_ip

        return get_client_ip(FACTORY.get("/", **meta))

    def test_trusted_proxy_header_is_used(self):
        self.assertEqual(
            self.ip(REMOTE_ADDR=DOCKER_PROXY, HTTP_X_REAL_IP="41.73.1.1"), "41.73.1.1"
        )

    def test_header_from_untrusted_peer_is_ignored(self):
        self.assertEqual(
            self.ip(REMOTE_ADDR="196.200.1.9", HTTP_X_REAL_IP="41.73.1.1"),
            "196.200.1.9",
        )

    def test_x_forwarded_for_is_never_trusted_even_from_the_proxy(self):
        self.assertEqual(
            self.ip(REMOTE_ADDR=DOCKER_PROXY, HTTP_X_FORWARDED_FOR="6.6.6.6, 41.73.1.1"),
            DOCKER_PROXY,
        )

    def test_trusted_proxy_without_header_falls_back_to_peer(self):
        self.assertEqual(self.ip(REMOTE_ADDR=DOCKER_PROXY), DOCKER_PROXY)

    def test_invalid_or_hostile_header_value_is_ignored(self):
        for bad in ("pas-une-ip", "41.73.1.1, 6.6.6.6", "x" * 100, ""):
            with self.subTest(bad=bad):
                self.assertEqual(
                    self.ip(REMOTE_ADDR=DOCKER_PROXY, HTTP_X_REAL_IP=bad), DOCKER_PROXY
                )

    def test_ipv6_supported_and_missing_peer_is_unknown(self):
        self.assertEqual(
            self.ip(REMOTE_ADDR=DOCKER_PROXY, HTTP_X_REAL_IP="2001:db8::1"), "2001:db8::1"
        )
        self.assertEqual(self.ip(REMOTE_ADDR=""), "unknown")

    @override_settings(TRUSTED_PROXY_NETWORKS=[])
    def test_no_configured_proxy_means_headers_are_never_trusted(self):
        self.assertEqual(
            self.ip(REMOTE_ADDR=DOCKER_PROXY, HTTP_X_REAL_IP="41.73.1.1"), DOCKER_PROXY
        )

    @override_settings(TRUSTED_PROXY_NETWORKS=["pas-un-reseau", "172.16.0.0/12"])
    def test_malformed_network_in_settings_is_skipped_not_fatal(self):
        self.assertEqual(
            self.ip(REMOTE_ADDR=DOCKER_PROXY, HTTP_X_REAL_IP="41.73.1.1"), "41.73.1.1"
        )


@override_settings(TRUSTED_PROXY_NETWORKS=TRUSTED)
class CallSitesUseTheSingleFunctionTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_audit_and_acceptance_use_the_trusted_header(self):
        from core.legal import acceptance_ip
        from core.models import AuditLog, audit

        request = FACTORY.get(
            "/", REMOTE_ADDR=DOCKER_PROXY, HTTP_X_REAL_IP="41.73.1.1",
            HTTP_X_FORWARDED_FOR="6.6.6.6",
        )
        request.user = type("Anon", (), {"is_authenticated": False})()
        audit("t.event", entity_type="X", entity_id=1, request=request)
        self.assertEqual(AuditLog.objects.get(action="t.event").ip_address, "41.73.1.1")
        self.assertEqual(acceptance_ip(request), "41.73.1.1")

    def test_audit_stores_none_when_no_usable_ip(self):
        from core.models import AuditLog, audit

        request = FACTORY.get("/", REMOTE_ADDR="")
        request.user = type("Anon", (), {"is_authenticated": False})()
        audit("t.noip", entity_type="X", entity_id=1, request=request)
        self.assertIsNone(AuditLog.objects.get(action="t.noip").ip_address)

    def test_order_rate_limit_cannot_be_bypassed_by_rotating_xff(self):
        from orders.services import client_order

        refused = 0
        for n in range(client_order.ORDER_SUBMIT_RATE_MAX_PER_WINDOW + 5):
            request = FACTORY.get(
                "/", REMOTE_ADDR="196.200.9.9", HTTP_X_FORWARDED_FOR=f"6.6.{n}.1"
            )
            try:
                client_order.enforce_public_order_rate_limit(request)
            except ValidationError:
                refused += 1
        self.assertGreaterEqual(refused, 5)

    def test_drf_throttle_identity_ignores_forged_xff(self):
        from rest_framework.request import Request

        from core.throttling import TrustedProxyAnonRateThrottle, TrustedProxyUserRateThrottle

        raw = FACTORY.get("/", REMOTE_ADDR="196.200.9.9", HTTP_X_FORWARDED_FOR="6.6.6.6")
        for cls in (TrustedProxyAnonRateThrottle, TrustedProxyUserRateThrottle):
            self.assertEqual(cls().get_ident(Request(raw)), "196.200.9.9")
        via_proxy = FACTORY.get("/", REMOTE_ADDR=DOCKER_PROXY, HTTP_X_REAL_IP="41.73.1.1")
        self.assertEqual(
            TrustedProxyAnonRateThrottle().get_ident(Request(via_proxy)), "41.73.1.1"
        )
