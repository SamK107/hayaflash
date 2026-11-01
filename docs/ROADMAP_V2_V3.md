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
- [ ] À confirmer : clés Orange réelles ou bac à sable en prod ; valeur de `SMS_NOTIFICATIONS_ENABLED`. Relevé le 01/11/2026 : `SMS_NOTIFICATIONS_ENABLED` absent du `.env` prod (défaut faux, `config/settings/base.py:615`) ; variables `ORANGE_ML_*` renseignées, réel ou bac à sable **non confirmé** (case laissée ouverte).

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
- **Argent** : HayaFlash ne touche jamais l'argent des ventes. Commission : pilote 2 mois à 0 %,
  puis encours plafonné réglé chaque semaine (Orange Money), produits masqués au-delà du plafond ;
  prépaiement facultatif plus tard. Négociation : ouverture 10 %, cible 6–7 %, plancher 5 %,
  minimum ~250–300 FCFA par commande, plafond par commande.
- **Reporté en V2** : inscription libre des grossistes, suspension automatique, notifications
  WhatsApp/SMS, sous-domaine distrib.hayaflash.com, stock commun, prépaiement.
- **Hors code** : CGU (transmission de l'adresse de livraison au grossiste), contrat grossiste.
