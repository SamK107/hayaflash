#!/bin/bash
# Smoke test post-deploy HayaFlash
# Usage: bash infra/scripts/smoke_test.sh [BASE_URL]
set -e

BASE="${1:-http://localhost:8000}"
PASS=0
FAIL=0

check() {
  local desc="$1" url="$2" pattern="$3"
  local http_code
  http_code=$(curl -sf -o /tmp/hf_smoke_body -w "%{http_code}" "$url" 2>/dev/null || echo "000")
  if [ "$http_code" = "000" ]; then
    echo "FAIL [$desc] — connexion impossible à $url"
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
