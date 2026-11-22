# Journal — Tâche E : Marché (boutiques inactives), avertissement de paiement, signalement, suspension, niveaux de confiance

Branche : `task/e-confiance-marche` (worktree `C:\projets\hf-e`). Base : `69a5cbe` (`integration/v2`).

## 2026-11-22 — Mise en place

| Décision | Raison | Alternative écartée |
|---|---|---|
| Branche créée depuis `integration/v2` (`69a5cbe`) dans le worktree `hf-e`. L'ancienne branche `task/e-marche-confiance` (base `0d2b9e1`, ancêtre de `integration/v2`, sans commit propre) est conservée telle quelle. | La consigne demande une branche depuis `integration/v2`. L'ancienne base manquait les tâches A, C, D (migration `products/0011`, `plan_has_feature`). | Travailler sur l'ancienne branche : écarté, base obsolète. |

## 2026-11-22 — Objectif 1 : boutiques inactives sur le Marché

**Constat.** Le Marché (`/ventes/`) n'appliquait aucun filtre sur `SellerProfile.is_active` (le `owner` de `FlashSale`). `/s/<slug>/` filtrait déjà (`analytics/services/public_pages.py`) : le Marché était donc incohérent avec la boutique.

**Surfaces touchées** (toutes les requêtes du Marché) :
- `flash_sales/public_views.py` : listing `_calendar_groups` (en direct, à venir).
- `analytics/services/market.py` : `compute_market_snapshot` (en direct, terminées, à venir).
- `analytics/services/market_showcase.py` : vitrine et « produits du moment ».
- `flash_sales/market_entry.py` : entrée « Le Marché » de l'accueil (compteur).
- `flash_sales/market_stats.py` : commandes, sparkline, livraisons en cours.

**Décision.** Une seule règle, `flash_sales/services/marche_visibility.py::marche_shop_q(prefix)`, appliquée partout. Le filtre suit le chemin vers la boutique (`owner`, `flash_sale__owner`, `order__flash_sale__owner`).

**Non traité volontairement.** `/f/<slug>/` (page de vente directe) et la recherche : la page de vente n'est pas une surface du Marché listé ; à décider (voir questions).

**Point d'arrêt règle d (à confirmer).** La correction masque toute boutique dont `SellerProfile.is_active` est faux. Aucune donnée de production n'est lue ici (interdit : action distante). Les boutiques inactives de la base locale sont à lister avant fusion (voir section « Vérifications »).

**Test.** `flash_sales/tests_marche_vendeuses.py` : 4 tests, écrits d'abord, rouges sur `integration/v2` (la boutique suspendue apparaissait dans le snapshot, la page, le compteur et les statistiques), verts après correction.

## 2026-11-22 — Objectif 2 : avertissement de paiement côté cliente

**Gabarits.** L'audit ne liste pas les trois gabarits : la mention « paiement à la livraison » n'existe en dur que dans deux fichiers, `templates/analytics/flash_sale_public.html` (page de vente, tiroir de commande et confirmation du tiroir) et `templates/orders/client_order.html` (formulaire `/order/` et sa confirmation). Décision : le texte est mis dans le partiel unique `templates/partials/_payment_warning.html`, inclus dans les trois contextes (page de vente, formulaire, confirmation), soit 4 inclusions dans 2 fichiers. Écart avec « 3 gabarits » noté ici.

**Texte.** Mot pour mot, sans guillemets. Apostrophe droite (`c'est`) conservée tel quel dans la demande.

**Coquille.** « a la livraison » → « à la livraison » dans les deux gabarits.

**Non touché.** `templates/core/legal/terms.html` (CGU, interdit) et `privacy.html` ; `templates/core/home.html` (texte marketing « Chaque paiement à la livraison est tracé »), hors gabarits acheteuse, signalé comme question.

**Test.** `core/tests_avertissement_paiement.py` : texte unique dans les sources, inclusion dans les deux gabarits, présence sur la page de vente et sur `/order/` (2 occurrences chacune), absence de la coquille.

## 2026-11-22 — Objectif 3 : signalement de boutique (ShopReport)

