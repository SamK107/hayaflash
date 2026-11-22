# SPEC_05 — Plans, BUSINESS, confiance et avertissement de paiement

Statut : **spécification**, aucun code écrit par cette spec. Source de vérité des décisions : `docs/EXECUTION_V2.md` (§ 3, qui prévaut sur le « Brief de gouvernance v2 »). Phasage : `docs/ROADMAP_V2_V3.md` § 4.
Dernière mise à jour : 2026-11-21.

---

## 0. Périmètre

Cette spec couvre :

1. les plans FREE, MEDIUM, PRO et le nouveau plan BUSINESS (§ 1 à § 3) ;
2. le contrôle central des fonctionnalités `plan_has_feature` et les garde-fous de migration (§ 4 à § 5) ;
3. le prix fondateur (§ 6) et le plan annuel reporté (§ 7) ;
4. la source de vente F12 (§ 8) ;
5. « Questions de la vente », spécification seulement (§ 9) ;
6. les niveaux de confiance des boutiques et le signalement (§ 10) ;
7. l'avertissement sur le paiement (§ 11).

Hors périmètre : le programme partenaires (`docs/releases/reports/partenaires_regles.md`), Distrib (`docs/specs/SPEC_03_DISTRIB_V1.md`), les statuts de livraison et de paiement (`docs/specs/SPEC_04_STATUTS_LIVRAISON_PAIEMENT.md`), le Studio photo (`docs/specs/SPEC_02_STUDIO_PHOTO.md`).

---

## 1. Plans existants (inchangés)

Source : `subscriptions/models.py` (`Plan`, `PlanConfig`), `subscriptions/services/plans.py` (lecture unique des tarifs, quotas, durées et fonctionnalités).

| Plan | Prix / mois | Ventes flash / mois | Durée d'un paiement |
|---|---|---|---|
| FREE | 0 | 3 | — |
| MEDIUM | 2 000 | 10 | 31 jours (`PlanConfig.duration_days`) |
| PRO | 5 000 | illimité | 31 jours |

Règles en vigueur, à ne pas modifier :
- les tarifs et quotas sont en base (`PlanConfig`), jamais en constante ;
- un changement de tarif ne touche que les **nouveaux** paiements (`SubscriptionPayment.amount` fige le montant) ;
- un abonnement payant expiré retombe sur FREE (fail-closed) ;
- les montants sont des FCFA entiers, sans centimes.

**Ce qui ne change pas pour les abonnés MEDIUM et PRO.** Aucune migration ne modifie la valeur `pro` ou `medium`.

---

## 2. Plan BUSINESS

Décision D4 : le plan à 10 000 FCFA s'appelle **BUSINESS**. PRO reste à 5 000 FCFA.

### 2.1 Ce qui est ajouté

- Une valeur `business` dans l'énumération `Plan`, ajoutée sans renommer les valeurs existantes.
- Une ligne `PlanConfig` (prix 10 000, durée 31 jours, ventes illimitées, `is_active = False`) créée par **migration de données séparée**.
- `is_active = False` tant que l'ouverture n'est pas décidée (D6, § 2.3) : le plan n'est pas proposé à la souscription.

### 2.2 Justification

Business se justifie par des outils qui font gagner du temps ou de l'argent, jamais par du volume. Les ventes restent bornées par 3 ventes par jour et 2 heures par vente.

### 2.3 Ouverture (D6)

Business s'ouvre quand **les trois conditions** sont réunies (décision du 22/11/2026, point O5 résolu) :
- la condition D6 est remplie : le bilan complet vendeuse et la ligne de valeur « HayaFlash t'a fait gérer X FCFA » sont en production ; et au moins une fonction à forte valeur est en production : **Mon stock étapes A et B**, ou **Studio photo** ;
- **14 jours de fonctionnement en production sans incident** après la mise en production de la dernière de ces fonctions ;
- le fondateur donne son accord explicite (EXECUTION_V2 § 1, c : le plan change ce que voient les vendeuses).

