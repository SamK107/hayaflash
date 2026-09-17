#!/bin/bash
# infra/scripts/backup.sh — sauvegarde base de donnees + medias HayaFlash
#
# Tourne sur le VPS (ou en local pour test), a cote de deploy.sh. Produit deux
# fichiers locaux horodates : un dump PostgreSQL compresse et une archive des
# medias, plus une purge des sauvegardes plus vieilles que BACKUP_RETENTION_DAYS.
#
# Usage :
#   DB_USER=hayaflash DB_NAME=hayaflash bash infra/scripts/backup.sh [BACKUP_DIR]
#
# Variables :
#   COMPOSE_FILE          Fichier compose a utiliser (defaut : docker-compose.production.yml)
#   BACKUP_DIR            Dossier de sortie (defaut : /srv/hayaflash/backups, ou 1er argument)
#   BACKUP_RETENTION_DAYS Nombre de jours a garder (defaut : 14)
#
# Volontairement hors scope de ce script (categorie 5 de GOVERNANCE_SECURITE.md,
# decisions produit/infra a prendre avant d'aller plus loin) :
#   - copie hors-site (S3, Backblaze, autre ?)
#   - chiffrement des sauvegardes
#   - installation d'un cron sur le VPS
# Ce script s'arrete au fichier local, verifiable avec restore_test.sh.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.production.yml}"
COMPOSE="docker compose -p hayaflash -f $COMPOSE_FILE"
BACKUP_DIR="${1:-${BACKUP_DIR:-/srv/hayaflash/backups}}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

: "${DB_USER:?DB_USER requis (voir /srv/hayaflash/.env en prod)}"
: "${DB_NAME:?DB_NAME requis (voir /srv/hayaflash/.env en prod)}"

mkdir -p "$BACKUP_DIR"

echo "→ Dump PostgreSQL ($DB_NAME) via $COMPOSE_FILE"
DB_DUMP="$BACKUP_DIR/db_${TIMESTAMP}.sql.gz"
$COMPOSE exec -T db pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$DB_DUMP"
echo "  $DB_DUMP ($(du -h "$DB_DUMP" | cut -f1))"

echo "→ Archive medias (/app/media)"
MEDIA_ARCHIVE="$BACKUP_DIR/media_${TIMESTAMP}.tar.gz"
$COMPOSE exec -T web tar czf - -C /app media > "$MEDIA_ARCHIVE"
echo "  $MEDIA_ARCHIVE ($(du -h "$MEDIA_ARCHIVE" | cut -f1))"

echo "→ Retention : suppression des sauvegardes de plus de ${RETENTION_DAYS} jours"
find "$BACKUP_DIR" -maxdepth 1 -name "db_*.sql.gz" -mtime "+${RETENTION_DAYS}" -print -delete
find "$BACKUP_DIR" -maxdepth 1 -name "media_*.tar.gz" -mtime "+${RETENTION_DAYS}" -print -delete

echo "✓ Sauvegarde terminee : $BACKUP_DIR"
