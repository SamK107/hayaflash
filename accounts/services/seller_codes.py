from __future__ import annotations

from django.utils.crypto import get_random_string


def generate_unique_seller_code(model_class, prefix: str = "SLR") -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    while True:
        candidate = f"{prefix}-{get_random_string(8, allowed_chars=alphabet)}"
        if not model_class.objects.filter(seller_code=candidate).exists():
            return candidate
