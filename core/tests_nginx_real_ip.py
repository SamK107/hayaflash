"""F-26 : le Nginx du conteneur recupere l'IP reelle du client derriere le proxy hote.

Sans set_real_ip_from actif, $remote_addr = la passerelle Docker : toutes les
limites par IP (limit_req) et verrous partageraient une seule cle pour tous les clients.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent
CONF = (ROOT / "infra/nginx/prod.conf").read_text(encoding="utf-8")
COMPOSE = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")


def _active_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]


class RealIpTests(SimpleTestCase):
    def test_set_real_ip_from_est_actif_et_parametre(self):
        self.assertIn("set_real_ip_from ${HF_REAL_IP_FROM};", _active_lines(CONF))

    def test_en_tete_et_recursion(self):
        active = _active_lines(CONF)
        self.assertTrue(any(ln.startswith("real_ip_header") and "X-Forwarded-For" in ln for ln in active))
        self.assertTrue(any(ln.startswith("real_ip_recursive") and ln.rstrip(";").endswith("on") for ln in active))

    def test_le_compose_fournit_la_variable_avec_une_plage_privee_par_defaut(self):
        match = re.search(r"HF_REAL_IP_FROM:\s*\$\{HF_REAL_IP_FROM:-([^}]+)\}", COMPOSE)
        self.assertIsNotNone(match, "HF_REAL_IP_FROM absente du service nginx")
        self.assertEqual(match.group(1), "172.16.0.0/12")

    def test_aucune_confiance_universelle(self):
        self.assertNotRegex(CONF, r"(?m)^\s*set_real_ip_from\s+(0\.0\.0\.0/0|all)\b")
