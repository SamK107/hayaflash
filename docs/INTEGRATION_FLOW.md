# Orange Money Payment Integration Flow

## Overview

This document describes the complete integration between HayaFlash's quota system and the Orange Money payment system, showing how users are guided from quota limits to subscription upgrades.

## Complete User Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│ USER FLOW: Quota Exceeded → Paywall → Payment → Subscription Activated  │
└─────────────────────────────────────────────────────────────────────────┘

1. USER INITIATES FLASH SALE CREATION
   │
   ├─ Opens: /flash-sales/create/
   ├─ View: flash_sales/views.py::flash_sale_create_view()
   │
   └─> Calls: can_seller_create_sale(seller)
       │
       └─> Returns: (can_create: bool, reason: str)
           │
           └─ Source: subscriptions/services/limits.py::can_create_flash_sale()

2. QUOTA CHECKED
   │
   ├─ Function: get_sale_quota(seller)
   │  ├─ Retrieves: Subscription.plan
   │  ├─ Counts: FlashSale objects created this month
   │  └─ Compares: monthly_count >= PLAN_MONTHLY_SALES_LIMIT[plan]
   │
   └─ Quota Limits (PLAN_MONTHLY_SALES_LIMIT):
      ├─ FREE: 3/month
      ├─ MEDIUM: 3/month
      └─ PRO: unlimited (None)

3. QUOTA EXCEEDED
   │
   ├─ If can_create == False:
   │
   └─> Render Paywall Template (NO error message + redirect)
       │
       ├─ Template: templates/flash_sales/quota_exceeded.html
       ├─ Context includes:
       │  ├─ quota: {monthly_count, monthly_limit, plan, ...}
       │  ├─ plans: [
       │  │    {key, label, price, features, is_current, recommended}
       │  │  ]
       │  ├─ current_plan: seller's current plan
       │  └─ reason: quota exceeded message
       │
       └─ UI Layout:
          ├─ Header: "Vous avez atteint votre limite mensuelle"
          ├─ 3 Plan Cards:
          │  ├─ FREE (current, disabled)
          │  ├─ MEDIUM (recommended, has CTA button)
          │  └─ PRO (has CTA button)
          └─ Each card shows:
             ├─ Plan name & price (2000 FCFA for MEDIUM, 5000 for PRO)
             ├─ Feature list
             └─ Action button:
                ├─ "Plan actuel" (disabled) if current
                └─ "Passer à [Plan]" → /subscriptions/upgrade/{plan}/

4. USER CLICKS UPGRADE
   │
   ├─ Clicks: "Passer à MEDIUM" or "Passer à PRO" button
   ├─ Destination: /subscriptions/upgrade/{plan}/
   │
   └─> View: subscriptions/views.py::upgrade_subscription_view()
       │
       ├─ Validates: seller can upgrade (not already on that plan)
       ├─ Renders: subscriptions/upgrade_confirm.html
       │  ├─ Confirms upgrade to [Plan]
       │  ├─ Shows final price (PLAN_PRICES[plan])
       │  ├─ Phone number field for payment
       │  └─ "Proceed to Payment" button
       │
       └─> POST handler creates payment:
           │
           └─> Function: create_orange_payment(seller, plan, phone)
               │
               ├─ Step 1: Generate notif_token (secrets.token_hex(32) = 64 hex chars)
               ├─ Step 2: Store notif_token BEFORE API call (SECURITY CRITICAL)
               ├─ Step 3: Generate order_id (format: "HF-{plan[0]}-{8 hex chars}")
               ├─ Step 4: Create SubscriptionPayment record:
               │  ├─ seller: FK to SellerProfile
               │  ├─ plan: target plan (MEDIUM or PRO)
               │  ├─ provider: "orange"
               │  ├─ amount: PLAN_PRICES[plan]
               │  ├─ phone: seller's payment phone
               │  ├─ order_id: unique, ≤24 chars
               │  ├─ notif_token: stored in DB (db_index=True)
               │  ├─ status: PaymentStatus.PENDING
               │  └─ created_at: now
               │
               └─> Step 5: Call Orange Money API
                   │
                   ├─ Function: OrangeMoneyService.initiate_payment()
                   ├─ Parameters:
                   │  ├─ order_id: HF-M-XXXXXXXX
                   │  ├─ amount: 2000 (FCFA)
                   │  ├─ notif_token: (passed from create_orange_payment)
                   │  ├─ merchant_key: from .env
                   │  └─ redirect_urls (return/cancel/notify)
                   │
                   ├─ Calls: POST https://api.orange.ml/payment/initiate
                   │  ├─ SSL verification: ALWAYS verify=True
                   │  ├─ OAuth2: client_credentials flow for Bearer token
                   │  └─ Payload includes: order_id, amount, notif_token, phone
                   │
                   └─ Returns: payment_url (Orange Money payment page)

