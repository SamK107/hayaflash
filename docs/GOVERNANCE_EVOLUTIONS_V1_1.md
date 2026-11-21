# GOUVERNANCE — Évolutions V1.1 (prod en service)

> Statut : validé pour développement local — 22 oct. 2026
> Périmètre : Lot 1 Prix promo · Lot 2 Studio photo · Lot 3 Module grossistes (Distrib V1)
> Règle d'or : **hayaflash.com a de vrais clients. Rien de ce qui existe ne doit changer de comportement, sauf la correction de bug du Lot 1.**
> Méthode : chaque phase = un prompt Claude Code distinct, une branche, des tests verts, puis la suivante. Ne jamais enchaîner plusieurs phases dans un seul prompt.

---

## 0. Règles communes (s'appliquent aux 3 lots)

### 0.1 Interdits absolus
- Ne pas modifier : `orders/services/create_order.py`, `payments/`, `orders/models.py`, statuts `OrderStatus`, `stock_release`, flux de paiement Orange Money.
- Pas de renommage / suppression de champ, pas de migration de données, pas de `ALTER` sur une colonne existante.
- Ne jamais utiliser `docker compose down -v` (supprime les volumes : base + médias).
- Ne jamais déployer deux lots ensemble. Ordre : Lot 1 → prod → Lot 2 → prod → Lot 3 → prod.
- Ne pas nommer quoi que ce soit « partner » dans le Lot 3 : l'app `partners` existe déjà (programme partenaires). Le module grossistes s'appelle **`distrib`**.

### 0.2 Autorisé
- Nouvelles apps Django (`studio`, `distrib`) avec leurs propres tables.
- Lecture seule des modèles existants (`Order`, `OrderItem`, `Product`, `FlashSaleProduct`…).
- Écritures sur modèles existants **uniquement** via les services listés dans ce document (ex. `ProductMedia.file` dans le Lot 2, `Product` créé par import dans le Lot 3).

### 0.3 Interrupteurs (feature flags) — `config/settings/base.py`, via `_env_bool`
| Variable | Défaut | Rôle |
|---|---|---|
| `PROMO_STRIKE_DISPLAY` | `true` | Affiche prix barré + « Prix promo » (Lot 1). La correction du prix reste active même à `false`. |
| `FEATURE_STUDIO_ENABLED` | `false` | Active le Studio (Lot 2) ; accès en plus limité par `StudioAccess`. |
| `FEATURE_DISTRIB_ENABLED` | `false` | Active `/distrib/` et `/seller/distrib/` (Lot 3). Désactivé → 404. |

Couper un module en prod = changer la variable dans `.env` + `docker compose up -d web worker` (pas de rebuild).

### 0.4 Contrôles obligatoires avant chaque merge
```bash
python manage.py makemigrations --check --dry-run   # aucune migration oubliée
python manage.py migrate --plan                     # seules les migrations du lot
python manage.py sqlmigrate <app> <numéro>          # relire : uniquement CREATE TABLE / CREATE INDEX / ADD COLUMN NULL
pytest -q                                           # 100 % vert, y compris les 70+ tests existants
ruff check .
```
Un test de non-régression `tests_regression_v1_1.py` (créé au Lot 1, enrichi à chaque lot) vérifie que : une commande publique sans promo, avec promo, et l'annulation + libération de stock donnent exactement les mêmes résultats qu'avant.

### 0.5 Parcours de déploiement (identique pour chaque lot)
1. Branche `feature/lot-N-…` depuis `main`, CI verte, merge.
2. **Staging** : déployer, tester sur téléphone réel, laisser tourner **48 h** (24 h suffisent pour le Lot 1).
3. **Prod**, hors vente flash en cours (vérifier dans l'admin qu'aucune vente n'est `live`) :
   ```bash
   # sur le VPS, dans le dossier hayaflash
   ./scripts/backup.sh            # ou pg_dump + archive médias, puis copie chiffrée (age) vers D:
   git tag v1.1-lotN-avant && git push --tags
   docker compose -f docker-compose.production.yml build
   docker compose -f docker-compose.production.yml run --rm web python manage.py migrate --plan
   docker compose -f docker-compose.production.yml up -d
   docker compose -f docker-compose.production.yml run --rm web python manage.py migrate
   ```
4. Tests de fumée prod : connexion vendeuse, Marché `/ventes/`, page commande d'une vente test, `/api/v1/health`, et vérifier que symain.africa et services.symain.africa répondent.
5. Activer le flag du lot (sauf Lot 1, actif d'office).
6. **Retour arrière** : 1) couper le flag ; 2) sinon redéployer l'image du tag précédent (les tables ajoutées ne gênent pas l'ancien code) ; 3) restauration de sauvegarde = dernier recours.

