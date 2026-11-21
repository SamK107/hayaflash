# SPEC_04 — Statuts livraison / paiement, fenêtre de livraison, corrections, notification acheteuse

Statut : **VALIDÉ par le mainteneur le 7 nov. 2026, D3 révisé (confirmation par appel, sans état intermédiaire ni code). Aucune implémentation avant son feu vert explicite.**
Date : 7 novembre 2026. Périmètre : app `orders`, app `delivery`, et points de contact avec `distrib`.

---

## 0. Périmètre et hors périmètre

**Dans le périmètre**
- Séparer « livré » et « payé », qui sont aujourd'hui fusionnés dans le statut `OrderStatus.DELIVERED` (« Livré et payé »).
- Qui pose « livré » et « payé » selon le cas (revendeur affilié, grossiste, vendeuse qui livre elle-même).
- Prépaiement possible, transitions autorisées et interdites.
- Correction d'un statut posé par erreur.
- Fenêtre de livraison fixée à la confirmation, modifiable, et notification de l'acheteuse en cas de changement.

**Hors périmètre (décidé le 7 nov. : aucune implémentation)**
- Créneaux de lives fixes. Les lives sont libres. Seules contraintes : max 3 ventes/jour par boutique et pas de chevauchement pour une même boutique (déjà implémentées, voir §1).
- Carte livreur, parcours généré, optimisation d'itinéraire, suivi GPS (V2/V3).
- SMS automatiques (désactivés au lancement, décision du 18 oct.).

---

## 1. Existant vérifié dans le code

