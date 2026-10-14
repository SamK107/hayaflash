"""Documents versionnés du programme partenaires et identité de l'éditeur.

Chaque version publiée a son gabarit FIGÉ (``templates/partners/legal/*_v1_0.html``, ``*_v1_1.html``) :
pour changer un texte publié, créer une nouvelle version ; jamais éditer l'ancienne. ``PUBLISHED`` liste
toutes les versions publiées (type, version, gabarit) ; ``DOCS`` pointe sur la version courante, celle que
l'on propose à un nouveau partenaire. Les anciennes versions restent rendables (``version=...``) et
valides. Les tests ``VersionLockTests`` et ``tests_letter_v1_1`` verrouillent l'empreinte de chaque texte publié.

L'identité de l'éditeur vient de l'environnement (``LEGAL_ENTITY_*``) : jamais de valeur
inventée. Un document dont une valeur utilisée est vide est « incomplet » : l'acceptation
est refusée hors dev ; en dev, un bandeau « brouillon » l'annonce.
"""

from __future__ import annotations

import hashlib
import re

from django.conf import settings
from django.template.loader import render_to_string

TRIAL_LETTER_VERSION = "1.1"  # « lettre de phase d'évaluation » (F-135) ; la 1.0 « lettre d'essai » reste valide
PROGRAM_TERMS_VERSION = "1.0"
BRIEF_VERSION = "1.1"
BRIEF_STATUS = "brouillon"  # le brief est informatif : ce n'est pas un document à accepter

PLACEHOLDER = "(à renseigner)"
INCOMPLETE_MESSAGE = "Ce document n'est pas encore finalisé."

ENTITY_SETTINGS = {
    "name": "LEGAL_ENTITY_NAME",
    "form": "LEGAL_ENTITY_FORM",
    "capital": "LEGAL_ENTITY_CAPITAL",
    "address": "LEGAL_ENTITY_ADDRESS",
    "rccm": "LEGAL_ENTITY_RCCM",
    "contact": "LEGAL_ENTITY_CONTACT",
    "jurisdiction": "LEGAL_JURISDICTION",
}
ALL_FIELDS = tuple(ENTITY_SETTINGS)
# Le capital est FACULTATIF (entreprise individuelle) : exclu de la complétude, omis du texte s'il est vide.
OPTIONAL_FIELDS = ("capital",)
REQUIRED_FIELDS = tuple(k for k in ALL_FIELDS if k not in OPTIONAL_FIELDS)


def _template(name: str, version: str) -> str:
    return f"partners/legal/{name}_v{version.replace('.', '_')}.html"


# Toutes les versions publiées : type -> {version: gabarit}. Jamais de retrait ni de modification.
PUBLISHED = {
    "trial_letter": {
        "1.0": _template("trial_letter", "1.0"),
        "1.1": _template("trial_letter", "1.1"),
    },
    "program_terms": {
        "1.0": _template("program_terms", "1.0"),
    },
}

DOCS = {
    "trial_letter": {
        "version": TRIAL_LETTER_VERSION,
        "template": _template("trial_letter", TRIAL_LETTER_VERSION),
        "label": "Lettre d'évaluation",
        "fields": REQUIRED_FIELDS,
        "ack": f"J'ai lu et j'accepte la lettre de phase d'évaluation version {TRIAL_LETTER_VERSION}",
    },
    "program_terms": {
        "version": PROGRAM_TERMS_VERSION,
        "template": _template("program_terms", PROGRAM_TERMS_VERSION),
        "label": "Conditions du programme partenaire",
        "fields": REQUIRED_FIELDS,
        "ack": f"J'ai lu et j'accepte les conditions du programme partenaire version {PROGRAM_TERMS_VERSION}",
    },
}
BRIEF = {
    "version": BRIEF_VERSION,
    "template": _template("partner_brief", BRIEF_VERSION),
    "fields": ("name",),
}
CITE_SHOP_LABEL = "J'autorise HayaFlash à citer le nom de ma boutique comme utilisatrice ou utilisateur"


def _raw(key: str) -> str:
    return (getattr(settings, ENTITY_SETTINGS[key], "") or "").strip()


def entity_context(fields=ALL_FIELDS) -> dict[str, str]:
    """Valeurs de l'éditeur pour les gabarits ; « (à renseigner) » si vide (brouillon seulement).

    Le capital, facultatif, reste vide s'il n'est pas renseigné : le texte l'omet alors."""
    return {
        key: _raw(key) or ("" if key in OPTIONAL_FIELDS else PLACEHOLDER) for key in ENTITY_SETTINGS
    }


def missing_fields(doc_type: str) -> list[str]:
    return [ENTITY_SETTINGS[k] for k in DOCS[doc_type]["fields"] if not _raw(k)]


def is_complete(doc_type: str) -> bool:
    return not missing_fields(doc_type)


def acceptance_allowed(doc_type: str) -> bool:
    """Hors dev, un document incomplet ne peut pas être accepté."""
    return is_complete(doc_type) or getattr(settings, "ENVIRONMENT", "") == "dev"


def render_document(doc_type: str, partner, version: str | None = None) -> str:
    """Texte intégral du document (fragment HTML), tel qu'il est figé à l'acceptation.

    ``version`` : une version publiée (``PUBLISHED``) ; par défaut la courante (``DOCS``). KeyError
    si la version n'existe pas.

    Il s'arrête à la ligne d'identification : le cadre « Acceptation », le formulaire et la
    preuve d'acceptation sont rendus par les pages, jamais dans le texte figé."""
    template = DOCS[doc_type]["template"] if version is None else PUBLISHED[doc_type][version]
    return render_to_string(template, {"entity": entity_context(), "partner": partner})


def render_brief(*, places: int) -> str:
    # ``places`` reste fourni au gabarit mais le brief v1.1 ne l'affiche plus (F-135).
    return render_to_string(BRIEF["template"], {"entity": entity_context(), "places": places})


def canonical_text(html: str) -> str:
    """Forme canonique (espaces normalisés) servant à l'empreinte."""
    return " ".join(re.sub(r">\s+<", "><", html).split())


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
