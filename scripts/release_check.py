"""Controle de release HayaFlash : Phase 2 de GOVERNANCE_RELEASE.md (+ pip-audit
et bandit de la Phase 3).

Execution (PowerShell, racine du depot, .venv active) :

    python -m pip install -r requirements-dev.txt
    python scripts/release_check.py --release v1.0.0-rc1

Prerequis : PostgreSQL 16 joignable avec les memes parametres que la CI
(.github/workflows/ci.yml + config/settings/test_pg.py) : 127.0.0.1:55432,
utilisateur postgres, mot de passe test, base hayaflash_test. Surchargeables
par TEST_PG_HOST / TEST_PG_PORT / TEST_PG_USER / TEST_PG_PASSWORD /
TEST_PG_NAME. Voir GOVERNANCE_RELEASE.md, section « release_check.py ».

Garanties :
- .env n'est jamais lu : chaque sous-processus recoit PYTHON_DOTENV_DISABLED=1
  et un environnement reduit (liste blanche), comme la CI qui n'a pas de .env ;
- aucun secret sur disque : la SECRET_KEY de ``check --deploy`` est generee a
  chaque execution et n'existe que dans l'environnement de ce sous-processus ;
  ALLOWED_HOSTS et DATABASE_URL y sont factices ;
- aucune ecriture dans le depot hors du rapport (docs/releases/reports/) :
  .coverage, junit et json de couverture vont dans un dossier temporaire ;
- aucune operation git en ecriture (seulement ``git rev-parse HEAD``).

Non couvert ici (voir le suivi de release) : Celery worker + beat reels,
gitleaks (manuel, bloquant en Phase 0 avant le tag rc), OWASP ZAP.

bandit : severite haute bloquante ; severite moyenne affichee dans le rapport,
non bloquante, a relire.

Code retour : 0 si toutes les etapes sont OK, 1 sinon.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "docs" / "releases" / "reports"

# Memes valeurs que les services de .github/workflows/ci.yml et que les
# defauts de config/settings/test_pg.py.
PG_DEFAULTS = {
    "TEST_PG_HOST": "127.0.0.1",
    "TEST_PG_PORT": "55432",
    "TEST_PG_USER": "postgres",
    "TEST_PG_PASSWORD": "test",
    "TEST_PG_NAME": "hayaflash_test",
}
PG_EXPECTED_MAJOR = 16
# Base creee puis supprimee par l'etape "migrate depuis une base vide".
MIGRATE_DB_NAME = "hayaflash_release_check"

# Variables de ci.yml (env: au niveau du workflow).
CI_ENV = {
    "DJANGO_SETTINGS_MODULE": "config.settings.test",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
}

# Variables systeme transmises aux sous-processus ; tout le reste (en
# particulier SECRET_KEY, DATABASE_URL, REDIS_URL, SENTRY_DSN, EMAIL_*...
# eventuellement exportes dans le shell) est ecarte.
ENV_ALLOWLIST = {
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
    "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
    "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "COMMONPROGRAMFILES", "USERNAME", "USER", "LOGNAME",
    "OS", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "LANG", "LC_ALL",
    "VIRTUAL_ENV", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "REQUESTS_CA_BUNDLE",
    "SSL_CERT_FILE", "PIP_INDEX_URL", "PIP_CERT",
    *PG_DEFAULTS.keys(),
}

# Seuil de couverture de la Phase 2 (code applicatif, hors fichiers de tests).
CRITICAL_COVERAGE_MIN = 90.0
CRITICAL_APPS = ("subscriptions", "orders", "payments")
# Fichiers du callback Orange Money (webhook /billing/webhook/orange/, callback
# historique /seller/abonnement/callback/, logique et client API).
ORANGE_CALLBACK_FILES = (
    "subscriptions/billing_views.py",
    "subscriptions/views.py",
    "subscriptions/services/payment.py",
    "subscriptions/services/orange_money.py",
)
# Fichiers critiques verifies un par un (en plus des apps ci-dessus) : chaque
# fichier doit atteindre le seuil individuellement.
CRITICAL_FILES = ORANGE_CALLBACK_FILES + ("orders/services/create_order.py",)
# Dossiers dont chaque fichier (hors __init__.py vide) est verifie un par un.
CRITICAL_FILE_PREFIXES = ("payments/services/",)
GLOBAL_COVERAGE_MIN = 60  # --cov-fail-under de ci.yml

BANDIT_TARGETS = (
    "accounts", "analytics", "config", "core", "delivery", "flash_sales",
    "notifications", "orders", "payments", "products", "subscriptions",
    "scripts",
)

OUTPUT_TAIL_LINES = 80

OK, FAIL, NOT_RUN = "OK", "ECHEC", "NON EXECUTE"


@dataclass
class StepResult:
    key: str
    title: str
    status: str
    summary: str = ""
    command: str = ""
    env_note: str = ""
    output: str = ""
    duration: float = 0.0
    details: list[str] = field(default_factory=list)


def _pg_params() -> dict[str, str]:
    return {k: os.environ.get(k) or v for k, v in PG_DEFAULTS.items()}


def clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() in ENV_ALLOWLIST}
    env.update(_pg_params())
    env.update(CI_ENV)
    env["PYTHON_DOTENV_DISABLED"] = "1"
    # Les sous-processus ecrivent en UTF-8 (run_cmd decode en UTF-8) : sinon
    # pip-audit plante sous Windows (cp1252) sur la fleche Unicode de son rapport.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update(extra)
    return env


def _tail(text: str, n: int = OUTPUT_TAIL_LINES) -> str:
    lines = text.rstrip().splitlines()
    if len(lines) <= n:
        return "\n".join(lines)
    return "\n".join([f"[... {len(lines) - n} lignes precedentes omises ...]"] + lines[-n:])


def run_cmd(args: list[str], env: dict[str, str]) -> tuple[int, str, float]:
    start = time.monotonic()
    proc = subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout or "", time.monotonic() - start


def _display(args: list[str]) -> str:
    shown = ["python" if a == sys.executable else a for a in args]
    return " ".join(f'"{a}"' if " " in a else a for a in shown)


def command_step(key: str, title: str, args: list[str], env: dict[str, str], env_note: str) -> StepResult:
    code, out, duration = run_cmd(args, env)
    return StepResult(
        key=key,
        title=title,
        status=OK if code == 0 else FAIL,
        summary=f"code retour {code}",
        command=_display(args),
        env_note=env_note,
        output=_tail(out),
        duration=duration,
    )


# ── Etapes ────────────────────────────────────────────────────────────────────


def step_pg_preflight() -> StepResult:
    title = f"PostgreSQL {PG_EXPECTED_MAJOR} joignable (parametres CI)"
    p = _pg_params()
    where = f"{p['TEST_PG_USER']}@{p['TEST_PG_HOST']}:{p['TEST_PG_PORT']}/{p['TEST_PG_NAME']}"
    start = time.monotonic()
    try:
        import psycopg2

        conn = psycopg2.connect(
            host=p["TEST_PG_HOST"],
            port=p["TEST_PG_PORT"],
            user=p["TEST_PG_USER"],
            password=p["TEST_PG_PASSWORD"],
            dbname=p["TEST_PG_NAME"],
            connect_timeout=5,
        )
        version_num = conn.server_version
        conn.close()
    except Exception as exc:  # noqa: BLE001 -- rapport, pas de masquage
        return StepResult(
            "pg", title, FAIL,
            summary=f"connexion impossible a {where} : {type(exc).__name__}: {exc}".strip(),
            duration=time.monotonic() - start,
        )
    major = version_num // 10000
    status = OK if major == PG_EXPECTED_MAJOR else FAIL
    return StepResult(
        "pg", title, status,
        summary=f"{where} -> serveur PostgreSQL {major} (server_version={version_num})",
        duration=time.monotonic() - start,
    )


def step_django_check() -> StepResult:
    return command_step(
        "check", "manage.py check (settings de test, comme ci.yml)",
        [sys.executable, "manage.py", "check", "--settings=config.settings.test"],
        clean_env(), "variables ci.yml, .env desactive",
    )


def step_makemigrations() -> StepResult:
    return command_step(
        "makemigrations", "Aucune migration manquante (makemigrations --check --dry-run)",
        [sys.executable, "manage.py", "makemigrations", "--check", "--dry-run",
         "--settings=config.settings.test"],
        clean_env(), "variables ci.yml, .env desactive",
    )


def step_migrate_empty_pg() -> StepResult:
    title = f"migrate depuis une base vide sur PostgreSQL {PG_EXPECTED_MAJOR}"
    import psycopg2
    from psycopg2 import sql

    p = _pg_params()

    def admin_conn():
        conn = psycopg2.connect(
            host=p["TEST_PG_HOST"], port=p["TEST_PG_PORT"], user=p["TEST_PG_USER"],
            password=p["TEST_PG_PASSWORD"], dbname=p["TEST_PG_NAME"], connect_timeout=5,
        )
        conn.autocommit = True
        return conn

    conn = admin_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", [MIGRATE_DB_NAME])
            if cur.fetchone():
                return StepResult(
                    "migrate", title, FAIL,
                    summary=(
                        f"la base {MIGRATE_DB_NAME} existe deja (execution precedente "
                        "interrompue ?). Supprimez-la a la main puis relancez."
                    ),
                )
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(MIGRATE_DB_NAME)))
    finally:
        conn.close()

    try:
        result = command_step(
            "migrate", title,
            [sys.executable, "manage.py", "migrate", "--noinput",
             "--settings=config.settings.test_pg"],
            clean_env({"TEST_PG_NAME": MIGRATE_DB_NAME}),
            f"variables ci.yml, .env desactive, TEST_PG_NAME={MIGRATE_DB_NAME} (base creee vide)",
        )
    finally:
        conn = admin_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(MIGRATE_DB_NAME)))
        finally:
            conn.close()
    return result


def _junit_counts(path: Path) -> tuple[dict[str, int], list[str]]:
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    skipped: list[str] = []
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    for suite in suites:
        for k in counts:
            counts[k] += int(suite.get(k, 0) or 0)
        for case in suite.iter("testcase"):
            sk = case.find("skipped")
            if sk is not None:
                name = f"{case.get('classname', '')}::{case.get('name', '')}"
                reason = (sk.get("message") or "").strip()
                skipped.append(f"{name} -- {reason}" if reason else name)
    return counts, skipped


def step_pytest(tmp: Path) -> tuple[StepResult, Path]:
    junit = tmp / "junit.xml"
    cov_json = tmp / "coverage.json"
    args = [
        sys.executable, "-m", "pytest",
        "--ds=config.settings.test_pg",
        "-rs",
        "-p", "no:cacheprovider",
        "--cov=.",
        "--cov-report=term-missing",
        f"--cov-report=json:{cov_json}",
        f"--cov-fail-under={GLOBAL_COVERAGE_MIN}",
        f"--junitxml={junit}",
    ]
    env = clean_env({"COVERAGE_FILE": str(tmp / ".coverage")})
    result = command_step(
        "pytest", "pytest sur PostgreSQL (--ds=config.settings.test_pg), 0 skipped exige",
        args, env, "variables ci.yml, .env desactive, .coverage en dossier temporaire",
    )
    code_ok = result.status == OK
    if junit.exists():
        counts, skipped = _junit_counts(junit)
        result.summary = (
            f"{result.summary} ; tests={counts['tests']} echecs={counts['failures']} "
            f"erreurs={counts['errors']} skipped={counts['skipped']}"
        )
        result.details = [f"skipped : {s}" for s in skipped]
        if counts["skipped"] != 0 or not code_ok:
            result.status = FAIL
    else:
        result.status = FAIL
        result.summary += " ; rapport junit absent"
    result.command = _display(args).replace(str(tmp), "<tmp>")
    return result, cov_json


def _is_test_file(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return name == "tests.py" or name.startswith(("tests_", "test_")) or "/tests/" in f"/{rel}"


def step_critical_coverage(cov_json: Path) -> StepResult:
    title = (
        f"Couverture >= {CRITICAL_COVERAGE_MIN:.0f} % : "
        + ", ".join(CRITICAL_APPS)
        + ", callback Orange, payments/services/*, orders/services/create_order.py"
        + " (hors fichiers de tests)"
    )
    if not cov_json.exists():
        return StepResult("coverage", title, NOT_RUN, summary="coverage.json absent (pytest non execute ?)")
    data = json.loads(cov_json.read_text(encoding="utf-8"))
    per_file: dict[str, tuple[int, int]] = {}
    for raw_path, info in data.get("files", {}).items():
        p = Path(raw_path.replace("\\", "/"))
        if p.is_absolute():
            try:
                p = p.relative_to(ROOT)
            except ValueError:
                continue
        rel = p.as_posix()
        s = info.get("summary", {})
        per_file[rel] = (int(s.get("covered_lines", 0)), int(s.get("num_statements", 0)))

    def pct(files: list[str]) -> tuple[float, int, int]:
        covered = sum(per_file[f][0] for f in files)
        total = sum(per_file[f][1] for f in files)
        return (100.0 * covered / total if total else 100.0), covered, total

    lines, all_ok = [], True
    for app in CRITICAL_APPS:
        files = [f for f in per_file if f.startswith(app + "/") and not _is_test_file(f)]
        value, cov, tot = pct(files)
        ok = tot > 0 and value >= CRITICAL_COVERAGE_MIN
        all_ok &= ok
        lines.append(f"{'OK   ' if ok else 'ECHEC'} {app}/ : {value:.1f} % ({cov}/{tot} lignes, {len(files)} fichiers)")
    prefixed = sorted(
        f for f in per_file
        if f.startswith(CRITICAL_FILE_PREFIXES) and not _is_test_file(f) and per_file[f][1] > 0
    )
    if not prefixed:
        all_ok = False
        lines.append("ECHEC " + ", ".join(CRITICAL_FILE_PREFIXES) + " : aucun fichier dans le rapport")
    for f in list(CRITICAL_FILES) + [f for f in prefixed if f not in CRITICAL_FILES]:
        if f not in per_file:
            all_ok = False
            lines.append(f"ECHEC {f} : absent du rapport de couverture")
            continue
        value, cov, tot = pct([f])
        ok = value >= CRITICAL_COVERAGE_MIN
        all_ok &= ok
        lines.append(f"{'OK   ' if ok else 'ECHEC'} {f} : {value:.1f} % ({cov}/{tot} lignes)")
    return StepResult(
        "coverage", title, OK if all_ok else FAIL,
        summary="voir le detail",
        details=lines,
    )


def step_check_deploy() -> StepResult:
    from django.core.management.utils import get_random_secret_key

    secret = get_random_secret_key()
    extra = {
        "ENVIRONMENT": "prod",
        "DJANGO_SETTINGS_MODULE": "config.settings.prod",
        "SECRET_KEY": secret,
        "ALLOWED_HOSTS": "release-check.invalid",
        # Seulement parsee par dj-database-url : check --deploy n'ouvre aucune
        # connexion a la base.
        "DATABASE_URL": "postgres://factice:factice@127.0.0.1:5432/factice",
    }
    result = command_step(
        "deploy", "manage.py check --deploy (settings prod, valeurs factices)",
        [sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING",
         "--settings=config.settings.prod"],
        clean_env(extra),
        "VALEURS FACTICES : ENVIRONMENT=prod, SECRET_KEY generee (get_random_secret_key, "
        "non enregistree), ALLOWED_HOSTS=release-check.invalid, "
        "DATABASE_URL=postgres://factice:***@127.0.0.1:5432/factice ; .env desactive",
    )
    result.output = result.output.replace(secret, "<SECRET_KEY factice masquee>")
    return result


def step_pip_audit() -> StepResult:
    return command_step(
        "pip-audit", "pip-audit sur requirements.txt (Phase 3)",
        [sys.executable, "-m", "pip_audit", "-r", "requirements.txt", "--desc", "on"],
        clean_env(), ".env desactive",
    )


def step_bandit(tmp: Path) -> StepResult:
    """Severite haute bloquante ; severite moyenne listee, non bloquante (a relire)."""
    report = tmp / "bandit.json"
    args = [
        sys.executable, "-m", "bandit", "-r", *BANDIT_TARGETS,
        "--severity-level", "medium", "-f", "json", "-o", str(report),
    ]
    result = command_step(
        "bandit", "bandit : severite haute bloquante, moyenne a relire (Phase 3)",
        args, clean_env(), ".env desactive",
    )
    result.command = _display(args).replace(str(tmp), "<tmp>")
    if not report.exists():
        result.status = FAIL
        result.summary += " ; rapport JSON absent"
        return result
    data = json.loads(report.read_text(encoding="utf-8"))
    highs, mediums = [], []
    for issue in data.get("results", []):
        where = Path(issue.get("filename", "")).as_posix().replace("\\", "/")
        line = (
            f"{issue.get('test_id', '?')} {where}:{issue.get('line_number', '?')} "
            f"(confiance {issue.get('issue_confidence', '?')}) -- {issue.get('issue_text', '').strip()}"
        )
        severity = (issue.get("issue_severity") or "").upper()
        if severity == "HIGH":
            highs.append(line)
        elif severity == "MEDIUM":
            mediums.append(line)
    errors = data.get("errors", [])
    result.details = (
        [f"HAUTE (bloquant) : {h}" for h in highs]
        + [f"MOYENNE (non bloquant, a relire) : {m}" for m in mediums]
        + [f"ERREUR bandit : {e.get('filename', '?')} -- {e.get('reason', '')}" for e in errors]
    )
    result.status = OK if not highs and not errors else FAIL
    result.summary = f"haute={len(highs)} (bloquant) ; moyenne={len(mediums)} (non bloquant) ; erreurs={len(errors)}"
    # Le JSON complet n'a pas sa place dans la sortie : le detail est ci-dessus.
    result.output = ""
    return result


# ── Rapport ───────────────────────────────────────────────────────────────────


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception:  # noqa: BLE001
        return "inconnu"


def write_report(release: str, results: list[StepResult], started: dt.datetime) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%d-%H%M%S")
    path = REPORTS_DIR / f"{release}_release_check_{stamp}.md"
    overall = OK if all(r.status == OK for r in results) else FAIL
    out = [
        f"# release_check — {release}",
        "",
        f"- Date (UTC) : {started.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Commit : `{git_sha()}`",
        f"- Python : {platform.python_version()} ({platform.system()})",
        "- `.env` : non lu (PYTHON_DOTENV_DISABLED=1, environnement en liste blanche)",
        "- `check --deploy` : **valeurs factices** (SECRET_KEY generee et non enregistree, "
        "ALLOWED_HOSTS et DATABASE_URL factices)",
        "- Non couvert par ce script : Celery worker + beat reels, gitleaks (bloquant "
        "Phase 0, manuel), OWASP ZAP (voir le suivi de release)",
        "",
        f"**Resultat global : {overall}**",
        "",
        "| Etape | Statut | Duree | Resume |",
        "|---|---|---|---|",
    ]
    for r in results:
        summary = r.summary.replace("|", "\\|").replace("\n", " ")
        out.append(f"| {r.title} | {r.status} | {r.duration:.1f} s | {summary} |")
    for r in results:
        out += ["", f"## {r.title}", "", f"Statut : **{r.status}**"]
        if r.command:
            out += ["", f"Commande : `{r.command}`"]
        if r.env_note:
            out += ["", f"Environnement : {r.env_note}"]
        if r.details:
            out += ["", *[f"- {d}" for d in r.details]]
        if r.output:
            out += ["", "```text", r.output.replace("```", "'''"), "```"]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--release", default="v1.0.0-rc1", help="nom de la release (defaut : v1.0.0-rc1)")
    args = parser.parse_args()
    # Console Windows (cp1252) : ne jamais planter sur un caractere non imprimable.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    started = dt.datetime.now(dt.timezone.utc)
    results: list[StepResult] = []

    def record(r: StepResult) -> StepResult:
        results.append(r)
        print(f"[{r.status:^11}] {r.title} -- {r.summary}", flush=True)
        return r

    print(f"release_check {args.release} -- depot : {ROOT}", flush=True)
    pg_ok = record(step_pg_preflight()).status == OK
    record(step_django_check())
    record(step_makemigrations())

    with tempfile.TemporaryDirectory(prefix="hf_release_check_") as tmp_dir:
        tmp = Path(tmp_dir)
        if pg_ok:
            record(step_migrate_empty_pg())
            pytest_result, cov_json = step_pytest(tmp)
            record(pytest_result)
            record(step_critical_coverage(cov_json))
        else:
            reason = "prerequis PostgreSQL non satisfait (voir la 1re etape)"
            for key, title in (
                ("migrate", f"migrate depuis une base vide sur PostgreSQL {PG_EXPECTED_MAJOR}"),
                ("pytest", "pytest sur PostgreSQL (--ds=config.settings.test_pg), 0 skipped exige"),
                ("coverage", f"Couverture >= {CRITICAL_COVERAGE_MIN:.0f} % (apps critiques, callback Orange)"),
            ):
                record(StepResult(key, title, NOT_RUN, summary=reason))

        record(step_check_deploy())
        record(step_pip_audit())
        record(step_bandit(tmp))

    report = write_report(args.release, results, started)
    overall_ok = all(r.status == OK for r in results)
    print(f"\nResultat global : {OK if overall_ok else FAIL}", flush=True)
    print(f"Rapport : {report.relative_to(ROOT).as_posix()}", flush=True)
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
