# HayaFlash : règles d'exécution et décisions retenues (V2)

Source de vérité pour toutes les tâches V2. Là où ce document diffère du « Brief de gouvernance v2.1 », ce document prévaut. Rapport d'audit de référence : `docs/releases/reports/pending/AUDIT_BRIEF_V2.md`.

## 1. Règles d'exécution (autonomie)

Travaille sans interruption. Prends toi-même les décisions techniques et consigne-les dans `docs/releases/reports/pending/JOURNAL_<TACHE>.md` (date, décision, raison, alternative écartée).

**Arrête-toi et demande UNIQUEMENT si :**

- a) une action touche staging ou production (déploiement, commande SSH, lecture ou écriture de la base distante) ;
- b) une migration est destructive, modifie des données existantes (RunPython, suppression, changement de type), ou sa numérotation est en conflit ;
- c) un changement altère le comportement visible des plans FREE, MEDIUM, PRO, des abonnés existants, du Marché pour des boutiques existantes, ou un montant d'argent (commission, prix, plafond) ;
- d) un test échoue et tu ne le corriges pas après deux tentatives, ou tu devrais supprimer ou affaiblir un test ;
- e) une décision de ce document contredit le code sans que tu puisses trancher ;
- f) il te faut un secret, un identifiant ou un accès que tu n'as pas ;
- g) la tâche exige un travail hors de son périmètre.

Dans tous les autres cas : continue et note l'incertitude dans le journal.

**Procédure :** une branche dédiée (worktree), commits atomiques, lint et tests concernés à chaque étape, suite complète à la fin. Aucune fusion dans `main`, aucun push sur `main`, aucun déploiement. Ne touche pas aux fichiers non suivis qui ne sont pas à toi ; n'utilise pas `git add -A` sans vérifier `git status`.

**Interdits permanents :** montants en FCFA entiers uniquement ; aucun paiement sortant dans HayaFlash ; aucun message WhatsApp ou SMS sortant automatique ; aucun appel à une IA externe ; ne pas toucher au comportement de FREE, MEDIUM, PRO.

**Fin de tâche :** rapport court dans le journal (fait / non fait / risques / commandes de validation pour le fondateur).

## 2. Vocabulaire

Dans tout ce qui concerne les partenaires : « partenaire », « lien personnel », « vendeur inscrit via le lien ». Les termes interdits sont listés dans `partenaires_regles.md` lignes 5 à 8 ; le test `VocabularyTests` doit rester vert.

## 3. Décisions retenues

**Stratégie partenaires.** Les partenaires sont des créateurs de contenu et influenceurs (`PartnerKind.creator`), dans un programme unique : 30 % du net encaissé (après retenue Orange 1 %), 12 mois par compte amené, contrat d'un an. Un partenaire peut aussi amener des grossistes, rattachés par l'admin. Le profil `seller_pilot` reste dans le code, dormant. Un seul niveau : aucune commission sur les revendeurs d'un grossiste. Le renouvellement de contrat reste à décider par le fondateur : ne rien coder.

**Décisions numérotées.**

