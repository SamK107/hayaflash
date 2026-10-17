# Le Marché HayaFlash — phase 1 (page publique `/ventes/`)

Date : 2026-10-17. Lecture seule : aucun modèle, aucune migration, pipeline de commande intact.

## Fichiers

| Fichier | Changement |
|---|---|
| `flash_sales/services/ordering.py` | `recently_ended_q(now, window)` + `RECENTLY_ENDED_WINDOW` (2 h) |
| `analytics/services/market.py` (nouveau) | `get_market_snapshot(now)`, cache 30 s, clé `hf:market:v1` |
| `flash_sales/public_views.py` | `_market_context()` : groupes, stats par vente, bandeau, héros « état calme », ventes terminées, puces |
| `templates/flash_sales/public_calendar.html` | En-tête « Le Marché », CSS, état Alpine `cat`, tiroir « M'alerter » partagé |
| `templates/flash_sales/partials/_calendar_list.html` | Bandeau, puces, cartes live / calmes / terminées, héros, état vide |
| `static/js/hf-public.js` | Comptes à rebours HH:MM:SS, urgence, animation des cartes nouvelles, ouverture du tiroir |
| `flash_sales/tests_marche.py` (nouveau) | 15 tests |

## Décisions

- **Snapshot** : 5 requêtes agrégées au plus sur cache froid (ventes en direct, terminées, commandes, articles, stock), 0 sur cache chaud. Il ne contient que des types simples (ids, int, str, datetime), pas d'instances de modèle. Les listes de ventes (en direct / à venir) restent lues à chaque requête (2 requêtes) : un changement de groupe n'attend jamais le cache.
- **% vendu** = `articles vendus / (vendus + stock restant)`, stock = somme de `Product.stock_available` des produits actifs liés à la vente (même source que `compute_live_pulse`). `None` si stock absent ou nul, ou si < 5 %. Commandes annulées exclues partout.
- **Badge commandes** : `PROOF_MIN_ORDERS` (importé de `live_pulse`).
- **Urgence** (orange < 15 min ou > 70 % vendu, rouge < 5 min + pulsation) calculée côté client, car elle dépend du temps qui passe ; elle s'applique à la barre de progression.
- **`recently_ended_q`** : `end_time < now` et `end_time >= now - fenêtre`, hors `CANCELLED`. Complémentaire exact de `live_now_q` (`end_time >= now`), donc jamais les deux. Une vente fermée par le vendeur avant l'heure de fin reste « en cours » côté horaire, comme partout ailleurs sur le site public.
- **Filtre catégorie** : état Alpine `cat` sur `.hfc-wrap` (hors de la zone remplacée par HTMX) ; les puces et les cartes sont dans le fragment, donc le filtre survit au rechargement. Si la catégorie active disparaît de la liste, retour automatique sur « Tout ».
- **Rafraîchissement** : `every 30s [document.visibilityState === 'visible']` + `hfc-refresh` + `visibilitychange` (rafraîchit au retour sur l'onglet). Aucun en-tête de cache modifié. Animation d'entrée uniquement pour les ventes jamais vues (suivi par slug en JS), jamais sur toute la liste.
- **M'alerter** : un seul tiroir pour la page, qui réutilise `submitInterest()` et `POST /f/<slug>/interest/` ; le slug est posé au clic. Aucun nouvel endpoint.
- **État calme** : sans vente en direct, la prochaine vente passe en vedette (grand compte à rebours + M'alerter) et est retirée de sa liste ; sans rien du tout, message d'accueil + lien `register` « Tu vends en live ? ».

## Écarts par rapport au brief

- **Emojis du bandeau et du badge (⚡ 🕗 🔥)** : remplacés par des mots (pastilles « En direct » / « Bientôt », « N commandes »). Le garde-fou `core/tests_ui_icons.py` interdit tout emoji décoratif dans les templates.
- **Captures** : pas de Playwright ; vérification manuelle dans le navigateur intégré (mobile et desktop, base SQLite jetable supprimée ensuite). Pas de fichiers image enregistrés.
- Le « 1 colonne / 2 / 3 » s'applique aux sections « En direct » et « Vient de se terminer » ; les lignes « Bientôt » et « À venir » restent en lignes sobres pleine largeur.

## Vérifications

- `pytest --ds=config.settings.test flash_sales core analytics` : 558 passés (avant le correctif emoji) puis `core/tests_ui_icons.py`, `core/tests_csp.py`, `analytics/tests.py`, `flash_sales/tests_marche.py` : 73 passés. `PublicVisibilityByTimeTests` vert.
- `ruff check` propre sur les fichiers touchés (le dépôt compte ~600 alertes ruff préexistantes ailleurs).
- Navigateur : filtre par catégorie (conservé après rechargement HTMX), tiroir « M'alerter » (slug posé), comptes à rebours, barre de progression, bandeau, section « Vient de se terminer ».

## Points ouverts

- La suite complète (`pytest` hors modules ci-dessus) n'a pas été relancée après le correctif emoji ; seuls les modules concernés l'ont été.
- Les heures affichées (« 01:37 – 02:12 ») suivent le fuseau actif du serveur, comme avant ; non modifié.
- Test réel sur téléphone à faire : bandeau (marquee) et tiroir sur faible bande passante.
- Phase 2 (indices de la journée, graphiques, ventilation des livraisons) non commencée, en attente de validation.

## Corrections finales (17/10)

- Badge « N commandes » : seuil `PROOF_MIN_ORDERS` importé de `live_pulse` (même que `/f/<slug>/pulse/`), rien sous le seuil.
- « Vient de se terminer » : plus aucun compteur de commandes ; « Terminée » (ou « Épuisé » si stock = 0) + « M'alerter » ; test d'absence ajouté.
- Suite complète : 1606 passés, 4 ignorés. Ruff propre sur les fichiers touchés (~600 alertes préexistantes ailleurs).
