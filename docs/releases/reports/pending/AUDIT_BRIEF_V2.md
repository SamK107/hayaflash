# Audit de l'existant — Brief de gouvernance v2

Date : 2026-11-20 · Mode : **lecture seule** (aucune modification, aucune migration, aucun commit, aucun test lancé).
Référence : état réel du répertoire de travail (`git status` du 20/11 : branche `feat/seed-demo-distrib-v2`, fichiers modifiés et non suivis inclus).
Brief audité : `docs/HayaFlash — Brief de gouvernance v2.md` (le chemin `docs/BRIEF_GOUVERNANCE_V2.md` demandé n'existe pas ; c'est ce fichier qui a été lu).

Légende : **Présent** = implémenté et trouvé dans le code · **Partiel** = une partie seulement · **Absent** = non trouvé (« non trouvé » = recherche faite, rien) · **Non vérifié** = hors de ce que j'ai pu lire.

---

## 0. Constats principaux

1. **Le programme créateurs (§6) est déjà largement implémenté** dans une app `partners/` **commitée** (migrations 0001 à 0003, plus de 40 tests). Le brief le traite comme à créer (`Partner`, `Referral`, `CommissionEntry`, `PartnerPayout`, `AuditLog`). Créer ces modèles en parallèle serait un doublon direct.
2. **La base de commission diverge** : le code et le document de règles `docs/releases/reports/partenaires_regles.md` calculent sur le **net** (montant − 1 % Orange). Le brief (D1) recommande le **brut**. Les conditions acceptées par les partenaires sont figées (texte immuable), donc le choix a des conséquences juridiques.
3. **Le plan BUSINESS n'existe pas** : `Plan` n'a que FREE / MEDIUM / PRO (`subscriptions/models.py:9-12`). Aucune mention de « Business » dans `ROADMAP_V2_V3.md`, `GOVERNANCE_EVOLUTIONS_V1_1.md`, `docs/evolutions/` ni `SPEC_04` (seul le brief en parle).
4. **Écart avec la règle « première attribution immuable »** (§6.2 du brief) : le cookie `hf_ref` est **réécrit à chaque clic** sur un lien (`partners/views.py`, `referral_link_view`). Si un vendeur clique deux liens avant de s'inscrire, c'est le **dernier** qui gagne. La recette C2 du brief (« un vendeur qui clique deux liens garde le premier ») échoue en l'état. Une fois le rattachement créé, il est bien immuable (`Referral`, `models.py:234`).
5. **Remboursements non traités** : aucun statut « remboursé » dans `subscriptions` (`PaymentStatus`, `models.py:104-110`), aucun code de reprise. Le document `partenaires_regles.md` indique « une commission annulée après versement exige une régularisation manuelle ». Le brief (§6.3) prévoit une reprise compensée automatiquement.
6. **Bilans** : le calcul existe (`analytics/services/monthly_report.py`, `shop_bilan`) mais **uniquement côté admin** (`/platform-admin/boutiques/<pk>/bilan/`). Aucune vue ni template vendeuse. Pas d'export PDF/CSV de bilan.
7. **Studio photo : code absent**, spec présente (`docs/specs/SPEC_02_STUDIO_PHOTO.md`). Pas d'app `studio`, pas dans `INSTALLED_APPS` (`config/settings/base.py`).
8. **Stock** : `Product.stock_available` existe, `adjust_stock` existe, la contrainte CHECK est **non commitée** (`products/migrations/0011_stock_non_negatif.py`, untracked). La page « Mon stock » et l'alerte de rupture sont **non trouvées**.
9. **Prix promo barré (SPEC_01) : implémenté** (`apply_sale_price`, interrupteur `HAYAFLASH_PROMO_DISPLAY`, défaut vrai). Non re-testé ici.
10. **D2 (plafond Distrib 1 500 FCFA)** : **par commande** selon `SPEC_03` §15.7 ; le code l'applique par ligne de suivi (un article importé), ce qui équivaut à « par commande » tant qu'une commande ne porte qu'un produit (voir §6).

---

## 1. Éléments marqués [À VÉRIFIER] dans le brief

