# HayaFlash — Phase 7 : Pro Features & Administration Plateforme
> Workflow exécutable par Claude Code / Cowork
> Durée estimée : 2-3 semaines
> Mis à jour le 2026-07-13 (version corrigée — alignée sur le code réel)

---

## PRÉREQUIS

- Toutes les phases P0 à P6 terminées ✅
- `python manage.py check` passe sans erreur
- `python manage.py runserver --settings=config.settings.dev` fonctionne

### Rappels conventions projet (à respecter absolument)

```python
# INTERDIT — GuardedOrderManager lève RuntimeError
Order.objects.create(...)

# OBLIGATOIRE pour créer une commande
Order.service_objects.create(...)
# ou passer par la fonction de service
create_order(data: dict)  # data est un dict unique, pas des paramètres individuels

# Accès au profil vendeur depuis request
seller = request.user.seller_profile  # related_name="seller_profile" (avec underscore)

# Nom namespace URL flash_sales
{% url 'flash_sales:detail' pk=sale.pk %}
{% url 'flash_sales:interests' %}

# PaymentStatus choices réels : pending / success / failed / cancelled / expired
# PAS "completed" — c'est "success"
```

---

## ÉTAPE 1 — QR Code de partage

### Priorité : Moyenne-haute (marketing vendeur)

### 1.1 Installation

```bash
pip install qrcode
# Ajouter dans requirements.txt :
# qrcode==7.4.2
# Pillow est déjà présent (pillow==12.2.0)
```

### 1.2 Service QR Code

**Fichier à créer : `analytics/services/qrcode.py`**

```python
from __future__ import annotations

import base64
from io import BytesIO

import qrcode
from qrcode.image.pure import PyPNGImage

from analytics.services.share_links import get_public_base_url, flash_sale_public_path


def generate_flash_sale_qr_b64(flash_sale, request=None) -> str:
    """
    Génère un QR Code pour l'URL publique d'une vente flash.
    Retourne l'image encodée en base64 (PNG) pour affichage direct via data URI.
    Utilise get_public_base_url() — aligné sur le reste du projet.
    """
    path = flash_sale_public_path(flash_sale.public_slug)
    base_url = get_public_base_url(request)
    url = f"{base_url}{path}"

    qr = qrcode.QRCode(version=1, box_size=8, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(image_factory=PyPNGImage)

    buffer = BytesIO()
    img.save(buffer)
    return base64.b64encode(buffer.getvalue()).decode()
```

### 1.3 Vue QR Code

**Fichier à modifier : `analytics/views.py`** (ajouter à la fin, avec les imports nécessaires)

```python
@login_required
def flash_sale_qr_view(request, slug: str):
    """Génère le QR Code d'une vente flash (JSON, auth vendeur requis)."""
    from django.http import JsonResponse
    from flash_sales.models import FlashSale
    from analytics.services.qrcode import generate_flash_sale_qr_b64

    flash_sale = get_object_or_404(
        FlashSale,
        public_slug=slug,
        owner=request.user.seller_profile,  # related_name correct
    )
    qr_b64 = generate_flash_sale_qr_b64(flash_sale, request)
    return JsonResponse({"qr": qr_b64, "slug": slug})
```

**URL à ajouter dans `analytics/urls.py` :**

```python
path(
    "f/<slug:slug>/qrcode/",
    views.flash_sale_qr_view,
    name="flash_sale_qrcode",
),
```

> Note : La vue est dans `analytics/` car c'est l'app qui gère les pages publiques
> `/f/<slug>/`. Elle est protégée par `@login_required` et vérifie que le vendeur
> est bien propriétaire de la vente.

### 1.4 Partial template QR Code

**Fichier à créer : `templates/flash_sales/partials/_qr_modal.html`**

```html
<!-- Bouton + Modal QR Code pour le dashboard vendeur -->
<!-- Usage : inclure dans flash_sales/detail.html -->
<!-- x-data doit être sur un parent ou on utilise un composant Alpine dédié -->

<div x-data="{
    open: false,
    qr: '',
    loading: false,
    fetchQR() {
        this.loading = true;
        fetch('{% url "flash_sale_qrcode" slug=sale.public_slug %}')
            .then(r => r.json())
            .then(data => { this.qr = data.qr; this.open = true; this.loading = false; })
            .catch(() => { this.loading = false; alert('Erreur génération QR Code'); });
    }
}">
    <button @click="fetchQR()"
            :disabled="loading"
            class="inline-flex items-center gap-2 px-4 py-2 bg-gray-100 text-gray-700
                   rounded-xl text-sm font-medium hover:bg-gray-200 transition-colors">
        <i data-lucide="qr-code" class="w-4 h-4"></i>
        <span x-text="loading ? 'Génération...' : 'QR Code'"></span>
    </button>

    <!-- Modal -->
    <div x-show="open"
         x-cloak
         x-transition
         class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
        <div class="bg-white rounded-2xl p-6 max-w-xs w-full shadow-xl"
             @click.outside="open = false">
            <h3 class="text-base font-bold text-gray-900 text-center mb-4">
                Scannez pour commander
            </h3>
            <img :src="`data:image/png;base64,${qr}`"
                 alt="QR Code vente flash"
                 class="mx-auto w-56 h-56 rounded-lg">
            <p class="text-xs text-gray-400 text-center mt-3">
                Idéal pour vos lives TikTok / Facebook
            </p>
            <button @click="open = false"
                    class="mt-4 w-full py-3 bg-primary text-white font-bold rounded-xl text-sm">
                Fermer
            </button>
        </div>
    </div>
</div>
```

