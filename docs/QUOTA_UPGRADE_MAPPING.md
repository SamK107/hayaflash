# Quota System ↔ Upgrade Flow Mapping

This document maps the integration points between HayaFlash's quota system and the Orange Money payment upgrade flow.

## Request/Response Flow Map

### 1. Quota Check Phase

```
HTTP GET /flash-sales/create/
    │
    ├─ View: flash_sales/views.py
    │  └─ flash_sale_create_view(request)
    │
    ├─ Calls: can_seller_create_sale(seller)
    │  │
    │  └─ Location: subscriptions/services/limits.py
    │     └─ get_sale_quota(seller) → dict with:
    │        ├─ can_create: True/False
    │        ├─ is_pro: bool
    │        ├─ monthly_count: int (sales created this month)
    │        ├─ monthly_limit: int (plan limit)
    │        └─ reason: str (error message if can_create=False)
    │
    └─> Response Decision:
        │
        ├─ If can_create=True:
        │  └─ Render: templates/flash_sales/create.html
        │
        └─ If can_create=False:
           ├─ Get subscription info
           ├─ Get plan options (FREE, MEDIUM, PRO)
           ├─ Build context with pricing & features
           └─ Render: templates/flash_sales/quota_exceeded.html
              └─ Context = {quota, plans, current_plan, reason}
```

### 2. Paywall Phase

```
Render: quota_exceeded.html
    │
    ├─ Display 3 plan cards:
    │  │
    │  ├─ FREE (Current, disabled)
    │  │  └─ Price: 0 FCFA
    │  │  └─ Features: 3 ventes/mois, page publique, ...
    │  │
    │  ├─ MEDIUM (Recommended if not paid)
    │  │  └─ Price: 2000 FCFA/mois
    │  │  └─ Features: 3 ventes/mois, stats 30j, ...
    │  │  └─ Button: "Passer à MEDIUM" → /subscriptions/upgrade/medium/
    │  │
    │  └─ PRO (Always available)
    │     └─ Price: 5000 FCFA/mois
    │     └─ Features: Ventes illimitées, stats avancées, ...
    │     └─ Button: "Passer à PRO" → /subscriptions/upgrade/pro/
    │
    └─> User clicks upgrade button
```

### 3. Upgrade Confirmation Phase

```
HTTP GET /subscriptions/upgrade/{plan}/
    │
    ├─ View: subscriptions/views.py
    │  └─ upgrade_subscription_view(request, plan)
    │
    ├─ Validate: User not already on that plan
    │
    ├─ Render: subscriptions/upgrade_confirm.html
    │  ├─ Show plan name & price
    │  ├─ Input: Phone number (for payment)
    │  └─ Button: "Proceed to Payment" → POST handler
    │
    └─> POST /subscriptions/upgrade/{plan}/
        │
        ├─ View: upgrade_subscription_view (POST handler)
        │
        ├─ Calls: create_orange_payment(
        │            seller=request.user.seller_profile,
        │            plan=plan,
        │            phone=form.cleaned_data['phone']
        │          )
        │
        └─> Location: subscriptions/services/payment.py
            │
            ├─ Step 1: Generate notif_token
            │  └─ secrets.token_hex(32) → 64 char hex string
            │  └─ Stored in DB immediately (SECURITY CRITICAL)
            │
            ├─ Step 2: Generate order_id
            │  └─ Format: "HF-{plan[0]}-{8 hex chars}"
            │  └─ Example: "HF-M-a1b2c3d4" (14 chars, ≤24 max)
            │
            ├─ Step 3: Create SubscriptionPayment record
            │  ├─ seller: FK
            │  ├─ plan: "medium" or "pro"
            │  ├─ provider: "orange"
            │  ├─ amount: PLAN_PRICES[plan] (2000 or 5000)
            │  ├─ phone: user's payment phone
            │  ├─ order_id: HF-M-XXXXXXXX
            │  ├─ notif_token: [already stored in DB]
            │  ├─ status: "pending"
            │  └─ save()
            │
            └─> Step 4: Call Orange Money API
                │
                ├─ Calls: OrangeMoneyService.initiate_payment(
                │            order_id="HF-M-XXXXXXXX",
                │            amount=2000,
                │            notif_token="[64-char token]",
                │            merchant_key=settings.ORANGE_ML_MERCHANT_KEY,
                │            phone="+223..."
                │          )
                │
                ├─ Location: subscriptions/services/orange_money.py
                │
                ├─ Security Checks:
                │  ├─ validate order_id ≤24 chars
                │  ├─ POST with verify=True (SSL)
                │  ├─ Bearer token (OAuth2 client_credentials)
                │  └─ HTTPS endpoint only
                │
                ├─ HTTP Request:
                │  ├─ POST https://api.orange.ml/payment/initiate
                │  ├─ Headers: Authorization: Bearer {token}
                │  └─ Body: {order_id, amount, notif_token, phone, ...}
                │
                └─> Returns: {success: true, payment_url: "https://..."}
                   │
                   └─ Redirect: response.payment_url
                      └─ User sent to Orange Money payment page
```