5. REDIRECT TO ORANGE MONEY
   │
   ├─ Redirect: payment_url (from Orange Money API)
   └─> User sees: Orange Money payment page
       ├─ Merchant: HayaFlash
       ├─ Amount: 2000 FCFA (or 5000 for PRO)
       ├─ Order ID: HF-M-XXXXXXXX
       └─ Options:
          ├─ Complete payment → Orange Money processes
          └─ Cancel → Orange Money redirects to /billing/cancel/

6. ORANGE MONEY PROCESSES PAYMENT
   │
   └─> User enters phone & PIN, payment confirmed
       │
       ├─ Status: success/failed
       ├─ Transaction ID: returned by Orange Money
       │
       └─> Orange Money triggers WEBHOOK (asynchronous)

7. WEBHOOK ARRIVES AT HAYAFLASH
   │
   ├─ Endpoint: POST /billing/webhook/orange/
   ├─ View: subscriptions/billing_views.py::billing_callback_view()
   ├─ Decorators:
   │  ├─ @csrf_exempt (ONLY on webhook, not on return/cancel)
   │  └─ @require_POST
   │
   ├─ Payload from Orange Money:
   │  ├─ order_id: HF-M-XXXXXXXX
   │  ├─ notif_token: [same 64-char token from step 4]
   │  ├─ status: "success" or "failure"
   │  ├─ txn_id: transaction ID
   │  └─ [other fields]
   │
   └─> Security Check (CRITICAL):
       │
       ├─ Lookup by notif_token ONLY (never by order_id)
       │  │
       │  ├─ Why: notif_token is secret, stored in DB at creation
       │  ├─ Security: only payments we created can be activated
       │  └─ Query: SubscriptionPayment.objects.get(notif_token=notif_token)
       │
       └─ If payment not found:
          │
          ├─ Log warning
          └─ Return HTTP 200 OK (idempotent, no error to Orange Money)

8. IDEMPOTENCE CHECK
   │
   ├─ If payment.status == PaymentStatus.SUCCESS:
   │  │
   │  ├─ Already processed (webhook arrived twice)
   │  ├─ Log in WebhookLog with processed=False
   │  └─ Return HTTP 200 OK (no re-activation)
   │
   └─ If payment.status == PaymentStatus.PENDING:
       │
       └─> Process webhook (continue to step 9)

9. WEBHOOK PROCESSING (ATOMIC TRANSACTION)
   │
   ├─ Transaction: database.atomic()
   │  │
   │  ├─ Update SubscriptionPayment:
   │  │  ├─ status: PaymentStatus.SUCCESS (if status==success)
   │  │  ├─ txn_id: from webhook
   │  │  ├─ paid_at: now
   │  │  └─ raw_callback: webhook payload (JSON)
   │  │
   │  ├─ Activate Subscription:
   │  │  │
   │  │  └─> Call: activate_subscription_from_payment(payment)
   │  │      │
   │  │      ├─ Gets/creates: Subscription(seller=seller)
   │  │      ├─ Updates:
   │  │      │  ├─ plan: from payment.plan (MEDIUM or PRO)
   │  │      │  ├─ expires_at: now + 30 days (configurable)
   │  │      │  ├─ updated_at: now
   │  │      │  └─ save()
   │  │      │
   │  │      └─ Subscription now active
   │  │
   │  └─ Log success in WebhookLog:
       │     ├─ payment: FK to SubscriptionPayment
       │     ├─ notif_token: from webhook
       │     ├─ status: "success"
       │     ├─ txn_id: from webhook
       │     ├─ raw_payload: full webhook data
       │     ├─ processed: True (successfully processed)
       │     └─ created_at: now
       │
       └─ Return HTTP 200 OK

10. USER RETURNS FROM ORANGE MONEY
    │
    ├─ User clicks "Back to Merchant" or closes payment page
    ├─ Orange Money redirects to: /billing/return/?order_id=HF-M-XXXXXXXX
    │
    └─> View: subscriptions/billing_views.py::billing_return_view()
        ├─ Decorator: @login_required (SECURITY)
        │
        ├─ Query: SubscriptionPayment.objects.get(order_id=order_id)
        │
        └─ If status == SUCCESS:
           │
           ├─ Message: "Paiement confirme ! Votre plan MEDIUM est actif."
           └─ Redirect: /subscriptions/subscription/

