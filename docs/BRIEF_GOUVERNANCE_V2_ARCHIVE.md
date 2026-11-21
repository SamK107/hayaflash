# HayaFlash — Brief de gouvernance v2

Plan Business (10 000 FCFA), programme créateurs, tracking et règlements manuels

Nov 20, 2026 · @Alex

## 0. Mode d'emploi (pour Claude Code / Cowork)

Ce brief remplace le brief « Module Partenaires » du collègue et l'analyse tarifaire associée. Il est la source de vérité pour créer ou mettre à jour la gouvernance.

**Ordre de travail imposé :**

1. **Audit de l'existant avant toute écriture** (lecture seule de `C:\projets\hayaflash\`). Produire un tableau « déjà présent / partiel / absent » pour chaque élément marqué **\[À VÉRIFIER\]** ci-dessous. Ne rien recréer de ce qui existe.
2. Mettre à jour les documents de gouvernance (§ 9), sans contradiction avec `SPEC_03` (Distrib) et `SPEC_04` (statuts livraison/paiement).
3. Seulement ensuite, découper en prompts d'implémentation par phase (§ 8).

**Règles transverses (déjà en vigueur, à ne jamais enfreindre) :**

- Montants en **FCFA entiers**, jamais de centimes.
- Approche **ultra safe** : aucune modification de l'existant sans migration réversible, staging puis prod, tag de retour avant fusion.
- **Aucun paiement sortant dans HayaFlash** : ni API de décaissement, ni bouton qui déclenche un virement. Les commissions sont payées hors plateforme (espèces ou Orange Money compte à compte) et seulement **constatées** dans HayaFlash.
- Textes en français en dur, tutoiement côté vendeur, pays jamais déduit d'un numéro nu.
- Fail-closed sur les droits d'abonnement (comportement existant : repli si PRO expiré).

## 1. Décisions figées (ne pas rediscuter)

| Sujet | Décision |
| --- | --- |
| Plans actuels | FREE 3 ventes/mois (0), MEDIUM 10 ventes/mois (2 000), PRO illimité (5 000) |
| Limites de fond | Vente flash max 2 h, max 3 ventes/jour/boutique, pas de chevauchement |
| Encaissement abonnements | API Orange Money, paiement direct à Orange qui retient 1 % |
| Commission créateur | 30 % des abonnements encaissés, 12 mois par vendeur recommandé, contrat d'1 an non renouvelable |
| Places fondateurs | 8 pour la cohorte 1 |
| Seuil de versement | 2 000 FCFA cumulables |
| Pas de prime d'activation | Commission uniquement sur argent encaissé |
| Suivi partenaire | Admin seul + relevé WhatsApp mensuel, pas d'interface partenaire au départ |
| Distrib | Commission 5–6 % négociée par grossiste, plafonnée à 1 500 FCFA, décompte à partir du mois 2, HayaFlash ne touche aucun argent client |
| Tarifs éditables | Prix et limites des plans modifiables depuis l'admin, prix spécial temporaire par vendeur (tests à 100 FCFA) |
| Offre de lancement | Plan Pro gratuit 1 mois pour qui veut essayer, sans parler de partenariat |

**Écarts assumés par rapport au brief du collègue :** pas de paliers 20/25/30 %, pas de tableau de bord partenaire en phase 1, pas de seuil à 5 000 FCFA, pas de rétrocession grossiste « payée par HayaFlash », pas de « double validation » (voir § 6.5), pas d'alerte fraude avancée avant volume.

## 2. Décisions ouvertes (à trancher avant implémentation)

| # | Question | Recommandation |
| --- | --- | --- |
| D1 | Base de la commission : montant brut encaissé ou net de la retenue Orange 1 % ? | **Brut.** Plus simple à expliquer, évite les fractions de FCFA, coût pour HayaFlash : 1 % de 30 % = 0,3 % du prix. À écrire dans les conditions. |
| D2 | Plafond Distrib de 1 500 FCFA : par vente, par commande ou par mois ? | À lire dans `SPEC_03` puis aligner. Ne jamais laisser ambigu dans les CGU. |
| D3 | Début des 12 mois de commission | **12 mois calendaires à partir du premier paiement encaissé**, date de fin fixe, mois gratuits exclus. |
| D4 | Nom du plan à 10 000 FCFA | **BUSINESS.** Le nom PRO existe déjà (5 000, illimité, présent dans le code, les vidéos, les lettres). Renommer PRO obligerait à migrer des abonnés et des textes. |
| D5 | Remise annuelle | **2 mois offerts** (PRO 50 000, Business 100 000), via un champ de durée sur l'abonnement. |
| D6 | Ouverture de Business | **Pas avant 3 fonctions livrées** parmi celles du § 4 (voir § 8). Avant : liste d'attente et tarif fondateur. |

