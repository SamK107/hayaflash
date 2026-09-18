#!/bin/bash
# infra/scripts/restore_test.sh — verifie qu'un dump produit par backup.sh
# est effectivement restaurable.
#
# Ne touche JAMAIS la base servie par l'app : restaure dans une base
# ephemere separee (hayaflash_restore_test_<pid>), verifiee, puis toujours
# supprimee (meme en cas d'echec, via trap).
#
# Usage :
#   DB_USER=hayaflash bash infra/scripts/restore_test.sh <chemin_vers_db_*.sql.gz>
#
# Variables :
#   COMPOSE_FILE  Fichier compose a utiliser (defaut : docker-compose.production.yml)

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.production.yml}"
COMPOSE="docker compose -p hayaflash -f $COMPOSE_FILE"

DUMP_FILE="${1:?Usage: restore_test.sh <chemin vers db_*.sql.gz>}"
: "${DB_USER:?DB_USER requis}"

if [ ! -f "$DUMP_FILE" ]; then
  echo "✗ Fichier introuvable : $DUMP_FILE"
  exit 1
fi

TEST_DB="hayaflash_restore_test_$$"

cleanup() {
  echo "→ Suppression de la base ephemere ${TEST_DB}"
  $COMPOSE exec -T db psql -U "$DB_USER" -c "DROP DATABASE IF EXISTS \"${TEST_DB}\";" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "→ Creation de la base ephemere ${TEST_DB}"
$COMPOSE exec -T db psql -U "$DB_USER" -c "CREATE DATABASE \"${TEST_DB}\";"

echo "→ Restauration de $DUMP_FILE dans ${TEST_DB}"
gunzip -c "$DUMP_FILE" | $COMPOSE exec -T db psql -U "$DB_USER" -d "$TEST_DB" >/dev/null

echo "→ Verification : comptage des tables restaurees"
TABLE_COUNT="$($COMPOSE exec -T db psql -U "$DB_USER" -d "$TEST_DB" -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" | tr -d '[:space:]')"
echo "  ${TABLE_COUNT} tables restaurees"

if [ "$TABLE_COUNT" -lt 1 ]; then
  echo "✗ ECHEC : aucune table restauree"
  exit 1
fi

echo "✓ Restauration verifiee avec succes (${TABLE_COUNT} tables) — base ephemere sur le point d'etre supprimee"
