#!/usr/bin/env bash
# infra/scripts/check_prod_prereqs.sh — prerequis de la production, STRICTEMENT EN LECTURE SEULE.
#
# A lancer par le porteur du projet sur le VPS, avant le premier demarrage de la prod :
#   bash infra/scripts/check_prod_prereqs.sh
#
# Ne modifie RIEN : aucun fichier ecrit, aucun service touche, aucune regle changee.
# Commandes utilisees : dig/getent, ufw status, ss, df, free, curl (GET/HEAD), cat de fichiers
# de configuration PostgreSQL (lecture, via sudo -n si besoin). Rien d'autre.
#
# Sortie : une ligne par controle — OK, ATTENTION ou ECHEC — puis un resume.
# Code de sortie : 0 s'il n'y a aucun ECHEC (les ATTENTION sont a relire), 1 sinon.
#
# Variables (surchargeables) :
#   EXPECTED_IP      IP publique du VPS               (defaut 31.207.39.116)
#   DOMAINS          domaines a verifier en DNS       (defaut "hayaflash.com www.hayaflash.com")
#   OTHER_SITES      sites a ne jamais casser (HTTPS) (defaut "symain.africa services.symain.africa")
#   PROD_PORTS       ports locaux des piles           (defaut "8020 8021")
#   MIN_MEM_MB       memoire disponible minimale      (defaut 2500)
#   MIN_DISK_FREE_PCT espace disque libre minimal     (defaut 15)

set -u

EXPECTED_IP="${EXPECTED_IP:-31.207.39.116}"
DOMAINS="${DOMAINS:-hayaflash.com www.hayaflash.com}"
OTHER_SITES="${OTHER_SITES:-symain.africa services.symain.africa}"
PROD_PORTS="${PROD_PORTS:-8020 8021}"
MIN_MEM_MB="${MIN_MEM_MB:-2500}"
MIN_DISK_FREE_PCT="${MIN_DISK_FREE_PCT:-15}"
# Ports qui PEUVENT etre ouverts au public (HestiaCP ouvre aussi la messagerie/DNS/FTP : a
# relire dans la ligne ATTENTION, ce n'est pas un echec).
ALLOWED_PUBLIC_PORTS="22 80 443 8083"

N_OK=0; N_WARN=0; N_FAIL=0
ok()   { N_OK=$((N_OK+1));     printf '  [ OK        ] %s\n' "$*"; }
warn() { N_WARN=$((N_WARN+1)); printf '  [ ATTENTION ] %s\n' "$*"; }
fail() { N_FAIL=$((N_FAIL+1)); printf '  [ ECHEC     ] %s\n' "$*"; }
section() { printf '\n== %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }
# sudo sans mot de passe seulement : si impossible, on le dit (jamais de prompt bloquant).
rsudo() { if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo -n "$@" 2>/dev/null; fi; }

echo "Prerequis de production HayaFlash — lecture seule — $(date '+%F %T %Z')"
echo "Hote : $(hostname) ; IP attendue : $EXPECTED_IP"

# ── 1. DNS ────────────────────────────────────────────────────────────────────
section "1. DNS (deux resolveurs publics)"
for d in $DOMAINS; do
  for r in 1.1.1.1 8.8.8.8; do
    if have dig; then
      ips="$(dig +short +time=5 +tries=1 A "$d" @"$r" 2>/dev/null | grep -E '^[0-9.]+$' | sort -u | tr '\n' ' ')"
    else
      ips=""
    fi
    ips="${ips% }"
    if ! have dig; then
      warn "$d @$r : dig absent (apt install dnsutils) — controle impossible"
    elif [ -z "$ips" ]; then
      fail "$d @$r : aucun enregistrement A"
    elif [ "$ips" = "$EXPECTED_IP" ]; then
      ok "$d @$r -> $ips"
    else
      fail "$d @$r -> $ips (attendu : $EXPECTED_IP seul)"
    fi
  done
  if have dig; then
    aaaa="$(dig +short +time=5 +tries=1 AAAA "$d" @1.1.1.1 2>/dev/null | grep -E ':' | tr '\n' ' ')"
    [ -z "$aaaa" ] && ok "$d : pas d'enregistrement AAAA parasite" \
                   || warn "$d : AAAA present ($aaaa) — doit pointer vers ce serveur ou etre supprime"
  fi
done

# ── 2. Pare-feu ───────────────────────────────────────────────────────────────
section "2. Pare-feu (ufw status verbose)"
if ! have ufw; then
  warn "ufw absent : le pare-feu est peut-etre gere par HestiaCP (iptables) — a verifier a la main"
else
  UFW="$(rsudo ufw status verbose || true)"
  if [ -z "$UFW" ]; then
    warn "ufw status illisible sans sudo : relancer avec 'sudo bash $0'"
  else
    printf '%s\n' "$UFW" | sed 's/^/      | /'
    if printf '%s\n' "$UFW" | grep -q '^Status: inactive'; then
      warn "ufw inactif : le filtrage repose sur autre chose (HestiaCP/iptables) — a confirmer"
    else
      ports="$(printf '%s\n' "$UFW" | awk '/ALLOW/ && !/\(v6\)/ {print $1}' | sed 's#/.*##' | grep -E '^[0-9]+$' | sort -un | tr '\n' ' ')"
      bad=""
      for p in $ports; do
        case " $ALLOWED_PUBLIC_PORTS " in *" $p "*) ;; *) bad="$bad $p" ;; esac
      done
      for p in $PROD_PORTS; do
        case " $ports " in *" $p "*) fail "port $p ouvert au public dans ufw (doit rester local)" ;; esac
      done
      if [ -z "$bad" ]; then ok "seuls les ports attendus sont ouverts ($ports)"
      else warn "ports ouverts en plus de ($ALLOWED_PUBLIC_PORTS) :$bad — normal pour la messagerie/DNS de HestiaCP, sinon a fermer"; fi
    fi
  fi