## 3. Grille tarifaire cible

|  | FREE | MEDIUM | PRO | **BUSINESS** |
| --- | --- | --- | --- | --- |
| Prix/mois | 0 | 2 000 | 5 000 | **10 000** |
| Ventes flash/mois | 3 | 10 | illimité | illimité |
| Public visé | Essai | Débutante | Vendeuse régulière | Gros compte, boutique avec équipe, revendeur Distrib actif |
| Outils de pilotage | de base | de base | tableau de bord + bilan simple | **bilan complet, stock maître, fichier clientes, export** |
| Image | standard | standard | standard | **Boutique personnalisée + badge** |

**Point d'attention :** « illimité » est déjà borné par 3 ventes/jour et 2 h par vente. Business ne se justifie donc **pas par du volume** mais par des outils qui font gagner de l'argent ou du temps. C'est la bonne logique : la vendeuse paie pour la maîtrise, pas pour une limite levée.

**Garde-fous de migration :**

- Ajouter `BUSINESS` à l'énumération des plans **sans toucher** aux valeurs existantes. Les abonnés PRO ne bougent pas.
- Les limites et prix passent par la configuration de plan éditable (déjà voulue). **\[À VÉRIFIER\]** si elle existe ; sinon la créer en premier, c'est le socle de tout le reste.
- **Rétrogradation sans perte** : un compte qui repasse de BUSINESS à PRO garde toutes ses données ; les fonctions Business deviennent en lecture seule, rien n'est supprimé. S'appuyer sur la logique fail-closed existante.
- Chaque fonction Business est protégée par un seul contrôle central du type `plan_has_feature(plan, feature)` (pas de `if plan == 'BUSINESS'` dispersés).

## 4. Contenu du plan Business

Critère de sélection : chaque élément doit (a) s'appuyer sur ce qui existe ou est déjà planifié, (b) apporter une valeur mesurable à la vendeuse, (c) ne pas créer de circuit parallèle. Légende des phases : **B1** rapide, **B2** moyen, **B3** plus tard.

| # | Valeur | Existant / planifié | Pourquoi ça justifie 10 000 FCFA | Effort | Phase |
| --- | --- | --- | --- | --- | --- |
| 1 | **Bilan mensuel complet côté vendeuse** : ventes, CA livré et payé, produits par % des recettes, évolution sur 3 mois, export PDF/CSV | La page admin de bilans existe (lancée le 17 oct.) | Réutilise un calcul déjà fait ; répond à « quels articles me rapportent vraiment » | S | B1 |
| 2 | **Ligne « HayaFlash t'a fait gérer X FCFA ce mois »** en tête du bilan, comparée au prix de l'abonnement | Données du bilan | Rend le prix évident et lutte contre le désabonnement. Calculé sur des données réelles, jamais estimé | S | B1 |
| 3 | **Studio photo avec quota élevé** (PRO : quota réduit, Business : large) | SPEC Studio photo prête | Valeur visible dès la première vente ; coût serveur borné par quota | S | B1 |
| 4 | **Stock maître** : saisie du stock total, décompte automatique, alerte de rupture dans le tableau de bord | Voulu le 21 oct. (approche ultra safe, distinct du stock par vente) | Réponse directe à la survente, douleur n° 1 des vendeuses de mode | L | B2 |
| 5 | **Fichier clientes** : historique par cliente, fiabilité (commandes honorées / non honorées), lien WhatsApp pré-rempli ouvert depuis le téléphone de la vendeuse | Blocage après 3 commandes non honorées déjà prévu ; la vendeuse appelle déjà pour confirmer | Les gros comptes vivent de leur fichier clientes ; aucune API WhatsApp, juste un lien `wa.me` | M | B2 |
| 6 | **Ventes privées** pour clientes fidèles ou gros acheteurs | Idée du 17 oct. | Crée de la valeur propre à Business, pas copiable avec un carnet | M | B3 |
| 7 | **Boutique personnalisée** : bannière, logo, adresse lisible, badge « Boutique Business » | Page boutique, lien et QR existants **\[À VÉRIFIER\]** | Visible par les clientes, donc valeur de marque ; peu coûteux | S–M | B1 |
| 8 | **Équipe sur la boutique** : 1 à 2 accès secondaires (assistante, personne qui confirme les commandes) | Un compte vendeur = un SellerProfile (OneToOne) ; la limite par boutique est en validation dans `SPEC_04` | Les gros comptes ne travaillent pas seuls ; à traiter avec rôles limités, sans toucher à la règle un compte = une boutique | L | B3 |
| 9 | **Mise en avant sur le Marché** : badge et un coup de pouce borné dans le classement par catégorie | Page `/ventes/` | Voir la règle d'équité ci-dessous | S | B2 |
| 10 | **Saisie assistée prioritaire** : 1 séance d'aide par mois | Priorité n° 1 déjà exercée à la main | Valeur forte pour les peu à l'aise avec l'informatique, **mais coûte ton temps** : limiter à 1 par mois et par compte | — | B1 (opérationnel) |

