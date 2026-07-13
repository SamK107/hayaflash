# Workflow P1 — Modèles Complets + Migrations
> Phase 1 · Durée estimée : ~1 semaine  
> Prérequis : P0 terminée

---

## Objectif

Aligner tous les modèles Django avec PROJECT_SPEC v2. Zéro champ manquant. Toutes les migrations validées. Admin complet.

---

## Étape 1.1 — FlashSale : statuts étendus

**Fichier** : `flash_sales/models.py`

Remplacer `FlashSaleStatus` :

```python
class FlashSaleStatus(models.TextChoices):
    SCHEDULED = "scheduled", "Programmée"
    LIVE      = "live",      "En cours"
    CLOSED    = "closed",    "Fermée"
    EXECUTING = "executing", "En exécution"
    COMPLETED = "completed", "Terminée"
    CANCELLED = "cancelled", "Annulée"
```

Ajouter sur le modèle `FlashSale` :
```python
description   = models.TextField(blank=True, verbose_name="Description")
cover_image   = models.ImageField(
    upload_to="flash_sales/covers/", null=True, blank=True,
    verbose_name="Image de couverture"
)
delivery_zone = models.CharField(
    max_length=200, blank=True, verbose_name="Zone de livraison",
    help_text="Ex: Bamako, ACI 2000, Kalaban Coura"
)
max_orders    = models.IntegerField(
    null=True, blank=True, verbose_name="Plafond de commandes",
    help_text="Laisser vide pour illimité"
)
```

Mettre à jour les méthodes :
```python
def open_sale(self) -> None:
    """Passe la vente en LIVE."""
    if self.status == FlashSaleStatus.CANCELLED:
        raise ValueError("Impossible d'ouvrir une vente annulée.")
    if self.status == FlashSaleStatus.COMPLETED:
        raise ValueError("Impossible de rouvrir une vente terminée.")
    self.status = FlashSaleStatus.LIVE
    self.save(update_fields=["status", "updated_at"])

def close_sale(self) -> None:
    """Ferme la vente (passe en CLOSED, puis EXECUTING si commandes existent)."""
    self.status = FlashSaleStatus.CLOSED
    self.save(update_fields=["status", "updated_at"])

def complete_sale(self) -> None:
    """Marque la vente comme complètement traitée."""
    self.status = FlashSaleStatus.COMPLETED
    self.save(update_fields=["status", "updated_at"])

def cancel_sale(self) -> None:
    """Annule la vente (seulement si pas encore LIVE)."""
    if self.status == FlashSaleStatus.LIVE:
        raise ValueError("Impossible d'annuler une vente en cours. Fermez-la d'abord.")
    self.status = FlashSaleStatus.CANCELLED
    self.save(update_fields=["status", "updated_at"])

@property
def is_scheduled(self) -> bool:
    return self.status == FlashSaleStatus.SCHEDULED

@property
def accepts_orders(self) -> bool:
    """Source de vérité unique pour les commandes."""
    from django.utils import timezone
    now = timezone.now()
    return (
        self.status == FlashSaleStatus.LIVE
        and self.start_time <= now <= self.end_time
    )
```

**Migration** : `python manage.py makemigrations flash_sales --name="extend_flash_sale_statuts_and_fields"`

**Data migration** : migrer `draft` → `scheduled` pour les lignes existantes.

```python
# migrations/XXXX_extend_flash_sale_statuts_and_fields.py
# Dans RunPython après AlterField :
def migrate_draft_to_scheduled(apps, schema_editor):
    FlashSale = apps.get_model("flash_sales", "FlashSale")
    FlashSale.objects.filter(status="draft").update(status="scheduled")
```

**Validation** :
- `python manage.py migrate` OK
- `FlashSale.objects.filter(status="draft").count() == 0`

---

## Étape 1.2 — Product : champs manquants

**Fichier** : `products/models.py`

```python
class Product(models.Model):
    flash_sale    = models.ForeignKey(
        "flash_sales.FlashSale", on_delete=models.CASCADE,
        related_name="products", null=True, blank=True
    )
    name          = models.CharField(max_length=255, verbose_name="Nom du produit")
    description   = models.TextField(blank=True, verbose_name="Description")
    price         = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="Prix (FCFA)"
    )
    stock_initial    = models.IntegerField(default=0, verbose_name="Stock initial")
    stock_available  = models.IntegerField(default=0, verbose_name="Stock disponible")
    unit          = models.CharField(
        max_length=50, default="pièce", verbose_name="Unité",
        help_text="pièce, kg, lot, carton..."
    )
    characteristics = models.JSONField(
        default=dict, blank=True, verbose_name="Caractéristiques",
        help_text='{"couleur": "rouge", "taille": "M"}'
    )
    display_order = models.IntegerField(default=0, verbose_name="Ordre d\'affichage")
    is_active     = models.BooleanField(default=True, verbose_name="Actif")
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "-created_at"]
        indexes = [
            models.Index(fields=["flash_sale", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.flash_sale_id})"

    @property
    def is_available(self) -> bool:
        return self.is_active and self.stock_available > 0

    @property
    def stock_percentage(self) -> int:
        if self.stock_initial == 0:
            return 0
        return int((self.stock_available / self.stock_initial) * 100)
```

**Data migration** : copier `stock → stock_initial` ET `stock → stock_available` si la colonne `stock` existait.

---

## Étape 1.3 — ProductMedia (nouveau modèle)

**Fichier** : `products/models.py` (ajouter après `Product`)

