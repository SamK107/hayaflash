#!/usr/bin/env bash
# infra/scripts/vps_audit.sh — audit du VPS HayaFlash, LECTURE SEULE.
#
# Produit un rapport Markdown (✅ / ❌ / ⚠️ + sortie brute de chaque commande)
# pret a coller dans GOVERNANCE_SECURITE.md (categories 2, 5, 6, 7). Etape 1
# du runbook docs/RUNBOOK_JOUR_J.md.
#
# Usage (sur le VPS, a la racine du depot deploye) :
#   sudo bash infra/scripts/vps_audit.sh > audit-$(date +%F).md
#
# Sans sudo, le script tourne quand meme : les verifications qui exigent root
# (ufw, fail2ban, sshd -T, lecture de .env) sont marquees ⚠️ « non verifiable ».
#
# Garanties :
#   - Aucune ecriture, aucun redemarrage, aucune modification de config : que
#     des commandes de lecture (status, stat, grep, docker ps, curl GET).
#   - Chaque verification tourne dans un sous-shell : un echec (commande
#     absente, permission refusee...) n'arrete pas les suivantes.
#   - Aucun secret affiche : de .env on ne lit que OFFSITE_DIR et PROD_DOMAIN,
#     du fichier de cles age on n'affiche que des cles PUBLIQUES (age1...).
#
# Variables (toutes optionnelles) :
#   HAYAFLASH_DIR        dossier du projet deploye (defaut /srv/hayaflash)
#   ENV_FILE             defaut $HAYAFLASH_DIR/.env
#   COMPOSE_FILE         defaut $HAYAFLASH_DIR/docker-compose.production.yml
#   AGE_RECIPIENTS_FILE  defaut $HAYAFLASH_DIR/backup_recipients.txt
#   OFFSITE_DIR          defaut : valeur OFFSITE_DIR lue dans ENV_FILE
#   CRON_FILE            defaut /etc/cron.d/hayaflash-backup
#   BACKUP_LOG           defaut $HAYAFLASH_DIR/logs/backup.log
#   HEALTH_URL           URL publique de /health/ (ex. https://hayaflash.ml/health/) ;
#                        defaut : https://$PROD_DOMAIN/health/ si PROD_DOMAIN est lisible

set -u

HAYAFLASH_DIR="${HAYAFLASH_DIR:-/srv/hayaflash}"
ENV_FILE="${ENV_FILE:-$HAYAFLASH_DIR/.env}"
COMPOSE_FILE="${COMPOSE_FILE:-$HAYAFLASH_DIR/docker-compose.production.yml}"
AGE_RECIPIENTS_FILE="${AGE_RECIPIENTS_FILE:-$HAYAFLASH_DIR/backup_recipients.txt}"
CRON_FILE="${CRON_FILE:-/etc/cron.d/hayaflash-backup}"
BACKUP_LOG="${BACKUP_LOG:-$HAYAFLASH_DIR/logs/backup.log}"
REPO_CRON_FILE="$HAYAFLASH_DIR/infra/cron/hayaflash-backup"

OK="✅"
KO="❌"
WARN="⚠️"

# Lignes « STATUT|Titre » de la synthese, accumulees en memoire par
# run_check : aucun fichier temporaire, le script n'ecrit que sur sa sortie.
SUMMARY=""

is_root() { [ "$(id -u)" -eq 0 ]; }
have() { command -v "$1" >/dev/null 2>&1; }

# Lit UNE variable non secrete dans .env (jamais de dump du fichier).
env_value() {
  [ -r "$ENV_FILE" ] || return 1
  grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//'
}

# report STATUT "Titre" "commande affichee" "sortie brute" ["commentaire"]
report() {
  local status="$1" title="$2" cmd="$3" raw="$4" note="${5:-}"
  printf '\n### %s %s\n\n' "$status" "$title"
  [ -n "$note" ] && printf '%s\n\n' "$note"
  # shellcheck disable=SC2016  # backticks = Markdown, pas une substitution
  printf 'Commande : `%s`\n\n```\n%s\n```\n' "$cmd" "${raw:-(aucune sortie)}"
}

# Lance une verification isolee : sa sortie (Markdown) est imprimee telle
# quelle ; une erreur inattendue est rapportee sans interrompre l'audit.
run_check() {
  local name="$1" out rc
  out="$( ( "$name" ) 2>&1 )"
  rc=$?
  if [ "$rc" -ne 0 ] && [ -z "$out" ]; then
    out="$(report "$WARN" "$name" "$name" "Verification interrompue (code $rc).")"
  fi
  printf '%s\n' "$out"
  # Titres « ### STATUT Titre » -> lignes de synthese « STATUT|Titre ».
  SUMMARY+="$(printf '%s\n' "$out" | sed -n 's/^### \([^ ]*\) \(.*\)$/\1|\2/p')"$'\n'
}

