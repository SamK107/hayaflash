from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db.models import (
    DecimalField,
    ExpressionWrapper,
    F,
    IntegerField,
    Prefetch,
    Q,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.http import Http404

from flash_sales.models import FlashSale
from orders.models import Order, OrderItem, OrderStatus

KPI_CACHE_KEY = "kpi:seller:{user_id}:v{version}:{scope}"
KPI_VERSION_KEY = "kpi:seller:{user_id}:version"
KPI_CACHE_TTL_SECONDS = 4
DASHBOARD_PAGE_SIZE = 20


def collected_q(prefix: str = "order__") -> Q:
    """Définition unique de « Encaissé » (F-94) : commande livrée ET livraison encaissée.

    ``prefix`` désigne le chemin vers la commande depuis le modèle filtré
    (``"order__"`` pour ``OrderItem``, ``""`` pour ``Order``). ``order.delivery``
    est un OneToOne : la jointure ne multiplie pas les lignes. Une commande
    livrée sans livraison n'est jamais encaissée (NULL ≠ True).
    """
    return Q(
        **{
            f"{prefix}status": OrderStatus.DELIVERED,
            f"{prefix}delivery__cod_collected": True,
        }
    )


def resolve_owned_flash_sale(user, raw_flash_sale_id):
    """Vente du vendeur désignée par le filtre, ou 404.

    ``None`` / chaîne vide / ``all`` = « Toutes les ventes ». Une valeur non entière, une
    vente inconnue ou celle d'un autre vendeur lèvent le même Http404 : rien ne
    permet de distinguer « n'existe pas » de « appartient à quelqu'un d'autre ».
    """
    if raw_flash_sale_id in (None, "", "all"):
        return None
    try:
        sale_id = int(raw_flash_sale_id)
    except (TypeError, ValueError):
        raise Http404("Vente introuvable.") from None
    sale = FlashSale.objects.filter(pk=sale_id, owner__user=user).first()
    if sale is None:
        raise Http404("Vente introuvable.")
    return sale


def list_owned_flash_sales(user):
    """Ventes proposées dans le sélecteur (récentes d'abord)."""
    return FlashSale.objects.filter(owner__user=user).order_by("-start_time")


def _scope(flash_sale_id) -> str:
    return "all" if flash_sale_id is None else str(flash_sale_id)


def _seller_orders_queryset(user, flash_sale_id=None):
    qs = (
        Order.service_objects.filter(flash_sale__owner__user=user)
        .select_related("flash_sale", "delivery")
        .prefetch_related(
            Prefetch(
                "items",
                queryset=OrderItem.objects.select_related("product"),
            )
        )
    )
    if flash_sale_id is not None:
        qs = qs.filter(flash_sale_id=flash_sale_id)
    return qs


def _kpi_version(user) -> int:
    return cache.get(KPI_VERSION_KEY.format(user_id=user.pk), 0)


def invalidate_seller_kpi_cache(user) -> None:
    """Invalide toutes les variantes (toutes ventes + une par vente) en changeant la version."""
    key = KPI_VERSION_KEY.format(user_id=user.pk)
    cache.set(key, _kpi_version(user) + 1, None)


def get_dashboard_kpis(user, flash_sale_id=None) -> dict[str, Any]:
    """
    Agrégats pour le vendeur connecté (optionnellement limités à une vente).
    - total_orders  : toutes commandes non annulées
    - total_quantity: articles de toutes commandes non annulées
    - total_revenue : Encaissé = commandes livrées dont la livraison a cod_collected=True
    - pending_revenue: En cours d'encaissement = confirmées + en livraison + livrées non encaissées
    """
    sale_filter = {} if flash_sale_id is None else {"flash_sale_id": flash_sale_id}
    item_sale_filter = (
        {} if flash_sale_id is None else {"order__flash_sale_id": flash_sale_id}
    )
    non_cancelled = Order.service_objects.filter(
        flash_sale__owner__user=user, **sale_filter
    ).exclude(status=OrderStatus.CANCELLED)

    total_orders = non_cancelled.count()

    revenue_expr = ExpressionWrapper(
        F("price_snapshot") * F("quantity"),
        output_field=DecimalField(max_digits=14, decimal_places=0),
    )

    zero = Value(
        Decimal("0.00"), output_field=DecimalField(max_digits=14, decimal_places=0)
    )
    owned_items = OrderItem.objects.filter(
        order__flash_sale__owner__user=user, **item_sale_filter
    )

    # Articles livrés : commandes livrées, qu'elles soient encaissées ou non.
    delivered_agg = owned_items.filter(order__status=OrderStatus.DELIVERED).aggregate(
        total_quantity=Coalesce(Sum("quantity"), Value(0, output_field=IntegerField())),
    )

    # Encaissé (F-94) : commande livrée ET paiement à la livraison réellement
    # encaissé (Delivery.cod_collected). `order.delivery` est un OneToOne : la
    # jointure ne multiplie pas les lignes de commande (pas de double comptage).
    collected = collected_q("order__")
    # En cours d'encaissement : commandes confirmées ou en livraison, plus les
    # commandes livrées NON encaissées (cod_collected faux). Une commande livrée
    # sans livraison associée n'est jamais « encaissée » : par prudence elle
    # compte ici. ~Q(...cod_collected=True) traite le NULL (pas de livraison)
    # comme « non encaissé ».
    in_progress = Q(
        order__status__in=[OrderStatus.CONFIRMED, OrderStatus.OUT_FOR_DELIVERY]
    ) | (Q(order__status=OrderStatus.DELIVERED) & ~Q(order__delivery__cod_collected=True))
    money = owned_items.aggregate(
        total_revenue=Coalesce(Sum(revenue_expr, filter=collected), zero),
        pending_revenue=Coalesce(Sum(revenue_expr, filter=in_progress), zero),
    )

    return {
        "total_orders": total_orders,
        "total_quantity": int(delivered_agg["total_quantity"] or 0),
        "total_revenue": money["total_revenue"],
        "pending_revenue": money["pending_revenue"],
    }


def get_dashboard_kpis_cached(user, flash_sale_id=None) -> dict[str, Any]:
    """KPI snapshot with short TTL (shared cache backend: LocMem or Redis).

    La clé porte la vente filtrée (ou « all ») et la version d'invalidation :
    deux filtres ne partagent jamais la même entrée.
    """
    key = KPI_CACHE_KEY.format(
        user_id=user.pk, version=_kpi_version(user), scope=_scope(flash_sale_id)
    )
    hit = cache.get(key)
    if hit is not None:
        return hit
    data = get_dashboard_kpis(user, flash_sale_id)
    cache.set(key, data, KPI_CACHE_TTL_SECONDS)
    return data


def get_dashboard_orders(user, *, limit: int = DASHBOARD_PAGE_SIZE, flash_sale_id=None):
    """Latest orders for this seller (optionally one sale), newest first."""
    return _seller_orders_queryset(user, flash_sale_id).order_by("-created_at")[:limit]


def count_dashboard_orders(user, flash_sale_id=None) -> int:
    """Nombre total de commandes du périmètre (tous statuts), pour « 20 sur N »."""
    return Order.service_objects.filter(
        flash_sale__owner__user=user,
        **({} if flash_sale_id is None else {"flash_sale_id": flash_sale_id}),
    ).count()


def _delivery_of(order: Order):
    """Fiche de livraison de la commande, ou None (commande ancienne sans fiche)."""
    return getattr(order, "delivery", None)


def _order_state(order: Order) -> dict[str, Any]:
    """Libellé et couleur affichés sur la carte (circuit unique : lecture seule après confirmation)."""
    from delivery.models import Delivery

    delivery = _delivery_of(order)
    if order.status == OrderStatus.CANCELLED:
        return {"state": "cancelled", "state_label": "Annulé", "state_tone": "red"}
    if order.status == OrderStatus.PENDING:
        return {"state": "pending", "state_label": "En attente", "state_tone": "amber"}
    if delivery is not None and delivery.status == Delivery.Status.FAILED:
        return {"state": "failed", "state_label": "Échec", "state_tone": "red"}
    if order.status == OrderStatus.CONFIRMED:
        return {"state": "to_deliver", "state_label": "À livrer", "state_tone": "gray"}
    if order.status == OrderStatus.OUT_FOR_DELIVERY:
        return {"state": "in_transit", "state_label": "En livraison", "state_tone": "gray"}
    if delivery is not None and not delivery.cod_collected:
        return {"state": "delivered_unpaid", "state_label": "Livré, à encaisser", "state_tone": "amber"}
    return {"state": "delivered", "state_label": "Livré et payé", "state_tone": "green"}


def delivery_page_url(order: Order) -> str:
    """Page Livraison ouverte sur la vente de la commande, ancrée sur sa carte."""
    from django.urls import reverse

    url = reverse("orders:seller_deliveries_dashboard")
    if not order.flash_sale_id:
        return url
    delivery = _delivery_of(order)
    anchor = f"#delivery-row-{delivery.pk}" if delivery is not None else ""
    return f"{url}?flash_sale_id={order.flash_sale_id}{anchor}"


def _row_dict_for_order(order: Order, blocked_keys: frozenset[str] = frozenset()) -> dict[str, Any]:
    from orders.services.unhonored import phone_key

    state = _order_state(order)
    return {
        "order": order,
        "phone_blocked": phone_key(order.customer_phone) in blocked_keys,
        "can_confirm": order.status == OrderStatus.PENDING,
        "can_cancel": order.status in (OrderStatus.PENDING, OrderStatus.CONFIRMED)
        and state["state"] != "failed",
        "delivery_url": delivery_page_url(order),
        "show_delivery_link": state["state"] == "to_deliver",
        **state,
    }


def list_dashboard_order_rows(
    user, *, limit: int = DASHBOARD_PAGE_SIZE, flash_sale_id=None
) -> list[dict[str, Any]]:
    """Pre-built rows for templates (no branching logic in HTML)."""
    orders = list(get_dashboard_orders(user, limit=limit, flash_sale_id=flash_sale_id))
    blocked = _blocked_keys_for(user, orders)
    return [_row_dict_for_order(o, blocked) for o in orders]


def _blocked_keys_for(user, orders) -> frozenset[str]:
    """Numeros bloques (F-59) parmi ces commandes, pour la boutique du vendeur."""
    from orders.services.unhonored import blocked_phone_keys, phone_key

    seller = getattr(user, "seller_profile", None)
    keys = {phone_key(o.customer_phone) for o in orders}
    return frozenset(blocked_phone_keys(keys, seller.pk if seller else None))


def get_order_row_context(user, order_id: int) -> dict[str, Any] | None:
    """Single order row context for HTMX partial swap."""
    order = _seller_orders_queryset(user).filter(pk=order_id).first()
    if order is None:
        return None
    return _row_dict_for_order(order, _blocked_keys_for(user, [order]))


def advance_order_status(*, user, order_id: int) -> Order:
    """Confirme une commande en attente (seule étape de la page Commandes).

    Passe par le service de la page Livraison (``apply_order_action``) : une seule
    règle de statuts. Les étapes de livraison se font sur la page Livraison ;
    ici elles sont refusées avec un message clair.
    """
    from delivery.services.delivery import LATER_STEPS_MESSAGE, apply_order_action

    order = (
        Order.service_objects.filter(pk=order_id, flash_sale__owner__user=user).first()
    )
    if order is None:
        raise PermissionDenied("Action non autorisée.")
    if order.status not in (OrderStatus.PENDING, OrderStatus.CANCELLED):
        raise PermissionDenied(LATER_STEPS_MESSAGE)
    apply_order_action(user=user, order_id=order_id, action="confirm")
    order.refresh_from_db()
    return order


def cancel_order_by_seller(*, user, order_id: int) -> Order:
    """Annule une commande avant sa mise en livraison (stock rendu)."""
    from delivery.services.delivery import apply_order_action

    apply_order_action(user=user, order_id=order_id, action="cancel")
    return Order.service_objects.get(pk=order_id)
