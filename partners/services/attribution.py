"""Attribution d'un vendeur à un partenaire (à l'inscription), sans jamais bloquer.

Règles : un vendeur n'a qu'un parrain, attribué une fois et jamais modifié ;
code invalide / partenaire inactif / contrat expiré / place libérée / auto-
recommandation : pas d'attribution, et rien ne le signale à l'utilisateur.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from accounts.services.users import normalize_phone
from core.services.client_ip import get_client_ip
from core.services.rate_limit import ip_fingerprint
from partners.models import CODE_RE, Partner, Referral

logger = logging.getLogger(__name__)

FLAG_WINDOW_DAYS = 7
FLAG_MAX_SAME_IP = 3
FLAG_REASON = "Plus de 3 inscriptions depuis la même adresse en 7 jours"
COOKIE_NAME = "hf_ref"


def request_ip_hash(request) -> str:
    """Empreinte salée de l'IP du client ; vide si l'IP est indéterminable."""
    ip = get_client_ip(request)
    return "" if ip == "unknown" else ip_fingerprint(ip)


def clean_code(raw) -> str:
    """Code normalisé (majuscules) ou chaîne vide s'il n'a pas la forme attendue."""
    code = re.sub(r"\s+", "", raw or "").upper() if isinstance(raw, str) else ""
    return code if CODE_RE.match(code) else ""


def find_partner_for_new_referral(raw_code) -> Partner | None:
    """Partenaire pouvant recevoir un NOUVEAU parrainage (actif et contrat en cours)."""
    code = clean_code(raw_code)
    if not code:
        return None
    partner = Partner.objects.filter(code=code).first()
    if partner is None or not partner.accepts_new_referrals:
        return None
    return partner


def _flag_same_ip_group(partner: Partner, ip_hash: str) -> None:
    if not ip_hash:
        return
    since = timezone.now() - timedelta(days=FLAG_WINDOW_DAYS)
    group = Referral.objects.filter(
        partner=partner, signup_ip_hash=ip_hash, attributed_at__gte=since
    )
    if group.count() > FLAG_MAX_SAME_IP:
        group.update(flagged=True, flag_reason=FLAG_REASON)


def _create_referral(*, partner, seller, source, ip_hash) -> Referral:
    referral = Referral.objects.create(
        partner=partner, seller=seller, source=source, signup_ip_hash=ip_hash
    )
    _flag_same_ip_group(partner, ip_hash)
    referral.refresh_from_db()
    return referral


def attribute_referral(
    *, seller, partner_code, signup_phone, source: str = "link", ip_hash: str = ""
) -> Referral | None:
    """Rattache ``seller`` au partenaire de ``partner_code`` si les règles le permettent.

    Ne lève jamais : une erreur est journalisée (type seulement) et l'inscription
    continue. Un parrainage existant est renvoyé tel quel, jamais modifié.
    """
    try:
        existing = Referral.objects.filter(seller=seller).first()
        if existing is not None:
            return existing
        partner = find_partner_for_new_referral(partner_code)
        if partner is None:
            return None
        if normalize_phone(signup_phone or "") == partner.phone:
            return None  # auto-recommandation
        with transaction.atomic():  # point de sauvegarde : une panne ne casse pas l'inscription
            return _create_referral(
                partner=partner, seller=seller, source=source, ip_hash=ip_hash
            )
    except Exception as exc:
        logger.error("Attribution partenaire echouee (%s)", type(exc).__name__)
        return None