**Dans `templates/flash_sales/detail.html`, ajouter l'include dans la section actions :**

```html
{% include "flash_sales/partials/_qr_modal.html" with sale=sale %}
```

### 1.5 Web Share API sur page publique

**Fichier à modifier : `templates/analytics/flash_sale_public.html`**
(C'est bien ce fichier — pas `flash_sales/public_detail.html`)

Ajouter un bouton "Partager" avec Web Share API + fallback WhatsApp, **en complément** du bouton WhatsApp existant (ne pas remplacer — le bouton WhatsApp est tracké via `ShareEvent`).

```html
<!-- Ajouter ce bouton uniquement sur les navigateurs qui supportent Web Share -->
<button x-data
        x-show="'share' in navigator"
        @click="
            navigator.share({
                title: '{{ sale.title|escapejs }}',
                text: '🔥 Vente flash sur HayaFlash !',
                url: window.location.href
            }).catch(() => {})
        "
        class="inline-flex items-center gap-2 px-4 py-3 bg-gray-100 text-gray-700
               rounded-xl text-sm font-medium w-full justify-center">
    <i data-lucide="share-2" class="w-4 h-4"></i>Partager
</button>
```

> Ne pas supprimer le bouton WhatsApp existant — il est tracké via `ShareEvent`
> et `record_whatsapp_share()`. Le bouton Web Share est un complément.

---

## ÉTAPE 2 — Vocal Client : audio réel (nouveau champ Delivery)

### Priorité : Haute (impact UX direct)

> ⚠️ La géolocalisation GPS est **déjà implémentée** dans le projet :
> `Delivery` a déjà `latitude`, `longitude`, `geo_accuracy`, `geo_method`.
> Le formulaire dans `flash_sale_public.html` capture déjà la position via
> `navigator.geolocation`. Cette étape n'ajoute que l'audio.

### 2.1 Nouveau champ `audio_note` sur Delivery

**Fichier à modifier : `delivery/models.py`**

Ajouter le champ après `delivery_notes` :

```python
audio_note = models.FileField(
    upload_to="delivery/audio/%Y/%m/%d/",
    null=True,
    blank=True,
    verbose_name="Note vocale client",
    help_text="Enregistrement audio de la localisation du client (WebM/OGG)",
)
```

**Migration :**

```bash
python manage.py makemigrations delivery --name="add_audio_note_to_delivery"
python manage.py migrate
```

### 2.2 Intégration dans `create_order()`

**Fichier à modifier : `orders/services/create_order.py`**

La fonction `create_order(data: dict)` conserve sa signature. L'audio est géré
dans `_create_delivery_for_order()` qui délègue à `delivery/services/delivery.py`.

**Fichier à modifier : `delivery/services/delivery.py`** — fonction `create_delivery_for_order` :

```python
def create_delivery_for_order(*, order, delivery_data: dict):
    """
    Crée la livraison associée à une commande.
    delivery_data peut contenir : address_text, latitude, longitude,
    geo_accuracy, geo_method, delivery_notes, audio_file (InMemoryUploadedFile).
    """
    from delivery.models import Delivery

    audio_file = delivery_data.pop("audio_file", None)

    delivery = Delivery.objects.create(
        order=order,
        address_text=delivery_data.get("address_text", ""),
        latitude=delivery_data.get("latitude"),
        longitude=delivery_data.get("longitude"),
        geo_accuracy=delivery_data.get("geo_accuracy"),
        geo_method=delivery_data.get("geo_method", Delivery.GeoMethod.MANUAL),
        delivery_notes=delivery_data.get("delivery_notes", ""),
        cod_amount=compute_order_total(order),
    )

    if audio_file:
        delivery.audio_note.save(
            f"order_{order.pk}_localisation.webm",
            audio_file,
            save=True,
        )

    return delivery
```

> Vérifier la signature existante de `create_delivery_for_order` avant de modifier —
> adapter selon ce qui existe déjà dans le fichier.

### 2.3 Vue commande — réception de l'audio

**Fichier à modifier : `orders/services/client_order.py`** (ou la vue qui traite le POST)

Ajouter dans le mapping des données de livraison :

```python
audio_file = request.FILES.get("audio_note")  # fichier uploadé
delivery_data["audio_file"] = audio_file  # passé à create_delivery_for_order
```

Le formulaire doit avoir `enctype="multipart/form-data"`.

### 2.4 Formulaire client — bouton enregistrement audio

**Fichier à modifier : `templates/analytics/flash_sale_public.html`**
(C'est le bon fichier — le formulaire de commande est là, pas dans `client_order.html`)

Ajouter dans la section du formulaire de commande (dans Alpine.js `x-data`) :

```javascript
// Enregistrement audio
isRecording: false,
audioUrl: null,
mediaRecorder: null,
audioChunks: [],

startRecording() {
    if (!navigator.mediaDevices) {
        alert("Enregistrement audio non disponible sur ce navigateur.");
        return;
    }
    navigator.mediaDevices.getUserMedia({ audio: true })
        .then(stream => {
            this.audioChunks = [];
            this.mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
            this.mediaRecorder.ondataavailable = e => this.audioChunks.push(e.data);
            this.mediaRecorder.onstop = () => {
                const blob = new Blob(this.audioChunks, { type: 'audio/webm' });
                this.audioUrl = URL.createObjectURL(blob);
                // Injecter dans l'input file caché
                const file = new File([blob], 'localisation.webm', { type: 'audio/webm' });
                const dt = new DataTransfer();
                dt.items.add(file);
                document.getElementById('audio-note-input').files = dt.files;
                stream.getTracks().forEach(t => t.stop());
            };
            this.mediaRecorder.start();
            this.isRecording = true;
        })
        .catch(() => alert("Microphone inaccessible."));
},
stopRecording() {
    this.mediaRecorder?.stop();
    this.isRecording = false;
},
clearAudio() {
    this.audioUrl = null;
    document.getElementById('audio-note-input').value = '';
},
```

HTML à ajouter dans le formulaire :

```html
<input type="hidden" id="audio-note-input" name="audio_note">

<div class="mt-3">
    <button type="button"
            x-show="!isRecording && !audioUrl"
            @click="startRecording()"
            class="w-full inline-flex items-center justify-center gap-2 px-4 py-3
                   bg-gray-100 text-gray-700 rounded-xl text-sm font-medium">
        <i data-lucide="mic" class="w-4 h-4"></i>
        Dicter ma localisation (audio)
    </button>
    <div x-show="isRecording"
         class="flex items-center gap-3 p-3 bg-red-50 rounded-xl">
        <span class="w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse"></span>
        <span class="text-sm text-red-600 flex-1">Enregistrement en cours…</span>
        <button type="button" @click="stopRecording()"
                class="text-xs font-bold text-red-600 border border-red-300
                       rounded-lg px-3 py-1">
            Arrêter
        </button>
    </div>
    <div x-show="audioUrl" class="p-3 bg-green-50 rounded-xl">
        <p class="text-xs text-gray-500 mb-2">🎤 Votre message vocal :</p>
        <audio controls :src="audioUrl" class="w-full h-8"></audio>
        <button type="button" @click="clearAudio()"
                class="mt-2 text-xs text-red-500 hover:underline">
            Supprimer
        </button>
    </div>
</div>
```

> ⚠️ L'input `audio_note` est un `type="hidden"` qui reçoit le fichier via `DataTransfer`.
> Le form doit avoir `enctype="multipart/form-data"` pour que le fichier soit transmis.

### 2.5 Dashboard livraisons — affichage audio + carte

**Fichier à modifier : `templates/delivery/deliveries_dashboard.html`** ou le partial `delivery_row.html`

```html
<!-- Après l'affichage de address_text existant -->

{% if delivery.audio_note %}
<div class="mt-2 p-3 bg-gray-50 rounded-xl">
    <p class="text-xs text-gray-400 mb-1 flex items-center gap-1">
        <i data-lucide="mic" class="w-3 h-3"></i>Message vocal du client
    </p>
    <audio controls class="w-full h-8">
        <source src="{{ delivery.audio_note.url }}" type="audio/webm">
    </audio>
</div>
{% endif %}

{% if delivery.latitude and delivery.longitude %}
<div class="mt-2 flex gap-2">
    <a href="{{ delivery.get_maps_url }}" target="_blank" rel="noopener"
       class="inline-flex items-center gap-1 text-xs text-blue-600
              hover:underline px-2 py-1 bg-blue-50 rounded-lg">
        <i data-lucide="map-pin" class="w-3 h-3"></i>Google Maps
    </a>
    <a href="{{ delivery.get_waze_url }}" target="_blank" rel="noopener"
       class="inline-flex items-center gap-1 text-xs text-blue-600
              hover:underline px-2 py-1 bg-blue-50 rounded-lg">
        <i data-lucide="navigation" class="w-3 h-3"></i>Waze
    </a>
</div>
{% endif %}
```

> Les méthodes `get_maps_url()` et `get_waze_url()` existent déjà sur `Delivery`.
> Pas besoin d'intégrer Leaflet — Google Maps + Waze couvrent le cas d'usage Mali.

---

## ÉTAPE 3 — Suivi des intérêts par vente (vue par vente individuelle)

### Priorité : Moyenne

> La vue `sale_interests_view` existe déjà sur `/seller/flash-sales/interests/`
> et affiche TOUTES les réservations groupées par vente.
> Cette étape ajoute une vue par vente individuelle (`<pk>/interests/`).

### 3.1 Vue par vente

**Fichier à modifier : `flash_sales/views.py`** — ajouter après `sale_interests_view` :

```python
@login_required
def flash_sale_interests_detail_view(request, pk: int):
    """Réservations d'intérêt pour une vente spécifique."""
    seller = _get_seller(request)
    flash_sale = get_object_or_404(FlashSale, pk=pk, owner=seller)
    interests = flash_sale.interests.order_by("-created_at")
    return render(request, "flash_sales/interests_detail.html", {
        "flash_sale": flash_sale,
        "interests": interests,
        "total": interests.count(),
    })
```

**URL à ajouter dans `flash_sales/urls.py`** (dans `urlpatterns`, après les routes existantes) :

```python
path("<int:pk>/interests/", views.flash_sale_interests_detail_view, name="interests_detail"),
```

### 3.2 Template par vente

**Fichier à créer : `templates/flash_sales/interests_detail.html`**

```html
{% extends "base.html" %}
{% block title %}Réservations — {{ flash_sale.title }}{% endblock %}

{% block content %}
<div class="max-w-2xl mx-auto px-4 py-8">

    <div class="flex items-center gap-3 mb-6">
        <a href="{% url 'flash_sales:detail' pk=flash_sale.pk %}"
           class="text-gray-400 hover:text-gray-600 transition-colors">
            <i data-lucide="arrow-left" class="w-5 h-5"></i>
        </a>
        <div>
            <h1 class="text-xl font-black text-gray-900">Réservations</h1>
            <p class="text-sm text-gray-400">{{ flash_sale.title }}</p>
        </div>
        {% if total > 0 %}
        <span class="ml-auto bg-primary/10 text-primary font-bold text-sm
                     px-3 py-1.5 rounded-full">
            {{ total }}
        </span>
        {% endif %}
    </div>

    {% if not interests %}
    <div class="text-center py-16 text-gray-400">
        <i data-lucide="bell-off" class="w-10 h-10 mx-auto mb-3 opacity-40"></i>
        <p class="font-medium">Aucune réservation</p>
    </div>
    {% else %}
    <div class="space-y-2">
        {% for interest in interests %}
        <div class="bg-white rounded-2xl border border-gray-100 shadow-sm
                    flex items-center gap-3 px-4 py-3">
            <div class="w-9 h-9 bg-gray-100 rounded-full flex items-center
                        justify-center shrink-0 font-bold text-gray-500 text-sm">
                {{ interest.name|default:"?"|slice:":1"|upper }}
            </div>
            <div class="flex-1 min-w-0">
                {% if interest.name %}
                <p class="text-sm font-semibold text-gray-800 truncate">
                    {{ interest.name }}
                </p>
                {% endif %}
                <p class="text-sm text-gray-500">{{ interest.phone }}</p>
            </div>
            <div class="flex items-center gap-2 shrink-0">
                <span class="text-xs text-gray-400">
                    {{ interest.created_at|date:"d/m H:i" }}
                </span>
                <a href="https://wa.me/{{ interest.phone|cut:' '|cut:'+' }}?text={{ flash_sale.title|urlencode }}%20est%20ouvert%20!"
                   target="_blank" rel="noopener"
                   class="p-1.5 bg-green-50 text-green-600 rounded-lg
                          hover:bg-green-100 transition-colors"
                   title="Contacter via WhatsApp">
                    <i data-lucide="message-circle" class="w-4 h-4"></i>
                </a>
            </div>
        </div>
        {% endfor %}
    </div>
    {% endif %}
</div>
{% endblock %}
```

### 3.3 Compteur sur la carte de vente

**Fichier à modifier : `templates/flash_sales/detail.html`** — ajouter le badge intérêts :

```html
{% with interest_count=sale.interests.count %}
{% if interest_count > 0 %}
<a href="{% url 'flash_sales:interests_detail' pk=sale.pk %}"
   class="inline-flex items-center gap-1.5 text-xs font-medium text-orange-600
          bg-orange-50 px-3 py-1.5 rounded-full hover:bg-orange-100 transition-colors">
    <i data-lucide="bell" class="w-3 h-3"></i>
    {{ interest_count }} réservation{{ interest_count|pluralize }}
</a>
{% endif %}
{% endwith %}
```

---

## ÉTAPE 4 — Reporting & Analytics (MEDIUM / PRO)

### Priorité : Haute (différenciation plans payants)

### 4.1 Service reporting

**Fichier à créer : `analytics/services/reporting.py`**

```python
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Sum, F, ExpressionWrapper, DecimalField
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone

from orders.models import Order, OrderItem, OrderStatus


def get_flash_sale_stats(flash_sale_id: int) -> dict:
    """Statistiques détaillées pour une vente flash (commandes livrées)."""
    delivered_items = OrderItem.objects.filter(
        order__flash_sale_id=flash_sale_id,
        order__status=OrderStatus.DELIVERED,
    )
    revenue_expr = ExpressionWrapper(
        F("price_snapshot") * F("quantity"),  # champ correct : price_snapshot
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    agg = delivered_items.aggregate(
        total_quantity=Sum("quantity"),
        total_revenue=Sum(revenue_expr),
        total_orders=Count("order_id", distinct=True),
        unique_customers=Count("order__customer_phone", distinct=True),
    )
    return {
        "total_orders": agg["total_orders"] or 0,
        "total_quantity": agg["total_quantity"] or 0,
        "total_revenue": agg["total_revenue"] or 0,
        "unique_customers": agg["unique_customers"] or 0,
    }


def get_revenue_timeline(seller_id: int, days: int = 30) -> list[dict]:
    """
    Timeline de CA par jour sur `days` jours.
    Groupe les OrderItems par date de commande — pas les FlashSales.
    """
    start_date = timezone.now() - timedelta(days=days)
    revenue_expr = ExpressionWrapper(
        F("price_snapshot") * F("quantity"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    rows = (
        OrderItem.objects.filter(
            order__flash_sale__owner_id=seller_id,
            order__status=OrderStatus.DELIVERED,
            order__created_at__gte=start_date,
        )
        .annotate(day=TruncDate("order__created_at"))
        .values("day")
        .annotate(revenue=Sum(revenue_expr), orders=Count("order_id", distinct=True))
        .order_by("day")
    )
    return [
        {"day": str(r["day"]), "revenue": float(r["revenue"] or 0), "orders": r["orders"]}
        for r in rows
    ]


def get_revenue_timeline_monthly(seller_id: int) -> list[dict]:
    """Timeline mensuelle sur 12 mois (PRO)."""
    start_date = timezone.now() - timedelta(days=365)
    revenue_expr = ExpressionWrapper(
        F("price_snapshot") * F("quantity"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    rows = (
        OrderItem.objects.filter(
            order__flash_sale__owner_id=seller_id,
            order__status=OrderStatus.DELIVERED,
            order__created_at__gte=start_date,
        )
        .annotate(month=TruncMonth("order__created_at"))
        .values("month")
        .annotate(revenue=Sum(revenue_expr), orders=Count("order_id", distinct=True))
        .order_by("month")
    )
    return [
        {"month": r["month"].strftime("%Y-%m"), "revenue": float(r["revenue"] or 0), "orders": r["orders"]}
        for r in rows
    ]


def get_top_products(seller_id: int, limit: int = 5) -> list[dict]:
    """Top produits livrés par quantité."""
    revenue_expr = ExpressionWrapper(
        F("price_snapshot") * F("quantity"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    rows = (
        OrderItem.objects.filter(
            order__flash_sale__owner_id=seller_id,
            order__status=OrderStatus.DELIVERED,
        )
        .values("product_name_snapshot")  # snapshot — pas de FK nullable
        .annotate(
            total_sold=Sum("quantity"),
            total_revenue=Sum(revenue_expr),
        )
        .order_by("-total_sold")[:limit]
    )
    return list(rows)


def get_sales_by_flash(seller_id: int) -> list[dict]:
    """Détail CA + commandes par vente flash terminée (PRO)."""
    from flash_sales.models import FlashSale, FlashSaleStatus

    revenue_expr = ExpressionWrapper(
        F("items__price_snapshot") * F("items__quantity"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    return list(
        FlashSale.objects.filter(
            owner_id=seller_id,
            status__in=[FlashSaleStatus.COMPLETED, FlashSaleStatus.CLOSED],
        )
        .annotate(
            order_count=Count("orders", filter=~__import__("django.db.models", fromlist=["Q"]).Q(orders__status="cancelled")),
            revenue=Sum(revenue_expr, filter=__import__("django.db.models", fromlist=["Q"]).Q(orders__status=OrderStatus.DELIVERED)),
        )
        .values("pk", "title", "start_time", "order_count", "revenue")
        .order_by("-start_time")
    )
```

> Note : `get_sales_by_flash` utilise une annotation complexe. Simplifier si nécessaire
> en faisant deux requêtes séparées pour éviter des agrégations imbriquées.

### 4.2 Vue analytics vendeur

**Ajouter à `flash_sales/views.py`** (garde la logique vendeur ensemble)
ou créer un fichier dédié `flash_sales/analytics_views.py`.

```python
import json
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from analytics.services.reporting import (
    get_revenue_timeline,
    get_revenue_timeline_monthly,
    get_top_products,
)
from orders.services.dashboard import get_dashboard_kpis  # prend user, pas seller


@login_required
def seller_analytics_view(request):
    """Dashboard analytics — MEDIUM (30j) et PRO (annuel + par vente)."""
    seller = request.user.seller_profile  # related_name correct

    # Vérification du plan via l'abonnement
    from subscriptions.services.limits import get_or_create_subscription
    sub = get_or_create_subscription(seller)

    if not sub.has_stats:  # FREE — pas d'accès analytics
        return render(request, "flash_sales/analytics_upgrade.html", {
            "plan": sub.plan,
        })

    # get_dashboard_kpis() prend un User, pas un SellerProfile
    kpis = get_dashboard_kpis(request.user)

    # Sérialiser en JSON pour Chart.js (pas de filtre |map: dans Django)
    timeline_30d = get_revenue_timeline(seller.pk, days=30)

    context = {
        "kpis": kpis,
        "sub": sub,
        "is_pro": sub.is_pro,
        "timeline_json": json.dumps(timeline_30d),  # passé au template comme JSON
        "top_products": get_top_products(seller.pk),
    }

    if sub.is_pro:
        context["timeline_year_json"] = json.dumps(
            get_revenue_timeline_monthly(seller.pk)
        )

    return render(request, "flash_sales/analytics_dashboard.html", context)
```

**URL dans `flash_sales/urls.py` :**

```python
path("analytics/", views.seller_analytics_view, name="analytics"),
```

> URL finale : `/seller/flash-sales/analytics/`

### 4.3 Template analytics

**Fichier à créer : `templates/flash_sales/analytics_dashboard.html`**

```html
{% extends "base.html" %}
{% block title %}Statistiques — HayaFlash{% endblock %}

{% block extra_head %}
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
{% endblock %}

{% block content %}
<div class="max-w-4xl mx-auto px-4 py-8">

    <div class="flex items-center gap-3 mb-6">
        <h1 class="text-2xl font-black text-gray-900">Statistiques</h1>
        <span class="px-2.5 py-1 rounded-full text-xs font-bold uppercase
            {% if sub.is_pro %}bg-yellow-100 text-yellow-700
            {% else %}bg-gray-100 text-gray-600{% endif %}">
            {{ sub.plan_label }}
        </span>
    </div>

    <!-- KPIs -->
    <div class="grid grid-cols-2 gap-3 mb-6">
        <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
            <p class="text-xs text-gray-400 mb-1">Commandes livrées</p>
            <p class="text-2xl font-bold text-gray-900">{{ kpis.total_orders }}</p>
        </div>
        <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
            <p class="text-xs text-gray-400 mb-1">CA encaissé</p>
            <p class="text-xl font-bold text-green-600">
                {{ kpis.total_revenue|floatformat:0 }} FCFA
            </p>
        </div>
        <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
            <p class="text-xs text-gray-400 mb-1">Articles livrés</p>
            <p class="text-2xl font-bold text-gray-900">{{ kpis.total_quantity }}</p>
        </div>
        <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
            <p class="text-xs text-gray-400 mb-1">CA en attente</p>
            <p class="text-xl font-bold text-amber-600">
                {{ kpis.pending_revenue|floatformat:0 }} FCFA
            </p>
        </div>
    </div>

    <!-- Graphique 30 jours -->
    <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5 mb-4">
        <h2 class="text-sm font-bold text-gray-700 mb-4">CA — 30 derniers jours</h2>
        <canvas id="chart30d" height="180"></canvas>
    </div>

    <!-- Top produits -->
    {% if top_products %}
    <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5 mb-4">
        <h2 class="text-sm font-bold text-gray-700 mb-3">Top produits</h2>
        <div class="space-y-2">
            {% for p in top_products %}
            <div class="flex items-center justify-between text-sm">
                <span class="text-gray-700 truncate flex-1">
                    {{ p.product_name_snapshot }}
                </span>
                <span class="text-gray-400 ml-3">{{ p.total_sold }} vendus</span>
                <span class="font-semibold text-gray-900 ml-3">
                    {{ p.total_revenue|floatformat:0 }} F
                </span>
            </div>
            {% endfor %}
        </div>
    </div>
    {% endif %}

    {% if is_pro %}
    <!-- Graphique annuel (PRO) -->
    <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5 mb-4">
        <div class="flex items-center justify-between mb-4">
            <h2 class="text-sm font-bold text-gray-700">CA mensuel — 12 mois</h2>
            <span class="text-xs px-2 py-0.5 bg-yellow-100 text-yellow-700
                         rounded-full font-bold">PRO</span>
        </div>
        <canvas id="chartYear" height="180"></canvas>
    </div>
    {% else %}
    <!-- Upgrade PRO -->
    <div class="bg-amber-50 border border-amber-200 rounded-2xl p-5 text-center">
        <p class="font-semibold text-gray-800 mb-1">
            Graphiques annuels disponibles en PRO
        </p>
        <p class="text-sm text-gray-500 mb-4">
            Historique complet, CA par vente flash, évolution mensuelle.
        </p>
        <a href="{% url 'billing' %}"
           class="inline-block px-5 py-2.5 bg-primary text-white font-bold
                  rounded-xl text-sm hover:bg-red-700 transition-colors">
            Passer au PRO — 5 000 FCFA/mois
        </a>
    </div>
    {% endif %}
</div>

<script>
// Les données sont sérialisées en JSON côté serveur — pas de filtre |map:
const data30d = {{ timeline_json|safe }};
{% if is_pro %}
const dataYear = {{ timeline_year_json|safe }};
{% endif %}

document.addEventListener('DOMContentLoaded', () => {
    // Graphique 30 jours
    const ctx30 = document.getElementById('chart30d');
    if (ctx30 && data30d.length) {
        new Chart(ctx30, {
            type: 'line',
            data: {
                labels: data30d.map(d => d.day),
                datasets: [{
                    label: 'CA (FCFA)',
                    data: data30d.map(d => d.revenue),
                    borderColor: '#E63946',
                    backgroundColor: 'rgba(230,57,70,0.08)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 3,
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true } }
            }
        });
    }

    {% if is_pro %}
    const ctxYear = document.getElementById('chartYear');
    if (ctxYear && dataYear.length) {
        new Chart(ctxYear, {
            type: 'bar',
            data: {
                labels: dataYear.map(d => d.month),
                datasets: [{
                    label: 'CA mensuel (FCFA)',
                    data: dataYear.map(d => d.revenue),
                    backgroundColor: '#FFB800',
                    borderRadius: 6,
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true } }
            }
        });
    }
    {% endif %}
});
</script>
{% endblock %}
```

**Fichier à créer : `templates/flash_sales/analytics_upgrade.html`** (page pour FREE)

```html
{% extends "base.html" %}
{% block content %}
<div class="max-w-md mx-auto px-4 py-16 text-center">
    <i data-lucide="bar-chart-2" class="w-12 h-12 text-gray-300 mx-auto mb-4"></i>
    <h1 class="text-xl font-bold text-gray-900 mb-2">Statistiques avancées</h1>
    <p class="text-gray-500 mb-6 text-sm">
        Accédez au reporting complet avec les plans MEDIUM ou PRO.
    </p>
    <a href="{% url 'billing' %}"
       class="inline-block px-6 py-3 bg-primary text-white font-bold
              rounded-xl hover:bg-red-700 transition-colors">
        Voir les offres
    </a>
</div>
{% endblock %}
```

---

## ÉTAPE 5 — Admin plateforme (vue custom staff-only)

### Priorité : Basse (usage interne uniquement)

### 5.1 Vue admin plateforme

**Fichier à modifier : `core/views.py`** — ajouter à la fin

```python
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Sum


@staff_member_required
def platform_admin_dashboard(request):
    """KPIs globaux de la plateforme — staff only."""
    from django.utils import timezone
    from datetime import timedelta
    from accounts.models import SellerProfile
    from subscriptions.models import Subscription, SubscriptionPayment, PaymentStatus
    from flash_sales.models import FlashSale, FlashSaleStatus
    from orders.models import Order

    now = timezone.now()
    month_start = now - timedelta(days=30)

    context = {
        "total_sellers": SellerProfile.objects.filter(is_active=True).count(),
        "subs_by_plan": (
            Subscription.objects.values("plan")
            .annotate(count=Count("id"))
            .order_by("plan")
        ),
        "live_sales": FlashSale.objects.filter(status=FlashSaleStatus.LIVE).count(),
        "total_orders_month": Order.service_objects.filter(
            created_at__gte=month_start
        ).count(),
        # Utiliser PaymentStatus.SUCCESS (pas 'completed')
        "mrr": (
            SubscriptionPayment.objects.filter(
                status=PaymentStatus.SUCCESS,
                paid_at__gte=month_start,
            ).aggregate(total=Sum("amount"))["total"] or 0
        ),
        "total_revenue": (
            SubscriptionPayment.objects.filter(
                status=PaymentStatus.SUCCESS,
            ).aggregate(total=Sum("amount"))["total"] or 0
        ),
        "recent_payments": (
            SubscriptionPayment.objects.select_related("seller__user")
            .order_by("-created_at")[:20]
        ),
    }
    return render(request, "core/platform_admin.html", context)
```

**URL dans `core/urls.py` :**

```python
path("platform-admin/", views.platform_admin_dashboard, name="platform_admin"),
```

**Ajouter aussi dans `config/urls.py` si `core/urls.py` n'est pas inclus à la racine :**
Vérifier que `path("", include("core.urls"))` inclut bien cette URL.

### 5.2 Template admin plateforme

**Fichier à créer : `templates/core/platform_admin.html`**

```html
{% extends "base.html" %}
{% block title %}Admin Plateforme — HayaFlash{% endblock %}

{% block content %}
<div class="max-w-4xl mx-auto px-4 py-8">

    <div class="flex items-center gap-3 mb-6">
        <h1 class="text-2xl font-black text-gray-900">Administration</h1>
        <span class="px-2.5 py-1 bg-red-100 text-red-700 text-xs
                     font-bold rounded-full uppercase">Staff Only</span>
    </div>

    <!-- KPIs -->
    <div class="grid grid-cols-2 gap-3 mb-6">
        <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
            <p class="text-xs text-gray-400">Vendeurs actifs</p>
            <p class="text-2xl font-bold text-gray-900">{{ total_sellers }}</p>
        </div>
        <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
            <p class="text-xs text-gray-400">Ventes LIVE</p>
            <p class="text-2xl font-bold text-red-600">{{ live_sales }}</p>
        </div>
        <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
            <p class="text-xs text-gray-400">Commandes (30j)</p>
            <p class="text-2xl font-bold text-gray-900">{{ total_orders_month }}</p>
        </div>
        <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
            <p class="text-xs text-gray-400">MRR (abonnements)</p>
            <p class="text-xl font-bold text-amber-600">
                {{ mrr|floatformat:0 }} FCFA
            </p>
            <p class="text-xs text-gray-400">
                Total : {{ total_revenue|floatformat:0 }} FCFA
            </p>
        </div>
    </div>

    <!-- Répartition par plan -->
    <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5 mb-4">
        <h2 class="text-sm font-bold text-gray-700 mb-3">Abonnements par plan</h2>
        <div class="flex gap-4">
            {% for row in subs_by_plan %}
            <div class="flex-1 text-center bg-gray-50 rounded-xl p-3">
                <p class="text-xl font-bold text-gray-900">{{ row.count }}</p>
                <p class="text-xs text-gray-500 uppercase mt-0.5">{{ row.plan }}</p>
            </div>
            {% empty %}
            <p class="text-gray-400 text-sm">Aucun abonnement</p>
            {% endfor %}
        </div>
    </div>

    <!-- Derniers paiements -->
    <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <h2 class="text-sm font-bold text-gray-700 mb-3">Derniers paiements</h2>
        <div class="overflow-x-auto -mx-1">
            <table class="w-full text-sm">
                <thead>
                    <tr class="text-xs text-gray-400 border-b border-gray-100">
                        <th class="text-left py-2 px-1">Vendeur</th>
                        <th class="text-left py-2 px-1">Plan</th>
                        <th class="text-right py-2 px-1">Montant</th>
                        <th class="text-left py-2 px-1">Statut</th>
                        <th class="text-left py-2 px-1">Date</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-gray-50">
                    {% for p in recent_payments %}
                    <tr>
                        <td class="py-2.5 px-1 font-medium text-gray-800 truncate max-w-[120px]">
                            {{ p.seller.business_name|default:p.phone }}
                        </td>
                        <td class="py-2.5 px-1 uppercase text-gray-500 text-xs">
                            {{ p.plan }}
                        </td>
                        <td class="py-2.5 px-1 text-right font-semibold">
                            {{ p.amount|floatformat:0 }}
                        </td>
                        <td class="py-2.5 px-1">
                            <span class="px-2 py-0.5 rounded-full text-xs font-medium
                                {% if p.status == 'success' %}bg-green-100 text-green-700
                                {% elif p.status == 'pending' %}bg-amber-100 text-amber-700
                                {% else %}bg-red-100 text-red-700{% endif %}">
                                {{ p.get_status_display }}
                            </span>
                        </td>
                        <td class="py-2.5 px-1 text-gray-400 text-xs">
                            {{ p.created_at|date:"d/m/Y" }}
                        </td>
                    </tr>
                    {% empty %}
                    <tr>
                        <td colspan="5" class="py-8 text-center text-gray-400 text-sm">
                            Aucun paiement
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
{% endblock %}
```

### 5.3 Enregistrer SubscriptionPayment dans l'admin Django

**Fichier à modifier : `subscriptions/admin.py`**

```python
from django.contrib import admin
from .models import Subscription, SubscriptionPayment, PaymentStatus


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display  = ["seller", "plan", "is_pro", "expires_at", "created_at"]
    list_filter   = ["plan"]
    search_fields = ["seller__business_name", "seller__user__phone"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(admin.ModelAdmin):
    list_display  = ["seller", "plan", "amount", "provider", "status", "created_at"]
    list_filter   = ["status", "plan", "provider"]
    search_fields = ["seller__business_name", "seller__user__phone", "order_id"]
    readonly_fields = ["id", "order_id", "pay_token", "txn_id", "raw_response",
                       "raw_callback", "created_at", "updated_at", "paid_at"]
    ordering = ["-created_at"]
```

---

## ORDRE D'EXÉCUTION RECOMMANDÉ

```
1. QR Code             (1-2j) — indépendant, grande valeur marketing
2. SubscriptionPayment admin (1h) — trivial, valeur immédiate
3. Delivery.audio_note  (2-3j) — migration + form + dashboard
4. Suivi intérêts/vente (1j)  — vue + template + URL
5. Reporting analytics  (3-4j) — service + vue + template + Chart.js
6. Admin plateforme     (1-2j) — vue + template (staff only)
```

---

## CRITÈRES DE SUCCÈS P7

- QR Code scannable depuis le dashboard vendeur → page de commande
- Client peut enregistrer un message vocal → vendeur l'écoute dans le dashboard livraisons
- Vue `/seller/flash-sales/<pk>/interests/` accessible et fonctionnelle
- `/seller/flash-sales/analytics/` affiche KPIs + graphiques (MEDIUM : 30j, PRO : annuel)
- Plan FREE redirigé vers upgrade
- `/platform-admin/` accessible aux staff, retourne 403 pour les autres
- `SubscriptionPayment` visible dans `/admin/`
- `python manage.py check` passe sans erreur après toutes les modifications
