"""Interrupteur et controles d'acces du module Distrib (spec §7).

Ordre des controles, identique pour toutes les vues : interrupteur (404) puis
authentification (redirection vers la connexion) puis role (403).
"""

from __future__ import annotations

from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import Http404

from .models import Distributor

LOGIN_URL = "/distrib/connexion/"


def distrib_enabled() -> bool:
    return bool(getattr(settings, "DISTRIB_ENABLED", False))


def get_distributor_or_none(user) -> Distributor | None:
    """Grossiste ACTIF de l'utilisateur, ou None (jamais d'exception)."""
    if not getattr(user, "is_authenticated", False):
        return None
    try:
        distributor = user.distributor
    except Distributor.DoesNotExist:
        return None
    return distributor if distributor.is_active else None


def feature_required(view_func):
    """404 tant que `DISTRIB_ENABLED` est faux : le module n'existe pas."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not distrib_enabled():
            raise Http404("Distrib désactivé.")
        return view_func(request, *args, **kwargs)

    return _wrapped


def distributor_required(view_func):
    """Grossiste actif uniquement ; le grossiste est passe a la vue (`request.distributor`)."""

    @feature_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), LOGIN_URL)
        distributor = get_distributor_or_none(request.user)
        if distributor is None:
            raise PermissionDenied
        request.distributor = distributor
        return view_func(request, *args, **kwargs)

    return _wrapped


def staff_required(view_func):
    """Pilotage HayaFlash : `is_staff` uniquement."""

    @feature_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), LOGIN_URL)
        if not request.user.is_staff:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return _wrapped


def reseller_required(view_func):
    """Revendeur : utilisateur connecte avec une boutique (`SellerProfile`)."""

    @feature_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), LOGIN_URL)
        seller = getattr(request.user, "seller_profile", None)
        if seller is None:
            raise PermissionDenied
        request.seller = seller
        return view_func(request, *args, **kwargs)

    return _wrapped