La **liste d'attente est un signal, pas une condition** : son nombre ne déclenche ni n'avance l'ouverture.

Avant l'ouverture : liste d'attente et tarif fondateur (§ 6). Aucun prix public affiché, aucune relance par message.

---

## 3. Fonctions Business

Contenu validé (EXECUTION_V2 § 3), numérotation du brief conservée :

| # | Fonction | Dépend de | Vague (ROADMAP § 4) |
|---|---|---|---|
| 1 | Bilan mensuel complet vendeuse, avec export | `analytics/services/monthly_report.py` (`shop_bilan`, existant côté admin) | 2 |
| 2 | Ligne « HayaFlash t'a fait gérer X FCFA » | Données de `SubscriptionPayment` et du bilan | 2 |
| F12 | Rapport des sources de vente (§ 8) | Paramètre `s` dans les liens | 1 |
| 4 | Mon stock (étapes A et B de la roadmap) | `products` (`stock_available`, `adjust_stock`) | 2 |
| 7 | Boutique personnalisée et badge « Boutique Business » | `SellerProfile` (à étendre) | 2 |
| 9 | Mise en avant bornée sur le Marché | `analytics/services/market.py` | 2 |
| 3 | Studio photo (quota large) | SPEC_02 | 2, après Mon stock (D7) |
| 5 | Fichier clientes (historique, fiabilité, lien `wa.me` pré-rempli) | `orders/services/unhonored.py` | 3 |
| 6 | Ventes privées | — (nouveau) | 3 |
| 8 | Équipe sur la boutique (1 à 2 accès secondaires) | Limite par boutique, `SPEC_04` § 7.3 | 3 |

**Règle d'équité (#9).** Le badge est cosmétique. La mise en avant ne passe jamais au-dessus de la performance réelle (taux de réalisation, ventes récentes). Une boutique mal notée ne se rachète pas avec la mise en avant.

**Éléments volontairement non retenus pour Business :**
- prix barré et prix promo : fonction de base de tous les plans, non verrouillée ;
- résumé hebdomadaire envoyé par WhatsApp ou SMS : contredit la règle « aucun SMS ni message sortant automatique » ;
- multi-boutiques par compte : contredit « un compte = une boutique » ;
- alertes de réapprovisionnement par message : remplacées par l'alerte dans le tableau de bord ;
- analyse des ventes par IA : interdit (« aucun appel à une IA externe ») ;
- tournée livreur par GPS : rattachée à `SPEC_04`, pas à Business.

---

## 4. Contrôle central `plan_has_feature`

- Une seule fonction, `plan_has_feature(plan, feature) -> bool`, décide de l'accès à toute fonction Business. Elle lit la configuration du plan (`PlanConfig`, `plans.py`).
- **Interdit** : `if plan == 'business'` ou toute comparaison directe de plan dispersée dans les vues, templates ou services.
- Les contrôles existants (`has_stats`, `has_advanced_stats`, `is_pro`, `effective_plan`) sont **migrés vers cette fonction** dans une PR dédiée, sans changer leur résultat pour FREE, MEDIUM et PRO.
- Point de vigilance : `Subscription.is_pro` teste `plan == PRO` exactement (`subscriptions/models.py:60-61`). Tant qu'il n'accepte pas BUSINESS, un abonné BUSINESS perdrait les fonctions PRO. Cette correction est un prérequis de l'ouverture de BUSINESS.

---

## 5. Garde-fous de migration

