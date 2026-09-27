"""Fixtures pytest communes a toute la suite."""

from __future__ import annotations

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache():
    """Vide le cache (LocMem en test) avant chaque test.

    Les compteurs de limite de debit (core/services/rate_limit.py), les
    verrous OTP et les caches de pages vivent dans le cache : sans ce vidage,
    des tests qui postent sur /login/ ou /register/ depuis la meme IP de
    test (127.0.0.1) se genent selon l'ordre d'execution.
    """
    cache.clear()
    yield
