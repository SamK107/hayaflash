# 📡 HayaFlash — Contrat API v1 (OpenAPI 3.0)

> Base URL : `https://api.hayaflash.com/api/v1/`
> Toutes les réponses sont en JSON. Erreurs structurées : `{"error": "code", "detail": "..."}`

---

## Principes API

- **Versionnée** : `/api/v1/`
- **Stateless** : pas de session serveur côté API
- **Retry-safe** : idempotence sur `POST /orders/` via `client_request_id`
- **Rate limited** : voir tableau ci-dessous
- **Offline-compatible** : retry-safe pour sync différée

### Codes d'erreur standardisés

| Code | HTTP | Description |
|---|---|---|
| `auth_required` | 401 | Non authentifié |
| `permission_denied` | 403 | Accès interdit |
| `not_found` | 404 | Ressource introuvable |
| `validation_error` | 400 | Données invalides |
| `sale_not_live` | 400 | Vente pas en mode live |
| `sale_window_closed` | 400 | Hors fenêtre horaire |
| `insufficient_stock` | 400 | Stock insuffisant |
| `already_exists` | 200 | Idempotence : commande déjà créée |
| `rate_limit_exceeded` | 429 | Trop de requêtes |

---

## Rate Limits

| Endpoint | Limite | Fenêtre |
|---|---|---|
| `POST /orders/` | 30 | 1 min / IP |
| `POST /accounts/auth/login/` | 10 | 1 min / IP |
| `POST /accounts/auth/register/` | 5 | 1 min / IP |
| `GET /flash-sales/` | 100 | 1 min / IP |
| Tous les autres | 200 | 1 min / IP |

---

## Endpoints

---

### 🔐 Auth

#### POST /accounts/auth/register/

Inscription d'un nouveau utilisateur (vendeur ou client).

**Request**
```json
{
  "phone": "+22376000000",
  "password": "motdepasse123",
  "display_name": "Fatoumata Diallo",
  "is_seller": true,
  "business_name": "Boutique Fati Mode"
}
```

**Response 201**
```json
{
  "user_id": "uuid",
  "phone": "+22376000000",
  "display_name": "Fatoumata Diallo",
  "seller_code": "SLR-A1B2C3D4",
  "public_slug": "boutique-fati-mode",
  "token": "jwt_token_or_session"
}
```

**Erreurs**
- `400` — phone déjà utilisé, password trop court
- `429` — rate limit

---

#### POST /accounts/auth/login/

**Request**
```json
{
  "phone": "+22376000000",
  "password": "motdepasse123"
}
```

**Response 200**
```json
{
  "user_id": "uuid",
  "display_name": "Fatoumata Diallo",
  "token": "jwt_or_session_token",
  "is_seller": true,
  "seller_code": "SLR-A1B2C3D4"
}
```

---

#### GET /accounts/auth/me/

Auth requis.

**Response 200**
```json
{
  "user_id": "uuid",
  "phone": "+22376000000",
  "display_name": "Fatoumata Diallo",
  "is_phone_verified": true,
  "seller": {
    "seller_code": "SLR-A1B2C3D4",
    "public_slug": "boutique-fati-mode",
    "business_name": "Boutique Fati Mode",
    "is_active": true
  }
}
```

---

### ⚡ Flash Sales

#### GET /flash-sales/

Liste des ventes flash publiques (`scheduled` ou `live`).

**Query params**
- `status` : `scheduled|live` (défaut: both)
- `page`, `page_size`

**Response 200**
```json
{
  "count": 12,
  "results": [
    {
      "id": "uuid",
      "title": "Promo Bazin Week-End",
      "public_slug": "promo-bazin-week-end",
      "status": "live",
      "start_time": "2025-10-15T14:00:00Z",
      "end_time": "2025-10-15T18:00:00Z",
      "cover_image": "https://...",
      "seller": {
        "business_name": "Boutique Fati Mode",
        "public_slug": "boutique-fati-mode"
      },
      "countdown_seconds": 3600,
      "order_count": 47
    }
  ]
}
```

---

#### GET /flash-sales/{slug}/

Détail d'une vente flash avec ses produits.

