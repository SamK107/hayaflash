# 🧪 HayaFlash — Plan QA & Tests (v1.0)

---

## Philosophie

> **Le backend est la source de vérité.** Tout test critique se fait côté serveur.
> Les tests frontend vérifient l'UX, jamais la logique métier.

---

## Matrice des Priorités

| Priorité | Impact si raté | Exemples |
|---|---|---|
| **P0** | Perte de données / argent | create_order, COD, stock |
| **P1** | Mauvaise UX bloquante | auth, dashboard, GPS |
| **P2** | Dégradation légère | analytics, notifications |
| **P3** | Nice-to-have | performance, accessibilité |

---

## 1. Tests Unitaires (P0/P1)

### 1.1 services.create_order()

```python
# orders/tests/test_create_order.py

class TestCreateOrder:
    """Tests du service critique create_order()."""

    def test_creates_order_successfully(self, db, live_flash_sale, product_with_stock):
        """Cas nominal : commande créée avec stock et GPS."""
        payload = {
            "flash_sale_id": str(live_flash_sale.id),
            "client_request_id": str(uuid.uuid4()),
            "customer_name": "Ibrahim Coulibaly",
            "customer_phone": "+22365000000",
            "items": [{"product_id": str(product_with_stock.id), "quantity": 2}],
            "delivery": {
                "address_text": "Hamdallaye ACI, Bamako",
                "latitude": 12.6392,
                "longitude": -8.0029
            }
        }
        order = create_order(payload)
        assert order.status == "pending"
        assert order.delivery is not None
        assert order.delivery.cod_amount == product_with_stock.price * 2

    def test_idempotence_same_client_request_id(self, db, live_flash_sale, product_with_stock):
        """Double appel avec même client_request_id → retourne la même commande."""
        payload = build_valid_payload(live_flash_sale, product_with_stock)
        order1 = create_order(payload)
        order2 = create_order(payload)  # même client_request_id
        assert order1.id == order2.id
        # Stock décrémenté une seule fois
        product_with_stock.refresh_from_db()
        assert product_with_stock.stock == initial_stock - payload["items"][0]["quantity"]

    def test_rejects_when_sale_not_live(self, db, scheduled_flash_sale):
        """Commande refusée si vente pas en live."""
        with pytest.raises(SaleNotLiveError):
            create_order(build_payload(scheduled_flash_sale))

    def test_rejects_outside_time_window(self, db, live_flash_sale):
        """Commande refusée hors fenêtre horaire."""
        live_flash_sale.end_time = timezone.now() - timedelta(minutes=1)
        live_flash_sale.save()
        with pytest.raises(SaleWindowClosedError):
            create_order(build_payload(live_flash_sale))

    def test_rejects_insufficient_stock(self, db, live_flash_sale, product_low_stock):
        """Commande refusée si stock insuffisant."""
        payload = build_payload_with_quantity(live_flash_sale, product_low_stock, quantity=999)
        with pytest.raises(InsufficientStockError):
            create_order(payload)

    def test_decrements_stock_atomically(self, db, live_flash_sale, product_with_stock):
        """Stock décrémenté dans la même transaction."""
        initial = product_with_stock.stock
        create_order(build_payload_with_quantity(live_flash_sale, product_with_stock, 3))
        product_with_stock.refresh_from_db()
        assert product_with_stock.stock == initial - 3

    def test_creates_delivery_with_gps(self, db, live_flash_sale, product_with_stock):
        """Delivery créée avec coordonnées GPS."""
        payload = build_valid_payload(live_flash_sale, product_with_stock)
        payload["delivery"]["latitude"] = 12.6392
        payload["delivery"]["longitude"] = -8.0029
        order = create_order(payload)
        assert order.delivery.latitude == Decimal("12.63920000")
        assert order.delivery.maps_url is not None

    def test_creates_delivery_without_gps(self, db, live_flash_sale, product_with_stock):
        """Delivery acceptée sans GPS (adresse texte uniquement)."""
        payload = build_valid_payload(live_flash_sale, product_with_stock)
        payload["delivery"].pop("latitude", None)
        payload["delivery"].pop("longitude", None)
        order = create_order(payload)
        assert order.delivery.latitude is None
        assert order.delivery.address_text != ""

    def test_cod_amount_equals_total(self, db, live_flash_sale, products):
        """COD amount = somme des prix snapshots."""
        order = create_order(build_multi_item_payload(live_flash_sale, products))
        expected = sum(item.price_snapshot * item.quantity for item in order.items.all())
        assert order.delivery.cod_amount == expected
```

