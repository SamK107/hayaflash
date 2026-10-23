#!/usr/bin/env bash
# infra/scripts/deploy_vps.sh — deploiement MANUEL OUTILLE d'une pile HayaFlash.
#
# Usage :
#   bash infra/scripts/deploy_vps.sh <dossier_pile> [--yes] [--dry-run]
#   ex. : bash infra/scripts/deploy_vps.sh /srv/hayaflash        # staging
#         bash infra/scripts/deploy_vps.sh /srv/hayaflash-prod   # production
#
# Quel script de deploiement utiliser ?
#   - CE script (deploy_vps.sh) : le deploiement reel d'aujourd'hui — image
#     construite SUR le VPS depuis le clone git, a la main, une pile a la fois.
#   - infra/scripts/deploy.sh   : ancien flux CI/CD par images GHCR (job GitHub
#     Actions `deploy-*`, aujourd'hui `if: false`). Ne pas l'utiliser a la main.
#
# Sequence :
#   1. check_stack_isolation.sh (stop si la pile partage quelque chose avec l'autre) ;
#   2. backup.sh, SEULEMENT si la pile a deja une base en service ;
#   3. git fetch + liste des commits et des changements sensibles (migrations,
#      .env.example, compose, Dockerfile, requirements, nginx), puis confirmation ;
#   4. tag de retour arriere <image>:previous sur l'image en cours ;
#   5. git checkout --detach origin/main, docker build, collectstatic (conteneur
#      jetable), up -d --no-deps web worker beat, migrate, puis nginx :
#        - si le compose, infra/nginx/* ou l'environnement de nginx ont change depuis
#          le dernier deploiement (ou si nginx est absent) : la nouvelle config est
#          d'abord validee dans un conteneur JETABLE (`compose run --rm nginx nginx -t`) ;
#          en cas d'echec rien n'est remplace ; sinon `up -d --no-deps --force-recreate nginx`
#          (un `restart` ne relit ni le compose ni l'environnement : incident du 18/10) ;
#        - sinon `nginx -t` puis `nginx -s reload` ;
#   6. /health/ avec X-Forwarded-Proto: https, plusieurs essais ;
#   7. affiche la commande EXACTE de retour arriere.
# Jamais de `down -v`, de `volume rm` ni de `prune`. Les migrations restent
# forward-only : le retour arriere d'image n'annule pas une migration.
#
# Options : --yes (pas de confirmation), --dry-run (affiche sans rien modifier),
#           --ref <ref> (defaut origin/main).

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_stack.sh
. "$SCRIPTS_DIR/lib_stack.sh"

ASSUME_YES=0; DRY_RUN=0; REF="origin/main"; STACK_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) ASSUME_YES=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --ref) shift; REF="${1:?--ref demande une valeur}" ;;
    -h|--help) sed -n '2,35p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) [ -z "$STACK_ARG" ] && STACK_ARG="$1" || hf_die "argument inattendu : $1" ;;
  esac
  shift
done

