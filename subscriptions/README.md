# subscriptions/

Module de gestion des abonnements HayaFlash et du paiement Orange Money.

## Vue d'ensemble

HayaFlash offre trois plans d'abonnement :

| Plan | Limite ventes/mois | Statistiques | Prix | Durée |
|------|-------------------|--------------|------|-------|
| **FREE** | 3 | Non | 0 XOF | Perpétuel |
| **MEDIUM** | 3 | 30 jours | 2000 XOF | 31 jours renouvelable |
| **PRO** | Illimité | Historique complet | 5000 XOF | 31 jours renouvelable |

Système de paiement : **Orange Money WebPay** (OAuth2 + webhook asynchrone).

## Structure

```
subscriptions/
├── models.py              # Subscription, SubscriptionPayment, WebhookLog, Plan choices
├── views.py               # FBV: subscription (page principal), checkout, callbacks
├── billing_views.py       # URLs stables pour Orange Money (return/cancel/webhook)
├── billing_urls.py        # Routes stables enregistrées chez Orange Money
├── urls.py                # Routes vendeur (historiques, utiliser billing_urls)
├── admin.py               # Django admin: SubscriptionAdmin, SubscriptionPaymentAdmin
│
├── services/
│   ├── limits.py          # get_sale_quota(), can_create_flash_sale() — quota par plan
│   ├── payment.py         # create_orange_payment(), activate_subscription_from_payment()
│   ├── orange_money.py    # OAuth2 + WebPay API client
│   └── platform_reporting.py  # Reporting MRR/ARR pour admin plateforme
│
├── tests.py               # Tests unitaires
└── migrations/            # Migrations Django (y compris WebhookLog)
```

## Modèles

### `Subscription`

État d'abonnement courant du vendeur (une par vendeur).

```python
class Subscription(models.Model):
    seller = OneToOneField(SellerProfile)
    plan = CharField(choices=['free', 'medium', 'pro'])
    expires_at = DateTimeField(null=True)  # Null = plan actif sans expiration
```

**Propriétés utiles:**
- `.is_free` — True si gratuit ou expiré
- `.is_paid` — True si MEDIUM/PRO et actif
- `.is_pro` — True si PRO et non expiré
- `.has_advanced_stats` — True si PRO

### `SubscriptionPayment`

Trace une tentative de paiement pour un upgrade.

```python
class SubscriptionPayment(models.Model):
    seller = ForeignKey(SellerProfile)
    plan = CharField(choices=['medium', 'pro'])
    status = CharField(choices=['pending', 'success', 'failed', 'cancelled'])
    order_id = CharField(max_length=24, unique=True)  # Orange Money
    notif_token = CharField(max_length=128, unique=True)  # Webhook lookup token
    txn_id = CharField()  # Transaction ID Orange
    payment_url = URLField()  # Redirection utilisateur
    amount = PositiveIntegerField()  # XOF
    created_at, updated_at, paid_at = DateTimeFields
```

**Règles critiques:**
- `notif_token` est généré et stocké AVANT appel API Orange Money
- Webhooks font un lookup par `notif_token` UNIQUEMENT (pas par `order_id`)
- `order_id` limité à 24 caractères (contrainte Orange Money)

### `WebhookLog`

Audit trail de toutes les notifications reçues.

```python
class WebhookLog(models.Model):
    payment = ForeignKey(SubscriptionPayment)
    notif_token = CharField()  # Token du webhook
    status = CharField()  # 'SUCCESS', 'FAILED', etc.
    txn_id = CharField()  # ID transaction
    raw_payload = JSONField()  # Payload brut (audit)
    processed = BooleanField()  # True si traité (activation), False si skip (idempotence)
    created_at = DateTimeField()
```

Permet l'audit complet : voir tous les webhooks reçus, identifier les doublons, etc.

## Services

### `orange_money.py`

Client Orange Money WebPay.