**Règle d'équité du classement (#9) :** le badge est cosmétique ; le coup de pouce de classement ne doit jamais l'emporter sur la performance réelle (taux de livraison honorée, ventes récentes). Payer ne doit pas masquer une boutique mauvaise, sinon la confiance des clientes, qui est ton actif, s'érode.

**Éléments volontairement non retenus pour Business :**

- **Prix barré / prix promo** : fonction de base pour tous les plans, ne pas la verrouiller.
- **Résumé hebdomadaire envoyé par WhatsApp ou SMS** : contredit « aucune promesse de SMS au lancement » ; envisageable plus tard en notification dans l'application.
- **Multi-boutiques par compte** : en conflit avec la règle un compte = une boutique ; à ne pas introduire sans la spec de limite par boutique.
- **Alertes de réapprovisionnement par message** : même raison ; remplacées par l'alerte dans le tableau de bord (#4).
- **Analyse par IA des ventes** : pas de coût d'inférence récurrent tant que le modèle économique n'est pas validé.
- **Tournée livreur par GPS** : à rattacher au chantier livraison (`SPEC_04`), pas à Business.

## 5. Mécanismes pour rendre Business attractif (bonnes pratiques)

Ces mécanismes sont ceux que les plateformes d'abonnement à succès appliquent de façon constante. Chacun est adapté à ton contexte et à tes contraintes techniques.

