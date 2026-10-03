"""Pays pris en charge : source unique (nom, indicatif, longueur nationale).

Ajouter un pays = ajouter une entree a ``COUNTRIES``, sans autre changement de code :
le selecteur d'indicatif des tiroirs « M'alerter » et la validation serveur des
numeros en sont derives. On ne devine JAMAIS un pays a partir d'un numero nu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Country:
    name: str
    calling_code: str  # sans « + » (ex. "223")
    national_length: int  # chiffres attendus apres l'indicatif

    @property
    def dial(self) -> str:
        return f"+{self.calling_code}"


COUNTRIES: tuple[Country, ...] = (
    Country("Mali", "223", 8),
    Country("Sénégal", "221", 9),
    Country("Côte d'Ivoire", "225", 10),
    Country("Burkina Faso", "226", 8),
    Country("Niger", "227", 8),
    Country("Guinée", "224", 9),
    Country("Togo", "228", 8),
    Country("Bénin", "229", 10),
    Country("Mauritanie", "222", 8),
)

DEFAULT_COUNTRY = COUNTRIES[0]

_SEPARATORS_RE = re.compile(r"[\s().\-]")


def country_for_digits(digits: str) -> Country | None:
    """Pays dont l'indicatif prefixe ces chiffres (indicatif le plus long d'abord)."""
    for country in sorted(COUNTRIES, key=lambda c: -len(c.calling_code)):
        if digits.startswith(country.calling_code):
            return country
    return None


def validate_international(raw: str) -> tuple[str | None, str]:
    """Valide un numero au format international (+… ou 00…).

    Retourne ``("+22370000001", "")`` si valide, sinon ``(None, message_en_francais)``.
    """
    cleaned = _SEPARATORS_RE.sub("", raw.strip()) if isinstance(raw, str) else ""
    if cleaned.startswith("+"):
        digits = cleaned[1:]
    elif cleaned.startswith("00"):
        digits = cleaned[2:]
    else:
        return None, "Indiquez le numéro avec l'indicatif du pays (ex. +223 70 00 00 00)."
    if not digits.isdigit():
        return None, "Numéro de téléphone invalide."
    country = country_for_digits(digits)
    if country is None:
        return None, "Indicatif de pays non pris en charge."
    national = digits[len(country.calling_code):]
    if len(national) != country.national_length:
        return None, (
            f"Numéro invalide pour {country.name} : "
            f"{country.national_length} chiffres attendus après {country.dial}."
        )
    return f"+{digits}", ""