**Response 200**
```json
{
  "id": "uuid",
  "title": "Promo Bazin Week-End",
  "description": "...",
  "status": "live",
  "start_time": "...",
  "end_time": "...",
  "delivery_zone": "Bamako intra-muros",
  "cover_image": "...",
  "seller": { "...": "..." },
  "products": [
    {
      "id": "uuid",
      "name": "Bazin Riche 5m",
      "description": "Tissu de qualité supérieure",
      "price": "4500.00",
      "stock": 23,
      "unit": "pièce",
      "characteristics": {"couleur": "bleu royal", "matière": "bazin"},
      "media": [
        {"type": "image", "url": "https://...", "order": 0},
        {"type": "video", "url": "https://...", "order": 1}
      ]
    }
  ],
  "order_count": 47,
  "share_url": "https://hayaflash.com/f/promo-bazin-week-end",
  "whatsapp_share_url": "https://wa.me/?text=..."
}
```

---

### 📦 Orders

#### POST /orders/

**⚠ Endpoint critique — idempotent via `client_request_id`**

Auth : AllowAny (clients sans compte)

**Request**
```json
{
  "flash_sale_id": "uuid",
  "client_request_id": "550e8400-e29b-41d4-a716-446655440000",
  "customer_name": "Ibrahim Coulibaly",
  "customer_phone": "+22365000000",
  "items": [
    {
      "product_id": "uuid",
      "quantity": 2
    }
  ],
  "delivery": {
    "address_text": "Hamdallaye ACI, Rue 312, face à la pharmacie centrale",
    "latitude": 12.6392,
    "longitude": -8.0029,
    "geo_accuracy": 15.5,
    "geo_method": "gps",
    "delivery_notes": "Appeler avant d'arriver"
  },
  "share_ref": "tok_abc123"
}
```

**Response 201** (nouvelle commande)
```json
{
  "order_id": "uuid",
  "status": "pending",
  "total_amount": "9000.00",
  "items": [
    {
      "product_name": "Bazin Riche 5m",
      "quantity": 2,
      "unit_price": "4500.00",
      "subtotal": "9000.00"
    }
  ],
  "delivery": {
    "address_text": "Hamdallaye ACI...",
    "maps_url": "https://www.google.com/maps?q=12.6392,-8.0029"
  },
  "referral": {
    "share_ref_registered": true,
    "discount_applied": false
  },
  "created_at": "2025-10-15T15:32:00Z"
}
```

**Response 200** (idempotence — déjà créée)
```json
{
  "order_id": "uuid",
  "status": "pending",
  "already_exists": true,
  "total_amount": "9000.00"
}
```

**Erreurs**
```json
// 400 — Vente pas live
{"error": "sale_not_live", "detail": "Cette vente n'est pas en cours"}

// 400 — Hors fenêtre
{"error": "sale_window_closed", "detail": "La vente est terminée"}

// 400 — Stock
{"error": "insufficient_stock", "detail": "Stock insuffisant pour Bazin Riche 5m (demandé: 2, disponible: 1)"}

// 400 — Validation
{"error": "validation_error", "detail": {"customer_phone": ["Numéro de téléphone invalide"]}}

// 429 — Rate limit
{"error": "rate_limit_exceeded", "detail": "30 commandes/minute maximum par IP"}
```

---

#### GET /orders/{order_id}/status/

Suivi de commande public (par customer_phone ou order_id).

**Response 200**
```json
{
  "order_id": "uuid",
  "status": "out_for_delivery",
  "total_amount": "9000.00",
  "delivery": {
    "status": "in_transit",
    "assigned_to": "Moussa D.",
    "estimated_delivery": null
  },
  "updated_at": "2025-10-15T16:45:00Z"
}
```

---

### 🚚 Delivery (Vendeur — Auth requis)

#### GET /delivery/

Liste des livraisons d'une vente.

**Query params**
- `flash_sale_id` (requis)
- `status` : `pending|assigned|in_transit|delivered|failed`

**Response 200**
```json
{
  "count": 12,
  "summary": {
    "pending": 3,
    "in_transit": 6,
    "delivered": 3,
    "total_cod_collected": "27000.00",
    "total_cod_pending": "42750.00"
  },
  "results": [
    {
      "delivery_id": "uuid",
      "order_id": "uuid",
      "order_number": "ORD-001",
      "customer_name": "Ibrahim Coulibaly",
      "customer_phone": "+22365000000",
      "address_text": "Hamdallaye ACI...",
      "latitude": "12.6392",
      "longitude": "-8.0029",
      "maps_url": "https://...",
      "waze_url": "https://...",
      "delivery_notes": "Appeler avant d'arriver",
      "status": "pending",
      "cod_amount": "9000.00",
      "cod_collected": false,
      "assigned_to": null
    }
  ]
}
```

