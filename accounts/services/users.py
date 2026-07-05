from __future__ import annotations

from django.contrib.auth import get_user_model


def normalize_phone(phone: str) -> str:
    """
    Normalize phone for lookups and OTP cache keys.
    Delegates to UserManager.normalize_phone so DB and cache stay aligned.
    """
    if not isinstance(phone, str):
        raise TypeError("phone must be a str")
    User = get_user_model()
    return User.objects.normalize_phone(phone)


def get_user_by_phone(phone: str):
    """
    Return the user for this phone, or None.
    Normalizes before querying; never raises DoesNotExist.
    """
    normalized = normalize_phone(phone)
    if not normalized:
        return None
    User = get_user_model()
    return User.objects.filter(phone=normalized).first()
