# Feuille de route V2 / V3 — idées validées et reportées

Document de gouvernance. Rien ici n'est implémenté sauf mention contraire.
Règle commune à toute évolution : app Django séparée, migrations **additives uniquement**,
interrupteur (feature flag) désactivé par défaut, staging 48 h vert, tag git + sauvegarde
avant mise en prod, aucun changement de `orders/services/create_order.py` sans tests de
non-régression dédiés.

## 0. Avant tout : lancement des 8 pilotes (passation du 22/10/2026)

**Règle : pas de nouvelle fonctionnalité en production avant que cette liste soit verte**
(la saisie assistée, priorité 0, est la seule exception car elle sert directement les pilotes).

- [x] **Validé par le fondateur** (lancement officiel aux vendeurs pilotes, essai de 1 mois) — Essai de bout en bout **en production** avec un numéro neuf : inscription (code reçu ?),
      paiement 100 FCFA (tarif spécial), note vocale lisible par le vendeur propriétaire et 404 pour
      un autre vendeur et pour `/media/delivery/audio/` (E4), QR encodant `hayaflash.com`,
      lettre v1.2 acceptée en ligne.
- [x] Première sauvegarde automatique de la prod vérifiée le 23/10 :
      `tail -n 3 /home/sam/sauvegardes/prod/backup.log`. Relevé le 01/11/2026 : exécutions quotidiennes `OK` du 28/10 au 01/11 (02 h 45) ; voir `docs/releases/reports/inventaire-prod-20261101.md` (la ligne du 23/10 n'a pas été relue ; copie vers D: non contrôlée).
- [ ] Politique de confidentialité : durées de conservation cohérentes avec les purges réellement
      actives ; E2 (preuve d'acceptation supprimée avec le compte, migration `core 0003`) non déployé.
- [x] À confirmer : clés Orange réelles ou bac à sable en prod ; valeur de `SMS_NOTIFICATIONS_ENABLED`. Relevé le 01/11/2026 : `SMS_NOTIFICATIONS_ENABLED` absent du `.env` prod (défaut faux, `config/settings/base.py:615`) ; variables `ORANGE_ML_*` renseignées, réel ou bac à sable **non confirmé** (case laissée ouverte). Relevé du 02/11/2026 : clés **identiques** sur staging et prod (voir F-165 dans `docs/releases/v1.0.0-rc1.md`). **Confirmé par le mainteneur le 02/11/2026 : clés réelles** (Orange fournit les mêmes identifiants en bac à sable et en production) ; F-165 clos en risque accepté.

### Règles communes de travail et d'exploitation

- Lecture seule d'abord ; tests rouges d'abord ; commit local seulement sur accord ; **jamais de push,
  merge ni action sur le VPS sans accord**.
- Lint CI : `ruff check . --select E,F,W --ignore E501` → « All checks passed! » ; `makemigrations --check`.
- Tests : séries PostgreSQL (`hf-pg-test`, port 55432) et sqlite ; ne pas toucher aux ports 5432/5433/6379.
- **Lettres figées** : ne jamais modifier `partners/legal_docs.py` ni `templates/partners/legal/` (SHA-256 verrouillés).
- **Environnements** (même hôte 31.207.39.116) :
  - staging : `/srv/hayaflash`, projet `hayaflash`, nginx `127.0.0.1:8020`, staging.hayaflash.com ;
  - **production** : `/srv/hayaflash-prod` (dépôt Git), projet `hayaflash-prod`, nginx `127.0.0.1:8021`,
    volumes `hayaflash-prod_*`, hayaflash.com. `ALLOWED_HOSTS` sans 127.0.0.1 : tester avec
    `-H 'Host: hayaflash.com'`.
  - **La procédure de déploiement de la production n'est pas celle du staging : ne jamais utiliser
    les commandes de staging pour la prod.**
- Sauvegardes prod : `/home/sam/hf-backup-prod.sh` (cron de sam 02h45, 14 jours), copie hebdomadaire
  sur `D:\sauvegardes-vps\prod`. Staging : aucune sauvegarde planifiée. **Jamais `sudo crontab -`**
  (la crontab root porte la sauvegarde LWS/Hestia).
- PostgreSQL système : ne pas modifier `pg_hba` sans iptables (symain_db, packindigo en dépendent).
  Ne pas toucher aux autres projets du serveur (bitiki, packgravity, symain).

## 1. Priorités (décidées le 22/10/2026)

| Rang | Fonctionnalité | Déclencheur |
|---|---|---|
| 0 | **Saisie assistée** : l'équipe crée vente et produits pour un vendeur — spec : `docs/specs/SPEC_00_SAISIE_ASSISTEE.md` | **Implémenté le 22/10** (non commité) — valider sur le staging puis déployer en prod |
| 1 | Prix barré + mention « Prix promo » sur `orders/client_order.html` (interrupteur global) — spec : `docs/specs/SPEC_01_PRIX_BARRE.md` | **Implémenté le 23/10**, déployé avec la saisie assistée |
| 2 | Studio photo (détourage `rembg`, worker Celery dédié, file `studio`, mémoire limitée) — spec : `docs/specs/SPEC_02_STUDIO_PHOTO.md` | Mesure RAM faite le 22/10 : feu vert |
| 3 | Module Distrib / Grossistes (V1, voir §3) — spec : `docs/specs/SPEC_03_DISTRIB_V1.md` | Cadrage terminé le 22/10 |
| 4 | Stock étapes A (« Mon stock ») et B (quantité mise en vente, affichage) | Demande des pilotes |
| 5 | Recherche sur le Marché + journal des recherches sans résultat | ≥ 30 boutiques actives |
| 6 | Stock étape C (blocage strict par vente, touche `create_order`) | Ventes simultanées constatées |
| 7 | Distrib V2 : annuaire des grossistes + candidatures revendeurs, puis niveaux revendeurs (voir § « Distrib V2 ») | ≥ 3 grossistes actifs (annuaire), ≥ 6 grossistes actifs ou ~mi-janvier 2027 (niveaux) |

## 2. Plages horaires communes des ventes live (« Marché du soir »)

**Idée** : concentrer les ventes flash de toutes les boutiques sur des plages communes
(ex. midi et soirée) pour animer le Marché, regrouper l'audience, et laisser aux vendeuses
du temps pour se reposer et organiser les livraisons.

**Décision** : reporté. Approche progressive :
1. Mesurer (analytics existants) les heures réelles des commandes pendant ≥ 3 mois.
2. Incitation d'abord : ventes dans les plages « heures de pointe » mises en avant sur le
   Marché ; ventes hors plage autorisées mais moins visibles.
3. Obligation éventuelle seulement plus tard, éventuellement sous forme d'événements
   (ex. « Grand Marché du vendredi soir »).

**Points de vigilance** : liberté des vendeuses (risque de départs), concurrence au détriment
des petites boutiques dans une même plage, sécurité des livraisons tard le soir (fin conseillée
vers 23 h plutôt que 2 h), heures de prière et Ramadan, HayaFlash ne contrôle que l'ouverture
des ventes flash, pas les lives TikTok eux-mêmes.

**Déclencheur** : ≥ 30 à 50 boutiques actives et ≥ 3 mois de données horaires.

## 3. Module Distrib / Grossistes — décisions de conception V1

- **App indépendante** `distrib`, URLs `/distrib/`, templates et tableau de bord propres,
  interrupteur général. Retirer le module ne doit rien changer au reste de HayaFlash.
- **Liste préalable des revendeurs** : le grossiste enregistre nom + numéro (indicatif choisi
  à la saisie, numéro normalisé, jamais de pays déduit). Quand un vendeur dont le numéro figure
  dans la liste crée sa boutique — **ou se connecte s'il a déjà une boutique** — on lui propose
  de rejoindre ce grossiste ; le lien n'est créé **qu'après son acceptation** (consentement au
  partage de ses ventes).
- **HayaFlash reste ouvert à tous** : la liste sert à rattacher, jamais à bloquer une inscription.
- **Cloisonnement** : le grossiste ne voit que les revendeurs rattachés et **uniquement les
  commandes portant sur les produits issus de son catalogue**, jamais les autres produits du
  revendeur ni les vendeurs non inscrits chez lui.
- **Circuit de commande inchangé** : le revendeur importe un produit du catalogue de gros, ce
  qui crée un `Product` normal ; lien stocké dans `distrib.ImportedProduct` (aucun champ ajouté à `products`). Stock V1 =
  allocation par revendeur, avec reprise des unités non vendues.
- **Suivi** : table `DistribSettlement` séparée (Commandée → En livraison → Livrée [boutique]
  → Livrée et payée [grossiste uniquement]). Seul le dernier statut déclenche marge revendeur,
  commission HayaFlash et encours.
- **Pilotage HayaFlash** : filtre « Distrib » dans le tableau de bord admin existant + une page
  dédiée (grossistes, encours, commissions, bouton Suspendre).
- **Argent** : HayaFlash ne touche jamais l'arg
- ent des ventes. Commission : pilote 2 mois à 0 %,
  puis encours plafonné réglé chaque semaine (Orange Money), produits masqués au-delà du plafond ;
  prépaiement facultatif plus tard. Négociation : ouverture 10 %, cible 6–7 %, plancher 5 %,
  minimum ~250–300 FCFA par commande, plafond par commande.
- **Reporté en V2** : inscription libre des grossistes, suspension automatique, notifications
  WhatsApp/SMS, sous-domaine distrib.hayaflash.com, stock commun, prépaiement.
- **Hors code** : CGU (transmission de l'adresse de livraison au grossiste), contrat grossiste.

## Tarification et paiement par vente (décidé le 04/11/2026)

Rien n'est implémenté. Aucun changement de prix ni de quota en production pour l'instant.

**Principe**
- Prix actuels inchangés pendant le lancement (Gratuit 3 ventes/mois, Medium 2 000 FCFA, Pro 5 000 FCFA).
- Les pilotes actives deviennent « prix fondateur » : elles gardent le prix actuel tant qu'elles restent abonnées.
- Une hausse éventuelle ne concernera que les nouvelles inscrites, une fois la valeur prouvée par les bilans mensuels.
- Pistes à tester plus tard : Medium 3 000 FCFA, Pro 7 500 à 10 000 FCFA avec plus de valeur (Studio photo, bilan mensuel, mise en avant sur le Marché).

**Option « paiement par vente »** (500 à 1 000 FCFA par vente flash au-delà du quota gratuit)
- Étape 1 : demander aux pilotes, avant la fin du mois Pro gratuit, leur préférence (abonnement ou paiement par vente).
- Étape 2 : si demandé, gestion manuelle (paiement Orange Money, vente accordée via l'admin et le prix spécial par vendeuse).
- Étape 3 : développement seulement si ≥ 50 % des pilotes actives le préfèrent, ou si la gestion manuelle dépasse ~10 vendeuses.
- Zones sensibles : logique de quota (fail-closed) et circuit Orange Money. Tests de non-régression dédiés obligatoires.

## Marché vivant (décidé le 03/11/2026)

Rien n'est implémenté. Priorité à l'activation des pilotes ; seule la phase 1 peut avancer en parallèle.

- **Phase 1 (maintenant, lot léger)** : message de bienvenue et 3 à 4 bulles d'orientation, uniquement sur le Marché et à la première visite (recherche, boutique, filtres, vente en cours). « Passer », « Ne plus afficher », « Revoir l'aide ». Mémoire en localStorage avec try/catch, code dans `hf-base.js` (CSP), aucune bibliothèque lourde. Pas de visite guidée si la cliente arrive directement sur une vente.
- **Phase 2** : « Suivre la boutique » et « Préviens-moi » (notifications web). Déclencheur : premières ventes réelles des pilotes.
- **Phase 3** : bulles d'activité réelle, teasers, badges, tri « Pour toi » par règles simples. Déclencheur : 10 à 20 boutiques actives.
- **Phase 4** : recommandations et fil pro Distrib. Déclencheur : quelques milliers de visites par mois.
- **Interdits** : fausse activité ou faux acheteurs, messagerie privée, commentaires publics, défilement infini.
- **Données** : profil d'intérêt anonyme, durée de conservation courte, mention dans la politique de confidentialité.

## Distrib V2 — Annuaire des grossistes, candidatures et niveaux revendeurs (décidé le 14/11/2026)

Rien n'est implémenté. Aucune ligne de code avant le déclencheur. Complète Distrib V1
(`docs/specs/SPEC_03_DISTRIB_V1.md`) sans en changer les règles : le grossiste garde le
contrôle (rien n'est rattaché sans son accord), cloisonnement, argent jamais touché par HayaFlash.

### Étape 1 — Annuaire et candidatures (déclencheur : ≥ 3 grossistes actifs)

- **Annuaire** des grossistes, réservé aux vendeurs connectés (pas sur le Marché public).
  Le grossiste choisit d'y figurer ou non (**opt-in**, désactivé par défaut).
- **Fiche en lecture seule** : nom, description, catégories, marché ou quartier, produits avec
  photos et descriptions. **Jamais** : prix de gros, numéro de téléphone, adresse exacte
  (visibles seulement après affiliation acceptée). Tout contact passe par HayaFlash.
- **Bouton « Devenir revendeur »** : nom personnel ou de la boutique (pré-rempli), quartier
  (bouton géolocalisation avec consentement, on enregistre une position **approximative**),
  message court prédéfini avec le nom du grossiste en paramètre. Plus tard : message vocal
  optionnel (bambara).
- **Garde-fous** : compte vendeur HayaFlash obligatoire ; **3 candidatures en attente** au
  maximum ; une candidature expire après **14 jours** sans réponse ; pas de nouvelle
  candidature au même grossiste pendant 30 jours après un refus.
- **Côté grossiste** : liste des candidatures (nom, boutique, quartier, niveau, ancienneté) →
  Accepter / Refuser. **Accepter crée une `ResellerInvite`** (circuit V1 existant, statut
  accepté puisque le revendeur a lui-même demandé) : aucun nouveau circuit d'affiliation.
- **Classement de l'annuaire** : grossistes les plus réactifs (délai de réponse aux
  candidatures, taux de livraison) en tête. Motive aussi les grossistes.

### Étape 2 — Niveaux revendeurs (déclencheur : ≥ 6 grossistes actifs, ou ~mi-janvier 2027)

Objectif : le nombre de grossistes auxquels un revendeur peut être affilié **en même temps**
se mérite par l'effort (prudence + motivation). Candidater reste libre (dans la limite
ci-dessus) ; c'est l'**affiliation active** qui est plafonnée.

| Niveau | Affiliations simultanées | Critères d'accès (provisoires) |
|---|---|---|
| Débutant | 1 | Compte créé |
| Confirmé | 2 | 4 semaines glissantes, moyenne ≥ 5 livraisons payées / semaine, annulations + « pas livré » < 20 % |
| Pro | 3 | 8 semaines au niveau Confirmé, moyenne ≥ 10 livraisons payées / semaine, respect des prix minimum |
| Élite | 5 | 12 semaines au niveau Pro, incidents quasi nuls |

**Seuils provisoires : à recalibrer sur les données réelles avant activation** (revue
obligatoire, consignée dans le journal).

**Règles**
- **Ce qui compte** : uniquement les `DistribSettlement` au statut `paid_confirmed`, comptés
  **par commande** (pas par ligne de produit), toutes affiliations confondues. Jamais une
  déclaration du revendeur, jamais le nombre de ventes flash lancées. Point à trancher à la
  calibration : compter ou non les confirmations par présomption (`confirmation_source`
  automatique à 72 h).
- **Calcul par le système** (tâche Celery quotidienne), jamais modifiable par le grossiste.
  Correction manuelle réservée au staff, journalisée.
- **Visibilité du niveau** : le revendeur lui-même, les grossistes auxquels il est affilié ou
  candidat, et le staff HayaFlash. **Jamais** les clientes, le Marché ni la page publique.
- **Le grossiste peut exiger un niveau minimum** (ex. « réservé Confirmé et plus »).
- **Baisse de niveau** (performances sous le seuil 4 semaines de suite) : un seul niveau à la
  fois ; **aucune affiliation en cours n'est coupée**, le revendeur ne peut simplement plus en
  ajouter tant qu'il n'est pas remonté.
- **Protection du revendeur** : rupture par le grossiste avec préavis de 7 jours (sauf fraude
  ou impayé, motif obligatoire) ; ventes en cours menées à terme ; marges dues versées.
- **Droits du grossiste** : prix de revente minimum, plafond de stock alloué par revendeur,
  suspension motivée, statistiques par revendeur (règles V1 inchangées).

**Activation** : interrupteur `DISTRIB_LEVELS_ENABLED` (faux par défaut), basculé à la main
par l'admin — **pas** de déclenchement automatique sur le nombre de grossistes (un grossiste
inscrit mais inactif, ou un départ qui ferait repasser à 5, rendrait le compteur instable).
Tant qu'il est coupé : **2 affiliations actives au maximum pour tout le revendeur**, sans niveau affiché.

**Rétroactivité** : aucune donnée à créer d'ici là. `DistribSettlement` conserve déjà
`invite` (revendeur), `distributor`, `status`, `paid_confirmed_at`, `declared_at`,
`created_at` : le jour de l'activation, chaque niveau est calculé sur tout l'historique.
**Ne pas supprimer ni purger ces champs ou ces lignes** (hors données de test).

### Contraintes techniques (rappel des règles communes)

Migrations additives uniquement (ex. `ResellerApplication`, `ResellerLevel`, champs opt-in /
niveau minimum sur `Distributor`), rien dans `orders/`, `payments/`, `create_order` ;
pas de script inline (CSP) ; staging 48 h vert, tag git + sauvegarde avant prod.

---

## 4. Phasage V2 en trois vagues (décidé le 21/11/2026)

Source des décisions : `docs/EXECUTION_V2.md` § 3. Spécifications : `docs/specs/SPEC_05_PLANS_ET_BUSINESS.md` (plans, Business, confiance, avertissement) ; `docs/specs/SPEC_03_DISTRIB_V1.md` (Distrib) ; `docs/specs/SPEC_04_STATUTS_LIVRAISON_PAIEMENT.md` (livraison et paiement) ; `docs/specs/SPEC_02_STUDIO_PHOTO.md` (Studio).

Ce phasage remplace le phasage P0 à P5 du « Brief de gouvernance v2 ».

| Vague | Contenu | Condition d'entrée |
|---|---|---|
| **Vague 1 : fondations et confiance** | Plan BUSINESS en liste d'attente (`is_active = False`) ; `plan_has_feature` ; `is_pro` accepte BUSINESS ; niveaux de confiance (migration sans `RunPython`, drapeau `MARKET_REQUIRE_VERIFIED` faux) ; signalement par une cliente ; suspension et réactivation par l'admin (journal d'audit) ; avertissement de paiement sur la page de vente, le formulaire et la confirmation ; F12 (paramètre `s`) ; tarif fondateur (champ dédié) ; lien personnel qui garde le premier cookie (tâche B) ; drapeau `PARTNER_REGISTRATIONS_OPEN` (D11) | Lancement des pilotes validé (§ 0) |
| **Vague 2 : fonctions Business** | Bilan vendeuse complet et export ; ligne « HayaFlash t'a fait gérer X FCFA » ; Mon stock étapes A et B ; boutique personnalisée et badge ; mise en avant bornée sur le Marché ; Studio photo (après Mon stock, D7) ; **ouverture de Business** dès que les conditions de SPEC_05 § 2.3 sont réunies | Vague 1 en production |
| **Vague 3 : plus tard** | Fichier clientes ; ventes privées ; équipe sur la boutique ; plan annuel (D5) ; « Questions de la vente » si le fondateur la retient (SPEC_05 § 9) ; commission générique sur Distrib (affectation paiement / ligne) ; renouvellement des contrats partenaires (décision du fondateur, rien à coder) | Retours des premiers comptes Business, ou 15 partenaires actifs |

**Règles de vague.** Aucune fonction n'est annoncée publiquement avant sa mise en production (D6). Chaque vague passe par staging 48 h, tag git et sauvegarde avant production. Une fonction qui change le comportement de FREE, MEDIUM ou PRO, des abonnés existants, du Marché pour une boutique existante ou un montant d'argent demande l'accord du fondateur (EXECUTION_V2 § 1, c).

**Point ouvert.** Le calendrier de l'ouverture de Business (SPEC_05 point O5) n'est pas fixé.
