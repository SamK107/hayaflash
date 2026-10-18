"""Contenu du guide « Ta première vente flash, étape par étape » (carrousel public).

Une entrée = une diapositive. Les textes suivent docs/guide-vente-flash-etape-par-etape.md
et les captures réelles de static/guide/ (données de démo : boutique « Awa Style »,
3 clientes fictives, total 25 000 FCFA).

screen : "vendeur" | "client" | "terrain" | "" (diapo sans capture)
img    : nom de fichier dans static/guide/ (WebP) ou "" ; w/h = dimensions réelles.
Le texte peut contenir <strong> (marqué sûr dans le template, contenu interne uniquement).
"""

CHAPTERS = {
    "A": "Crée ton compte",
    "B": "Programme ta vente",
    "C": "Ajoute tes produits",
    "D": "Partage et fais réserver",
    "E": "Le live : les commandes arrivent",
    "F": "Fin de vente et livraison",
    "G": "Ton bilan",
}

_PHONE = (780, 1688)


def _s(ch, screen, title, text, img="", size=_PHONE, alt=""):
    return {"chapter": ch, "chapter_name": CHAPTERS[ch], "screen": screen, "title": title,
            "text": text, "img": img, "w": size[0], "h": size[1], "alt": alt or title}


SLIDES = [
    _s("A", "", "Ta première vente flash, étape par étape",
       "En quelques minutes, tu vas programmer ta vente, recevoir tes commandes et suivre ton argent. "
       "Fais défiler pour suivre l'exemple de <strong>Awa Style</strong>."),
    _s("A", "vendeur", "Crée ton compte",
       "Va sur <strong>hayaflash.com</strong> et touche <strong>« Créer mon compte gratuitement »</strong>.",
       "01_accueil_creer_compte.webp"),
    _s("A", "vendeur", "3 informations, c'est tout",
       "Le <strong>nom de ta boutique</strong>, ton <strong>numéro de téléphone</strong> et un "
       "<strong>mot de passe</strong>. Pas d'e-mail, pas de carte.",
       "02_inscription_remplie.webp"),
    _s("B", "vendeur", "Ton tableau de bord",
       "Tu arrives dans ta boutique. Touche <strong>« Créer une vente flash »</strong>.",
       "03_tableau_de_bord_vide.webp"),
    _s("B", "vendeur", "Donne un nom à ta vente",
       "Par exemple : « Vente flash du samedi ». Tes clientes verront ce titre.",
       "04_creation_titre.webp"),
    _s("B", "vendeur", "Choisis l'heure de début et la durée",
       "Mets le jour et l'heure où ton live commence, puis choisis <strong>1 heure</strong> ou "
       "<strong>2 heures</strong>. L'heure de fin s'affiche toute seule.",
       "05_creation_heure_duree.webp"),
    _s("B", "vendeur", "La fin se calcule toute seule",
       "Tu n'as rien à faire : la vente <strong>s'ouvre et se ferme à l'heure</strong>. "
       "Touche <strong>« Programmer la vente »</strong>.",
       "06_creation_programmer.webp"),
    _s("C", "vendeur", "Ajoute la photo du produit",
       "Prends une photo avec <strong>« Caméra »</strong> ou choisis-la dans ta <strong>« Galerie »</strong>.",
       "07_produit_photo.webp"),
    _s("C", "vendeur", "Prix et quantité",
       "Écris le <strong>nom</strong>, le <strong>prix en FCFA</strong> et <strong>combien tu en as</strong>. "
       "Le stock baissera tout seul à chaque commande.",
       "08_produit_prix_stock.webp"),
    _s("C", "vendeur", "Tes produits sont prêts",
       "Ajoute les autres produits de la même façon : ils s'affichent dans ta vente. Ici : pagne wax, "
       "sac à main et sandales.",
       "09_produits_publies.webp"),
    _s("D", "vendeur", "Partage ton lien ou ton QR code",
       "Mets le <strong>lien</strong> de ta vente dans ton statut WhatsApp ou ta bio TikTok, "
       "ou montre le <strong>QR code</strong> pendant ton live.",
       "10_partage_lien_qr.webp"),
    _s("D", "client", "Tes clientes se font prévenir",
       "Avant l'ouverture, ta cliente voit le compte à rebours et touche "
       "<strong>« Je veux être prévenu(e) »</strong>.",
       "11_client_alerte.webp"),
    _s("D", "vendeur", "Tu vois qui attend ta vente",
       "Dans <strong>Réservations</strong>, tu as la liste des clientes inscrites. Ici : "
       "<strong>3 réservations</strong>.",
       "12_vendeur_reservations.webp"),
    _s("E", "client", "La vente est ouverte",
       "À l'heure prévue, ta cliente voit tes produits, le prix et <strong>le stock qui reste</strong>. "
       "Rien à installer.",
       "13_client_vente_ouverte.webp"),
    _s("E", "client", "Elle commande elle-même",
       "Elle choisit la <strong>quantité</strong>, écrit son <strong>nom</strong> et son "
       "<strong>numéro</strong>.",
       "14_client_tiroir.webp"),
    _s("E", "client", "Son adresse : position ou message vocal",
       "Elle touche <strong>« Envoyer ma position »</strong>, ou enregistre un "
       "<strong>message vocal</strong> pour dire où elle habite.",
       "15_client_position_vocal.webp"),
    _s("E", "client", "Commande envoyée !",
       "Elle paiera <strong>à la livraison</strong>, après avoir vu le produit.",
       "16_client_commande_envoyee.webp"),
    _s("E", "vendeur", "Les commandes arrivent toutes seules",
       "Pendant ton live, les commandes s'ajoutent dans <strong>Commandes</strong>. "
       "Ici : <strong>3 clientes, 3 commandes</strong>.",
       "17_vendeur_3_commandes.webp"),
    _s("F", "client", "La vente se ferme à l'heure",
       "À l'heure de fin, <strong>la vente se ferme toute seule</strong>. Plus aucune commande n'est possible.",
       "18_client_vente_fermee.webp"),
    _s("F", "vendeur", "Prépare tes livraisons",
       "Dans <strong>Commandes</strong>, touche <strong>« Confirmer »</strong>, puis "
       "<strong>« Gérer la livraison → »</strong>. Tu arrives sur <strong>Livraisons</strong> : tu y vois "
       "l'adresse et le montant à encaisser, tu notes le nom du livreur et tu touches <strong>« En livraison »</strong>.",
       "19_vendeur_livraisons.webp", (780, 1305)),
    _s("F", "terrain", "Ta cliente paie à la livraison",
       "Elle voit le produit, puis <strong>paie le livreur</strong> : en espèces ou par mobile money.",
       "20_illustration_paiement_moto.webp", (1200, 900),
       alt="Illustration : une cliente remet des billets en FCFA à un livreur casqué sur son scooter"),
    _s("F", "vendeur", "Livré et payé ✔",
       "Quand le livreur te confirme, touche <strong>« Livré et payé »</strong> dans <strong>Livraisons</strong>. "
       "Si la livraison n'aboutit pas, touche <strong>« Échec »</strong>. La commande est terminée.",
       "21_vendeur_livre_paye_avant.webp"),
    _s("G", "vendeur", "Tes comptes sont déjà faits",
       "Ton tableau de bord affiche tes commandes, les articles livrés et l'argent encaissé : "
       "<strong>25 000 FCFA</strong>.",
       "22_vendeur_bilan.webp"),
    _s("G", "", "Excellente opération ! 🎉",
       "Maintenant, programme ta vente flash de demain <strong>en toute tranquillité, sans stress</strong>."),
]
