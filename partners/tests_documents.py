"""BLOCS H0 et H2 : vocabulaire, documents versionnés, complétude, verrou de version."""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

from partners import legal_docs
from partners.models import Partner
from partners.tests_models import make_partner

FACTICE = dict(
    LEGAL_ENTITY_NAME="ENTREPRISE TEST SARL",
    LEGAL_ENTITY_FORM="société à responsabilité limitée unipersonnelle",
    LEGAL_ENTITY_CAPITAL="1 000 000 FCFA",
    LEGAL_ENTITY_ADDRESS="12 rue de Test, Bamako",
    LEGAL_ENTITY_RCCM="ML-BKO-2026-B-00000",
    LEGAL_ENTITY_CONTACT="contact@test.example",
    LEGAL_JURISDICTION="le tribunal de commerce de Bamako",
)
BLANK = {k: "" for k in FACTICE}

# VERROU DE VERSION : empreinte du texte canonique de chaque version PUBLIEE, rendue avec
# FACTICE et un partenaire fictif. Toute modification d'un texte publié change l'empreinte
# et fait échouer le test : il faut alors créer une nouvelle version (v1_1, ...), jamais
# changer la constante.
LOCKED_HASHES = {
    ("trial_letter", "1.0"): "187ca2e0d84a84a4cf77eeb024c73f1143a6d8a6444380f84ada6b2a0583b019",
    ("program_terms", "1.0"): "3084d462f872c77ace9ace8a5aea70283812d1ba46d78a2b98da970d8d7c55e6",
}
BANNED_RE = re.compile(r"parrain|filleul|recommand", re.IGNORECASE)


def fake_partner() -> Partner:
    return Partner(name="Awa Diarra", phone="+22370000001", shop_name="Boutique Test")


class RenderTests(SimpleTestCase):
    @override_settings(**FACTICE)
    def test_documents_render_with_entity_and_partner_values(self):
        html = legal_docs.render_document("trial_letter", fake_partner())
        for expected in ("ENTREPRISE TEST SARL", "12 rue de Test, Bamako", "ML-BKO-2026-B-00000",
                         "Awa Diarra", "+22370000001", "Boutique Test", "contact@test.example",
                         "le tribunal de commerce de Bamako", "1 000 000 FCFA"):
            self.assertIn(expected, html)
        terms = legal_docs.render_document("program_terms", fake_partner())
        self.assertIn("ENTREPRISE TEST SARL", terms)
        self.assertIn("Article 8 bis", terms)

    @override_settings(**FACTICE)
    def test_no_bracket_is_ever_rendered(self):
        for doc_type in ("trial_letter", "program_terms"):
            html = legal_docs.render_document(doc_type, fake_partner())
            self.assertNotIn("[", html, doc_type)
            self.assertNotIn("]", html, doc_type)
        brief = legal_docs.render_brief(places=7)
        self.assertNotIn("[", brief)
        self.assertNotIn("]", brief)

    @override_settings(**BLANK)
    def test_no_bracket_with_empty_values_either(self):
        for doc_type in ("trial_letter", "program_terms"):
            html = legal_docs.render_document(doc_type, fake_partner())
            self.assertNotIn("[", html)
            self.assertNotIn("]", html)
            self.assertIn("(à renseigner)", html)

    @override_settings(**FACTICE)
    def test_missing_shop_name_is_not_a_bracket(self):
        p = fake_partner()
        p.shop_name = ""
        html = legal_docs.render_document("trial_letter", p)
        self.assertIn("(non renseignée)", html)

    @override_settings(**FACTICE)
    def test_partner_values_are_escaped(self):
        p = fake_partner()
        p.name = "<script>alert(1)</script>"
        html = legal_docs.render_document("trial_letter", p)
        self.assertNotIn("<script>", html)

    @override_settings(**FACTICE)
    def test_brief_is_a_draft_and_shows_remaining_places(self):
        brief = legal_docs.render_brief(places=7)
        self.assertIn("Il reste 7 places", brief)
        self.assertIn("ENTREPRISE TEST SARL", brief)
        self.assertEqual(legal_docs.BRIEF_STATUS, "brouillon")


