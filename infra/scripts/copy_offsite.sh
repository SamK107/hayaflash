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
#   AGE_RECIPIENTS_FILE    Fichier de cles PUBLIQUES age (obligatoire, defaut :
#                           /srv/hayaflash/backup_recipients.txt)
#
# Chiffrement (ADR-0001, decision 2 -- non negociable) : tout ce qui est ecrit
# sur le disque externe est chiffre avec age (https://age-encryption.org) AVANT
# ecriture. Chiffrement asymetrique : seule la cle PUBLIQUE (age1...) reside sur
# le VPS ; la cle privee (AGE-SECRET-KEY-...) reste dans le gestionnaire de mots
# de passe, jamais sur le VPS ni sur le disque. Une passphrase symetrique aurait
# du etre stockee sur le VPS pour que le cron tourne sans interaction -- c'est
# precisement ce que l'ADR interdit.
#
#   Generer la paire (sur TON poste, pas sur le VPS) :
#     age-keygen -o hayaflash-backup.key      # -> garder dans le gestionnaire
#     age-keygen -y hayaflash-backup.key      # -> cle publique a copier sur le VPS
#   Dechiffrer une sauvegarde pour la restaurer :
#     age -d -i hayaflash-backup.key db_XXXX.sql.gz.age > db_XXXX.sql.gz
#
# Aucun fichier en clair n'est jamais ecrit sur le disque externe : age ecrit
# dans un .partial, on controle l'en-tete age et la taille (pas de round-trip
# possible sans cle privee, c'est voulu), puis rename. Le sha256 du clair est
# garde a cote (.src.sha256) pour verifier une restauration apres dechiffrement.
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
AGE_RECIPIENTS_FILE="${AGE_RECIPIENTS_FILE:-/srv/hayaflash/backup_recipients.txt}"
AGE_BIN="${AGE_BIN:-age}"

if ! command -v "$AGE_BIN" >/dev/null 2>&1; then
  echo "✗ age introuvable ($AGE_BIN) -- installer age (apt install age) avant toute copie hors-site."
  echo "  Refus de copier en clair (ADR-0001, decision 2)."
  exit 1
fi
if [ ! -s "$AGE_RECIPIENTS_FILE" ]; then
  echo "✗ Fichier de cles publiques age absent ou vide : $AGE_RECIPIENTS_FILE"
  echo "  Refus de copier en clair (ADR-0001, decision 2)."
  exit 1
fi
if grep -q "AGE-SECRET-KEY" "$AGE_RECIPIENTS_FILE"; then
  echo "✗ $AGE_RECIPIENTS_FILE contient une cle PRIVEE age. Seule la cle publique"
  echo "  (age1...) doit etre sur le VPS -- retirer ce fichier et le regenerer avec age-keygen -y."
  exit 1
fi

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

echo "→ Copie chiffree (age) de $SOURCE_DIR vers $OFFSITE_DIR"
COPIED=0
for f in "$SOURCE_DIR"/db_*.sql.gz "$SOURCE_DIR"/media_*.tar.gz; do
  [ -e "$f" ] || continue
  base="$(basename "$f")"
  dest="$OFFSITE_DIR/$base.age"
  if [ -f "$dest" ]; then
    continue
  fi
  tmp="$dest.partial"
  rm -f "$tmp"
  if ! "$AGE_BIN" -R "$AGE_RECIPIENTS_FILE" -o "$tmp" "$f"; then
    echo "✗ Chiffrement age echoue pour $base"
    rm -f "$tmp"
    exit 1
  fi
  # Sans la cle privee on ne peut pas dechiffrer pour comparer : on verifie que
  # la sortie est un fichier age bien forme (en-tete) et non tronque (taille
  # >= source, age n'ecrit jamais moins que le clair).
  if ! head -c 64 "$tmp" | grep -q "age-encryption.org/v1"; then
    echo "✗ Sortie age invalide pour $base -- suppression"
    rm -f "$tmp"
    exit 1
  fi
  if [ "$(stat -c %s "$tmp")" -lt "$(stat -c %s "$f")" ]; then
    echo "✗ Fichier chiffre plus petit que la source pour $base (tronque ?) -- suppression"
    rm -f "$tmp"
    exit 1
  fi
  mv "$tmp" "$dest"
  sha256sum "$f" | cut -d' ' -f1 > "$dest.src.sha256"
  echo "  $base chiffre -> $(basename "$dest")"
  COPIED=$((COPIED+1))
done
# .partial orphelins (coupure pendant une copie precedente)
find "$OFFSITE_DIR" -maxdepth 1 -name "*.partial" -print -delete
echo "→ ${COPIED} fichier(s) copie(s)"

echo "→ Retention hors-site : suppression des copies de plus de ${OFFSITE_RETENTION_DAYS} jours"
find "$OFFSITE_DIR" -maxdepth 1 -name "db_*.sql.gz.age*" -mtime "+${OFFSITE_RETENTION_DAYS}" -print -delete
find "$OFFSITE_DIR" -maxdepth 1 -name "media_*.tar.gz.age*" -mtime "+${OFFSITE_RETENTION_DAYS}" -print -delete

echo "✓ Copie hors-site terminee : $OFFSITE_DIR"
