from __future__ import annotations

from typing import TYPE_CHECKING

from core.services.slugs import seller_slug_base, unique_slug_for_model

if TYPE_CHECKING:
    from accounts.models import SellerProfile


def generate_unique_seller_public_slug(profile: SellerProfile) -> str:
    base = seller_slug_base(
        business_name=profile.business_name,
        display_name=profile.user.display_name,
    )
    return unique_slug_for_model(
        type(profile),
        field_name="public_slug",
        base=base,
        exclude_pk=profile.pk,
        max_length=80,
    )
