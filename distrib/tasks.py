"""Taches Celery du module Distrib. File par defaut (« default »), ecoutee par le worker.

Chaque tache ne fait RIEN quand `DISTRIB_ENABLED` est faux (spec §7). Les erreurs sont
journalisees dans les services, jamais propagees d'une ligne aux autres.
"""

from __future__ import annotations

from celery import shared_task

from .access import distrib_enabled


@shared_task(name="distrib.reconcile_settlements", ignore_result=True)
def reconcile_settlements_task() -> None:
    """Toutes les 5 min : cree les lignes manquantes et synchronise les statuts (§5.4)."""
    if not distrib_enabled():
        return
    from .services.settlement import reconcile

    reconcile()


@shared_task(name="distrib.auto_confirm_settlements", ignore_result=True)
def auto_confirm_settlements_task() -> None:
    """Toutes les 15 min : presomption de livraison apres `auto_confirm_hours` (§15.1)."""
    if not distrib_enabled():
        return
    from .services.settlement import auto_confirm_due

    auto_confirm_due()


@shared_task(name="distrib.close_weekly_statements", ignore_result=True)
def close_weekly_statements_task() -> None:
    """Lundi 00:05 : un releve par revendeur pour la semaine ecoulee (§15.4). Idempotent."""
    if not distrib_enabled():
        return
    from .services.statements import close_weekly_statements

    close_weekly_statements()


@shared_task(name="distrib.accept_payouts", ignore_result=True)
def accept_payouts_task() -> None:
    """Toutes les 15 min : silence du revendeur pendant 72 h = versement accepte (§15.4)."""
    if not distrib_enabled():
        return
    from .services.statements import accept_due_payouts

    accept_due_payouts()
