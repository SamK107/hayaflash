from __future__ import annotations

from rest_framework import serializers

from .models import SellerProfile, User


class UserSerializer(serializers.ModelSerializer):
    seller_code = serializers.CharField(
        source="seller_profile.seller_code", read_only=True
    )

    class Meta:
        model = User
        fields = (
            "id",
            "phone",
            "display_name",
            "email",
            "is_phone_verified",
            "seller_code",
        )
        read_only_fields = ("id", "is_phone_verified", "seller_code")


class RegisterSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=16)
    display_name = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, min_length=8)
    email = serializers.EmailField(required=False, allow_blank=True)
    create_seller_profile = serializers.BooleanField(default=False)
    business_name = serializers.CharField(
        max_length=160, required=False, allow_blank=True
    )

    def validate_phone(self, value: str) -> str:
        phone = User.objects.normalize_phone(value)
        if User.objects.filter(phone=phone).exists():
            raise serializers.ValidationError("A user with this phone already exists.")
        return phone


class LoginSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=16)
    password = serializers.CharField(write_only=True)

    def validate_phone(self, value: str) -> str:
        return User.objects.normalize_phone(value)


class SellerProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = SellerProfile
        fields = ("id", "seller_code", "business_name", "is_active", "user")
