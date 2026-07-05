from __future__ import annotations


def send_sms(phone: str, message: str) -> None:
    """Send SMS (mock: logs to stdout; replace with real provider in production)."""
    print(f"[SMS MOCK] {phone}: {message}")
