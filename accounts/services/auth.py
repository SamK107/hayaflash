from __future__ import annotations

from django.contrib.auth import authenticate, login
from django.db import transaction
from rest_framework.exceptions import AuthenticationFailed

from accounts.models import SellerProfile, User
from core.legal import record_legal_acceptances


@transaction.atomic
def register_user(validated_data: dict, request=None) -> User:
    create_seller_profile = validated_data.pop("create_seller_profile", False)
    business_name = validated_data.pop("business_name", "")
    password = validated_data.pop("password")
    # Deja verifiee a True par RegisterSerializer ; pas un champ du modele.
    validated_data.pop("accept_terms", None)

    user = User.objects.create_user(password=password, **validated_data)

    if create_seller_profile:
        SellerProfile.objects.create(user=user, business_name=business_name)

    record_legal_acceptances(user, request)

    return user


def login_user(request, validated_data: dict) -> User:
    phone = User.objects.normalize_phone(validated_data["phone"])
    # HttpRequest sous-jacent : django-axes pose `axes_locked_out` sur la requete
    # recue par authenticate(), et son middleware ne lit que l'HttpRequest, pas
    # le wrapper DRF (sinon le verrou n'aboutit jamais a la reponse 429).
    user = authenticate(
        getattr(request, "_request", request),
        phone=phone,
        password=validated_data["password"],
    )

    if user is None:
        raise AuthenticationFailed("Invalid phone or password.")

    login(request, user)
    return user
