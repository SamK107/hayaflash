"""Vues du grossiste (`/distrib/`). FBV partout ; les regles metier vivent dans `services/`."""

from __future__ import annotations

from urllib.parse import quote

from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from .access import (
    distributor_required,
    feature_required,
    get_distributor_or_none,
)

HOME_URL = "/distrib/"


def safe_next(request) -> str | None:
    """`?next=` limite aux pages de ce module (pas de redirection ouverte)."""
    candidate = request.GET.get("next", "")
    if "\\" in candidate or not candidate.startswith("/distrib/"):
        return None
    if url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return None


@feature_required
def connexion(request):
    """Entree dediee `/distrib/connexion/` (spec §5.1).

    La connexion existante (`/login/?next=...`) ignore `next` pour un utilisateur DEJA
    connecte (il atterrit sur `/seller/`) : on court-circuite ce cas ici, sans toucher a
    `core`. Un compte sans boutique ni role n'est jamais renvoye vers une page qui plante.
    """
    target = safe_next(request) or HOME_URL
    if not request.user.is_authenticated:
        return redirect(f"/login/?next={quote(target, safe='/')}")
    if get_distributor_or_none(request.user) is not None or safe_next(request):
        return redirect(target)
    return render(request, "distrib/not_distributor.html", status=403)


@distributor_required
def home(request):
    return render(request, "distrib/home.html", {"distributor": request.distributor})

