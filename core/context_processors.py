"""Context processors globaux pour HayaFlash."""

from __future__ import annotations


def seller_interests_count(request):
    """
    Injecte `interests_count` dans tous les templates.
    Vaut 0 si l'utilisateur n'est pas authentifié ou n'a pas de profil vendeur.
    """
    if not request.user.is_authenticated:
        return {"interests_count": 0}
    try:
        seller = request.user.seller_profile
    except Exception:
        return {"interests_count": 0}

    from flash_sales.models import SaleInterest

    count = SaleInterest.objects.filter(flash_sale__owner=seller).count()
    return {"interests_count": count}


def active_live_sale(request):
    """
    Injecte `active_sale` (la premiere vente LIVE du vendeur, ou None) dans
    tous les templates — utilise par le badge "LIVE" de partials/_nav_seller.html.

    Trouve mort lors de l'audit des routes : le badge referencait `active_sale`
    (jamais defini nulle part, seul `active_sales` — pluriel — existait dans le
    contexte de seller_home_view) et un lien vers `flash_sales:live` (URL
    inexistante) — le bloc {% if %} etant toujours faux, ca ne crashait jamais,
    mais le badge n'est jamais apparu.
    """
    if not request.user.is_authenticated:
        return {"active_sale": None}
    try:
        seller = request.user.seller_profile
    except Exception:
        return {"active_sale": None}

    from flash_sales.models import FlashSale, FlashSaleStatus

    sale = (
        FlashSale.objects.filter(owner=seller, status=FlashSaleStatus.LIVE)
        .order_by("start_time")
        .first()
    )
    return {"active_sale": sale}


# Pages acheteur (Phase 10.2) : manifest PWA acheteur (id /ventes/, start_url
# /ventes/). Choisi ici selon l'URL plutot que par un bloc a surcharger dans
# chaque template : une nouvelle page client sous ces prefixes (ex. futur
# espace client sous /ventes/) recoit automatiquement le bon manifest, au lieu
# de proposer par erreur l'installation de l'espace vendeur.
BUYER_PWA_PATH_PREFIXES = ("/f/", "/s/", "/ventes", "/order/")

# Cle de session posee par les vues (ex. creation de vente) pour afficher le
# bandeau d'installation sur la page suivante (apres redirection).
PWA_INSTALL_INVITE_SESSION_KEY = "hf_install_invite"


def request_pwa_install_invite(request, context: str) -> None:
    """Demande l'affichage du bandeau d'installation a la prochaine page.

    Le JS (static/js/hf-install.js) decide ensuite s'il l'affiche vraiment
    (pas si deja installee, au plus 2 fois par appareil).
    """
    request.session[PWA_INSTALL_INVITE_SESSION_KEY] = context


def pwa_install(request):
    """`pwa_app` ('buyer'/'seller') pour le manifest + invitation en attente.

    `pwa_install_invite` est un callable : Django ne l'evalue (et ne retire le
    flag de la session) que la ou un template l'utilise, c.-a-d. base.html —
    un fragment HTMX ou un autre rendu ne le consomme pas par erreur.
    """
    app = "buyer" if request.path.startswith(BUYER_PWA_PATH_PREFIXES) else "seller"

    def pwa_install_invite():
        if request.headers.get("HX-Request") or not hasattr(request, "session"):
            return None
        return request.session.pop(PWA_INSTALL_INVITE_SESSION_KEY, None)

    return {"pwa_app": app, "pwa_install_invite": pwa_install_invite}
