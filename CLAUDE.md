# CLAUDE.md — HayaFlash

> Source de vérité technique pour Claude (Cowork / Claude Code).
> Mis à jour le 2026-07-13. Basé sur audit direct du code source.
> **Ne pas modifier sans avoir d'abord lu le code réel.**

---

## Projet

Application Django de ventes flash mobiles (Mali). Les vendeurs créent des ventes limitées dans le temps ; les clients commandent depuis une page publique partageable via WhatsApp.

---

## Stack

```
Backend  : Django 5.2 · DRF 3.16 · Celery · Redis
Frontend : HTMX 2.0 · Alpine.js 3 · Tailwind CSS (CDN)
DB dev   : SQLite
DB prod  : PostgreSQL
Infra    : Docker · Gunicorn · Nginx · GitHub Actions CI/CD
```

---

## Structure des apps

```
accounts/       → User (phone E.164) + SellerProfile (seller_code, public_slug, bio, avatar)
analytics/      → ShareLink/ShareEvent (tracking WhatsApp), pages publiques SEO, stats agrégées
config/         → Settings multi-env, Celery, URLs, API router
core/           → Home page, slugs centralisés, AuditLog
delivery/       → Modèle Delivery (GPS, COD, statuts), dashboard HTMX livraisons
flash_sales/    → FlashSale + SaleInterest, CRUD vendeur, tâches Celery auto open/close
notifications/  → Modèle Notification, services WhatsApp/SMS, tâches Celery
orders/         → Order + OrderItem, create_order() idempotent, dashboard LIVE HTMX
payments/       → PaymentTransaction + LedgerEntry (COD V1, mock provider)
products/       → Product + ProductMedia + ProductVariant + StockMovement
subscriptions/  → Plan FREE/MEDIUM/PRO, Subscription, SubscriptionPayment (Orange Money)
```

---

## Commandes essentielles

```bash
# Dev
python manage.py runserver --settings=config.settings.dev
python manage.py migrate
python manage.py createsuperuser

# Celery (deux terminaux séparés)
celery -A config worker -l info
celery -A config beat -l info

# Tests
pytest --ds=config.settings.test
python manage.py check

# Docker (dev local)
docker-compose up
```

---

## URLs principales

| URL | Description |
|-----|-------------|
| `/admin/` | Django admin (seule interface admin existante) |
| `/seller/` | Dashboard vendeur (authentifié) |
| `/seller/flash-sales/` | CRUD ventes flash |
| `/orders/dashboard/` | Dashboard LIVE commandes |
| `/orders/seller/deliveries/` | Dashboard livraisons HTMX |
| `/f/<slug>/` | Page publique vente flash (SEO + commande) |
| `/s/<slug>/` | Page publique vendeur |
| `/ventes/` | Calendrier public des ventes |
| `/billing/` | Abonnements vendeur |
| `/api/v1/` | API REST (DRF) |

---

## Conventions

- **FBV partout** (pas de CBV). Services dans `app/services/`.
- **Pas de `Model.objects.create()`** pour `Order` — utiliser uniquement `orders.services.create_order.create_order()`.
- **Migrations data séparées** des migrations schema.
- **HTMX** pour les mises à jour partielles (dashboard LIVE, livraisons).
- **Alpine.js** pour l'état local UI (countdown, GPS, vocal, modals).
- Design system : primary `#E63946`, gold `#FFB800`, success `#22C55E`, bg `#F5F5F5`.

---

## Points clés à connaître

1. **Vocal client** = `SpeechRecognition` navigateur côté client uniquement → transcription texte dans `Delivery.address_text`. Aucun audio stocké en base côté client.
2. **Audio vendeur** = `FlashSale.description_audio` et `Product.description_audio` (FileField WebM/OGG), enregistré par le vendeur, lu par les clients.
3. **Partage** = WhatsApp uniquement (`wa.me` + `api.whatsapp.com`). Pas de QR code, pas de Web Share API.
4. **Admin plateforme** = uniquement `django.contrib.admin`. Pas de vue custom plateforme.
5. **`SubscriptionPayment`** n'est pas enregistré dans l'admin Django.
6. **Plans MEDIUM et FREE** ont la même limite de 3 ventes/mois (`PLAN_MONTHLY_SALES_LIMIT`). Seul PRO est illimité.
7. **Stats avancées MEDIUM/PRO** déclarées dans `PLAN_FEATURES` mais l'UI dashboard est identique pour tous les plans actuellement.

---

## Docs de référence

| Fichier | Rôle |
|---------|------|
| `docs/CODEBASE_STATUS.md` | État réel du code par module — **mettre à jour après chaque chantier** |
| `docs/PLAN_PHASES.md` | Phases P0→P6 avec statut d'avancement |
| `docs/PROJECT_SPEC.md` | Intention produit V1 |
| `docs/ARCHITECTURE.md` | Décisions d'architecture |
| `docs/API_CONTRACT.md` | Contrat API REST |
| `docs/workflows/WORKFLOW_Px_*.md` | Workflows exécutables par phase |

---

## État des phases (juillet 2026)

| Phase | Nom | État |
|-------|-----|------|
| P0 | Foundation & Qualité | ✅ Terminé |
| P1 | Modèles Complets | ✅ Terminé |
| P2 | Interface Vendeur CRUD | ✅ Terminé |
| P3 | LIVE Workflow Complet | ✅ Terminé |
| P4 | Design Moderne Tailwind | ✅ Terminé |
| P5 | Notifications + Subscriptions | ✅ Terminé |
| P6 | CI/CD + Production Hardening | ✅ Terminé |

→ Détail et prochaines priorités : `docs/CODEBASE_STATUS.md`