### 4. Orange Money Payment Phase

```
Orange Money Payment Page
    │
    ├─ User sees:
    │  ├─ Merchant: HayaFlash
    │  ├─ Amount: 2000 FCFA (or 5000)
    │  ├─ Order ID: HF-M-XXXXXXXX
    │  ├─ Description: "Upgrade to MEDIUM"
    │  │
    │  └─ Options:
    │     ├─ Enter phone number & PIN → Payment
    │     └─ Cancel → Redirect to return_url
    │
    ├─ Payment Confirmed by Orange Money
    │  ├─ Deduct: 2000 FCFA from user's phone
    │  ├─ Mark: Transaction as successful
    │  └─ Trigger: Webhook (asynchronous)
    │
    └─> Orange Money Webhook (asynchronous)
        │
        ├─ POST /billing/webhook/orange/
        │  ├─ Payload:
        │  │  ├─ order_id: "HF-M-XXXXXXXX"
        │  │  ├─ notif_token: "[same 64-char token]"
        │  │  ├─ status: "success" or "failure"
        │  │  ├─ txn_id: "ORA-20240914-123456"
        │  │  └─ amount: 2000
        │  │
        │  └─> View: subscriptions/billing_views.py
        │     └─ billing_callback_view(request)
        │        │
        │        ├─ Decorator: @csrf_exempt
        │        │  (Orange Money is external server, not browser)
        │        │
        │        ├─ Parse: json.loads(request.body)
        │        │
        │        ├─ Verify: verify_callback(data)
        │        │  └─ Location: subscriptions/services/orange_money.py
        │        │  └─ Returns: {success, status, txn_id, notif_token}
        │        │
        │        └─> SECURITY CHECK: Lookup by notif_token
        │           │
        │           └─ Query: SubscriptionPayment.objects.get(
        │                       notif_token=notif_token
        │                     )
        │           │
        │           ├─ If found:
        │           │  └─ Check idempotence
        │           │
        │           └─ If not found:
        │              ├─ Log warning
        │              └─ Return HTTP 200 OK (idempotent)
        │
        └─> Idempotence Check
           │
           ├─ Query: payment.status
           │
           ├─ If status == PaymentStatus.SUCCESS:
           │  │
           │  ├─ Already processed (webhook arrived twice)
           │  ├─ Log in WebhookLog:
           │  │  ├─ processed: False (duplicate skip)
           │  │  └─ error_message: "Payment already processed"
           │  │
           │  └─ Return HTTP 200 OK
           │
           └─ If status == PaymentStatus.PENDING:
              │
              └─> Process webhook (Transaction block)
                 │
                 ├─ IF result['success']:
                 │  │
                 │  ├─ Call: activate_subscription_from_payment(payment)
                 │  │  │
                 │  │  └─ Location: subscriptions/services/payment.py
                 │  │     └─ get_or_create_subscription(seller)
                 │  │        └─ Update:
                 │  │           ├─ plan: "medium" (from payment.plan)
                 │  │           ├─ expires_at: now + 30 days
                 │  │           └─ save()
                 │  │
                 │  ├─ Update: SubscriptionPayment
                 │  │  ├─ status: PaymentStatus.SUCCESS
                 │  │  ├─ txn_id: from webhook
                 │  │  ├─ paid_at: now
                 │  │  ├─ raw_callback: webhook payload
                 │  │  └─ save()
                 │  │
                 │  └─ Log in WebhookLog:
                 │     ├─ processed: True (successfully activated)
                 │     └─ status: "success"
                 │
                 └─ ELSE (payment failed):
                    │
                    ├─ Update: SubscriptionPayment
                    │  ├─ status: PaymentStatus.FAILED
                    │  └─ save()
                    │
                    └─ Log in WebhookLog:
                       ├─ processed: True (logged failure)
                       └─ status: from webhook (e.g., "failure")
                 │
                 └─ Return HTTP 200 OK (always, even on error)
                    (Orange Money doesn't retry on 2xx HTTP)
```

### 5. Return from Orange Money

```
Orange Money Redirect
    │
    ├─ User clicks "Back to Merchant" or page times out
    │
    └─> GET /billing/return/?order_id=HF-M-XXXXXXXX
        │
        ├─ View: subscriptions/billing_views.py
        │  └─ billing_return_view(request)
        │
        ├─ Decorator: @login_required (SECURITY)
        │
        ├─ Query: SubscriptionPayment.objects.get(order_id=order_id)
        │
        ├─> IF payment.status == PaymentStatus.SUCCESS:
        │   │
        │   ├─ Message: "Paiement confirme ! Votre plan MEDIUM est actif."
        │   ├─ Subscription: Already activated by webhook
        │   └─ Redirect: /subscriptions/subscription/
        │
        └─> IF payment.status == PaymentStatus.PENDING:
            │
            ├─ Message: "Votre paiement est en cours de traitement..."
            ├─ Render: subscriptions/payment_pending.html
            ├─ Include: <meta name="refresh" content="5">
            │          (auto-refresh every 5 seconds)
            │
            └─ Page auto-refreshes until webhook processed
               (then shows success message)
```