1. **Ajout de la valeur `business`** : migration d'état (`choices`) sur `Subscription.plan`, `SubscriptionPayment.plan`, `PlanConfig.plan`. Aucune donnée modifiée.
2. **Ligne `PlanConfig` BUSINESS** : migration de données **séparée**, réversible, sans toucher aux lignes existantes.
3. **`SellerPriceOverride.plan`** reste limité à MEDIUM et PRO tant que Business n'est pas ouvert (le tarif spécial de test à 100 FCFA ne concerne pas Business).
4. **Rétrogradation sans perte** : un compte qui repasse de BUSINESS à PRO garde toutes ses données. Les fonctions Business deviennent en lecture seule. Rien n'est supprimé. S'appuie sur le fail-closed existant.
5. **Chaque migration** est additive, réversible, testée en staging puis en production, avec tag de retour avant fusion.
6. **Numérotation** : vérifier `makemigrations --check` avant chaque migration ; une migration `products` ou `subscriptions` en conflit de numéro est un arrêt (EXECUTION_V2 § 1, b).

---

## 6. Tarif fondateur

Décision D6 : les premiers abonnés Business gardent leur prix tant qu'ils restent actifs, même si le prix monte.

- **Mécanisme dédié** : un champ sur l'abonnement (`founder_price`, entier FCFA, nullable), posé à la souscription pendant la phase d'attente. Un abonné avec `founder_price` renouvelle à ce prix.
- **Interdit** : utiliser `SellerPriceOverride`. Il est limité à 30 jours (`SPECIAL_PRICE_MAX_DAYS`) et sert au test de paiement, pas à un prix verrouillé.
- Le champ n'est pas modifiable depuis l'espace vendeuse.

