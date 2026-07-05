# Workflow P3 — LIVE Workflow Complet
> Phase 3 · Durée estimée : ~2 semaines  
> Prérequis : P0 + P1 + P2 terminées

---

## Objectif

Automatiser le cycle de vie des ventes (Celery), améliorer le dashboard LIVE (Tailwind, countdown, badge pulsant), créer le calendrier public, ajouter l'API flash sales publique. La boucle Live Commerce complète doit fonctionner de bout en bout.

---

## Étape 3.1 — Celery Tasks (auto-open / auto-close)

**Nouveau fichier** : `flash_sales/tasks.py`

```python
"""Tâches Celery pour la gestion automatique des ventes flash."""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="flash_sales.auto_open_scheduled_sales", ignore_result=True)
def auto_open_scheduled_sales() -> None:
    """Ouvre automatiquement les ventes dont start_time est atteint."""
    from flash_sales.models import FlashSale, FlashSaleStatus

    now      = timezone.now()
    to_open  = FlashSale.objects.filter(
        status=FlashSaleStatus.SCHEDULED,
        start_time__lte=now,
        end_time__gt=now,
    )
    count = 0
    for sale in to_open:
        try:
            sale.open_sale()
            count += 1
            logger.info("FlashSale %s [%s] → LIVE (auto)", sale.pk, sale.title)
        except Exception as exc:
            logger.error("Erreur ouverture auto FlashSale %s : %s", sale.pk, exc)

    if count:
        logger.info("auto_open_scheduled_sales : %d vente(s) ouvertes", count)


@shared_task(name="flash_sales.auto_close_live_sales", ignore_result=True)
def auto_close_live_sales() -> None:
    """Ferme automatiquement les ventes dont end_time est atteint."""
    from flash_sales.models import FlashSale, FlashSaleStatus

    now      = timezone.now()
    to_close = FlashSale.objects.filter(
        status=FlashSaleStatus.LIVE,
        end_time__lte=now,
    )
    count = 0
    for sale in to_close:
        try:
            sale.close_sale()
            count += 1
            logger.info("FlashSale %s [%s] → CLOSED (auto)", sale.pk, sale.title)
        except Exception as exc:
            logger.error("Erreur fermeture auto FlashSale %s : %s", sale.pk, exc)

    if count:
        logger.info("auto_close_live_sales : %d vente(s) fermée(s)", count)
```

**Tests** : `flash_sales/tests.py` — tester les deux tasks avec mock `timezone.now()`.

---

## Étape 3.2 — Dashboard LIVE : Refonte Tailwind

**Fichier** : `templates/orders/dashboard.html` — refonte complète.

Structure cible :
```
┌────────────────────────────────────────────┐
│  ● LIVE  [Titre vente]         [00:45:23]  │  ← navbar + countdown Alpine
├────────────────────────────────────────────┤
│  [Commandes: 24]  [Articles: 47]  [125k]  │  ← KPI cards
├────────────────────────────────────────────┤
│  STOCK CRITIQUE : Sac rouge → 2 restants  │  ← alerte stock
├────────────────────────────────────────────┤
│  Nouvelles commandes ─────────────────────  │
│  [Aïssata Coulibaly · 2x Sac · 10 000 F]  │  ← order card
│    [✓ Confirmer]  [🚚 Livrer]  [✗ Annuler] │
│  ─────────────────────────────────────────  │
│  ... (HTMX polling 3s)                     │
├────────────────────────────────────────────┤
│  [🔴 Fermer la vente]                       │
└────────────────────────────────────────────┘
```

Éléments Alpine.js à intégrer :