---

## LOT 1 — Prix barré + « Prix promo » sur la page de commande

### 1.0 Constat (lecture du code, 22/10)
**Bug en prod** : `orders/services/client_order.py::resolve_client_order_page` vérifie le lien produit-vente avec `.exists()` et transmet l'objet `product` ; le template `orders/client_order.html` affiche `product.price` (ligne ~50) et le JS calcule le total avec `product.price` (ligne ~82). Or `create_order.py` facture `link.effective_price`. **Quand un prix promo existe, la cliente voit et totalise le prix catalogue, mais la commande enregistre le prix promo.** Le Marché (`_calendar_list.html`) affiche déjà correctement prix barré et −X %.

### 1.1 Phase unique — service + template (aucune migration)
`orders/services/client_order.py` : remplacer le `.exists()` par la récupération du lien :
```python
link = (
    FlashSaleProduct.objects.filter(
        flash_sale_id=flash_sale.id, product_id=product.id, is_active=True
    )
    .only("promo_price")
    .first()
)
if link is None:
    return { ...même dictionnaire d'erreur qu'aujourd'hui... }

unit_price = link.effective_price          # prix réellement facturé (source de vérité)
catalog_price = product.price
show_strike = (
    settings.PROMO_STRIKE_DISPLAY
    and link.promo_price is not None
    and catalog_price
    and link.promo_price < catalog_price
)
discount_pct = (
    int(round((1 - (unit_price / catalog_price)) * 100)) if show_strike else 0
)
```
Ajouter au contexte de retour : `"unit_price": unit_price, "catalog_price": catalog_price, "show_strike": show_strike, "discount_pct": discount_pct`. Ne rien retirer du contexte existant.

`templates/orders/client_order.html` :
```django
{% if show_strike %}
  <div class="flex items-baseline gap-2 flex-wrap">
    <span class="text-base text-gray-400 line-through">{{ catalog_price|floatformat:"0g" }} FCFA</span>
    <span class="text-2xl font-bold text-primary">{{ unit_price|floatformat:"0g" }} FCFA</span>
    <span class="hf-promo-pill">Prix promo −{{ discount_pct }} %</span>
  </div>
{% else %}
  <span class="text-2xl font-bold text-primary">{{ unit_price|floatformat:"0g" }} FCFA</span>
{% endif %}
```
Et dans le JS : `price: {{ unit_price|floatformat:0 }},` (au lieu de `product.price`).
Style de la pastille : reprendre exactement celui de la pastille −X % du Marché (même classe si elle est réutilisable).

