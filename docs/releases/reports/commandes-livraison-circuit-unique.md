# Commandes / Livraison : circuit unique (18/10/2026)

Branche `fix/commandes-livraison-circuit-unique` (depuis `main` à `51bd747`). Rien poussé.

## 1. Diagnostic

Symptôme : des commandes de quelques jours passent d'étape dans `/orders/seller/dashboard/` mais ne réagissent plus
(ou disparaissent) sur la page Livraison ; celles du jour fonctionnent. Je n'ai pas accès aux données du staging :
la cause est établie **par le code et reproduite par les tests**, pas par une requête sur la base réelle.

Trois défauts se cumulaient :

1. **Fiche de livraison absente.** La synchro de Commandes (`_sync_delivery_for_order`) faisait `if delivery is None: return`
   et avalait toute exception. Une commande ancienne sans `Delivery` avançait donc sans bruit dans Commandes ; la page
   Livraison, qui ne liste que des `Delivery`, ne la montrait pas et ne pouvait rien lui faire faire.
2. **Statuts divergents.** « Livré » en groupe (`bulk_mark_delivered`) faisait un `update()` sur la commande seule ; le
   bouton de Commandes sautait « En livraison » et « Livré et payé » sans livreur ni encaissement. La fiche restait
   `pending`/`assigned` : les boutons de la page Livraison (qui exigent commande **et** fiche cohérentes) disparaissaient.
3. **Deux chemins de statuts.** L'échec de livraison (donc F-59, blocage du numéro) n'existait que sur Livraison ; Commandes
   pouvait « livrer » ce qui était en échec.
   (Aggravant : Livraison s'ouvre par défaut sur la vente **la plus récente** ; les commandes d'une vente plus ancienne n'y
   sont visibles qu'en changeant de vente, d'où l'impression qu'elles « n'apparaissent plus ».)

## 2. Correctifs

- `delivery/services/delivery.py` : `ensure_delivery_for_order` (fiche créée si elle manque, montant recalculé, idempotent),
  `ensure_deliveries_for_sale` (appelé à l'ouverture de Livraison), action `cancel` (stock rendu, audit), `mark_failed`
  exige une commande confirmée, `apply_order_action` = **seule porte** de Commandes vers le service de Livraison.
- **Rattrapage** : `python manage.py repair_order_deliveries --dry-run` puis sans option. Crée les fiches manquantes (commandes
  non annulées), réaligne « livré » / « en livraison » divergents, ne touche ni aux annulées, ni à l'encaissement, ni aux
  échecs. Idempotent.
- **Commandes** : seulement Confirmer et Annuler. Carte : « À livrer » (petit texte) + bouton contour « Gérer la livraison → »
  (vente + ancre `#delivery-row-<id>`), puis lecture seule : « En livraison » (gris), « Livré et payé » (vert), « Échec »
  (rouge) ; « Livré, à encaisser » (ambre) si livré non encaissé. Les étapes de livraison renvoient 403 avec un message
  clair ; « Livré » en groupe est refusé ; « Confirmer » en groupe passe par le service.
- **Livraison** : seule à faire avancer la livraison (livreur, En livraison, Livré et payé, Échec) ; plus de bouton Confirmer ;
  Confirmer/Annuler refusés (400, message). Menu **Livraisons** : pastille = commandes à livrer (confirmées ou en livraison,
  ni livrées ni en échec, y compris sans fiche).
- Guide « Ta première vente flash » (étape F) : décrit Confirmer → « Gérer la livraison → » → En livraison → Livré et payé / Échec.
- `orders/services/stock_release.py` : restitution de stock partagée entre expiration et annulation.

## 3. Tests

Nouveau `orders/tests_circuit_unique.py` (22) : commande ancienne sans fiche, rattrapage (dry-run, idempotence, annulées
intactes), transitions autorisées/refusées sur chaque page, annulation (stock rendu une fois, refus après mise en livraison,
autre vendeuse), F-59 déclenché par l'Échec, cartes (états, lien ancré), pastille du menu. Tests existants adaptés
(libellés « Livré et payé », définition de la pastille, étapes retirées de Commandes).

## 4. À faire par le porteur

Sur le staging après déploiement : `repair_order_deliveries --dry-run`, relire, puis sans option. Vérifier sur téléphone
une commande ancienne : Confirmer → Gérer la livraison → En livraison → Livré et payé.
