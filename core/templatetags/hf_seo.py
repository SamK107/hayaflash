"""Balises Open Graph par defaut de base.html (bloc og_meta)."""

from __future__ import annotations

from django import template
from django.template.loader_tags import BLOCK_CONTEXT_KEY
from django.templatetags.static import static
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag(takes_context=True)
def hf_block_text(context, name: str) -> str:
    """Contenu deja rendu d'un bloc de la page (ex. "title"), sur une ligne.

    Django interdit de declarer deux fois le meme bloc : ce tag permet de
    reprendre le titre / la meta description de la page dans og:title /
    og:description sans toucher aux templates enfants. Le rendu du bloc est
    deja echappe (autoescape) : on ne le re-echappe pas.
    """
    block_context = context.render_context.get(BLOCK_CONTEXT_KEY)
    block = block_context.get_block(name) if block_context is not None else None
    if block is None:
        return ""
    return mark_safe(" ".join(block.render(context).split()))


@register.simple_tag(takes_context=True)
def hf_page_url(context) -> str:
    """URL absolue de la page, sans query string (og:url, canonical)."""
    request = context.get("request")
    return request.build_absolute_uri(request.path) if request is not None else ""


@register.simple_tag(takes_context=True)
def hf_absolute_static(context, path: str) -> str:
    """URL absolue d'un fichier statique (og:image doit etre absolue)."""
    url = static(path)
    request = context.get("request")
    return request.build_absolute_uri(url) if request is not None else url
