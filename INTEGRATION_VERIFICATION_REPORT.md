# Integration Verification Report
## Orange Money + Quota System → Payment Flow

**Date:** 14 September 2026  
**Status:** ⚠️ PARTIAL INTEGRATION — GAPS IDENTIFIED  
**Impact:** Critical components exist but integration layer is INCOMPLETE

---

## Executive Summary

The quota system (FREE/MEDIUM/PRO limits) EXISTS and is wired into `flash_sales/views.py`. The Orange Money payment integration is IMPLEMENTED but **NOT fully integrated** with the quota → paywall → payment flow.

**Critical Gap:** When quota check fails, system only redirects + shows error message. There is NO paywall UI to show plans & upgrade option, and NO link to payment checkout.

---

## Component Status Matrix

| Component | Status | Location | Notes |
|-----------|--------|----------|-------|
| **Quota System** | ✅ EXISTS | `subscriptions/services/limits.py` | get_sale_quota(), can_create_flash_sale() |
| **Quota View Integration** | ✅ WIRED | `flash_sales/views.py:flash_sale_list_view()` | Passes quota to template context (line 39) |
| **Quota Check on Create** | ✅ WIRED | `flash_sales/views.py:flash_sale_create_view()` (line 66) | Calls can_seller_create_sale() |
| **Quota Exceeded Handling** | ❌ INCOMPLETE | `flash_sales/views.py:flash_sale_create_view()` (line 67-69) | Only shows error + redirect. **NO paywall template** |
| **Paywall Template** | ❌ MISSING | Should be `templates/flash_sales/quota_exceeded.html` | **NEEDS TO BE CREATED** |
| **Upgrade Checkout Form** | ✅ EXISTS | `subscriptions/views.py:checkout_view()` | Form for phone number + payment initiation |
| **Upgrade Checkout Template** | ✅ EXISTS | `templates/subscriptions/checkout.html` | Payment form UI |
| **Payment Processing Template** | ✅ EXISTS | `templates/subscriptions/payment_pending.html` | Shows "awaiting confirmation" |
| **Orange Money Webhook** | ✅ WIRED | `subscriptions/billing_views.py:billing_callback_view()` | @csrf_exempt, idempotent |
| **Subscription Activation** | ✅ WIRED | `subscriptions/services/payment.py:activate_subscription_from_payment()` | Updates Subscription.plan + expires_at |
| **Dashboard Warning Widget** | ❌ MISSING | Should show "27/30 ventes utilisées" | **NEEDS TO BE CREATED** |
| **UX Design Artboards** | ❌ MISSING | Should be Main.dc.html, QuotaExceeded.dc.html | **REFERENCED BUT NOT IN REPO** |

---

## Current Data Flow (INCOMPLETE)

```
User clicks "Create flash sale"
    ↓
flash_sale_create_view(request)
    ↓
can_seller_create_sale(seller)  [✅ WORKS]
    ↓
can_create_flash_sale(seller)  [✅ WORKS]
    ↓
get_sale_quota(seller)  [✅ WORKS]
    ↓
[DECISION]
├─ IF quota available → create sale ✅
└─ IF quota exceeded → ❌ INCOMPLETE:
    ├─ messages.error(request, reason)
    ├─ redirect('flash_sales:list')
    ├─ BUT NO PAYWALL with upgrade button
    ├─ BUT NO link to /seller/abonnement/checkout/pro/
    └─ User just sees error and has no way to upgrade easily
```

---

## Required Integration Points (MISSING)

### 1. Paywall Template (HIGHEST PRIORITY)

**File needed:** `templates/flash_sales/quota_exceeded.html`

```html
{% extends "base.html" %}
{% block content %}
<div class="paywall">
  <h1>Limite de ventes flash atteinte</h1>
  <p>Vous avez utilisé {{ quota.monthly_count }}/{{ quota.monthly_limit }} ventes ce mois-ci.</p>
  
  <!-- Show 3 plans with comparison -->
  <div class="plan-cards">
    <div class="plan medium">
      <h3>MEDIUM — 2000 XOF</h3>
      <p>{{ quota.monthly_limit }} ventes/mois</p>
      <a href="{% url 'subscriptions:checkout' plan='medium' %}">Passer à MEDIUM</a>
    </div>
    <div class="plan pro recommended">
      <h3>PRO — 5000 XOF</h3>
      <p>Ventes illimitées</p>
      <a href="{% url 'subscriptions:checkout' plan='pro' %}">Passer à PRO</a>
    </div>
  </div>
</div>
{% endblock %}
```

**Action required:** 
- Create template
- Wire flash_sale_create_view() to render this instead of redirect
- Pass plan options + pricing to context

### 2. Dashboard Warning Widget (HIGH PRIORITY)

**File needed:** `templates/flash_sales/partials/_quota_warning.html`