# ── Categorie 7 : durcissement ───────────────────────────────────────────────

check_ufw() {
  local raw
  if ! have ufw; then
    report "$KO" "Pare-feu ufw" "command -v ufw" "ufw non installe." "Installer : apt install ufw, puis n'autoriser que 22/80/443."
    return
  fi
  if ! is_root; then
    report "$WARN" "Pare-feu ufw" "ufw status verbose" "" "Non verifiable sans sudo."
    return
  fi
  raw="$(ufw status verbose 2>&1)"
  if printf '%s' "$raw" | grep -q "^Status: active" && printf '%s' "$raw" | grep -q "deny (incoming)"; then
    report "$OK" "Pare-feu ufw actif, entrant refuse par defaut" "ufw status verbose" "$raw"
  elif printf '%s' "$raw" | grep -q "^Status: active"; then
    report "$WARN" "Pare-feu ufw actif mais politique entrante non « deny »" "ufw status verbose" "$raw"
  else
    report "$KO" "Pare-feu ufw inactif" "ufw status verbose" "$raw"
  fi
  # Rappel : Docker publie ses ports via iptables en contournant ufw -> voir
  # aussi check_docker_ports.
}

check_fail2ban() {
  local active raw
  if ! have fail2ban-client; then
    report "$KO" "fail2ban" "command -v fail2ban-client" "fail2ban non installe." "Installer : apt install fail2ban (jail sshd active par defaut sur Ubuntu)."
    return
  fi
  active="$(systemctl is-active fail2ban 2>&1)"
  if ! is_root; then
    report "$WARN" "fail2ban (service : $active)" "fail2ban-client status sshd" "" "Jail sshd non verifiable sans sudo."
    return
  fi
  raw="$(fail2ban-client status sshd 2>&1)"
  if [ "$active" = "active" ] && printf '%s' "$raw" | grep -q "Currently banned"; then
    report "$OK" "fail2ban actif, jail sshd en place" "systemctl is-active fail2ban && fail2ban-client status sshd" "service: $active
$raw"
  else
    report "$KO" "fail2ban inactif ou jail sshd absente" "systemctl is-active fail2ban && fail2ban-client status sshd" "service: $active
$raw"
  fi
}

check_sshd() {
  local raw root pass cmd
  if is_root && have sshd; then
    # Configuration EFFECTIVE (includes sshd_config.d/ compris), pas juste le fichier.
    raw="$(sshd -T 2>&1 | grep -Ei '^(permitrootlogin|passwordauthentication|pubkeyauthentication|kbdinteractiveauthentication) ')"
    cmd="sshd -T | grep -Ei 'permitrootlogin|passwordauthentication|...'"
  else
    raw="$(grep -EhRi '^\s*(PermitRootLogin|PasswordAuthentication|PubkeyAuthentication)\b' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/ 2>&1)"
    cmd="grep PermitRootLogin|PasswordAuthentication /etc/ssh/sshd_config*"
  fi
  root="$(printf '%s\n' "$raw" | grep -i 'permitrootlogin' | awk '{print tolower($2)}' | head -n 1)"
  pass="$(printf '%s\n' "$raw" | grep -i 'passwordauthentication' | awk '{print tolower($2)}' | head -n 1)"
  if [ "$root" = "no" ] && [ "$pass" = "no" ]; then
    report "$OK" "SSH : cle uniquement, root interdit" "$cmd" "$raw"
  elif [ "$pass" = "no" ] && [ "$root" = "prohibit-password" ]; then
    report "$WARN" "SSH : mot de passe desactive, root autorise par cle" "$cmd" "$raw" "Cible : PermitRootLogin no (se connecter avec l'utilisateur d'exploitation)."
  else
    report "$KO" "SSH : PermitRootLogin=${root:-?} PasswordAuthentication=${pass:-?}" "$cmd" "$raw" "Cible : PermitRootLogin no, PasswordAuthentication no."
  fi
}

