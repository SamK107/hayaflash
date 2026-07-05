from rest_framework import serializers
from .models import FlashSale
from products.models import Product, ProductMedia


class ProductMediaSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = ProductMedia
        fields = ["media_type", "file_url", "video_url", "order"]

    def get_file_url(self, obj):
        request = self.context.get("request")
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None


class ProductPublicSerializer(serializers.ModelSerializer):
    media = ProductMediaSerializer(many=True, read_only=True)
    is_available = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = [
            "id", "name", "description", "price",
            "stock_available", "unit", "is_available",
            "display_order", "media",
        ]


class FlashSalePublicSerializer(serializers.ModelSerializer):
    seller_name = serializers.CharField(source="owner.business_name", read_only=True)
    seller_slug = serializers.CharField(source="owner.public_slug", read_only=True)
    cover_image_url = serializers.SerializerMethodField()

    class Meta:
        model = FlashSale
        fields = [
            "id", "title", "description", "public_slug", "status",
            "start_time", "end_time", "cover_image_url",
            "delivery_zone", "seller_name", "seller_slug",
        ]

    def get_cover_image_url(self, obj):
        request = self.context.get("request")
        if obj.cover_image and request:
            return request.build_absolute_uri(obj.cover_image.url)
        return None


class FlashSaleDetailSerializer(FlashSalePublicSerializer):
    products = ProductPublicSerializer(many=True, read_only=True)

    class Meta(FlashSalePublicSerializer.Meta):
        fields = FlashSalePublicSerializer.Meta.fields + ["products"]