11. SUBSCRIPTION ACTIVE
    │
    └─> Dashboard shows:
        ├─ Current plan: "MEDIUM" (with expiration date)
        ├─ Quota message: "3/3 ventes utilisées" (same limit for MEDIUM)
        └─ Option to upgrade to PRO (unlimited)

        Note: User still has same 3/month limit on MEDIUM
              This is intentional (MEDIUM features other analytics)
              PRO plan provides unlimited sales + advanced features
```

## Data Flow Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        HAYAFLASH ARCHITECTURE                            │
└──────────────────────────────────────────────────────────────────────────┘

                          FLASH SALES MODULE
                                  │
                    ┌─────────────┴─────────────┐
                    │                           │
           flash_sale_create_view()    quota_exceeded.html
                    │                           │
                    └─────────────┬─────────────┘
                                  │
                        can_seller_create_sale()
                                  │
                ┌─────────────────┴────────────────────┐
                │                                      │
        subscriptions.services.limits                quota check
                │                                      │
        ┌───────┴────────────┐                        │
        │                    │                        │
    is_pro?          monthly_count >= limit    render paywall
                      │
                ┌─────┴─────────────────┐
                │                       │
            YES: can create         NO: show paywall
                │                       │
        continue form          quota_exceeded.html
                                        │
                                 (3 plan cards)
                                        │
                          ┌─────────┬───┴───┬─────────┐
                          │         │       │         │
                       FREE      MEDIUM   PRO      buttons
                      disabled   upgrade  upgrade
                                (CTA)    (CTA)
                                  │
                                  └──────────────┐
                                                 │
                         /subscriptions/upgrade/{plan}/
                                                 │
                         subscriptions/views.py upgrade_subscription_view()
                                                 │
                         ┌────────────────────────┴────────────────┐
                         │                                         │
                upgrade_confirm.html template          create_orange_payment()
                (phone input form)                               │
                                                    ┌────────────┴────────────┐
                                                    │                         │
                                        Store notif_token in DB        OrangeMoneyService
                                                    │                    .initiate_payment()
                                        Create SubscriptionPayment          │
                                        (status=PENDING)              OAuth2 token
                                                    │                    │
                                                    │              POST https://
                                                    │              api.orange.ml/
                                                    │              payment/initiate
                                                    │                    │
                                                    │              Returns payment_url
                                                    │                    │
                                                    └────────────────────┴──────────┐
                                                                                    │
                                                               Redirect to Orange Money
                                                               (user enters phone & PIN)
                                                                                    │
                                                                    Orange Money: Payment Processed
                                                                    │
                                                    ┌───────────────┴────────────────────┐
                                                    │                                    │
                                            status: success                    status: failure
                                                    │                                    │
                                     Webhook POST /billing/webhook/orange/
                                                    │
                                        billing_callback_view()
                                                    │
                        ┌───────────────────────────┼───────────────────────────┐
                        │                           │                           │
                    Parse payload            Lookup by notif_token      Verify callback
                    Verify webhook              (SECURITY)                │
                        │                           │                   Returns {success,
                        │                    If found:                   txn_id, status}
                        │                    │                           │
                        │                activate_subscription_from_payment()
                        │                    │                           │
                        │            Update Subscription:                │
                        │            ├─ plan: MEDIUM                     │
                        │            ├─ expires_at: now+30d             │
                        │            └─ save()                          │
                        │                    │                           │
                        │            Log in WebhookLog                   │
                        │            ├─ status: success                  │
                        │            ├─ processed: True                  │
                        │            └─ created_at: now                  │
                        │                    │                           │
                        └────────────────────┼───────────────────────────┘
                                             │
                                    Return HTTP 200 OK
                                    (always, even on error)
                                             │
                                  User redirected to /billing/return/
                                  (Orange Money or user action)
                                             │
                                  billing_return_view()
                                  ├─ @login_required
                                  ├─ Query: SubscriptionPayment by order_id
                                  ├─ If status == SUCCESS:
                                  │  ├─ Success message
                                  │  └─ Redirect: /subscriptions/subscription/
                                  └─ If status == PENDING:
                                     └─ Show payment_pending.html
                                        (auto-refresh waiting for webhook)
```

## Component Relationships

