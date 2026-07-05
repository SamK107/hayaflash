# HayaFlash — commit P0-P5 MVP base architecture
# Run from: C:\projets\hayaflash\
# Usage:    powershell -ExecutionPolicy Bypass -File commit_mvp.ps1

Set-Location "C:\projets\hayaflash"

# Clear any stale lock
$lock = ".git\index.lock"
if (Test-Path $lock) {
    Remove-Item $lock -Force
    Write-Host "Removed stale index.lock" -ForegroundColor Yellow
}

# Stage everything
git add -A
if ($LASTEXITCODE -ne 0) { Write-Host "git add failed" -ForegroundColor Red; exit 1 }

# Commit
$msg = @"
feat(P0-P5): MVP base architecture — models, UI vendeur, Celery, dashboard, commandes, pages publiques, analytics, notifications, abonnements

P0 - Socle Django 5.2
- Config settings (base/dev/prod/test), Celery + Beat, accounts (User+SellerProfile),
  migrations initiales, design tokens Tailwind (primary=#E63946, gold=#FFB800, success=#22C55E)

P1 - Modeles metier
- FlashSale (6 statuts: scheduled/live/closed/executing/completed/cancelled)
- Product (stock_initial + stock_available), Order, Delivery
- open_sale() protege contre reouverture (ensemble non_reopenable)

P2 - Interface vendeur (FBV + HTMX 2 + Alpine.js 3)
- seller_home, flash_sale CRUD, product CRUD, live dashboard partiel
- _nav_seller.html : URL correctes (seller_home sans namespace, orders:seller_deliveries_dashboard)

P3 - Celery automatisation
- Tache periodique (60s) : ouverture/fermeture automatique des ventes flash
- Beat schedule configure dans settings

P4 - Commandes publiques et livraisons
- Page publique produit, formulaire commande anonyme, confirmation
- orders/views.py : seller_dashboard + seller_deliveries_dashboard (related_name=seller_profile)
- delivery/views.py : aliases contexte (current_flash_sale, flash_sale_choices, current_flash_sale_id)
- filter_choices : tuples (value, label) pour template

P5 - Pages publiques, analytics, notifications, abonnements
- analytics/services/cache.py : TTL min=1 (cache.set TTL=0 = pas de stockage dans Django)
- templates/analytics/ : extra_head avec canonical + JSON-LD
- subscriptions/subscription.html : filtre split supprime (non natif Django)
- config/urls.py : debug_toolbar conditionnel

QA — corrections post-audit
- SellerProfile.user related_name=seller_profile corrige dans 5 vues
- config/urls.py : inclusion debug_toolbar protegee par try/except
- Tous les templates : endblock manquants ajoutes
- 55/55 tests pytest OK, 14/14 URLs verifiees (200/302)
"@

git commit -m $msg
if ($LASTEXITCODE -eq 0) {
    Write-Host "`nCommit OK!" -ForegroundColor Green
    git log --oneline -3
} else {
    Write-Host "`ngit commit failed" -ForegroundColor Red
}
