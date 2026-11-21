"""Fenêtre de vente (avant / pendant / après) et idempotence de POST /api/v1/orders/.

Le temps réel est utilisé (pas de bibliothèque de temps figé) : chaque cas
règle explicitement les bornes de la vente par rapport à `now`.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order
from orders.tests import LiveFlashSaleProductFixture


def _payload(fixture, client_request_id: str, **overrides) -> dict:
    base = {
        "flash_sale_id": fixture.sale.pk,
        "product_id": fixture.product.pk,
        "name": "Acheteuse",
        "phone": "+22370030001",
        "quantity": 1,
        "client_request_id": client_request_id,
        "delivery": {"address_text": "Quartier du fleuve, Bamako", "geo_method": "manual"},
    }
    base.update(overrides)
    return base


class FenetreVenteTests(LiveFlashSaleProductFixture):
    """Commande acceptée uniquement pendant la fenêtre horaire de la vente."""

    def _fixer_fenetre(self, debut_delta, fin_delta, statut):
        now = timezone.now()
        FlashSale.objects.filter(pk=self.sale.pk).update(
            start_time=now + debut_delta,
            end_time=now + fin_delta,
            status=statut,
        )

    def _commander(self, request_id: str):
        return APIClient().post(
            "/api/v1/orders/", _payload(self, request_id), format="json"
        )

    def test_avant_ouverture_refusee(self):
        self._fixer_fenetre(
            timedelta(hours=1), timedelta(hours=2), FlashSaleStatus.SCHEDULED
        )
        n = Order.objects.count()
        response = self._commander("fenetre-avant")
        assert response.status_code == 400
        assert Order.objects.count() == n

    def test_pendant_fenetre_acceptee(self):
        self._fixer_fenetre(
            -timedelta(hours=1), timedelta(hours=1), FlashSaleStatus.LIVE
        )
        response = self._commander("fenetre-pendant")
        assert response.status_code == 201, response.content

    def test_apres_fermeture_refusee_meme_si_statut_pas_encore_bascule(self):
        """Celery beat peut être en retard : le statut LIVE ne suffit pas, l'heure fait foi."""
        self._fixer_fenetre(
            -timedelta(hours=2), -timedelta(minutes=5), FlashSaleStatus.LIVE
        )
        n = Order.objects.count()
        response = self._commander("fenetre-apres")
        assert response.status_code == 400
        assert Order.objects.count() == n

    def test_vente_annulee_refusee(self):
        self._fixer_fenetre(
            -timedelta(hours=1), timedelta(hours=1), FlashSaleStatus.CANCELLED
        )
        response = self._commander("fenetre-annulee")
        assert response.status_code == 400


class IdempotenceApiTests(LiveFlashSaleProductFixture):
    def test_rejeu_meme_request_id_ne_cree_pas_de_second_ordre(self):
        client = APIClient()
        first = client.post("/api/v1/orders/", _payload(self, "idem-1"), format="json")
        second = client.post("/api/v1/orders/", _payload(self, "idem-1"), format="json")
        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json()["already_exists"] is True
        assert Order.objects.filter(client_request_id="idem-1").count() == 1

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "FINDING : orders/api.py:29-47 renvoie l'adresse de livraison de la "
            "commande existante à tout appelant anonyme qui connaît son "
            "client_request_id (aucun contrôle de propriété). Passe en échec "
            "(XPASS strict) dès que la fuite est corrigée : retirer alors ce marqueur."
        ),
    )
    def test_rejeu_anonyme_ne_divulgue_pas_la_livraison_de_la_commande_existante(self):
        client = APIClient()
        client.post("/api/v1/orders/", _payload(self, "idem-leak"), format="json")
        autre = _payload(
            self,
            "idem-leak",
            name="Intruse",
            phone="+22370030999",
            delivery={"address_text": "Adresse d'une autre cliente", "geo_method": "manual"},
        )
        response = client.post("/api/v1/orders/", autre, format="json")
        # La première commande a l'adresse « Quartier du fleuve » (valeur par défaut).
        assert "Quartier du fleuve" not in response.content.decode()
        assert "address_text" not in response.json().get("delivery", {})
