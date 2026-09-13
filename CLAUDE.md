# CLAUDE.md — HayaFlash

> Source de vérité technique pour Claude (Cowork / Claude Code).
> Mis à jour le 2026-09-13. Basé sur audit direct du code source.
> **Ne pas modifier sans avoir d'abord lu le code réel.**
>
> Note : la version précédente (13/07) n'avait jamais été mise à jour depuis le
> tout premier commit du projet — elle décrivait l'état d'avant la Phase 7
> (pas de QR code, pas d'admin plateforme, etc.) alors que tout ça existe et
> fonctionne depuis. Cette révision aligne le fichier sur le code réel.

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
analytics/      → ShareLink/ShareEvent (tracking WhatsApp), QR code (services/qrcode.py),
                  reporting MEDIUM/PRO (services/reporting.py), pages publiques SEO
config/         → Settings multi-env, Celery, URLs, API router
core/           → Home page, slugs centralisés, AuditLog, dashboard staff /platform-admin/
delivery/       → Modèle Delivery (GPS, COD, audio_note), dashboard HTMX livraisons
flash_sales/    → FlashSale + SaleInterest, CRUD vendeur, tâches Celery auto open/close +
                  rappel automatique aux inscrits (send_pending_sale_reminders)
notifications/  → Modèle Notification, services WhatsApp/SMS, tâches Celery
orders/         → Order + OrderItem, create_order() idempotent, dashboard LIVE HTMX
payments/       → PaymentTransaction + LedgerEntry (COD V1, mock provider)
products/       → Product + ProductMedia + ProductVariant + StockMovement
subscriptions/  → Plan FREE/MEDIUM/PRO, Subscription, SubscriptionPayment (Orange Money),
                  admin Django (simulation de plan sans paiement réel)
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
| `/admin/` | Django admin standard |
| `/platform-admin/` | Dashboard pilotage plateforme (staff only) — MRR, vendeurs, abonnements |
| `/seller/` | Dashboard vendeur (authentifié) |
| `/seller/flash-sales/` | CRUD ventes flash |
| `/seller/flash-sales/analytics/` | Reporting MEDIUM (30j) / PRO (annuel + top produits) |
| `/seller/flash-sales/<pk>/interests/` | Réservations d'intérêt par vente |
| `/orders/dashboard/` | Dashboard LIVE commandes |
| `/orders/seller/deliveries/` | Dashboard livraisons HTMX |
| `/f/<slug>/` | Page publique vente flash (SEO + commande) |
| `/f/<slug>/qrcode/` | QR code de la vente (JSON, auth vendeur) |
| `/s/<slug>/` | Page publique vendeur |
| `/ventes/` | Calendrier public des ventes |
| `/billing/` | Abonnements vendeur |
| `/health/` | Healthcheck (alias racine, anonyme — voir point 8) |
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

1. **Vocal client** = deux mécanismes coexistent : `SpeechRecognition` navigateur → transcription texte dans `Delivery.address_text`, **et** un enregistrement audio réel (`audio_base64` envoyé par le client, décodé et stocké dans `Delivery.audio_note` via `_attach_audio_note()`, best-effort — un échec de décodage ne bloque jamais la commande).
2. **Audio vendeur** = `FlashSale.description_audio` et `Product.description_audio` (FileField WebM/OGG), enregistré par le vendeur, lu par les clients.
3. **Partage** = WhatsApp (`wa.me` + `api.whatsapp.com`) **+ QR code** (`analytics/services/qrcode.py`, vue `flash_sale_qr_view`, `/f/<slug>/qrcode/`). Web Share API (`navigator.share()`) **absente** — gap connu, backlog.
4. **Admin plateforme** = `django.contrib.admin` **+ vue custom** `/platform-admin/` (`core/views.py:platform_admin_dashboard`, `@staff_member_required`) : vendeurs actifs, ventes live, MRR, revenu YTD, résumé remittance Orange, derniers paiements.
5. **`SubscriptionPayment`** **est enregistré** dans l'admin Django (`SubscriptionPaymentAdmin` — filtres status/plan/provider). `SubscriptionAdmin` expose aussi des actions de simulation de plan (Gratuit perpétuel / Medium 90j / Pro 90j) sans paiement réel — pratique pour la démo/support.
6. **Plans MEDIUM et FREE** ont la même limite de 3 ventes/mois (`PLAN_MONTHLY_SALES_LIMIT`). Seul PRO est illimité.
7. **Stats avancées MEDIUM/PRO** déclarées dans `PLAN_FEATURES`, différenciées dans l'UI via `/seller/flash-sales/analytics/` (gate sur `sub.has_stats`).
8. **Quota d'abonnement (`subscriptions/services/limits.py`)** est fail-closed : toute exception pendant la vérification bloque la création de vente plutôt que de l'autoriser silencieusement (loggé via `logger.exception`). Une vente `CANCELLED` libère son slot de quota. Un abonnement PRO/MEDIUM expiré retombe sur la limite FREE.
9. **Healthcheck** (`config/api_urls.py:health`) doit rester `@permission_classes([AllowAny])` et accessible à la fois sous `/health/` (racine, alias dans `config/urls.py`, ciblé par Dockerfile/compose/nginx) et `/api/v1/health/` — ne pas réintroduire `IsAuthenticated` dessus, ça casse tous les healthchecks infra silencieusement (403, pas d'erreur visible sans creuser).
10. **CI/CD** : `.github/workflows/deploy.yml` = `test → build → deploy-staging → deploy-prod` chaînés (même fichier, `needs:` — pas de dépendance inter-workflow fiable sur GitHub Actions). `deploy-staging`/`deploy-prod` ont `if: false` (**déploiement VPS mis en pause volontairement le 13/09** — retirer la ligne quand le VPS est prêt : `docker login ghcr.io`, secrets `STAGING_*`/`PROD_*`, `/srv/hayaflash/.env`). L'image est poussée sur GHCR taguée au SHA exact + tag mobile `staging-latest`. `infra/scripts/deploy.sh` gère le rollback automatique (tag précédent) si le smoke test échoue — ne défait pas les migrations DB (forward-only).
11. **F3 "Sales Drawer"** : incertitude de gouvernance non résolue — un composant drawer (`orderDrawer`, `templates/analytics/flash_sale_public.html`) existe, mais rien ne confirme que c'est ce que désignait ce label externe. Voir `docs/PROJECT_SPEC.md` § Incertitudes.

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

## État des phases (septembre 2026)

| Phase | Nom | État |
|-------|-----|------|
| P0 | Foundation & Qualité | ✅ Terminé |
| P1 | Modèles Complets | ✅ Terminé |
| P2 | Interface Vendeur CRUD | ✅ Terminé |
| P3 | LIVE Workflow Complet | ✅ Terminé |
| P4 | Design Moderne Tailwind | ✅ Terminé |
| P5 | Notifications + Subscriptions | ✅ Terminé |
| P6 | CI/CD + Production Hardening | ✅ Terminé |
| P7 | Pro Features & Admin Plateforme | ✅ Terminé (QR code, audio_note, interests par vente, analytics MEDIUM/PRO, admin plateforme, `SubscriptionPayment` admin) |

→ Détail et prochaines priorités : `docs/CODEBASE_STATUS.md`
