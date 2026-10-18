"""Incident du 18/10 (12:57) : nginx redémarré au lieu d'être recréé.

Un `restart` ne relit ni le compose ni l'environnement du conteneur : la nouvelle variable
HF_REAL_IP_FROM n'a pas été prise en compte, nginx a bouclé (emerg set_real_ip_from).
deploy_vps.sh doit : (1) détecter tout changement de ce qui configure nginx par une
empreinte ; (2) valider la nouvelle config dans un conteneur jetable AVANT de remplacer le
conteneur en service ; (3) recréer (jamais redémarrer) ; (4) sinon nginx -t + reload.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "infra" / "scripts" / "deploy_vps.sh"
LIB = ROOT / "infra" / "scripts" / "lib_stack.sh"
BASH = shutil.which("bash")


def _code(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return [ln for ln in text.splitlines() if not ln.strip().startswith("#")]


class DeployScriptShapeTests(SimpleTestCase):
    def setUp(self):
        self.code = "\n".join(_code(DEPLOY))

    def test_jamais_de_restart_de_nginx(self):
        self.assertNotRegex(self.code, r"restart\s+nginx")

    def test_validation_jetable_avant_le_remplacement(self):
        validate = self.code.index("hf_nginx_validate_disposable ")
        recreate = self.code.index(chr(34) + "${COMPOSE[@]}" + chr(34) + " up -d --no-deps --force-recreate nginx")
        self.assertLess(validate, recreate)

    def test_echec_de_validation_arrete_sans_remplacer(self):
        block = self.code[self.code.index("hf_nginx_validate_disposable "):]
        first = block.split(chr(10), 1)[0]
        self.assertIn("hf_die", first)
        self.assertIn("PAS ete remplace", first)

    def test_chemin_sans_changement_garde_nginx_t_et_reload(self):
        self.assertIn("exec -T nginx nginx -s reload", self.code)
        self.assertRegex(self.code, r"exec -T nginx nginx -t")

    def test_conteneur_jetable_meme_service(self):
        lib = "\n".join(_code(LIB))
        self.assertRegex(lib, r'"\$\{COMPOSE\[@\]\}" run --rm --no-deps -T nginx nginx -t')

    def test_retour_arriere_recree_nginx(self):
        tail = self.code[self.code.index("Retour arriere"):]
        self.assertIn("run --rm --no-deps -T nginx nginx -t", tail)
        self.assertIn("up -d --no-deps --force-recreate nginx", tail)
        self.assertNotIn("restart nginx", tail)

    def test_dry_run_conserve_et_decrit_la_recreation(self):
        self.assertIn("--dry-run", self.code)
        self.assertIn("[dry-run] nginx : configuration changee", self.code)
        self.assertIn("[dry-run] nginx : configuration inchangee", self.code)

    def test_syntaxe_bash(self):
        if BASH is None:
            self.skipTest("bash absent")
        for path in (DEPLOY, LIB):
            res = subprocess.run([BASH, "-n", str(path)], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)

    def test_empreinte_ignoree_par_git(self):
        gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".hf_nginx_fingerprint", gi)


COMPOSE_CONFIG = """name: hayaflash
services:
  nginx:
    environment:
      HF_REAL_IP_FROM: {real_ip}
      PROD_DOMAIN: hayaflash.com
    image: nginx:1.27-alpine
  web:
    image: {web_image}
volumes:
  data: {{}}
"""


class FingerprintTests(SimpleTestCase):
    """hf_nginx_fingerprint avec un faux `docker` : seule la config de nginx compte."""

    def setUp(self):
        if BASH is None:
            self.skipTest("bash absent")
        import tempfile

        self.tmp = Path(tempfile.mkdtemp(prefix="hf-fp-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "bin").mkdir()
        (self.tmp / "stack" / "infra" / "nginx").mkdir(parents=True)
        (self.tmp / "stack" / "infra" / "nginx" / "prod.conf").write_text("server { listen 80; }\n")
        (self.tmp / "stack" / "docker-compose.production.yml").write_text("services: {}\n")
        (self.tmp / "stack" / ".env").write_text("X=1\n")
        fake = self.tmp / "bin" / "docker"
        fake.write_text('#!/bin/sh\ncat "$FAKE_COMPOSE_CONFIG"\n')
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.set_config()

    def set_config(self, real_ip="172.16.0.0/12", web_image="hayaflash:abc"):
        (self.tmp / "config.txt").write_text(
            COMPOSE_CONFIG.format(real_ip=real_ip, web_image=web_image), encoding="utf-8"
        )

    def fingerprint(self) -> str:
        env = {
            **os.environ,
            "PATH": f"{self.tmp / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "FAKE_COMPOSE_CONFIG": str(self.tmp / "config.txt"),
        }
        script = f'. "{LIB.as_posix()}"; hf_stack_init "{(self.tmp / "stack").as_posix()}"; hf_nginx_fingerprint'
        res = subprocess.run([BASH, "-c", script], capture_output=True, text=True, env=env)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = res.stdout.strip()
        self.assertRegex(out, r"^[0-9a-f]{64}$")
        return out

    def test_stable_si_rien_ne_change(self):
        self.assertEqual(self.fingerprint(), self.fingerprint())

    def test_variable_d_environnement_de_nginx_change_l_empreinte(self):
        before = self.fingerprint()
        self.set_config(real_ip="10.0.0.0/8")
        self.assertNotEqual(before, self.fingerprint())

    def test_nouvelle_variable_de_nginx_change_l_empreinte(self):
        """Le cas du 18/10 : variable ajoutée au service nginx dans le compose."""
        before = self.fingerprint()
        cfg = (self.tmp / "config.txt").read_text(encoding="utf-8")
        (self.tmp / "config.txt").write_text(
            cfg.replace("    image: nginx", "      NOUVELLE: 1\n    image: nginx"), encoding="utf-8"
        )
        self.assertNotEqual(before, self.fingerprint())

    def test_fichier_infra_nginx_change_l_empreinte(self):
        before = self.fingerprint()
        (self.tmp / "stack" / "infra" / "nginx" / "prod.conf").write_text("server { listen 81; }\n")
        self.assertNotEqual(before, self.fingerprint())

    def test_un_autre_service_ne_declenche_pas_de_recreation(self):
        before = self.fingerprint()
        self.set_config(web_image="hayaflash:def")
        self.assertEqual(before, self.fingerprint())

    def test_pas_de_motif_secret_dans_la_sortie(self):
        self.assertIsNone(re.search(r"hayaflash\.com", self.fingerprint()))
