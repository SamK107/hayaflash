"""Context processors globaux pour HayaFlash."""

from __future__ import annotations


# Pastilles de la navigation vendeur (F-84). Definitions :
# - commandes a traiter  = commandes du vendeur au statut `pending` (jamais
#   confirmees) ; les `confirmed` attendent la livraison, donc relevent du
#   compteur « livraisons » ;
# - livraisons en cours  = livraisons du vendeur aux statuts `assigned` ou
#   `in_transit` (`pending` = pas encore prise en charge, `delivered` / `failed`
#   = terminees) ;
# - reservations         = SaleInterest du vendeur.
# Les deux premiers COUNT sont mis en cache 5 s (meme ordre de grandeur que
# KPI_CACHE_TTL_SECONDS) : au plus 5 s de retard, cout constant.
NAV_COUNTS_CACHE_KEY = "hf:navcounts:{seller_id}"
NAV_COUNTS_TTL_SECONDS = 5
NAV_BADGE_CAP = 99
_ZERO_NAV_COUNTS = {"orders_to_process_count": 0, "deliveries_active_count": 0}


def format_nav_badge(count: int) -> str:
    """Texte d'une pastille : valeur exacte jusqu'a 99, « 99+ » au-dela."""
    return f"{NAV_BADGE_CAP}+" if count > NAV_BADGE_CAP else str(count)


def _compute_nav_counts(seller) -> dict:
    from delivery.models import Delivery
    from orders.models import Order, OrderStatus

    return {
        "orders_to_process_count": Order.service_objects.filter(
            flash_sale__owner=seller, status=OrderStatus.PENDING
        ).count(),
        "deliveries_active_count": Delivery.objects.filter(
            order__flash_sale__owner=seller,
            status__in=[Delivery.Status.ASSIGNED, Delivery.Status.IN_TRANSIT],
        ).count(),
    }


def seller_interests_count(request):
    """
    Injecte les compteurs de la navigation vendeur dans tous les templates :
    `interests_count`, `orders_to_process_count`, `deliveries_active_count` et
    leur libelle de pastille (`*_badge`, plafonne a « 99+ »).
    Tout vaut 0 si l'utilisateur n'est pas authentifie ou n'a pas de profil
    vendeur. Les fragments HTMX (HX-Request) ne rendent pas la navigation : on
    saute alors tous les COUNT.
    """
    zero = {
        "interests_count": 0,
        **_ZERO_NAV_COUNTS,
        "orders_to_process_badge": "0",
        "deliveries_active_badge": "0",
    }
    if not request.user.is_authenticated or request.headers.get("HX-Request"):
        return zero
    try:
        seller = request.user.seller_profile
    except Exception:
        return zero

    from django.core.cache import cache

    from flash_sales.models import SaleInterest

    count = SaleInterest.objects.filter(flash_sale__owner=seller).count()

    counts = cache.get_or_set(
        NAV_COUNTS_CACHE_KEY.format(seller_id=seller.pk),
        lambda: _compute_nav_counts(seller),
        NAV_COUNTS_TTL_SECONDS,
    )
    return {
        "interests_count": count,
        **counts,
        "orders_to_process_badge": format_nav_badge(counts["orders_to_process_count"]),
        "deliveries_active_badge": format_nav_badge(counts["deliveries_active_count"]),
    }


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

    from flash_sales.models import FlashSale
    from flash_sales.services.ordering import live_now_q

    # Par l'heure (CLAUDE.md point 15) : une vente LIVE dont la fin est passee
    # (beat en retard/absent) ne doit plus afficher le badge "LIVE".
    sale = (
        FlashSale.objects.filter(live_now_q(), owner=seller)
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