### 1.2 Concurrence (PostgreSQL uniquement)

```python
class TestConcurrency:
    """Tests de concurrence — nécessitent PostgreSQL."""

    @pytest.mark.skipif(not is_postgresql(), reason="PostgreSQL uniquement")
    def test_concurrent_orders_no_oversell(self, db, live_flash_sale, product_stock_5):
        """10 commandes simultanées sur stock=5 → exactement 5 acceptées."""
        import concurrent.futures
        results = []

        def place_order():
            try:
                order = create_order(build_payload_qty_1(live_flash_sale, product_stock_5))
                return ("success", order.id)
            except InsufficientStockError:
                return ("rejected", None)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(place_order) for _ in range(10)]
            results = [f.result() for f in futures]

        successes = [r for r in results if r[0] == "success"]
        assert len(successes) == 5  # Exactement stock disponible

        product_stock_5.refresh_from_db()
        assert product_stock_5.stock == 0
```

### 1.3 Delivery Workflow

```python
class TestDeliveryWorkflow:

    def test_advance_to_delivered_sets_cod(self, db, confirmed_order):
        """mark_delivered → cod_collected = True + timestamp."""
        delivery = confirmed_order.delivery
        delivery.advance("mark_delivered", cod_collected=True, user=seller_user)
        delivery.refresh_from_db()
        assert delivery.cod_collected is True
        assert delivery.cod_collected_at is not None
        assert delivery.cod_confirmed_by == seller_user

    def test_cannot_go_backwards(self, db, delivered_order):
        """Impossible de revenir sur un statut antérieur."""
        with pytest.raises(InvalidTransitionError):
            delivered_order.delivery.advance("start_delivery")

    def test_gps_coordinates_validated(self, db, live_flash_sale):
        """Coordonnées GPS invalides rejetées."""
        payload = build_payload(live_flash_sale)
        payload["delivery"]["latitude"] = 999  # invalide
        with pytest.raises(ValidationError):
            create_order(payload)
```

---

## 2. Tests d'Intégration API (P0/P1)

```python
class TestOrdersAPI:

    def test_post_order_returns_201(self, client, live_flash_sale):
        res = client.post('/api/v1/orders/', valid_order_payload(), content_type='application/json')
        assert res.status_code == 201
        data = res.json()
        assert "order_id" in data
        assert "delivery" in data
        assert data["delivery"]["maps_url"] is not None

    def test_post_order_idempotent_returns_200(self, client, live_flash_sale):
        payload = valid_order_payload()
        res1 = client.post('/api/v1/orders/', payload, content_type='application/json')
        res2 = client.post('/api/v1/orders/', payload, content_type='application/json')
        assert res1.status_code == 201
        assert res2.status_code == 200
        assert res2.json()["already_exists"] is True
        assert res1.json()["order_id"] == res2.json()["order_id"]

    def test_rate_limit_enforced(self, client, live_flash_sale):
        """31e requête doit retourner 429."""
        for i in range(30):
            client.post('/api/v1/orders/', unique_order_payload(), content_type='application/json')
        res = client.post('/api/v1/orders/', unique_order_payload(), content_type='application/json')
        assert res.status_code == 429

    def test_delivery_advance_requires_auth(self, client, delivery):
        res = client.patch(f'/api/v1/delivery/{delivery.id}/advance/', {"action": "start_delivery"})
        assert res.status_code == 401

    def test_mark_delivered_sets_cod(self, auth_client, in_transit_delivery):
        res = auth_client.patch(
            f'/api/v1/delivery/{in_transit_delivery.id}/advance/',
            {"action": "mark_delivered", "cod_collected": True},
            content_type='application/json'
        )
        assert res.status_code == 200
        assert res.json()["cod_collected"] is True
```

---

## 3. Tests Offline / Sync (P1)

```javascript
// tests/e2e/offline_sync.spec.js (Playwright)

test('order submitted offline syncs when back online', async ({ page, context }) => {
  await page.goto('/order/?flash_sale_id=xxx&product_id=yyy');
  await fillOrderForm(page);

  // Simuler déconnexion
  await context.setOffline(true);
  await page.click('[data-testid="submit-order"]');

  // Vérifier stockage IndexedDB
  const queued = await page.evaluate(() => {
    return new Promise(resolve => {
      const req = indexedDB.open('haya_offline');
      req.onsuccess = (e) => {
        const tx = e.target.result.transaction('order_queue', 'readonly');
        const store = tx.objectStore('order_queue');
        store.getAll().onsuccess = (e2) => resolve(e2.target.result);
      };
    });
  });
  expect(queued).toHaveLength(1);

  // Reconnecter
  await context.setOffline(false);

  // Attendre sync
  await page.waitForResponse(res =>
    res.url().includes('/api/v1/orders/') && res.status() === 201,
    { timeout: 35_000 }
  );

  // Queue vidée
  // (re-check IndexedDB)
});
```

