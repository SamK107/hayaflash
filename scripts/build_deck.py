"""Construit docs/presentation/HayaFlash_Distrib_Grossistes.pptx (presentation commerciale grossistes).

    .venv\\Scripts\\python.exe scripts/build_deck.py

Sources : demo_captures/*.png (voir scripts/demo_captures.py). Format 16:9, texte >= 28 pt, aucune animation.
Une slide = un titre-benefice, une capture, au plus 3 reperes numerotes ; le texte oral est dans les notes.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
CAPTURES = ROOT / "demo_captures"
OUT = ROOT / "docs" / "presentation" / "HayaFlash_Distrib_Grossistes.pptx"

RED = RGBColor(0xE6, 0x39, 0x46)
GOLD = RGBColor(0xFF, 0xB8, 0x00)
DARK = RGBColor(0x1F, 0x29, 0x37)
GREY = RGBColor(0x6B, 0x72, 0x80)
LIGHT = RGBColor(0xF5, 0xF5, 0xF5)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
MIN_PT = 28
FONT = "Calibri"
# Captures dont le bas est vide : on ne garde que le haut (fraction de la hauteur).
CROPS = {"12-revendeuse-page-publique-de-la-boutique": 0.66}

# (fichier, titre, [reperes], notes)
SECTIONS = [
    ("Qui vend : vos revendeuses, en direct", [
        ("12-revendeuse-page-publique-de-la-boutique",
         "Chaque revendeuse a sa boutique en ligne",
         ["Sa boutique HayaFlash", "Sa vente flash « LIVE »", "Partage en un clic sur WhatsApp"],
         "Avant de parler de vous, voyons qui vend. Vos produits sont vendus par des revendeuses. Chacune a sa boutique en ligne sur HayaFlash, "
         "et elle y lance des ventes flash : des ventes courtes, en direct. Elle les partage sur WhatsApp à ses clientes."),
        ("21-cliente-page-de-vente-cote-cliente-1sur3",
         "La cliente voit vos produits et commande",
         ["Vente « EN DIRECT » avec compte à rebours", "Vos produits, photos et prix", "Commande en quelques secondes"],
         "Voici la vente flash vue par la cliente, sur son téléphone. Le compte à rebours crée l'urgence. Elle voit vos produits avec leurs photos et leurs prix, "
         "et elle commande sans créer de compte. C'est ce que vos revendeuses font pour vous, et ce que nous allons suivre côté grossiste."),
    ]),
    ("Pour le grossiste", [
        ("01-grossiste-tableau-de-bord-grossiste-accueil-1sur2",
         "Votre activité en direct, sans appeler personne",
         ["Commandes du jour", "Stock vendu et restant", "Mise à jour automatique"],
         "Voici votre écran d'accueil. Il se met à jour tout seul : vous voyez les commandes et le stock sans téléphoner à personne. "
         "Fini les appels pour savoir où en sont les ventes."),
        ("02-grossiste-catalogue-de-gros-1sur3",
         "Vous fixez le prix de gros et le prix minimum de vente",
         ["Vos produits avec photos", "Prix de gros", "Prix de vente minimum protégé"],
         "Vous créez votre catalogue une seule fois. Vous choisissez votre prix de gros et le prix en dessous duquel la revendeuse ne peut pas vendre. "
         "Votre marque et vos prix restent protégés."),
        ("03-grossiste-liste-des-revendeuses-1sur2",
         "Vous invitez vos revendeuses en quelques clics",
         ["Invitation par lien", "Liste de vos revendeuses", "Statut de chacune"],
         "Vous invitez une revendeuse avec un simple lien. Quand elle accepte, elle apparaît ici. "
         "Vous savez toujours avec qui vous travaillez."),
        ("04-grossiste-stock-alloue-1sur3",
         "Vous savez où est chaque pièce",
         ["Total, alloué, vendu", "Quantité par revendeuse", "Allouer ou reprendre"],
         "Pour chaque produit, vous voyez ce qui est chez chaque revendeuse, ce qui est vendu et ce qui reste. "
         "Vous donnez du stock quand elle vend bien, et vous le reprenez si elle ne vend pas."),
        ("05-grossiste-commandes-toutes-1sur3",
         "Toutes les commandes de vos produits au même endroit",
         ["Une ligne par commande", "Filtre par statut", "Filtre par revendeuse"],
         "Toutes les commandes de vos produits arrivent ici, quelle que soit la revendeuse. "
         "Vous filtrez en un clic pour voir ce qui est en livraison, livré ou payé."),
        ("09-grossiste-releves-et-versements-de-marges-1sur3",
         "Un relevé chaque lundi, déjà calculé",
         ["Un relevé par revendeuse", "Montant calculé, rien à saisir", "Référence Orange Money"],
         "Chaque lundi, le système prépare un relevé par revendeuse. Le montant est calculé, vous n'avez rien à compter. "
         "Vous payez en une fois avec Orange Money et vous notez la référence."),
        ("09-grossiste-releves-et-versements-de-marges-2sur3",
         "Vous réglez le relevé et notez la référence Orange Money",
         ["Relevé à régler, montant calculé", "Référence Orange Money + « Payé »", "Relevé déjà payé : en attente de la revendeuse"],
         "Vous payez la revendeuse avec Orange Money, hors de l'application. Ensuite, vous notez ici la référence du paiement et vous cliquez sur Payé. "
         "Le relevé passe en attente : la revendeuse va confirmer qu'elle a bien reçu l'argent."),
        ("10-grossiste-releve-a-regler-detail-par-livraison",
         "Chaque marge est justifiée, livraison par livraison",
         ["Produit et quantité", "Commande et date de confirmation", "Marge de la revendeuse"],
         "Si une revendeuse demande « pourquoi ce montant ? », la réponse est ici. "
         "Chaque ligne montre la commande, la date et la marge. Plus de dispute."),
    ]),
    ("Pour la revendeuse", [
        ("18-revendeuse-mes-grossistes",
         "Elle voit ses grossistes et leurs catalogues",
         ["Ses grossistes", "Leurs catalogues", "Son stock reçu"],
         "Côté revendeuse, tout part de ses grossistes. Elle ouvre votre catalogue depuis son téléphone. "
         "Elle n'a pas besoin de stock chez elle pour commencer."),
        ("19-revendeuse-stock-recu-du-grossiste-1sur3",
         "Elle choisit ses produits et fixe son prix",
         ["Prix de gros affiché", "Son prix de vente", "Stock alloué par vous"],
         "Elle choisit les produits qu'elle veut vendre et fixe son prix, au-dessus de votre minimum. "
         "Vous gardez la main sur la quantité que vous lui donnez."),
        ("13-revendeuse-vente-en-cours-lien-de-partage-et-qr-code-1sur2",
         "Elle partage sa vente par WhatsApp ou QR code",
         ["Lien de la vente", "Bouton WhatsApp", "QR code à montrer"],
         "Elle lance une vente et la partage sur WhatsApp en un clic. Elle peut aussi montrer un QR code. "
         "Vos produits atteignent plus de clientes, sans effort pour vous."),
        ("20-revendeuse-mes-gains-1sur2",
         "Elle sait ce qu'elle a gagné et ce qui reste dû",
         ["Ventes en cours", "Restant dû", "Reçu ce mois"],
         "Elle voit ses marges en cours, confirmées et déjà versées. "
         "Une revendeuse qui voit ses gains vend plus, et elle vous réclame moins."),
    ]),
    ("Le Marché", [
        ("24-marche-marche-ventes-en-direct-1sur3",
         "Sur téléphone, le Marché fonctionne pareil",
         ["Ventes en cours", "Ventes à venir", "Mise à jour automatique"],
         "Le Marché montre toutes les ventes en direct et à venir. Une cliente qui ne connaît aucune revendeuse peut quand même vous trouver. "
         "C'est de la visibilité en plus."),
    ]),
    ("Le cycle de livraison", [
        ("16-revendeuse-commandes-dashboard-live-1sur3",
         "La revendeuse voit la commande arriver en direct",
         ["Nouvelle commande", "Statut en temps réel", "Action en un clic"],
         "La commande arrive tout de suite chez la revendeuse. Elle confirme et prépare la livraison depuis son téléphone."),
        ("17-revendeuse-livraisons-1sur3",
         "Elle livre et suit chaque livraison",
         ["Adresse et position de la cliente", "Livraison en cours", "Mise à jour du statut"],
         "Chaque livraison a son suivi : adresse, position, statut. Rien ne se perd dans une conversation WhatsApp."),
        ("06-grossiste-livraisons-en-cours-1sur2",
         "Vous suivez les livraisons en cours",
         ["Livraisons en cours", "Revendeuse concernée", "Produit et quantité"],
         "De votre côté, vous voyez les livraisons en cours, sans demander à personne. "
         "Vous savez ce qui est en route."),
        ("22-cliente-confirmation-de-reception-telephone-code",
         "La cliente confirme sa réception avec son numéro et un code",
         ["Son numéro de téléphone", "Son code à 4 chiffres", "Aucune application à installer"],
         "Quand elle reçoit son colis, la cliente entre son numéro et son code. "
         "Le code est connu d'elle seule : ni vous ni la revendeuse ne le voyez."),
        ("23-cliente-confirmation-de-reception",
         "Un clic, et la livraison est prouvée",
         ["Produit reçu", "Bouton « J'ai reçu ma commande »", "Référence Orange Money facultative"],
         "Un seul bouton. La cliente confirme qu'elle a reçu son produit. "
         "C'est votre preuve de livraison."),
        ("07-grossiste-livrees-et-payees-1sur3",
         "Livrée et payée : la marge est acquise",
         ["Commandes confirmées", "Date de confirmation", "Marge calculée"],
         "Les commandes livrées et payées apparaissent ici. Sans déclaration contraire de votre part, une livraison est présumée faite après 72 heures. "
         "Cela évite les blocages."),
        ("08-grossiste-pas-livrees-non-honorees",
         "Une livraison échouée est tracée, sans conflit",
         ["Commandes « Pas livré »", "Motif obligatoire", "Aucun impact sur la commande"],
         "Si la cliente refuse ou n'est pas là, vous déclarez « Pas livré » avec un motif. "
         "La trace est gardée, et trois échecs en 30 jours bloquent le numéro de la cliente."),
        ("25-revendeuse-versement-a-verifier-reponse-de-la-revendeuse-2sur2",
         "La revendeuse confirme qu'elle a bien été payée",
         ["Montant et référence Orange Money", "« Oui, reçu » : le relevé est clos", "« Pas reçu » : elle choisit un motif"],
         "Sur son téléphone, la revendeuse voit le montant et la référence que vous avez notée. Si elle a reçu l'argent, elle clique sur Oui, reçu. "
         "Sinon, elle clique sur Pas reçu et choisit un motif. Si elle ne répond pas en 72 heures, le versement est accepté."),
        ("11-grossiste-releve-paye-et-accepte-detail-1sur2",
         "Le paiement est confirmé des deux côtés",
         ["Relevé payé", "Référence Orange Money", "Reçu par la revendeuse"],
         "Vous payez la marge. La revendeuse répond « oui, reçu » ou « pas reçu ». "
         "Quand elle accepte, le relevé est clos, avec une preuve des deux côtés."),
        ("26-admin-pilotage-hayaflash-releves-contestes-et-reglemen",
         "HayaFlash garde un œil sur les paiements contestés",
         ["Relevé contesté, grossiste et revendeuse", "Le montant reste dû", "Règlements de commission avec référence"],
         "Si la revendeuse dit « pas reçu », l'équipe HayaFlash le voit tout de suite. Le montant reste dû, et le grossiste peut payer à nouveau avec une autre référence. "
         "Au deuxième refus, HayaFlash prend le relais. Aucune sanction automatique : on règle les cas en discutant."),
    ]),
]


def set_text(frame, runs, size=MIN_PT, bold=False, color=DARK, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    frame.word_wrap = True
    frame.vertical_anchor = anchor
    frame.margin_left = frame.margin_right = Inches(0.05)
    frame.margin_top = frame.margin_bottom = Inches(0.02)
    para = frame.paragraphs[0]
    para.alignment = align
    run = para.add_run()
    run.text = runs
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = FONT
    run.font.color.rgb = color


def textbox(slide, x, y, w, h, text, **kw):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    set_text(box.text_frame, text, **kw)
    return box


def number_badge(slide, x, y, n):
    badge = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(0.6), Inches(0.6))
    badge.fill.solid()
    badge.fill.fore_color.rgb = RED
    badge.line.fill.background()
    frame = badge.text_frame
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    set_text(frame, str(n), bold=True, color=WHITE, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    frame.margin_left = frame.margin_right = 0


def new_slide(prs, title, section=None):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, Inches(0.12))
    band.fill.solid()
    band.fill.fore_color.rgb = RED
    band.line.fill.background()
    textbox(slide, 0.6, 0.3, 12.1, 1.1, title, size=34, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    return slide


def notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


def callouts(slide, items, x, y, w, gap=0.35):
    """Au plus 3 reperes numerotes."""
    row_h = 1.15
    for i, text in enumerate(items[:3], start=1):
        top = y + (i - 1) * (row_h + gap)
        number_badge(slide, x, top + 0.1, i)
        textbox(slide, x + 0.8, top, w - 0.8, row_h, text, anchor=MSO_ANCHOR.MIDDLE)


def capture_slide(prs, filename, title, marks, oral):
    slide = new_slide(prs, title)
    path = CAPTURES / f"{filename}.png"
    source = str(path)
    with Image.open(path) as img:
        if filename in CROPS:
            buf = io.BytesIO()
            img.crop((0, 0, img.width, int(img.height * CROPS[filename]))).save(buf, "PNG")
            buf.seek(0)
            source = buf
            ratio = img.width / int(img.height * CROPS[filename])
        else:
            ratio = img.width / img.height
    max_h, max_w = 5.65, 6.9
    h = max_h
    w = h * ratio
    if w > max_w:
        w, h = max_w, max_w / ratio
    x, y = 0.6, 1.5 + (max_h - h) / 2
    frame = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x - 0.04), Inches(y - 0.04), Inches(w + 0.08), Inches(h + 0.08))
    frame.fill.background()
    frame.line.color.rgb = RGBColor(0xD1, 0xD5, 0xDB)
    frame.line.width = Pt(1.5)
    slide.shapes.add_picture(source, Inches(x), Inches(y), Inches(w), Inches(h))
    right = x + w + 0.7
    callouts(slide, marks, right, 1.9, 13.333 - right - 0.5)
    notes(slide, oral)


NAVY = RGBColor(0x1A, 0x1A, 0x2E)


def full_bleed(prs, filename):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.shapes.add_picture(str(CAPTURES / f"{filename}.png"), 0, 0, prs.slide_width, prs.slide_height)
    return slide


def bottom_band(prs, slide, text, height=1.0, color=NAVY):
    band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, prs.slide_height - Inches(height), prs.slide_width, Inches(height))
    band.fill.solid()
    band.fill.fore_color.rgb = color
    band.line.fill.background()
    textbox(slide, 0.5, 7.5 - height, 12.3, height, text, size=32, bold=True, color=WHITE,
            align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


def platform_slides(prs):
    """Slide 1 : l'accueil de la plateforme en plein ecran ; slide Marche : version ordinateur en plein ecran."""
    slide = full_bleed(prs, "27-plateforme-accueil-hayaflash")
    bottom_band(prs, slide, "HayaFlash.com : une boutique en ligne pour chaque revendeuse")
    notes(slide, "Bonjour et merci de votre temps. Ce que je vous présente, c'est une plateforme : voici son écran d'accueil. "
                 "Elle s'appelle HayaFlash.com. Elle permet à chacune de vos revendeuses d'avoir sa propre boutique en ligne, "
                 "où elle vend en ventes flash, c'est-à-dire des ventes courtes, en direct. Tous les écrans que je vais vous montrer "
                 "sont des exemples fictifs.")