| Décision | Raison | Alternative écartée |
|---|---|---|
| Modèle `accounts.ShopReport` (migration `accounts/0008_shopreport`) : boutique (`PROTECT`), motif (4 choix), message 500 car. max, contact 120 car. max facultatif, statut `new/handled/closed`, note interne, date. | Même app que `SellerProfile` ; aucune donnée supprimée. | App dédiée : écarté, un seul modèle. |
| Page publique `/signaler/<slug>/` (`accounts/report_views.py`), sans compte, `csrf` actif, `never_cache`. Boutique inconnue ou inactive : 404, comme `/s/<slug>/`. | Réponse qui ne révèle rien de plus que la boutique publique. | Réponse 200 générique pour une boutique inconnue : écarté, incohérent avec `/s/`. |
| Limite par IP réutilise `core/services/rate_limit.py` (`hit`, fail-open) : `RATELIMIT_SHOP_REPORT_IP = (5, 3600)`, toutes les soumissions (pas seulement les échecs). Dépassement : 429 avec message neutre. | Mécanisme existant ; clé `shopreport:ip:<hmac>`. | Nouveau cache ad hoc : écarté. |
| Anti-bot : `core/services/honeypot.py` (champ piège + jeton signé). Rejet anti-bot : message générique, rien enregistré. | Mécanisme déjà utilisé à l'inscription. | — |
| Aucun envoi automatique (SMS, WhatsApp, e-mail). Le contact de la cliente n'est pas écrit dans les journaux. | Interdits permanents + demande. | — |
| Admin : `ShopReportAdmin` (filtres statut, motif, boutique ; compteur par boutique ; lecture seule sauf statut et note ; ni ajout ni suppression). Colonne « Signalements » sur la boutique (lien vers la liste filtrée). | Demande. | — |
| Lien « Signale-la ici » sur la confirmation de la page de vente et du formulaire `/order/` (`{% if seller_slug %}` pour `/order/`, qui n'a pas de slug en cas d'erreur). | Demande (page de confirmation). | — |

**Points d'attention.** `SellerProfileAdmin` avait déjà un `get_queryset` (préchargements) : la méthode est fusionnée, pas dupliquée. La vérification `makemigrations --check` est faite à la fin (objectif 5 ajoute un champ à `SellerProfile`).

**Tests.** `accounts/tests_shop_reports.py` (12) ; `core/tests_avertissement_paiement.py` : liens vers le formulaire (2 tests de plus).

## 2026-11-22 — Objectif 4 : suspension et réactivation par l'équipe

| Décision | Raison | Alternative écartée |
|---|---|---|
| Mécanisme existant : `SellerProfile.is_active` (déjà lu par `/s/`, sitemap, Marché). Pas de nouveau champ, pas de migration. | Demande : réutiliser l'existant. | Nouveau champ `suspended_at` : écarté, redondant. |
| Service `accounts/services/suspension.py` : `suspend_shop` / `reactivate_shop`, motif obligatoire (1 à 300 car.), `select_for_update`, refus si déjà dans cet état, entrée `AuditLog` (`shop.suspended` / `shop.reactivated`, `actor`, `ip`, `metadata.reason`). | Demande (qui, quand, motif). | — |
| Admin : actions « Suspendre » et « Réactiver » sur `SellerProfile`, en deux étapes : page de confirmation avec motif obligatoire (`templates/admin/accounts/sellerprofile/suspension_form.html`). | Motif obligatoire imposé côté serveur. | Champ de motif dans le formulaire de la boutique : écarté, pas de motif sans action. |
| Garde-fou : `flash_sales/services/crud.py::_ensure_shop_can_sell` dans `create_flash_sale` et `clone_flash_sale` (les deux créent une vente). Lève `SaleRuleError`. | Demande : une boutique suspendue ne lance plus de vente. Couvre aussi la saisie assistée (même service). | Garde dans `enforce_creation_rules` : écarté, cette fonction sert aussi à la modification d'une vente existante (hors demande). |
| Aucune suppression ; ventes, commandes et abonnement inchangés. | Demande. | — |

**Ce qui n'est PAS changé (volontairement).** Connexion de la vendeuse (`User.is_active` intact) ; commandes sur une vente déjà ouverte ; modification de ventes existantes ; abonnement et quota.

**Point d'arrêt règle c / d (à trancher avant fusion).** Le Marché (objectif 1) et la création (objectif 4) excluent toute boutique dont `is_active` est faux. Une boutique déjà désactivée à la main avant ce chantier, mais légitime, disparaîtrait donc du Marché. Je n'ai pas accès à la production (interdit). Vérification à faire, lecture seule, par le fondateur :

```
python manage.py shell -c "from accounts.models import SellerProfile as S; print(list(S.objects.filter(is_active=False).values_list('seller_code','business_name')))"
```

**Tests.** `accounts/tests_suspension.py` (8 tests) : motif obligatoire, journal d'audit, aucune suppression, garde-fou de création, parcours admin en deux étapes.
