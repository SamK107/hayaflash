# HayaFlash Integration Documentation

This directory contains comprehensive documentation for the Orange Money payment integration with HayaFlash's quota system.

## Documents

### INTEGRATION_FLOW.md
Complete technical flow document showing:
- 11-step user journey from quota exceeded to subscription active
- Detailed data flow diagrams with component interactions
- Model specifications (SubscriptionPayment, Subscription, WebhookLog)
- Security considerations and implementation details
- Complete webhook flow with idempotence and error handling
- Integration verification checklist

**Use this when**: You need to understand the complete payment flow or debug integration issues.

### QUOTA_UPGRADE_MAPPING.md
Component-to-component mapping showing:
- Request/response flow for each phase (quota → paywall → upgrade → payment)
- Path to production with file changes and testing checklist
- Deployment checklist
- Rollback plan if issues occur
- Monitoring points for production support

**Use this when**: You're deploying to production or monitoring the system.

### ../CLAUDE.md
Root-level documentation containing:
- Orange Money Payment Integration section (200+ lines)
- All 6 critical security rules with code examples
- Architecture overview
- Environment variables reference
- Debugging & monitoring guide

**Use this when**: You need to set up environment variables or understand the authentication flow.

## Quick Start

1. **To Deploy**: Read `QUOTA_UPGRADE_MAPPING.md` "Path to Production" section
2. **To Debug**: Read `INTEGRATION_FLOW.md` and check corresponding component
3. **To Monitor**: Read `QUOTA_UPGRADE_MAPPING.md` "Monitoring Points" section
4. **To Test**: Follow "Testing Checklist" in `QUOTA_UPGRADE_MAPPING.md`

## Key Components

### Modified Files
- `subscriptions/billing_views.py`: Added @login_required decorators
- `flash_sales/views.py`: Modified to render paywall on quota exceeded

### New Templates
- `templates/flash_sales/quota_exceeded.html`: Paywall with 3 plan cards
- `templates/flash_sales/partials/_quota_warning.html`: Dashboard usage widget

### Already Implemented (Phase 1)
- `subscriptions/models.py`: Payment & webhook models
- `subscriptions/services/payment.py`: Payment creation & subscription activation
- `subscriptions/services/orange_money.py`: Orange Money API & webhook verification
- `subscriptions/billing_views.py`: Webhook handler with idempotence

## Security Checklist

- [x] Webhook lookup by notif_token (not order_id)
- [x] Idempotence check (payment.status == SUCCESS skip)
- [x] notif_token stored BEFORE Orange Money API call
- [x] order_id validation (≤24 characters)
- [x] SSL verification always enabled (verify=True)
- [x] @csrf_exempt only on webhook, not on return/cancel
- [x] @login_required on return/cancel endpoints

## Integration Status

**Status**: COMPLETE INTEGRATION - Production Ready

### Phase 1 (Orange Money Backend) - DONE
- Payment models with security (notif_token, order_id validation)
- Orange Money OAuth2 service
- Webhook handler with idempotence and security
- Subscription activation on payment success
- Comprehensive documentation in CLAUDE.md

### Phase 2 (Quota System Integration) - DONE
- Quota check in flash_sale_create_view()
- Paywall template (quota_exceeded.html) with plan options
- Dashboard widget showing quota usage
- Security: @login_required on return/cancel endpoints
- Complete flow documentation

## Testing in Development

### Environment Setup
```bash
# .env
ORANGE_ML_CLIENT_ID=your_client_id
ORANGE_ML_CLIENT_SECRET=your_secret
ORANGE_ML_MERCHANT_KEY=your_key
ORANGE_ML_BASE_URL=https://api-dev.orange.ml  # or ngrok tunnel

# Disable SSL verification for development (if needed)
# BUT: Only in development, NEVER in production
```

### Webhook Testing
To test webhooks locally, use ngrok:
```bash
ngrok http 8000
# Then set ORANGE_ML_NOTIFY_URL=https://your-ngrok-url/billing/webhook/orange/
```

### Quota Testing
1. Create free account
2. Create 3 flash sales (hits quota)
3. Try to create 4th → should see paywall
4. Click "Passer à MEDIUM" → goes to upgrade form
5. Complete payment flow

## Production Deployment

1. **Database Migrations**: `python manage.py migrate subscriptions`
2. **Environment Variables**: Set all ORANGE_ML_* variables
3. **Static Files**: `python manage.py collectstatic`
4. **SSL**: Ensure HTTPS is enabled
5. **Testing**: Run production test checklist (see QUOTA_UPGRADE_MAPPING.md)

## Monitoring

Key metrics to track:
- SubscriptionPayment.status distribution (should be mostly SUCCESS)
- WebhookLog.processed distribution (should be mostly True)
- Payments with status=PENDING older than 24h (stuck payments)
- Webhook error rate (should be < 1%)

## Support

For specific issues:

| Issue | Check |
|-------|-------|
| Quota not enforcing | `subscriptions/services/limits.py` logic |
| Paywall not showing | `flash_sales/views.py` and `quota_exceeded.html` |
| Payment not completing | `subscriptions/billing_views.py` webhook handler |
| Webhook not received | Check Orange Money API logs and ngrok tunnel (dev) |
| User can't access return URL | Check @login_required decorators |

## Glossary

- **notif_token**: 64-char hex string generated at payment creation, used for webhook security
- **order_id**: Unique identifier for payment (max 24 chars), format: "HF-{M/P}-XXXXXXXX"
- **idempotence**: Webhook handler skips re-processing if payment already SUCCESS
- **Quota**: Monthly limit on flash sale creations (3 for FREE/MEDIUM, unlimited for PRO)
- **Paywall**: quota_exceeded.html template showing plan options to upgrade

## FAQ

**Q: What happens if webhook never arrives?**
A: Payment stays PENDING. User can visit /billing/return/?order_id=... and see "payment pending" message with auto-refresh every 5 seconds. If still pending after 24h, manually check Orange Money dashboard.

**Q: Can I disable the quota system?**
A: Set `PLAN_MONTHLY_SALES_LIMIT[Plan.FREE] = None` in models.py, but this breaks the business model. Better to offer a "pause quota" feature.

**Q: What if a user's phone number is wrong?**
A: Orange Money payment will fail. They can retry with correct number. Previous failed attempt stays in SubscriptionPayment with status=FAILED.

**Q: Can PRO users upgrade again?**
A: No, upgrade_subscription_view() checks if already on that plan. They can add a "renew" feature instead.

**Q: Is the paywall mobile responsive?**
A: Yes, tested at 390px (mobile breakpoint). Quota warning widget also responsive.