fi

# ── 3. Ports locaux des piles ─────────────────────────────────────────────────
section "3. Ports 8020 / 8021 : liaison locale seulement (ss -ltnp)"
if ! have ss; then
  warn "ss absent : controle impossible"
else
  SS="$(rsudo ss -ltnp || ss -ltn 2>/dev/null || true)"
  for p in $PROD_PORTS; do
    line="$(printf '%s\n' "$SS" | awk -v p=":$p" '$4 ~ p"$" {print $4}' | sort -u | tr '\n' ' ')"
    if [ -z "$line" ]; then
      warn "port $p : aucun processus en ecoute (pile arretee ?)"
    elif printf '%s\n' "$line" | tr ' ' '\n' | grep -vE '^(127\.0\.0\.1|\[::1\]):' | grep -q .; then
      fail "port $p ecoute sur une interface publique : $line (attendu 127.0.0.1 seulement)"
    else
      ok "port $p lie a 127.0.0.1 seulement ($line)"
    fi
  done
fi

# ── 4. PostgreSQL de l'hote ───────────────────────────────────────────────────
section "4. PostgreSQL de l'hote (utilise par symain)"
PGOPEN=0
if have ss; then
  pgl="$(rsudo ss -ltn 2>/dev/null || ss -ltn 2>/dev/null || true)"
  pgl="$(printf '%s\n' "$pgl" | awk '$4 ~ /:5432$/ {print $4}' | sort -u | tr '\n' ' ')"
  if [ -z "$pgl" ]; then
    ok "rien n'ecoute sur le port 5432 de l'hote"
  elif printf '%s\n' "$pgl" | tr ' ' '\n' | grep -vE '^(127\.0\.0\.1|\[::1\]):' | grep -q .; then
    fail "PostgreSQL ecoute sur une interface publique : $pgl"; PGOPEN=1
  else
    ok "PostgreSQL ecoute en local seulement ($pgl)"
  fi
fi
CONFS="$(ls /etc/postgresql/*/main/postgresql.conf 2>/dev/null || true)"
if [ -z "$CONFS" ]; then
  ok "aucune configuration PostgreSQL d'hote trouvee (/etc/postgresql) — rien a verifier"
