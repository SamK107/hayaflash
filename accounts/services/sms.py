from __future__ import annotations


from core.services.rate_limit import phone_fingerprint


def send_sms(phone: str, message: str) -> None:
    """Send SMS (mock: logs to stdout; replace with real provider in production).

    F-36 : le numero n'est jamais ecrit en clair (empreinte seulement).
    """
    print(f"[SMS MOCK] {phone_fingerprint(phone)}: {message}")
