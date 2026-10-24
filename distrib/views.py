"""Vues du grossiste (`/distrib/`). FBV partout ; les regles metier vivent dans `services/`."""

from __future__ import annotations

from django.shortcuts import render

from .access import distributor_required


@distributor_required
def home(request):
    return render(request, "distrib/home.html", {"distributor": request.distributor})
