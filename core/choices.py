"""Listes de choix partagees entre apps (evite les imports croises)."""

from __future__ import annotations

from django.db import models


class SaleCategory(models.TextChoices):
    """Type de produits d'une vente / d'une boutique (liste fermee : filtrable).

    Affiche sur le calendrier public /ventes/ ; sert plus tard au filtrage du
    dashboard "Decouvrir". Une vente sans categorie herite de celle de la
    boutique (FlashSale.effective_category).
    """

    MODE = "mode", "Mode"
    CHAUSSURES = "chaussures", "Chaussures"
    BEAUTE = "beaute", "Beauté"
    ELECTRONIQUE = "electronique", "Électronique"
    ALIMENTATION = "alimentation", "Alimentation"
    MAISON = "maison", "Maison"
    AUTRE = "autre", "Autre"
