# HayaFlash — Scripts motion design prêts à l'emploi

> Complète `docs/motion-design-brief.md` (les faits). Ce fichier = **comment s'en servir** + **les scripts**.
> Règle : chaque argument de vente ci-dessous existe dans le code. Ce qui est faux ou douteux est dans la liste « INTERDIT » (§2).
> Comparaison : uniquement avec la **méthode classique** (cahier, carnet, 2ᵉ téléphone, WhatsApp). Comparaison avec d'autres applications : **non trouvé** dans le dépôt, donc non faite.

---

## 1. Mode d'emploi en 4 étapes

1. **Préparer le dossier de travail** (à donner à Claude) :
   - `docs/motion-design-brief.md` (les faits)
   - ce fichier
   - logos : `static/img/brand/bolt.svg`, `logo.svg`, `logo-dark.svg`
   - polices : `static/fonts/` (Inter, Poppins)
   - captures : lancer le script Playwright du brief §6 → dossier `motion_assets/` (PNG 1080×1920 et 1920×1080 + `manifest.json`)
2. **Ouvrir une conversation neuve** avec Claude Opus 5.5, joindre ces fichiers, coller le **PROMPT MAÎTRE** (§3).
3. **Une vidéo à la fois** : coller ensuite le bloc « PROMPT SCÈNE » de la vidéo choisie (§5), qui renvoie au script.
4. **Contrôle avant publication** : relire la liste « INTERDIT » (§2) ; faire valider les textes par un vendeur malien ; faire relire la voix off par un locuteur natif si traduction en bambara.

**Technique recommandée (simple et reproductible)** : Claude écrit un projet **Remotion** (React) : 1 composition par format (1080×1920 et 1920×1080), 30 images/s, une scène = un fichier. Rendu : `npx remotion render`. Alternative sans React : une page HTML + GSAP, enregistrée avec Playwright puis `ffmpeg`. Dans les deux cas : **mêmes scripts, mêmes textes**.

---

## 2. Garde-fous commerciaux

### Arguments VRAIS (autorisés)
| Argument | Preuve dans le code |
|----------|--------------------|
| Un **lien** (et un **QR code**) à montrer pendant le live : le client commande seul | `/f/<slug>/`, « QR Code » |
| Le client choisit le produit, la quantité, écrit **ou dit** son adresse, peut envoyer sa **position** | tiroir de commande |
| La commande **arrive toute seule** dans « Commandes » (rafraîchi en continu) | Dashboard LIVE |
| Le **stock baisse tout seul** ; le client voit « Plus que N ! » puis « Épuisé » | page publique |
| La vente **s'ouvre et se ferme à l'heure** programmée (max 2 h) | tâches automatiques |
| **Un bouton par étape** : Confirmé → En livraison → Livré et payé | carte commande |
| Chiffres en direct : **commandes, articles livrés, FCFA encaissé, FCFA en cours** | Dashboard LIVE |
| Livraisons : adresse, **Maps / Waze**, message vocal du client, **nom du livreur**, argent à récupérer | page Livraisons |
| **Export CSV** de la vente | « Exporter CSV » |
| Clients qui veulent être prévenus (**« M'alerter à l'ouverture »**) | Réservations |
| **Reprendre** une vente précédente / **Publication rapide** de plusieurs produits | boutons existants |
| Acheteur : **rien à installer**, pas de compte | page web publique |
| Compte **gratuit**, sans carte, sans e-mail ; 3 ventes/mois | inscription, plan Gratuit |
| Paiement à la livraison (espèces ou mobile money) | tiroir de commande |

### INTERDIT (faux, inactif ou non prouvé)
- « Numéro du client caché / anonyme » · « annulez en un tap » · « annulation par le client »
- « Confirmation automatique envoyée au client par SMS/WhatsApp » (non trouvé)
- « Plafond de commandes » comme protection · « Livraisons groupées » · « taux de livraison », « clients fidèles »
- « Pro = tableau LIVE / SMS / support prioritaire » (non bloqué par plan) → pour Pro, dire seulement **ventes illimitées + statistiques avancées**
- Montrer les boutons « Livrée » / « Échec » de la page Livraisons (jamais affichés) · montrer la page d'admin plateforme
- Témoignages de la page d'accueil, « 3× plus vite », « 2 heures par vente » (sans source)
- « 30 secondes » : **chronométrer d'abord** une vraie création de vente, puis écrire le temps mesuré
- Paiement en ligne par l'acheteur · Moov/Wave pour l'abonnement · « Premium » · date de lancement (déploiement en pause)
- Marques réelles (ex. « Gucci ») dans les exemples : utiliser « Pagne wax », « Sac à main rouge », « Sandales »
- Prix : à reconfirmer en base avant diffusion (Gratuit 0 · Medium 2 000 · Pro 5 000 FCFA/mois, 31 jours)

