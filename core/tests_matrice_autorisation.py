"""Matrice d'autorisation paramétrée : anonyme, acheteur, vendeur A, vendeur B, staff.

Règle testée : un vendeur ne voit ni ne modifie les ventes (ni les produits)
d'un autre vendeur. Les codes attendus reflètent le comportement voulu :
- 302 : redirection vers la connexion ou vers l'espace adapté
- 403 : API refusée (non authentifié, pas vendeur, staff sans seller_id)
- 404 : ressource d'un autre vendeur (get_object_or_404 filtré sur owner)
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import SellerProfile
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order
from products.models import Product, StockMovement
from products.services.crud import attach_product_to_sale

User = get_user_model()

ROLES = ("anonyme", "acheteur", "vendeur_a", "vendeur_b", "staff")


@pytest.fixture
def monde(db):
    now = timezone.now()

    def _seller(phone: str, name: str):
        user = User.objects.create_user(phone=phone, password="x", display_name=name)
        return SellerProfile.objects.create(user=user), user

    seller_a, user_a = _seller("+22370020001", "Vendeuse A")
    seller_b, user_b = _seller("+22370020002", "Vendeuse B")
    buyer = User.objects.create_user(
        phone="+22370020003", password="x", display_name="Acheteuse"
    )
    staff = User.objects.create_user(
        phone="+22370020004", password="x", display_name="Staff", is_staff=True
    )

    sale_a = FlashSale.objects.create(
        title="Vente A",
        start_time=now - timedelta(hours=1),
        end_time=now + timedelta(hours=1),
        status=FlashSaleStatus.LIVE,
        owner=seller_a,
    )
    sale_b = FlashSale.objects.create(
        title="Vente B",
        start_time=now - timedelta(hours=1),
        end_time=now + timedelta(hours=1),
        status=FlashSaleStatus.LIVE,
        owner=seller_b,
    )
    product_a = Product.objects.create(
        owner=seller_a,
        name="Produit A",
        price=Decimal("10000"),
        stock_initial=5,
        stock_available=5,
    )
    attach_product_to_sale(flash_sale=sale_a, product=product_a)

    return {
        "seller_a": seller_a,
        "seller_b": seller_b,
        "user_a": user_a,
        "user_b": user_b,
        "buyer": buyer,
        "staff": staff,
        "sale_a": sale_a,
        "sale_b": sale_b,
        "product_a": product_a,
    }


def _client_for(role: str, monde: dict, api: bool):
    """Client authentifié selon le rôle (anonyme = aucun login)."""
    client = APIClient() if api else Client()
    users = {
        "acheteur": monde["buyer"],
        "vendeur_a": monde["user_a"],
        "vendeur_b": monde["user_b"],
        "staff": monde["staff"],
    }
    if role in users:
        client.force_login(users[role])
    return client


# ── Pages vendeur (HTML) ─────────────────────────────────────────────────────
WEB_ROWS = [
    # (méthode, clé d'URL, rôle, code attendu)
    ("GET", "detail", "anonyme", 302),
    ("GET", "detail", "acheteur", 302),
    ("GET", "detail", "vendeur_a", 200),
    ("GET", "detail", "vendeur_b", 404),
    ("GET", "detail", "staff", 302),
    ("GET", "edit", "anonyme", 302),
    ("GET", "edit", "acheteur", 302),
    ("GET", "edit", "vendeur_a", 200),
    ("GET", "edit", "vendeur_b", 404),
    ("GET", "edit", "staff", 302),
    ("POST", "cancel", "anonyme", 302),
    ("POST", "cancel", "acheteur", 302),
    ("POST", "cancel", "vendeur_b", 404),
]


def _web_url(key: str, monde: dict) -> str:
    sale = monde["sale_a"]
    return {
        "detail": f"/seller/flash-sales/{sale.pk}/",
        "edit": f"/seller/flash-sales/{sale.pk}/edit/",
        "cancel": f"/seller/flash-sales/{sale.pk}/cancel/",
    }[key]


@pytest.mark.django_db
@pytest.mark.parametrize("method,key,role,attendu", WEB_ROWS)
def test_matrice_pages_vendeur(monde, method, key, role, attendu):
    client = _client_for(role, monde, api=False)
    url = _web_url(key, monde)
    response = getattr(client, method.lower())(url)
    assert response.status_code == attendu, f"{role} {method} {url}"


@pytest.mark.django_db
def test_vendeur_b_ne_peut_pas_annuler_la_vente_de_a(monde):
    client = _client_for("vendeur_b", monde, api=False)
    client.post(_web_url("cancel", monde))
    monde["sale_a"].refresh_from_db()
    assert monde["sale_a"].status == FlashSaleStatus.LIVE


# ── API produits (grille Publication rapide) ─────────────────────────────────
def _catalog_url(monde: dict, staff_seller: bool = False) -> str:
    base = f"/api/v1/flash-sales/{monde['sale_a'].pk}/products/catalog/"
    if staff_seller:
        return f"{base}?seller_id={monde['seller_a'].pk}"
    return base


def _bulk_url(monde: dict) -> str:
    return f"/api/v1/flash-sales/{monde['sale_a'].pk}/products/bulk-update/"


CATALOG_ROWS = [
    ("anonyme", 403),
    ("acheteur", 403),
    ("vendeur_a", 200),
    ("vendeur_b", 404),
    ("staff", 403),
]


@pytest.mark.django_db
@pytest.mark.parametrize("role,attendu", CATALOG_ROWS)
def test_matrice_api_catalogue(monde, role, attendu):
    client = _client_for(role, monde, api=True)
    response = client.get(_catalog_url(monde))
    assert response.status_code == attendu, role


@pytest.mark.django_db
def test_matrice_api_catalogue_staff_avec_seller_id(monde):
    """Le staff n'agit sur la boutique d'un vendeur que via seller_id explicite."""
    client = _client_for("staff", monde, api=True)
    response = client.get(_catalog_url(monde, staff_seller=True))
    assert response.status_code == 200


BULK_ROWS = [
    ("anonyme", 403),
    ("acheteur", 403),
    ("vendeur_a", 200),
    ("vendeur_b", 404),
    ("staff", 403),
]


@pytest.mark.django_db
@pytest.mark.parametrize("role,attendu", BULK_ROWS)
def test_matrice_api_bulk_update(monde, role, attendu):
    """Chaque ligne tente un réglage de stock (adjust_stock, products/api.py:175)."""
    client = _client_for(role, monde, api=True)
    body = {
        "mutations": [
            {"product_id": monde["product_a"].pk, "stock": 2, "display_order": 0}
        ]
    }
    response = client.post(_bulk_url(monde), body, format="json")
    assert response.status_code == attendu, role


@pytest.mark.django_db
def test_vendeur_b_ne_peut_pas_ajuster_le_stock_du_produit_de_a(monde):
    """adjust_stock ne doit jamais modifier un produit d'un autre vendeur, même
    quand B envoie l'identifiant de ce produit sur sa propre vente."""
    client = _client_for("vendeur_b", monde, api=True)
    url = f"/api/v1/flash-sales/{monde['sale_b'].pk}/products/bulk-update/"
    body = {"mutations": [{"product_id": monde["product_a"].pk, "stock": 0}]}

    response = client.post(url, body, format="json")

    monde["product_a"].refresh_from_db()
    assert response.status_code != 200
    assert monde["product_a"].stock_available == 5
    assert not StockMovement.objects.filter(product=monde["product_a"]).exists()


@pytest.mark.django_db
def test_stock_negatif_refuse_par_adjust_stock(monde):
    client = _client_for("vendeur_a", monde, api=True)
    body = {"mutations": [{"product_id": monde["product_a"].pk, "stock": -4}]}
    response = client.post(_bulk_url(monde), body, format="json")
    assert response.status_code == 400
    monde["product_a"].refresh_from_db()
    assert monde["product_a"].stock_available == 5


# ── API commande publique (anonyme attendu) ──────────────────────────────────
@pytest.mark.django_db
def test_anonyme_peut_commander_sur_une_vente_en_cours(monde):
    client = APIClient()
    payload = {
        "flash_sale_id": monde["sale_a"].pk,
        "product_id": monde["product_a"].pk,
        "name": "Acheteuse anonyme",
        "phone": "+22370020099",
        "quantity": 1,
        "client_request_id": "matrice-anon-001",
        "delivery": {"address_text": "Hamdallaye ACI, Bamako", "geo_method": "manual"},
    }
    response = client.post("/api/v1/orders/", payload, format="json")
    assert response.status_code == 201, response.content
    assert Order.objects.filter(client_request_id="matrice-anon-001").exists()
