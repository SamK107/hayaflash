# 🚀 HayaFlash — Product & Architecture Specification (v2.0)

> **Source of Truth.** Tout assistant IA, tout développeur, toute décision d'architecture doit se référer à ce document.
> Toute feature non alignée doit être rejetée ou explicitement justifiée ici.

---

## 📌 Vision Produit

HayaFlash est une plateforme SaaS **mobile-first** de **ventes flash live** pour l'Afrique francophone.

Elle permet à des vendeurs (boutiques, créateurs, producteurs) de :
- Programmer et diffuser des ventes flash en direct (1h à 4h)
- Recevoir des commandes en temps réel pendant le live
- Exécuter les commandes post-live (livraison à l'adresse, géolocalisée)
- Être payé à la livraison (Cash on Delivery)
- Croître viralement via WhatsApp et les réseaux sociaux

### Mental Model

> HayaFlash = **Bourse de commandes live** + **Exécution logistique post-live**

Ce n'est pas un e-commerce classique. C'est un système de **trading de commandes en temps réel** avec exécution différée et paiement à la livraison.

---

## 🎯 Objectifs Produit (toute feature doit servir ≥1)

1. **Vendre plus** — augmenter le volume de commandes par vente
2. **Zéro erreur** — aucune commande perdue, dupliquée ou hors fenêtre live
3. **Gagner du temps** — gestion des commandes rapide pour le vendeur
4. **Exécution fiable** — livraison à l'adresse exacte, paiement à la livraison
5. **Croissance virale** — boucle de partage WhatsApp native

---

## 🚫 Hors Scope V1

- Paiement mobile money in-app (paiement = Cash on Delivery uniquement en V1)
- Chat interne vendeur/acheteur
- ERP ou comptabilité
- Multi-tenant avancé
- Marketplace multi-vendeurs
- Logistique partenaire (DHL, etc.)
- Abonnements payants (scaffold uniquement)

---

## 🧠 Cycle de Vie d'une Vente Flash

```
SCHEDULED → LIVE → CLOSED → EXECUTING → COMPLETED
     ↑                              ↓
  (annulé)                     (CANCELLED)
```

| Statut | Description |
|---|---|
| `scheduled` | Vente programmée, visible publiquement |
| `live` | Vente active, commandes acceptées |
| `closed` | Fenêtre fermée, plus de commandes |
| `executing` | Livraisons en cours |
| `completed` | Toutes commandes traitées |
| `cancelled` | Vente annulée avant ou pendant le live |

**Règle critique** : Les commandes sont acceptées uniquement si `status == live` ET `start_time ≤ now ≤ end_time`.

---

## ⚡ Règles Produit Fondamentales

### R1 — Temps réel
Les commandes apparaissent dans le dashboard vendeur en quasi temps réel (HTMX polling ≤ 5s).

### R2 — Anti-erreur
- Aucune commande perdue ou dupliquée
- `client_request_id` UUID obligatoire sur chaque commande
- Transactions DB atomiques avec `select_for_update`

### R3 — Offline-first (client)
- Le client peut passer commande sans connexion stable
- Stockage IndexedDB + sync queue avec retry automatique

### R4 — Simplicité extrême
- Chaque écran : UNE action principale
- Formulaire commande client : ≤ 5 champs

### R5 — Géolocalisation obligatoire
- Coordonnées GPS capturées à la commande
- Adresse textuelle confirmée par le client
- Fallback manuel si GPS refusé

### R6 — Paiement à la livraison (COD)
- Aucun paiement en ligne en V1
- Le livreur collecte le montant en cash
- Le vendeur confirme la réception

---

## 🏗️ Architecture Technique

### Stack

| Couche | Technologie |
|---|---|
| Backend | Django 5.2+, DRF 3.16 |
| DB dev | SQLite |
| DB prod | PostgreSQL 15+ |
| Cache | LocMem dev / Redis prod |
| Auth | User custom phone (E.164), OTP SMS |
| Frontend | Django Templates + HTMX + Alpine.js + TailwindCSS |
| Offline | IndexedDB + sync queue JS |
| Static | WhiteNoise + Gunicorn |
| Media | Local dev / S3-compatible prod |

### Principes d'Architecture

```
views / api        →  orchestration uniquement (no business logic)
services/          →  toute logique métier
create_order()     →  SEUL point d'entrée pour créer une commande
Order.objects.create()  →  bloqué via GuardedOrderManager
```

**Le backend est la source de vérité absolue.** Toute validation critique se fait côté serveur.

---

## 📦 Structure Projet

```
hayaflash/
│
├── config/                  # Settings, URLs, WSGI/ASGI
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py
│   │   └── prod.py
│
├── apps/
│   ├── accounts/            # Auth, SellerProfile, OTP
│   ├── flash_sales/         # Ventes flash (workflow statut)
│   ├── products/            # Produits + stock
│   ├── orders/              # Commandes + dashboard HTMX
│   ├── delivery/            # Livraisons + géolocalisation ← NEW
│   ├── analytics/           # Viral growth, partage, SEO
│   ├── notifications/       # Push/SMS (scaffold)
│   ├── subscriptions/       # Plans vendeur (scaffold)
│   └── core/                # Home, slugs, utilitaires
│
├── api/
│   └── v1/                  # REST API versionnée
│
├── services/                # Logique métier découplée
│
├── infra/                   # Docker, Nginx, scripts deploy
│
├── templates/               # Django templates
├── static/                  # CSS, JS, assets
└── PROJECT_SPEC.md
```

---

## 🧩 Domaines Fonctionnels

### 1. Accounts
- Inscription vendeur (phone E.164, OTP)
- Profil vendeur : `seller_code` auto, `public_slug`, `business_name`
- Authentification session + token API
- Page publique vendeur : `/s/<slug>/`

### 2. Flash Sales

- Création vente : titre, description, médias, `start_time`, `end_time`, zone géographique de livraison
- Statuts : `scheduled → live → closed → executing → completed`
- Ouverture/fermeture automatique (Celery beat ou cron) + manuelle
- Page publique vente : `/f/<slug>/` (SEO, OpenGraph, JSON-LD)
- Affichage dans le calendrier public des ventes programmées

### 3. Products

- Associés à une `FlashSale`
- Champs : `name`, `description`, `price`, `stock`, `unit`
- Médias : photos (multi), vidéo (URL ou upload)
- Caractéristiques libres (JSON)
- Prix snapshot à la commande

### 4. Orders *(Cœur critique)*

- Liée à une `FlashSale` et un ou plusieurs `Product`
- `client_request_id` UUID (idempotence)
- Champs client : `customer_name`, `customer_phone`
- Adresse livraison : texte + `latitude` + `longitude`
- Statuts : `pending → confirmed → out_for_delivery → delivered | cancelled`
- Stock sécurisé : `select_for_update` + transaction atomique
- Anti-doublon : `client_request_id` unique

### 5. Delivery *(NEW)*

- Entité `Delivery` liée à une `Order`
- Champs : `address_text`, `latitude`, `longitude`, `delivery_notes`, `scheduled_at`
- Statuts : `pending → assigned → in_transit → delivered | failed`
- Collecte COD : `cod_amount`, `cod_collected_at`, `cod_confirmed_by`
- Vue carte vendeur (optionnel V1.1)

### 6. Live Dashboard (Vendeur)

- Commandes temps réel (HTMX polling 3–5s)
- KPI live : #commandes, #articles, revenus estimés, #livraisons en cours
- Actions rapides par commande : confirmer / préparer / en livraison / livré / annuler
- Filtre par statut
- Badge "LIVE" rouge + countdown timer

### 7. Page Commande Client

- Mobile-first, ultra-rapide
- Champs : `nom`, `téléphone`, `quantité`, `adresse`, `GPS auto`
- Géolocalisation browser (navigator.geolocation) avec fallback manuel
- 1 CTA principal "Commander"
- Offline-first : IndexedDB + retry queue
- Confirmation par SMS optionnel

### 8. Calendrier Public des Ventes

- Liste des ventes `scheduled` et `live` accessibles publiquement
- Filtrage par catégorie / zone géographique
- Countdown vers le prochain live
- Bouton "Me rappeler" (numéro phone → SMS de rappel)

### 9. Sync System (Offline)

- `client_request_id` UUID généré côté client
- API idempotente
- Retry-safe
- Queue offline IndexedDB
- Sync automatique au retour de connexion

### 10. Growth System

- Lien de vente partageable court (`/f/<slug>/`)
- Message WhatsApp préformaté avec lien + image produit
- `ShareLink` tracé avec attribution `share_ref`
- Page publique vendeur avec toutes ses ventes actives
- Referral loop : client partagé → commande → attribution

### 11. Subscriptions *(Scaffold V1)*

| Plan | Limite |
|---|---|
| Free | 3 ventes / mois |
| Pro | Illimité + analytics avancés |

- Middleware enforcement sur création de vente
- Upgrade CTA dans le dashboard

---

## 🔴 Live Mode UX Rules

Quand une vente est `LIVE` :
- Badge rouge pulsant "● LIVE"
- Countdown visible en permanence
- UI simplifiée au maximum
- Actions rapides uniquement (pas de settings)
- Commandes récentes en haut, ordre chronologique inversé
- Son/vibration optionnel à chaque nouvelle commande (PWA)

---

## 🗺️ Géolocalisation — Règles

1. **Capture GPS** : `navigator.geolocation.getCurrentPosition()` sur la page commande
2. **Timeout** : 10 secondes, puis fallback vers saisie manuelle obligatoire
3. **Précision minimum** : 500m acceptable (mobile en zone dense)
4. **Stockage** : `latitude` DECIMAL(10,8), `longitude` DECIMAL(11,8)
5. **Adresse texte** : obligatoire (reverse geocoding optionnel via Nominatim/OSM)
6. **Affichage vendeur** : adresse texte + coordonnées + lien Google Maps
7. **Jamais bloquant** : si GPS refusé → adresse textuelle suffit

---

## 💰 Paiement à la Livraison (COD)

- Aucune intégration paiement en ligne en V1
- Flux :
  1. Client commande
  2. Vendeur confirme
  3. Livreur livre à l'adresse GPS
  4. Livreur collecte le cash
  5. Vendeur marque "livré" + "COD collecté"
- Montant COD = somme des `OrderItem.price_snapshot * quantity`
- Prévu V1.1 : Mobile Money (Orange Money, MTN MoMo)

---

## 🔐 Sécurité & Fiabilité

- Aucune commande acceptée hors fenêtre LIVE
- Idempotence obligatoire (`client_request_id`)
- Validation serveur stricte (jamais côté client seul)
- Transactions DB atomiques (`atomic()` + `select_for_update`)
- Stock verrouillé avant décrémentation
- Rate limit commandes publiques : 30 POST/IP/min
- CSRF protégé sur toutes les pages auth
- Signatures HMAC sur webhooks
- Coordonnées GPS validées côté serveur (range check)

---

## ⚙️ API Principles

- Versionnée : `/api/v1/`
- Stateless
- Retry-safe
- Compatible offline sync
- JSON uniquement
- Erreurs structurées : `{ "error": "code", "detail": "..." }`
- Rate limiting par IP et par user

---

## 🎨 Design System

| Token | Valeur |
|---|---|
| Primary | `#E63946` (rouge action) |
| Dark | `#111111` |
| Accent | `#FFB800` (or) |
| Success | `#22C55E` |
| Background | `#F5F5F5` |
| Text | `#1A1A1A` |

### UX Principles
- Mobile-first (viewport 375px référence)
- Gros boutons (min 48px touch target)
- 1 action principale par écran
- Interface type fintech + live commerce
- Feedback immédiat sur chaque action (loaders, toasts)

---

## 📊 KPI Produit (Live Dashboard)

| Métrique | Source |
|---|---|
| #commandes | `Order.count()` par vente |
| #articles vendus | `sum(OrderItem.quantity)` |
| Revenu estimé | `sum(price_snapshot * quantity)` |
| Taux de conversion | commandes / vues page |
| #livraisons en cours | `Delivery.status = in_transit` |
| COD collecté | `sum(Delivery.cod_amount where delivered)` |

---

## 🚀 Definition of Done — V1

| Critère | Cible |
|---|---|
| Créer une vente flash | < 60 secondes |
| Passer une commande (client) | < 15 secondes |
| Apparition commande (dashboard) | < 5 secondes |
| Aucune commande perdue (offline) | 100% |
| Fermer + exécuter une vente | workflow complet |
| Adresse livraison capturée | GPS + texte |
| COD confirmé | workflow complet |

---

## 🔚 Fin du document