```html
<!-- Timer countdown -->
<div
  x-data="{
    end: new Date('{{ flash_sale.end_time.isoformat }}'),
    now: new Date(),
    get remaining() {
      const diff = Math.max(0, this.end - this.now);
      const h = Math.floor(diff / 3600000);
      const m = Math.floor((diff % 3600000) / 60000);
      const s = Math.floor((diff % 60000) / 1000);
      return String(h).padStart(2,'0') + ':' + String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
    },
    get isUrgent() { return (this.end - this.now) < 300000; }  // < 5 min
  }"
  x-init="setInterval(() => now = new Date(), 1000)"
  class="font-mono text-2xl font-bold"
  :class="isUrgent ? 'text-red-500 animate-pulse' : 'text-gray-900'"
>
  <span x-text="remaining">--:--:--</span>
</div>

<!-- Badge LIVE pulsant -->
<span class="inline-flex items-center gap-1.5 bg-red-600 text-white text-xs font-bold px-2 py-1 rounded-full">
  <span class="w-2 h-2 rounded-full bg-white live-pulse"></span>
  LIVE
</span>

<!-- Modal fermeture vente -->
<div x-data="{ open: false }">
  <button @click="open = true" class="w-full bg-red-600 hover:bg-red-700 text-white font-bold py-4 rounded-xl mt-4">
    Fermer la vente
  </button>
  <div x-show="open" x-cloak class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
    <div class="bg-white rounded-2xl p-6 max-w-sm w-full shadow-xl">
      <h3 class="text-lg font-bold mb-2">Fermer la vente ?</h3>
      <p class="text-gray-600 text-sm mb-4">Plus aucune commande ne sera acceptée. Cette action est définitive.</p>
      <div class="flex gap-3">
        <button @click="open = false" class="flex-1 border border-gray-300 text-gray-700 font-semibold py-3 rounded-xl">
          Annuler
        </button>
        <form method="POST" action="{% url 'flash_sales:close' pk=flash_sale.pk %}" class="flex-1">
          {% csrf_token %}
          <button type="submit" class="w-full bg-red-600 text-white font-bold py-3 rounded-xl">
            Fermer
          </button>
        </form>
      </div>
    </div>
  </div>
</div>
```

---

## Étape 3.3 — Page commande client : Refonte Tailwind

**Fichier** : `templates/orders/client_order.html` — refonte complète.

Structure cible :
```
┌──────────────────────────────┐
│  HAYAFLASH               ●LIVE│
├──────────────────────────────┤
│  [Image produit]              │
│  Sac à main cuir rouge        │
│  10 000 FCFA  •  8 restants  │
├──────────────────────────────┤
│  Votre nom *                  │
│  [________________________]   │
│                               │
│  Téléphone *                  │
│  [________________________]   │
│                               │
│  Quantité                     │
│  [ - ]  [1]  [ + ]           │
│                               │
│  Adresse de livraison *       │
│  [________________________]   │
│  [📍 Détecter ma position]   │
│                               │
│  Commentaire (optionnel)      │
│  [________________________]   │
│                               │
│  ┌──────────────────────────┐ │
│  │    COMMANDER → 10 000F  │ │  ← CTA rouge, full-width, 56px
│  └──────────────────────────┘ │
│                               │
│  Commande via HayaFlash       │
└──────────────────────────────┘
```

Points critiques UX :
- Compteur quantité +/- avec Alpine.js (jamais moins que 1, jamais plus que stock_available)
- GPS : feedback visuel (spinner → succès vert → adresse suggérée)
- CTA désactivé pendant l'envoi (prevent double-submit)
- Toast de succès après confirmation

---

## Étape 3.4 — Calendrier Public des Ventes

**Nouveau fichier** : `flash_sales/public_views.py`

```python
from django.shortcuts import render
from django.utils import timezone
from .models import FlashSale, FlashSaleStatus


def public_flash_sale_calendar(request):
    """Page publique : liste des ventes programmées et en cours."""
    now = timezone.now()
    live_sales = FlashSale.objects.filter(
        status=FlashSaleStatus.LIVE
    ).select_related("owner").prefetch_related("products").order_by("end_time")

    scheduled_sales = FlashSale.objects.filter(
        status=FlashSaleStatus.SCHEDULED,
        start_time__gte=now,
    ).select_related("owner").order_by("start_time")[:20]

    return render(request, "flash_sales/public_calendar.html", {
        "live_sales": live_sales,
        "scheduled_sales": scheduled_sales,
    })
```

**Nouveau template** : `templates/flash_sales/public_calendar.html`

