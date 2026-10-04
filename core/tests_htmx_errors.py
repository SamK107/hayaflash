"""F-92 : les erreurs HTMX 4xx/5xx des actions vendeur doivent etre visibles.

htmx 2 ne remplace pas le contenu sur une reponse 4xx : sans gestionnaire,
le vendeur ne voit rien quand une action echoue. `static/js/hf-base.js` doit
donc ecouter `htmx:responseError` et afficher le texte via le toast existant
(evenement `hf-toast`, rendu par x-text donc sans injection HTML).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

HF_BASE = Path(settings.BASE_DIR) / "static" / "js" / "hf-base.js"

# Execute le vrai hf-base.js avec un faux DOM, declenche les evenements htmx
# et renvoie en JSON les toasts emis.
NODE_HARNESS = textwrap.dedent(
    """
    const fs = require('fs');
    const vm = require('vm');
    const listeners = {};
    const toasts = [];
    const document = {
      cookie: '',
      body: { setAttribute() {} },
      addEventListener(name, fn) { (listeners[name] = listeners[name] || []).push(fn); },
      querySelectorAll() { return []; },
      querySelector() { return null; },
    };
    const window = {
      addEventListener() {},
      dispatchEvent(ev) { if (ev.type === 'hf-toast') toasts.push(ev.detail); },
    };
    class CustomEvent { constructor(type, init) { this.type = type; this.detail = (init || {}).detail; } }
    const ctx = { document, window, CustomEvent, navigator: {}, console, setTimeout };
    vm.createContext(ctx);
    vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
    const cases = JSON.parse(process.argv[2]);
    const out = [];
    for (const c of cases) {
      toasts.length = 0;
      const handlers = listeners[c.event] || [];
      for (const h of handlers) {
        h({ detail: { xhr: { status: c.status, responseText: c.text } } });
      }
      out.push({ handlers: handlers.length, toasts: toasts.slice() });
    }
    process.stdout.write(JSON.stringify(out));
    """
)


def _run(cases: list[dict]) -> list[dict]:
    result = subprocess.run(
        ["node", "-e", NODE_HARNESS, str(HF_BASE), json.dumps(cases)],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class HtmxErrorHandlerSourceTests(SimpleTestCase):
    def test_hf_base_listens_to_htmx_response_errors(self) -> None:
        src = HF_BASE.read_text(encoding="utf-8")
        self.assertIn("htmx:responseError", src)
        self.assertIn("hf-toast", src)
        # Le texte serveur ne doit jamais etre injecte comme HTML.
        self.assertNotIn("innerHTML", src)


class HtmxErrorHandlerBehaviourTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if shutil.which("node") is None:
            raise AssertionError("node est requis pour tester le JS (F-92).")

    def test_error_text_is_toasted_for_4xx(self) -> None:
        out = _run(
            [
                {"event": "htmx:responseError", "status": 400, "text": "Action non autorisée."},
                {"event": "htmx:responseError", "status": 403, "text": "Profil vendeur requis."},
            ]
        )
        self.assertEqual(
            out[0]["toasts"], [{"msg": "Action non autorisée.", "type": "error"}]
        )
        self.assertEqual(
            out[1]["toasts"], [{"msg": "Profil vendeur requis.", "type": "error"}]
        )

    def test_nothing_displayed_for_2xx(self) -> None:
        # htmx ne declenche pas responseError sur 2xx ; le gestionnaire doit de
        # toute facon rester muet si on l'appelle avec un statut de succes.
        out = _run([{"event": "htmx:responseError", "status": 200, "text": "<div>ok</div>"}])
        self.assertEqual(out[0]["toasts"], [])

    def test_fallback_message_when_body_empty_or_html(self) -> None:
        out = _run(
            [
                {"event": "htmx:responseError", "status": 500, "text": ""},
                {"event": "htmx:responseError", "status": 403, "text": "<!doctype html><h1>403</h1>"},
            ]
        )
        for case in out:
            self.assertEqual(len(case["toasts"]), 1)
            self.assertEqual(case["toasts"][0]["type"], "error")
            self.assertNotIn("<", case["toasts"][0]["msg"])
            self.assertTrue(case["toasts"][0]["msg"])

    def test_network_error_is_toasted(self) -> None:
        out = _run([{"event": "htmx:sendError", "status": 0, "text": ""}])
        self.assertEqual(len(out[0]["toasts"]), 1)
        self.assertEqual(out[0]["toasts"][0]["type"], "error")
