#!/usr/bin/env bash
# infra/scripts/backup.sh — sauvegarde d'UNE pile HayaFlash (base + medias).
#
# Usage :
#   bash infra/scripts/backup.sh <dossier_pile> [--dry-run]
#   ex. : bash infra/scripts/backup.sh /srv/hayaflash-prod
#
# Produit /srv/backups/<projet>/AAAA-MM-JJ_HHMM/ (heure UTC) contenant :
#   db.dump          pg_dump -Fc (format personnalise, restaurable avec pg_restore)
#   media.tar.gz     archive du dossier media (images produits, avatars...)
#   backup.info      projet, date, commit git, tailles (aucun secret)
#   SHA256SUMS       empreintes des trois fichiers
# Droits : dossiers 700, fichiers 600. Ecriture ATOMIQUE : tout est ecrit dans un
# dossier temporaire « .tmp-... » renomme a la toute fin ; une sauvegarde
# incomplete n'est donc jamais visible sous son nom definitif.
#
# Identifiants : lus dans l'environnement du CONTENEUR db (POSTGRES_USER /
# POSTGRES_DB), jamais affiches ; la connexion se fait par la socket locale du
# conteneur (pas de mot de passe sur la ligne de commande).
#
# Retention (par defaut, configurable) :
#   BACKUP_KEEP_DAILY=14   la derniere sauvegarde de chacun des 14 derniers jours
#   BACKUP_KEEP_WEEKLY=8   la derniere sauvegarde de chacun des 8 derniers dimanches
# Seuls les dossiers au nom AAAA-MM-JJ_HHMM contenant SHA256SUMS sont candidats a
# la suppression, et jamais la sauvegarde la plus recente. Echec de la sauvegarde
# => aucune purge.
#
# Copie hors du VPS : BACKUP_REMOTE (ex. « remote:hayaflash-backups ») active une
# copie rclone. Vide = avertissement visible « sauvegarde locale uniquement ».
# (Le porteur du projet tire aussi les sauvegardes vers son PC : voir
# infra/scripts/windows/pull_backups.ps1 et docs/SAUVEGARDES.md.)
#
# Variables optionnelles (environnement ou .env de la pile) :
#   BACKUP_ROOT (defaut /srv/backups/<projet>), BACKUP_KEEP_DAILY, BACKUP_KEEP_WEEKLY,
#   BACKUP_REMOTE.
#
# Prerequis : le dossier parent doit exister et appartenir a l'utilisateur qui
# lance le script (une fois : sudo install -d -o sam -m 700 /srv/backups).
# Code de sortie : 0 = succes ; != 0 = echec (une ligne FAIL est ecrite dans backup.log).

set -euo pipefail
umask 077

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_stack.sh
. "$SCRIPTS_DIR/lib_stack.sh"

DRY_RUN=0
STACK_ARG=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,38p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) [ -z "$STACK_ARG" ] && STACK_ARG="$arg" || hf_die "argument inattendu : $arg" ;;
  esac
done

hf_stack_init "$STACK_ARG"
hf_load_config
PROJECT="$(hf_project_name)"
[ -n "$PROJECT" ] || hf_die "nom de projet Compose introuvable"

BACKUP_ROOT="$(hf_cfg BACKUP_ROOT "/srv/backups/$PROJECT")"
KEEP_DAILY="$(hf_cfg BACKUP_KEEP_DAILY 14)"
KEEP_WEEKLY="$(hf_cfg BACKUP_KEEP_WEEKLY 8)"
REMOTE="$(hf_cfg BACKUP_REMOTE "")"
case "$KEEP_DAILY$KEEP_WEEKLY" in *[!0-9]*|"") hf_die "BACKUP_KEEP_DAILY / BACKUP_KEEP_WEEKLY doivent etre des entiers" ;; esac

STAMP="$(date -u +%Y-%m-%d_%H%M)"
FINAL_DIR="$BACKUP_ROOT/$STAMP"
TMP_DIR="$BACKUP_ROOT/.tmp-$STAMP-$$"
LOG_FILE="$BACKUP_ROOT/backup.log"

log_line() {  # ligne horodatee dans backup.log (si possible) et a l'ecran
  local msg
  msg="$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
  echo "$msg"
  if [ "$DRY_RUN" -eq 0 ] && [ -d "$BACKUP_ROOT" ]; then echo "$msg" >> "$LOG_FILE" || true; fi
}

on_exit() {
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    [ -d "$TMP_DIR" ] && rm -rf "$TMP_DIR"
    log_line "FAIL backup projet=$PROJECT stamp=$STAMP code=$rc"
  fi
}
trap on_exit EXIT

echo "Projet      : $PROJECT"
echo "Destination : $FINAL_DIR"
echo "Retention   : $KEEP_DAILY quotidiennes + $KEEP_WEEKLY hebdomadaires (dimanche)"
[ "$DRY_RUN" -eq 1 ] && echo "MODE --dry-run : rien ne sera ecrit ni supprime."

hf_service_running db || hf_die "le service db ne tourne pas (pile $PROJECT) : rien a sauvegarder"