class CompletenessTests(SimpleTestCase):
    @override_settings(**FACTICE)
    def test_complete_when_every_used_value_is_set(self):
        for doc_type in ("trial_letter", "program_terms"):
            self.assertTrue(legal_docs.is_complete(doc_type))
            self.assertEqual(legal_docs.missing_fields(doc_type), [])

    @override_settings(**BLANK)
    def test_incomplete_when_values_are_empty(self):
        self.assertFalse(legal_docs.is_complete("trial_letter"))
        self.assertIn("LEGAL_ENTITY_RCCM", legal_docs.missing_fields("program_terms"))

    def test_one_missing_value_is_enough(self):
        with override_settings(**{**FACTICE, "LEGAL_JURISDICTION": "  "}):
            self.assertFalse(legal_docs.is_complete("trial_letter"))
            self.assertEqual(legal_docs.missing_fields("trial_letter"), ["LEGAL_JURISDICTION"])

    def test_acceptance_blocked_outside_dev_only(self):
        with override_settings(**BLANK, ENVIRONMENT="prod"):
            self.assertFalse(legal_docs.acceptance_allowed("trial_letter"))
        with override_settings(**BLANK, ENVIRONMENT="staging"):
            self.assertFalse(legal_docs.acceptance_allowed("trial_letter"))
        with override_settings(**BLANK, ENVIRONMENT="dev"):
            self.assertTrue(legal_docs.acceptance_allowed("trial_letter"))
        with override_settings(**FACTICE, ENVIRONMENT="prod"):
            self.assertTrue(legal_docs.acceptance_allowed("trial_letter"))

    def test_settings_default_to_empty_except_the_editor_name(self):
        import importlib
        import os

        base = importlib.import_module("config.settings.base")
        # Valeur de l'environnement local si elle existe, sinon le défaut du code.
        defaults = {"NAME": "ABEXPERTISES"}
        for name in ("NAME", "FORM", "CAPITAL", "ADDRESS", "RCCM", "CONTACT"):
            expected = (os.environ.get(f"LEGAL_ENTITY_{name}") or defaults.get(name, "")).strip()
            self.assertEqual(getattr(base, f"LEGAL_ENTITY_{name}"), expected, name)
        self.assertEqual(base.LEGAL_JURISDICTION, (os.environ.get("LEGAL_JURISDICTION") or "").strip())

    def test_env_example_lists_the_variables_without_value(self):
        text = (Path(settings.BASE_DIR) / ".env.example").read_text(encoding="utf-8")
        for key in FACTICE:
            self.assertRegex(text, rf"(?m)^{key}=\s*$")


NO_CAPITAL = {**FACTICE, "LEGAL_ENTITY_CAPITAL": ""}


class OptionalCapitalTests(SimpleTestCase):
    """L'éditeur est une entreprise individuelle : le capital est facultatif."""

    @override_settings(**NO_CAPITAL)
    def test_completeness_ignores_the_capital(self):
        for doc_type in ("trial_letter", "program_terms"):
            self.assertTrue(legal_docs.is_complete(doc_type), doc_type)
            self.assertNotIn("LEGAL_ENTITY_CAPITAL", legal_docs.missing_fields(doc_type))

    @override_settings(**NO_CAPITAL)
    def test_render_without_capital_has_no_orphan_comma_nor_bracket(self):
        for doc_type in ("trial_letter", "program_terms"):
            html = legal_docs.canonical_text(legal_docs.render_document(doc_type, fake_partner()))
            self.assertNotIn("capital ", html.lower())
            self.assertNotIn(", ,", html)
            self.assertNotIn(" ,", html)
            self.assertNotIn(",,", html)
            self.assertNotIn("[", html)
            self.assertNotIn("]", html)
            self.assertIn("société à responsabilité limitée unipersonnelle, siège 12 rue de Test, Bamako", html)
            self.assertNotIn("(à renseigner)", html)

    @override_settings(**FACTICE)
    def test_render_with_capital_still_shows_it(self):
        html = legal_docs.canonical_text(legal_docs.render_document("trial_letter", fake_partner()))
        self.assertIn("unipersonnelle, capital 1 000 000 FCFA, siège 12 rue de Test", html)

    @override_settings(**{**FACTICE, "LEGAL_ENTITY_FORM": ""})
    def test_the_form_stays_mandatory(self):
        self.assertFalse(legal_docs.is_complete("trial_letter"))
        self.assertEqual(legal_docs.missing_fields("trial_letter"), ["LEGAL_ENTITY_FORM"])

    @override_settings(**BLANK)
    def test_blank_capital_never_shows_a_placeholder(self):
        self.assertEqual(legal_docs.entity_context()["capital"], "")


class NoWrongLegalFormTests(SimpleTestCase):
    def test_no_suarl_left_in_the_programme(self):
        from pathlib import Path

        wrong = "SUA" + "RL"  # écrit en deux morceaux pour que ce fichier ne se signale pas lui-même
        base = Path(settings.BASE_DIR)
        offenders = []
        for root in (base / "partners", base / "templates" / "partners"):
            for path in root.rglob("*"):
                if path.suffix in (".py", ".html", ".md", ".txt") and path.is_file():
                    if wrong in path.read_text(encoding="utf-8", errors="ignore"):
                        offenders.append(str(path.relative_to(base)))
        self.assertEqual(offenders, [])

    @override_settings(**FACTICE)
    def test_documents_and_messages_use_the_variable_not_a_literal_name(self):
        from partners.services.messages import TEMPLATES

        html = legal_docs.render_document("trial_letter", fake_partner())
        self.assertEqual(html.count("ENTREPRISE TEST SARL"), 3)  # en-tête, phrase de preuve, identification de clôture
        self.assertNotIn("ABEXPERTISES", html)
        for text in TEMPLATES.values():
            self.assertNotIn("ABEXPERTISES", text)