check_unattended() {
  local installed conf enabled
  installed="$(dpkg -s unattended-upgrades 2>/dev/null | grep '^Status:' || echo 'non installe')"
  conf="$(cat /etc/apt/apt.conf.d/20auto-upgrades 2>&1)"
  enabled="$(systemctl is-enabled unattended-upgrades 2>&1)"
  if printf '%s' "$installed" | grep -q "install ok installed" \
    && printf '%s' "$conf" | grep -q 'Unattended-Upgrade "1"'; then
    report "$OK" "Mises a jour de securite automatiques" "dpkg -s unattended-upgrades; cat /etc/apt/apt.conf.d/20auto-upgrades" "$installed
service: $enabled
$conf"
  else
    report "$KO" "Mises a jour de securite automatiques absentes" "dpkg -s unattended-upgrades; cat /etc/apt/apt.conf.d/20auto-upgrades" "$installed
service: $enabled
$conf" "Activer : apt install unattended-upgrades && dpkg-reconfigure -plow unattended-upgrades"
  fi
}

check_docker_ports() {
  local raw exposed
  if ! have docker; then
    report "$KO" "Ports publies par Docker" "docker ps" "docker introuvable."
    return
  fi
  # Le code retour compte, pas seulement la sortie : un docker ps en echec
  # (daemon arrete, permission refusee, shim WSL...) ne doit jamais passer ✅.
  local rc
  raw="$(docker ps --format '{{.Names}}\t{{.Ports}}' 2>&1)"
  rc=$?
  # Un port publie sur l'hote apparait sous la forme 0.0.0.0:5432-> ou [::]:5432->.
  exposed="$(printf '%s\n' "$raw" | grep -E '(0\.0\.0\.0|\[::\]|:::):(5432|6379)->' || true)"
  if [ "$rc" -ne 0 ]; then
    report "$WARN" "Ports publies par Docker : docker ps en echec (code $rc)" "docker ps --format '{{.Names}}\t{{.Ports}}'" "$raw" "Lancer avec sudo (ou un utilisateur du groupe docker) ; verifier que le daemon tourne."
  elif [ -n "$exposed" ]; then
    report "$KO" "PostgreSQL/Redis publie sur l'hote" "docker ps --format '{{.Names}}\t{{.Ports}}'" "$raw" "Docker contourne ufw : un port publie est joignable depuis Internet. Retirer la section ports: du service."
  else
    report "$OK" "Aucun port 5432/6379 publie (seuls 80/443 attendus)" "docker ps --format '{{.Names}}\t{{.Ports}}'" "$raw"
  fi
}

check_env_perms() {
  local raw mode
  if [ ! -e "$ENV_FILE" ]; then
    report "$KO" "Fichier de secrets $ENV_FILE" "stat $ENV_FILE" "Fichier absent."
    return
  fi
  raw="$(stat -c '%a %U:%G %n' "$ENV_FILE" 2>&1)"
  mode="$(stat -c '%a' "$ENV_FILE" 2>/dev/null)"
  case "$mode" in
    600|400) report "$OK" "Permissions .env ($mode)" "stat -c '%a %U:%G' $ENV_FILE" "$raw" ;;
    *) report "$KO" "Permissions .env trop ouvertes ($mode)" "stat -c '%a %U:%G' $ENV_FILE" "$raw" "Corriger : chmod 600 $ENV_FILE (proprietaire = compte qui opere Docker)." ;;
  esac
}

# ── Categorie 5 : sauvegardes ────────────────────────────────────────────────

check_age() {
  if have age; then
    report "$OK" "age installe" "age --version" "$(age --version 2>&1)"
  else
    report "$KO" "age non installe" "command -v age" "" "Installer : apt install age (copy_offsite.sh refuse de copier sans age)."
  fi
}

check_age_keys() {
  local pubs privs stray
  if [ ! -s "$AGE_RECIPIENTS_FILE" ]; then
    report "$KO" "Cle publique age absente" "test -s $AGE_RECIPIENTS_FILE" "Fichier absent ou vide : $AGE_RECIPIENTS_FILE"
    return
  fi
  pubs="$(grep -Eo 'age1[0-9a-z]+' "$AGE_RECIPIENTS_FILE" 2>&1)"
  privs="$(grep -c 'AGE-SECRET-KEY' "$AGE_RECIPIENTS_FILE" 2>/dev/null || true)"
  # Cle privee egaree ailleurs dans le projet (hors dossier de sauvegardes) ?
  stray="$(grep -rlI --exclude-dir=backups --exclude-dir=.git 'AGE-SECRET-KEY' "$HAYAFLASH_DIR" 2>/dev/null | head -n 5 || true)"
  if [ "${privs:-0}" != "0" ] || [ -n "$stray" ]; then
    report "$KO" "Cle PRIVEE age presente sur le VPS" "grep -l AGE-SECRET-KEY" "Fichiers concernes (contenu non affiche) :
$AGE_RECIPIENTS_FILE ($privs ligne(s))
$stray" "La cle privee doit rester dans le gestionnaire de mots de passe (ADR-0001). La retirer du VPS."
  elif [ -n "$pubs" ]; then
    report "$OK" "Cle publique age presente, aucune cle privee" "grep -Eo 'age1...' $AGE_RECIPIENTS_FILE" "$pubs"
  else
    report "$KO" "Aucune cle publique age valide" "grep -Eo 'age1...' $AGE_RECIPIENTS_FILE" "Aucune ligne age1... dans $AGE_RECIPIENTS_FILE"
  fi
}

