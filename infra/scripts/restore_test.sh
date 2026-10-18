#!/usr/bin/env bash
# infra/scripts/restore_test.sh — prouve qu'une sauvegarde est RESTAURABLE.
#
# Usage :
#   bash infra/scripts/restore_test.sh /srv/backups/hayaflash-prod/2026-10-18_0317
#
# Ce que fait le script (aucune pile reelle n'est touchee) :
#   1. verifie les empreintes SHA256SUMS ;
#   2. demarre un conteneur PostgreSQL TEMPORAIRE et isole : nom unique, --network
#      none (aucun reseau, donc aucun lien avec la base de staging ou de prod),
#      donnees en tmpfs (aucun volume, nomme ou non) ;
#   3. y restaure db.dump (pg_restore) et compte les lignes de tables cles
#      (utilisateurs, vendeurs, ventes, commandes) ;
#   4. verifie l'integrite de media.tar.gz (gzip + lecture de l'archive) ;
#   5. supprime le conteneur (meme en cas d'echec) et affiche « RESTAURATION OK ».
# Code de sortie != 0 au moindre probleme. Aucun secret affiche : le mot de passe
# du conteneur jetable est genere au hasard et n'existe que le temps du test.
#
# Variable : RESTORE_TEST_IMAGE (defaut postgres:16-alpine = meme version que la pile).

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_stack.sh
. "$SCRIPTS_DIR/lib_stack.sh"

BACKUP_DIR="${1:-}"
[ -n "$BACKUP_DIR" ] || hf_die "usage : restore_test.sh <dossier_sauvegarde>"
[ -d "$BACKUP_DIR" ] || hf_die "dossier introuvable : $BACKUP_DIR"
BACKUP_DIR="$(cd "$BACKUP_DIR" && pwd)"
IMAGE="${RESTORE_TEST_IMAGE:-postgres:16-alpine}"
for f in db.dump media.tar.gz SHA256SUMS; do
  [ -s "$BACKUP_DIR/$f" ] || hf_die "fichier manquant ou vide : $BACKUP_DIR/$f"
done

echo "→ Verification des empreintes"
(cd "$BACKUP_DIR" && sha256sum -c --quiet SHA256SUMS) || hf_die "SHA256SUMS : empreintes invalides"

NAME="hf-restore-test-$(date -u +%Y%m%d%H%M%S)-$$"
TEST_DB="restore_check"
PGPASS="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)"
cleanup() {
  echo "→ Suppression du conteneur temporaire $NAME"
  docker rm -f "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "→ Demarrage de PostgreSQL temporaire ($IMAGE, sans reseau, donnees en memoire)"
docker run -d --name "$NAME" --network none \
  --tmpfs /var/lib/postgresql/data:rw \
  -e POSTGRES_PASSWORD="$PGPASS" "$IMAGE" >/dev/null

# 127.0.0.1 : pendant l'initialisation le serveur n'ecoute que sur la socket ;
# seul le serveur definitif ecoute en TCP local.
ready=0
for _ in $(seq 1 60); do
  if docker exec "$NAME" pg_isready -q -h 127.0.0.1 -U postgres 2>/dev/null; then ready=1; break; fi
  sleep 2
done
[ "$ready" -eq 1 ] || hf_die "PostgreSQL temporaire n'a pas demarre"

docker exec "$NAME" createdb -U postgres "$TEST_DB"

echo "→ Restauration de db.dump"
# --no-owner/--no-privileges : les roles de la pile d'origine n'existent pas ici.
docker exec -i "$NAME" pg_restore -U postgres -d "$TEST_DB" --no-owner --no-privileges --exit-on-error \
  < "$BACKUP_DIR/db.dump" || hf_die "pg_restore a echoue"

count() {  # count <table> : nombre de lignes, echec si la table n'existe pas
  docker exec "$NAME" psql -U postgres -d "$TEST_DB" -At -c "SELECT count(*) FROM $1" 2>/dev/null \
    || hf_die "table absente apres restauration : $1"
}
echo "→ Lignes dans les tables cles"
for t in accounts_user accounts_sellerprofile flash_sales_flashsale orders_order; do
  printf '  %-26s %s\n' "$t" "$(count "$t")"
done
TABLES="$(docker exec "$NAME" psql -U postgres -d "$TEST_DB" -At -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
echo "  tables (schema public)     $TABLES"
[ "$TABLES" -gt 10 ] || hf_die "trop peu de tables restaurees ($TABLES)"

echo "→ Integrite de l'archive des medias"
gzip -t "$BACKUP_DIR/media.tar.gz" || hf_die "media.tar.gz : gzip invalide"
N_FILES="$(tar tzf "$BACKUP_DIR/media.tar.gz" | wc -l)"
echo "  $N_FILES entrees dans l'archive"

echo
echo "RESTAURATION OK"