Design : page publique épurée, ventes LIVE en haut (badge rouge), puis ventes programmées avec countdown, partage WhatsApp.

**URL** : `path("ventes/", views.public_flash_sale_calendar, name="flash_sale_calendar")`

---

## Étape 3.5 — API Flash Sales Publiques

**Nouveau fichier** : `flash_sales/api.py`

```python
"""API REST publique pour les ventes flash."""
from __future__ import annotations

from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from .models import FlashSale, FlashSaleStatus
from .serializers import FlashSalePublicSerializer, FlashSaleDetailSerializer


@api_view(["GET"])
def flash_sale_list_api(request: Request) -> Response:
    """GET /api/v1/flash-sales/ — ventes scheduled + live."""
    from django.utils import timezone
    sales = FlashSale.objects.filter(
        status__in=[FlashSaleStatus.SCHEDULED, FlashSaleStatus.LIVE]
    ).select_related("owner").order_by("start_time")
    serializer = FlashSalePublicSerializer(sales, many=True, context={"request": request})
    return Response(serializer.data)


@api_view(["GET"])
def flash_sale_detail_api(request: Request, slug: str) -> Response:
    """GET /api/v1/flash-sales/<slug>/ — détail + produits."""
    try:
        sale = FlashSale.objects.prefetch_related("products__media").get(public_slug=slug)
    except FlashSale.DoesNotExist:
        return Response({"error": "not_found", "detail": "Vente introuvable."}, status=404)

    serializer = FlashSaleDetailSerializer(sale, context={"request": request})
    return Response(serializer.data)
```

**Nouveau fichier** : `flash_sales/serializers.py`

```python
from rest_framework import serializers
from .models import FlashSale
from products.models import Product, ProductMedia


class ProductMediaSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    class Meta:
        model  = ProductMedia
        fields = ["media_type", "file_url", "video_url", "order"]
    def get_file_url(self, obj):
        request = self.context.get("request")
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None


class ProductPublicSerializer(serializers.ModelSerializer):
    media = ProductMediaSerializer(many=True, read_only=True)
    is_available = serializers.BooleanField(read_only=True)
    class Meta:
        model  = Product
        fields = ["id", "name", "description", "price", "stock_available", "unit", "is_available", "display_order", "media"]


class FlashSalePublicSerializer(serializers.ModelSerializer):
    seller_name = serializers.CharField(source="owner.business_name", read_only=True)
    seller_slug = serializers.CharField(source="owner.public_slug", read_only=True)
    class Meta:
        model  = FlashSale
        fields = ["id", "title", "description", "public_slug", "status", "start_time", "end_time",
                  "cover_image", "delivery_zone", "seller_name", "seller_slug"]


class FlashSaleDetailSerializer(FlashSalePublicSerializer):
    products = ProductPublicSerializer(many=True, read_only=True)
    class Meta(FlashSalePublicSerializer.Meta):
        fields = FlashSalePublicSerializer.Meta.fields + ["products"]
```

**Ajouter dans `config/api_urls.py`** :
```python
from flash_sales.api import flash_sale_list_api, flash_sale_detail_api
path("flash-sales/",         flash_sale_list_api,   name="api-flash-sales-list"),
path("flash-sales/<slug:slug>/", flash_sale_detail_api, name="api-flash-sales-detail"),
```

---

## Checklist Finale P3

- [ ] `celery -A config worker` démarre sans erreur
- [ ] `celery -A config beat` démarre sans erreur
- [ ] Une vente passe SCHEDULED → LIVE automatiquement à `start_time`
- [ ] Une vente passe LIVE → CLOSED automatiquement à `end_time`
- [ ] Badge "● LIVE" rouge visible et pulsant sur le dashboard
- [ ] Timer countdown mis à jour chaque seconde
- [ ] Nouvelle commande visible en < 5s (HTMX polling 3s)
- [ ] Page client refaite en Tailwind, fonctionnelle sur 375px
- [ ] `/ventes/` liste les ventes programmées et en cours
- [ ] `GET /api/v1/flash-sales/` retourne les ventes actives
- [ ] `GET /api/v1/flash-sales/<slug>/` retourne les produits