def market_desktop_slide(prs):
    slide = full_bleed(prs, "28-plateforme-le-marche-ordinateur")
    bottom_band(prs, slide, "Toutes les boutiques se retrouvent sur le Marché", height=0.9, color=DARK)
    notes(slide, "Toutes ces boutiques se retrouvent sur un même Marché, avec les revendeuses d'autres produits. "
                 "Une cliente arrive ici, voit les ventes en direct, les prix barrés et le temps qui reste, et choisit. "
                 "Vos produits sont donc visibles par toutes les clientes, pas seulement celles de votre revendeuse.")


def pains_slide(prs):
    slide = new_slide(prs, "Ce que vous vivez aujourd'hui")
    pains = ["Le stock est éparpillé chez les revendeuses", "Le suivi se fait par appels et WhatsApp",
             "Les marges et les paiements sont flous"]
    for i, text in enumerate(pains, start=1):
        top = 1.9 + (i - 1) * 1.6
        number_badge(slide, 0.9, top + 0.15, i)
        textbox(slide, 1.9, top, 10.8, 1.1, text, size=36, anchor=MSO_ANCHOR.MIDDLE)
    notes(slide, "Ces trois problèmes, vous les connaissez. Vous ne savez pas toujours où est votre marchandise. "
                 "Vous passez vos journées au téléphone pour avoir des nouvelles. Et à la fin du mois, personne n'est d'accord sur les comptes.")



