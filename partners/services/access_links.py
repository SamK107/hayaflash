"""Liens privés des partenaires : le jeton en clair n'est jamais stocké ni journalisé."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.utils import timezone

from partners.models import Partner, PartnerAccessLink


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def create_link(partner: Partner, purpose: str, *, days: int | None = None):
    """Crée un lien. Retourne (lien, jeton en clair) : le clair n'existe qu'ici, une seule fois."""
    token = secrets.token_urlsafe(32)
    link = PartnerAccessLink.objects.create(
        partner=partner,
        purpose=purpose,
        token_hash=hash_token(token),
        expires_at=timezone.now() + timedelta(days=days) if days else None,
    )
    return link, token


def resolve_token(token: str) -> PartnerAccessLink | None:
    """Lien actif correspondant au jeton, sinon None (inconnu, expiré ou révoqué : même résultat)."""
    if not token or len(token) > 200:
        return None
    link = (
        PartnerAccessLink.objects.select_related("partner")
        .filter(token_hash=hash_token(token))
        .first()
    )
    if link is None or not link.is_active:
        return None
    PartnerAccessLink.objects.filter(pk=link.pk).update(last_viewed_at=timezone.now())
    return link


def revoke(link: PartnerAccessLink) -> None:
    """Révoque le lien (idempotent : la première date est conservée)."""
    PartnerAccessLink.objects.filter(pk=link.pk, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
