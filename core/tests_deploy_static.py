"""Incident du 23/10 : 500 « Missing staticfiles manifest entry for 'js/hf-assist.js' ».

deploy_vps.sh lancait collectstatic APRES le demarrage de web : les processus gunicorn
avaient deja lu l'ancien manifeste et ne voyaient pas le nouveau fichier statique.
Regle : collectstatic dans un conteneur jetable AVANT `up -d ... web worker beat`.
"""

from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase

DEPLOY = Path(__file__).resolve().parents[1] / "infra" / "scripts" / "deploy_vps.sh"


def _code() -> str:
    text = DEPLOY.read_text(encoding="utf-8").replace("\r\n", "\n")
    return "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("#"))


class CollectstaticBeforeStartTests(SimpleTestCase):
    def test_collectstatic_avant_le_demarrage_de_web(self):
        code = _code()
        collect = code.index("run --rm --no-deps -T web python manage.py collectstatic --noinput")
        start = code.index("up -d --no-deps web worker beat")
        self.assertLess(collect, start)

    def test_plus_de_collectstatic_dans_le_conteneur_en_service(self):
        self.assertNotIn("exec -T web python manage.py collectstatic", _code())

    def test_migrate_reste_apres_le_demarrage(self):
        code = _code()
        self.assertLess(
            code.index("up -d --no-deps web worker beat"),
            code.index("exec -T web python manage.py migrate --noinput"),
        )
