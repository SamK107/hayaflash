#!/usr/bin/env bash
# infra/scripts/check_stack_isolation.sh — verifie qu'une pile (staging ou prod)
# ne partage RIEN avec l'autre : projet Compose, port, image, volumes, reseau,
# .env. Lecture seule (aucune modification, aucun conteneur touche).
#
# Usage :
#   bash infra/scripts/check_stack_isolation.sh /srv/hayaflash        # staging
#   bash infra/scripts/check_stack_isolation.sh /srv/hayaflash-prod   # prod
#
# Regle : un dossier dont le nom contient « prod » est une pile de production.
#   - prod    : projet, image, volumes et reseau doivent contenir « prod » ; le
#               projet ne doit pas etre « hayaflash », le port pas 8020, l'image
#               pas « hayaflash:latest » ; HAYAFLASH_ALLOW_DEMO_SEED interdit.
#   - staging : rien de tout cela ne doit contenir « prod » ni viser 8021.
# Code de sortie : 0 = isole, 1 = au moins une violation (listee).

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_stack.sh
. "$SCRIPTS_DIR/lib_stack.sh"

hf_stack_init "${1:-}"
hf_load_config

PROJECT="$(hf_project_name)"
PORT="$(hf_http_port)"
IMAGE="$(hf_web_image)"
VOLUMES="$(hf_volume_names | tr '\n' ' ')"
NETWORKS="$(hf_network_names | tr '\n' ' ')"

echo "Pile        : $STACK_DIR"
echo "Projet      : $PROJECT"
echo "Port hote   : 127.0.0.1:$PORT"
echo "Image (web) : $IMAGE"
echo ".env        : $ENV_FILE"
echo "Volumes     : $VOLUMES"
echo "Reseau      : $NETWORKS"

ERRORS=0
fail() { printf '✗ %s\n' "$*" >&2; ERRORS=$((ERRORS + 1)); }

[ -n "$PROJECT" ] && [ -n "$PORT" ] && [ -n "$IMAGE" ] || fail "config incomplete (projet/port/image non resolus)"
[ -n "$VOLUMES" ] || fail "aucun volume resolu"
[ -n "$NETWORKS" ] || fail "aucun reseau resolu"

# Le compose ne doit plus contenir de chemin /srv/... en dur (env_file relatif).
if grep -nE '^[^#]*/srv/hayaflash' "$STACK_DIR/docker-compose.production.yml" >/dev/null; then
  fail "docker-compose.production.yml contient un chemin /srv/hayaflash en dur (env_file doit etre relatif)"
fi

if hf_is_prod_dir; then
  echo "Role        : PRODUCTION"
  [ "$PROJECT" != "hayaflash" ] || fail "prod : le projet resout « hayaflash » (celui du staging) — poser HAYAFLASH_PROJECT=hayaflash-prod dans $ENV_FILE"
  case "$PROJECT" in *prod*) ;; *) fail "prod : le projet « $PROJECT » ne contient pas « prod »" ;; esac
  [ "$PORT" != "8020" ] || fail "prod : le port resout 8020 (celui du staging) — poser HAYAFLASH_HTTP_PORT=8021"
  [ "$IMAGE" != "hayaflash:latest" ] || fail "prod : l'image resout hayaflash:latest (celle du staging) — poser DOCKER_IMAGE=hayaflash-prod"
  case "$IMAGE" in *prod*) ;; *) fail "prod : l'image « $IMAGE » ne contient pas « prod »" ;; esac
  for v in $VOLUMES; do case "$v" in *prod*) ;; *) fail "prod : le volume « $v » ne contient pas « prod »" ;; esac; done
  for n in $NETWORKS; do case "$n" in *prod*) ;; *) fail "prod : le reseau « $n » ne contient pas « prod »" ;; esac; done
  if [ "$(hf_env_get HAYAFLASH_ALLOW_DEMO_SEED)" = "1" ]; then
    fail "prod : HAYAFLASH_ALLOW_DEMO_SEED=1 dans $ENV_FILE (variable de demo interdite en production)"
  fi
else
  echo "Role        : STAGING"
  case "$PROJECT" in *prod*) fail "staging : le projet « $PROJECT » pointe vers une ressource prod" ;; esac
  [ "$PORT" != "8021" ] || fail "staging : le port resout 8021 (celui de la prod)"
  case "$IMAGE" in *prod*) fail "staging : l'image « $IMAGE » pointe vers une ressource prod" ;; esac
  for v in $VOLUMES; do case "$v" in *prod*) fail "staging : le volume « $v » pointe vers une ressource prod" ;; esac; done
  for n in $NETWORKS; do case "$n" in *prod*) fail "staging : le reseau « $n » pointe vers une ressource prod" ;; esac; done
fi

if [ "$ERRORS" -gt 0 ]; then
  printf '\n✗ ISOLATION NON GARANTIE : %d violation(s).\n' "$ERRORS" >&2
  exit 1
fi
echo
echo "✓ Isolation OK."