---

#### PATCH /delivery/{delivery_id}/advance/

Avancer le statut d'une livraison.

**Request**
```json
{
  "action": "start_delivery",
  "assigned_to": "Moussa D."
}
```

Actions valides :
- `confirm` : `pending → confirmed` (côté order)
- `start_delivery` : `confirmed → in_transit`
- `mark_delivered` : `in_transit → delivered` + COD collecté
- `mark_failed` : `in_transit → failed`

**Response 200**
```json
{
  "delivery_id": "uuid",
  "status": "in_transit",
  "order_status": "out_for_delivery",
  "cod_collected": false,
  "updated_at": "..."
}
```

**Pour `mark_delivered`** :
```json
// Request
{
  "action": "mark_delivered",
  "cod_collected": true
}

// Response
{
  "delivery_id": "uuid",
  "status": "delivered",
  "order_status": "delivered",
  "cod_collected": true,
  "cod_collected_at": "2025-10-15T18:30:00Z",
  "cod_confirmed_by": "Fatoumata Diallo"
}
```

---

### 📊 Dashboard (Vendeur — Auth requis + HTMX)

#### GET /orders/seller/dashboard/

Dashboard principal vendeur.

**Query params** : `flash_sale_id` (requis)

**Response 200**
```json
{
  "flash_sale": {
    "id": "uuid",
    "title": "...",
    "status": "live",
    "countdown_seconds": 1823
  },
  "kpis": {
    "total_orders": 47,
    "total_items": 89,
    "estimated_revenue": "84500.00",
    "deliveries_in_progress": 6,
    "cod_collected": "27000.00"
  },
  "recent_orders": ["..."]
}
```

---

### 🔗 Analytics

#### GET /analytics/share-link/

Créer ou récupérer un lien de partage.

**Request**
```json
{
  "link_type": "flash_sale",
  "flash_sale_id": "uuid"
}
```

**Response 200**
```json
{
  "token": "tok_abc123",
  "share_url": "https://hayaflash.com/f/promo-bazin?ref=tok_abc123",
  "whatsapp_url": "https://wa.me/?text=...",
  "stats": {
    "clicks": 234,
    "conversions": 12
  }
}
```

---

## OpenAPI YAML (résumé)

```yaml
openapi: 3.0.3
info:
  title: HayaFlash API
  version: 1.0.0
  description: API de ventes flash live pour l'Afrique francophone

servers:
  - url: https://api.hayaflash.com/api/v1
    description: Production
  - url: http://localhost:8000/api/v1
    description: Development

security:
  - BearerAuth: []

components:
  securitySchemes:
    BearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT

  schemas:
    Error:
      type: object
      properties:
        error:
          type: string
        detail:
          oneOf:
            - type: string
            - type: object

    Order:
      type: object
      required: [flash_sale_id, client_request_id, customer_name, customer_phone, items, delivery]
      properties:
        flash_sale_id:
          type: string
          format: uuid
        client_request_id:
          type: string
          format: uuid
          description: UUID généré côté client pour idempotence
        customer_name:
          type: string
          minLength: 2
          maxLength: 200
        customer_phone:
          type: string
          pattern: '^(\+?[0-9]{8,15})$'
        items:
          type: array
          minItems: 1
          items:
            type: object
            required: [product_id, quantity]
            properties:
              product_id:
                type: string
                format: uuid
              quantity:
                type: integer
                minimum: 1
        delivery:
          type: object
          required: [address_text]
          properties:
            address_text:
              type: string
              minLength: 10
            latitude:
              type: number
              minimum: -90
              maximum: 90
            longitude:
              type: number
              minimum: -180
              maximum: 180
            geo_accuracy:
              type: number
            geo_method:
              type: string
              enum: [gps, manual, timeout, denied]
            delivery_notes:
              type: string
        share_ref:
          type: string
          description: Token de référence virale (optionnel)
```

---

## 🔚 Fin du document