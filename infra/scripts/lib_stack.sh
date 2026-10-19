#!/usr/bin/env bash
# infra/scripts/lib_stack.sh — fonctions communes aux scripts multi-piles.
# A "sourcer" (. lib_stack.sh), jamais a executer seul.
#
# Une « pile » = un clone git (ex. /srv/hayaflash = staging, /srv/hayaflash-prod
# = production) contenant docker-compose.production.yml et SON .env. Le nom de
# projet Compose, le port, l'image, les volumes et le reseau en decoulent
# (voir l'en-tete de docker-compose.production.yml).

hf_log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
hf_warn() { printf '⚠ %s\n' "$*" >&2; }
hf_die() { printf '✗ %s\n' "$*" >&2; exit 1; }

# hf_stack_init <dossier_pile> : positionne STACK_DIR, ENV_FILE, COMPOSE (tableau).
hf_stack_init() {
  local d="${1:-}"
  [ -n "$d" ] || hf_die "dossier de pile requis (ex. /srv/hayaflash-prod)"
  [ -d "$d" ] || hf_die "dossier de pile introuvable : $d"
  STACK_DIR="$(cd "$d" && pwd)"
  ENV_FILE="$STACK_DIR/.env"
  local compose_file="$STACK_DIR/docker-compose.production.yml"
  [ -f "$compose_file" ] || hf_die "docker-compose.production.yml introuvable dans $STACK_DIR"
  [ -f "$ENV_FILE" ] || hf_die ".env introuvable dans $STACK_DIR (chaque pile a le sien)"
  # --project-directory : Compose lit le .env de CE dossier pour l'interpolation.
  COMPOSE=(docker compose --project-directory "$STACK_DIR" -f "$compose_file")
}

# hf_env_get CLE : derniere valeur de CLE dans le .env de la pile (sans « source » :
# on ne deroule jamais le contenu du .env comme du code). Vide si absente.
hf_env_get() {
  local line
  line="$(grep -E "^[[:space:]]*$1=" "$ENV_FILE" 2>/dev/null | tail -n 1 || true)"
  line="${line#*=}"
  line="${line%$'\r'}"
  line="${line#\"}"; line="${line%\"}"
  line="${line#\'}"; line="${line%\'}"
  printf '%s' "$line"
}

# hf_cfg CLE DEFAUT : variable d'environnement, sinon .env de la pile, sinon defaut.
hf_cfg() {
  local key="$1" def="${2:-}" val
  val="${!key:-}"
  [ -n "$val" ] || val="$(hf_env_get "$key")"
  printf '%s' "${val:-$def}"
}

# hf_load_config : charge la config resolue de Compose (texte) dans CONFIG_TXT.
hf_load_config() {
  CONFIG_TXT="$("${COMPOSE[@]}" config 2>/dev/null)" \
    || hf_die "« docker compose config » echoue dans $STACK_DIR (voir la sortie de la commande a la main)"
}

hf_project_name() { printf '%s\n' "$CONFIG_TXT" | awk '/^name:/ {print $2; exit}'; }

# Port publie sur l'hote par le service nginx.
hf_http_port() {
  printf '%s\n' "$CONFIG_TXT" | awk '/^  nginx:/ {s=1; next} /^  [a-z_-]+:/ {s=0} s && /published:/ {gsub(/"/, "", $2); print $2; exit}'
}

# Image du service web (repo:tag).
hf_web_image() {
  printf '%s\n' "$CONFIG_TXT" | awk '/^  web:/ {s=1; next} /^  [a-z_-]+:/ {s=0} s && /^    image:/ {print $2; exit}'
}

# Noms reels (prefixes par le projet) des volumes / du reseau.
hf_volume_names() {
  printf '%s\n' "$CONFIG_TXT" | awk '/^volumes:/ {s=1; next} /^[^ ]/ {s=0} s && /^    name:/ {print $2}'
}
hf_network_names() {
  printf '%s\n' "$CONFIG_TXT" | awk '/^networks:/ {s=1; next} /^[^ ]/ {s=0} s && /^    name:/ {print $2}'
}

# hf_is_prod_dir : vrai si le dossier de pile est une pile de production.
hf_is_prod_dir() { case "$(basename "$STACK_DIR")" in *prod*) return 0 ;; *) return 1 ;; esac; }

# hf_service_running SERVICE : vrai si le conteneur du service tourne.
hf_service_running() {
  "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -qx "$1"
}

# hf_nginx_fingerprint : empreinte de TOUT ce qui configure le conteneur nginx : son bloc
# resolu dans « docker compose config » (image, montages, ports, variables d'environnement
# y compris celles du .env) + le contenu de infra/nginx/. Un `restart` ne relit ni le compose
# ni l'environnement : quand l'empreinte change, nginx doit etre RECREE (deploy_vps.sh).
hf_nginx_fingerprint() {
  {
    "${COMPOSE[@]}" config 2>/dev/null       | awk '/^  nginx:/ {s=1; print; next} /^  [a-z_-]+:/ {s=0} s'
    if [ -d "$STACK_DIR/infra/nginx" ]; then
      find "$STACK_DIR/infra/nginx" -type f | sort | while read -r f; do printf '%s
' "$f"; cat "$f"; done
    fi
  } | sha256sum | cut -d' ' -f1
}

# hf_nginx_validate_disposable : teste la configuration nginx dans un conteneur JETABLE
# (meme image, memes montages et variables que le service, `nginx -t`, supprime ensuite),
# sans toucher au conteneur en service. Code de retour = celui de nginx -t.
hf_nginx_validate_disposable() {
  "${COMPOSE[@]}" run --rm --no-deps -T nginx nginx -t
}