```python
def _get_access_token() -> str:
    """OAuth2 client_credentials — retourne Bearer token."""

def initiate_payment(
    *, amount: int, order_id: str, notif_token: str, 
    return_url: str, cancel_url: str, notif_url: str, 
    reference: str = "HayaFlash"
) -> dict:
    """Initie un paiement. Retourne {payment_url, raw}."""
    # Valide order_id ≤ 24 chars
    # Envoie notif_token à Orange Money
    # Active SSL verification (verify=True)

def verify_callback(callback_data: dict) -> dict:
    """Parse webhook Orange Money.
    Retourne {success, notif_token, status, txn_id, ...}."""
```

### `payment.py`

Orchestration du paiement.

```python
def _generate_order_id(plan: str) -> str:
    """Génère order_id ≤ 24 chars (HF-{plan[0]}-{random})."""

def _generate_notif_token() -> str:
    """Génère token aléatoire 64 hex chars."""

def create_orange_payment(
    *, seller, plan: str, phone: str, request
) -> SubscriptionPayment:
    """
    Crée SubscriptionPayment + appelle Orange Money.
    Règle: notif_token généré et stocké AVANT appel API.
    """

def activate_subscription_from_payment(payment: SubscriptionPayment) -> Subscription:
    """Idempotent: active/prolonge abonnement si paiement success."""
```

### `limits.py`

Vérification des quotas.

```python
def get_sale_quota(seller) -> dict:
    """Retourne l'etat du quota (can_create, monthly_count, monthly_limit, reason)."""
    # FREE: 3 ventes/mois, MEDIUM: 10 ventes/mois (hors CANCELLED)
    # PRO: illimité tant que non expiré

def can_create_flash_sale(seller) -> tuple[bool, str]:
    """Raccourci (can_create, reason) au-dessus de get_sale_quota()."""
```

Appelée via `flash_sales.services.crud.can_seller_create_sale()`, qui est
**fail-closed** : toute exception pendant la verification refuse la creation
plutot que de l'autoriser silencieusement (voir CLAUDE.md point 8).

## Vues

### Vues vendeur (historiques — préférer billing_views.py pour prod)

**`/seller/abonnement/`** (`subscription_view`)
- Liste plans MEDIUM/PRO avec prix/features
- Affiche abonnement courant + historique paiements

**`/seller/abonnement/checkout/<plan>/`** (`checkout_view`)
- Formulaire de paiement (saisie numéro téléphone)
- POST → création `SubscriptionPayment` → redirection Orange Money

**`/seller/abonnement/callback/`** (`payment_callback_view`) — `@csrf_exempt`
- Webhook asynchrone (historique)
- Lookup par `notif_token` + idempotence

### Vues stables (enregistrées chez Orange Money)

**`/billing/return/?order_id=...`** (`billing_return_view`)
- Redirection post-paiement (succès ou fail)
- Affiche page "En attente de confirmation" ou "Succès"
- Polling JS vers `payment_status_check` (custom si existent templates)

**`/billing/cancel/?order_id=...`** (`billing_cancel_view`)
- Redirection si user a cliqué "Annuler" chez Orange Money
- Marque payment.status = 'CANCELLED'

**`/billing/webhook/orange/`** (`billing_callback_view`) — `@csrf_exempt`
- Webhook asynchrone de confirmation de paiement
- Lookup par `notif_token` (sécurité)
- Idempotent (skip si déjà success)
- Log dans `WebhookLog`
- **Retourne toujours 200 OK** (même en erreur)

### Vue debug (dev only)

**`/seller/abonnement/debug-om/`** (`om_debug_view`)
- Visible seulement en DEBUG
- Affiche état config Orange Money (credentials, base URL)
- Test OAuth2 token + WebPay API

## Flow complet