def schema_slide(prs):
    slide = new_slide(prs, "Une seule chaîne, du grossiste à la cliente")
    labels = [("Grossiste", "Vous fournissez"), ("Revendeuse", "Elle vend"), ("Marché", "Les clientes achètent")]
    box_w, box_h, gap = 3.4, 2.2, 0.85
    x0 = (13.333 - (3 * box_w + 2 * gap)) / 2
    for i, (name, role) in enumerate(labels):
        x = x0 + i * (box_w + gap)
        shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(2.3), Inches(box_w), Inches(box_h))
        shape.fill.solid()
        shape.fill.fore_color.rgb = [RED, GOLD, DARK][i]
        shape.line.fill.background()
        frame = shape.text_frame
        set_text(frame, name, size=36, bold=True, color=WHITE if i != 1 else DARK, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        textbox(slide, x - 0.2, 4.7, box_w + 0.4, 0.7, role, size=30, align=PP_ALIGN.CENTER)
        if i < 2:
            arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x + box_w + 0.12), Inches(3.05), Inches(gap - 0.24), Inches(0.7))
            arrow.fill.solid()
            arrow.fill.fore_color.rgb = GREY
            arrow.line.fill.background()
    notes(slide, "Le principe est simple. Vous, le grossiste, mettez vos produits dans un catalogue. Les revendeuses les vendent à leurs clientes, "
                 "et le Marché les rend visibles à tout le monde. Chaque étape est suivie sur HayaFlash.")


