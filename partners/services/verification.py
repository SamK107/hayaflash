"""Vérification publique d'une acceptation : code, QR et résumé sans donnée personnelle.

Le QR encode UNIQUEMENT l'URL absolue ``/verifier/<référence>/`` : ni jeton privé, ni nom, ni
téléphone. Le code est la référence imprimée (numéro d'acceptation + 12 premiers caractères de
l'empreinte du texte) ; il faut connaître les deux pour obtenir une réponse.
"""

from __future__ import annotations

import hmac
import re

import qrcode
import qrcode.image.svg
from django.urls import reverse

from partners import legal_docs
from partners.models import PartnerAcceptance

CODE_RE = re.compile(r"^(\d{1,9})-([0-9a-f]{12})$")
TOP_MAX_CHARS = 26  # au-delà, le texte du haut est réduit pour rester dans l'arc


def verify_url(request, acceptance: PartnerAcceptance) -> str:
    return request.build_absolute_uri(reverse("partner_verify", args=[acceptance.reference]))


def qr_svg(url: str) -> str:
    """QR en SVG inline (bibliothèque ``qrcode``), noir sur blanc, redimensionnable par CSS.

    Le fond blanc et la taille viennent de la classe ``hf-qr-svg`` (écran 140 px, impression
    32 mm) : le SVG n'a ni largeur ni hauteur propres."""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4
    )
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    svg = image.to_string(encoding="unicode")
    svg = re.sub(r"^<\?xml[^>]*\?>\s*", "", svg)
    root = re.match(r"<svg[^>]*>", svg).group(0)
    clean = re.sub(r'\s(?:width|height)="[^"]*"', "", root)
    clean = clean.replace("<svg", '<svg class="hf-qr-svg"', 1)
    return clean + svg[len(root):]


def find_acceptance(code: str) -> PartnerAcceptance | None:
    """Acceptation correspondant au code, ou None (inconnu, malformé : même résultat)."""
    match = CODE_RE.match(code or "")
    if not match:
        return None
    acceptance = (
        PartnerAcceptance.objects.select_related("partner").filter(pk=int(match.group(1))).first()
    )
    if acceptance is None:
        return None
    if not hmac.compare_digest(acceptance.text_sha256[:12], match.group(2)):
        return None
    return acceptance


def seal_context(acceptance: PartnerAcceptance) -> dict:
    """Textes du sceau circulaire (rendus depuis l'enregistrement, jamais dans le texte figé)."""
    top = f"HAYAFLASH · {legal_docs.entity_context()['name'].upper()}"
    size = 11.5 if len(top) <= TOP_MAX_CHARS else round(11.5 * TOP_MAX_CHARS / len(top), 1)
    return {
        "top_text": top,
        "top_size": size,
        "bottom_text": f"ACCEPTÉ · {acceptance.seal_date}",
        "version": f"v{acceptance.doc_version}",
        "reference": acceptance.reference,
    }


def initials(name: str) -> str:
    parts = [p for p in re.split(r"[\s\-']+", (name or "").strip()) if p]
    return " ".join(f"{p[0].upper()}." for p in parts[:3]) or "—"


def public_summary(acceptance: PartnerAcceptance) -> dict:
    """Ce que la page publique de vérification peut montrer : rien de personnel."""
    return {
        "doc_label": acceptance.get_doc_type_display(),
        "version": acceptance.doc_version,
        "accepted_at": acceptance.accepted_at_utc,
        "who": acceptance.partner.shop_name.strip() or initials(acceptance.signer_name),
        "sha256": acceptance.text_sha256,
        "valid": not acceptance.is_invalidated,
        "reference": acceptance.reference,
    }