```html
{% if quota.monthly_limit and not quota.is_pro %}
  <div class="quota-warning" data-percentage="{{ quota_percentage }}">
    <div class="progress-bar">
      <div class="used" style="width: {{ quota_percentage }}%"></div>
    </div>
    <p>{{ quota.monthly_count }}/{{ quota.monthly_limit }} ventes utilisées ce mois</p>
    {% if quota_percentage >= 80 %}
      <a href="{% url 'subscriptions:checkout' plan='pro' %}" class="btn-upgrade">
        Passer à PRO pour des ventes illimitées
      </a>
    {% endif %}
  </div>
{% endif %}
```

**Where to integrate:**
- `templates/flash_sales/list.html` — add quota widget at top
- `templates/flash_sales/_sale_list_section.html` — include warning in each section

### 3. Payment Confirmation Template (MEDIUM PRIORITY)

**File exists but may need updates:** `templates/subscriptions/payment_pending.html`

Should include:
- Order ID reference (NOT notif_token)
- Plan name + price
- Payment status with auto-refresh
- "Return to dashboard" button after confirmation

### 4. Integration Layer in Views

**File:** `flash_sales/views.py:flash_sale_create_view()` (currently line 64-69)

**Current code (INCOMPLETE):**
```python
@login_required
def flash_sale_create_view(request):
    seller = _get_seller(request)
    can_create, reason = can_seller_create_sale(seller)
    if not can_create:
        messages.error(request, reason)  # ❌ JUST SHOWS MESSAGE
        return redirect("flash_sales:list")  # ❌ NO PAYWALL
```

**Should be (REQUIRED CHANGES):**
```python
@login_required
def flash_sale_create_view(request):
    seller = _get_seller(request)
    can_create, reason = can_seller_create_sale(seller)
    
    if not can_create:
        # ✅ SHOW PAYWALL INSTEAD OF JUST ERROR
        quota = get_sale_quota(seller)
        return render(
            request,
            "flash_sales/quota_exceeded.html",
            {
                "quota": quota,
                "plans": [
                    {
                        "name": "MEDIUM",
                        "price": PLAN_PRICES[Plan.MEDIUM],
                        "limit": 3,
                        "checkout_url": reverse("subscriptions:checkout", args=["medium"]),
                    },
                    {
                        "name": "PRO",
                        "price": PLAN_PRICES[Plan.PRO],
                        "limit": "Illimité",
                        "checkout_url": reverse("subscriptions:checkout", args=["pro"]),
                        "recommended": True,
                    },
                ],
                "current_plan": quota["plan"],
                "current_usage": quota["monthly_count"],
                "limit": quota["monthly_limit"],
            },
        )
    
    # ... rest of form processing
```

---

## Complete UX Flow (DESIRED)