---

## 3. PROMPT MAÎTRE (à coller en premier)

```text
Tu es directeur artistique et motion designer senior. Tu crées des vidéos courtes pour HayaFlash,
une application de ventes flash pour vendeurs de live au Mali et en Afrique de l'Ouest.

PUBLIC : vendeurs et lanceurs de live, souvent peu à l'aise avec mobile/ordinateur. Ils regardent
sur téléphone, souvent sans le son, avec une connexion moyenne. Ils veulent gagner du temps et ne plus
perdre de commandes ni d'argent.

SOURCES DE VÉRITÉ : docs/motion-design-brief.md et docs/motion-design-scripts.md.
Tu n'affirmes RIEN qui n'y figure. Tu respectes la liste « INTERDIT » (§2). Si une information manque,
tu écris « à confirmer » au lieu d'inventer. Les textes affichés dans les écrans de l'app sont copiés
mot pour mot depuis le brief (§1).

IDENTITÉ : couleur principale #FF4D2E, dégradé logo #FFC24A→#FF8A2B→#FF4D2E, or #FFB800, fond sombre
#1A1A2E, clair #FAFAFA, succès #22C55E. Polices Inter (texte) et Poppins 800 (titres). Logo : fichiers
fournis, jamais redessiné. Icônes : Lucide. Coins très arrondis, pastilles, point LIVE qui pulse.

STYLE DE MOTION : dynamique mais calme. Un seul message par scène, 5 à 8 mots maximum à l'écran,
gros caractères (≥ 64 px en 9:16), contraste fort. Mouvements : entrées en « ressort » de 300-450 ms,
sorties 200 ms, pas de rotation décorative, pas d'effet qui masque l'écran de l'app. Montre l'app
réelle (captures fournies) dans un cadre de téléphone, avec un zoom doux sur la zone importante et un
cercle/halo orange sur le bouton à toucher. Sous-titres incrustés TOUJOURS (la vidéo doit se comprendre
sans le son). Rythme : une scène de 2 à 4 s.

LANGUE : français simple, phrases courtes, vouvoiement, mots du quotidien (voir tableau « Vocabulaire
simple »). Pas de jargon (COD, CA, dashboard).

FORMATS : produire 9:16 (1080×1920) ET 16:9 (1920×1080) à partir des mêmes scènes. En 9:16, tout le
texte reste dans la zone sûre (marges 64 px haut/bas, 120 px en bas pour les interfaces TikTok/WhatsApp).
En 16:9, le téléphone passe à droite, le texte à gauche.

LIVRABLE : un projet Remotion (une composition par format, 30 i/s), un fichier par scène, un fichier
`copy.ts` avec tous les textes (pour relecture/traduction), et la commande de rendu. Aucun texte en
dur dans les scènes. Dis-moi à la fin quelles captures il te manque.

Réponds d'abord par : (1) ta compréhension en 5 lignes, (2) la liste des captures dont tu as besoin,
(3) la structure du projet. Attends mon « go » avant de coder.
```

---

## 4. Ce que HayaFlash change (tableau pivot de tous les scripts)