| Élément du brief | Statut | Preuve (fichier:ligne ou « non trouvé ») |
|---|---|---|
| Configuration de plan éditable (§3) | **Présent** (sans BUSINESS) | `subscriptions/models.py:267` (`PlanConfig`) ; `subscriptions/services/plans.py:27-29` (défauts) ; `plans.py:148-216` (lecture, prix spécial, `plan_offers`) ; admin « Configuration des plans » |
| Prix spécial temporaire par vendeur (tests à 100 FCFA) | **Présent** | `subscriptions/models.py:378` (`SellerPriceOverride`, 100 ≤ prix ≤ officiel, 30 j max, `max_uses`) ; `plans.py:199` (`get_price_quote`) ; `subscriptions/services/payment.py:130` |
| Marquage des paiements de test | **Présent** | `subscriptions/services/platform_reporting.py` (`revenue_payments()` exclut `reason=test`) ; `partners/services/commissions.py` (motif `test_payment`, pas de commission) |
| Page boutique publique `/s/<slug>/` | **Présent** | `analytics/urls.py:6` (`public_seller`) ; `accounts/models.py` (`SellerProfile.public_slug`, OneToOne `user`) |
| Lien boutique | **Présent** | Lien `/s/<slug>/` + bouton WhatsApp trackable (`ShareEvent`) |
| QR de la boutique | **Absent** | Seuls existent : QR d'une **vente** (`analytics/urls.py:12`, `/f/<slug>/qrcode/`), QR du **lien partenaire** (`partners/services/qr.py`), QR de **vérification** (`partners/services/verification.py`) |
| Code de parrainage / suivi de lien | **Présent** (programme partenaires) | `partners/urls.py:7` (`/r/<code>/`) ; `partners/views.py` (`referral_link_view`, cookie `hf_ref`) ; `partners/services/attribution.py` |
| Page admin de bilans | **Présent** | `core/urls.py:28-30` ; `core/views.py` (`platform_admin_shop_report`, ~l.495-530) ; `analytics/services/monthly_report.py` (`shop_month_report` l.200, `shop_bilan` l.612) |
| Studio photo | **Absent** (code) | « non trouvé » : aucune app `studio`, aucun template, aucun `studio` dans les `.py`. Spec : `docs/specs/SPEC_02_STUDIO_PHOTO.md` |
| Gestion de stock | **Partiel** | `products/models.py:41` (`stock_available`), `products/models.py:67-76` (CHECK, non commitée), `products/services/crud.py:122` (`adjust_stock`), `StockMovement` (`products/models.py` ~l.181) |
| Prix promo barré | **Présent** | `products/services/crud.py:150` (`promo_discount_percent`), `:160` (`apply_sale_price`) ; `config/settings/base.py:132` ; `docs/specs/SPEC_01_PRIX_BARRE.md` |
| Plan Business / `plan_has_feature` (§3) | **Absent** | « non trouvé » : pas de `plan_has_feature` ; contrôles dispersés (`has_stats`, `is_pro`, `effective_plan` monthly_report.py:130) |

---

## 2. Vérification des 10 fonctions du § 4

