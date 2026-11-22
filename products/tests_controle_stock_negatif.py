"""Commande controle_stock_negatif : lecture seule, détection, code de sortie.

Les lignes négatives ne peuvent pas être créées normalement (contrainte CHECK, migration
products.0011). Pour tester la détection, on désactive la vérification des CHECK le
temps d'une écriture : fonctionnalité propre à SQLite (tests en SQLite uniquement).
"""

from __future__ import annotations

from decimal import Decimal
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from accounts.models import SellerProfile
from products.management.commands.controle_stock_negatif import (
    negative_products,
    negative_variants,
)
from products.models import Product, ProductVariant

User = get_user_model()
sqlite_only = pytest.mark.skipif(
    connection.vendor != "sqlite", reason="Désactivation des CHECK : SQLite uniquement"
)


@pytest.fixture
def produit(db):
    user = User.objects.create_user(
        phone="+22370020001", password="x", display_name="Vendeuse contrôle"
    )
    seller = SellerProfile.objects.create(user=user)
    return Product.objects.create(
        owner=seller,
        name="Robe",
        price=Decimal("12000"),
        stock_initial=4,
        stock_available=4,
    )


def _force_negative(sql_update, **kwargs):
    """Écrit une valeur négative en ignorant temporairement les CHECK (SQLite)."""
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA ignore_check_constraints = ON")
        try:
            sql_update(**kwargs)
        finally:
            cursor.execute("PRAGMA ignore_check_constraints = OFF")


def _run(**options):
    out = StringIO()
    err = StringIO()
    try:
        call_command("controle_stock_negatif", stdout=out, stderr=err, **options)
        return 0, out.getvalue()
    except CommandError as exc:
        return 1, out.getvalue() + str(exc)


@pytest.mark.django_db
def test_base_saine_sort_en_succes_sans_rien_modifier(produit):
    variante = ProductVariant.objects.create(product=produit, type="taille", value="M", stock=2)
    avant = (
        Product.objects.get(pk=produit.pk).stock_available,
        ProductVariant.objects.get(pk=variante.pk).stock,
    )

    code, sortie = _run()

    assert code == 0
    assert "Aucun stock négatif" in sortie
    assert negative_products() == []
    assert negative_variants() == []
    apres = (
        Product.objects.get(pk=produit.pk).stock_available,
        ProductVariant.objects.get(pk=variante.pk).stock,
    )
    assert apres == avant


@sqlite_only
@pytest.mark.django_db
def test_produit_negatif_est_detecte_et_fait_echouer(produit):
    _force_negative(Product.objects.filter(pk=produit.pk).update, stock_available=-3)

    code, sortie = _run()

    assert code == 1
    assert f"produit #{produit.pk}" in sortie
    assert "stock -3" in sortie
    assert "0011" in sortie
    # Lecture seule : la valeur négative est toujours là, rien n'a été corrigé.
    assert Product.objects.get(pk=produit.pk).stock_available == -3


@sqlite_only
@pytest.mark.django_db
def test_variante_negative_est_detectee(produit):
    variante = ProductVariant.objects.create(product=produit, type="taille", value="L", stock=1)
    _force_negative(ProductVariant.objects.filter(pk=variante.pk).update, stock=-2)

    code, sortie = _run()

    assert code == 1
    assert f"variante #{variante.pk}" in sortie
    assert negative_variants() == [(variante.pk, produit.pk, -2)]


@pytest.mark.django_db
def test_alias_de_base_inconnu_est_refuse():
    code, sortie = _run(database="inexistante")
    assert code == 1
    assert "Alias de base inconnu" in sortie


@pytest.mark.django_db
def test_stock_zero_n_est_pas_negatif(produit):
    Product.objects.filter(pk=produit.pk).update(stock_available=0)
    assert negative_products() == []