---

## 4. Tests GPS (P1)

```javascript
// tests/e2e/geolocation.spec.js

test('GPS granted - shows address suggestion', async ({ page }) => {
  await page.addInitScript(() => {
    navigator.geolocation.getCurrentPosition = (success) =>
      success({ coords: { latitude: 12.6392, longitude: -8.0029, accuracy: 15 } });
  });
  await page.goto('/order/?...');
  await expect(page.locator('[data-testid="gps-success-badge"]')).toBeVisible();
  await expect(page.locator('[data-testid="address-field"]')).not.toBeEmpty();
});

test('GPS denied - manual address field required', async ({ page }) => {
  await page.addInitScript(() => {
    navigator.geolocation.getCurrentPosition = (_, error) =>
      error({ code: 1, message: 'Permission denied' });
  });
  await page.goto('/order/?...');
  await expect(page.locator('[data-testid="gps-denied-notice"]')).toBeVisible();
  await expect(page.locator('[data-testid="address-field"]')).toBeVisible();
  await expect(page.locator('[data-testid="address-field"]')).toBeRequired();
});

test('GPS timeout - fallback to manual', async ({ page }) => {
  await page.addInitScript(() => {
    navigator.geolocation.getCurrentPosition = () => {}; // jamais résolu
  });
  await page.goto('/order/?...');
  // Attendre 11s (timeout > 10s)
  await page.waitForTimeout(11_000);
  await expect(page.locator('[data-testid="gps-timeout-notice"]')).toBeVisible();
});
```

---

## 5. Tests de Charge Flash Sale (P1)

```python
# locust/locustfile.py

class FlashSaleUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(10)
    def place_order(self):
        """Simule un client qui passe commande pendant le live."""
        self.client.post("/api/v1/orders/", json={
            "flash_sale_id": LIVE_SALE_ID,
            "client_request_id": str(uuid.uuid4()),
            "customer_name": fake.name(),
            "customer_phone": f"+223{random.randint(60000000, 79999999)}",
            "items": [{"product_id": PRODUCT_ID, "quantity": 1}],
            "delivery": {
                "address_text": fake.address(),
                "latitude": 12.6 + random.uniform(-0.1, 0.1),
                "longitude": -8.0 + random.uniform(-0.1, 0.1)
            }
        })

    @task(3)
    def view_flash_sale(self):
        self.client.get(f"/api/v1/flash-sales/{SALE_SLUG}/")

# Cibles de performance P0:
# - 200 commandes/minute → p95 < 500ms
# - 500 concurrent viewers → p95 < 200ms
# - 0% erreurs 5xx
# - Stock final = stock_initial - commandes_acceptées (EXACT)
```

---

## 6. Sécurité (P0/P1)

| Test | Attendu |
|---|---|
| POST /orders/ sans `client_request_id` | 400 |
| POST /orders/ avec vente `scheduled` | 400 `sale_not_live` |
| POST /orders/ après `end_time` | 400 `sale_window_closed` |
| PATCH /delivery/ sans auth | 401 |
| PATCH /delivery/ par mauvais vendeur | 403 |
| Coordonnées GPS `lat=999` | 400 validation_error |
| 31 POST/min même IP | 429 |
| Webhook sans signature HMAC | 401 |
| XSS dans `address_text` | Échappé en DB et HTML |
| SQL injection dans `customer_name` | Ignoré (ORM) |
| Accès dashboard autre vendeur | 403 |

---

## 7. Smoke Tests Deploy (Staging → Production)

```bash
#!/bin/bash
# infra/scripts/smoke_test.sh

BASE_URL="${1:-https://staging.hayaflash.com}"

echo "=== HayaFlash Smoke Tests ==="

# Health check
echo -n "Health check... "
status=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/v1/health/")
[ "$status" = "200" ] && echo "✅" || (echo "❌ $status" && exit 1)

# Flash sales list
echo -n "Flash sales endpoint... "
status=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/v1/flash-sales/")
[ "$status" = "200" ] && echo "✅" || (echo "❌ $status" && exit 1)

# Auth register (dry run)
echo -n "Auth register endpoint... "
status=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "$BASE_URL/api/v1/accounts/auth/register/" \
  -H "Content-Type: application/json" \
  -d '{"phone": "invalid", "password": "x"}')
[ "$status" = "400" ] && echo "✅ (validation active)" || (echo "❌ unexpected $status" && exit 1)

# Rate limit header présent
echo -n "Rate limit headers... "
headers=$(curl -sI "$BASE_URL/api/v1/flash-sales/")
echo "$headers" | grep -q "X-RateLimit" && echo "✅" || echo "⚠️ headers absents"

# DB migration check
echo -n "Migrations applied... "
python manage.py migrate --check --settings=config.settings.prod && echo "✅" || (echo "❌" && exit 1)

echo ""
echo "=== Smoke tests passed ✅ ==="
```

