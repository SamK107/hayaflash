"""Les règles d'impression du programme partenaires ne touchent que ses pages.

Le bloc `@media print` de templates/base.html masquait nav/header/footer, le fond du body et le style
des liens sur TOUTES les pages du site. Il doit être limité aux pages qui contiennent le conteneur
`hf-p-wrap` (documents, preuves d'acceptation, pages équipe).
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from partners.tests_documents_admin import Base as StaffBase
from partners.tests_public_documents import Base as PublicBase
from partners.tests_public_documents import page

User = get_user_model()
SCOPE = "body:has(.hf-p-wrap)"
BARE_GLOBALS = {"nav", "header", "footer", "body", "html", "a", "[x-cloak]", "*", "main", "p", "img", "h1", "h2", "h3"}
SCOPED_RE = re.compile(r"^(body:has\(\.hf-p-wrap\)(\s|$)|\.hf-)")


def print_rules() -> list[tuple[str, str]]:
    css = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(encoding="utf-8")
    start = css.index("@media print")
    body = css[css.index("{", start) + 1 :]
    depth, end = 1, 0
    for i, ch in enumerate(body):
        depth += (ch == "{") - (ch == "}")
        if depth == 0:
            end = i
            break
    block = re.sub(r"/\*.*?\*/", "", body[:end], flags=re.S)  # commentaires CSS
    return [(m.group(1).strip(), m.group(2).strip()) for m in re.finditer(r"([^{}]+)\{([^}]*)\}", block)]


class PrintBlockIsScopedTests(SimpleTestCase):
    def test_no_selector_of_the_print_block_can_match_a_page_outside_the_programme(self):
        offenders = []
        for selectors, _ in print_rules():
            for selector in (s.strip() for s in selectors.split(",")):
                first = selector.split()[0] if selector else ""
                if selector in BARE_GLOBALS or first in BARE_GLOBALS or not SCOPED_RE.match(selector):
                    offenders.append(selector)
        self.assertEqual(offenders, [], "sélecteurs d'impression non limités aux pages du programme")

    def test_the_layout_elements_are_hidden_only_inside_the_programme_scope(self):
        hidden = [sel for sel, decl in print_rules() if "display: none" in decl]
        joined = " ".join(hidden)
        for tag in ("nav", "header", "footer"):
            self.assertIn(f"{SCOPE} {tag}", joined)
        self.assertIn(".hf-no-print", joined)

    def test_the_programme_keeps_its_current_print_rendering(self):
        rules = {sel.replace("\n", " "): decl for sel, decl in print_rules()}
        flat = " | ".join(f"{s} => {d}" for s, d in rules.items())
        for expected in (
            "background: #fff !important",       # fond blanc
            "box-shadow: none !important",       # cartes à plat
            "position: fixed",                   # référence en pied de page
            "width: 32mm",                       # QR imprimé
            "width: 48mm",                       # sceau
            "break-inside: avoid",               # cadre d'acceptation
            "text-decoration: none",             # liens
            "border: 2px solid #000",            # bandeau « à conserver »
        ):
            self.assertIn(expected, flat)
        self.assertTrue(any(SCOPE in sel and "background" in decl for sel, decl in rules.items()))
        self.assertTrue(any(sel.startswith(f"{SCOPE} a") for sel in rules))


class PagesOutsideTheProgrammeAreUnaffectedTests(TestCase):
    def test_home_and_login_have_no_programme_container_nor_print_only_classes(self):
        for url in ("/", reverse("login")):
            resp = Client().get(url)
            self.assertEqual(resp.status_code, 200, url)
            html = resp.content.decode()
            body = html.split("<body", 1)[1]
            self.assertNotIn("hf-p-wrap", body, url)
            self.assertNotIn("hf-no-print", body, url)
            self.assertNotIn("hf-print-ref", body, url)

    def test_the_scope_selector_cannot_match_home_or_login(self):
        # Le sélecteur `body:has(.hf-p-wrap)` exige le conteneur : absent de ces pages (test ci-dessus).
        self.assertTrue(all(SCOPE in sel or sel.startswith(".hf-") for selectors, _ in print_rules()
                            for sel in (s.strip() for s in selectors.split(","))))


class ProgrammePagesCarryTheContainerTests(PublicBase):
    def test_public_document_and_proof_pages_have_the_container(self):
        self.assertIn('class="hf-p-wrap"', self.client.get(page(self.token)).content.decode())
        self.accept_letter()
        self.assertIn('class="hf-p-wrap"', self.client.get(page(self.token)).content.decode())


class StaffPagesCarryTheContainerTests(StaffBase):
    def test_staff_pages_have_the_container(self):
        for name in ("partners_dashboard", "partners_list", "partners_documents", "partners_contact"):
            html = self.client.get(reverse(name)).content.decode()
            self.assertIn('class="hf-p-wrap"', html, name)
