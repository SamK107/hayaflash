"""Acces aux pages vendeur pour un compte SANS profil vendeur.

Un compte staff (createsuperuser, administration pure) ou tout compte
non-vendeur n'a pas de SellerProfile : `request.user.seller_profile` leve alors
RelatedObjectDoesNotExist, soit une erreur 500 sur les pages vendeur.

Regle unique, jamais de 500 :
  - page vendeur (GET/POST classique) -> redirection : /platform-admin/ si
    staff (avec un message), sinon /seller/ (qui explique la situation) ;
  - fragment HTMX / appel AJAX (JSON) -> 403 explicite, une redirection n'y
    aurait pas de sens (voir orders/, delivery/, analytics/).
"""

from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

NO_PROFILE_STAFF_MESSAGE = (
    "Ce compte d'administration n'a pas de boutique : les pages vendeur ne "
    "s'appliquent pas. Utilisez un compte vendeur pour vendre ou tester un paiement."
)


def get_seller_or_none(user):
    """Profil vendeur de l'utilisateur, ou None (jamais d'exception)."""
    if not getattr(user, "is_authenticated", False):
        return None
    return getattr(user, "seller_profile", None)


def redirect_without_seller_profile(request):
    """Reponse pour un compte sans profil vendeur sur une page vendeur."""
    if request.user.is_staff:
        messages.info(request, NO_PROFILE_STAFF_MESSAGE)
        return redirect("platform_admin")
    # /seller/ affiche une page explicative (seller/no_profile.html) :
    # aucune boucle de redirection possible.
    return redirect("seller_home")


def seller_required(view_func):
    """login_required + profil vendeur obligatoire (sinon redirection, cf. module)."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if get_seller_or_none(request.user) is None:
            return redirect_without_seller_profile(request)
        return view_func(request, *args, **kwargs)

    return login_required(_wrapped)