# Tout le travail est dans une fonction : bash lit un script au fur et a mesure,
# et `git checkout` (etape 5) peut remplacer CE fichier pendant son execution.
# Une fonction est analysee en entier avant d'etre lancee.
main() {
  hf_stack_init "$STACK_ARG"
  run() {  # execute, ou affiche en --dry-run
    if [ "$DRY_RUN" -eq 1 ]; then echo "[dry-run] $*"; else "$@"; fi
  }

  # ── 1. Isolation ──────────────────────────────────────────────────────────────
  echo "═══ 1/7 Isolation de la pile"
  bash "$SCRIPTS_DIR/check_stack_isolation.sh" "$STACK_DIR" || hf_die "isolation non garantie : deploiement interdit"
  hf_load_config
  PROJECT="$(hf_project_name)"
  PORT="$(hf_http_port)"
  IMAGE="$(hf_web_image)"
  IMAGE_REPO="${IMAGE%:*}"
  IMAGE_TAG="${IMAGE##*:}"

  # ── 2. Sauvegarde ─────────────────────────────────────────────────────────────
  echo "═══ 2/7 Sauvegarde avant changement"
  if hf_service_running db; then
    if [ "$DRY_RUN" -eq 1 ]; then
      bash "$SCRIPTS_DIR/backup.sh" "$STACK_DIR" --dry-run
    else
      bash "$SCRIPTS_DIR/backup.sh" "$STACK_DIR" || hf_die "sauvegarde echouee : deploiement annule (rien n'a ete modifie)"
    fi
  else
    echo "  Aucune base en service dans $PROJECT (premier deploiement ?) : sauvegarde sautee."
  fi

  # ── 3. Revue des changements ──────────────────────────────────────────────────
  echo "═══ 3/7 Changements a deployer"
  git -C "$STACK_DIR" diff --quiet HEAD -- 2>/dev/null \
    || hf_die "le clone $STACK_DIR a des modifications locales sur des fichiers suivis : les annuler ou les committer d'abord"
  run git -C "$STACK_DIR" fetch origin
  if ! git -C "$STACK_DIR" rev-parse --verify -q "$REF^{commit}" >/dev/null; then
    hf_die "reference introuvable : $REF (git fetch a-t-il reussi ?)"
  fi
  PREV_SHA="$(git -C "$STACK_DIR" rev-parse HEAD)"
  NEW_SHA="$(git -C "$STACK_DIR" rev-parse "$REF^{commit}")"
  echo "  Actuel  : $(git -C "$STACK_DIR" rev-parse --short "$PREV_SHA")"
  echo "  Cible   : $(git -C "$STACK_DIR" rev-parse --short "$NEW_SHA") ($REF)"
  if [ "$PREV_SHA" = "$NEW_SHA" ]; then
    echo "  Deja a jour : aucun commit nouveau (l'image sera simplement reconstruite)."
  else
    echo "  Commits :"
    git -C "$STACK_DIR" log --oneline --no-decorate "$PREV_SHA..$NEW_SHA" | sed 's/^/    /' || true
    SENSITIVE="$(git -C "$STACK_DIR" diff --name-only "$PREV_SHA" "$NEW_SHA" \
      | grep -E '(^|/)migrations/|^\.env\.example$|^docker-compose|^Dockerfile$|^requirements|^infra/' || true)"
    if [ -n "$SENSITIVE" ]; then
      echo "  ⚠ Changements sensibles :"
      printf '%s\n' "$SENSITIVE" | sed 's/^/    /'
    else
      echo "  Aucun changement sensible (migrations, .env.example, compose, Dockerfile, requirements, infra)."
    fi
  fi

  if [ "$ASSUME_YES" -ne 1 ] && [ "$DRY_RUN" -ne 1 ]; then
    [ -t 0 ] || hf_die "pas de terminal : relancer avec --yes pour automatiser"
    read -r -p "Deployer sur $PROJECT (port $PORT) ? [oui/NON] " ans
    [ "$ans" = "oui" ] || { echo "Abandon, rien n'a ete modifie."; exit 1; }
  fi

  # ── 4. Tag de retour arriere ──────────────────────────────────────────────────
  echo "═══ 4/7 Tag de retour arriere"
  if docker image inspect "$IMAGE" >/dev/null 2>&1; then
    run docker tag "$IMAGE" "$IMAGE_REPO:previous"
    echo "  $IMAGE → $IMAGE_REPO:previous"
  else
    echo "  Pas d'image $IMAGE existante (premier deploiement) : pas de tag :previous."
  fi

  # ── 5. Mise a jour ────────────────────────────────────────────────────────────
  echo "═══ 5/7 Construction et demarrage"
  run git -C "$STACK_DIR" checkout --detach "$NEW_SHA"
  SHORT="$(git -C "$STACK_DIR" rev-parse --short "$NEW_SHA")"
  run docker build -t "$IMAGE" -t "$IMAGE_REPO:$SHORT" "$STACK_DIR"
  run "${COMPOSE[@]}" up -d --wait db redis
  # Fichiers statiques AVANT de (re)demarrer web/worker/beat, dans un conteneur jetable de la
  # nouvelle image : chaque processus lit le manifeste (staticfiles.json) une seule fois. Le
  # 23/10, collectstatic tournait APRES le demarrage de web : les processus gardaient l'ancien
  # manifeste -> « Missing staticfiles manifest entry for 'js/hf-assist.js' » (500) jusqu'a un
  # redemarrage manuel de web.
  run "${COMPOSE[@]}" run --rm --no-deps -T web python manage.py collectstatic --noinput
  run "${COMPOSE[@]}" up -d --no-deps web worker beat
  # Attendre que web accepte les commandes.
  if [ "$DRY_RUN" -eq 0 ]; then
    for _ in $(seq 1 30); do hf_service_running web && break; sleep 2; done
    hf_service_running web || hf_die "web ne demarre pas : docker compose logs web"
  fi
  run "${COMPOSE[@]}" exec -T web python manage.py migrate --noinput
  # nginx. Un `restart` ne relit NI le compose NI l'environnement du conteneur : le 18/10 a
  # 12:57, la nouvelle variable HF_REAL_IP_FROM n'a pas ete prise en compte, nginx a tourne
  # en boucle (emerg set_real_ip_from) et /health/ a echoue jusqu'a un --force-recreate
  # manuel. Regle : empreinte (compose + env de nginx + infra/nginx/*) differente de celle du
  # dernier deploiement, ou nginx absent -> validation en conteneur jetable PUIS recreation ;
  # sinon nginx -t + reload (suffit pour une nouvelle IP de web : resolution dynamique).
  FP_FILE="$STACK_DIR/.hf_nginx_fingerprint"
  NEW_FP="$(hf_nginx_fingerprint)"
  OLD_FP="$(cat "$FP_FILE" 2>/dev/null || true)"
  RECREATE_NGINX=0
  if [ -z "$OLD_FP" ] || [ "$OLD_FP" != "$NEW_FP" ]; then RECREATE_NGINX=1; fi
  if [ "$DRY_RUN" -eq 0 ] && ! hf_service_running nginx; then RECREATE_NGINX=1; fi
  if [ "$DRY_RUN" -eq 1 ]; then
    if [ "$RECREATE_NGINX" -eq 1 ]; then
      echo "[dry-run] nginx : configuration changee (ou premiere fois) -> validation en conteneur jetable"
      echo "[dry-run]         (${COMPOSE[*]} run --rm --no-deps -T nginx nginx -t),"
      echo "[dry-run]         puis ${COMPOSE[*]} up -d --no-deps --force-recreate nginx"
    else
      echo "[dry-run] nginx : configuration inchangee -> exec nginx -t && exec nginx -s reload"
    fi
  elif [ "$RECREATE_NGINX" -eq 1 ]; then
    echo "  nginx : configuration changee (ou conteneur absent) : validation avant remplacement."
    hf_nginx_validate_disposable       || hf_die "nginx -t echoue dans un conteneur jetable : le nginx en service n'a PAS ete remplace. Corriger compose / infra/nginx / .env puis relancer."
    "${COMPOSE[@]}" up -d --no-deps --force-recreate nginx
    for _ in $(seq 1 15); do hf_service_running nginx && break; sleep 2; done
    hf_service_running nginx || hf_die "nginx ne demarre pas apres recreation : docker compose logs nginx"
    sleep 3   # une boucle de redemarrage (emerg) ne reste pas « running » plus de quelques secondes
    hf_service_running nginx || hf_die "nginx redemarre en boucle apres recreation : docker compose logs nginx"
    "${COMPOSE[@]}" exec -T nginx nginx -t       || hf_die "nginx -t a echoue apres recreation : docker compose logs nginx"
    echo "$NEW_FP" > "$FP_FILE"
  else
    "${COMPOSE[@]}" exec -T nginx nginx -t       || hf_die "nginx -t a echoue : nginx NON recharge. Corriger la config puis relancer (journaux : docker compose logs nginx)"
    "${COMPOSE[@]}" exec -T nginx nginx -s reload       || hf_die "nginx -s reload a echoue : docker compose logs nginx"
  fi

  # ── 6. Verification ───────────────────────────────────────────────────────────
  echo "═══ 6/7 Verification de /health/"
  DOMAIN="$(hf_env_get PROD_DOMAIN)"
  [ -n "$DOMAIN" ] || DOMAIN="$(hf_env_get ALLOWED_HOSTS | cut -d, -f1)"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] curl -H 'Host: $DOMAIN' -H 'X-Forwarded-Proto: https' http://127.0.0.1:$PORT/health/"
  else
    OK=0
    for i in $(seq 1 12); do
      if curl -sf -m 10 -H "Host: $DOMAIN" -H 'X-Forwarded-Proto: https' "http://127.0.0.1:$PORT/health/" >/dev/null; then OK=1; break; fi
      echo "  essai $i/12 : pas encore pret"; sleep 5
    done
    if [ "$OK" -ne 1 ]; then
      echo "✗ /health/ ne repond pas apres 12 essais (http://127.0.0.1:$PORT, Host: $DOMAIN)." >&2
      echo "  Journaux : ${COMPOSE[*]} logs --tail=100 web nginx" >&2
      echo "  Retour arriere : voir la commande ci-dessous." >&2
    fi
  fi

  # ── 7. Retour arriere ─────────────────────────────────────────────────────────
  echo "═══ 7/7 Retour arriere (si besoin)"
  cat <<EOF
    cd $STACK_DIR \\
      && git checkout --detach $PREV_SHA \\
      && docker tag $IMAGE_REPO:previous $IMAGE \\
      && ${COMPOSE[*]} up -d --no-deps web worker beat \\
      && ${COMPOSE[*]} run --rm --no-deps -T nginx nginx -t \\
      && ${COMPOSE[*]} up -d --no-deps --force-recreate nginx \\
      && ${COMPOSE[*]} exec -T nginx nginx -t
    (les migrations appliquees ne sont PAS annulees ; pour la base : restore.sh, apres avis)
EOF

  if [ "$DRY_RUN" -eq 0 ] && [ "${OK:-0}" -ne 1 ]; then exit 1; fi
  echo "✓ Deploiement termine : $PROJECT @ $SHORT"
}

main
exit $?