check_offsite() {
  local dir raw
  dir="${OFFSITE_DIR:-$(env_value OFFSITE_DIR 2>/dev/null || true)}"
  if [ -z "$dir" ]; then
    report "$KO" "Disque hors-site" "OFFSITE_DIR" "OFFSITE_DIR non defini (ni en variable, ni lisible dans $ENV_FILE)."
    return
  fi
  raw="$(findmnt -T "$dir" 2>&1; ls -la "$dir/.hayaflash_backup_target" 2>&1)"
  if mountpoint -q "$dir" && [ -f "$dir/.hayaflash_backup_target" ]; then
    report "$OK" "Disque hors-site monte + fichier temoin" "mountpoint $dir; ls $dir/.hayaflash_backup_target" "$raw"
  elif [ -f "$dir/.hayaflash_backup_target" ]; then
    report "$WARN" "Fichier temoin present mais $dir n'est pas un point de montage" "mountpoint $dir" "$raw" "Verifier que $dir est bien le disque externe (et non un dossier du disque systeme)."
  else
    report "$KO" "Disque hors-site absent ou sans fichier temoin" "mountpoint $dir; ls $dir/.hayaflash_backup_target" "$raw" "Brancher le disque, le monter sur $dir, puis : touch $dir/.hayaflash_backup_target"
  fi
}

check_cron() {
  local raw last
  if [ ! -f "$CRON_FILE" ]; then
    report "$KO" "Cron de sauvegarde non installe" "ls $CRON_FILE" "Absent : $CRON_FILE" "Voir infra/cron/hayaflash-backup (installation a l'etape 5 du runbook)."
    return
  fi
  raw="$(ls -la "$CRON_FILE" 2>&1; grep -v '^#' "$CRON_FILE" | grep -v '^$')"
  if [ -f "$BACKUP_LOG" ]; then
    last="$(tail -n 3 "$BACKUP_LOG" 2>&1)
(log modifie le $(stat -c '%y' "$BACKUP_LOG" 2>/dev/null | cut -d. -f1))"
  else
    last="(pas encore de $BACKUP_LOG)"
  fi
  if [ -f "$REPO_CRON_FILE" ] && ! diff -q "$REPO_CRON_FILE" "$CRON_FILE" >/dev/null 2>&1; then
    report "$WARN" "Cron installe mais different du depot" "diff $REPO_CRON_FILE $CRON_FILE" "$raw

$last" "Ecart volontaire (utilisateur adapte) ? Sinon reinstaller depuis le depot."
  else
    report "$OK" "Cron de sauvegarde installe" "cat $CRON_FILE; tail $BACKUP_LOG" "$raw

$last"
  fi
}

# ── Categorie 2 : disponibilite ──────────────────────────────────────────────

health_verdict() {
  # $1 = corps JSON de /health/ ; imprime OK / KO / WARN selon status + celery.
  local body="$1"
  if ! printf '%s' "$body" | grep -q '"status": *"ok"'; then
    echo KO
  elif printf '%s' "$body" | grep -q '"celery": *"ok"'; then
    echo OK
  else
    echo WARN
  fi
}

check_health_internal() {
  local raw verdict
  if ! have docker; then
    report "$KO" "/health/ (conteneur web)" "docker compose exec web curl" "docker introuvable."
    return
  fi
  if [ ! -f "$COMPOSE_FILE" ]; then
    report "$KO" "/health/ (conteneur web)" "test -f $COMPOSE_FILE" "Fichier compose absent : $COMPOSE_FILE (HAYAFLASH_DIR=$HAYAFLASH_DIR)."
    return
  fi
  raw="$(cd "$HAYAFLASH_DIR" && docker compose -f "$COMPOSE_FILE" exec -T web curl -sS -m 10 http://localhost:8000/health/ 2>&1)"
  verdict="$(health_verdict "$raw")"
  case "$verdict" in
    OK) report "$OK" "/health/ : DB, cache et Celery ok (conteneur web)" "docker compose exec -T web curl http://localhost:8000/health/" "$raw" ;;
    WARN) report "$WARN" "/health/ ok mais Celery non « ok » (beat/worker ?)" "docker compose exec -T web curl http://localhost:8000/health/" "$raw" "stale/missing : docker compose ps worker beat ; docker compose logs --tail 50 beat" ;;
    *) report "$KO" "/health/ en echec (conteneur web)" "docker compose exec -T web curl http://localhost:8000/health/" "$raw" ;;
  esac
}