```python
class ProductMedia(models.Model):
    class MediaType(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Vidéo"

    product    = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="media"
    )
    media_type = models.CharField(
        max_length=10, choices=MediaType.choices, default=MediaType.IMAGE
    )
    file       = models.ImageField(
        upload_to="products/images/", null=True, blank=True,
        verbose_name="Fichier image"
    )
    video_url  = models.URLField(
        blank=True, verbose_name="URL vidéo",
        help_text="Lien YouTube, TikTok ou autre"
    )
    alt_text   = models.CharField(max_length=200, blank=True)
    order      = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return f"Media #{self.order} — {self.product.name}"
```

---

## Étape 1.4 — ProductVariant (nouveau modèle)

**Fichier** : `products/models.py` (ajouter après `ProductMedia`)

```python
class ProductVariant(models.Model):
    product  = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="variants"
    )
    type     = models.CharField(
        max_length=50, verbose_name="Type",
        help_text="couleur, taille, pointure..."
    )
    value    = models.CharField(max_length=100, verbose_name="Valeur")
    stock    = models.IntegerField(default=0, verbose_name="Stock variante")
    price_delta = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name="Différence de prix"
    )

    class Meta:
        unique_together = ("product", "type", "value")

    def __str__(self) -> str:
        return f"{self.product.name} — {self.type}: {self.value}"
```

---

## Étape 1.5 — StockMovement (nouveau modèle)

**Fichier** : `products/models.py` (ajouter après `ProductVariant`)

```python
class StockMovement(models.Model):
    class MovementType(models.TextChoices):
        RESERVATION = "reservation", "Réservation (commande)"
        RELEASE     = "release",     "Libération (annulation)"
        CORRECTION  = "correction",  "Correction manuelle"
        INITIAL     = "initial",     "Stock initial"

    product         = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="stock_movements"
    )
    order           = models.ForeignKey(
        "orders.Order", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="stock_movements"
    )
    quantity_change = models.IntegerField(
        verbose_name="Variation de stock",
        help_text="Négatif = sortie, positif = entrée"
    )
    movement_type   = models.CharField(
        max_length=20, choices=MovementType.choices
    )
    notes           = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["product", "created_at"]),
        ]

    def __str__(self) -> str:
        sign = "+" if self.quantity_change > 0 else ""
        return f"{self.product.name} {sign}{self.quantity_change} ({self.movement_type})"
```

**Intégration dans `orders/services/create_order.py`** :

Après la décrémentation du stock, créer un `StockMovement` hors transaction :
```python
# Hors transaction, pour ne pas bloquer le commit critique
from products.models import StockMovement
StockMovement.objects.create(
    product=product,
    order=order,
    quantity_change=-item["quantity"],
    movement_type=StockMovement.MovementType.RESERVATION,
)
```

---

## Étape 1.6 — SellerProfile : champs manquants

**Fichier** : `accounts/models.py`

Ajouter sur `SellerProfile` :
```python
bio            = models.TextField(blank=True, verbose_name="Biographie")
avatar         = models.ImageField(
    upload_to="sellers/avatars/", null=True, blank=True,
    verbose_name="Photo de profil"
)
delivery_zones = models.CharField(
    max_length=500, blank=True,
    verbose_name="Zones de livraison",
    help_text="Ex: Bamako, Kati, Koulikoro"
)
```

---

## Étape 1.7 — Admin complet

**Fichier** : `flash_sales/admin.py`

```python
from django.contrib import admin
from .models import FlashSale

@admin.register(FlashSale)
class FlashSaleAdmin(admin.ModelAdmin):
    list_display  = ("title", "owner", "status", "start_time", "end_time", "created_at")
    list_filter   = ("status",)
    search_fields = ("title", "owner__business_name", "public_slug")
    date_hierarchy = "start_time"
    readonly_fields = ("public_slug", "created_at", "updated_at")
    fieldsets = (
        ("Informations", {"fields": ("title", "description", "cover_image", "public_slug")}),
        ("Planification", {"fields": ("owner", "start_time", "end_time", "status")}),
        ("Paramètres", {"fields": ("delivery_zone", "max_orders")}),
        ("Dates", {"fields": ("created_at", "updated_at")}),
    )
```

**Fichier** : `products/admin.py`

```python
from django.contrib import admin
from .models import Product, ProductMedia, ProductVariant, StockMovement

class ProductMediaInline(admin.TabularInline):
    model = ProductMedia
    extra = 1

class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display  = ("name", "flash_sale", "price", "stock_available", "stock_initial", "is_active")
    list_filter   = ("is_active", "flash_sale__status")
    search_fields = ("name", "flash_sale__title")
    inlines       = [ProductMediaInline, ProductVariantInline]

@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display  = ("product", "quantity_change", "movement_type", "order", "created_at")
    list_filter   = ("movement_type",)
    readonly_fields = ("created_at",)
```

---

## Étape 1.8 — Générer et appliquer toutes les migrations

```bash
python manage.py makemigrations accounts --name="add_seller_profile_fields"
python manage.py makemigrations flash_sales --name="extend_statuts_and_fields"
python manage.py makemigrations products --name="add_product_fields_and_media"
python manage.py migrate
```

---

## Checklist Finale P1

- [ ] `python manage.py migrate` sans erreur
- [ ] `python manage.py check` sans warning
- [ ] `FlashSaleStatus` contient 6 choix
- [ ] `FlashSale.description`, `cover_image`, `delivery_zone`, `max_orders` présents
- [ ] `Product.stock_initial`, `stock_available`, `description`, `unit`, `characteristics`, `display_order` présents
- [ ] `ProductMedia`, `ProductVariant`, `StockMovement` présents dans l'admin
- [ ] `SellerProfile.bio`, `avatar`, `delivery_zones` présents
- [ ] `create_order()` crée un `StockMovement` à chaque commande
- [ ] Tests existants passent toujours : `pytest --ds=config.settings.test`
