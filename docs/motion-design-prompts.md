# HayaFlash — Prompts et scripts prêts à l'emploi (motion design avec Claude)

> Complète `docs/motion-design-brief.md` (la **source de vérité**). Ici : comment s'en servir, le prompt maître, et 4 vidéos déjà scénarisées.
> Principe : **une idée par scène, un seul texte à l'écran, un seul mouvement**. Simple, rapide, lisible sur un petit téléphone.

---

## 1. Comment utiliser le brief (5 étapes)

1. **Captures** : lancer `scripts/motion_capture_demo.py` (mode d'emploi §6 du brief). Vous obtenez des PNG propres + `manifest.json` (la liste des écrans). Utiliser les **noms réels du manifest** dans les prompts ci-dessous (les noms entre `[crochets]` sont des exemples).
2. **Nouvelle conversation** avec Claude pour **chaque vidéo** (contexte propre, résultats plus précis).
3. **Joindre** : `motion-design-brief.md` + le dossier de captures de la vidéo + `static/img/brand/logo.svg`.
4. **Coller** le *prompt maître* (§2) puis le *script de la vidéo* (§3 à §6).
5. **Vérifier** avec la checklist (§7) avant publication. Corrections : demandez **un seul changement par message**.

Claude écrit le **code d'animation** (page HTML/CSS animée, ou projet Remotion). Vous l'exportez en vidéo (capture d'écran en boucle ou rendu Remotion + ffmpeg). Vérifiez dans votre poste quel outil de rendu est installé avant de choisir.

---

## 2. Prompt maître (à coller au début de chaque conversation)

```
Tu es motion designer senior et copywriter publicitaire pour HayaFlash,
application de ventes flash pour vendeurs et lanceurs de live au Mali et
en Afrique de l'Ouest.

SOURCE DE VÉRITÉ : le fichier joint motion-design-brief.md.
- N'affirme RIEN qui n'y figure pas. Si un fait manque, écris « à confirmer ».
- Respecte la section 0 (pièges) : jamais « numéro caché », jamais d'annulation
  de commande, jamais « Premium », jamais de vidéo live dans l'app, jamais
  « paiement en ligne » pour l'acheteur, pas de témoignages ni de chiffres
  d'accueil.
- Prix : 2 000 FCFA (Medium) et 5 000 FCFA (Pro) par mois, marqués « à confirmer ».

PUBLIC : vendeurs peu à l'aise avec le téléphone et l'ordinateur. Français très
simple, phrases de 8 mots maximum, aucun jargon (pas de COD, CA, dashboard).

STYLE : professionnel, simple, dynamique, fluide, sans surcharge.
- Couleur principale #FF4D2E, fond sombre #1A1A2E, accent or #FFB800,
  succès #22C55E. Police Inter (titres Poppins). Logo fourni.
- UN message par scène. UN texte à l'écran (6 mots max, très gros).
- Écran de l'app : toujours dans un cadre de téléphone, un zoom doux sur
  la zone utile, un doigt/cercle qui montre où toucher.
- Mouvements : entrées 0,3 à 0,4 s, ease-out ; pas de rebond excessif ;
  1 seul effet à la fois ; transitions par glissement ou fondu.
- Sous-titres toujours présents (beaucoup regardent sans le son).
- Zones de sécurité 9:16 : garder le texte à 12 % du haut et 20 % du bas.

LIVRABLE : (1) le storyboard final en tableau, (2) le code d'animation complet,
un seul fichier, qui joue en boucle sans clic, aux formats 1080x1920 et
1920x1080, (3) la liste exacte des captures utilisées.
Avant de coder, relis le script, signale tout fait non présent dans le brief,
puis code.
```

---

## 3. Vidéo A — « Présentation » (30 s, 9:16 puis 16:9)

**Objectif** : donner envie de tester gratuitement. **Appel à l'action** : « Créez votre boutique gratuite ».

```
Script de la vidéo A (30 s). Utilise ces scènes telles quelles.

| # | s | Visuel (capture) | Texte écran | Voix off |
|---|---|------------------|-------------|----------|
| 1 | 0-3 | Fond sombre, éclair du logo qui s'allume | Vous vendez en live ? | Vous vendez en live ? |
| 2 | 3-7 | [accueil / création de vente] | Programmez votre vente | Programmez votre vente en moins d'une minute. |
| 3 | 7-11 | [page publique – en direct] | Un lien à partager | Vos clients reçoivent un lien. |
| 4 | 11-15 | [QR code + bouton WhatsApp] | WhatsApp ou QR code | Partagez-le sur WhatsApp ou avec un QR code. |
| 5 | 15-20 | [commande de l'acheteur] | Ils commandent seuls | Vos clients commandent eux-mêmes. |
| 6 | 20-25 | [tableau Commandes – Livré et payé] | Vous suivez tout | Vous suivez chaque commande, étape par étape. |
| 7 | 25-30 | Logo + « Gratuit · Sans carte » + bouton | Créez votre boutique gratuite | Essayez gratuitement avec HayaFlash. |

Interdits : "30 secondes", "numéro caché", "annuler en un tap".
```

*(« Moins d'une minute » = formulation du tableau de bord de l'app ; « 30 s » de l'accueil est à valider, donc évité.)*

---

## 4. Vidéo B — Tutoriel « Lancer ma première vente » (45-60 s)

**Objectif** : apprendre sans lire. Une étape = une scène = un geste montré.

```
Script de la vidéo B (tutoriel). Chaque scène montre le vrai bouton avec son
libellé EXACT de l'app, entouré par un cercle animé.

| # | Étape | Libellé à montrer | Texte écran (6 mots max) |
|---|-------|-------------------|--------------------------|
| 1 | Ouvrir | « Nouvelle vente » | Touchez « Nouvelle vente » |
| 2 | Titre | « Titre de la vente * » | Écrivez le titre |
| 3 | Début | « Date et heure de début * » | Choisissez l'heure |
| 4 | Durée | cartes « 1 heure » / « 2 heures » | 1 heure ou 2 heures |
| 5 | Valider | « Programmer la vente » | Touchez « Programmer » |
| 6 | Produits | « Publication rapide » | Ajoutez vos produits |
| 7 | Publier | « Publier N produit(s) » | Touchez « Publier » |
| 8 | Partager | « Lien de partage » + « QR Code » | Copiez le lien |
| 9 | Ouvrir | « Ouvrir la vente » (ou automatique à l'heure) | La vente s'ouvre |

Fait à rappeler en fin de vidéo (sous-titre) : "Maximum 2 heures par vente."
Option mentionnable : "Vous pouvez enregistrer votre voix pour décrire un produit."
(enregistrement audio seulement, PAS de transcription).
Ne pas montrer : le champ "Plafond de commandes" (non appliqué).
```

---

## 5. Vidéo C — « Suivre mes commandes et livrer » (40 s)

```
Script de la vidéo C.

| # | Visuel | Texte écran | Voix off |
|---|--------|-------------|----------|
| 1 | Page « Commandes », une commande arrive seule | Les commandes arrivent | Les commandes arrivent toutes seules. |
| 2 | Bouton « Confirmé » | 1. Confirmé | Vous confirmez. |
| 3 | Bouton « En livraison » | 2. En livraison | Vous envoyez le livreur. |
| 4 | Bouton « Livré et payé » | 3. Livré et payé | Le client a reçu et payé. |
| 5 | Page Livraisons : adresse, « Maps » / « Waze », message vocal | Adresse et position | Vous voyez l'adresse et le message vocal du client. |
| 6 | Chiffres : « FCFA encaissé » | Votre argent, en un coup d'œil | Vous voyez l'argent encaissé. |
| 7 | Logo + appel à l'action | Essayez gratuitement | Essayez gratuitement. |

IMPORTANT :
- Pour marquer livré, montrer UNIQUEMENT la page Commandes (« Livré et payé »).
  Ne montre pas les boutons « Livrée » / « Échec » de la page Livraisons (inactifs).
- Dire "le client paie à la livraison" (espèces ou mobile money), jamais "paiement en ligne".
- Ne pas montrer ni lire à voix haute un numéro de client réel. Données fictives uniquement.
```

---

## 6. Vidéo D — « Les offres » (35 s)

```
Script de la vidéo D (prix « à confirmer » avant publication).

| # | Visuel | Texte écran | Voix off |
|---|--------|-------------|----------|
| 1 | Carte « Gratuit » | Gratuit : 3 ventes par mois | Gratuit : 3 ventes flash par mois. |
| 2 | Carte « Medium » | Medium : 10 ventes · 2 000 FCFA | Medium : 10 ventes par mois, 2 000 francs. |
| 3 | Carte « Pro » | Pro : ventes illimitées · 5 000 FCFA | Pro : ventes illimitées, 5 000 francs. |
| 4 | Écran « Statistiques » | Statistiques : Medium et Pro | Les statistiques sont pour Medium et Pro. |
| 5 | Checkout Orange Money | Paiement par Orange Money | Vous payez avec Orange Money. |
| 6 | Écran fin | 31 jours · Sans engagement | Un mois de 31 jours, vous renouvelez quand vous voulez. |

Règles de rédaction :
- Appeler les plans « Gratuit », « Medium », « Pro » (jamais Premium).
- Ne lister que les avantages RÉELS : nombre de ventes + statistiques.
  Ne pas citer : tableau LIVE, SMS automatiques, support prioritaire, avant-première.
- Dire "Orange Money" seul (Moov et Wave sont « Bientôt » : ne pas les annoncer).
- Préciser "renouvellement manuel" (pas de prélèvement automatique).
- Ne pas montrer la page Abonnement d'un compte expiré (affiche un plan erroné).
```

---

## 7. Checklist avant publication

| ✔ | Contrôle |
|---|----------|
| ☐ | Chaque phrase se retrouve dans le brief (sinon « à confirmer »). |
| ☐ | Libellés des boutons identiques à l'app (copier-coller du brief). |
| ☐ | Prix confirmés dans l'admin « Configuration des plans ». |
| ☐ | Aucune donnée réelle : numéros fictifs `+22370000…`. |
| ☐ | Pas de marque réelle visible (retirer « Gucci » des exemples de titres). |
| ☐ | Aucune des 13 interdictions de la section 0 du brief. |
| ☐ | Sous-titres présents, texte lisible sur un petit téléphone. |
| ☐ | Texte à 12 % du haut / 20 % du bas en 9:16. |
| ☐ | Durée respectée (30-60 s), une idée par scène. |
| ☐ | Test sur un vrai téléphone, sans le son. |

## 8. Corrections rapides (à coller au besoin)

- « Trop chargé : retire un élément par scène et agrandis le texte. »
- « Plus fluide : durée des transitions 0,35 s, ease-out, pas de rebond. »
- « Plus convaincant : ouvre la scène 1 par la douleur du vendeur, ferme par un seul bouton d'action. »
- « Vérifie chaque phrase contre le brief et liste celles à confirmer. »
- « Version 16:9 : même storyboard, écran de l'app au centre dans un cadre de téléphone, texte à gauche. »
