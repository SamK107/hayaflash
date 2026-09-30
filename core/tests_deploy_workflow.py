"""F-09 : le deploiement se fait au SHA exact de l'image, jamais `git pull`.

L'image est taguee au SHA (${{ github.sha }}) ; `git pull origin main` sur le VPS
pouvait rapatrier un commit plus recent (scripts, docker-compose) que celui de
l'image deployee. Lecture texte du workflow (pas de dependance YAML).
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "deploy.yml"


def _job(text: str, name: str) -> str:
    """Bloc d'un job : de `  <name>:` au job suivant (indentation 2) ou fin."""
    match = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  [a-z][\w-]*:\n|\Z)", text, re.S | re.M)
    assert match, f"job {name} introuvable"
    return match.group(1)


class DeployWorkflowTests(SimpleTestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8").replace("\r\n", "\n")

    def test_deploy_jobs_check_out_the_exact_sha_not_pull(self):
        for name in ("deploy-staging", "deploy-prod"):
            with self.subTest(job=name):
                job = _job(self.text, name)
                self.assertNotRegex(job, r"git\s+pull", "git pull deploie un commit imprevu")
                self.assertRegex(job, r"git\s+fetch\s+.*origin")
                self.assertRegex(job, r"git\s+checkout\s+--detach\s+\"?\$\{\{\s*github\.sha\s*\}\}\"?")

    def test_checkout_precedes_the_deploy_script_and_uses_the_image_tag(self):
        for name in ("deploy-staging", "deploy-prod"):
            with self.subTest(job=name):
                job = _job(self.text, name)
                checkout = job.index("git checkout")
                deploy = job.index("deploy.sh")
                self.assertLess(checkout, deploy)  # la version du script = celle du SHA
                self.assertIn('HAYAFLASH_TAG="${{ github.sha }}"', job)

    def test_the_deploy_pause_is_untouched(self):
        for name in ("deploy-staging", "deploy-prod"):
            with self.subTest(job=name):
                self.assertRegex(_job(self.text, name), r"(?m)^    if: false$")

    def test_staging_smoke_test_gets_the_public_host(self):
        """F-52 : deploy.sh vise 127.0.0.1:8010 ; sans SMOKE_HOST, Django refuse le
        Host « 127.0.0.1 » (ALLOWED_HOSTS) et le smoke test echoue toujours."""
        job = _job(self.text, "deploy-staging")
        match = re.search(r"SMOKE_HOST=\"?\$\{\{\s*secrets\.\w+\s*\}\}\"?", job)
        self.assertIsNotNone(match, "SMOKE_HOST absent du job deploy-staging")
        self.assertLess(match.start(), job.index("deploy.sh"))

    def test_prod_smoke_test_uses_the_public_url(self):
        # deploy-prod teste par le domaine public : le Host est celui de l'URL.
        job = _job(self.text, "deploy-prod")
        self.assertRegex(job, r"deploy\.sh\s+https://\$\{\{\s*secrets\.PROD_DOMAIN\s*\}\}")