| # | Fonction | Statut | Détail |
|---|---|---|---|
| 1 | Bilan mensuel complet côté vendeuse | **Partiel** | Calcul complet côté admin (`monthly_report.py` : ventes, CA, produits en % des recettes, comparaison, tendance 3 mois, signaux). **Pas de vue vendeuse, pas d'export PDF/CSV** (« non trouvé »). |
| 2 | Ligne « HayaFlash t'a fait gérer X FCFA » | **Absent** | « non trouvé ». Le brief ne définit pas la source : `SubscriptionPayment` (ce que la vendeuse paie) ou montant des commandes gérées (ce que HayaFlash « gère ») ? |
| 3 | Studio photo à quota | **Absent** | Spec seulement. Quota par plan non chiffré dans le brief. |
| 4 | Stock maître + alerte de rupture | **Partiel** | Stock par produit et ajustement existent. « Mon stock » absent (roadmap §1 : étapes A/B/C non faites). Alerte rupture : « non trouvé » dans les templates. |
| 5 | Fichier clientes + fiabilité + lien wa.me | **Partiel** | Blocage après 3 non-honorées sur 30 jours : `orders/services/unhonored.py:26-27` (**présent**). Historique par cliente : `monthly_report.py` compte `customers` seulement. Fichier clientes : absent. Lien `wa.me` : `monthly_report.py:138` (`wa_link`), admin uniquement. |
| 6 | Ventes privées | **Absent** | « non trouvé ». |
| 7 | Boutique personnalisée (bannière, logo, badge) | **Partiel** | Page et lien existent. `SellerProfile` n'a ni bannière, ni logo, ni badge (champs : `avatar`, `bio`, `delivery_zones`, `category`, `is_active`). |
| 8 | Équipe sur la boutique (1-2 accès secondaires) | **Absent** | Un compte = une boutique (`SellerProfile.user` OneToOne). Décision de limite par boutique : `SPEC_04` §7.3 (par `SellerProfile`). Aucun modèle de membre. |
| 9 | Mise en avant sur le Marché | **Absent** | `analytics/services/market.py` trie par `end_time` (l.61, l.71) ; pas de classement par catégorie, pas de badge, pas de coup de pouce. |
| 10 | Saisie assistée prioritaire, 1 séance/mois | **Partiel** | L'outil existe : app `assist`, `/platform-admin/saisie/<seller_id>/` (CLAUDE.md point 19). **La limite d'une séance par mois : non trouvée** (aucun compteur). |

---

## 3. Conflits entre le brief et l'existant

| # | Sujet | Brief | Existant | Source |
|---|---|---|---|---|
| C1 | Base de la commission | Brut (D1) : 2 000 → 600 | **Net** : floor(2 000 × 99 %) = 1 980 → 594 | `partners/services/commissions.py` (`compute_amounts`), `config/settings/base.py:443` (`ORANGE_RETENTION_PERCENT = 1`), `partenaires_regles.md:94-98` |
| C2 | Premier lien | « Première attribution gagnante, immuable » (§6.2) | Cookie réécrit à chaque clic ; rattachement à l'inscription = dernier cookie | `partners/views.py` (`referral_link_view`, `set_cookie`) ; `partners/services/attribution.py` (`attribute_registration`) |
| C3 | Début des 12 mois (D3) | « premier paiement encaissé » | « premier paiement encaissé **après acceptation des conditions** » (un paiement antérieur n'est jamais rattrapé) | `partenaires_regles.md:106-109`, `commissions.py:_terms_reason` |
| C4 | Statuts de commission | `due → payable → paid` (+ `reversed`) | `pending → validated → paid` (+ `cancelled`, sans `payable` ni `reversed`) | `partners/models.py:249-253` |
| C5 | Remboursement | Reprise compensée sur versements suivants, tracée | Annulation uniquement avant versement ; après versement, régularisation manuelle | `commissions.py:cancel_entry` ; `partenaires_regles.md:169` |
| C6 | Règlements | Annulation par écriture inverse, saisie non modifiable | `mark_paid` une seule fois (`payouts.py`), pas d'écriture inverse, pas d'entité « reversal » | `partners/services/payouts.py:mark_paid` |
| C7 | Journal `AuditLog` immuable (§6.4) | Immuable | `core/models.py:8` : aucune surcharge `save`/`delete` trouvée (immutabilité non garantie au modèle) | `core/models.py` |
| C8 | Vocabulaire | Brief : « parrainage », « créateur » | Périmètre partenaires : « parrain », « parrainage », « filleul », « recommand* » **interdits** (test `partners/tests_documents.py::VocabularyTests`) | `partenaires_regles.md:5-8` |
| C9 | Offre de lancement (§1) | Pro gratuit 1 mois, sans parler de partenariat | Accès Pro 30 j **lié à l'essai d'un partenaire** (« essai partenaire ») ; pas d'offre générique « 1 mois » | `partners/services/trial.py` (`grant_pro_trial`) |
| C10 | Anti-fraude (§6.6) | Alerte : même numéro partenaire + vendeur ; plusieurs comptes du même créateur en 24 h | Auto-recommandation **bloquée** (`attribution.py`, comparaison de téléphone) ; alerte : **plus de 3 inscriptions même IP en 7 jours** (`FLAG_*`) | `partners/services/attribution.py` |
| C11 | Plafond Distrib | D2 à trancher | `SPEC_03` §15.7 : **par commande** ; §5.5 : formule sans unité ; code : par ligne de suivi | `distrib/services/commission.py:1-12` |
| C12 | Feuille de route tarifaire | Grille fixe : Pro 5 000, Business 10 000 | `ROADMAP_V2_V3.md` § « Tarification » (04/11) : pistes Medium 3 000, Pro 7 500-10 000 « plus tard » ; « aucun changement de prix en production » | `docs/ROADMAP_V2_V3.md:107-121` |
| C13 | Stock | Brief #4 « stock maître » (21 oct.) | Roadmap rang 4 « Stock étapes A (Mon stock) et B » ; étape C « blocage strict par vente » ; `FlashSaleProduct` garde le stock sur `Product` **délibérément** | `ROADMAP_V2_V3.md:44-56` ; `products/models.py:225-240` |
| C14 | Documentation d'état | `partenaires_regles.md` : « travail non commité » (branche `feat/programme-partenaires`) | `partners` est commité (#71 à #76 dans l'historique) | `git log -- partners` |
| C15 | CLAUDE.md | — | Liste des apps sans `partners/`, `distrib/`, `studio/` (distrib seulement au point 21) | `CLAUDE.md` § Structure des apps |

