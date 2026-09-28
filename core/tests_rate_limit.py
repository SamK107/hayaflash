"""core/services/rate_limit.py : compteur, fenetre, fail-open, IP, cles."""

from __future__ import annotations

from unittest import mock

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase

from core.services import rate_limit


class HitTests(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_under_limit_returns_false(self) -> None:
        results = [rate_limit.hit("t:a", limit=3, window_seconds=60) for _ in range(3)]
        self.assertEqual(results, [False, False, False])

    def test_over_limit_returns_true(self) -> None:
        for _ in range(3):
            rate_limit.hit("t:b", limit=3, window_seconds=60)
        self.assertTrue(rate_limit.hit("t:b", limit=3, window_seconds=60))

    def test_keys_are_prefixed(self) -> None:
        rate_limit.hit("t:c", limit=3, window_seconds=60)
        self.assertEqual(cache.get("rl:t:c"), 1)

    def test_window_expiry_resets_counter(self) -> None:
        for _ in range(4):
            rate_limit.hit("t:d", limit=3, window_seconds=60)
        self.assertTrue(rate_limit.is_limited("t:d", limit=3))
        cache.delete("rl:t:d")  # equivalent de l'expiration de la fenetre
        self.assertFalse(rate_limit.hit("t:d", limit=3, window_seconds=60))

    def test_short_window_really_expires(self) -> None:
        with mock.patch("django.core.cache.backends.locmem.time.time") as fake_time:
            fake_time.return_value = 1_000_000.0
            for _ in range(4):
                rate_limit.hit("t:e", limit=3, window_seconds=1)
            fake_time.return_value = 1_000_002.0  # fenetre de 1 s depassee
            self.assertFalse(rate_limit.hit("t:e", limit=3, window_seconds=1))

    def test_cache_failure_fails_open(self) -> None:
        with mock.patch.object(rate_limit, "cache") as broken:
            broken.add.side_effect = ConnectionError("redis down")
            broken.get.side_effect = ConnectionError("redis down")
            broken.delete.side_effect = ConnectionError("redis down")
            with self.assertLogs("core.services.rate_limit", level="WARNING"):
                self.assertFalse(rate_limit.hit("t:f", limit=0, window_seconds=60))
            self.assertFalse(rate_limit.is_limited("t:f", limit=0))
            rate_limit.reset("t:f")  # ne leve pas

    def test_reset_clears_counter(self) -> None:
        for _ in range(5):
            rate_limit.hit("t:g", limit=3, window_seconds=60)
        rate_limit.reset("t:g")
        self.assertFalse(rate_limit.is_limited("t:g", limit=3))


class KeyAndIpTests(SimpleTestCase):
    def test_phone_is_hashed_in_key(self) -> None:
        key = rate_limit.phone_key("login", "+22370000000")
        self.assertTrue(key.startswith("login:phone:"))
        self.assertNotIn("70000000", key)
        self.assertEqual(key, rate_limit.phone_key("login", "+22370000000"))

    def test_client_ip_prefers_x_real_ip_over_spoofable_xff(self) -> None:
        request = RequestFactory().get(
            "/",
            HTTP_X_REAL_IP="41.73.1.1",
            HTTP_X_FORWARDED_FOR="6.6.6.6, 41.73.1.1",
            REMOTE_ADDR="172.18.0.5",
        )
        self.assertEqual(rate_limit.client_ip(request), "41.73.1.1")

    def test_client_ip_falls_back_to_xff_then_remote_addr(self) -> None:
        factory = RequestFactory()
        self.assertEqual(
            rate_limit.client_ip(factory.get("/", HTTP_X_FORWARDED_FOR="41.73.1.2, 10.0.0.1")),
            "41.73.1.2",
        )
        self.assertEqual(rate_limit.client_ip(factory.get("/", REMOTE_ADDR="196.200.1.9")), "196.200.1.9")

    def test_client_ip_is_truncated(self) -> None:
        request = RequestFactory().get("/", HTTP_X_REAL_IP="x" * 100)
        self.assertEqual(len(rate_limit.client_ip(request)), 45)