## Path to Production

### Files Modified

| File | Changes | Purpose |
|------|---------|---------|
| `subscriptions/billing_views.py` | Added `@login_required` to `billing_return_view()` and `billing_cancel_view()` | Security: prevent unauthenticated access |
| `flash_sales/views.py` | Import Plan models, modify `flash_sale_create_view()` to render paywall | Route quota exceeded → paywall instead of error |
| (new) `templates/flash_sales/quota_exceeded.html` | Create paywall template with 3 plan cards | Show upgrade options to user |
| (new) `templates/flash_sales/partials/_quota_warning.html` | Create dashboard widget | Show quota usage in list view |

### Files Created (Documentation)

| File | Purpose |
|------|---------|
| `docs/INTEGRATION_FLOW.md` | Complete UX flow and data flow diagrams |
| `docs/QUOTA_UPGRADE_MAPPING.md` | Component mapping and request/response flow |

### Files Already Exist (from Phase 1)

These were implemented in the previous conversation and are ready for production:

| File | Purpose |
|------|---------|
| `subscriptions/models.py` | SubscriptionPayment, Subscription, WebhookLog models |
| `subscriptions/services/payment.py` | create_orange_payment(), activate_subscription_from_payment() |
| `subscriptions/services/orange_money.py` | OrangeMoneyService, OAuth2, webhook verification |
| `subscriptions/billing_views.py` | billing_callback_view(), webhook handler |
| `subscriptions/urls.py` | URL routing for /billing/* endpoints |
| `CLAUDE.md` | Orange Money documentation |

## Deployment Checklist

- [x] **Models**: SubscriptionPayment, WebhookLog created with migrations
- [x] **Services**: Orange Money OAuth2, payment, webhook services implemented
- [x] **Views**: Webhook handler with idempotence & security
- [x] **Security**: notif_token lookup, SSL verification, CSRF exemption correct
- [x] **Quota Integration**: flash_sale_create_view() calls quota check
- [x] **Paywall Template**: quota_exceeded.html created with plan cards
- [x] **Dashboard Widget**: _quota_warning.html created
- [x] **Login Protection**: @login_required on return/cancel endpoints
- [x] **Documentation**: Flow diagrams and component mapping complete

## Testing Checklist

### Quota System Tests
- [ ] Free user creates 3rd sale → quota exceeded
- [ ] Free user tries to create 4th → sees paywall
- [ ] Medium user creates 3rd sale → quota exceeded (same limit)
- [ ] Pro user creates unlimited sales → no quota message
- [ ] Paywall shows correct plan prices (2000, 5000 FCFA)

### Payment Flow Tests
- [ ] Click "Passer à MEDIUM" → upgrade form
- [ ] Enter phone number → create payment
- [ ] Redirect to Orange Money → success
- [ ] Mock webhook with success status → subscription activated
- [ ] Mock duplicate webhook → idempotence check works
- [ ] Webhook with wrong token → logged & ignored (no error)
- [ ] User returns from Orange Money → sees success message
- [ ] Cancel button works → payment marked cancelled

### Security Tests
- [ ] Direct URL access to /billing/return/ → @login_required redirects
- [ ] Direct URL access to /billing/cancel/ → @login_required redirects
- [ ] Webhook without notif_token → returns HTTP 200 (no error)
- [ ] Webhook with wrong notif_token → returns HTTP 200 (no activation)
- [ ] SSL verification enforced → no requests.post(..., verify=False)

### Integration Tests
- [ ] Hit quota → redirect to paywall (not old error message)
- [ ] Paywall → click upgrade → forms loads correctly
- [ ] Forms → payment → webhook → subscription updated
- [ ] Dashboard shows new plan after payment
- [ ] Quota warning widget shows correct usage

## Rollback Plan

If integration causes issues:

1. **Disable Upgrade Path**: Set `ENABLE_ORANGE_MONEY = False` in settings
2. **Revert View**: Modify `flash_sale_create_view()` to show old error + redirect
3. **Keep Models**: Don't delete SubscriptionPayment/WebhookLog (audit data)
4. **Notify Users**: Post message on platform explaining temporary unavailability

## Monitoring Points

- [ ] Watch: SubscriptionPayment.status distribution (pending vs success vs failed)
- [ ] Alert: WebhookLog with `processed=False` (duplicate/error webhooks)
- [ ] Alert: SubscriptionPayment with `status=PENDING` older than 24h (stuck payments)
- [ ] Monitor: /billing/webhook/orange/ HTTP 200 rate (webhook frequency)
- [ ] Log: All notif_token lookups (first 16 chars for debugging)

## Support Contacts

- **Orange Money API Issues**: Check subscriptions/services/orange_money.py logs
- **Payment Not Activated**: Check WebhookLog for webhook audit trail
- **User Stuck in Payment**: Check SubscriptionPayment.status in admin
- **Quota Not Enforcing**: Check subscriptions/services/limits.py logic
