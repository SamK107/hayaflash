from __future__ import annotations

import logging
import secrets
import string

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache

from accounts.services.users import get_user_by_phone, normalize_phone

logger = logging.getLogger(__name__)

OTP_TIMEOUT_SECONDS = 300
OTP_LENGTH = 6
OTP_MAX_VERIFY_ATTEMPTS = 5
OTP_LOCKOUT_SECONDS = 300


def _normalize_phone(phone: str) -> str:
    """Single entry for OTP flows: cache key, SMS destination, and DB alignment."""
    if not isinstance(phone, str):
        return ""
    return normalize_phone(phone)


def _cache_key(phone: str) -> str:
    return f"otp:{_normalize_phone(phone)}"


def _otp_attempts_key(normalized_phone: str) -> str:
    return f"otp_attempts:{normalized_phone}"


def _otp_attempt_count(normalized_phone: str) -> int:
    raw = cache.get(_otp_attempts_key(normalized_phone))
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _is_otp_verify_locked(normalized_phone: str) -> bool:
    return _otp_attempt_count(normalized_phone) >= OTP_MAX_VERIFY_ATTEMPTS


def _record_failed_otp_verify(normalized_phone: str) -> int:
    key = _otp_attempts_key(normalized_phone)
    n = _otp_attempt_count(normalized_phone) + 1
    cache.set(key, n, OTP_LOCKOUT_SECONDS)
    if n >= OTP_MAX_VERIFY_ATTEMPTS:
        if settings.DEBUG:
            logger.warning(
                "OTP verify locked after max attempts (tail=%s).",
                normalized_phone[-4:] if len(normalized_phone) >= 4 else "****",
            )
        else:
            logger.warning(
                "OTP verify locked after max attempts (environment=%s).",
                getattr(settings, "ENVIRONMENT", "unknown"),
            )
    return n


def _clear_otp_verify_attempts(normalized_phone: str) -> None:
    cache.delete(_otp_attempts_key(normalized_phone))


def generate_otp_code(length: int = OTP_LENGTH) -> str:
    if length != OTP_LENGTH:
        raise ValueError(f"OTP length must be {OTP_LENGTH} for this flow.")
    digits = string.digits
    return "".join(secrets.choice(digits) for _ in range(length))


def hash_otp(code: str) -> str:
    return make_password(code)


def verify_otp(code: str, hashed: str) -> bool:
    return check_password(code, hashed)


def send_otp(phone: str) -> None:
    """
    Issue a single active OTP for this phone (cache overwrites any previous).
    Stores only the hashed code; plain code is sent via SMS only.
    """
    normalized_phone = _normalize_phone(phone)
    if not normalized_phone:
        return

    _clear_otp_verify_attempts(normalized_phone)

    code = generate_otp_code()
    hashed = hash_otp(code)
    cache.set(_cache_key(normalized_phone), hashed, timeout=OTP_TIMEOUT_SECONDS)

    from accounts.services.sms import send_sms

    send_sms(normalized_phone, f"Your verification code is: {code}")


def verify_phone_otp(phone: str, code: str) -> bool:
    """
    Validate the OTP for ``phone``; on success marks the user's phone verified
    and clears the cache entry. Returns False if missing, invalid, or user not found.
    """
    normalized_phone = _normalize_phone(phone)
    if not normalized_phone:
        return False

    if _is_otp_verify_locked(normalized_phone):
        if settings.DEBUG:
            logger.info(
                "OTP verify rejected: locked (tail=%s).",
                normalized_phone[-4:] if len(normalized_phone) >= 4 else "****",
            )
        else:
            logger.warning("OTP verify rejected: locked.")
        return False

    if (
        not isinstance(code, str)
        or len(code) != OTP_LENGTH
        or not code.isdigit()
    ):
        return False

    key = _cache_key(normalized_phone)
    stored_hash = cache.get(key)
    if stored_hash is None:
        _record_failed_otp_verify(normalized_phone)
        return False
    if not isinstance(stored_hash, str):
        _record_failed_otp_verify(normalized_phone)
        return False

    if not verify_otp(code, stored_hash):
        _record_failed_otp_verify(normalized_phone)
        return False

    cache.delete(key)
    _clear_otp_verify_attempts(normalized_phone)

    user = get_user_by_phone(normalized_phone)
    if user is None:
        return False

    if not user.is_phone_verified:
        user.is_phone_verified = True
        user.save(update_fields=["is_phone_verified", "updated_at"])
    return True