1. **Grille à trois niveaux lisibles** (bon / meilleur / le plus complet) : l'écart 5 000 → 10 000 se justifie par des outils, jamais par un chiffre arbitraire. Présenter les plans en parallèle avec les 4 ou 5 différences qui comptent, pas une liste de 20 lignes.
2. **Proposer l'upgrade au moment du besoin**, pas dans une page de tarifs : quand la vendeuse atteint son quota de Studio photo, ou ouvre le bilan complet, un encart court montre ce que Business débloque. Aucune relance par message.
3. **Essai ciblé de Business** (14 jours) offert aux comptes qui dépassent un seuil d'activité sur 2 mois consécutifs. Le seuil est **à calibrer avec les bilans réels** ; ne pas inventer de chiffre avant d'avoir des données.
4. **Preuve de rentabilité intégrée** (#2) : montrer chaque mois ce que l'outil a géré, face au prix payé. C'est le levier de rétention le plus efficace pour un petit commerce.
5. **Tarif fondateur verrouillé** : les premiers abonnés Business gardent 10 000 FCFA tant qu'ils restent actifs, même si le prix monte. Cela s'accorde avec ta logique de rareté (8 places).
6. **Plan annuel** (D5) : 2 mois offerts, paiement unique par Orange Money. Améliore la trésorerie et réduit le désabonnement.
7. **Rétrogradation douce** : aucune donnée perdue, accès en lecture seule. Réduit la peur de s'engager et protège la confiance.
8. **Pas de promesse non tenue** : ne vendre que des fonctions en production (D6). Une fonction annoncée mais absente coûte plus cher qu'un prix plus bas.

## 6. Programme créateurs : règles, données, calculs

### 6.1 Périmètre phase 1

Inscription par toi (pas de page publique au départ), lien et code uniques, attribution, calcul des commissions, saisie manuelle des règlements, relevé mensuel. **Pas** de tableau de bord partenaire, de retrait en ligne, ni de paliers.

### 6.2 Lien traçable

- Format `hayaflash.com/r/CODE` (ou `?ref=CODE`), le code est conservé en cookie **et** en stockage local.
- **Première attribution gagnante, immuable** : une fois le vendeur rattaché à un créateur, aucun autre code ne l'écrase.
- Fenêtre d'attribution : 30 jours entre le clic et la création du compte.
- Le rattachement est enregistré **à la création du compte**, avec date et source.
- Le lien peut pointer vers la page d'inscription vendeuse ou vers la page de présentation.

### 6.3 Calcul de la commission

- **Source de vérité** : la table des paiements d'abonnement réussis. Un paiement échoué, annulé, remboursé ou **de test** ne génère rien.
- Une ligne de commission par paiement d'abonnement, avec contrainte d'unicité sur l'identifiant du paiement : **un webhook rejoué ne peut pas créer deux commissions**.
- Montant = 30 % du montant encaissé (D1), arrondi au FCFA, calculé au moment de l'encaissement.
- Mois d'essai gratuit : aucune commission, et ils ne comptent pas dans les 12 mois (D3).
- Changement de plan : la commission suit le prix réellement payé chaque mois.
- **Plan annuel** : commission calculée à l'encaissement, **due en 12 échéances mensuelles** (arrondi entier, la dernière absorbe le reste), arrêt en cas de remboursement.
- **Remboursement après versement** : reprise compensée sur les versements suivants, tracée dans le journal.
- Exemple de contrôle (à reprendre comme test) :

| Plan | Paiement | Commission 30 % | Retenue Orange 1 % | Reste HayaFlash après commission et retenue |
| --- | --- | --- | --- | --- |
| MEDIUM | 2 000 | 600 | 20 | 1 380 |
| PRO | 5 000 | 1 500 | 50 | 3 450 |
| BUSINESS | 10 000 | 3 000 | 100 | 6 900 |

### 6.4 Modèle de données minimal (à confronter à l'existant)

- **Partner** : nom, téléphone, code, statut, date de début et de fin de contrat, nombre de places fondateurs.
- **Referral** : vendeur, partner, date, source ; unique par vendeur ; immuable.
- **CommissionEntry** : paiement d'abonnement (unique), partner, période, base, taux, montant, statut `due` → `payable` → `paid` (+ `reversed`), échéance si plan annuel.
- **PartnerPayout** : partner, date, montant, **référence libre** (ex. transaction Orange Money ou « espèces »), note, admin, horodatage ; il rattache des CommissionEntry et les passe à `paid`.
- **AuditLog** : qui, quoi, quand, avant/après, pour chaque changement de statut et chaque saisie de paiement. Immuable.

### 6.5 Statuts et validation

Le brief du collègue exigeait une double validation. Étant seul administrateur, ce serait un contrôle sans effet. À la place : **une validation unique + journal horodaté immuable + impossibilité de modifier un règlement saisi** (annulation par écriture inverse tracée). Si une deuxième personne a un jour accès à l'administration, la double validation pourra être ajoutée.

### 6.6 Anti-fraude proportionné

- Un créateur ne peut pas parrainer son propre numéro, ni un numéro déjà lié à lui (blocage technique).
- Un vendeur ne peut être rattaché qu'à un seul créateur (déjà garanti par l'unicité).
- Alerte à l'administrateur si un même numéro apparaît comme partenaire et vendeur, ou si plusieurs comptes naissent du même créateur en 24 h. **Alerte seulement**, pas de blocage automatique.
- Les paiements de test et les comptes à prix spécial sont marqués et exclus du calcul.

### 6.7 Écrans admin

- Liste des partenaires, filtres statut, rattachements.
- Vue « à régler » par période : par partenaire, nombre de filleuls payants, détail par plan, montant dû, déjà payé, solde.
- Saisie d'un règlement : montant, référence libre, date, note.
- Génération du **relevé mensuel** en texte à copier dans WhatsApp (filleuls payants, commission par plan, total, déjà versé, solde).
- Export CSV des règlements pour la comptabilité.

### 6.8 Condition pour une interface partenaire

Ouvrir un tableau de bord partenaire seulement après **15 partenaires actifs** ou si le relevé WhatsApp devient trop lourd à produire.

## 7. Recette de bout en bout (avant tout contact de créateur)

Chaque test se déroule d'abord en staging, puis en production avec un prix spécial de 100 FCFA sur un compte de test.

