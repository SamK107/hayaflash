from __future__ import annotations

from django.contrib.auth import authenticate, login
from django.db import transaction
from rest_framework.exceptions import AuthenticationFailed

from accounts.models import SellerProfile, User


@transaction.atomic
def register_user(validated_data: dict) -> User:
    create_seller_profile = validated_data.pop("create_seller_profile", False)
    business_name = validated_data.pop("business_name", "")
    password = validated_data.pop("password")

    user = User.objects.create_user(password=password, **validated_data)

    if create_seller_profile:
        SellerProfile.objects.create(user=user, business_name=business_name)

    return user


def login_user(request, validated_data: dict) -> User:
    phone = User.objects.normalize_phone(validated_data["phone"])
    user = authenticate(
        request,
        phone=phone,
        password=validated_data["password"],
    )

    if user is None:
        raise AuthenticationFailed("Invalid phone or password.")

    login(request, user)
    return user
