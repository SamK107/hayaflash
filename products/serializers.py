"""Serializers DRF pour l'API "Publication rapide" (gestion catalogue +
produits d'une vente flash). Distincts de `flash_sales/serializers.py`, qui
couvre l'API publique en lecture seule.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from rest_framework import serializers

from .models import FlashSaleProduct, Product, ProductMedia


class ProductMediaSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = ProductMedia
        fields = ["id", "file_url", "alt_text", "media_type", "order"]

    def get_file_url(self, obj):
        request = self.context.get("request")
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        if obj.file:
            return obj.file.url
        return None


class ProductCatalogSerializer(serializers.ModelSerializer):
    """Produit du catalogue vendeur -- pour la grille Publication rapide."""

    media = ProductMediaSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "description",
            "price",
            "stock_initial",
            "stock_available",
            "unit",
            "is_active",
            "media",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class FlashSaleProductSerializer(serializers.ModelSerializer):
    """Lien produit <-> vente : ce qui change par vente (prix promo, ordre)."""

    product = ProductCatalogSerializer(read_only=True)
    effective_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = FlashSaleProduct
        fields = [
            "id",
            "product",
            "promo_price",
            "effective_price",
            "display_order",
            "is_active",
        ]
        read_only_fields = ["id"]


class NewProductPayloadSerializer(serializers.Serializer):
    """Sous-payload pour la creation d'un nouveau produit catalogue depuis
    la grille (mutation avec `product_id_new` au lieu de `product_id`)."""

    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    price = serializers.DecimalField(max_digits=12, decimal_places=2)
    stock = serializers.IntegerField(min_value=0)
    unit = serializers.CharField(max_length=50, required=False, default="piece")


class FlashSaleProductMutationSerializer(serializers.Serializer):
    """Une ligne de la grille "Publication rapide" (produit existant OU
    nouveau produit catalogue a creer), avec ses reglages pour CETTE vente.
    """

    product_id = serializers.IntegerField(required=False, min_value=1)
    product_new = NewProductPayloadSerializer(required=False)
    promo_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True
    )
    stock = serializers.IntegerField(required=False, min_value=0, allow_null=True)
    display_order = serializers.IntegerField(required=False, default=0)
    is_active = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs):
        if not attrs.get("product_id") and not attrs.get("product_new"):
            raise serializers.ValidationError(
                "Fournir soit product_id (produit existant), soit product_new "
                "(nouveau produit catalogue)."
            )
        if attrs.get("product_id") and attrs.get("product_new"):
            raise serializers.ValidationError(
                "product_id et product_new sont mutuellement exclusifs."
            )
        return attrs


class FlashSaleProductBulkUpdateSerializer(serializers.Serializer):
    mutations = FlashSaleProductMutationSerializer(many=True)


class BulkImageAssignmentSerializer(serializers.Serializer):
    media_id = serializers.IntegerField()
    product_id = serializers.IntegerField()


def parse_decimal_or_none(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise serializers.ValidationError("Valeur décimale invalide.") from exc
