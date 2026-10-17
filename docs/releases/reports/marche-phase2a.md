# Le Marché, phase 2a : indices publics du jour

Fait : bloc « Le marché aujourd'hui » sous le bandeau de `/ventes/` (`flash_sales/market_stats.py`, `get_market_stats`) : commandes de la dernière heure, top 3 catégories, livraisons en cours, sparkline SVG inline (aucun JS, CSP intacte). Sous les seuils, l'indicateur est masqué ; tout masqué = bloc absent, état calme inchangé.
Seuils (constantes en tête de module) : `MARKET_MIN_ORDERS_HOUR` = 3, `MARKET_MIN_SHOPS_PER_CATEGORY` = 2, `MARKET_MIN_DELIVERIES` = 3, `MARKET_MIN_ORDERS_DAY` = 5 (sparkline, 2 points minimum).
Cache : 60 s, une clé par jour (`hf:market:stats:v1:<date>`) ; 4 requêtes à froid, 0 à chaud (testé, indépendant du nombre de commandes).
Statuts : commandes = `Order.status != CANCELLED` (`Order.service_objects`) ; pas de brouillon ni d'échec de paiement sur `Order` (COD V1). Livraisons = `Delivery.status == IN_TRANSIT`, commande non annulée.
Ville : aucun champ ville exploitable (`Delivery.address_text` libre) : libellé « En cours de livraison » sans ville.
Catégorie d'une commande : `flash_sale.category`, sinon `flash_sale.owner.category`, sinon « Autre » ; commandes sans vente exclues du top.
Sparkline : un point par heure de 0 h à l'heure courante incluse (heure en cours partielle).
Écarts au brief : chemins réels `flash_sales/services/ordering.py` ; le rafraîchissement HTMX est à 30 s (phase 1), pas 45 s ; le bloc affiche des noms de catégories sans effectifs.
Branche `marche-phase2a` (worktree `../hayaflash-marche2a`, partie du commit `b1e87ca`) : le checkout principal est sur `feat/admin-bilans-a`, utilisé par une autre session.
Tests : 14 nouveaux (`flash_sales/tests_market_stats.py`), suite complète 1620 passés, 4 ignorés.
Correctif multi-boutiques : `MARKET_MIN_SHOPS` = 2 ; commandes de la dernière heure, livraisons en cours et sparkline (boutiques distinctes sur la journée) exigent ce nombre de boutiques en plus du seuil de volume (même constante pour les catégories). Toujours 4 requêtes à froid (comptages et boutiques distinctes agrégés ensemble).
Tests : 4 cas « volume suffisant, une seule boutique » ajoutés ; suite complète relancée, ruff propre sur les fichiers touchés.
Tiroir « M'alerter » : modèle inerte (`<template>`) cloné une seule fois par le JS, rendu seulement si une carte a un bouton ; fermé il est `inert` + `aria-hidden` (testé, vérifié au navigateur). État calme : phrase « Suis tes boutiques… » remplacée par « Cette page se met à jour toute seule » (pas de suivi de boutiques).
Commande de dev `python manage.py seed_marche_demo [--clear]` (`core/management/commands/`, DEBUG uniquement, comptes repérés par le préfixe `+22379990`) : 3 boutiques, 3 ventes (en direct, dans 30 min, terminée il y a 1 h), 10 commandes sur 2 boutiques dans l'heure dont 3 livraisons IN_TRANSIT ; testée.
Suite complète et ruff relancés avant commit.
