"""Contrainte CHECK de base : un stock ne peut jamais être négatif.

Garde-fou au niveau base, indépendant du code applicatif (create_order,
adjust_stock, distrib...). Nécessite la migration products.0011.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from accounts.models import SellerProfile
from products.models import Product, ProductVariant
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def produit(db):
    user = User.objects.create_user(
        phone="+22370010001", password="x", display_name="Vendeuse stock"
    )
    seller = SellerProfile.objects.create(user=user)
    return Product.objects.create(
        owner=seller,
        name="Sac",
        price=Decimal("15000"),
        stock_initial=5,
        stock_available=5,
    )


@pytest.mark.django_db
def test_stock_disponible_negatif_leve_integrity_error(produit):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Product.objects.filter(pk=produit.pk).update(stock_available=-1)


@pytest.mark.django_db
def test_stock_variante_negatif_leve_integrity_error(produit):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ProductVariant.objects.create(
                product=produit, type="taille", value="M", stock=-3
            )


@pytest.mark.django_db
def test_stock_zero_reste_autorise(produit):
    Product.objects.filter(pk=produit.pk).update(stock_available=0)
    produit.refresh_from_db()
    assert produit.stock_available == 0
    ProductVariant.objects.create(product=produit, type="taille", value="S", stock=0)


@pytest.mark.django_db
def test_contraintes_declarees_dans_le_modele():
    noms = {c.name for c in Product._meta.constraints}
    assert "product_stock_available_non_negatif" in noms
    noms_var = {c.name for c in ProductVariant._meta.constraints}
    assert "productvariant_stock_non_negatif" in noms_var
