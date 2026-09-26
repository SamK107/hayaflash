"""Content-Security-Policy HayaFlash (django-csp 3.8).

Importe par base.py (dev/staging/prod) et par test.py (qui ne charge pas
base.py) : une seule definition de la policy, testee par core/tests_csp.py.
Voir GOVERNANCE_SECURITE.md categorie 4.
"""

from __future__ import annotations

import os

__all__ = [
    "CSP_BASE_URI",
    "CSP_CONNECT_SRC",
    "CSP_DEFAULT_SRC",
    "CSP_FONT_SRC",
    "CSP_FRAME_ANCESTORS",
    "CSP_IMG_SRC",
    "CSP_MANIFEST_SRC",
    "CSP_MEDIA_SRC",
    "CSP_OBJECT_SRC",
    "CSP_REPORT_ONLY",
    "CSP_REPORT_URI",
    "CSP_SCRIPT_SRC",
    "CSP_STYLE_SRC",
    "CSP_WORKER_SRC",
]

# Étape 1 du durcissement post-vendoring (13/09) : tout le JS/CSS/police est
# maintenant self-hosted (static/vendor, static/fonts), donc une vraie CSP est
# possible — avant, 5 origines externes (unpkg/jsdelivr/cdn.tailwindcss.com/
# fonts.googleapis.com) l'auraient rendue inutilement permissive.
#
# Report-Only (CSP_REPORT_ONLY = True) : la policy est envoyée et les
# violations remontées (console navigateur + CSP_REPORT_URI si défini), mais
# rien n'est bloqué. Surcharge possible par env (CSP_REPORT_ONLY=false) pour
# tester le mode bloquant en local ; le passage en prod reste une décision à
# part (docs/RUNBOOK_JOUR_J.md, étape 6).
#
# Sprint gouvernance B (26/09) : plus aucun <script> inline ni attribut on*=
# dans les templates (déplacés vers static/js/*.js, garde-fou
# core/tests_csp.py) → 'unsafe-inline' retiré de script-src.
# 'unsafe-eval' reste exigé par Alpine.js standard (expressions évaluées via
# le constructeur AsyncFunction) ; migrer vers @alpinejs/csp imposerait de
# réécrire les 18 templates Alpine en Alpine.data() — écarté (GOVERNANCE
# catégorie 4).
CSP_REPORT_ONLY = os.environ.get("CSP_REPORT_ONLY", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CSP_DEFAULT_SRC = ["'self'"]
CSP_SCRIPT_SRC = ["'self'", "'unsafe-eval'"]
# 'unsafe-inline' conservé pour les styles (attributs style="" et <style> des
# templates, styles injectés par hf-install.js) : hors périmètre du sprint B.
CSP_STYLE_SRC = ["'self'", "'unsafe-inline'"]
CSP_IMG_SRC = ["'self'", "data:", "blob:"]
CSP_FONT_SRC = ["'self'"]
CSP_CONNECT_SRC = ["'self'"]
# blob: = lecture des messages vocaux enregistrés dans le navigateur
# (URL.createObjectURL, formulaires vendeur et commande acheteur).
CSP_MEDIA_SRC = ["'self'", "blob:"]
CSP_MANIFEST_SRC = ["'self'"]
CSP_WORKER_SRC = ["'self'"]
CSP_OBJECT_SRC = ["'none'"]
CSP_BASE_URI = ["'self'"]
CSP_FRAME_ANCESTORS = ["'none'"]
# Mesure : endpoint "security" de Sentry (Project Settings > Security Headers),
# ex. https://oXXX.ingest.sentry.io/api/NNN/security/?sentry_key=... — absent
# si vide. Pas de directive report-to : elle exige un en-tête
# Reporting-Endpoints que django-csp 3.8 n'émet pas.
_CSP_REPORT_URI = os.environ.get("CSP_REPORT_URI", "").strip()
CSP_REPORT_URI = [_CSP_REPORT_URI] if _CSP_REPORT_URI else None