| Component | Role | Talks To |
|-----------|------|----------|
| `flash_sale_create_view()` | Check quota before allowing form | `can_seller_create_sale()` |
| `quota_exceeded.html` | Display paywall with plan options | None (static template) |
| `can_seller_create_sale()` | Determine if user can create (quota check) | `get_sale_quota()` |
| `get_sale_quota()` | Count monthly sales, check limits | `Subscription`, `FlashSale` models |
| `upgrade_subscription_view()` | Handle upgrade form submission | `create_orange_payment()` |
| `create_orange_payment()` | Create payment record & initiate payment | `OrangeMoneyService.initiate_payment()` |
| `OrangeMoneyService` | Call Orange Money API | Orange Money API endpoint |
| `billing_callback_view()` | Handle webhook from Orange Money | `activate_subscription_from_payment()` |
| `activate_subscription_from_payment()` | Activate subscription on payment success | `Subscription` model |
| `billing_return_view()` | Handle user redirect from Orange Money | `SubscriptionPayment` model |
| `_quota_warning.html` | Dashboard widget showing usage | None (included in list.html) |

## Models & Data

### SubscriptionPayment (UUID primary key)

```python
{
  "id": "UUID",
  "seller": FK(SellerProfile),
  "plan": "medium|pro",
  "provider": "orange",
  "amount": 2000,  # FCFA
  "phone": "+223XXXXXXXX",
  "status": "pending|success|failed|cancelled",
  "order_id": "HF-M-XXXXXXXX",  # ≤24 chars, unique, indexed
  "notif_token": "64-char hex string",  # SECURITY: indexed, unique
  "txn_id": "transaction id from Orange Money",
  "payment_url": "https://orange-money.ml/pay/...",
  "raw_response": {JSON from Orange Money API},
  "raw_callback": {JSON from webhook},
  "created_at": "datetime",
  "updated_at": "datetime",
  "paid_at": "datetime (only if success)"
}
```

### Subscription

```python
{
  "id": "int",
  "seller": FK(SellerProfile) unique,
  "plan": "free|medium|pro",
  "expires_at": "datetime or null",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

### WebhookLog (UUID primary key)

```python
{
  "id": "UUID",
  "payment": FK(SubscriptionPayment),
  "notif_token": "64-char hex string (indexed)",
  "status": "success|failure|...",
  "txn_id": "from webhook",
  "raw_payload": {full webhook JSON},
  "processed": True/False,  # True if webhook was acted on
  "error_message": "error text if failed",
  "created_at": "datetime"
}
```

## Integration Verification Checklist

- [x] Quota system exists and works (subscriptions/services/limits.py)
- [x] Flash sales create view calls can_seller_create_sale()
- [x] Paywall template (quota_exceeded.html) created and linked
- [x] Plans with pricing displayed in paywall
- [x] Upgrade buttons link to /subscriptions/upgrade/{plan}/
- [x] Payment model stores notif_token before API call
- [x] Webhook lookup by notif_token (security)
- [x] Webhook is idempotent (checks status == SUCCESS)
- [x] Subscription activation on webhook success
- [x] @login_required on return/cancel endpoints (security)
- [x] @csrf_exempt only on webhook (not on return/cancel)
- [x] SSL verification always enabled (verify=True)
- [x] Dashboard widget (_quota_warning.html) shows usage
- [x] Documentation complete

## Security Considerations

### Webhook Authenticity (notif_token)
- **Security Model**: Possession-based (token stored in DB at creation)
- **Not Used**: HMAC-SHA256 signature (complexity not justified for possession model)
- **Lookup**: `SubscriptionPayment.objects.get(notif_token=notif_token)`
- **Assurance**: Only payments we created can be activated
- **Log Token**: Displayed as `[:16] + "..."` in logs for traceability without exposure

### Idempotence
- **Problem**: Orange Money may send webhook twice
- **Solution**: Check `if payment.status == PaymentStatus.SUCCESS: return`
- **Audit**: Log duplicate webhooks in WebhookLog with `processed=False`

### SSL Verification
- **Rule**: Always `requests.post(..., verify=True)` when calling Orange Money API
- **Never**: Disable SSL verification, even in development
- **ngrok**: For local testing, use ngrok HTTPS tunnel to bypass cert issues

### CSRF Protection
- **Rule**: `@csrf_exempt` only on webhook endpoint
- **Other endpoints**: Always `@login_required` (implicit CSRF via Django middleware)
- **Why**: Webhook is called by Orange Money servers (external), not browsers

### Token Storage
- **Critical**: Generate and store notif_token in DB **BEFORE** calling Orange Money API
- **Reason**: If API call fails, webhook can't arrive; token must exist for webhook to work
- **Validation**: order_id must be ≤24 characters (Orange Money constraint)