Règles :
- `unit_price` est **toujours** affiché, même si `PROMO_STRIKE_DISPLAY=false` (c'est la correction de bug).
- Pas de prix barré si promo ≥ prix catalogue.
- Montants en FCFA entiers, jamais de centimes.

### 1.2 Tests (`orders/tests_client_order_promo.py`)
1. Sans promo : affiche le prix catalogue, pas de `line-through`.
2. Avec promo 7 500 / catalogue 10 000 : affiche 10 000 barré, 7 500, « −25 % ».
3. Promo ≥ catalogue : pas de prix barré, affiche le prix promo.
4. `PROMO_STRIKE_DISPLAY=False` : pas de barré mais prix affiché = prix promo.
5. Le prix injecté dans le JS = `effective_price`.
6. Une commande passée via l'API publique a un total = prix affiché × quantité.
Créer aussi `tests_regression_v1_1.py` (cf. 0.4).

### 1.3 Critères de validation staging
- Vente test avec 2 produits (un avec promo, un sans) : affichage correct sur téléphone, total du formulaire = total de la commande dans le tableau de bord vendeuse.
- Durée : ~1 jour de dev, 24 h de staging.

---

## LOT 2 — Studio HayaFlash (détourage photo, fond uni)

### 2.0 Prérequis bloquant (avant toute ligne de code)
Sur le VPS : `free -h` et `docker stats --no-stream`. Il faut **≥ 1,5 Go de RAM réellement libre**.
- OK → modèle `isnet-general-use` (meilleure qualité produits).
- Entre 0,6 et 1,5 Go → modèle léger `u2netp` (qualité moindre, quelques dizaines de Mo de RAM), à valider sur photos réelles.
- < 0,6 Go → reporter le Lot 2 (ou augmenter le VPS).
Noter le résultat dans ce document.

### 2.1 Architecture
- App `studio` (nouvelle). Dépendances : `rembg` (licence MIT), `onnxruntime`, Pillow (déjà présent).
- **Le conteneur `web` n'importe jamais `rembg`** : import uniquement dans la tâche Celery (import local dans la fonction). La RAM du web ne change pas.
- Nouvelle file Celery `studio`, consommée **uniquement** par un nouveau service `worker-studio` :
  ```yaml
  worker-studio:
    <<: *app-common            # même image que worker (reprendre l'ancre existante)
    command: celery -A config worker -l info -c 1 -Q studio --max-tasks-per-child 50
    mem_limit: 1500m           # 700m si modèle u2netp
    cpus: 1.0
  ```
  Le `worker` existant reste sur `-Q default,flash_sales,notifications` (inchangé). Adapter `CELERY_WORKER_QUEUES`/routes et `core/tests_celery_queues.py` de façon cohérente (lire ce test avant).
- Modèle téléchargé **au build** (jamais au premier appel en prod) : dans le Dockerfile, `ENV U2NET_HOME=/opt/rembg` puis `RUN python -c "from rembg import new_session; new_session('isnet-general-use')"`.

### 2.2 Modèles (`studio/models.py`, migration additive)
```python
class StudioAccess(models.Model):          # liste blanche des boutiques pilotes
    seller = models.OneToOneField("accounts.SellerProfile", on_delete=models.CASCADE, related_name="studio_access")
    enabled = models.BooleanField(default=True)
    daily_quota = models.PositiveSmallIntegerField(default=20)
    created_at = models.DateTimeField(auto_now_add=True)

class PhotoCleanJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "En file"
        RUNNING = "running", "En cours"
        DONE = "done", "Prêt"
        APPLIED = "applied", "Appliqué"
        REVERTED = "reverted", "Annulé"
        FAILED = "failed", "Échec"
    seller = models.ForeignKey("accounts.SellerProfile", on_delete=models.CASCADE, related_name="studio_jobs")
    media = models.ForeignKey("products.ProductMedia", on_delete=models.SET_NULL, null=True, related_name="studio_jobs")
    original_file = models.ImageField(upload_to=RandomUploadPath("studio/originals"))   # copie de sauvegarde
    result_file = models.ImageField(upload_to=RandomUploadPath("studio/results"), blank=True)
    bg_color = models.CharField(max_length=7, default="#FFFFFF")      # validé ^#[0-9A-Fa-f]{6}$
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    error = models.CharField(max_length=255, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### 2.3 Service image (`studio/services/clean.py`) — fonction pure, testable
```python
def clean_image(data: bytes, *, bg_color: str = "#FFFFFF", size: int = 1080, model: str) -> bytes:
    from rembg import new_session, remove        # import local : jamais chargé par le web
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGBA")
    img.thumbnail((1600, 1600))                    # borne la RAM et le temps
    cut = remove(img, session=_session(model))     # _session = cache module-level
    bbox = cut.getbbox()
    if bbox is None:
        raise StudioError("Aucun produit détecté sur la photo.")
    cut = cut.crop(bbox)
    cut.thumbnail((int(size * 0.85),) * 2)
    canvas = Image.new("RGBA", (size, size), bg_color)
    canvas.alpha_composite(cut, ((size - cut.width) // 2, (size - cut.height) // 2))
    out = io.BytesIO()
    canvas.convert("RGB").save(out, "WEBP", quality=82, method=4)
    return out.getvalue()
```
En test, `rembg.remove` est **mocké** (CI rapide, aucun modèle téléchargé en CI).

### 2.4 Tâche (`studio/tasks.py`)
`clean_photo_job(job_id)` sur la file `studio`, `soft_time_limit=60`, `time_limit=90`, `acks_late=True`. Passe `running` → `done` (enregistre `result_file`, `duration_ms`) ou `failed` (message en français lisible par la vendeuse).

### 2.5 Parcours vendeuse (HTMX)
1. Sur une photo produit existante : bouton **« ✨ Nettoyer le fond »** (visible seulement si flag + `StudioAccess.enabled`).
2. Choix du fond en pastilles : Blanc `#FFFFFF`, Gris clair `#F3F4F6`, Crème `#FAF3E0`, Rose poudré `#F9E4E7`, Noir `#111827`, + « Couleur de ma boutique » (sélecteur).
3. `POST /seller/studio/jobs/` → copie la photo dans `original_file`, crée le job, lance la tâche. Vérifie le quota du jour (`daily_quota`) et refuse si > 20 jobs en file au total (« Le Studio est occupé, réessaie dans une minute »).
4. Poll HTMX toutes les 2 s sur `/seller/studio/jobs/<id>/` → aperçu **avant / après**.
5. **« Utiliser cette photo »** → `ProductMedia.file` ← `result_file` (job `applied`). **« Annuler »** → restaure `original_file` (job `reverted`). L'original n'est jamais supprimé.
6. Vérification de propriété à chaque vue : `job.seller == request.user.seller_profile` et `media.product.owner == seller`.

### 2.6 Phases Claude Code
| Phase | Contenu | Validation |
|---|---|---|
| 2.1 | App, modèles, admin, migration additive, flag | `sqlmigrate` = CREATE TABLE uniquement |
| 2.2 | `clean_image` + tests (rembg mocké) | tests verts |
| 2.3 | Tâche, file `studio`, service compose, Dockerfile (modèle au build) | `tests_celery_queues` vert, `docker compose config` OK |
| 2.4 | Vues + UI HTMX + quotas + permissions | tests de vues (propriété, quota, flag off → 404) |
| 2.5 | Staging : 20 vraies photos téléphone (tissus, chaussures, cosmétiques, bijoux) | pic RAM `worker-studio` < `mem_limit`, temps p95 < 10 s, symain non affecté |
| 2.6 | Prod : flag ON + `StudioAccess` pour 2–3 pilotes | 1 semaine d'observation avant ouverture plus large |

---

## LOT 3 — Distrib V1 (grossistes → revendeurs)

### 3.0 Prérequis non techniques (bloquants pour la prod, pas pour le dev)
- CGU / politique de confidentialité : l'adresse et le téléphone de la cliente sont transmis au grossiste qui livre.
- Contrat grossiste : commission (pilote 0 % 2 mois), minimum et plafond par commande, plafond d'encours, délai de versement des marges aux revendeurs (≤ 7 jours), prix de vente minimum, refus de livraison, authenticité des produits.

### 3.1 Principes de conception
- **Aucune modification** de `create_order.py`, des paiements, des statuts de commande ni des formulaires produits existants.
- Le revendeur **importe** un produit du grossiste → création d'un `products.Product` **normal** dans sa boutique (+ copie des images en `ProductMedia`). Tout le reste (vente flash, commande, prix promo, stock, annulation) fonctionne déjà. **Aucune migration sur `products`** : le lien est porté par `distrib.StockAllocation.product`.
- **Stock V1 = allocation par revendeur** : quantité allouée = `Product.stock_available` de la copie → la survente est impossible par construction (verrou existant de `create_order`). Bouton « Reprendre l'allocation » = récupérer uniquement les unités non vendues.
- **HayaFlash ne touche jamais l'argent** : le livreur du grossiste encaisse ; HayaFlash calcule et affiche.
- **Double contrôle** : la boutique (avec le livreur) fait avancer la commande dans le flux existant (`out_for_delivery` → `delivered`) ; le **grossiste seul** confirme ensuite « Encaissement reçu » dans Distrib. Si la cliente a payé d'avance, le grossiste peut confirmer avant la livraison (statut « Payé d'avance »).
- « Temps réel » V1 = rafraîchissement HTMX toutes les 30 s + badge « nouvelles commandes ». Pas de WebSocket.

### 3.2 Modèles (`distrib/models.py`, migrations additives)
```python
class Wholesaler(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "En attente de validation"
        ACTIVE = "active", "Actif"
        SUSPENDED = "suspended", "Suspendu"
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="wholesaler")
    business_name = models.CharField(max_length=150)
    district = models.CharField(max_length=100, blank=True)                 # quartier
    payout_phone = models.CharField(max_length=32)                          # numéro Orange Money (référence)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    commission_rate = models.DecimalField(max_digits=4, decimal_places=2, default=0)   # % ; 0 pendant le pilote
    commission_min = models.PositiveIntegerField(default=250)               # FCFA par commande
    commission_cap = models.PositiveIntegerField(default=1500)              # FCFA par commande
    pilot_until = models.DateField(null=True, blank=True)                   # commission = 0 jusqu'à cette date
    outstanding_cap = models.PositiveIntegerField(default=10000)            # plafond d'encours FCFA
    created_at / updated_at

class WholesaleProduct(models.Model):
    wholesaler = FK(Wholesaler, related_name="catalog")
    name, description, category (core.choices.SaleCategory)
    wholesale_price = PositiveIntegerField()        # FCFA
    min_retail_price = PositiveIntegerField()       # prix de vente minimum imposé ; >= wholesale_price (clean())
    stock_total = PositiveIntegerField()
    is_active = BooleanField(default=True)
    created_at / updated_at

class WholesaleProductImage(models.Model):
    product = FK(WholesaleProduct, related_name="images"); file = ImageField(validators=IMAGE_VALIDATORS); order = IntegerField(default=0)

class ResellerLink(models.Model):
    class Status(models.TextChoices): INVITED="invited","Invité"; ACTIVE="active","Actif"; ENDED="ended","Terminé"
    wholesaler = FK(Wholesaler); seller = FK("accounts.SellerProfile", related_name="distrib_links")
    status, created_at, updated_at ; unique_together (wholesaler, seller)

class StockAllocation(models.Model):
    link = FK(ResellerLink); wholesale_product = FK(WholesaleProduct, related_name="allocations")
    product = OneToOneField("products.Product", on_delete=models.PROTECT, related_name="distrib_allocation")
    quantity_allocated = PositiveIntegerField()
    created_at / updated_at

class Settlement(models.Model):                  # une ligne par (commande, grossiste)
    class Status(models.TextChoices):
        ORDERED="ordered","Commandée"; IN_DELIVERY="in_delivery","En livraison"
        DELIVERED="delivered","Livrée (boutique)"; PAID="paid","Encaissement confirmé"
        PREPAID="prepaid","Payé d'avance"; CANCELLED="cancelled","Annulée"
    order = FK("orders.Order", on_delete=models.PROTECT); wholesaler = FK(Wholesaler); seller = FK("accounts.SellerProfile")
    retail_total = PositiveIntegerField(); wholesale_total = PositiveIntegerField(); reseller_margin = IntegerField()
    commission_due = PositiveIntegerField(default=0)       # figé à la confirmation d'encaissement
    status; paid_confirmed_at = DateTimeField(null=True); paid_confirmed_by = FK(User, null=True)
    margin_paid_at = DateTimeField(null=True); margin_paid_ref = CharField(blank=True)   # versement marge au revendeur
    created_at / updated_at ; unique_together (order, wholesaler)

class CommissionPayment(models.Model):           # saisi par l'admin HayaFlash
    wholesaler = FK(Wholesaler); amount = PositiveIntegerField(); paid_at = DateTimeField(); reference = CharField(max_length=64); recorded_by = FK(User)
```
Encours d'un grossiste = Σ `commission_due` (statut PAID/PREPAID) − Σ `CommissionPayment.amount`.
Commission d'une commande = `0` si `pilot_until` non dépassée, sinon `clamp(round(retail_total × rate / 100), commission_min, commission_cap)`.

### 3.3 Services (`distrib/services/`)
- `import_product(link, wholesale_product, quantity, retail_price)` : `retail_price ≥ min_retail_price`, `quantity ≤ stock restant` ; transaction atomique ; crée `Product(owner=seller, stock_initial=stock_available=quantity, price=retail_price)`, copie les images, crée `StockAllocation` + `StockMovement` (type existant `initial`).
- `adjust_allocation(allocation, delta)` : `select_for_update` sur le `Product` ; une reprise ne peut retirer que `stock_available` (jamais les unités vendues) ; `StockMovement` type `correction`.
- `remaining_stock(wholesale_product)` = `stock_total − Σ quantity_allocated` (+ reprises).
- `sync_settlements(wholesaler=None)` : **lecture seule** sur `OrderItem` dont le produit a une `distrib_allocation` → crée/actualise les `Settlement` (statut dérivé de `Order.status` tant que non PAID/PREPAID). Appelée par une tâche beat toutes les 60 s (file `default`) **et** à l'ouverture du tableau de bord.
- `confirm_payment(settlement, user)` : réservé au grossiste propriétaire ; fige `commission_due` ; journalise.
- `record_margin_payout(settlement, ref)` : le grossiste déclare le versement de la marge au revendeur (référence Orange Money).
- Suspension (V1 manuelle, par l'admin) : bloque nouveaux imports et nouvelles allocations ; alerte rouge quand encours > plafond. Masquage automatique des produits = V2.

### 3.4 Écrans
**Grossiste — `/distrib/`** (connexion via `/distrib/connexion/` qui réutilise l'authentification existante puis redirige ; aucune modification de la redirection de connexion actuelle)
- Accueil : KPI du jour (commandes, en livraison, à encaisser, encaissé), badge nouvelles commandes, liste temps réel (poll 30 s).
- Commandes : statut, boutique, produit, quantité, adresse + téléphone cliente (pour livrer), bouton **« Encaissement reçu »**.
- Catalogue : CRUD produits de gros + images (photos nettoyables par le Studio en V2).
- Revendeurs : inviter (par numéro de boutique), allocations par produit, stock restant, bouton « Reprendre l'allocation ».
- Relevés : par revendeur (marges dues / versées) ; vis-à-vis de HayaFlash (commissions, encours, plafond).
- Inscription `/distrib/inscription/` → statut `pending` ; activation par l'admin uniquement.

**Revendeur — `/seller/distrib/`**
- Invitations reçues (accepter / refuser), catalogue de ses grossistes, bouton **« Importer dans ma boutique »** (quantité, prix ≥ minimum), suivi de ses marges.

**Admin HayaFlash — `/platform-admin/distrib/`** (`is_staff`)
- Validation des grossistes, paramètres de commission, encours, saisie des `CommissionPayment`, suspension.

Permissions : chaque requête filtre par `request.user.wholesaler` ou `seller_profile` ; tests d'accès croisé obligatoires (un grossiste ne voit jamais les données d'un autre).

### 3.5 Charte graphique « HayaFlash Distrib »
Bonne pratique des apps modernes (Shopify admin, Uber Freight, Jumia Vendor Center…) : **même famille de marque, accent différent** pour l'espace pro. Pas une charte totalement différente (coût, incohérence, perte de confiance).
- Garder : logo HayaFlash, police Inter, composants `hf-p-*`, rayons, espacements.
- Changer : accent principal **bleu nuit `#1E3A5F`** (sérieux, finance, B2B) ; le rouge HayaFlash `#E63946` reste pour la marque et les alertes.
- Libellé fixe en en-tête : **« HayaFlash Distrib »** + pastille « Espace grossiste ».
- Tokens (CSS variables dans un `distrib/base_distrib.html` qui étend la base) :
  `--d-primary:#1E3A5F; --d-primary-soft:#E8EEF5; --d-accent:#E63946; --d-success:#16A34A; --d-warning:#D97706; --d-bg:#F1F5F9; --d-text:#111827; --d-muted:#6B7280;`
- Statuts en couleur cohérente partout : Commandée (gris), En livraison (ambre), Livrée (bleu), Encaissement confirmé (vert), Annulée (rouge pâle).
- Mise en page pensée tablette/PC (tableaux denses) mais lisible sur téléphone (tableaux → cartes sous 640 px).

### 3.6 Phases Claude Code
| Phase | Contenu | Validation |
|---|---|---|
| 3.1 | App `distrib`, modèles, admin Django, migrations, flag | `sqlmigrate` = CREATE TABLE/INDEX uniquement ; aucune migration sur d'autres apps |
| 3.2 | Inscription + validation admin + catalogue grossiste | tests permissions, flag off → 404 |
| 3.3 | Invitations, import dans la boutique, allocations, reprise | tests stock (pas de survente, reprise ≤ invendus) |
| 3.4 | `sync_settlements` + tâche beat + tableau de bord temps réel | test : une commande publique standard crée un Settlement sans changer la commande |
| 3.5 | Confirmation d'encaissement, commissions, encours, relevés, versement des marges | tests calcul (pilote 0 %, minimum, plafond) |
| 3.6 | Espace revendeur `/seller/distrib/` | tests accès croisé |
| 3.7 | Admin plateforme `/platform-admin/distrib/` | — |
| 3.8 | Passe design (charte 3.5) + non-régression complète + staging avec 1 grossiste et 2–3 revendeurs | 48 h staging, parcours complet sur téléphone |

---

## 4. Modèle de prompt Claude Code (économe en tokens)
```
Lis docs/GOVERNANCE_EVOLUTIONS_V1_1.md : section 0 et la Phase <X.Y> uniquement.
Implémente seulement cette phase, sur la branche feature/lot-<N>.
Respecte les interdits de 0.1. Ne modifie aucun fichier hors du périmètre de la phase.
Avant de terminer : makemigrations --check, sqlmigrate des nouvelles migrations, pytest -q, ruff check.
Termine par : fichiers modifiés, migrations créées (avec le SQL), résultat des tests.
Ne passe pas à la phase suivante.
```

## 5. Journal
| Date | Lot / phase | Résultat | Déployé staging | Déployé prod |
|---|---|---|---|---|
| | | | | |
