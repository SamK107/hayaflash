# distrib — constats P0 (24/10/2026)

Branche `feature/distrib` (créée depuis `main` local, `a8c0b8b`). Lecture seule : aucun code écrit.
Spec : `docs/specs/SPEC_03_DISTRIB_V1.md` (Avenant A §15 prioritaire).

## 0. Base de départ

| Contrôle | Résultat |
|---|---|
| Lint `ruff check . --select E,F,W --ignore E501` (venv `.venv`) | `All checks passed!` |
| `makemigrations --check --dry-run` (settings test) | `No changes detected` |
| Suite complète `pytest --ds=config.settings.test` (SQLite) | **1928 passed, 4 skipped, 527 subtests passed** (5 min 32 s) — vert (PostgreSQL `hf-pg-test` non lancé, sqlite seulement) |

Note : l'interpréteur système (`C:\Program Files\Python311`) n'a ni pytest ni django-htmx : **utiliser `.venv\Scripts\python.exe`**.
`main` est en avance d'un commit sur `origin/main` ; aucun fetch/push fait.

## a. Order / OrderItem — plusieurs articles ? (§3)

**Oui, le modèle le permet.** `OrderItem.order` → `Order` (`related_name="items"`), `product`,
`product_name_snapshot`, `price_snapshot` (FCFA entiers), `quantity` (`orders/models.py:86-105`).
`Order` garde aussi un `product` legacy nullable (`orders/models.py:30`) et `total_amount` (`:66`).
Statuts : `OrderStatus` (`orders/models.py:9-14`) = pending / confirmed / out_for_delivery / delivered / cancelled.
Le client public ne commande qu'un produit à la fois (`flash_sale_id`, `product_id`, `quantity` dans
`static/js/hf-components.js:191-200`) ; l'API `create_order` boucle toutefois sur plusieurs produits
(`orders/services/create_order.py:123`).
→ Suivi : **une `DistribSettlement` par `OrderItem`** dont le `product` est un `ImportedProduct`, et ne
jamais s'appuyer sur `Order.product` (legacy). Le cas multi-articles est donc à prévoir pour §15.2 (cas partiel).
`Order.objects.create()` est interdit (`GuardedOrderManager`, `:17-24`) ; lecture via `Order.service_objects`.
Aucun signal `post_save` n'existe aujourd'hui sur `Order` (seul `analytics/signals.py` en a, sur d'autres modèles) :
`distrib` peut enregistrer le sien dans `DistribConfig.ready()`.

## b. Services `products/` : création produit, ajustement de stock (§5.3)

- Création : `create_product(*, owner, name, price, stock, description, unit, …)`
  (`products/services/crud.py:9-54`) → `Product` + `StockMovement(INITIAL)`. Utilisable tel quel.
  Images : `add_product_image(*, product, image_file, order)` (`:76-85`, valide le fichier, crée `ProductMedia`).
  Rattachement vente : `attach_product_to_sale` (`:88-111`). `update_product` (`:57-73`).
- Ajustement : `adjust_stock(*, product, new_stock_available, notes)` (`:114-132`) → mouvement `CORRECTION`.
  **⚠️ Il NE verrouille PAS la ligne** : pas de `select_for_update`, pas de transaction ; il fixe une valeur
  **absolue** à partir de `product.stock_available` lue en mémoire puis `save(update_fields=…)`.
  Une commande concurrente (`create_order` verrouille bien le produit : `create_order.py:123`) peut être écrasée
  (lost update) → du stock « ressuscite » ou disparaît. Seul appelant actuel : `products/api.py:166`.
- Le seul code qui fait ça proprement est `release_order_stock` (`orders/services/stock_release.py:32-35`) :
  `select_for_update()` puis `F("stock_available") + n`.
- Enum `StockMovement.MovementType` : INITIAL, RESERVATION, RELEASE, CORRECTION (`products/models.py:168-173`).

**Conséquence / repli (aucun service modifié)** : pour la **reprise** (§5.3) ne pas appeler `adjust_stock`.
`distrib.services.allocation` fera, dans `transaction.atomic()`, `Product.objects.select_for_update().get(pk)`,
borne `qty ≤ stock_available` lu *sous verrou*, `update(stock_available=F(...) - qty)` et crée un
`StockMovement(CORRECTION, quantity_change=-qty)`. Même chose pour une allocation complémentaire (+).
Création initiale : `create_product` convient (aucune concurrence possible sur un produit neuf).
À signaler au mainteneur : `adjust_stock` lui-même est un défaut latent (hors périmètre — finding à consigner).

## c. Circuit d'annulation de la vendeuse (§15.2)

Chaîne : vue `orders/views.py:236-249` `seller_order_cancel` (POST) → `cancel_order_by_seller(*, user, order_id)`
(`orders/services/dashboard.py:290-295`) → `delivery.services.delivery.apply_order_action(user, order_id, "cancel")`
(`delivery/services/delivery.py:419-439`) → `advance_delivery(..., action="cancel")` (`:245`, branche `:294-315`).
Cette branche : verrouille `Delivery` puis `Order` (`:259-274`), **appelle `release_order_stock(order, "Annulation par la vendeuse")`**
(`:303-305`), passe `Order.status = CANCELLED`, écrit un `AuditLog` (`order.cancelled_by_seller`, `actor=user`). ✔ stock libéré.
`release_order_stock` se base sur les mouvements de la commande (réservations − libérations déjà faites) : rejouable, pas de double retour.

**Appelable depuis `distrib` sans modification : techniquement oui, mais pas proprement ni suffisamment.**
1. **Identité** : la fonction exige `user == flash_sale.owner.user` (`:276-278`, et `apply_order_action:429-435`).
   Un grossiste n'est jamais ce `user`. Il faudrait passer `imported.product.owner.user` (la revendeuse) :
   l'action est alors journalisée comme **faite par la revendeuse** (`actor`), ce qui contredit l'esprit du §15
   (« aucune action demandée au revendeur », traçabilité du grossiste). Usurpation d'identité de service : **non recommandé**.
2. **États couverts** : annulation seulement si `order.status ∈ {pending, confirmed}` **et** `delivery.status ∈ {pending, assigned}`
   (`:296-301`). **Impossible dès `out_for_delivery` / `in_transit`** — or le cas réel du « Pas livré »
   (cliente refuse/absente à la porte) se produit précisément à ce stade. Un échec de livraison passe par
   `mark_failed` (`:368-387`) qui n'annule pas la commande, **ne libère pas le stock** et enregistre la commande comme
   non honorée (`record_unhonored_order` → compte vers le blocage du numéro de la cliente après 3 échecs : effet de bord sur une cliente
   que le grossiste peut déclarer à tort).
3. Effets annexes : `invalidate_seller_kpi_cache(user)`, mails/notifs éventuels hors de contrôle de `distrib`.
Autre voie existante : `orders/services/expiration.py:56-58` (annulation automatique des commandes pending trop vieilles,
appelle aussi `release_order_stock`) — réservée au système.

**Verdict §15.2 : non faisable proprement en l'état.** Selon la spec, « sinon : arrêter et consigner, ne rien contourner » →
je m'arrête sur ce point. Repli proposé (à valider) :
- (R1) « Pas livré » enregistre `not_delivered` + motif dans `distrib` seulement, **sans toucher à la commande** ni au stock ; le stock reste
  « parti » ; reprise de stock via la reprise manuelle (§b, verrou propre). Simple et sûr, mais perd l'effet de contrôle voulu (§15.2, dernier point).
- (R2) Étendre la spec : autoriser `distrib` à appeler **directement** `orders.services.stock_release.release_order_stock` (service existant, lecture/appel
  sans modification) dans sa propre transaction `atomic`, verrouillant `Order`, **sans** changer `Order.status` — mais cela laisse une commande
  `confirmed/out_for_delivery` avec stock rendu (état incohérent côté vendeuse) : à écarter sans décision explicite.
- (R3) Demander un petit service d'annulation « par un tiers autorisé » dans `orders/`/`delivery/` (modification hors périmètre §8 → décision du mainteneur).
Recommandation : **R1 en V1**, R3 en V1.1 si l'effet de contrôle est jugé indispensable.

## d. `templates/orders/client_order.html` — include du code à 4 chiffres (§15.3, accès 1)

- Le gabarit est rendu en GET **avant** toute commande (`orders/views.py:33-37`, `@require_GET`).
  La commande est créée par un `fetch` JSON vers `/api/v1/orders/` (`static/js/hf-components.js:210`) ; le composant Alpine
  `clientOrderForm` (`x-data` sur `client_order.html:79-89`) passe `submitted = true` et stocke la réponse dans `orderResult` (`:226-227`) ;
  la confirmation est un bloc Alpine `x-show="submitted"` **dans le même `x-data`** (`client_order.html:204-210`, référence `orderResult.id`).
- **Un seul `{% include "distrib/_receipt_hint.html" %}` est possible**, placé *dans* le `<div x-data=…>`, à côté du bloc de confirmation
  (avant `client_order.html:211`). Il hérite du scope Alpine (`submitted`, `orderResult.id`, `$refs.customerPhone`). Le serveur ne connaît pas la commande à ce moment :
  l'include est un fragment Alpine qui, quand `submitted` passe à vrai, appelle un endpoint `distrib` (`/distrib/recu/`, POST : `orderResult.id` + téléphone saisi)
  qui renvoie le code **si** la commande contient un produit importé, et pose le cookie `hf_receipts` (HttpOnly, côté serveur). Le JS va dans `distrib/static/distrib/…`
  (CSP : pas de `<script>` inline, `script-src 'self'`, directives Alpine OK).
- **Faisable sans toucher à `orders/`, au JS ni à l'API** (l'API ne renvoie pas de code, on ne la change pas). Points d'attention :
  1. L'include modifie quand même **un fichier hors §8** (`templates/orders/client_order.html`) : §15.3 l'exige explicitement ; à acter comme dérogation (une ligne).
  2. `id` de commande séquentiel : l'endpoint doit exiger `id` **et** téléphone correspondant (`Order.customer_phone`), limiter le débit, répondre à l'identique si échec
     (sinon le code serait récupérable par énumération).
  3. Le signal `post_save`+`on_commit` crée la ligne avant la réponse HTTP ; prévoir quand même un retry court côté JS (réconciliation 5 min en dernier recours).
  4. Le gabarit teste `can_submit` : l'include doit être dans ce `{% if can_submit %}` (sinon il ne verra jamais de commande).
  5. Cookie posé par la réponse d'un endpoint `distrib` : possible, indépendant de l'API de commande.

