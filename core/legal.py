"""Documents légaux (CGU, politique de confidentialité) : versions courantes.

Source unique des numéros de version : pages légales, inscription web et API
les lisent ici. Changer une version = nouveau texte à faire accepter aux
nouveaux inscrits (les acceptations passées restent liées à leur version).
"""

from __future__ import annotations

import datetime

LEGAL_CGU_VERSION = "2026-09"
LEGAL_PRIVACY_VERSION = "2026-09"

# Date affichée « Dernière mise à jour » sur les pages légales.
LEGAL_LAST_UPDATED = datetime.date(2026, 9, 27)