| Méthode classique (cahier, carnet, 2ᵉ téléphone) | Avec HayaFlash |
|---|---|
| Vous notez les « je prends » en plein live, vous en ratez | Le client **commande lui-même** par le lien ; la commande arrive seule |
| « C'est où ? Envoyez-moi votre position » (10 messages) | Adresse écrite **ou vocale** + **position** envoyée avec la commande |
| Vous comptez le stock de tête, vous vendez trop | Le **stock baisse tout seul**, « Épuisé » s'affiche |
| Il faut ouvrir et arrêter la vente soi-même | **Ouverture et fermeture à l'heure** |
| Le 2ᵉ téléphone sonne, les messages se perdent | **Une seule liste** de commandes, rafraîchie seule |
| Qui est confirmé ? livré ? payé ? On ne sait plus | **3 étapes, 1 bouton** : Confirmé → En livraison → Livré et payé |
| Fin de journée : on refait les comptes | **FCFA encaissé / en cours** déjà affichés ; **export CSV** |
| Le livreur appelle pour l'adresse | **Maps / Waze**, message vocal, nom du livreur, argent à récupérer |
| Les curieux oublient l'heure du prochain live | **« M'alerter à l'ouverture »** : vous gardez la liste |
| Tout est à recopier d'un live à l'autre | **« Reprendre cette vente »** + **Publication rapide** |

---

## 5. Les scripts vidéo

Convention : **[ÉCRAN]** = texte incrusté · **[VOIX]** = voix off · **[MOTION]** = consigne · **[CAPTURE]** = écran à utiliser (noms = `manifest.json`).

### Vidéo 1 — « Fini le cahier » (annonce, 30 s, 9:16 + 16:9)
**Objectif** : arrêt du défilement, un seul message : *vos commandes arrivent seules*.

| Temps | [MOTION] / [CAPTURE] | [ÉCRAN] | [VOIX] |
|---|---|---|---|
| 0-3 s | Cahier raturé + 2ᵉ téléphone qui vibre, messages « je prends 2 », « c'est où ? » qui s'empilent. Secousse légère | « Un live. 40 messages. » | « Pendant votre live, les messages arrivent de partout. » |
| 3-6 s | Stylo qui rature ; chiffre de stock qui se trompe (rouge) | « Une commande perdue. » | « Une commande oubliée, un stock faux… » |
| 6-8 s | Coupure franche, fond #FF4D2E, éclair du logo | « HayaFlash » | « Avec HayaFlash, ça change. » |
| 8-13 s | [CAPTURE] page publique en direct ; halo sur « Commander · X FCFA » ; tiroir qui monte | « Le client commande seul » | « Le client touche, choisit, donne son adresse. » |
| 13-18 s | [CAPTURE] Commandes ; carte qui tombe en haut de liste ; compteur « Commandes » +1 | « La commande arrive seule » | « Et la commande arrive toute seule chez vous. » |
| 18-23 s | Bouton « Confirmé » → « En livraison » → « Livré et payé » ; badge qui change de couleur | « Un bouton. Trois étapes. » | « Un bouton par étape. Vous savez où en est chaque commande. » |
| 23-27 s | Carte « FCFA encaissé » qui monte | « Vos comptes à jour » | « Et vos comptes sont déjà faits. » |
| 27-30 s | Logo + « Créer mon compte — Gratuit » | « Gratuit · sans carte » | « Créez votre compte gratuit. » |

**PROMPT SCÈNE** : « Réalise la Vidéo 1 du fichier docs/motion-design-scripts.md. Montre-moi d'abord le storyboard image par image (descriptions), puis code les scènes. »

---

### Vidéo 2 — « Votre vente en 3 étapes » (démonstration, 60 s)
**Objectif** : rassurer les moins à l'aise : *c'est simple, voilà exactement quoi toucher*.

| Temps | [CAPTURE] + [MOTION] | [ÉCRAN] | [VOIX] |
|---|---|---|---|
| 0-4 s | Logo, puis 3 pastilles 1-2-3 | « 3 étapes » | « Lancer une vente HayaFlash, c'est trois étapes. » |
| 4-8 s | Écran inscription ; halo sur « Créer mon compte » | « 0. Créer son compte » | « D'abord, un compte : nom de boutique, téléphone, mot de passe. » |
| 8-20 s | Création de vente : titre ; choix **1 heure / 2 heures** ; halo | « 1. Programmer la vente » | « Donnez un titre, choisissez la durée : une heure, ou deux heures. Puis “Programmer la vente”. » |
| 20-32 s | Publication rapide : « + Nouveau produit », photo, prix, stock ; « Publier N produit(s) » | « 2. Ajouter les produits » | « Ajoutez vos produits : photo, prix, quantité. Plusieurs d'un coup, avec la Publication rapide. » |
| 32-40 s | Fiche vente : lien ; **QR Code** plein écran | « 3. Partager le lien » | « Copiez le lien ou montrez le QR code pendant votre live. » |
| 40-50 s | Commandes qui arrivent ; 3 boutons de statut | « Les commandes arrivent seules » | « La vente s'ouvre et se ferme toute seule. Vous suivez vos commandes ici. » |
| 50-57 s | FCFA encaissé / en cours | « Suivez vos recettes » | « Vous voyez l'argent encaissé et l'argent en attente. » |
| 57-60 s | CTA | « Gratuit · 3 ventes par mois » | « Essayez gratuitement. » |

