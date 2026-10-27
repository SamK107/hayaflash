"""Numeros E.164 du module Distrib : indicatif choisi a la saisie, jamais devine (spec §2.9)."""

from __future__ import annotations

from core.countries import COUNTRIES, DEFAULT_COUNTRY, validate_international

CALLING_CODE_CHOICES = [(c.calling_code, f"{c.dial} {c.name}") for c in COUNTRIES]
DEFAULT_CALLING_CODE = DEFAULT_COUNTRY.calling_code


def build_e164(calling_code: str, national: str) -> tuple[str | None, str]:
    """`("+22370000001", "")` si valide, sinon `(None, message_en_francais)`.

    `calling_code` vient du selecteur (sans « + »), `national` est la saisie libre
    (espaces, points et tirets tolérés ; un « + » ou « 00 » dans la saisie est refuse :
    l'indicatif se choisit dans le selecteur).
    """
    code = (calling_code or "").strip().lstrip("+")
    if code not in {c.calling_code for c in COUNTRIES}:
        return None, "Choisissez l'indicatif du pays."
    raw = (national or "").strip()
    if not raw:
        return None, "Indiquez le numéro de téléphone."
    if raw.startswith(("+", "00")):
        return None, "Saisissez le numéro sans l'indicatif : il se choisit dans la liste."
    return validate_international(f"+{code}{raw}")


def display_phone(e164: str) -> str:
    """`+22370000001` -> `+223 70 00 00 01` (lecture seule, jamais stocke)."""
    digits = e164.lstrip("+")
    for country in COUNTRIES:
        if digits.startswith(country.calling_code):
            national = digits[len(country.calling_code):]
            pairs = [national[i:i + 2] for i in range(0, len(national), 2)]
            return f"{country.dial} {' '.join(pairs)}"
    return e164
