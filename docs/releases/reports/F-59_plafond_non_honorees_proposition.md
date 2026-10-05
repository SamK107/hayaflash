# F-59 — Plafond de commandes non honorées par numéro : proposition

> **Proposition seulement, rien n'est implémenté.** Attend la décision du mainteneur
> (valeurs, message, emplacement). L'expiration à 48 h et la restitution du stock sont
> faites (commit `28e57ab`, branche `fix/expiration-stock`).

## Ce que l'expiration ne règle pas

Une commande à paiement à la livraison réserve du stock pendant 48 h. Un bot qui change
de numéro à chaque commande reste libre de vider une vente pendant ces 48 h : les limites
existantes ne l'arrêtent pas (voir « Interaction »).

## Proposition

Deux règles, évaluées sur le numéro de l'acheteur (8 derniers chiffres, comme
`order_phone_limited`, pour que `+22370000001` et `70 00 00 01` comptent pareil).

| # | Règle | Valeur proposée | Effet |
|---|---|---|---|
| A | Commandes **en attente** simultanées par numéro, toutes ventes confondues | **3** | Un numéro ne peut pas immobiliser plus de 3 commandes de stock à la fois. N'a besoin d'aucun historique. |
| B | Commandes **expirées** (jamais confirmées) par numéro sur une fenêtre glissante | **2 sur 7 jours** | Au-delà, plus de nouvelle commande de ce numéro avant la fin de la fenêtre. Frappe les récidivistes, pas le client occasionnel. |

Le vendeur reste l'arbitre : confirmer une commande la sort de A (et elle n'est jamais comptée dans B).

### Message en français (même texte pour A et B, sans révéler la règle)

> « Vous avez déjà des commandes en attente de confirmation. Attendez qu'elles soient confirmées par le vendeur, puis réessayez. »

Pour B, une fois la fenêtre dépassée, la commande repasse sans action de l'utilisateur.

### Emplacement et code de retour

- Dans `create_order`, après le rejeu idempotent (un rejeu ne consomme rien, comme la limite
  par numéro actuelle) et **avant** la réservation de stock.
- Refus en **400** avec `{"detail": [...]}` comme les autres refus métier : c'est un état,
  pas un débit de requêtes, donc pas de 429.
- Course : deux commandes simultanées du même numéro peuvent passer toutes deux A. Pour un
  plafond strict : `pg_advisory_xact_lock` sur l'empreinte du numéro dans la transaction de
  `create_order`. Sans verrou, dépassement possible de 1 ou 2 commandes : acceptable si on
  veut éviter le verrou.

### Distinguer « expirée » des autres annulations

Aujourd'hui l'expiration est le **seul** chemin qui annule une commande, donc
`status = cancelled` suffit. Si une annulation par le vendeur est ajoutée un jour, il faudra
s'appuyer sur l'`AuditLog` `order.expired` (déjà écrit) pour ne pas pénaliser l'acheteur.

### Coût technique

`customer_phone` n'est pas indexé et stocké tel que saisi (formats variables). La recherche
par 8 derniers chiffres (`endswith`) n'utilise pas d'index : acceptable à l'échelle des
pilotes (filtre d'abord sur `created_at`, indexé), à revoir avec un champ normalisé indexé
(**migration**, donc seulement sur ton accord).

## Interaction avec les limites existantes

| Limite existante | Interaction |
|---|---|
| IP 120/min (Django et Nginx) | Aucune : A et B portent sur le numéro, pas sur l'IP. |
| Numéro 10 / 10 min (`RATELIMIT_ORDER_PHONE`) | Complémentaire : celle-ci freine le débit, A et B plafonnent le stock immobilisé. A (3) est plus strict que 10/10 min, donc c'est A qui se déclenche en premier pour un acheteur honnête qui recommande. |
| **CGNAT** (beaucoup d'acheteurs derrière une IP) | Non touchée : aucun compteur par IP. C'est le principal avantage. |
| Stock insuffisant | Inchangé. |

## Limites assumées

- Un bot qui change de numéro à chaque commande n'est pas arrêté par A ni B ; il est borné
  par la limite d'IP et par les 48 h. Seule une vérification du numéro (code SMS à la
  commande, payant) fermerait ce cas : hors de cette proposition.
- Un foyer qui partage un téléphone partage le plafond. Le message invite à attendre la
  confirmation du vendeur.
- Un numéro légitime qui a deux commandes expirées (vendeur injoignable) est bloqué 7 jours
  sur B : valeur à discuter, par exemple 3 sur 14 jours.

## Décisions à prendre

1. Valeurs de A (3) et B (2 / 7 jours), ou les deux ?
2. Texte du message.
3. Verrou strict (advisory lock) ou dépassement toléré ?
4. Index sur le numéro normalisé (migration) maintenant ou après les pilotes ?