## e. Gabarit commun des pages publiques : lien « Confirmer un paiement » + bandeau (§15.3, accès 1 et 2)

- Pas de « footer » commun dans `templates/base.html` (structure : `{% block content %}` dans `<main>`, `base.html:233-236`, puis scripts `:238-249`).
- **Existe déjà un partial commun de pied de page** : `templates/partials/_legal_links.html` (Confidentialité / CGU / Mentions), inclus par
  `analytics/flash_sale_public.html:715`, `analytics/seller_public.html:125`, `flash_sales/public_calendar.html:195`, `accounts/register.html:169`, `core/legal/_layout.html:33`.
  **Mais** : absent de `orders/client_order.html` et de `core/home.html` (qui a son propre `<footer>`).
- Deux options pour **un seul** `{% include "distrib/_public_hooks.html" %}` :
  - **(E1, recommandée)** `base.html`, juste avant `</main>` (ou après `{% endblock %}` `:235`) : couvre **toutes** les pages publiques, dont `/order/` et la home ; l'include décide
    lui-même (balise d'inclusion `distrib`) d'afficher bandeau + lien, jamais sur les pages vendeur/admin (test sur `request.path`/`user`). Fichier hors §8 → dérogation d'une ligne.
  - (E2) `partials/_legal_links.html` : couvre les 4 pages publiques ci-dessus mais **pas** `/order/` ni la home ; aucune des pages hors pied de page n'est touchée.
- Dans les deux cas : `DISTRIB_ENABLED` faux ⇒ la balise rend `""` (aucun lien, aucun bandeau). Le bandeau lit le cookie `hf_receipts` côté serveur
  (`request.COOKIES`, HttpOnly donc pas de JS) et ne rend rien sans ligne ouverte. Impact cache : pages publiques servies avec `Vary: Cookie` ? **À vérifier avant E1**
  (page publique éventuellement mise en cache ; le bandeau dépend d'un cookie).

## f. Redirection après connexion pour un utilisateur sans `SellerProfile` (§5.1)

- `LOGIN_URL="/login/"`, `LOGIN_REDIRECT_URL="/seller/"` (`config/settings/base.py:298-299`).
- `core/views.py:158-187` `login_view` : POST valide → `redirect(_safe_next_url(request) or _post_login_redirect_target(user))` ;
  `_safe_next_url` (`:136-155`) n'accepte que les chemins locaux (anti open-redirect) → **`/login/?next=/distrib/` fonctionne** pour un
  utilisateur **non connecté**, y compris sans `SellerProfile` (le formulaire propage `next` : `templates/accounts/login.html:29`).
- `_post_login_redirect_target` (`:122-133`) : sans profil → `platform_admin` (staff) ou `seller_home` ; `seller_home_view` (`core/views.py:327-343`) rend
  `seller/no_profile.html` pour un non-staff sans profil (pas de 500, pas de boucle).
- **Piège** : si l'utilisateur est **déjà connecté**, `login_view` (`:159-160`) redirige vers `_post_login_redirect_target` **en ignorant `next`** → un grossiste
  déjà connecté qui ouvre `/login/?next=/distrib/` atterrit sur `/seller/` (page « pas de boutique »).
- **Conclusion** : `/distrib/connexion/` doit être une vue `distrib` : si `request.user.is_authenticated` et `Distributor` actif → `redirect("/distrib/")` ;
  sinon `redirect("/login/?next=/distrib/")`. Aucun fichier existant à modifier. Un grossiste sans boutique qui se trompe d'URL (`/login/` sans next) tombe sur
  `no_profile.html` : acceptable (pas d'erreur), mais la page n'évoque pas Distrib. Un grossiste **avec** boutique va à `/seller/` par défaut : normal.

## g. Tableau de bord vendeur — où poser le bandeau d'invitation (§5.2)

- Le tableau de bord vendeur est `templates/seller/home.html` (vue `core/views.py:327` `seller_home_view`, route `/seller/` via `core.seller_urls`, `config/urls.py:37`).
  Structure : `{% block content %}` ligne 5, conteneur `max-w-5xl` ligne 6, puis l'en-tête « Bonjour, … » (lignes 8-30).
- **Point d'insertion unique** : `{% include "distrib/_invitation_banner.html" %}` (ou `{% distrib_invite_banner %}`) juste après l'ouverture du conteneur, **avant** l'en-tête (`seller/home.html` ~ligne 7).
  Le gabarit hérite de `request` (context processor) : la balise lit `request.user.phone` (E.164) → invitations `invited` correspondantes (`ResellerInvite.phone`), `DISTRIB_ENABLED` faux ⇒ rien.
- Remarque : « à la création de boutique » (§5.2) n'a **aucune vue/template à modifier** : le premier affichage de `/seller/` après création suffit (la détection est à la visite, pas à la création).
- Fichier hors §8 stricte, mais c'est précisément « la ligne d'include dans le template du tableau de bord vendeur » **autorisée** par §8 → OK sans dérogation.

## Décisions du mainteneur (24/10/2026)

- **§15.2 : R1 retenu.** « Pas livré » pose uniquement `not_delivered` (+ motif, auteur, date) dans `distrib` ; ni `Order` ni stock touchés,
  aucune remise en stock automatique. Réaffectation volontaire via l'allocation §5.3. Spec mise à jour (§15.2, tests 14, staging §15.12).
- **§15.3 : les deux dérogations d'une ligne sont acceptées** : `templates/orders/client_order.html` (include dans le `x-data`, dans `{% if can_submit %}`)
  et le gabarit public commun (option E1 `templates/base.html` recommandée, à confirmer avant P6b ; cache vérifié le 24/10, voir plus bas).
  Ce sont les seules lignes hors §8 autorisées, avec la ligne de `seller/home.html`.

## Interactions avec `orders/expiration.py` et `orders/unhonored.py` (lecture seule)

`expiration.py` (tâche beat `orders.expire_pending_orders`, `config/settings/base.py:487`, `ORDER_PENDING_EXPIRY_HOURS = 48`, `base.py:464`) :
- ne sélectionne que `status=PENDING` et `created_at < now − 48 h` (`expiration.py:34-39`, relecture sous verrou `:47-52`) ; passe la commande en `CANCELLED`,
  appelle `release_order_stock` (idempotent : se base sur les mouvements nets de la commande) et écrit `order.expired` dans l'`AuditLog`.
- **Peut agir sur une commande Distrib** : toute commande de produit importé restée `pending` 48 h (revendeuse n'a pas confirmé) est annulée, stock rendu à la boutique.
  Conséquences pour `distrib` : (1) la synchro §5.4 doit faire passer la ligne en `cancelled` (jamais `paid_confirmed` si la commande est annulée) ;
  (2) comme 48 h < `auto_confirm_hours` (72 h), la présomption §15.1 ne s'applique jamais à une commande restée `pending` ; (3) si le grossiste a déclaré
  `not_delivered` sur une commande encore `pending`, l'expiration l'annulera plus tard et rendra le stock **une seule fois** (pas de double libération, puisque `distrib`
  n'a rien libéré) ; la ligne reste `not_delivered` (statut final, jamais écrasé).
- N'écrit rien dans `distrib` et ne l'importe pas : aucune modification de `orders/` nécessaire.

`unhonored.py` (F-59 / D2) :
- `record_unhonored_order` n'est appelé que par `advance_delivery` action `mark_failed` (`delivery/services/delivery.py:385-387`), donc par une **action de la vendeuse** sur la livraison.
  `distrib` n'appelant pas ce circuit, « Pas livré » **n'enregistre aucune commande non honorée** et n'affecte pas le blocage du numéro de la cliente.
- `blocked_phone_keys` exclut les commandes `CANCELLED` du compte (`unhonored.py:67`, `:90`) : une commande expirée/annulée ensuite par le circuit normal ne compte pas. Pas d'interaction avec `distrib`.
- Lecture seule : `distrib` peut au plus lire `Order.status` ; aucune action requise.

**Cas `paid_confirmed` puis commande annulée : tranché le 24/10/2026** (spec §15.1, §5.4, §15.9, tests 13 et 15 mis à jour) :
- source `auto`, ligne sans versement : la synchro la passe en `cancelled` et recalcule marge/commission (présomption renversée), `DistribCorrection` auteur système ;
- source `distributor` ou `customer`, ou ligne déjà dans un `ResellerPayout` : pas de rétrogradation, `conflict_flag` + signal pilotage (correction staff) ;
- `auto_confirm_hours` court depuis `confirmed_at`, horodaté par `distrib` à la première observation de `confirmed` (ou plus) ; une commande `pending` n'est jamais auto-confirmée (cohérent avec l'expiration à 48 h).
- Point de précision restant : `confirmed_at` a la précision de la synchro (signal immédiat, réconciliation ≤ 5 min), `orders/` n'exposant pas d'horodatage de confirmation.

## Décision P7 : relevé hebdomadaire (24/10/2026) — spec §15.4, §15.9, §15.1, §5.6, tests 11, 18, 22-25

- Plus de montant libre : tâche beat du lundi 00:05 (`distrib.tasks.close_weekly_statements`) génère un `DistribStatement` par revendeur (lundi 00:00 → dimanche 23:59:59, `Africa/Bamako`), avec les lignes `paid_confirmed` non encore couvertes ; montant calculé.
- Le grossiste clique « Payé » + référence OM : le `ResellerPayout` (une ligne par déclaration, 2 au plus) couvre exactement les lignes du relevé (`DistribSettlement.payout` renseigné sur chacune). Pas de paiement partiel ; les lignes confirmées après clôture vont au relevé suivant.
- Contestation portée sur le relevé (reste dû, signal pilotage ; une redéclaration, puis staff seul). Renversement automatique §15.1 : relevé `to_pay` recalculé, relevé `paid` figé (→ `conflict_flag`).
- Modèle : nouveau `DistribStatement` ; `DistribSettlement.statement` + `.payout` ; `ResellerPayout.statement` (FK + `attempt`). Aucune migration hors `distrib`.
- Précisions validées le 24/10/2026 : pas de relevé à 0 FCFA ; alerte de retard = relevé `to_pay` depuis plus de `payout_delay_days` après la clôture ; `accepted_source` = `staff` possible.
- Ajustements du 24/10/2026 : **une seule redéclaration** par le grossiste sur un relevé contesté (nouvelle référence OM, nouveau délai de 72 h, `ResellerPayout.attempt` = 2) ; **2e contestation → relevé `escalated`**, staff seul (clôture `accepted`/`staff` ou réouverture `to_pay`, `contest_count` remis à 0) ; **`payout_delay_days` = 3 par défaut**, réglable par grossiste.
- Modèle ajusté en conséquence : `ResellerPayout.statement` devient une FK (unicité `statement` + `attempt`) au lieu d'un OneToOne ; `DistribStatement` gagne le statut `escalated` et `contest_count`.

## Cache des pages publiques avant E1 (`base.html`), vérifié le 24/10/2026

Constats :
- `/f/<slug>/` et `/s/<slug>/` renvoient `Cache-Control: public, max-age=60, stale-while-revalidate=120` + `ETag` (`analytics/views.py:24-30`), **sans `Vary: Cookie`**, et sans cookie `csrftoken` (`analytics/views.py:124-128`). Pas de `cache_page` ni de middleware de cache Django (`config/settings/base.py:248-265`) ; pas de `proxy_cache` Nginx (`infra/nginx/prod.conf` : `expires` seulement sur `/static/` et `/media/`). Le service worker est network-first pour les pages HTML (`static/sw.js:73-79`). **Pas de CDN** : le mainteneur a vérifié le 24/10/2026 que `hayaflash.com` résout directement vers le VPS (31.207.39.116), sans CDN ni proxy intermédiaire ; seuls les caches navigateur/service worker restent à considérer.
- `/order/` (`orders/views.py:33-37`) et `/ventes/` : pas d'en-tête de cache explicite.
- Conséquence : un bandeau rendu **côté serveur** à partir du cookie `hf_receipts` serait mis en cache 60 s (+120 s) par le navigateur ou un intermédiaire et pourrait être servi à une autre personne ; l'`ETag` (non lié au bandeau) provoquerait aussi des 304 sans lui.
- **Décision de conception pour P6b (E1 validée le 24/10/2026)** : l'include de `base.html` (E1) rend un fragment **identique pour tous** (lien « Confirmer un paiement » + conteneur vide du bandeau), donc sans risque de cache. Le bandeau est chargé par un `fetch` same-origin vers un endpoint `distrib` (`Cache-Control: private, no-store`, lit le cookie HttpOnly côté serveur, renvoie un fragment vide s'il n'y a rien à afficher). Le JS est dans `distrib/static/` (CSP `script-src 'self'`). `DISTRIB_ENABLED` coupé : include vide. Le lien est cache-safe (décalage de 60-180 s au plus lors d'une bascule du flag). E1 reste donc possible sans toucher aux en-têtes existants.

## Synthèse faisabilité

| Point | Statut | Détail |
|---|---|---|
| §3 OrderItem multi-articles | ✅ | un suivi par `OrderItem` |
| §5.3 `adjust_stock` verrouillé | ❌ pas de verrou | verrou propre dans `distrib`, aucun service modifié |
| §15.2 annulation depuis `distrib` | ❌ non propre → **R1 décidé** | `not_delivered` dans `distrib` seulement, ni `Order` ni stock |
| §15.3 include `client_order.html` | ✅ avec dérogation d'une ligne | fragment Alpine dans le scope `x-data` ; endpoint `distrib` ; hors §8 |
| §15.3 include page publique | ✅ avec dérogation d'une ligne | E1 `base.html` (recommandé) ou E2 `_legal_links.html` ; hors §8 |
| §5.1 redirection | ✅ | vue `distrib/connexion/` ; piège « déjà connecté » |
| §5.2 bandeau | ✅ | une ligne dans `seller/home.html`, autorisée §8 |

## Écarts / points à trancher avant P1

1. **Dérogations §8** (acceptées le 24/10) : `templates/orders/client_order.html` (+1 ligne) et `templates/base.html` ou `partials/_legal_links.html` (+1 ligne) ne figurent pas au périmètre §8 alors que §15.3 les impose.
2. **§15.2** : tranché le 24/10 (R1), spec mise à jour.
3. **`adjust_stock` sans verrou** (`products/services/crud.py:114`) : finding à consigner dans le suivi de release (pas de correction « au passage »).
4. Commande API en mode multi-produits mais UI mono-produit : décider si le cas partiel §15.2 est à traiter en V1.
