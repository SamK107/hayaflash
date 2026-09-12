#!/bin/bash
# infra/scripts/deploy.sh — deploiement HayaFlash avec healthcheck + rollback auto
#
# Tourne SUR LE VPS (pas en CI), invoque via SSH par .github/workflows/deploy.yml
# apres un `git pull` qui a deja rapatrie cette version du script.
#
# Usage :
#   DOCKER_IMAGE=ghcr.io/<org>/hayaflash HAYAFLASH_TAG=<sha> \
#     bash infra/scripts/deploy.sh [BASE_URL]
#
# Comportement :
#   1. Sauvegarde le tag actuellement en prod (avant bascule) comme cible de
#      rollback.
#   2. Deploie HAYAFLASH_TAG, migrate, collectstatic.
#   3. Lance smoke_test.sh contre BASE_URL. Si ca echoue, rollback automatique
#      vers le dernier tag connu bon, puis sort en erreur (le job CI est rouge
#      meme si le rollback a reussi — echec a investiguer, pas a masquer).
#
# Limite assumee : les migrations Django sont forward-only (voir
# docs/QA_PLAN.md §8). Un rollback d'image ne desfait PAS une migration DB.
# Si HAYAFLASH_TAG a introduit une migration incompatible avec le tag
# precedent, le rollback automatique ne suffit pas — intervention manuelle.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

COMPOSE="docker compose -p hayaflash -f docker-compose.production.yml"
CURRENT_TAG_FILE="$PROJECT_DIR/.deploy_current_tag"
LAST_GOOD_TAG_FILE="$PROJECT_DIR/.deploy_last_good_tag"
BASE_URL="${1:-http://localhost:8000}"

: "${HAYAFLASH_TAG:?HAYAFLASH_TAG requis (SHA de l'image a deployer)}"
: "${DOCKER_IMAGE:?DOCKER_IMAGE requis (ex: ghcr.io/<org>/hayaflash)}"

if [ -f "$CURRENT_TAG_FILE" ]; then
  cp "$CURRENT_TAG_FILE" "$LAST_GOOD_TAG_FILE"
fi

deploy_tag() {
  local tag="$1"
  echo "→ Deploiement de ${DOCKER_IMAGE}:${tag}"
  DOCKER_IMAGE="$DOCKER_IMAGE" IMAGE_TAG="$tag" $COMPOSE pull web worker beat
  DOCKER_IMAGE="$DOCKER_IMAGE" IMAGE_TAG="$tag" $COMPOSE up -d --no-deps web worker beat
  echo "$tag" > "$CURRENT_TAG_FILE"
}

deploy_tag "$HAYAFLASH_TAG"

DOCKER_IMAGE="$DOCKER_IMAGE" IMAGE_TAG="$HAYAFLASH_TAG" \
  $COMPOSE exec -T web python manage.py migrate --noinput
DOCKER_IMAGE="$DOCKER_IMAGE" IMAGE_TAG="$HAYAFLASH_TAG" \
  $COMPOSE exec -T web python manage.py collectstatic --noinput

# Laisse Gunicorn + le healthcheck Docker se stabiliser avant de juger.
sleep 5

if bash "$PROJECT_DIR/infra/scripts/smoke_test.sh" "$BASE_URL"; then
  echo "✓ Deploiement ${HAYAFLASH_TAG} valide (smoke test OK)"
  exit 0
fi

echo "✗ Smoke test echoue sur ${HAYAFLASH_TAG}"

if [ -s "$LAST_GOOD_TAG_FILE" ]; then
  ROLLBACK_TAG="$(cat "$LAST_GOOD_TAG_FILE")"
  echo "→ Rollback automatique vers ${ROLLBACK_TAG}"
  deploy_tag "$ROLLBACK_TAG"
  echo "⚠ Rollback effectue vers ${ROLLBACK_TAG}. Les migrations DB de"
  echo "  ${HAYAFLASH_TAG} ne sont PAS annulees (forward-only) — verifier"
  echo "  la compatibilite si ${HAYAFLASH_TAG} avait migre le schema."
else
  echo "✗ Aucun tag precedent connu (${LAST_GOOD_TAG_FILE} absent)."
  echo "  Rollback automatique impossible — intervention manuelle requise."
fi

exit 1
