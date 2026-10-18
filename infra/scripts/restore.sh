#!/usr/bin/env bash
# infra/scripts/restore.sh — VRAIE restauration d'une sauvegarde dans une pile.
#
# ⚠ OPERATION DESTRUCTIVE : la base de la pile designee est ECRASEE par le
# contenu de la sauvegarde (les donnees posterieures sont perdues) et les medias
# sont reecrits par-dessus. A n'utiliser qu'en cas de sinistre, apres avoir
# valide la sauvegarde avec restore_test.sh.
#
# Usage :
#   bash infra/scripts/restore.sh <dossier_pile> <dossier_sauvegarde> [--dry-run] [--allow-other-project]
#   ex. : bash infra/scripts/restore.sh /srv/hayaflash-prod /srv/backups/hayaflash-prod/2026-10-18_0317
#
# Garde-fous :
#   - uniquement vers la pile designee ; refuse une sauvegarde d'un AUTRE projet
#     (backup.info) sauf --allow-other-project (ex. copie prod → staging pour test) ;
#   - verification des SHA256SUMS ;
#   - sauvegarde automatique prealable de l'etat courant (backup.sh) ;
#   - DOUBLE confirmation au clavier (nom du projet, puis le mot RESTAURER) ;
#     refuse de tourner sans terminal interactif ;
#   - jamais de « down -v », de suppression de volume ni de DROP DATABASE : la
#     base est rejouee avec « pg_restore --clean --if-exists » web/worker/beat arretes.
# Apres : redemarre web, worker, beat et verifie /health/.

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_stack.sh
. "$SCRIPTS_DIR/lib_stack.sh"

DRY_RUN=0; ALLOW_OTHER=0; POS=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --allow-other-project) ALLOW_OTHER=1 ;;
    -h|--help) sed -n '2,24p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) POS+=("$arg") ;;
  esac
done
[ "${#POS[@]}" -eq 2 ] || hf_die "usage : restore.sh <dossier_pile> <dossier_sauvegarde> [--dry-run] [--allow-other-project]"

hf_stack_init "${POS[0]}"
hf_load_config
PROJECT="$(hf_project_name)"
BACKUP_DIR="${POS[1]}"
[ -d "$BACKUP_DIR" ] || hf_die "sauvegarde introuvable : $BACKUP_DIR"
BACKUP_DIR="$(cd "$BACKUP_DIR" && pwd)"
for f in db.dump media.tar.gz SHA256SUMS backup.info; do
  [ -s "$BACKUP_DIR/$f" ] || hf_die "fichier manquant ou vide : $BACKUP_DIR/$f"
done

BACKUP_PROJECT="$(sed -n 's/^project=//p' "$BACKUP_DIR/backup.info" | head -n 1)"
echo "Pile cible        : $STACK_DIR (projet $PROJECT)"
echo "Sauvegarde        : $BACKUP_DIR (projet d'origine : ${BACKUP_PROJECT:-inconnu})"
if [ "$BACKUP_PROJECT" != "$PROJECT" ] && [ "$ALLOW_OTHER" -eq 0 ]; then
  hf_die "la sauvegarde vient du projet « ${BACKUP_PROJECT:-inconnu} », la cible est « $PROJECT » : refuse (ajouter --allow-other-project si c'est voulu)"
fi

echo "→ Verification des empreintes"
(cd "$BACKUP_DIR" && sha256sum -c --quiet SHA256SUMS) || hf_die "SHA256SUMS : empreintes invalides"

if [ "$DRY_RUN" -eq 1 ]; then
  cat <<EOF
[dry-run] Etapes qui seraient jouees sur $PROJECT :
  1. sauvegarde prealable : backup.sh $STACK_DIR
  2. confirmations (nom du projet, puis RESTAURER)
  3. docker compose stop web worker beat
  4. pg_restore --clean --if-exists --no-owner de db.dump dans la base du conteneur db
  5. extraction de media.tar.gz dans /app/media (volume media_data)
  6. docker compose up -d --no-deps web worker beat
EOF
  exit 0
fi

[ -t 0 ] || hf_die "terminal interactif requis (double confirmation)"
echo
echo "⚠ La base de « $PROJECT » va etre ECRASEE par cette sauvegarde."
read -r -p "Confirmation 1/2 — tapez le nom du projet cible ($PROJECT) : " ans1
[ "$ans1" = "$PROJECT" ] || hf_die "confirmation 1 incorrecte, abandon (rien n'a ete modifie)"
read -r -p "Confirmation 2/2 — tapez RESTAURER en majuscules : " ans2
[ "$ans2" = "RESTAURER" ] || hf_die "confirmation 2 incorrecte, abandon (rien n'a ete modifie)"

echo "→ Sauvegarde prealable de l'etat courant"
bash "$SCRIPTS_DIR/backup.sh" "$STACK_DIR" || hf_die "sauvegarde prealable echouee : restauration annulee"

echo "→ Arret de web, worker, beat"
"${COMPOSE[@]}" stop web worker beat

echo "→ Restauration de la base"
"${COMPOSE[@]}" exec -T db sh -c \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges' \
  < "$BACKUP_DIR/db.dump" \
  || hf_warn "pg_restore a signale des erreurs (souvent benignes avec --clean) : verifier la suite"

echo "→ Restauration des medias"
"${COMPOSE[@]}" run --rm --no-deps -T web tar xzf - -C /app < "$BACKUP_DIR/media.tar.gz"

echo "→ Redemarrage"
"${COMPOSE[@]}" up -d --no-deps web worker beat

echo "✓ Restauration terminee. Verifier /health/ et l'application, puis (si web a change d'IP) :"
echo "  ${COMPOSE[*]} restart nginx"