else
  for c in $CONFS; do
    la="$(rsudo grep -E '^[[:space:]]*listen_addresses' "$c" || true)"
    if [ -z "$la" ]; then
      rsudo test -r "$c" || { warn "$c illisible sans sudo (relancer avec sudo)"; continue; }
      ok "$c : listen_addresses par defaut (localhost)"
    elif printf '%s' "$la" | grep -qE "'(\*|0\.0\.0\.0)'|\"(\*|0\.0\.0\.0)\""; then
      fail "$c : $la — ecoute sur toutes les interfaces"
    else
      ok "$c : $la"
    fi
    hba="$(dirname "$c")/pg_hba.conf"
    open="$(rsudo grep -E '^[[:space:]]*host' "$hba" | grep -E '0\.0\.0\.0/0|::/0' || true)"
    if ! rsudo test -r "$hba"; then warn "$hba illisible sans sudo"
    elif [ -n "$open" ]; then fail "$hba autorise des connexions depuis tout Internet : $open"
    else ok "$hba : aucune regle ouverte a 0.0.0.0/0 ni ::/0"; fi
  done
fi

# ── 5. Disque et memoire ──────────────────────────────────────────────────────
section "5. Espace disque et memoire"
if have df; then
  used="$(df -P / | awk 'NR==2 {gsub("%","",$5); print $5}')"
  avail="$(df -Ph / | awk 'NR==2 {print $4}')"
  case "$used" in ''|*[!0-9]*) used=""; esac
  free_pct=$((100 - ${used:-100}))
  if [ -z "$used" ]; then warn "disque / : pourcentage illisible (df)"
  elif [ "$free_pct" -lt 5 ];                    then fail "disque / : ${free_pct}% libre ($avail)"
  elif [ "$free_pct" -lt "$MIN_DISK_FREE_PCT" ]; then warn "disque / : ${free_pct}% libre ($avail) < ${MIN_DISK_FREE_PCT}%"
  else ok "disque / : ${free_pct}% libre ($avail)"; fi
  if [ -d /var/lib/docker ]; then
    dfree="$(df -Ph /var/lib/docker | awk 'NR==2 {print $4}')"; ok "volume Docker : $dfree disponibles"
  fi
fi
if have free; then
  avail_mb="$(free -m | awk '/^Mem:/ {print $7}')"
  swap_mb="$(free -m | awk '/^Swap:/ {print $3}')"
  if   [ "${avail_mb:-0}" -lt 800 ];          then fail "memoire disponible : ${avail_mb} Mo (staging + prod + symain : trop juste)"
  elif [ "${avail_mb:-0}" -lt "$MIN_MEM_MB" ]; then warn "memoire disponible : ${avail_mb} Mo < ${MIN_MEM_MB} Mo (une pile peut reserver jusqu'a 2,5 Go)"
  else ok "memoire disponible : ${avail_mb} Mo"; fi
  [ "${swap_mb:-0}" -gt 512 ] && warn "swap utilise : ${swap_mb} Mo (pression memoire)"
fi

# ── 6. Autres sites : ne doivent pas etre impactes ────────────────────────────
section "6. Sites voisins en HTTPS (code HTTP)"
if ! have curl; then
  warn "curl absent : controle impossible"
else
  for site in $OTHER_SITES; do
    code="$(curl -s -o /dev/null -m 15 -w '%{http_code}' "https://$site/" 2>/dev/null || true)"
    case "$code" in
      200|301|302|303|307|308) ok "https://$site/ -> HTTP $code" ;;
      000|"")                  fail "https://$site/ ne repond pas" ;;
      *)                       fail "https://$site/ -> HTTP $code" ;;
    esac
  done
fi

# ── Resume ────────────────────────────────────────────────────────────────────
printf '\n== Resume : %d OK, %d ATTENTION, %d ECHEC\n' "$N_OK" "$N_WARN" "$N_FAIL"
if [ "$N_FAIL" -gt 0 ]; then
  echo "Au moins un ECHEC : ne pas demarrer la prod avant de l'avoir corrige."
  exit 1
fi
[ "$N_WARN" -gt 0 ] && echo "Relire les lignes ATTENTION avant de continuer."
exit 0
