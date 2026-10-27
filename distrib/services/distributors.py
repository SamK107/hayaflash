"""Creation d'un grossiste par l'equipe HayaFlash (spec §5.1) : jamais d'inscription libre."""

from __future__ import annotations

import secrets
import string
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from core.models import audit
from distrib.models import Distributor

_PASSWORD_ALPHABET = "".join(c for c in string.ascii_letters + string.digits if c not in "0OolI1")


def generate_temporary_password(length: int = 10) -> str:
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


def create_distributor(
    *,
    phone: str,
    display_name: str,
    business_name: str,
    created_by,
    orange_money_number: str = "",
    commission_rate: Decimal | None = None,
    pilot_until: date | None = None,
) -> tuple[Distributor, str | None]:
    """Cree le grossiste et, au besoin, son compte de connexion.

    - numero deja connu (une boutique par exemple) : le compte est rattache tel quel, son
      mot de passe n'est pas touche (retour `None`) ;
    - numero inconnu : compte cree avec un mot de passe provisoire, retourne UNE fois pour que
      l'equipe le transmette ; il n'est stocke nulle part en clair.
    """
    User = get_user_model()
    business_name = (business_name or "").strip()
    if not business_name:
        raise ValidationError("Indiquez le nom commercial du grossiste.")

    with transaction.atomic():
        user = User.objects.select_for_update().filter(phone=phone).first()
        temporary_password = None
        if user is None:
            if not (display_name or "").strip():
                raise ValidationError("Indiquez le nom de la personne de contact.")
            temporary_password = generate_temporary_password()
            user = User.objects.create_user(
                phone=phone, password=temporary_password, display_name=display_name.strip()
            )
        elif Distributor.objects.filter(user=user).exists():
            raise ValidationError("Ce numéro correspond déjà à un grossiste.")

        extra = {}
        if commission_rate is not None:
            extra["commission_rate"] = commission_rate
        if pilot_until is not None:
            extra["pilot_until"] = pilot_until
        distributor = Distributor.objects.create(
            user=user,
            business_name=business_name,
            contact_phone=phone,
            orange_money_number=orange_money_number or "",
            created_by=created_by,
            **extra,
        )
        audit(
            "distrib.distributor_created",
            entity_type="Distributor",
            entity_id=distributor.pk,
            actor=created_by,
            new_account=temporary_password is not None,
        )
    return distributor, temporary_password
