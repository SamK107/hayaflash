"""Contrôle en LECTURE SEULE des stocks négatifs (produits et variantes).

Préalable à la migration ``products.0011_stock_non_negatif`` (contrainte CHECK
``stock >= 0``) : la migration échoue si une ligne a déjà un stock négatif. Cette
commande liste ces lignes sans rien modifier, sur la base désignée par
``--database`` et le réglage ``--settings``.

Sortie : code 0 si aucune ligne n'est négative, erreur (code 1) sinon.
Aucune écriture, aucune transaction ouverte, aucune donnée personnelle affichée
(identifiants, nom du produit et stock seulement).

Exemple : python manage.py controle_stock_negatif --settings=config.settings.prod
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from products.models import Product, ProductVariant


def negative_products(using: str = "default") -> list[tuple[int, int, str, int]]:
    """(pk, owner_id, nom, stock_available) des produits au stock négatif."""
    return list(
        Product.objects.using(using)
        .filter(stock_available__lt=0)
        .order_by("pk")
        .values_list("pk", "owner_id", "name", "stock_available")
    )


def negative_variants(using: str = "default") -> list[tuple[int, int, int]]:
    """(pk, product_id, stock) des variantes au stock négatif."""
    return list(
        ProductVariant.objects.using(using)
        .filter(stock__lt=0)
        .order_by("pk")
        .values_list("pk", "product_id", "stock")
    )


class Command(BaseCommand):
    help = (
        "Liste les produits et variantes à stock négatif (lecture seule). "
        "Code d'erreur si la migration products.0011 serait bloquée."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            default="default",
            help="Alias de base de données à contrôler (défaut : default).",
        )

    def handle(self, *args, **options):
        using = options["database"]
        if using not in connections:
            raise CommandError(f"Alias de base inconnu : {using!r}.")

        products = negative_products(using)
        variants = negative_variants(using)
        self.stdout.write(f"Base contrôlée : {using} ({connections[using].vendor})")
        self.stdout.write(f"Produits à stock négatif : {len(products)}")
        for pk, owner_id, name, stock in products:
            self.stdout.write(f"  produit #{pk} · boutique #{owner_id} · {name!r} · stock {stock}")
        self.stdout.write(f"Variantes à stock négatif : {len(variants)}")
        for pk, product_id, stock in variants:
            self.stdout.write(f"  variante #{pk} · produit #{product_id} · stock {stock}")

        if products or variants:
            raise CommandError(
                "Stock négatif détecté : la migration products.0011 échouerait. "
                "Corriger les lignes listées à la main (validation du fondateur), "
                "puis relancer ce contrôle."
            )
        self.stdout.write("Aucun stock négatif : la migration products.0011 peut être appliquée.")