```
1. User clique "Passer au plan PRO"
   ↓
2. GET /seller/abonnement/checkout/pro/ → formulaire
   ↓
3. POST {plan, phone}
   ├── Génère order_id (HF-P-xxx)
   ├── Génère notif_token (aléatoire 64 hex)
   ├── Crée SubscriptionPayment(status='pending')
   └── Appelle initiate_payment(order_id, notif_token, ...)
   ↓
4. OAuth2 token fetch (client_credentials)
   ↓
5. POST /orange-money-webpay/.../pay avec payload
   ├── order_id, notif_token, amount, return_url, cancel_url, notif_url
   └── Retour: {payment_url, ...}
   ↓
6. Redirect user vers payment_url (Orange Money page)
   ↓
7a. User paie → Orange Money POST /billing/webhook/orange/
    ├── Lookup SubscriptionPayment par notif_token
    ├── Idempotence check (skip si déjà success)
    ├── Activation abonnement (atomique)
    └── Log dans WebhookLog
    
7b. Webhook déjà reçu → idempotent skip (WebhookLog.processed=False)

7c. User retour navigateur → GET /billing/return/?order_id=xxx
    ├── Lookup par order_id (retrouver payment)
    └── Si status=success → "Confirmation reçue !"
        Sinon → page d'attente avec polling
   ↓
8. Dashboard : /seller/abonnement/ affiche nouveau plan actif + expires_at
```

## Configuration

Variables `.env` requises:

```bash
# OAuth2
ORANGE_ML_CLIENT_ID=...
ORANGE_ML_CLIENT_SECRET=...
ORANGE_ML_MERCHANT_KEY=...

# Base URL publique (HTTPS obligatoire)
ORANGE_ML_BASE_URL=https://app.hayaflash.com  # ou ngrok en dev

# Optional: URLs fixes (sinon générées automatiquement)
ORANGE_ML_RETURN_URL=https://app.hayaflash.com/billing/return/
ORANGE_ML_CANCEL_URL=https://app.hayaflash.com/billing/cancel/
ORANGE_ML_NOTIFY_URL=https://app.hayaflash.com/billing/webhook/orange/
```

## Debugging / Support

### Vérifier la config

```python
from django.conf import settings
print(f"Client ID configured: {bool(settings.ORANGE_MONEY_CLIENT_ID)}")
print(f"Base URL: {settings.ORANGE_MONEY_BASE_URL}")
```

### Consulter les webhooks reçus

```python
from subscriptions.models import WebhookLog, SubscriptionPayment
# Derniers webhooks
logs = WebhookLog.objects.all().order_by('-created_at')[:10]
for log in logs:
    print(f"{log.notif_token[:16]}... → {log.status} ({log.processed})")

# Paiements success
payments = SubscriptionPayment.objects.filter(status='success')
for p in payments:
    print(f"{p.seller} → {p.plan} activé le {p.paid_at}")
```

### Simuler un webhook (dev)

```bash
curl -X POST http://localhost:8000/billing/webhook/orange/ \
  -H "Content-Type: application/json" \
  -d '{
    "notif_token": "XXX",
    "status": "SUCCESS",
    "txnid": "YYY",
    "orderId": "HF-P-abc123"
  }'
# Logs: "Webhook already processed..." ou "Subscription activated..."
```

### Re-tester OAuth2

```python
from subscriptions.services.orange_money import _get_access_token
try:
    token = _get_access_token()
    print(f"Token OK: {token[:20]}...")
except Exception as e:
    print(f"Token error: {e}")
```

## Phase 8.1 — déployée

Migrations `0004_orange_money_security_improvements` et
`0005_rename_..._notif_t_...` appliquées sur `main` (PR #15, 17/09). Reste à
faire avant une vraie mise en prod : tester un paiement réel via ngrok en dev
(jamais fait, `ORANGE_ML_BASE_URL` exige HTTPS publique), et confirmer que
le VPS de prod aura `python manage.py migrate` dans sa checklist de déploiement
(`infra/scripts/deploy.sh` l'appelle déjà automatiquement).

## Points clés

1. **Sécurité:** `notif_token` est le secret — ne jamais le logger en clair
2. **Idempotence:** Webhook reçu 2x = traité 1x seulement (skip check)
3. **order_id ≤ 24 chars:** Validé à l'appel API (HTTP 400 sinon)
4. **@csrf_exempt:** Seulement sur `/billing/webhook/orange/`
5. **SSL toujours activé:** `requests.post(..., verify=True)`
6. **200 OK toujours:** Webhook retourne 200 même en erreur (Orange Money retry)

## Voir aussi

- `CLAUDE.md` § Orange Money Payment Integration
- `docs/ARCHITECTURE.md` § Payment Flow
- Orange Money API: https://developer.orange.com/apis/orange-money-webpay-ml
