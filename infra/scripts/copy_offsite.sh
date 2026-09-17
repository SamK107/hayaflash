#!/bin/bash
# infra/scripts/copy_offsite.sh — copie les sauvegardes produites par backup.sh
# vers un support hors-site (disque externe branche sur le VPS, ou tout autre
# point de montage).
#
# Usage :
#   OFFSITE_DIR=/mnt/hf_backup_disk bash infra/scripts/copy_offsite.sh [SOURCE_DIR]
#
# Variables :
#   SOURCE_DIR             Dossier source (defaut : /srv/hayaflash/backups, ou 1er argument)
#   OFFSITE_DIR             Racine du support hors-site (obligatoire)
#   OFFSITE_RETENTION_DAYS Retention appliquee cote hors-site (defaut : 60,
#                           plus longue que la retention locale de backup.sh)
#
# Securite : refuse de copier si OFFSITE_DIR n'est pas un vrai point de montage
# du disque externe. Un dossier vide qui existe juste parce que le disque n'est
# pas branche est indiscernable d'un vrai montage pour `cp`/`rsync` -- ca
# copierait silencieusement sur le disque local du VPS en pensant sauvegarder
# hors-site. Protection : on exige un fichier temoin cree UNE FOIS a la racine
# du vrai disque externe (jamais recree automatiquement par ce script).
#
#   touch "$OFFSITE_DIR/.hayaflash_backup_target"
#
# Si ce fichier est absent, le script s'arrete sans rien copier.

set -euo pipefail

SOURCE_DIR="${1:-${SOURCE_DIR:-/srv/hayaflash/backups}}"
OFFSITE_RETENTION_DAYS="${OFFSITE_RETENTION_DAYS:-60}"

: "${OFFSITE_DIR:?OFFSITE_DIR requis (ex: OFFSITE_DIR=/mnt/hf_backup_disk)}"

MARKER="$OFFSITE_DIR/.hayaflash_backup_target"
if [ ! -f "$MARKER" ]; then
  echo "✗ Fichier temoin absent : $MARKER"
  echo "  Le disque externe ne semble pas branche/monte sur $OFFSITE_DIR,"
  echo "  ou le fichier temoin n'a jamais ete cree dessus. Pour l'autoriser"
  echo "  une fois le vrai disque confirme monte a cet endroit :"
  echo "    touch \"$MARKER\""
  exit 1
fi

if [ ! -d "$SOURCE_DIR" ]; then
  echo "✗ Dossier source introuvable : $SOURCE_DIR"
  exit 1
fi

echo "→ Copie de $SOURCE_DIR vers $OFFSITE_DIR"
COPIED=0
for f in "$SOURCE_DIR"/db_*.sql.gz "$SOURCE_DIR"/media_*.tar.gz; do
  [ -e "$f" ] || continue
  base="$(basename "$f")"
  dest="$OFFSITE_DIR/$base"
  if [ -f "$dest" ]; then
    continue
  fi
  cp "$f" "$dest"
  src_sum="$(sha256sum "$f" | cut -d' ' -f1)"
  dest_sum="$(sha256sum "$dest" | cut -d' ' -f1)"
  if [ "$src_sum" != "$dest_sum" ]; then
    echo "✗ Verification checksum echouee pour $base — copie corrompue, suppression"
    rm -f "$dest"
    exit 1
  fi
  echo "  $base copie et verifie (sha256 identique)"
  COPIED=$((COPIED+1))
done
echo "→ ${COPIED} fichier(s) copie(s)"

echo "→ Retention hors-site : suppression des copies de plus de ${OFFSITE_RETENTION_DAYS} jours"
find "$OFFSITE_DIR" -maxdepth 1 -name "db_*.sql.gz" -mtime "+${OFFSITE_RETENTION_DAYS}" -print -delete
find "$OFFSITE_DIR" -maxdepth 1 -name "media_*.tar.gz" -mtime "+${OFFSITE_RETENTION_DAYS}" -print -delete

echo "✓ Copie hors-site terminee : $OFFSITE_DIR"
