"""Source unique des tarifs, quotas, durees et fonctionnalites des plans.

Les valeurs vivent en base (PlanConfig, modifiables dans l'admin sans
redeploiement). Tout le code les lit ICI, jamais via des constantes.

Secours (fail-closed) : si la base ou une ligne est indisponible, on
retombe sur les DEFAULT_* ci-dessous (valeurs d'origine) avec un
logger.error -- le quota reste donc applique, jamais leve par une panne.

Tarif special par vendeur (SellerPriceOverride) : get_price_quote() /
get_price() le renvoient s'il est actif et non epuise ; sinon prix officiel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.core.cache import cache
from django.utils import timezone

from subscriptions.models import Plan

logger = logging.getLogger(__name__)

# ── Valeurs de secours (= valeurs d'origine, reprises par la migration 0008) ──
DEFAULT_PRICES = {Plan.FREE: 0, Plan.MEDIUM: 2000, Plan.PRO: 5000}
DEFAULT_MONTHLY_LIMITS = {Plan.FREE: 3, Plan.MEDIUM: 10, Plan.PRO: None}
DEFAULT_DURATION_DAYS = 31
# Sans la ligne du quota : elle est generee par quota_label() pour rester
# toujours coherente avec la limite configuree.
DEFAULT_FEATURES = {
    Plan.FREE: [
        "Page publique vendeur",
        "Commandes en ligne",
        "Lien de partage WhatsApp",
    ],
    Plan.MEDIUM: [
        "Statistiques de ventes (30 derniers jours)",
        "Historique des commandes complet",
        "Page publique vendeur",
        "Commandes en ligne",
        "Lien de partage WhatsApp",
    ],
    Plan.PRO: [
        "Statistiques et analyses avancées (historique complet)",
        "Tableau de bord LIVE temps réel",
        "Notifications SMS automatiques",
        "Support prioritaire WhatsApp",
        "Accès aux nouvelles fonctionnalités en avant-première",
    ],
}

PAID_PLANS = (Plan.MEDIUM, Plan.PRO)
CACHE_KEY = "subscriptions:plan_config:v1"
CACHE_TIMEOUT = 60


@dataclass(frozen=True)
class PlanValues:
    plan: str
    price: int
    monthly_sales_limit: int | None
    duration_days: int
    features: tuple[str, ...]
    is_active: bool
    from_db: bool


def _default(plan: str) -> PlanValues:
    return PlanValues(
        plan=plan,
        price=DEFAULT_PRICES[plan],
        monthly_sales_limit=DEFAULT_MONTHLY_LIMITS[plan],
        duration_days=DEFAULT_DURATION_DAYS,
        features=tuple(DEFAULT_FEATURES[plan]),
        is_active=True,
        from_db=False,
    )


def _load_from_db() -> dict[str, PlanValues]:
    from subscriptions.models import PlanConfig

    values = {}
    for row in PlanConfig.objects.all():
        values[row.plan] = PlanValues(
            plan=row.plan,
            price=int(row.price),
            monthly_sales_limit=row.monthly_sales_limit,
            duration_days=int(row.duration_days or DEFAULT_DURATION_DAYS),
            features=tuple(str(f) for f in (row.features or [])),
            is_active=row.is_active,
            from_db=True,
        )
    return values


def _all_plans() -> dict[str, PlanValues]:
    try:
        cached = cache.get(CACHE_KEY)
    except Exception:
        cached = None
    if cached:
        return cached

    try:
        values = _load_from_db()
    except Exception:
        logger.error(
            "PlanConfig illisible : tarifs/quotas de secours (DEFAULT_*) appliqués",
            exc_info=True,
        )
        # Pas de mise en cache du secours : on retente la base au prochain appel.
        return {plan: _default(plan) for plan in Plan.values}

    missing = [plan for plan in Plan.values if plan not in values]
    for plan in missing:
        logger.error(
            "PlanConfig absent pour le plan %s : valeurs de secours appliquées", plan
        )
        values[plan] = _default(plan)
    if not missing:
        try:
            cache.set(CACHE_KEY, values, CACHE_TIMEOUT)
        except Exception:
            pass
    return values


def invalidate_plan_cache() -> None:
    try:
        cache.delete(CACHE_KEY)
    except Exception:
        logger.warning("Cache PlanConfig non invalidé (expire sous %s s)", CACHE_TIMEOUT)


# ── API publique ──────────────────────────────────────────────────────────────


def get_plan_config(plan: str) -> PlanValues:
    plans = _all_plans()
    if plan not in plans:
        logger.error("Plan inconnu %r : valeurs du plan Gratuit appliquées", plan)
        return plans[Plan.FREE]
    return plans[plan]


def get_official_price(plan: str) -> int:
    return get_plan_config(plan).price


def get_monthly_limit(plan: str) -> int | None:
    return get_plan_config(plan).monthly_sales_limit


def get_duration_days(plan: str) -> int:
    return get_plan_config(plan).duration_days


def is_plan_active(plan: str) -> bool:
    return get_plan_config(plan).is_active


def quota_label(plan: str) -> str:
    limit = get_monthly_limit(plan)
    if limit is None:
        return "Ventes flash illimitées"
    return f"{limit} vente{'s' if limit > 1 else ''} flash par mois"


def get_features(plan: str) -> list[str]:
    """Ligne du quota (generee) + fonctionnalites configurees."""
    return [quota_label(plan), *get_plan_config(plan).features]


def get_active_override(plan: str, seller):
    """Tarif special utilisable pour ce vendeur et ce plan, ou None."""
    if seller is None or plan not in PAID_PLANS:
        return None
    from subscriptions.models import SellerPriceOverride

    now = timezone.now()
    try:
        candidates = SellerPriceOverride.objects.filter(
            seller=seller,
            plan=plan,
            is_active=True,
            starts_at__lte=now,
            expires_at__gt=now,
        ).order_by("price", "-created_at")
        for override in candidates:
            if override.uses_count < override.max_uses:
                return override
    except Exception:
        logger.error("Lecture des tarifs spéciaux impossible : prix officiel", exc_info=True)
    return None


def get_price_quote(plan: str, seller=None) -> tuple[int, object | None]:
    """(montant, tarif special ou None) -- calcule cote serveur uniquement.

    Un tarif special n'est retenu que s'il reste inferieur ou egal au prix
    officiel courant (si l'officiel a baisse depuis, l'officiel l'emporte).
    """
    official = get_official_price(plan)
    override = get_active_override(plan, seller)
    if override is not None and override.price <= official:
        return int(override.price), override
    return official, None


def get_price(plan: str, seller=None) -> int:
    return get_price_quote(plan, seller)[0]


def plan_offers(current_sub=None, seller=None) -> list[dict]:
    """Cartes Medium/Pro (prix officiels) pour les pages d'upgrade."""
    offers = []
    for plan in PAID_PLANS:
        cfg = get_plan_config(plan)
        if not cfg.is_active:
            continue
        offers.append(
            {
                "plan": plan,
                "label": Plan(plan).label,
                "price": cfg.price,
                "features": get_features(plan),
                "monthly_limit": cfg.monthly_sales_limit,
                "quota_label": quota_label(plan),
                "is_current": bool(
                    current_sub
                    and current_sub.plan == plan
                    and not current_sub.is_expired
                ),
                "highlight": plan == Plan.PRO,
            }
        )
    return offers
