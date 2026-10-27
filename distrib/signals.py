"""Signal `post_save` sur `Order` (spec §2.4, §5.4).

Le suivi ne doit JAMAIS bloquer ni faire echouer une commande :
- la synchronisation est differee par `transaction.on_commit` (la commande est deja validee) ;
- toute erreur, y compris a l'enregistrement du rappel, est journalisee et jamais propagee ;
- interrupteur coupe : le signal ne fait rien ;
- la tache de reconciliation (beat, 5 min) rattrape tout oubli.
"""

from __future__ import annotations

import logging

from django.db import transaction

from .access import distrib_enabled

logger = logging.getLogger(__name__)


def order_saved(sender, instance, raw=False, **kwargs) -> None:
    try:
        if raw or not distrib_enabled():
            return
        order_id = instance.pk
        from .services.settlement import safe_sync_order

        transaction.on_commit(lambda: safe_sync_order(order_id))
    except Exception:
        logger.exception("distrib: signal de commande ignore (la reconciliation rattrapera)")