check_health_public() {
  local url domain raw verdict
  url="${HEALTH_URL:-}"
  if [ -z "$url" ]; then
    domain="$(env_value PROD_DOMAIN 2>/dev/null || true)"
    [ -n "$domain" ] && url="https://$domain/health/"
  fi
  if [ -z "$url" ]; then
    report "$WARN" "/health/ public (Nginx + TLS)" "curl \$HEALTH_URL" "" "HEALTH_URL non defini et PROD_DOMAIN illisible : relancer avec HEALTH_URL=https://<domaine>/health/"
    return
  fi
  # Verification TLS conservee (pas de -k) : un certificat invalide doit echouer.
  raw="$(curl -sS -m 10 "$url" 2>&1)"
  verdict="$(health_verdict "$raw")"
  case "$verdict" in
    OK) report "$OK" "/health/ public ok via Nginx + TLS" "curl $url" "$raw" ;;
    WARN) report "$WARN" "/health/ public ok, Celery non « ok »" "curl $url" "$raw" ;;
    *) report "$KO" "/health/ public en echec" "curl $url" "$raw" ;;
  esac
}

check_disk() {
  local raw worst
  raw="$(df -hP / "$HAYAFLASH_DIR" /var/lib/docker 2>/dev/null | awk '!seen[$0]++')"
  worst="$(df -P / "$HAYAFLASH_DIR" /var/lib/docker 2>/dev/null | awk 'NR>1 {gsub("%","",$5); if ($5>m) m=$5} END {print m+0}')"
  if [ "$worst" -ge 90 ]; then
    report "$KO" "Espace disque critique (${worst}% utilise)" "df -hP / $HAYAFLASH_DIR /var/lib/docker" "$raw"
  elif [ "$worst" -ge 80 ]; then
    report "$WARN" "Espace disque a surveiller (${worst}% utilise)" "df -hP / $HAYAFLASH_DIR /var/lib/docker" "$raw"
  else
    report "$OK" "Espace disque (${worst}% max utilise)" "df -hP / $HAYAFLASH_DIR /var/lib/docker" "$raw"
  fi
}

# ── Rapport ──────────────────────────────────────────────────────────────────

os_name() {
  # shellcheck source=/dev/null
  (. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-?}")
}

# shellcheck disable=SC2016  # backticks = Markdown, pas des substitutions
{
  printf '# Audit VPS HayaFlash — %s\n\n' "$(date -u '+%Y-%m-%d %H:%M UTC')"
  printf -- '- Hote : `%s` (%s)\n' "$(hostname 2>/dev/null)" "$(os_name)"
  printf -- '- Utilisateur : `%s`%s\n' "$(id -un)" "$(is_root || echo ' — **sans sudo : verifications partielles**')"
  printf -- '- Script : `infra/scripts/vps_audit.sh` (lecture seule)\n'
}

printf '\n## Categorie 7 — Durcissement\n'
run_check check_ufw
run_check check_fail2ban
run_check check_sshd
run_check check_unattended
run_check check_docker_ports
run_check check_env_perms

printf '\n## Categorie 5 — Sauvegardes\n'
run_check check_age
run_check check_age_keys
run_check check_offsite
run_check check_cron

printf '\n## Categorie 2 — Disponibilite\n'
run_check check_health_internal
run_check check_health_public
run_check check_disk

printf '\n## Synthese\n\n| | Verification |\n|---|---|\n'
# Pipes plutot que here-strings (<<<) : bash < 5.1 ecrit ces dernieres dans
# un fichier temporaire, et ce script ne doit rien ecrire.
printf '%s' "$SUMMARY" | while IFS='|' read -r status title; do
  [ -n "$status" ] && printf '| %s | %s |\n' "$status" "$title"
done
printf '\n%s ok · %s a corriger · %s a verifier\n' \
  "$(printf '%s' "$SUMMARY" | grep -c "^$OK|")" \
  "$(printf '%s' "$SUMMARY" | grep -c "^$KO|")" \
  "$(printf '%s' "$SUMMARY" | grep -c "^$WARN|")"
