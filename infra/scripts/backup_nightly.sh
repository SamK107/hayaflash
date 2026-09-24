#!/bin/bash
# infra/scripts/backup_nightly.sh — enchainement quotidien lance par le cron
# (infra/cron/hayaflash-backup). Ne rien lancer a la main sur le VPS avant la
# checklist de deploiement final (ADR-0001, decisions 3 et 4).
#
#   1. backup.sh        : dump PostgreSQL + archive medias + retention locale
#   2. copy_offsite.sh  : copie CHIFFREE (age) vers le disque externe, SEULEMENT
#                         si le disque est branche (fichier temoin present).
#                         Disque absent = cas normal (branche periodiquement) :
#                         on le logue, sans echec (ADR-0001, decision 1).
#   3. Heartbeat        : si BACKUP_HEARTBEAT_URL est defini (healthchecks.io,
#                         UptimeRobot "heartbeat"...), ping en fin de succes.
#                         Pas de ping = alerte cote service : c'est ce qui
#                         detecte un cron mort ou un dump qui echoue en silence.
#
# Variables lues dans ENV_FILE (defaut /srv/hayaflash/.env) : DB_USER, DB_NAME,
# et optionnellement OFFSITE_DIR, AGE_RECIPIENTS_FILE, BACKUP_HEARTBEAT_URL,
# BACKUP_RETENTION_DAYS, OFFSITE_RETENTION_DAYS.

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-/srv/hayaflash/.env}"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

echo "=== $(date -Is) backup_nightly : debut"

bash "$SCRIPTS_DIR/backup.sh"

if [ -n "${OFFSITE_DIR:-}" ] && [ -f "$OFFSITE_DIR/.hayaflash_backup_target" ]; then
  bash "$SCRIPTS_DIR/copy_offsite.sh"
else
  echo "→ Disque externe absent (${OFFSITE_DIR:-OFFSITE_DIR non defini}) : copie hors-site sautee ce soir."
fi

if [ -n "${BACKUP_HEARTBEAT_URL:-}" ]; then
  curl -fsS -m 10 --retry 3 "$BACKUP_HEARTBEAT_URL" >/dev/null \
    || echo "⚠ Heartbeat injoignable : $BACKUP_HEARTBEAT_URL"
fi

echo "=== $(date -Is) backup_nightly : OK"
