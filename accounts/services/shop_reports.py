"""Signalements de boutiques : creation seule.

Aucun envoi automatique (ni SMS, ni WhatsApp, ni e-mail) : le signalement reste
dans l'admin, l'equipe le lit et decide. Le contact de la cliente n'est jamais
ecrit dans les journaux.
"""

from __future__ import annotations

import logging

from accounts.models import SellerProfile, ShopReport

logger = logging.getLogger(__name__)


def create_shop_report(
    shop: SellerProfile, *, reason: str, message: str = "", contact: str = ""
) -> ShopReport:
    report = ShopReport.objects.create(
        shop=shop,
        reason=reason,
        message=(message or "").strip(),
        contact=(contact or "").strip(),
    )
    logger.info("Signalement de boutique cree : id=%s motif=%s", report.pk, reason)
    return report