**Note** : montrer les écrans à vitesse réelle ×1,5 maximum, jamais plus (lisibilité pour débutants). Ne pas ajouter de temps du type « en 30 secondes » sans chronométrage.

---

### Vidéo 3 — « Avant / Après » (comparatif, 45 s, boucle)
**Objectif** : convaincre par contraste. **Écran coupé en deux** (9:16 : haut/bas ; 16:9 : gauche/droite). Gauche/haut = classique, grisé. Droite/bas = HayaFlash, couleurs.

Reprendre **5 lignes** du tableau §4, une par scène de 6 s, dans cet ordre (le plus parlant d'abord) :
1. Commandes : « Je note dans le cahier » ↔ « Le client commande seul »
2. Adresse : « C'est où ? » ↔ « Adresse, vocal et position »
3. Stock : « Je compte de tête » ↔ « Le stock baisse tout seul »
4. Suivi : « Qui est payé ? » ↔ « Confirmé → En livraison → Livré et payé »
5. Comptes : « Je refais tout le soir » ↔ « FCFA encaissé déjà calculé »

Chaque scène : [MOTION] le côté classique se froisse/tremble 1 s, le côté HayaFlash glisse avec un « tick » vert. Final 6 s : logo + « Passez de la méthode classique à HayaFlash ».
[VOIX] (une phrase par scène, 6 s) : « Avant : je note. Maintenant : le client commande seul. » etc.

---

### Vidéo 4 — « Un client commande » (côté acheteur, 25 s) — preuve de simplicité
| Temps | [CAPTURE] page publique (mobile) | [ÉCRAN] | [VOIX] |
|---|---|---|---|
| 0-4 s | Carte produit + « Plus que N ! » | « Le stock est visible » | « Votre client voit ce qu'il reste. » |
| 4-10 s | Tiroir : quantité, nom, téléphone | « Il choisit » | « Il choisit, il donne son numéro. » |
| 10-16 s | « Envoyer ma position » ; micro « Enregistrer un message » | « Position ou vocal » | « Il envoie sa position ou un message vocal. » |
| 16-20 s | « Paiement a la livraison » ; « Confirmer la commande » | « Il paie à la livraison » | « Il paie à la livraison, en espèces ou en mobile money. » |
| 20-25 s | « Commande envoyée ! » | « Rien à installer » | « Rien à installer pour lui. Pour vous, c'est déjà dans la liste. » |

---

### Vidéo 5 — « Les plans » (présentation des abonnements, 30 s)
**Prix à reconfirmer en base avant diffusion.**
| Temps | [MOTION] | [ÉCRAN] | [VOIX] |
|---|---|---|---|
| 0-4 s | Trois cartes glissent | « 3 plans » | « Commencez gratuitement. » |
| 4-11 s | Carte **Gratuit** s'allume | « Gratuit · 0 FCFA · 3 ventes par mois » | « Gratuit : trois ventes par mois, page boutique, commandes en ligne, partage WhatsApp. » |
| 11-19 s | Carte **Medium** | « Medium · 2 000 FCFA/mois · 10 ventes » | « Medium : dix ventes par mois et les statistiques des trente derniers jours. » |
| 19-26 s | Carte **Pro** (halo « Recommande ») | « Pro · 5 000 FCFA/mois · ventes illimitées » | « Pro : ventes illimitées et les statistiques avancées. » |
| 26-30 s | Logo Orange Money (texte seulement, **pas le logo officiel sans autorisation**) | « Paiement par Orange Money · Sans engagement » | « Vous payez par Orange Money, sans engagement. » |

**Interdit ici** : lister tableau LIVE, SMS, support prioritaire comme avantages Pro. Maximum 3 ventes par jour sur tous les plans : à mentionner dans un sous-titre « Max 3 ventes par jour ».

---

### Vidéo 6 — Série de **mini-tutoriels 15 s** (une action = une vidéo)
Format commun : 1 phrase + 1 écran + 1 halo. Réutiliser le gabarit : titre (2 s) → écran avec halo (10 s) → résultat (3 s).

| N° | Titre affiché | Captures | Voix (1 phrase) |
|---|---|---|---|
| T1 | « Créer mon compte » | inscription | « Nom de boutique, téléphone, mot de passe, et c'est fait. » |
| T2 | « Programmer une vente » | création | « Titre, heure de début, une heure ou deux heures. » |
| T3 | « Ajouter plusieurs produits » | publication rapide | « Ajoutez tous vos produits d'un coup. » |
| T4 | « Partager le lien et le QR code » | fiche vente | « Copiez le lien, ou montrez le QR code. » |
| T5 | « Suivre mes commandes » | Commandes | « Touchez le bouton pour passer à l'étape suivante. » |
| T6 | « Préparer la livraison » | Livraisons (sans « Livrée/Échec ») | « Ouvrez Maps ou Waze, notez le nom du livreur. » |
| T7 | « Prévenir mes clients » | Réservations / « M'alerter » | « Vos clients se font prévenir, vous gardez leur liste. » |
| T8 | « Reprendre une vente » | « Reprendre cette vente » | « Refaire la même vente, en un bouton. » |
| T9 | « Voir mes chiffres » | Commandes (KPI) ; Statistiques **Medium/Pro** via adresse directe | « Argent encaissé, argent en attente. » |

---

### Vidéo 7 — Réponses aux doutes (6 clips de 10-15 s)
| Doute du vendeur | Réponse **vraie** | À ne PAS répondre |
|---|---|---|
| « Mes clients ne vont pas installer une application » | « Rien à installer : un simple lien. » | — |
| « C'est compliqué ? » | « Trois étapes, un bouton par étape. » | « 30 secondes » (non mesuré) |
| « Combien ça coûte ? » | « Gratuit pour commencer. Medium 2 000, Pro 5 000 FCFA/mois (à reconfirmer). » | Tarifs non confirmés |
| « Et si mon téléphone est lent ? » | « Les commandes restent dans votre liste. » (à vérifier avant de filmer : comportement hors ligne non étudié) | Promesse hors-ligne |
| « Mes clients paient comment ? » | « À la livraison, espèces ou mobile money. » | « Paiement en ligne » |
| « Mon numéro / celui du client ? » | « Le numéro du client sert à vous faire appeler. » | « Caché », « anonyme » |

---

## 6. Plan de diffusion conseillé (ordre de production)
1. **Vidéo 1** (annonce) — la plus partageable.
2. **Vidéo 3** (avant/après) — la plus convaincante.
3. **Vidéo 2** (démo) — rassure.
4. **Vidéo 5** (plans) — après confirmation des prix en base.
5. **Vidéo 4** et série **T1-T9** — onboarding.
6. **Vidéo 7** — publicités ciblées / réponses en commentaires.

Appel à l'action unique partout : **« Créez votre compte gratuit »** (inscription : nom de boutique, téléphone, mot de passe ; aucune carte).

---

## 7. Checklist qualité avant export
- [ ] Chaque texte d'écran existe dans `docs/motion-design-brief.md` ou dans ce fichier.
- [ ] Aucun point de la liste « INTERDIT » (§2).
- [ ] Sous-titres lisibles sans le son, ≥ 64 px en 9:16, dans la zone sûre.
- [ ] Données de démo uniquement (numéros fictifs +22370000xxx), aucun vrai client ni vraie marque.
- [ ] Captures sans bandeau debug, sans bannière « Installer », sans page d'administration.
- [ ] Prix relus en base de production.
- [ ] Relecture par un vendeur malien (compréhension) + locuteur natif si voix en bambara/autre langue.
- [ ] Exports : 1080×1920 et 1920×1080, 30 i/s, MP4 H.264, moins de 30 Mo pour WhatsApp.