- D1 : commission sur le **net**.
- D2 : plafond Distrib de 1 500 FCFA **par commande** (`SPEC_03` § 15.7).
- D3 : les 12 mois partent du premier paiement encaissé **après l'acceptation des conditions** ; mois gratuits exclus.
- D4 : le plan à 10 000 FCFA s'appelle **BUSINESS** ; PRO reste à 5 000.
- D5 : plan annuel reporté en P3 (prix annuel dans `PlanConfig`, pas de champ de durée sur `Subscription`).
- D6 : Business s'ouvre quand le bilan complet et la ligne de valeur sont livrés **et** qu'au moins une fonction à forte valeur (Mon stock étapes A et B, ou Studio photo) est en production. Avant : liste d'attente et tarif fondateur (champ dédié sur l'abonnement, jamais `SellerPriceOverride`).
- D7 : Mon stock (étapes A et B de la roadmap) avant le Studio photo.
- D8 : spécifications numérotées dans `docs/specs/`, phasage dans `docs/ROADMAP_V2_V3.md`. Les doublons de `docs/evolutions/` sont archivés dans `docs/archive/` avec un renvoi, rien n'est supprimé. Ignorer `.claude/worktrees/` et `Claude outputs/`.
- D9 : commission sur les grossistes : le **rattachement est enregistré dès maintenant** (clé `distributor` facultative sur `Referral`, contrainte « une seule cible », attribution par l'admin) ; le calcul de la part du partenaire sur Distrib est fait **à la main** par relevé au début ; la source de commission générique viendra plus tard avec l'affectation paiement/ligne de Distrib.
- D10 : voir « Confiance et paiement » ci-dessous.
- D11 : un drapeau global `PARTNER_REGISTRATIONS_OPEN` ferme ou ouvre les inscriptions de partenaires.

**Confiance et paiement.**

- Le paiement se fait hors HayaFlash : aucun prépaiement n'est géré par la plateforme. `SPEC_04` ne doit pas présenter le prépaiement comme une fonction contrôlée.
- Texte d'avertissement affiché sur la page de vente, le formulaire de commande et la confirmation : « **Paie à la livraison, une fois le produit vérifié et conforme.** Si tu choisis de payer avant, c'est sous ta propre responsabilité et en connaissance des risques. HayaFlash ne reçoit aucun paiement et ne garantit pas les transactions entre toi et la vendeuse. » Confirmation : « Commande enregistrée. Rappel : ne paie qu'à la livraison, après avoir vérifié ton produit. Un problème avec cette boutique ? Signale-la ici. » Ne pas modifier les CGU : proposer la formulation dans le journal pour relecture par l'avocat.
- Niveaux de confiance d'une boutique : 0 (inscrite), 1 (vérifiée : contact de l'équipe depuis le numéro inscrit et première commande livrée et payée), 2 (fiable : nombre de commandes livrées sans litige, seuil à calibrer). Toutes les boutiques **existantes** passent au niveau 1 (AddField avec défaut 1 puis AlterField défaut 0, sans RunPython). La règle de listage sur le Marché ne s'applique que si le drapeau `MARKET_REQUIRE_VERIFIED` est actif (défaut : faux).
- Une cliente peut signaler une boutique ; l'admin peut suspendre ou réactiver une vendeuse (avec entrée au journal d'audit) ; une boutique suspendue disparaît du Marché.

**Plan BUSINESS (10 000 FCFA).** Il se justifie par des outils, jamais par du volume. Contenu : bilan complet vendeuse avec export (#1), ligne « HayaFlash t'a fait gérer X FCFA » (#2), boutique personnalisée et badge (#7), rapport des sources de vente (F12), Mon stock (#4), mise en avant bornée sur le Marché (#9, jamais au-dessus de la performance réelle), Studio photo (#3), fichier clientes (#5), ventes privées (#6), équipe sur la boutique (#8). Toute fonction Business passe par un contrôle central `plan_has_feature(plan, feature)` : jamais de `if plan == 'BUSINESS'` dispersé.

**F12 (sources de vente).** La source est déclarée dans le lien par un paramètre `s` (valeurs `wa`, `qr`, `marche` ; absence = direct). Pas de source « partenaire » pour les commandes. Comptages et totaux seulement, jamais de donnée personnelle de cliente, aucun traceur externe.

**F11 (assistant de conversation).** Écartée. Remplacée par « Questions de la vente » (questions publiques une fois répondues, réponses texte ou audio préenregistrées, interrupteur actif/pause par vente, aucune escalade vers l'admin). Spécification seulement, aucun code avant décision du fondateur.

## 4. Documents de référence

Le « Brief de gouvernance v2.1 » devient une archive. Après la tâche de gouvernance, la référence est `docs/specs/SPEC_05_PLANS_ET_BUSINESS.md` et `docs/ROADMAP_V2_V3.md`.
