# PR 4 — Propositions (sans code) : accueil vendeur, compteurs, Commandes par vente

- **Date** : 2026-10-04 — **Branche** : `fix/finitions-ui-mobile` (depuis `main`)
- **Statut** : proposition, **en attente de validation du mainteneur**. Rien de ce qui suit n'est implémenté (seul B1, le bouton « Mon dashboard », l'est : commit `2eb4877`).
- **Contraintes** : textes français en dur ; aucune classe Tailwind absente du build (FV-01) ; aucun `<script>` inline ni `on*=` dans `templates/` (GS-4.1) ; aucune migration ni modèle touché.
- **Aperçu visuel** : [`ui-pr4-apercu-entete.html`](ui-pr4-apercu-entete.html) (autonome, s'ouvre directement).

## 1. Accueil vendeur (`templates/seller/home.html`)

### État actuel
- En-tête : `Bonjour, {{ display_name }} 👋` + sous-titre + bouton « Nouvelle vente ».
- Trois cartes : « Commandes totales » (`total_orders`), « Ventes actives » (`active_sales|length`), « Ventes terminées » (`recent_sales|length`).

### Proposition d'en-tête sobre
1. Retirer le 👋 (aligné sur le retrait des émojis-icônes).
2. Bloc : **pastille d'initiales** (2 lettres de `display_name`, rond `bg-primary/10 text-primary` — classes déjà utilisées dans ce gabarit), « Bonjour, *Prénom* », puis une **ligne d'état** :
   `2 ventes en cours · 5 commandes à traiter` (singulier/pluriel via `pluralize` ; segment omis à 0 ; si les deux sont à 0 : « Rien à traiter pour le moment »).
3. Bouton principal « **Créer une vente flash** » (remplace « Nouvelle vente », même URL `flash_sales:create`).
4. Pas de nouvelle icône : `plus` Lucide déjà présent.

### Requêtes exactes (aucune migration)
```python
now = timezone.now()
# Ventes en cours : règle d'heure (CLAUDE.md point 15), pas le statut seul
live_count = FlashSale.objects.filter(live_now_q(now), owner=seller).count()
# Commandes à traiter : statut exact PENDING (« En attente » = jamais confirmée)
to_process_count = Order.service_objects.filter(
    flash_sale__owner=seller, status=OrderStatus.PENDING
).count()
```
Définition retenue de « à traiter » : `OrderStatus.PENDING` uniquement (le vendeur doit encore la confirmer). Les commandes `CONFIRMED` attendent la livraison, ce qui relève du compteur « livraisons » (§2).

### F-75 — compteurs tronqués
`active_sales` est tranché à `[:5]` et `recent_sales` à `[:3]` dans `core/views.py:seller_home_view` (l.234-243), puis les cartes affichent `|length` → un vendeur avec 12 ventes à venir voit « 5 », et « 3 » ventes terminées au plus. **Correction proposée** : calculer les totaux par `.count()` sur les querysets non tranchés (`active_total`, `recent_total`) et ne garder le découpage `[:5]` / `[:3]` que pour les listes affichées. Coût : 2 `COUNT` supplémentaires filtrés sur `owner` (FK indexée).

### Fichiers touchés / tests
`core/views.py` (contexte), `templates/seller/home.html`. Tests : contexte (`live_count`, `to_process_count`, `active_total` > 5 avec 7 ventes, `recent_total` > 3), rendu (pas de 👋, présence « Créer une vente flash », pluriel), compte sans commande → « Rien à traiter ».

## 2. Compteurs de navigation (F-84)

Aujourd'hui seul `interests_count` est injecté (`core/context_processors.py:6-21`). Proposition : un context processor unique `seller_nav_counts` (étend `seller_interests_count`, mêmes garde-fous « non connecté / sans profil → 0 »).

| Pastille | Définition écrite | Requête | Index utilisé |
|---|---|---|---|
| **Commandes** (à traiter) | commandes du vendeur au statut `pending` | `Order.service_objects.filter(flash_sale__owner=seller, status="pending").count()` | `Order.status` (`db_index=True`, `orders/models.py:57`) + FK `flash_sale` |
| **Livraisons** (en cours) | livraisons du vendeur au statut `assigned` ou `in_transit` | `Delivery.objects.filter(order__flash_sale__owner=seller, status__in=["assigned","in_transit"]).count()` | `Delivery.status` indexé (`delivery/models.py:66,88`), `order` indexé (l.89) |
| **Réservations** | existant : `SaleInterest` du vendeur | inchangé | — |

- **Pourquoi `assigned` + `in_transit`** : un livreur assigné n'a pas encore livré ; `pending` (pas encore pris en charge) reste du ressort de « Commandes à traiter » ; `delivered` / `failed` sont terminés.
- **Coût par page** : 2 `COUNT` jointés de plus (3 au total avec l'existant) sur chaque page vendeur rendant `_nav_seller.html` ; le processor sera sauté pour les fragments HTMX (`HX-Request`), comme `pwa_install`.
- **Option cache** : `cache.get_or_set(f"hf:navcounts:{seller.pk}", compute, 5)` (5 s, même backend que `KPI_CACHE_TTL_SECONDS`, `orders/services/dashboard.py`). Recommandation : **cache 5 s** — au plus 5 s de retard visible, coût DB constant même avec rafraîchissements répétés.
- **Affichage** : même pastille que « Réservations » (`bg-primary text-white text-xs font-bold px-1.5 py-0.5 rounded-full`, classes déjà dans le build), masquée à 0, plafonnée à « 99+ ».
- **Tests** : définitions par statut (chaque statut inclus/exclu), isolation entre vendeurs, 0 sans profil, plafond 99+, `assertNumQueries` borné, cache (deuxième appel sans requête).

## 3. Page Commandes filtrée par vente flash (F-86)

### Constat
- `orders:seller_dashboard` n'affiche que la vente **en cours** (sinon la « prochaine vente ») ; ses fragments (`seller_dashboard_kpi`, `seller_dashboard_orders`) agrègent **toutes** les ventes du vendeur (`_seller_orders_queryset(user)`) et sont limités à **20 commandes** (`list_dashboard_order_rows(limit=20)`).
- La page Livraisons possède déjà un sélecteur de vente (`flash_sale_id` en GET, `deliveries_dashboard.html:30-46`, navigation via `data-hf-nav-prefix`).

### Proposition
- **Tableau de bord** (`/seller/`) = vue d'ensemble globale (inchangé en logique).
- **Commandes** = nouvelle page liste, filtrée par vente, option « Toutes les ventes ».
- **Route** : `orders/seller/orders/?flash_sale_id=<id>` → `orders:seller_orders` (absent = « Toutes les ventes »). Le lien « Commandes » de `_nav_seller.html` pointe dessus ; `seller_dashboard` (page LIVE) reste accessible.
- **Vue** : `seller_orders_page(request)` (FBV, `@login_required` + `_require_seller`), valide `flash_sale_id` (vente appartenant au vendeur, sinon refus).
- **Gabarit** : `templates/orders/orders_page.html`, patron de `deliveries_dashboard.html` : `<select data-hf-nav-prefix="?flash_sale_id=">` avec « Toutes les ventes » en tête, conteneurs HTMX KPI et liste.
- **Transmission du filtre aux requêtes HTMX** : les `hx-get` ajoutent `?flash_sale_id=…` ; `seller_dashboard_kpi` et `seller_dashboard_orders` lisent le paramètre (absent = global, comportement actuel conservé) et le passent à `get_dashboard_kpis_cached` / `list_dashboard_order_rows`.
- **KPI qui suivent le filtre** : `get_dashboard_kpis(user, flash_sale_id=None)` ; la **clé de cache KPI doit inclure `flash_sale_id`** (sinon un filtre afficherait les chiffres d'un autre) et `invalidate_seller_kpi_cache` doit purger toutes les clés du vendeur (ou utiliser un numéro de version par vendeur).
- **Fichiers touchés** : `orders/views.py`, `orders/urls.py`, `orders/services/dashboard.py`, `templates/orders/orders_page.html` (nouveau), `templates/partials/_nav_seller.html`.
- **Tests à écrire** : filtre par vente (vente d'un autre vendeur → refus), « Toutes » = global, KPI filtrés, clé de cache distincte par filtre, fragments HTMX avec/sans paramètre, lien Commandes actif dans la nav, aucun `only` autour d'un `{% csrf_token %}`.
- **Limite de 20 (F-78)** : **elle s'applique** telle quelle (`limit=20`). Sur une page « liste » c'est gênant : (a) garder 20 et afficher « 20 dernières commandes », ou (b) « Voir plus » HTMX par tranches de 20.

## Points de décision pour le mainteneur
1. « À traiter » = `pending` seul : OK ?
2. Livraisons « en cours » = `assigned` + `in_transit` : OK ?
3. Cache 5 s des compteurs de navigation : OK ?
4. Commandes filtrées : plafond 20 (a) ou « Voir plus » (b) ?
5. Bouton accueil « Créer une vente flash » alors que la nav garde « Nouvelle vente » : harmoniser ?
