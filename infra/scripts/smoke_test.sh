#!/bin/bash
# Smoke test post-deploy HayaFlash
# Usage: [SMOKE_HOST=<domaine>] bash infra/scripts/smoke_test.sh [BASE_URL]
#
# BASE_URL : par defaut le Nginx du conteneur en loopback (127.0.0.1:8010 en
#   production, port PROVISOIRE a confirmer en Phase 4, cf. docker-compose.production.yml).
# SMOKE_HOST : optionnel, valeur de l'en-tete Host (le domaine public) quand on
#   teste par 127.0.0.1 : sinon Django refuse le Host (ALLOWED_HOSTS).
#
# Une URL n'est OK que si le serveur repond en 2xx : une redirection, une
# erreur client ou serveur, ou une connexion impossible est un ECHEC (F-35).
set -e

BASE="${1:-http://127.0.0.1:8010}"
PASS=0
FAIL=0

# Le Nginx de l'hote (qui termine TLS en production) pose X-Forwarded-Proto ;
# sans lui, Django (SECURE_SSL_REDIRECT) repondrait 301 vers https.
CURL_ARGS=(-H "X-Forwarded-Proto: https")
if [ -n "${SMOKE_HOST:-}" ]; then
  CURL_ARGS+=(-H "Host: ${SMOKE_HOST}")
fi

check() {
  local desc="$1" url="$2" pattern="$3"
  local http_code
  # Pas de -f : avec -f, curl imprime le code puis sort en erreur, et le
  # `|| echo 000` d'avant l'ajoutait au code (« 500000 », « 000000 »), jamais
  # egal a « 000 ». Ici le code vient de -w seul ; `|| true` ne change rien a
  # la sortie (curl n'imprime « 000 » que si aucune reponse n'est recue).
  http_code=$(curl -s -o /tmp/hf_smoke_body -w "%{http_code}" --max-time 15 \
    "${CURL_ARGS[@]}" "$url" 2>/dev/null) || true
  if [ -z "$http_code" ] || [ "$http_code" = "000" ]; then
    echo "FAIL [$desc] — connexion impossible à $url"
    FAIL=$((FAIL+1))
    return
  fi
  if ! [[ "$http_code" =~ ^2[0-9][0-9]$ ]]; then
    echo "FAIL [$desc] — HTTP $http_code (2xx attendu) sur $url"
    FAIL=$((FAIL+1))
    return
  fi
  if [ -n "$pattern" ] && ! grep -q "$pattern" /tmp/hf_smoke_body 2>/dev/null; then
    echo "FAIL [$desc] — HTTP $http_code mais pattern '$pattern' absent"
    FAIL=$((FAIL+1))
    return
  fi
  echo "OK   [$desc] — HTTP $http_code"
  PASS=$((PASS+1))
}

echo "=== HayaFlash Smoke Test : $BASE ==="

# /health/ : DB + cache (503 « degraded » si l'un tombe) — GOVERNANCE_SECURITE.md cat. 2 (F-52)
check "Health (DB + cache)" "$BASE/health/"        '"status":"ok"'
check "Page d'accueil"      "$BASE/"               "HayaFlash"
check "Page login"          "$BASE/login/"          "Se connecter"
check "Page ventes publiq." "$BASE/ventes/"         ""
check "API flash-sales"     "$BASE/api/v1/flash-sales/" ""
check "Manifest PWA"        "$BASE/static/manifest.json" "HayaFlash"

echo ""
echo "=== Résultat : $PASS OK / $FAIL FAIL ==="

if [ "$FAIL" -gt 0 ]; then
  echo "SMOKE TEST FAILED"
  exit 1
fi

echo "SMOKE TEST PASSED"
