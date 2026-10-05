"""Validateurs de mot de passe : messages 100 % français.

Les messages de Django sont traduits, sauf celui de la similarité qui cite le
nom technique du champ (« display name », « phone »).
"""

from __future__ import annotations

from django.contrib.auth.password_validation import UserAttributeSimilarityValidator
from django.core.exceptions import ValidationError


class FrenchUserAttributeSimilarityValidator(UserAttributeSimilarityValidator):
    def validate(self, password, user=None):
        try:
            super().validate(password, user)
        except ValidationError as exc:
            raise ValidationError(
                "Le mot de passe est trop semblable à votre numéro ou au nom de votre boutique.",
                code=exc.code,
            ) from None

    def get_help_text(self):
        return "Votre mot de passe ne peut pas ressembler à votre numéro ou au nom de votre boutique."
