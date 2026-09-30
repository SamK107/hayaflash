"""Points d'extension de django-axes (verrouillage du login).

- ``lockout_username`` : cle telephone unique pour toutes les routes de login.
  Le formulaire HTML et l'admin passent ``username=``, l'API DRF ``phone=`` ;
  sans normalisation commune, un attaquant alternerait les routes pour
  multiplier ses essais.
- ``lockout_response`` : reponse de verrouillage en francais (page HTML, ou JSON
  ``{"detail": [...]}`` pour l'API, lisible par le front Alpine).
"""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from accounts.services.users import normalize_phone


def lockout_username(request: HttpRequest, credentials: dict | None) -> str:
    raw = None
    if credentials:
        raw = credentials.get("phone") or credentials.get("username")
    if raw is None:
        data = getattr(request, "data", None) or getattr(request, "POST", {})
        raw = data.get("phone") or data.get("username")
    return normalize_phone(raw) if isinstance(raw, str) else ""


def lockout_response(
    request: HttpRequest, response: HttpResponse | None = None, credentials: dict | None = None
) -> HttpResponse:
    message = settings.AXES_LOCKOUT_MESSAGE
    wants_json = request.path.startswith("/api/") or "application/json" in request.headers.get(
        "Accept", ""
    )
    if wants_json:
        return JsonResponse({"detail": [message]}, status=429)
    return render(request, "accounts/lockout.html", {"message": message}, status=429)