**A. Inscription de bout en bout**

1. Arriver par le lien de suivi d'un créateur fictif, créer le compte vendeur par téléphone et mot de passe, valider.
2. Vérifier : rattachement enregistré, un second lien n'écrase pas le premier, un lien invalide n'empêche pas l'inscription.
3. Cas d'échec : téléphone déjà existant, indicatif pays, abandon puis reprise.

**B. Paiement Orange Money**

1. Souscrire un plan avec le prix spécial de 100 FCFA.
2. Vérifier : montant reçu égal au montant attendu, statut `succès` seulement après confirmation Orange, abonnement activé une seule fois.
3. **Rejouer le webhook** : aucun doublon d'abonnement ni de commission.
4. Paiement annulé, expiré, montant différent : aucun abonnement, aucune commission.
5. Confirmer que le paiement de test **n'a généré aucune commission** (marquage test).
6. Passage ultérieur au vrai prix de PRO et de Business testé séparément.

**C. Lien traçable par créateur**

1. Deux créateurs de test, deux liens, chacun attribue correctement.
2. Un vendeur qui clique deux liens garde le premier.
3. Le créateur ne peut pas se parrainer.
4. La page admin « à régler » affiche des montants cohérents avec les tests (reprendre le tableau du § 6.3).

**D. Règlement manuel**

1. Saisir un versement avec référence ; les lignes passent à `paid` ; une tentative de modification est refusée ; l'annulation passe par écriture inverse ; le journal montre tout.

## 8. Phasage

| Phase | Contenu | Condition d'entrée |
| --- | --- | --- |
| **P0** | Audit de l'existant, configuration de plan éditable, prix spécial par vendeur, marquage des paiements de test | Immédiat |
| **P1** | Recette § 7 (A, B, C) + modèle Partner/Referral/Commission + admin « à régler » + relevé | P0 terminé |
| **P2** | Plan Business en liste d'attente + #1, #2, #3, #7 (rapides) + mécanisme d'upgrade au besoin | P1 en production |
| **P3** | Ouverture de Business quand **3 fonctions** sont livrées (D6) ; plan annuel ; #9 | P2 en production |
| **P4** | #4 stock maître, #5 fichier clientes | Retours des premiers comptes Business |
| **P5** | #6 ventes privées, #8 équipe, interface partenaire | 15 partenaires actifs ou demande claire |

Le contact avec les créateurs commence **après P1**, à raison d'**un à deux créateurs** puis d'une montée progressive, avec environ 1 heure par semaine de prospection.

## 9. Fichiers de gouvernance à créer ou mettre à jour

À adapter après l'audit, sans dupliquer l'existant :

- **Créer** `docs/specs/SPEC_05_PLANS_ET_BUSINESS.md` : § 3, 4 et 5.
- **Créer** `docs/specs/SPEC_06_PARTENAIRES_TRACKING.md` : § 6 et 7.
- **Mettre à jour** `docs/ROADMAP_V2_V3.md` : phasage § 8, en renvoyant à SPEC\_05 et SPEC\_06.
- **Mettre à jour** les conditions du programme créateurs (versement, base de calcul D1, plan annuel, reprise après remboursement).
- **Aligner** `SPEC_03` (plafond de la commission Distrib, D2) et `SPEC_04` (limite par boutique pour #8).
- **Mettre à jour** les textes publics et vidéos qui citent des prix : seulement au moment de l'ouverture de Business (P3).

## 10. Risques et points de vigilance

| Risque | Parade |
| --- | --- |
| Annoncer Business avant livraison | D6 : liste d'attente tant que 3 fonctions ne sont pas en production |
| Aucune vendeuse pilote encore opérationnelle | Ne pas hausser de prix ; Business vise les comptes déjà actifs. Priorité : faire vendre les 8 pilotes |
| Ton temps de support | Saisie assistée prioritaire limitée à 1 séance par mois et par compte |
| Dérive de l'existant | Audit P0, contrôle central des droits, aucun `if plan ==` dispersé |
| Litige sur une commission | Une ligne par paiement, journal immuable, relevé détaillé |
| Commission sur plan annuel difficile à expliquer | Échéances mensuelles, 12 mois fixes, exemple chiffré dans les conditions |
| Classement du Marché perçu comme acheté | Badge cosmétique, coup de pouce borné et subordonné à la performance |