**Règles de cohorte (décision du 22/11/2026, point O2 résolu)**
- **Cohorte limitée à 20 comptes ou 60 jours après l'ouverture de Business, selon ce qui arrive en premier.** Au-delà, le prix fondateur n'est plus proposé.
- Le prix est **verrouillé tant que l'abonnement est continu**.
- Une **interruption de plus de 30 jours** fait perdre le prix fondateur : le compte revient au prix courant à sa reprise.
- **Mise en œuvre en P3 seulement** (ROADMAP § 4, vague 2 ou 3 selon l'ouverture) ; rien n'est codé avant.

**Précision.** Le chiffre « 8 » du brief de gouvernance désigne la **cohorte des partenaires fondateurs** (`PARTNER_FOUNDER_SLOTS = 8`, `partners/models.py`), **pas** les comptes Business.

---

## 7. Plan annuel (D5, reporté en P3)

- Prix annuel dans `PlanConfig` (nouvelle colonne ou nouvelle ligne), pas de champ de durée sur `Subscription`.
- Remise : 2 mois offerts (PRO 50 000, BUSINESS 100 000), à titre indicatif.
- Ne pas coder avant la vague 3.

---

## 8. Source de vente F12

Décision EXECUTION_V2 § 3 (remplace la version du brief).

- La source est déclarée dans le lien par le paramètre `s` : `wa` (WhatsApp), `qr` (QR code), `marche` (Marché). **Absence de paramètre = direct.**
- **Pas de source « partenaire »** pour les commandes. Un lien personnel de partenaire n'ajoute aucun paramètre de source.
- Comptages et totaux seulement. Aucune donnée personnelle de cliente. Aucun traceur externe.
- Lecture : bilan vendeuse, section « Sources de vente » (fonction Business, vague 1).

---

## 9. « Questions de la vente » (remplace F11, spécification seulement)

F11 (assistant de conversation) est **écartée**. Elle est remplacée par :

- des questions publiques sur une vente, une fois répondues, visibles de toutes les clientes ;
- des réponses en texte ou en audio **préenregistré** par la vendeuse ;
- un interrupteur actif ou en pause, par vente ;
- **aucune escalade vers l'administration** ;
- aucune réponse générée par une IA externe.

**Aucun code avant décision du fondateur.** Cette section n'est qu'une spécification.

---

## 10. Niveaux de confiance et signalement

### 10.1 Niveaux

| Niveau | Nom | Condition |
|---|---|---|
| 0 | Inscrite | Compte créé. |
| 1 | Vérifiée | Contact de l'équipe depuis le numéro inscrit **et** première commande livrée et payée. |
| 2 | Fiable | Nombre de commandes livrées sans litige. Seuil à calibrer (§ 12). |

- Toutes les boutiques **existantes** passent au niveau 1 : migration `AddField` avec défaut 1, puis `AlterField` avec défaut 0 pour les nouvelles. **Sans `RunPython`.**
- La règle de listage sur le Marché ne s'applique que si le drapeau `MARKET_REQUIRE_VERIFIED` est actif. **Défaut : faux.** Aucune boutique n'est retirée du Marché à la mise en production.

### 10.2 Signalement par une cliente

- Une cliente peut signaler une boutique (motif court, pas de texte libre obligatoire).
- Le signalement va à l'administration uniquement. Il n'est visible d'aucune autre cliente ni de la vendeuse.
- Le signalement ne suspend rien par lui-même.

### 10.3 Suspension

- L'administration peut **suspendre ou réactiver** une vendeuse. Chaque action est inscrite au journal d'audit (`AuditLog`).
- Une boutique suspendue **disparaît du Marché**.
- Aucune suspension automatique.

---

## 11. Avertissement sur le paiement

Décision EXECUTION_V2 § 3 : **le paiement se fait hors HayaFlash.** Aucun prépaiement n'est géré par la plateforme. Un prépaiement éventuel est une pratique du vendeur, pas une fonction contrôlée.

Textes à afficher, sans modification des CGU :

**Page de vente, formulaire de commande :**
> **Paie à la livraison, une fois le produit vérifié et conforme.** Si tu choisis de payer avant, c'est sous ta propre responsabilité et en connaissance des risques. HayaFlash ne reçoit aucun paiement et ne garantit pas les transactions entre toi et la vendeuse.

**Confirmation de commande :**
> Commande enregistrée. Rappel : ne paie qu'à la livraison, après avoir vérifié ton produit. Un problème avec cette boutique ? Signale-la ici.

Les CGU ne sont **pas** modifiées. La formulation d'un passage aux CGU est soumise à l'avocat et consignée dans le journal de la tâche concernée.

---

## 12. Points ouverts

| # | Point | Qui décide |
|---|---|---|
| O1 | Seuil du niveau 2 (« Fiable ») | Fondateur, après calibrage sur les bilans réels |
| O2 | Tarif fondateur Business : **résolu le 22/11/2026** — 20 comptes ou 60 jours (le premier des deux), prix verrouillé tant que l'abonnement est continu, perdu après plus de 30 jours d'interruption, P3 seulement (§ 6). Le « 8 » du brief concerne les partenaires fondateurs. | — |
| O3 | Relecture juridique de l'avertissement (§ 11) | Avocat |
| O4 | Décision sur « Questions de la vente » (§ 9) | Fondateur |
| O5 | Ouverture de Business (§ 2.3) : **résolu le 22/11/2026** — D6 remplie, 14 jours de production sans incident, accord explicite du fondateur ; liste d'attente = signal seulement. | — |

---

## 13. Tests attendus (à écrire avant le code, EXECUTION_V2 § 1)

- `plan_has_feature` : FREE, MEDIUM, PRO inchangés ; BUSINESS sans accès tant que `is_active = False`.
- Abonné BUSINESS : accès aux fonctions PRO (non-régression du point de vigilance § 4).
- Rétrogradation BUSINESS → PRO : données intactes, fonctions Business en lecture seule.
- Migration de données BUSINESS : réversible, aucune ligne existante modifiée.
- Tarif fondateur : renouvellement au prix verrouillé ; `SellerPriceOverride` non utilisé.
- Niveaux de confiance : migration sans `RunPython`, toutes les boutiques existantes au niveau 1 ; `MARKET_REQUIRE_VERIFIED` faux par défaut, Marché inchangé.
- Suspension : boutique suspendue absente du Marché ; action journalisée.
- Avertissement : présent sur la page de vente, le formulaire et la confirmation.