SENTENCE = (
    "En envoyant, vous acceptez ce document dans sa version 1.0. HayaFlash conserve la date, "
    "l'heure, le texte accepté et l'empreinte de votre adresse IP."
)


class ClosingBlockTests(SimpleTestCase):
    """Bloc de clôture : « Fin du document », identification, bloc d'acceptation."""

    def render(self, doc_type):
        if doc_type == "brief":
            return legal_docs.canonical_text(legal_docs.render_brief(places=5))
        return legal_docs.canonical_text(legal_docs.render_document(doc_type, fake_partner()))

    @override_settings(**FACTICE)
    def test_end_marker_and_identification_in_the_three_documents(self):
        ident = (
            "ENTREPRISE TEST SARL, société à responsabilité limitée unipersonnelle, "
            "RCCM ML-BKO-2026-B-00000, 12 rue de Test, Bamako. Version 1.0."
        )
        for doc_type in ("trial_letter", "program_terms", "brief"):
            html = self.render(doc_type)
            self.assertIn("Fin du document", html, doc_type)
            self.assertIn(ident, html, doc_type)
            self.assertLess(html.index("Fin du document"), html.index(ident), doc_type)

    @override_settings(**FACTICE)
    def test_closing_comes_after_the_last_article(self):
        letter = self.render("trial_letter")
        self.assertLess(letter.index("7. Droit applicable"), letter.index("Fin du document"))
        terms = self.render("program_terms")
        self.assertLess(terms.index("Article 14."), terms.index("Fin du document"))

    @override_settings(**FACTICE)
    def test_frozen_text_stops_at_the_identification_line(self):
        for doc_type in ("trial_letter", "program_terms"):
            html = self.render(doc_type)
            self.assertNotIn("hf-doc-accept", html, doc_type)
            self.assertNotIn("<h3>Acceptation</h3>", html, doc_type)
            self.assertNotIn("En envoyant, vous acceptez", html, doc_type)
            self.assertTrue(html.endswith("Version 1.0.</p></div>"), doc_type)
        self.assertNotIn("hf-doc-accept", self.render("brief"))

    @override_settings(**FACTICE)
    def test_snapshot_text_has_no_form_fields(self):
        for doc_type in ("trial_letter", "program_terms"):
            html = self.render(doc_type)
            for forbidden in ("<form", "<input", "<button", "csrfmiddlewaretoken", "Accepter et envoyer"):
                self.assertNotIn(forbidden, html, (doc_type, forbidden))

    @override_settings(**FACTICE)
    def test_documents_never_mention_the_ip_address(self):
        for doc_type in ("trial_letter", "program_terms", "brief"):
            html = self.render(doc_type)
            self.assertIsNone(re.search(r"\bIP\b", html), doc_type)
            self.assertNotIn("adresse IP", html)
            self.assertIn("données techniques de connexion", self.render("trial_letter"))

    def test_empty_values_are_omitted_cleanly(self):
        from django.template.loader import render_to_string

        empty = {"name": "ENTREPRISE TEST", "form": "", "capital": "", "address": "", "rccm": "",
                 "contact": "c@test.example", "jurisdiction": "le tribunal"}
        for doc_type in ("trial_letter", "program_terms"):
            html = legal_docs.canonical_text(
                render_to_string(legal_docs.DOCS[doc_type]["template"], {"entity": empty, "partner": fake_partner()})
            )
            self.assertIn("ENTREPRISE TEST. Version 1.0.", html, doc_type)
            html = html.split("Fin du document")[1]
            self.assertNotIn(", ,", html)
            self.assertNotIn(",,", html)
            self.assertNotIn(", .", html)
            self.assertNotIn("RCCM ,", html)
        brief = legal_docs.canonical_text(
            render_to_string(legal_docs.BRIEF["template"], {"entity": empty, "places": 3})
        )
        self.assertIn("ENTREPRISE TEST. Version 1.0.", brief)
        self.assertNotIn(", .", brief)

    @override_settings(**BLANK)
    def test_blank_settings_never_leave_orphans_or_brackets(self):
        for doc_type in ("trial_letter", "program_terms", "brief"):
            html = self.render(doc_type)
            self.assertNotIn("[", html)
            self.assertNotIn("]", html)
            self.assertNotIn(", ,", html)
            self.assertNotIn(",,", html)
            self.assertNotIn(" ,", html)

    @override_settings(**NO_CAPITAL)
    def test_no_capital_in_the_identification_line(self):
        for doc_type in ("trial_letter", "program_terms", "brief"):
            self.assertNotIn("capital", self.render(doc_type).lower().split("fin du document")[1])

    @override_settings(**FACTICE)
    def test_brief_keeps_its_footer_mention(self):
        html = self.render("brief")
        self.assertIn("Ce document résume les conditions", html)
        self.assertIn("font foi", html)
        self.assertLess(html.index("Fin du document"), html.index("Ce document résume les conditions"))

    def test_styles_for_the_frame_the_end_marker_and_the_print_version(self):
        css = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(encoding="utf-8")
        for selector in (".hf-doc-end", ".hf-doc-accept", ".hf-p-btn--lg", ".hf-seal", ".hf-print-ref", ".hf-keep-banner"):
            self.assertIn(selector, css)
        print_block = css.split("@media print", 1)[1]
        self.assertIn(".hf-print-ref", print_block)
        self.assertIn("position: fixed", print_block)