---

## 4. Doublons à éviter

| Ce que le brief propose | Existe déjà | Conséquence |
|---|---|---|
| Modèles `Partner`, `Referral`, `CommissionEntry`, `PartnerPayout`, `AuditLog` (§6.4) | `partners/models.py` (Partner:55, Referral:203, CommissionEntry:293, Payout:261) ; journal `core/models.py` `AuditLog` | Ne pas recréer ; SPEC_06 doit **étendre** `partners`. |
| Admin « à régler », relevé, export CSV (§6.7) | `partners/services/payouts.py` (`build_payout`, `statement_text`, exports CSV neutralisés) ; `partners/admin_views.py` | Partiel : vérifier l'écran exact avant de le refaire. |
| Validation mensuelle + versement ≥ 2 000 FCFA | `payouts.py` (`validate_month`, `PARTNER_MIN_PAYOUT_FCFA`) | Déjà la règle du brief. |
| Accès Pro offert pendant l'essai | `partners/services/trial.py` | Réutilisable pour une offre de lancement, mais avec une raison distincte. |
| Blocage des clientes après 3 non-honorées | `orders/services/unhonored.py` | Ne pas en refaire un. |
| Assistance à la saisie (#10) | app `assist` | Ajouter seulement le compteur mensuel. |
| Bilan admin (#1) | `analytics/services/monthly_report.py` | Réutiliser `shop_bilan` côté vendeuse ; ne pas écrire un second calcul. |
| Mécanisme de prix / quota | `PlanConfig` + `plans.py` | Ajouter BUSINESS à cette source, pas de constantes. |
| Plusieurs documents de gouvernance | `docs/GOVERNANCE_EVOLUTIONS_V1_1.md` et `docs/evolutions/GOVERNANCE_EVOLUTIONS.md` ; `docs/specs/SPEC_02_STUDIO_PHOTO.md` et `docs/evolutions/SPEC_STUDIO.md` ; `docs/specs/SPEC_03_DISTRIB_V1.md` et `docs/evolutions/SPEC_DISTRIB.md` | Doublons à réconcilier ; choisir une source (`docs/specs/` pour les specs). |
| Stock (#4) | Roadmap étapes A/B/C | Un seul plan de stock. |
| Copies anciennes dans l'arbre | `.claude/worktrees/amazing-lederberg-3944d2/` et `Claude outputs/sauvegarde-avant-tri-C/` contiennent des copies de `subscriptions/models.py`, `accounts/admin.py`, etc. | Risque de lecture ou de modification au mauvais endroit. À exclure des recherches. |

---

## 5. Points du brief à corriger ou préciser

1. **§1 / §3 / §4 : nom du plan et tarifs** : « PRO illimité 5 000 » est correct ; ajouter que la roadmap (C12) prévoit des hausses non décidées.
2. **D1** : le brief dit « brut ». Le code et les conditions signées disent « net ». Préciser si le changement vaut pour les nouveaux partenaires (nouvelle version des conditions, `doc_version`) ou pour tous.
3. **D3** : préciser « premier paiement encaissé **après l'acceptation** des conditions ».
4. **D5 (remise annuelle)** : `Subscription` n'a pas de champ de durée ; la durée vient de `PlanConfig.duration_days` (défaut 31) et de `expires_at`. Il faut dire où vit le plan annuel (nouveau prix dans `PlanConfig`, ou durée par abonnement).
5. **§5.5 « tarif fondateur verrouillé »** : `SellerPriceOverride` est limité à **30 jours** (`SPECIAL_PRICE_MAX_DAYS`) et ne convient pas à un prix verrouillé à vie. Il faut un mécanisme dédié.
6. **§5.3 « essai Business 14 jours »** : l'essai existant est de 30 jours et lié aux partenaires. Un essai de 14 jours est nouveau.
7. **§4 #2** : définir la source du chiffre « géré » (voir tableau §2).
8. **§4 #9** : « coup de pouce borné » : aucun classement par catégorie n'existe à modifier ; à décrire comme nouveau.
9. **§4 #10** : la limite mensuelle est à créer (compteur).
10. **§6.3 « remboursement » et « plan annuel »** : décrire la reprise (automatique ou manuelle) en cohérence avec C5.
11. **§6.5** : « annulation par écriture inverse » : l'entité n'existe pas (C6).
12. **§6.6** : aligner le seuil d'alerte sur celui du code (C10).
13. **§6.2** : la règle « première attribution immuable » n'est pas respectée au niveau du cookie (C2) ; le brief doit soit l'accepter, soit demander le correctif.
14. **§8 Phasage P0** : « prix spécial par vendeur, marquage des tests » sont **déjà faits**. P0 se réduit à l'ajout de BUSINESS et au mécanisme de prix verrouillé.
15. **§9** : `docs/ROADMAP_V2_V3.md` est déjà modifié non commité ; les références aux SPEC doivent suivre `docs/specs/`.
16. **Vocabulaire** : les textes publics ne doivent pas utiliser « parrainage » pour le programme partenaires (C8).

---

## 6. Risques de migration

- **Numérotation** : `products/migrations/0011_stock_non_negatif.py` est **non suivie** (dépend de `0010_alter_product_description_audio_and_more`, présente). Elle échoue explicitement s'il existe un stock négatif (`RuntimeError`) : requête de contrôle dans son docstring. Elle doit être commitée et jouée en staging puis prod ; la prochaine migration `products` sera la 0012.
- **Énumération des plans** : `Plan.choices` sert de `choices` à plusieurs champs : `Subscription.plan`, `SubscriptionPayment.plan`, `PlanConfig.plan`, `SellerPriceOverride.plan` (limité à MEDIUM/PRO, `models.py:394`). Ajouter BUSINESS = migration d'état (choices) sur chacun, plus une **migration de données séparée** pour la ligne `PlanConfig` (convention CLAUDE.md).
- **Risque sur `is_pro`** : `Subscription.is_pro` teste `plan == PRO` exactement (`subscriptions/models.py:60-61`). Un abonné BUSINESS perdrait les fonctions PRO (stats avancées) tant que `is_pro` et `has_advanced_stats` ne couvrent pas BUSINESS. `effective_plan` (monthly_report.py:130) et `limits.py` ont le même problème potentiel ; `limits.py` non relu en détail.
- **Abonnés PRO existants** : aucune migration ne doit toucher la valeur `pro`. Le montant de chaque paiement est figé (`SubscriptionPayment.amount`), donc un changement de prix ne rétroagit pas. En revanche, un renouvellement suit le prix courant de `PlanConfig`.
- **Partenaires** : `Partner.commission_percent` est figé à la création ; `CommissionEntry` stocke `gross`/`net`/`percent` : un plan BUSINESS n'altère pas l'historique.
- **Rétrogradation sans perte** (§3) : repose sur le fail-closed existant (`Subscription.is_free` renvoie FREE si expiré). Pour un passage BUSINESS → PRO sans expiration, il faut le tester.
- **Stock** : CHECK sur `stock_available` et sur `ProductVariant.stock` ; la migration échoue si des lignes sont négatives. À vérifier en production avant déploiement.
- **Tests** : non lancés (lecture seule). `tests_stock_contrainte.py` et `orders/tests_fenetre_et_idempotence_api.py` sont non suivis.

---

## 7. Décisions à trancher (avec recommandation)

| # | Décision | Recommandation |
|---|---|---|
| D1 | Base de commission : brut ou net | **Net, comme le code**, pour les partenaires déjà acceptés (acceptations immuables). Si le brut est voulu, le faire par **nouvelle version des conditions** (`doc_version`) pour les nouveaux partenaires uniquement. |
| D2 | Plafond Distrib 1 500 FCFA | **Par commande**, comme `SPEC_03` §15.7. Corriger la formule de §5.5 pour lever l'ambiguïté. |
| D3 | Début des 12 mois | **Premier paiement encaissé après acceptation** (code). Préciser le texte du brief. |
| D4 | Nom du plan 10 000 FCFA | **BUSINESS** (PRO est utilisé dans plus de 40 endroits). |
| D5 | Remise annuelle | **Reporter en P3**, avec prix annuel dans `PlanConfig`. Pas de champ de durée sur `Subscription` sans besoin prouvé. |
| D6 | Ouverture de Business | **Garder** la règle des 3 fonctions livrées. |
| N1 | Premier lien (C2) | **Premier cookie gagnant** : ne pas réécrire `hf_ref` s'il existe déjà. Petit correctif de code, à traiter dans une PR à part avec test. |
| N2 | Remboursement (C5) | **Garder la régularisation manuelle** au début ; documenter le processus. La reprise automatique est une évolution ultérieure. |
| N3 | Offre de lancement Pro 1 mois | **Réutiliser `grant_pro_trial`** avec une raison distincte, ou créer une offre générique ; à trancher, car `trial.py` est lié aux partenaires. |
| N4 | Stock (C13) | **Un seul plan** : fusionner brief #4 et roadmap étapes A/B ; étape C à part. |
| N5 | Tarif fondateur verrouillé | **Champ dédié** sur l'abonnement (pas `SellerPriceOverride`, limité à 30 jours). |
| N6 | Vocabulaire (C8) | Public : « lien personnel », « vendeur inscrit via le lien ». Interne (brief) : le terme peut rester. |
| N7 | Roadmap tarifaire (C12) | Réaligner `ROADMAP_V2_V3.md` sur la décision du brief une fois tranchée. |
| N8 | Doublons documentaires | Désigner `docs/specs/` comme source ; supprimer ou marquer comme obsolètes les copies `docs/evolutions/`. Exclure les copies de `.claude/worktrees/` et `Claude outputs/`. |
| N9 | Commit de la migration 0011 | **Commiter après vérification du stock négatif en staging et prod**, et avant toute autre migration `products`. |

---

## 8. Non trouvé / non vérifié

- **Non trouvé** : Studio photo (code), « Mon stock », alerte de rupture, `plan_has_feature`, plan BUSINESS, QR de boutique, bannière/logo/badge de boutique, mise en avant du Marché, limite d'une séance d'assistance par mois, mécanisme de remboursement, export PDF/CSV de bilan vendeuse, ligne « HayaFlash t'a fait gérer X FCFA ».
- **Non vérifié** : `subscriptions/services/limits.py` (fail-closed) relu seulement par les notes de CLAUDE.md ; `distrib/` hors périmètre sauf la règle de plafond ; `campagne/` (non suivi) hors périmètre ; comportement réel en production ; résultat des tests (non lancés).