def conclusion_slides(prs):
    slide = new_slide(prs, "Ce que vous gagnez")
    gains = ["Un stock visible, pièce par pièce", "Des marges calculées, sans dispute", "Une preuve de livraison à chaque commande"]
    for i, text in enumerate(gains, start=1):
        top = 1.9 + (i - 1) * 1.6
        number_badge(slide, 0.9, top + 0.15, i)
        textbox(slide, 1.9, top, 10.8, 1.1, text, size=36, anchor=MSO_ANCHOR.MIDDLE)
    notes(slide, "En résumé : vous voyez votre stock, vous ne comptez plus les marges à la main, et chaque livraison laisse une preuve. "
                 "Vous vendez plus loin, avec moins de coups de téléphone.")

    slide = new_slide(prs, "Prochaine étape : un essai simple")
    steps = ["Choisissez 5 produits pour votre catalogue", "Invitez 1 ou 2 revendeuses de confiance", "Suivez la première semaine ensemble"]
    for i, text in enumerate(steps, start=1):
        top = 1.9 + (i - 1) * 1.6
        number_badge(slide, 0.9, top + 0.15, i)
        textbox(slide, 1.9, top, 10.8, 1.1, text, size=36, anchor=MSO_ANCHOR.MIDDLE)
    notes(slide, "Je vous propose de commencer petit. Quelques produits, une ou deux revendeuses que vous connaissez bien. "
                 "Nous suivons la première semaine ensemble, puis vous décidez. Quelle revendeuse inviteriez-vous en premier ?")