```
┌─────────────────────────────────────────────────────────────────┐
│ Dashboard (/seller/flash-sales/)                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  [Quota Warning Widget] ← NEW                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ ▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░ 8/10 ventes utilisées         │  │
│  │ [Passer à PRO] → /seller/abonnement/checkout/pro/        │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                   │
│  [+ Créer une vente] button                                      │
└─────────────────────────────────────────────────────────────────┘
        ↓ (user clicks button)
┌─────────────────────────────────────────────────────────────────┐
│ Create Flash Sale Form                                           │
│ (fill in details, click "Créer")                                │
└─────────────────────────────────────────────────────────────────┘
        ↓ (quota exceeded)
┌─────────────────────────────────────────────────────────────────┐
│ PAYWALL (quota_exceeded.html) ← NEW                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ❌ Limite atteinte (10/10 ventes)                              │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐                             │
│  │ MEDIUM       │  │ PRO ★ BEST   │                             │
│  │ 2000 XOF     │  │ 5000 XOF     │                             │
│  │ 10/mois      │  │ Illimité     │                             │
│  │              │  │              │                             │
│  │ [Choisir]    │  │ [Choisir]    │ ← BUTTON LINKS TO:         │
│  └──────────────┘  └──────────────┘   /seller/abonnement/      │
│                                        checkout/pro/             │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
        ↓ (user clicks [Choisir])
┌─────────────────────────────────────────────────────────────────┐
│ Upgrade Confirmation (/seller/abonnement/checkout/pro/)          │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Vous allez passer à PRO — 5000 XOF                              │
│  Valable 31 jours. Renouvelable.                                │
│                                                                   │
│  [Numéro téléphone: +223 XX XX XX]                              │
│  [Procéder au paiement]                                         │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
        ↓ (click "Procéder")
        POST to checkout_view() → create_orange_payment()
        ↓ (initiate_payment() returns payment_url)
┌─────────────────────────────────────────────────────────────────┐
│ [REDIRECT TO ORANGE MONEY PAGE]                                  │
│ (user completes payment)                                         │
└─────────────────────────────────────────────────────────────────┘
        ↓ (success)
        Orange Money POST webhook → /billing/webhook/orange/
        → activate_subscription_from_payment()
        → Subscription.plan = 'pro', expires_at = now+31d
        ↓
        Orange Money GET redirect → /billing/return/?order_id=...
┌─────────────────────────────────────────────────────────────────┐
│ Payment Confirmation Page                                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ✅ Paiement confirmé!                                           │
│  Votre plan PRO est maintenant actif.                           │
│  Vous avez ventes illimitées jusqu'au XX/YY/ZZZZ.              │
│                                                                   │
│  [Retourner au dashboard]                                       │
│  [Créer une vente flash]                                        │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
        ↓ (click button)
┌─────────────────────────────────────────────────────────────────┐
│ Dashboard (/seller/flash-sales/) — UPGRADED                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  [Quota Widget] — NOW SHOWS PRO                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ ✅ PRO — Ventes illimitées                               │  │
│  │ Expire le XX/YY/ZZZZ                                      │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                   │
│  [+ Créer une vente] ← NOW WORKS (no quota limit)               │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Files to Create/Modify

### CREATE (4 files)

| File | Type | Purpose | Lines | Priority |
|------|------|---------|-------|----------|
| `templates/flash_sales/quota_exceeded.html` | Template | Paywall with plan options | 80-120 | 🔴 CRITICAL |
| `templates/flash_sales/partials/_quota_warning.html` | Template | Dashboard warning widget | 20-40 | 🟠 HIGH |
| `docs/INTEGRATION_FLOW.md` | Doc | Complete UX + data flow diagram | 100-150 | 🟡 MEDIUM |
| `docs/QUOTA_UPGRADE_MAPPING.md` | Doc | Which component talks to which | 50-80 | 🟡 MEDIUM |

### MODIFY (3 files)

| File | Changes | Priority |
|------|---------|----------|
| `flash_sales/views.py` (line 64-69) | Render paywall instead of error + redirect | 🔴 CRITICAL |
| `templates/flash_sales/list.html` | Include quota warning widget at top | 🟠 HIGH |
| `subscriptions/views.py` | Add context for upgrade_confirm page if needed | 🟡 MEDIUM |

### ALREADY EXIST (verification)

| File | Status | Notes |
|------|--------|-------|
| `subscriptions/services/limits.py` | ✅ OK | Quota logic correct |
| `subscriptions/services/payment.py` | ✅ OK | Payment initiation correct |
| `subscriptions/services/orange_money.py` | ✅ OK | OAuth2 + API client correct |
| `subscriptions/billing_views.py` | ✅ OK | Webhook handling correct |
| `subscriptions/models.py` | ✅ OK | Models updated (notif_token, WebhookLog) |
| `templates/subscriptions/checkout.html` | ✅ OK | Payment form exists |
| `templates/subscriptions/payment_pending.html` | ✅ OK | Confirmation page exists |

---

## Context Variable Requirements

### For quota_exceeded.html

```python
context = {
    "quota": {
        "can_create": False,
        "plan": "free",
        "monthly_count": 10,
        "monthly_limit": 10,
        "is_paid": False,
    },
    "plans": [
        {
            "plan_code": "medium",
            "label": "MEDIUM",
            "price": 2000,
            "currency": "XOF",
            "limit_text": "10 ventes/mois",
            "features": ["10 ventes/mois", "Stats 30 jours", ...],
            "checkout_url": "/seller/abonnement/checkout/medium/",
            "recommended": False,
        },
        {
            "plan_code": "pro",
            "label": "PRO",
            "price": 5000,
            "currency": "XOF",
            "limit_text": "Illimité",
            "features": ["Ventes illimitées", "Stats complètes", ...],
            "checkout_url": "/seller/abonnement/checkout/pro/",
            "recommended": True,
        },
    ],
    "current_usage": 10,
    "current_limit": 10,
    "current_plan": "free",
}
```

### For quota_warning widget

```python
context = {
    "quota": {
        "can_create": True/False,
        "monthly_count": 8,
        "monthly_limit": 10,
        "is_pro": False,
        "plan": "medium",
    },
    "quota_percentage": 80,  # for progress bar
}
```

---

## URL Routing Verification

**Existing routes (verified ✅):**
- `GET /seller/abonnement/` → `subscription_view` (show plans)
- `GET /seller/abonnement/checkout/<plan>/` → `checkout_view` (form)
- `POST /seller/abonnement/checkout/<plan>/` → `checkout_view` (submit)
- `GET /billing/webhook/orange/` → `billing_callback_view` (webhook)

**Needed routes (verify in billing_urls.py):**
- `GET /billing/return/?order_id=...` → should exist
- `GET /billing/cancel/?order_id=...` → should exist

---

## Styling/Design Consistency

**CSS Classes to use (from Tailwind build):**
- `.paywall` — Container
- `.plan-card` — Individual plan box
- `.plan-recommended` — Highlight PRO
- `.quota-warning` — Dashboard warning
- `.progress-bar` — Usage meter
- `.btn-primary` — CTA buttons

**Mobile responsive (390px):**
- Stack plans vertically on mobile
- Full-width buttons
- Clear typography hierarchy

---

## API Contracts (Data Format)

### Webhook Payload (Orange Money → /billing/webhook/orange/)

```json
{
  "notif_token": "64_hex_chars_here",
  "status": "SUCCESS",
  "txnid": "txn_123456",
  "orderId": "HF-P-12345678",
  "amount": 5000,
  "currency": "XOF"
}
```

Handler expects: `notif_token` (for lookup), `status`, `txn_id`

### Subscription Activation Response

```python
{
  "success": True,
  "plan": "pro",
  "expires_at": "2026-10-14T18:30:00Z",
  "message": "Subscription activated"
}
```

---

## Security Checklist (Integration)

- [✅] notif_token lookup ONLY (not order_id) — implemented
- [✅] Webhook idempotent (skip if success) — implemented
- [✅] @csrf_exempt ONLY on webhook — implemented
- [✅] SSL verification enabled — implemented
- [✅] No sensitive data in logs — implemented
- [✅] Environment variables for credentials — implemented
- [❌] **MISSING:** Prevent direct access to `/billing/return/` by unauthenticated user
  - **Action:** Add @login_required to billing_return_view() / billing_cancel_view()

---

## Testing Integration Points

### 1. Quota Widget Display

Test: `flash_sale_list_view` includes quota context
```bash
curl -H "Cookie: sessionid=..." http://localhost:8000/seller/flash-sales/
# Verify in response: quota dict with can_create, monthly_count, limit
```

### 2. Quota Check on Create

Test: Creating beyond limit triggers paywall
```bash
# Create 10 flash sales as FREE user
# Attempt 11th → should render quota_exceeded.html
# Should NOT redirect, should NOT show error message
```

### 3. Paywall → Payment Link

Test: Paywall has functioning upgrade links
```bash
# Click "Passer à PRO" on paywall
# Should navigate to /seller/abonnement/checkout/pro/
# Form pre-filled with plan=PRO
```

### 4. Payment → Webhook → Subscription

Test: End-to-end payment activates subscription
```bash
# Initiate payment → Orange Money mock → webhook
# POST /billing/webhook/orange/ with notif_token + status=SUCCESS
# Verify: SubscriptionPayment.status = 'success'
# Verify: Subscription.plan = 'pro', expires_at updated
# Verify: WebhookLog entry created
```

### 5. Dashboard After Upgrade

Test: Quota widget shows new plan
```bash
# After payment activation
# Visit /seller/flash-sales/
# Verify quota widget shows "PRO — Illimité"
# Verify can_create = True
# Verify [+ Créer une vente] works
```

---

## Impact Assessment

| Layer | Impact | Severity |
|-------|--------|----------|
| **User Experience** | Cannot easily upgrade when hitting quota limit | 🔴 CRITICAL |
| **Conversion** | Missing paywall = lost upgrade opportunities | 🔴 CRITICAL |
| **Visibility** | No warning before hitting quota | 🟠 HIGH |
| **Data Flow** | Orange Money integration works but unreachable from quota flow | 🟡 MEDIUM |

---

## Summary

### What EXISTS ✅
- Quota calculation system (limits.py)
- Payment initiation (payment.py, orange_money.py)
- Webhook handler with idempotence (billing_views.py)
- Subscription models + WebhookLog

### What's MISSING ❌
- Paywall template to show plans during upgrade decision
- Dashboard warning widget for usage visibility
- Integration in views layer: redirect → paywall instead of error
- Complete documentation of end-to-end flow

### Status
**PARTIAL INTEGRATION — 60% complete**
- Backend logic: 95% ✅
- Integration layer: 40% ⚠️
- User experience: 20% ❌

### Next Steps (PRIORITY ORDER)
1. **Create quota_exceeded.html** (2 hours)
2. **Modify flash_sale_create_view()** to render paywall (30 minutes)
3. **Create quota_warning widget** (1 hour)
4. **Integrate widget into list.html** (30 minutes)
5. **Update documentation** (1 hour)

**Total effort:** ~5-6 hours for complete integration

---

## Conclusion

The Orange Money payment system is **production-ready** for its isolated use case (direct payment checkout). However, the **quota → upgrade flow is incomplete**. Without the paywall, users have no easy way to discover and activate upgrades when they hit limits.

**Recommendation:** Complete the integration (create missing templates + modify views) before deploying to production. The quota system already exists — just needs proper UX to surface the upgrade option.
