"""Politique de mot de passe des NOUVELLES saisies (inscription, changement).

Elle s'appuie sur ``AUTH_PASSWORD_VALIDATORS`` (config/settings/base.py :
8 caractères minimum, ni trop courant, ni tout numérique, ni trop semblable
au numéro ou au nom). Les messages sont ceux de Django, traduits en français
(LANGUAGE_CODE = "fr-fr").

Jamais appelée à la connexion : les comptes existants (mot de passe de 6
caractères par exemple) continuent de se connecter, un hash ne permettant pas
de connaître la longueur du mot de passe.
"""

from __future__ import annotations

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError


def password_policy_errors(password: str, user) -> list[str]:
    """Messages (français) des validateurs en échec ; liste vide si le mot de passe convient.

    ``user`` peut être un utilisateur non enregistré (inscription) : seuls ses
    attributs ``phone`` et ``display_name`` servent à la vérification de
    similarité.
    """
    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        return list(exc.messages)
    return []