---

## 8. Critères de Rollback

| Condition | Action |
|---|---|
| Health check /api/v1/health/ → 5xx | Rollback immédiat |
| Smoke test échoue | Rollback immédiat |
| Taux erreur 5xx > 1% sur 5min | Rollback immédiat |
| Latence p95 > 2s sur /api/v1/orders/ | Alerte → rollback si > 10min |
| Erreur migration | Ne pas déployer en prod |
| Test `create_order` échoue en staging | Bloquer merge PR |

### Procédure de rollback

```bash
# Rollback = redéployer l'image précédente (tag immuable semver)
docker pull ghcr.io/hayaflash/app:v1.2.2  # version stable précédente
docker stop hayaflash-prod
docker run -d --name hayaflash-prod ghcr.io/hayaflash/app:v1.2.2
# Pas de migrate --fake, pas de rollback DB manuel
# Les migrations sont forward-only
```

---

## 9. Pipeline CI/CD

```yaml
# .github/workflows/deploy.yml

name: CI/CD HayaFlash

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_DB: hayaflash_test
          POSTGRES_USER: hayaflash
          POSTGRES_PASSWORD: testpass
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
      redis:
        image: redis:7
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r requirements/test.txt
      - run: python manage.py test --settings=config.settings.test
      - run: python manage.py check --settings=config.settings.prod --deploy

  build:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build & Push image
        run: |
          VERSION=$(git describe --tags --always)
          docker build -t ghcr.io/hayaflash/app:$VERSION .
          docker push ghcr.io/hayaflash/app:$VERSION
          echo "IMAGE_TAG=$VERSION" >> $GITHUB_ENV

  deploy-staging:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to staging VPS
        run: |
          ssh deploy@staging.hayaflash.com "
            docker pull ghcr.io/hayaflash/app:${{ env.IMAGE_TAG }}
            docker stop hayaflash-staging || true
            docker run -d --name hayaflash-staging \
              --env-file /etc/hayaflash/staging.env \
              ghcr.io/hayaflash/app:${{ env.IMAGE_TAG }}
            python manage.py migrate --settings=config.settings.staging
          "
      - name: Smoke test staging
        run: bash infra/scripts/smoke_test.sh https://staging.hayaflash.com

  deploy-prod:
    needs: deploy-staging
    runs-on: ubuntu-latest
    environment: production  # Approval manuel GitHub
    steps:
      - name: Backup DB prod
        run: ssh deploy@prod.hayaflash.com "pg_dump hayaflash_prod > /backups/pre-deploy-$(date +%Y%m%d-%H%M%S).sql"
      - name: Deploy to prod VPS
        run: |
          ssh deploy@prod.hayaflash.com "
            docker pull ghcr.io/hayaflash/app:${{ env.IMAGE_TAG }}
            docker stop hayaflash-prod || true
            docker run -d --name hayaflash-prod \
              --env-file /etc/hayaflash/prod.env \
              ghcr.io/hayaflash/app:${{ env.IMAGE_TAG }}
            python manage.py migrate --settings=config.settings.prod
          "
      - name: Smoke test prod
        run: bash infra/scripts/smoke_test.sh https://hayaflash.com
```

---

## 10. Checklist V1 Ready

- [ ] `create_order()` : idempotence testée
- [ ] `create_order()` : concurrence testée (PostgreSQL)
- [ ] Stock : pas d'oversell sous charge
- [ ] GPS : capture + fallback manuel testés
- [ ] Delivery : workflow COD complet testé
- [ ] Auth : login + rate limit testés
- [ ] HTMX dashboard : polling < 5s confirmé
- [ ] Offline queue : sync au retour de connexion testé
- [ ] Rate limits : 429 actif sur /orders/
- [ ] Smoke tests : staging + prod verts
- [ ] Rollback drill : testé au moins une fois
- [ ] Migrations : aucune migration destructive non réversible

---

## 🔚 Fin du document