def section_slide(prs, name):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(0.5), prs.slide_height)
    band.fill.solid()
    band.fill.fore_color.rgb = RED
    band.line.fill.background()
    textbox(slide, 1.2, 2.8, 11.5, 1.6, name, size=54, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    return slide


def main() -> None:
    missing = [f for f in ["27-plateforme-accueil-hayaflash", "28-plateforme-le-marche-ordinateur"] + [f for _, items in SECTIONS for f, *_ in items] if not (CAPTURES / f"{f}.png").exists()]
    if missing:
        raise SystemExit(f"Captures introuvables : {missing}")
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    sections = dict(SECTIONS)
    shops = sections.pop("Qui vend : vos revendeuses, en direct")
    market_mobile = sections.pop("Le Marché")
    platform_slides(prs)
    for filename, title, marks, oral in shops:
        capture_slide(prs, filename, title, marks, oral)
    market_desktop_slide(prs)
    for filename, title, marks, oral in market_mobile:
        capture_slide(prs, filename, title, marks, oral)
    schema_slide(prs)
    pains_slide(prs)
    for name, items in sections.items():
        slide = section_slide(prs, name)
        notes(slide, f"Section : {name}.")
        for filename, title, marks, oral in items:
            capture_slide(prs, filename, title, marks, oral)
    conclusion_slides(prs)

    # garde-fou : aucune police sous 28 pt, aucun repere au-dela de 3
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    for run in para.runs:
                        assert run.font.size is None or run.font.size.pt >= MIN_PT, (run.text, run.font.size.pt)
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT  # chemin optionnel (fichier ouvert dans PowerPoint = verrouille)
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(out)
    print(f"{len(prs.slides)} slides -> {out}")


if __name__ == "__main__":
    main()
