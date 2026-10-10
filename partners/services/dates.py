"""Calculs de dates du programme partenaires (mois calendaires, fin de mois bornée)."""

from __future__ import annotations

import calendar
from datetime import date, datetime


def add_months(value: date | datetime, months: int):
    """``value`` + ``months`` mois ; le jour est ramené à la fin du mois si besoin."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)