class VersionLockTests(SimpleTestCase):
    def test_versions_are_declared(self):
        self.assertEqual(legal_docs.TRIAL_LETTER_VERSION, "1.0")
        self.assertEqual(legal_docs.PROGRAM_TERMS_VERSION, "1.0")

    @override_settings(**FACTICE)
    def test_published_texts_never_change(self):
        for (doc_type, version), expected in LOCKED_HASHES.items():
            self.assertEqual(legal_docs.DOCS[doc_type]["version"], version)
            html = legal_docs.render_document(doc_type, fake_partner())
            actual = legal_docs.sha256_of(legal_docs.canonical_text(html))
            self.assertEqual(
                actual,
                expected,
                f"Le texte de {doc_type} v{version} a changé : créez une nouvelle version "
                f"(gabarit v1_1...), ne modifiez pas un texte publié.",
            )

    def test_every_version_has_its_own_frozen_template(self):
        for doc_type, doc in legal_docs.DOCS.items():
            self.assertIn("_v" + doc["version"].replace(".", "_"), doc["template"])
            self.assertTrue((Path(settings.BASE_DIR) / "templates" / doc["template"]).exists())


class VocabularyTests(TestCase):
    """H0 : pas de « parrain / filleul / recommand* » dans le vocabulaire du programme."""

    def test_templates_partners_are_clean(self):
        offenders = []
        for path in (Path(settings.BASE_DIR) / "templates" / "partners").rglob("*.html"):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if BANNED_RE.search(line):
                    offenders.append(f"{path.name}:{n}: {line.strip()[:80]}")
        self.assertEqual(offenders, [])

    @override_settings(**FACTICE)
    def test_rendered_documents_are_clean(self):
        for doc_type in ("trial_letter", "program_terms"):
            self.assertIsNone(BANNED_RE.search(legal_docs.render_document(doc_type, fake_partner())), doc_type)
        self.assertIsNone(BANNED_RE.search(legal_docs.render_brief(places=3)))

    def test_statement_and_partner_csv_are_clean(self):
        from partners.services.payouts import partner_csv, statement_text
        from partners.tests_payouts import Base as PayoutBase

        class _T(PayoutBase):
            def runTest(self):  # pragma: no cover - utilisé comme fabrique de données
                pass

        t = _T()
        t.setUp()
        try:
            t.entry(commission=2500)
            self.assertIsNone(BANNED_RE.search(statement_text(t.partner, "2026-10")))
            self.assertIsNone(BANNED_RE.search(partner_csv(t.partner, "2026-10")[0]))
            self.assertIsNone(BANNED_RE.search(statement_text(t.partner, "2030-01")))  # mois vide
        finally:
            pass

    def test_message_templates_are_clean(self):
        from partners.services.messages import TEMPLATES

        for key, text in TEMPLATES.items():
            self.assertIsNone(BANNED_RE.search(text), key)

    def test_model_labels_are_clean(self):
        from partners import models

        for name in ("Partner", "PartnerClick", "Referral", "CommissionEntry", "Payout",
                     "PartnerAcceptance", "OutboundMessage", "PartnerAccessLink"):
            model = getattr(models, name)
            labels = [str(model._meta.verbose_name), str(model._meta.verbose_name_plural)]
            labels += [str(f.verbose_name) for f in model._meta.get_fields() if hasattr(f, "verbose_name")]
            for label in labels:
                self.assertIsNone(BANNED_RE.search(label), f"{name}: {label}")


class PrintStylesTests(SimpleTestCase):
    def test_print_stylesheet_exists_and_hides_menu(self):
        css = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(encoding="utf-8")
        self.assertIn("@media print", css)
        self.assertIn(".hf-no-print", css)
        self.assertIn(".hf-doc", css)


class LegalDocsTemplateGuard(SimpleTestCase):
    def test_make_partner_helper_is_importable(self):
        self.assertTrue(callable(make_partner))