| Élément | Fait vérifié | Fichier |
|---|---|---|
| Statuts commande | `pending`, `confirmed`, `out_for_delivery`, `delivered` (« Livré et payé »), `cancelled` | `orders/models.py` |
| Statuts livraison | `pending`, `assigned`, `in_transit`, `delivered`, `failed` | `delivery/models.py` |
| Encaissement | `Delivery.cod_collected` (booléen), `cod_collected_at`, `cod_confirmed_by`, posé **à** `mark_delivered` | `delivery/models.py`, `delivery/services/delivery.py` |
| Actions vendeuse | `confirm`, `cancel`, `start_delivery`, `mark_delivered`, `mark_failed` (`advance_delivery`) | `delivery/services/delivery.py` |
| Annulation vendeuse | Seulement si commande `pending`/`confirmed` **et** livraison `pending`/`assigned` | idem |
| Échec livraison | Crée une `UnhonoredOrder` (blocage numéro après 3 échecs / 30 j) | `orders/services/unhonored.py` |
| Fenêtre de livraison | **Inexistante** (aucun champ, aucun service) | — |
| Page de suivi acheteuse | **Non trouvée** pour les commandes directes. Seul existe le reçu Distrib, accessible par jeton (`receipt_token`) | `distrib/services/receipts.py` |
| Notifications | `sms_enabled()` existe ; WhatsApp en V1 = journalisation seulement (pas d'envoi) ; lien WhatsApp manuel via `build_whatsapp_share_url` | `notifications/services/` |
| Module Distrib | Ligne de suivi `DistribSettlement` avec ses propres statuts (`ordered`, `in_delivery`, `delivered_by_shop`, `paid_confirmed`, `cancelled`, `not_delivered`), mappée depuis `OrderStatus` (`STATUS_MAP`). **Règle explicite : ce module lit `orders` et n'écrit jamais sur `Order`.** Présomption de paiement après `auto_confirm_hours` (défaut 72 h). Correction par l'équipe seulement, motivée (`DistribCorrection`). | `distrib/services/settlement.py`, `distrib/models.py` |
| Compte vendeur | `SellerProfile.user` est un **OneToOne** : un compte = une boutique | `accounts/models.py` |
| « Livré, à encaisser » | Libellé déjà utilisé dans le tableau de bord vendeuse (état `delivered_unpaid`) | `delivery/services/seller_dashboard.py` |

**Conséquence :** le statut `delivered` porte aujourd'hui deux informations (livré et payé). C'est la cause principale du problème. Corriger cela par un simple renommage ne suffit pas.

---

## 2. Modèle cible : deux axes indépendants

On ne remplace **pas** `OrderStatus` ni `Delivery.Status`. On ajoute deux axes, pour limiter le risque sur le code existant (tableau de bord, comptages, `UnhonoredOrder`, tests).

### 2.1 Axe livraison (existant, inchangé dans ses valeurs)
`Delivery.Status` : `pending` → `assigned` → `in_transit` → `delivered` | `failed`.
`delivered` signifie **livré**, et seulement livré.

### 2.2 Axe paiement (nouveau, sur `Delivery`)
| Champ | Type | Valeurs / rôle |
|---|---|---|
| `payment_status` | CharField | `unpaid` (défaut), `paid` (confirmé par `payment_receiver`) |
| `payment_timing` | CharField | `prepaid` (avant livraison), `on_delivery` (à la livraison) — choisi par le revendeur à la confirmation |
| `paid_at` | DateTime, nullable | Date de réception confirmée |
| `paid_by` | FK user, nullable | Personne qui a confirmé la réception (vendeuse, grossiste, ou revendeur selon le cas) |
| `payment_confirmed_by_phone` | Booléen | `true` si la confirmation a suivi un appel entre le livreur et le bénéficiaire avant la remise (indication pour l'audit) |
| `payment_receiver` | CharField | `seller` (vendeuse non affiliée ou boutique), `wholesaler` (argent sur le compte du grossiste) |

**Compatibilité :** `cod_collected` reste en place et est **mis à jour en même temps** que `payment_status` (miroir) tant que les vues existantes en dépendent. Migration : pour les livraisons `delivered` avec `cod_collected=True`, initialiser `payment_status=paid` (sans toucher aux autres lignes).

### 2.3 Ce qui n'est PAS un champ
- « Livré et payé » n'est plus un statut. C'est l'affichage combiné de deux axes (`livré` + `payé`), généré par le service.
- `OrderStatus.DELIVERED` garde sa valeur technique (« commande livrée ») pour ne rien casser. Son libellé devient « Livré ». (Changement de libellé uniquement.)

### 2.4 Champ de mode de livraison (nouveau)
| Champ | Valeurs | Rôle |
|---|---|---|
| `delivery_mode` | `seller` (le revendeur ou la vendeuse livre) / `wholesaler` (le grossiste livre) | Fixé **à la confirmation**. Détermine qui pose « livré ». |

---

## 3. (a) Qui pose « livré » et « payé »

### 3.1 Tableau de décision

| Cas | `delivery_mode` | Qui pose **livré** | Qui pose **payé** | Précision |
|---|---|---|---|---|
| Vendeuse non affiliée, elle livre elle-même | `seller` | Vendeuse | Vendeuse | Une seule personne fait les deux |
| Vendeuse non affiliée, livraison par un tiers | `seller` | Vendeuse | Vendeuse | Même règle : elle reste responsable de sa commande |
| Revendeur affilié, **livraison par son livreur** | `seller` | **Revendeur**, sur confirmation de son livreur | **Grossiste** (il reçoit l'argent) | Le revendeur ne peut jamais poser « payé » |
| Revendeur affilié, **livraison par le grossiste** | `wholesaler` | **Grossiste** | **Grossiste** | Le revendeur voit les statuts, ne les pose pas |

### 3.2 Règles
- **R-A1.** « Livré » ne peut être posé que par la personne désignée par `delivery_mode` (voir §3.1). Aucune autre personne, y compris l'équipe HayaFlash, ne le pose à sa place (l'équipe corrige seulement via §6).
- **R-A2.** « Payé » ne peut être posé que par la personne qui reçoit l'argent (`payment_receiver`). Le revendeur affilié ne peut **jamais** poser « payé ».
- **R-A3.** La confirmation du livreur reste **hors plateforme** (téléphone ou WhatsApp, comme aujourd'hui). Le revendeur clique « Livré » et peut saisir le nom du livreur, qui est repris dans la trace. Le livreur n'a pas de compte dans cette version.
- **R-A4.** « Livré » et « payé » peuvent être posés en même temps (vendeuse non affiliée, paiement reçu à la livraison) ou séparément.

### 3.3 Points à valider (voir §9)
- Le grossiste écrit aujourd'hui dans `DistribSettlement` **sans écrire sur `Order`** (règle R1 de `distrib`). Pour que ses actions apparaissent chez le revendeur et dans la commande, il faut une écriture sur `Delivery`. C'est une dérogation à cette règle. **Décision D1.**

---

## 4. (b) Transitions autorisées et interdites

### 4.1 Axe livraison (`Delivery.Status`)

| De → vers | Autorisé ? | Remarque |
|---|---|---|
| `pending` → `assigned` | Oui | Livreur désigné |
| `pending`/`assigned` → `in_transit` | Oui | Exige un nom de livreur (existant) |
| `in_transit` → `delivered` | Oui | Par la personne `delivery_mode` |
| `pending`/`assigned` → `delivered` (remise directe) | Oui, **seulement si `delivery_mode=seller`** | Remise en main propre sans étape « en livraison » |
| `in_transit` → `failed` | Oui | Crée une `UnhonoredOrder` (existant) |
| `failed` → `in_transit` | Oui | Nouvelle tentative, avec motif |
| `failed` → `delivered` | **Non** | Il faut repasser par `in_transit` |
| `delivered` → autre statut | **Non** | Seule la correction (§6) permet de revenir en arrière |
| `pending` → `delivered` (hors remise directe) | **Non** | |
| toute transition si la commande est `cancelled` | **Non** | |

### 4.2 Axe paiement (`payment_status`)

| De → vers | Autorisé ? | Conditions |
|---|---|---|
| `unpaid` → `paid` | Oui | Commande `confirmed`, `out_for_delivery` ou `delivered` ; par `payment_receiver` uniquement ; pour `on_delivery`, la remise suit (§5) |
| `unpaid` → `paid` avant confirmation (`pending`) | **Non** | Pas d'argent pris sur une commande non confirmée |
| `paid` → `unpaid` | **Non** | Seulement par correction (§6) |
| `paid` sur commande `cancelled` | **Non** autorisé à l'annulation | Voir R-T3 |

### 4.3 Axe commande (`OrderStatus`, inchangé dans ses valeurs)
`pending` → `confirmed` → `out_for_delivery` → `delivered`, et `pending`/`confirmed` → `cancelled`. Aucune transition depuis `delivered` ou `cancelled`.

### 4.4 Règles croisées
- **R-T1.** `delivered` (livraison) **n'exige pas** `paid`. Une livraison livrée non payée reste valide : c'est l'état « Livré, à encaisser ».
- **R-T2.** `paid` n'exige pas `delivered`, sauf dans le cas `on_delivery` où le paiement est pris à la livraison. Une commande `prepaid` peut être payée avant toute livraison.
- **R-T3.** **Annuler une commande payée est interdit** pour la vendeuse. Le revendeur ou la vendeuse doit d'abord rembourser ou prévenir l'équipe. La commande passe alors en `conflict` (voir §6.4) et l'équipe tranche. Cela reprend la logique `conflict_flag` de `distrib`.
- **R-T4.** Une commande `cancelled` ne peut plus recevoir de fenêtre, de statut de livraison ni de paiement.

---

## 5. Prépaiement

> **Décision EXECUTION_V2 § 3 (21/11/2026) : le paiement se fait hors HayaFlash.** La plateforme ne gère, ne contrôle et ne reçoit aucun prépaiement. Le prépaiement décrit ci-dessous est une **pratique du vendeur**, hors de la plateforme : aucune de ses étapes n'est une fonction contrôlée par HayaFlash, et le « payé » n'a pas de preuve automatique côté plateforme. Les textes destinés aux clientes doivent présenter le paiement à la livraison comme la règle, et le prépaiement comme un risque pris par la cliente (SPEC_05 § 11).

- **Option par vente**, choisie par le revendeur à la confirmation : `prepaid` ou `on_delivery`. Une vente peut proposer les deux, mais chaque commande n'a qu'un mode.
- **Prépaiement (validé le 7 nov. 2026)** : la cliente paie avant la livraison sur le compte mobile money du bénéficiaire (`payment_receiver`). Le SMS de l'opérateur arrive au bénéficiaire dès que le paiement est effectif, quel que soit le moment (avant ou à la livraison). Le bénéficiaire marque « payé » depuis son tableau de bord après ce SMS. La plateforme ne reçoit pas de confirmation automatique en V1 : le SMS reste la preuve, et le « payé » reste une action humaine.
- **Paiement à la livraison (D3, validé)** : la cliente paie sur le compte mobile money du bénéficiaire (`payment_receiver`). **Aucun espèces ne passe par le livreur.** Le livreur n'écrit rien et n'utilise aucune application pour cette étape : la vérification se fait par appel téléphonique.
  - **Procédure de remise (R-P1)** :
    1. La cliente vérifie le produit et le valide.
    2. Le livreur appelle le bénéficiaire, avec le montant et le nom de la cliente.
    3. Le bénéficiaire vérifie le SMS de l'opérateur reçu sur son téléphone (SMS systématique, vérifié le 7 nov. 2026).
    4. S'il a bien reçu le montant, il marque « payé » depuis son tableau de bord.
    5. Il dit « c'est bon » au livreur, qui remet le produit.
  - **R-P2.** Pas de « payé » sur le tableau de bord, pas de remise. Si le bénéficiaire ne répond pas, le livreur repart avec le produit.
  - **R-P3.** Seul `payment_receiver` pose « payé ». Le livreur et la cliente ne le posent jamais.
  - **R-P4.** Pas de code de confirmation : un code que le livreur ne peut pas saisir ne protège rien. Une interface livreur en V2 pourra faire cette vérification, sans la rendre obligatoire en V1.
  - **Point à informer aux clientes :** les frais de transfert mobile money sont à leur charge, selon les tarifs de l'opérateur. À mentionner dans le message de confirmation.
- **Montants** : FCFA entiers, jamais de centimes (règle projet).

---

## 6. (c) Correction d'un statut posé par erreur

Trois niveaux, du plus simple au plus contrôlé.

### 6.1 Annulation immédiate par l'auteur
- Pendant **10 minutes** après l'action (valeur à valider, D4), la personne qui a posé le statut peut le défaire (`livré` → `en livraison`, `payé` → `non payé`).
- Refusé si l'état suivant a déjà été utilisé : une ligne rattachée à un versement ou à un relevé Distrib ne peut plus être défaite par l'auteur.
- Trace : `AuditLog` (action `fulfillment.undo`, acteur, ancien et nouvel état) via `core.models.audit`.

### 6.2 Correction par le revendeur après le délai
- Possible seulement si `payment_status=unpaid` et si le grossiste n'a pas confirmé la réception.
- Motif obligatoire (liste fermée : « livreur erroné », « cliente absente », « autre » avec précision).
- Trace : nouvelle ligne `DeliveryCorrection` (ancien, nouveau, motif, auteur, date), et `audit`.

### 6.3 Correction par l'équipe HayaFlash
- Réservée à `is_staff`. Motif obligatoire. Refusée si la ligne fait partie d'un versement (il faut d'abord rouvrir le relevé, comme `staff_correct` dans `distrib`).
- Trace : `DeliveryCorrection` + `audit` (action `fulfillment.staff_correct`).

### 6.4 Commande en conflit
- Déclenchée par : annulation d'une commande payée (R-T3), ou désaccord déclaré entre le revendeur et le grossiste.
- État `conflict_flag=True` sur la livraison. Seule l'équipe la résout (§6.3). Signal enregistré dans l'audit, comme `distrib.signal.cancelled_after_confirmation`.

---

## 7. Fenêtre de livraison

### 7.1 Règles
- **F1.** La fenêtre est fixée **à la confirmation** de la commande (passage `pending` → `confirmed`). Sans fenêtre, la confirmation est refusée (**D5** : à valider, c'est une décision forte).
- **F2.** Début de fenêtre ≥ **fin réelle du live** + délai minimum. Le délai minimum vaut **120 minutes** par défaut (ta consigne du 6 nov.), **réglable par la vendeuse** dans son profil, dans une fourchette 60 à 240 minutes. Pas de constante en dur.
- **F3.** Largeur de la fenêtre : 60 à 180 minutes (valeur par défaut à valider).
- **F4.** Modifiable par le revendeur (ou le grossiste si `delivery_mode=wholesaler`), **au plus 2 fois par commande** (D6). Chaque modification est tracée (ancienne fenêtre, nouvelle fenêtre, auteur, date) et déclenche la notification (§8).
- **F5.** L'heure est affichée à l'acheteuse en heure de Bamako.
- **F6.** Aucune heure « exacte » : la fenêtre est toujours une plage.

### 7.2 Champs ajoutés
Sur `Delivery` : `window_start`, `window_end` (nullable), `window_revision` (entier, 0 à 2), `window_updated_at`, `window_updated_by`.
Sur le profil vendeuse (`SellerProfile`) : `min_delivery_delay_minutes` (défaut 120, borné 60–240).

### 7.3 Limite par boutique ou par vendeur — décision

**Décision proposée : par boutique, c'est-à-dire par `SellerProfile`.**
- Raison 1 : `SellerProfile.user` est un OneToOne. Une boutique a un seul compte, donc « par vendeur » et « par boutique » désignent la même entité aujourd'hui.
- Raison 2 : c'est déjà le comportement implémenté (3 ventes/jour, et chevauchement, comptés sur `FlashSale.owner`).
- Raison 3 : cela évite un deuxième compteur à maintenir.
- **À reconsidérer seulement si** un jour plusieurs comptes peuvent gérer une même boutique. Ce n'est pas prévu.
- Côté grossiste : pas de limite de ce type dans cette spec. Sa capacité de livraison est une décision séparée (hors périmètre).

---

## 8. (d) Notification de l'acheteuse quand la fenêtre change

**Contexte :** pas de SMS automatique au lancement (décision du 18 oct.), WhatsApp automatique non implémenté. Pas de page de suivi pour les commandes directes.

### 8.1 V1 (proposée)
1. **Page de suivi publique par jeton** : `Delivery.tracking_token` (aléatoire, long, comme `receipt_token`). Affiche les deux axes (livraison, paiement), la fenêtre et l'historique des modifications (« mise à jour à 15 h 10 »).
2. **Lien dans le message de confirmation** que la vendeuse envoie déjà par WhatsApp (helper `build_whatsapp_order_message` existant). Le lien de suivi y est ajouté.
3. **Changement de fenêtre** : la page affiche immédiatement la nouvelle plage et la mention de mise à jour. La vendeuse peut renvoyer manuellement le lien via `build_whatsapp_share_url`.
4. **Aucune notification automatique** en V1.

### 8.2 V2 (quand SMS ou WhatsApp seront activés)
- Événement `delivery.window_changed` vers `notifications.send_notification`.
- Nouveau modèle de message, texte FCFA et français, aucune promesse ferme (« la nouvelle plage est … »).
- Respecter `sms_enabled()` et le canal disponible.

### 8.3 Points à retenir
- Ne jamais promettre une heure précise (règle de la gouvernance).
- Le jeton de suivi ne doit pas contenir de donnée personnelle, et la page ne doit pas afficher le téléphone ni l'adresse complète de la cliente.

---

## 9. Décisions à valider avant implémentation

| # | Sujet | Ma recommandation | Impact si refusé |
|---|---|---|---|
| **D1** | Le grossiste peut-il écrire sur `Delivery` alors que `distrib` interdit d'écrire sur `Order` ? | Oui, via un service unique `fulfillment`, appelé par la vue vendeuse et la vue grossiste. `Delivery` devient la source de vérité. `DistribSettlement` reste le grand livre, alimenté par synchro. Il faut mettre à jour la règle R1 de `distrib/README.md`. | Il faut un canal séparé, donc deux sources de vérité. Risque de divergence. |
| **D2** | Un revendeur affilié peut-il poser « livré » seul ? | Oui, quand `delivery_mode=seller`, sur confirmation de son livreur. | Le grossiste doit confirmer chaque livraison, ce qui ralentit le circuit. |
| **D3** | Paiement à la livraison | **Validé et révisé** : la cliente paie toujours sur le compte mobile money du bénéficiaire. Aucun espèces ne passe par le livreur. Remise après « payé » du bénéficiaire, confirmé par appel (§5). Le SMS opérateur est systématique (vérifié). | — |
| **D4** | Durée de l'annulation immédiate | 10 minutes | — |
| **D5** | Fenêtre obligatoire pour confirmer | Oui | Sans fenêtre, la promesse n'existe pas et le risque de fausse promesse revient. |
| **D6** | Nombre maximal de modifications de fenêtre | 2 par commande | Pas de limite = abus possible. |
| **D7** | Limite par boutique | Par `SellerProfile` (voir §7.3) | — |
| **D8** | Libellé « Livré et payé » | Remplacer par « Livré » ; « payé » affiché séparément | Changement visible pour les vendeuses ; prévenir les pilotes. |

---

## 10. Tests attendus (à écrire avant le code)

- Tableau de transitions : chaque ligne autorisée passe, chaque ligne interdite est refusée avec un message en français.
- Qui pose quoi : pour chaque cas du §3.1, un acteur autorisé passe et les autres sont refusés (dont le revendeur qui tente « payé »).
- Prépaiement : `paid` refusé avant confirmation ; `paid` puis `delivered` ; `delivered` puis `paid`.
- Annulation d'une commande payée : refusée pour la vendeuse, conflit créé.
- Correction : annulation immédiate ; correction après délai ; correction équipe avec motif ; refus si versement ; trace `AuditLog` présente dans chaque cas.
- Fenêtre : début ≥ fin de live + délai ; largeur 60–180 ; deux modifications maximum, la troisième est refusée ; fenêtre absente = confirmation refusée.
- Migration : `cod_collected=True` devient `payment_status=paid` ; aucune autre ligne n'est modifiée. Les tests existants (tableau de bord, comptages, `UnhonoredOrder`, Distrib) passent sans modification.
- Page de suivi : jeton invalide = 404 ; aucune donnée personnelle affichée.

---

## 11. Déploiement

1. Migrations **non destructives** (ajout de colonnes, aucune suppression). Sauvegarde préalable de la base de production (règle projet).
2. Staging d'abord, avec les tests de non-régression complets.
3. Production seulement après 48–72 h de stabilité sur staging (décision du 18 oct.).
4. Aucune modification de l'app `distrib` avant validation de D1.
5. Fonctionnalités derrière un drapeau de configuration (activable sans redéploiement) si la validation D1 n'est pas faite.

---

## 12. Ce que je n'ai pas encore vérifié

- ~~Le flux exact de réception d'un paiement Orange Money en prépaiement~~ : **vérifié le 7 nov. 2026** : le SMS arrive au bénéficiaire dans tous les cas (prépaiement ou à la livraison). Reste à vérifier si la plateforme peut recevoir une confirmation automatique (non nécessaire en V1).
- Le comportement de l'interface vendeuse et du tableau de bord avec les nouveaux états (à tester en staging).
- L'absence totale de page de suivi pour les commandes directes : je ne l'ai pas trouvée dans les URLs ni les templates, mais je n'ai pas fait de recherche exhaustive des templates.

---

## 13. Numéro de paiement affiché et paiement par un tiers (ajout du 7 nov. 2026)

### 13.1 Source du numéro (vérifiée dans le code)
- `Distributor.orange_money_number` : numéro Orange Money du grossiste, saisi par l'équipe. La revendeuse ne peut pas le modifier.
- Chaîne de lien existante : produit de la boutique (`products.Product`) → `ImportedProduct` (lien OneToOne avec le produit, créé lors de l'import) → `WholesaleProduct` → `Distributor` → `orange_money_number`.
- Un produit de la boutique qui ne vient pas d'un grossiste n'a pas de lien : le numéro affiché est celui de la vendeuse (**à vérifier** : je n'ai pas encore repéré le champ dédié dans `SellerProfile`).

### 13.2 Règle d'affichage (proposée)
- Sous le bouton « Commandé » du produit, afficher : « Paiement par Orange Money sur XX XX XX XX ».
- Le numéro est déterminé par le produit choisi, jamais par le choix de la revendeuse. Un même panier ne peut pas mélanger des grossistes différents : une commande = un bénéficiaire = un numéro. (`Order` a un champ `product`, et `OrderItem` existe déjà : à vérifier avant d'implémenter ce cas.)
- Le template du bouton « Commandé » n'a pas encore été repéré dans le dépôt : à localiser avant de coder.

### 13.3 Paiement par un tiers (proche avec un compte Orange Money)
- **Accepté**, c'est une pratique courante, même si rare à Bamako.
- Le SMS de l'opérateur indique le nom de l'expéditeur, qui ne sera pas forcément celui de l'acheteuse. Le bénéficiaire doit donc vérifier **le montant et la date**, et non le nom seul.
- Pas de champ supplémentaire en V1. Le nom de l'expéditeur figure dans la trace du SMS, côté bénéficiaire.

## 14. Live sans produit physique (question ouverte, rien d'implémenté)

### 14.1 Constat
- La revendeuse ne tient pas de stock. Une cliente ne peut pas toucher, mesurer ni essayer le produit pendant le live.
- Le stock est alloué par le grossiste (`AllocationMovement`, `allocated_qty`), et les variantes existent (`ProductVariant` : couleur, taille, pointure, avec stock par variante).

### 14.2 Pratiques répandues (à vérifier avant d'en faire une référence)
- **Live « dropshipping »** : la vendeuse montre les photos et vidéos fournies par le fournisseur, sans stock. C'est la pratique la plus courante sur les lives de vente en ligne.
- **Échantillons** : un exemplaire par modèle, prêté ou acheté, montré en live. Le reste est livré depuis le stock du fournisseur.
- **Fiche produit détaillée** : tableau de tailles en centimètres, couleurs, matières, photos sous plusieurs angles, stock par variante.

### 14.3 Recommandation pour HayaFlash
1. **Pas de stock minimum obligatoire** pour la revendeuse. Une obligation de ce type ne peut pas être vérifiée par la plateforme, et elle freinerait les revendeuses qui débutent.
2. **La fiche produit est la source de vérité**, fournie par le grossiste : photos multi-angles (`WholesaleProductImage`), tableau de tailles, couleurs, et stock par variante. C'est la fiche, et non la description de la revendeuse, qui fait foi.
3. **Échantillon optionnel**, montré en live. Le grossiste peut en prêter un, ou la revendeuse peut en acheter un. HayaFlash ne le contrôle pas.
4. **Pendant le live** : un lien vers la fiche HayaFlash, qui affiche les variantes disponibles en temps réel. La revendeuse ne doit pas dire qu'un article est disponible sans que le stock le confirme.
5. **Protection de la cliente** : une fiche ou une description trompeuse (taille, couleur, matière) engage la revendeuse et le grossiste. Il faut prévoir un **cadre de retour ou d'échange** pour les produits non conformes. Ce point n'est pas encore dans la spec et doit être décidé avant le lancement du module Distrib en live.

### 14.4 Ce qui n'est pas recommandé
- Une obligation d'avoir un stock physique : impossible à vérifier, et contraire au modèle grossiste.
- Une simple description de la revendeuse, sans fiche du grossiste : risque de fausse promesse.

## 15. Décisions à valider (ajout)

| # | Sujet | Ma recommandation |
|---|---|---|
| D9 | Numéro affiché : celui du grossiste du produit choisi (§13.2) | Oui |
| D10 | Une commande = un bénéficiaire (pas de panier mélangé entre grossistes) | Oui |
| D11 | Paiement par un tiers accepté, vérification du montant et de la date | Oui |
| D12 | Pas de stock physique obligatoire pour la revendeuse | Oui |
| D13 | La fiche du grossiste fait foi, avec un tableau de tailles et un stock par variante | Oui, à préciser |
| D14 | Cadre de retour ou d'échange pour les produits non conformes | À décider avant le lancement du module en live |
