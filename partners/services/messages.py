"""Messages WhatsApp aux partenaires : lien wa.me prérempli, AUCUN envoi automatique.

L'équipe ouvre WhatsApp dans un nouvel onglet et touche « Envoyer » elle-même. Le journal
(OutboundMessage) garde le texte avec le lien MASQUÉ : le jeton en clair n'est jamais stocké.
"""

from __future__ import annotations

import re
import secrets
import string
from dataclasses import dataclass
from urllib.parse import quote

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse

from core.countries import COUNTRIES, validate_international
from partners.models import (
    AccessLinkPurpose,
    OutboundMessage,
    Partner,
    PartnerPhase,
    PartnerStatus,
)
from partners.services.access_links import create_link
from partners.services.acceptance import places_left

MAX_LENGTH = 1000
MASKED_TOKEN = "(jeton non conservé)"
PREVIEW_LINK = "(lien privé généré à l'envoi)"
VAR_RE = re.compile(r"\{([^{}]+)\}")

TEMPLATES = {
    "invitation_essai": (
        "Bonjour {prénom},\n"
        "J'ai suivi ton live, bravo pour {détail à compléter par le staff}.\n"
        "Je suis {ton nom}, j'ai créé HayaFlash : une application malienne qui range les commandes "
        "de tes ventes en direct. Le client commande par un lien, avec son adresse, ou un vocal, ou "
        "sa position. Tu vois tout au même endroit, étape par étape.\n"
        "Je cherche quelques vendeurs pour l'essayer gratuitement pendant 30 jours (plan Pro offert), "
        "avec un accompagnement de ma part. En échange, je te demande un avis honnête chaque semaine.\n"
        "Si tu veux, je t'envoie la lettre d'essai à lire et accepter en ligne : {lien}\n"
        "Ça t'intéresse ?"
    ),
    "envoi_lettre_essai": "Voici la lettre d'essai à lire et accepter : {lien}",
    "envoi_conditions": (
        "Voici les conditions du programme partenaire : {lien}. Il reste {places} places."
    ),
    "relance": (
        "Bonjour {prénom}, je reviens vers toi au sujet de HayaFlash. "
        "As-tu pu lire le document que je t'ai envoyé ? Il est ici : {lien}"
    ),
}
LABELS = {
    "invitation_essai": "Invitation à l'essai",
    "envoi_lettre_essai": "Envoi de la lettre d'essai",
    "envoi_conditions": "Envoi des conditions du programme",
    "relance": "Relance (une seule, 3 jours après)",
}


def whatsapp_url(phone_e164: str, text: str) -> str:
    digits = re.sub(r"\D", "", phone_e164)
    return f"https://wa.me/{digits}?text={quote(text, safe='')}"


def parse_phone(country_code: str, national: str) -> str:
    """Numéro E.164 valide, ou ValidationError. Aucun pays n'est jamais deviné."""
    code = (country_code or "").strip().lstrip("+")
    if code not in {c.calling_code for c in COUNTRIES}:
        raise ValidationError("Choisissez l'indicatif du pays.")
    digits = re.sub(r"[\s().\-]", "", national or "")
    if not digits.isdigit():
        raise ValidationError("Numéro de téléphone invalide : chiffres uniquement.")
    e164, error = validate_international(f"+{code}{digits}")
    if e164 is None:
        raise ValidationError(error)
    return e164


def _fill(text: str, values: dict[str, str]) -> str:
    def sub(match):
        key = match.group(1).strip()
        return values[key] if key in values else match.group(0)

    return VAR_RE.sub(sub, text)


def _unresolved(text: str) -> list[str]:
    return ["{" + m.group(1) + "}" for m in VAR_RE.finditer(text)]


def _generate_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "HF" + "".join(secrets.choice(alphabet) for _ in range(6))
        if not Partner.objects.filter(code=code).exists():
            return code


@dataclass
class Prepared:
    url: str
    body: str  # texte final, avec le vrai lien (jamais stocké)
    outbound: OutboundMessage | None
    partner: Partner | None


def prepare(
    *,
    staff,
    country: str,
    national: str,
    first_name: str,
    shop_name: str,
    template_key: str,
    text: str,
    link_builder,
    preview: bool = False,
) -> Prepared:
    """Valide, puis (sauf aperçu) crée le prospect, le lien privé et la ligne de journal.

    ``link_builder(token)`` retourne l'URL absolue de la page du partenaire.
    """
    if template_key not in TEMPLATES:
        raise ValidationError("Choisissez un modèle de message.")
    phone = parse_phone(country, national)
    first_name = (first_name or "").strip()
    if not first_name:
        raise ValidationError("Indiquez le prénom du partenaire.")
    text = (text or "").strip()
    if not text:
        raise ValidationError("Le message est vide.")
    shop_name = (shop_name or "").strip()

    values = {
        "prénom": first_name,
        "places": str(places_left()),
        "ton nom": (getattr(staff, "display_name", "") or "").strip(),
    }
    if shop_name:
        values["boutique"] = shop_name
    has_link = "{lien}" in text
    check = _fill(text, {**values, "lien": PREVIEW_LINK})
    missing = _unresolved(check)
    if missing:
        raise ValidationError(
            "Complétez ou retirez avant d'envoyer : " + ", ".join(dict.fromkeys(missing)) + "."
        )

    if preview:
        return Prepared(url="", body=check, outbound=None, partner=None)

    with transaction.atomic():
        partner = Partner.objects.filter(phone=phone).first()
        if partner is None:
            partner = Partner.objects.create(
                name=first_name[:120],
                phone=phone,
                code=_generate_code(),
                status=PartnerStatus.PROSPECT,
                phase=PartnerPhase.NONE,
                shop_name=shop_name[:160],
            )
        real_link = masked_link = ""
        if has_link:
            _, token = create_link(
                partner, AccessLinkPurpose.ACCEPT, days=settings.PARTNER_ACCEPT_LINK_DAYS
            )
            real_link = link_builder(token)
            masked_link = link_builder(MASKED_TOKEN)
        body = _fill(text, {**values, "lien": real_link})
        if len(body) > MAX_LENGTH:
            raise ValidationError(
                "Le message dépasse 1 000 caractères : raccourcissez-le (limite du lien WhatsApp)."
            )
        stored = _fill(text, {**values, "lien": masked_link})
        outbound = OutboundMessage.objects.create(
            partner=partner,
            phone_e164=phone,
            template_key=template_key,
            body_text=stored,
            created_by=staff if getattr(staff, "pk", None) else None,
        )
    return Prepared(url=whatsapp_url(phone, body), body=body, outbound=outbound, partner=partner)


def partner_page_url(request, token: str) -> str:
    return request.build_absolute_uri(reverse("partner_doc_page", args=["TOKEN"])).replace("TOKEN", token)