if [ "$DRY_RUN" -eq 0 ]; then
  [ -d "$(dirname "$BACKUP_ROOT")" ] || hf_die "$(dirname "$BACKUP_ROOT") absent : sudo install -d -o $(id -un) -m 700 $(dirname "$BACKUP_ROOT")"
  mkdir -p "$BACKUP_ROOT"; chmod 700 "$BACKUP_ROOT"
  mkdir "$TMP_DIR"; chmod 700 "$TMP_DIR"

  echo "→ Base de donnees (pg_dump -Fc)"
  "${COMPOSE[@]}" exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$TMP_DIR/db.dump"
  [ -s "$TMP_DIR/db.dump" ] || hf_die "db.dump vide"
  # Lecture de la table des matieres : detecte une archive tronquee ou corrompue.
  "${COMPOSE[@]}" exec -T db pg_restore -l < "$TMP_DIR/db.dump" > /dev/null \
    || hf_die "db.dump illisible par pg_restore"

  echo "→ Medias (/app/media)"
  hf_service_running web || hf_die "le service web ne tourne pas : medias inaccessibles"
  "${COMPOSE[@]}" exec -T web tar czf - -C /app media > "$TMP_DIR/media.tar.gz"
  gzip -t "$TMP_DIR/media.tar.gz" || hf_die "media.tar.gz corrompue"
  tar tzf "$TMP_DIR/media.tar.gz" > /dev/null || hf_die "media.tar.gz illisible"

  {
    echo "project=$PROJECT"
    echo "stamp_utc=$STAMP"
    echo "git_commit=$(git -C "$STACK_DIR" rev-parse --short HEAD 2>/dev/null || echo inconnu)"
    echo "db_dump_bytes=$(stat -c %s "$TMP_DIR/db.dump")"
    echo "media_bytes=$(stat -c %s "$TMP_DIR/media.tar.gz")"
  } > "$TMP_DIR/backup.info"

  (cd "$TMP_DIR" && sha256sum db.dump media.tar.gz backup.info > SHA256SUMS && sha256sum -c --quiet SHA256SUMS)
  chmod 600 "$TMP_DIR"/*
  [ ! -e "$FINAL_DIR" ] || hf_die "$FINAL_DIR existe deja (deux sauvegardes dans la meme minute ?)"
  mv "$TMP_DIR" "$FINAL_DIR"
  echo "  $(du -h "$FINAL_DIR/db.dump" | cut -f1) base, $(du -h "$FINAL_DIR/media.tar.gz" | cut -f1) medias"
else
  echo "[dry-run] pg_dump -Fc -> $TMP_DIR/db.dump ; tar medias -> $TMP_DIR/media.tar.gz ; SHA256SUMS ; mv -> $FINAL_DIR"
fi

# ── Retention ─────────────────────────────────────────────────────────────────
# On calcule l'ensemble a CONSERVER, tout le reste (dossiers conformes) est supprime.
purge_old() {
  local d name day n_daily=0 n_weekly=0 last_day="" dow
  local -a keep=() all=()
  if [ -d "$BACKUP_ROOT" ]; then mapfile -t all < <(
    find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -regextype posix-extended \
      -regex '.*/[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{4}' -printf '%f\n' | sort -r
  ); fi
  # Le dossier qu'on vient de creer compte meme en dry-run.
  if [ "$DRY_RUN" -eq 1 ]; then all=("$STAMP" "${all[@]}"); fi
  local newest="${all[0]:-}"
  declare -A kept=()
  [ -n "$newest" ] && kept["$newest"]=1
  local seen_days="" seen_sundays=""
  for name in "${all[@]}"; do   # ordre decroissant : la plus recente d'abord
    day="${name%%_*}"
    case " $seen_days " in *" $day "*) ;; *)
      if [ "$n_daily" -lt "$KEEP_DAILY" ]; then kept["$name"]=1; fi
      seen_days="$seen_days $day"; n_daily=$((n_daily + 1)) ;;
    esac
    dow="$(date -u -d "$day" +%u)"
    if [ "$dow" = "7" ]; then
      case " $seen_sundays " in *" $day "*) ;; *)
        if [ "$n_weekly" -lt "$KEEP_WEEKLY" ]; then kept["$name"]=1; fi
        seen_sundays="$seen_sundays $day"; n_weekly=$((n_weekly + 1)) ;;
      esac
    fi
  done
  local removed=0
  for name in "${all[@]}"; do
    [ -z "${kept[$name]:-}" ] || continue
    d="$BACKUP_ROOT/$name"
    [ -f "$d/SHA256SUMS" ] || { hf_warn "retention : $d sans SHA256SUMS, ignore"; continue; }
    if [ "$DRY_RUN" -eq 1 ]; then echo "[dry-run] supprimerait $d"; else rm -rf -- "$d"; echo "  retention : supprime $name"; fi
    removed=$((removed + 1))
  done
  echo "→ Retention : $removed ancienne(s) sauvegarde(s) hors politique"
}
purge_old

# ── Copie hors du VPS (optionnelle) ───────────────────────────────────────────
OFFSITE_STATUS="locale-seulement"
if [ -n "$REMOTE" ]; then
  echo "→ Copie hors VPS (rclone → $REMOTE)"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] rclone copy $FINAL_DIR $REMOTE/$PROJECT/$STAMP"
  else
    command -v rclone >/dev/null 2>&1 || hf_die "BACKUP_REMOTE defini mais rclone n'est pas installe"
    rclone copy "$FINAL_DIR" "$REMOTE/$PROJECT/$STAMP" --checksum || hf_die "copie rclone echouee (la sauvegarde locale est intacte)"
    OFFSITE_STATUS="rclone"
  fi
else
  hf_warn "BACKUP_REMOTE vide : sauvegarde locale uniquement — non protégée contre la perte du VPS."
fi

if [ "$DRY_RUN" -eq 0 ]; then
  log_line "OK backup projet=$PROJECT stamp=$STAMP offsite=$OFFSITE_STATUS"
fi
echo "✓ Sauvegarde terminee : $FINAL_DIR"
