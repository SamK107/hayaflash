# 🚚 HayaFlash — Delivery Module Specification (v1.0)

> Module critique pour l'exécution post-live. Le paiement se fait à la livraison (COD).

---

## 📌 Objectif

Permettre au vendeur de :
1. Connaître l'adresse exacte de livraison pour chaque commande
2. Organiser et suivre les livraisons post-live
3. Confirmer la collecte du paiement cash (COD) à la livraison

---

## 🗺️ Géolocalisation — Règles Techniques

### Capture côté client

```javascript
// Dans la page commande client
async function captureLocation() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) {
      resolve({ lat: null, lng: null, accuracy: null, method: 'manual' });
      return;
    }

    const timeout = setTimeout(() => {
      resolve({ lat: null, lng: null, accuracy: null, method: 'timeout' });
    }, 10_000);

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        clearTimeout(timeout);
        resolve({
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          accuracy: pos.coords.accuracy,
          method: 'gps'
        });
      },
      (err) => {
        clearTimeout(timeout);
        resolve({ lat: null, lng: null, accuracy: null, method: 'denied' });
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }
    );
  });
}
```

### Reverse Geocoding (adresse depuis coordonnées)

- Provider : **Nominatim (OpenStreetMap)** — gratuit, sans clé API
- Endpoint : `https://nominatim.openstreetmap.org/reverse?lat=...&lon=...&format=json`
- Usage : suggestion uniquement, le client confirme ou corrige
- Rate limit : 1 requête/seconde max (respecter les CGU OSM)
- Fallback : champ texte libre si Nominatim indisponible

### Validation côté serveur

```python
def validate_coordinates(lat, lng):
    """Validation stricte des coordonnées GPS."""
    if lat is not None and lng is not None:
        if not (-90 <= lat <= 90):
            raise ValidationError("Latitude invalide")
        if not (-180 <= lng <= 180):
            raise ValidationError("Longitude invalide")
    # Adresse texte obligatoire dans tous les cas
    return True
```

---

## 📦 Modèle de Données

### Delivery

```python
class Delivery(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'En attente'
        ASSIGNED = 'assigned', 'Livreur assigné'
        IN_TRANSIT = 'in_transit', 'En livraison'
        DELIVERED = 'delivered', 'Livré'
        FAILED = 'failed', 'Échec livraison'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    order = models.OneToOneField(
        'orders.Order', on_delete=models.CASCADE, related_name='delivery'
    )

    # Adresse livraison
    address_text = models.CharField(max_length=500)
    latitude = models.DecimalField(max_digits=10, decimal_places=8, null=True, blank=True)
    longitude = models.DecimalField(max_digits=11, decimal_places=8, null=True, blank=True)
    geo_accuracy = models.FloatField(null=True, blank=True)   # mètres
    geo_method = models.CharField(max_length=20, default='manual')  # gps|manual|timeout|denied
    delivery_notes = models.TextField(blank=True)             # instructions spéciales

    # Statut
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    assigned_to = models.CharField(max_length=200, blank=True)  # V1: free text
    scheduled_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    # COD (Cash on Delivery)
    cod_amount = models.DecimalField(max_digits=10, decimal_places=2)
    cod_collected = models.BooleanField(default=False)
    cod_collected_at = models.DateTimeField(null=True, blank=True)
    cod_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='confirmed_deliveries'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['order']),
        ]

    def get_maps_url(self):
        """Lien Google Maps pour le livreur."""
        if self.latitude and self.longitude:
            return f"https://www.google.com/maps?q={self.latitude},{self.longitude}"
        return None

    def get_waze_url(self):
        """Lien Waze pour le livreur."""
        if self.latitude and self.longitude:
            return f"https://waze.com/ul?ll={self.latitude},{self.longitude}&navigate=yes"
        return None
```

---

## 🔄 Workflow COD

```
Commande créée (pending)
        │
        ▼
Vendeur confirme → confirmed
        │
        ▼
Vendeur prépare + assigne livreur → out_for_delivery
Delivery.status = in_transit
Delivery.assigned_to = "Moussa D."
Delivery.scheduled_at = now()
        │
        ▼
Livreur arrive à l'adresse GPS
Livreur collecte le cash
        │
        ▼
Vendeur marque "Livré" dans dashboard
→ Order.status = delivered
→ Delivery.status = delivered
→ Delivery.cod_collected = True
→ Delivery.cod_amount = Order.total_amount
→ Delivery.cod_collected_at = now()
→ Delivery.cod_confirmed_by = request.user
```

---

## 📱 UX — Page Commande Client

### Champs du formulaire (ordre d'affichage)

```
1. Nom complet *
2. Téléphone *
3. [Bouton "Utiliser ma position GPS"] → auto-rempli
4. Adresse de livraison * (texte, modifiable)
5. Instructions supplémentaires (optionnel)
--- PRODUITS ---
6. Quantité * (par produit)
--- CTA ---
[Commander maintenant]
```

### États UX Géolocalisation

| État | UX |
|---|---|
| GPS en cours | Spinner + "Détection de votre position..." |
| GPS ok | ✅ Badge vert + adresse suggérée |
| GPS > 500m précision | ⚠️ "Position imprécise, vérifiez l'adresse" |
| GPS refusé | ℹ️ "Entrez votre adresse manuellement" |
| GPS timeout | ℹ️ "GPS indisponible, entrez votre adresse" |

---

## 📊 Dashboard Vendeur — Vue Livraisons

### Tableau de bord post-live

```
┌─────────────────────────────────────────────────────┐
│  VENTE: "Promo Tissus Bazin" — CLOSED               │
│  12 commandes | 8,750 XOF à collecter               │
├─────────────────────────────────────────────────────┤
│ Filtres: [Toutes] [En attente] [En cours] [Livrées] │
├─────────────────────────────────────────────────────┤
│ #001 Aissatou D.   📍 Hamdallaye ACI    750 XOF    │
│      +223 76 XX XX   [Confirmer] [Livrer] [Annuler] │
│      Lien: [Maps] [Waze]                            │
├─────────────────────────────────────────────────────┤
│ #002 Moussa K.     📍 Badalabougou      1,200 XOF  │
│      ...                                            │
└─────────────────────────────────────────────────────┘
```

### Actions rapides par commande

| Action | Transition | COD |
|---|---|---|
| Confirmer | `pending → confirmed` | — |
| Mettre en livraison | `confirmed → out_for_delivery` | Saisir livreur |
| Marquer Livré + COD | `out_for_delivery → delivered` | cod_collected = true |
| Annuler | `any → cancelled` | — |

---

## 🔐 Sécurité Livraison

- Coordonnées GPS validées côté serveur (range check)
- COD ne peut être confirmé que par un `is_authenticated` seller
- Transition de statut strictement contrôlée (pas de retour en arrière)
- Adresse texte minimum 10 caractères
- Numéro de téléphone client validé (format E.164 ou local)

---

## 🔚 Fin du document