"""Journal d'accès Gunicorn sans le jeton des liens privés (F-109).

Utilisé avec `--logger-class config.gunicorn_logging.MaskedLogger`. Le format d'accès par défaut de Gunicorn contient
la ligne de requête (`%(r)s`) et le Referer (`%(f)s`) : on masque le jeton dans chaque valeur avant la mise en forme.
Ce module n'importe Gunicorn qu'à l'exécution (Gunicorn n'est pas importable sous Windows, où seuls les tests tournent).
"""

from __future__ import annotations

from gunicorn.glogging import Logger

from core.logging_mask import mask_private_tokens


class MaskedLogger(Logger):
    def atoms(self, resp, req, environ, request_time):
        atoms = super().atoms(resp, req, environ, request_time)
        return {key: mask_private_tokens(value) for key, value in atoms.items()}
