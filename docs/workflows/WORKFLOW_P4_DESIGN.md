# Workflow P4 — Design Moderne Complet (Tailwind)
> Phase 4 · Durée estimée : ~2 semaines  
> Prérequis : P0 + P1 + P2 + P3

---

## Objectif

Appliquer le design system HayaFlash sur toutes les pages. Expérience utilisateur moderne, cohérente, performante sur Android entrée de gamme.

---

## Design System Tokens

```js
// tailwind.config (dans base.html ou fichier séparé)
colors: {
  primary: '#E63946',   // rouge action
  gold:    '#FFB800',   // accent
  dark:    '#111111',
  success: '#22C55E',
  warning: '#F59E0B',
  danger:  '#EF4444',
  muted:   '#6B7280',
  surface: '#FFFFFF',
  bg:      '#F5F5F5',
}
```

## Composants CSS Communs (via @layer ou classe utilitaire)

```html
<!-- Bouton primaire -->
<button class="w-full bg-primary hover:bg-red-700 active:bg-red-800 text-white font-bold py-4 px-6 rounded-xl text-base transition-colors disabled:opacity-50 disabled:cursor-not-allowed min-h-[56px]">
  Commander
</button>

<!-- Input standard -->
<input class="w-full px-4 py-3 border border-gray-300 rounded-xl text-base focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent bg-white">

<!-- Card -->
<div class="bg-white rounded-2xl shadow-sm border border-gray-100 p-4">

<!-- Badge statut -->
<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-green-100 text-green-800">
  Confirmée
</span>

<!-- Section title -->
<h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">
```

---

## Pages à Refondre (par priorité)

### 1. `accounts/login.html` + `register.html`

Login :
- Fond blanc, logo HayaFlash centré en haut
- Champ téléphone (input type=tel, format E.164)
- Bouton "Recevoir le code OTP" rouge
- Lien "Créer un compte"
- Footer "Commande via HayaFlash"

Register :
- Étapes : 1. Téléphone → 2. Code OTP → 3. Nom boutique
- Step indicator (3 points)
- Chaque étape : 1 champ, 1 bouton → ultra simplifié

### 2. `seller/home.html` (landing vendeur)

```
┌────────────────────────────────┐
│  [Nav]                         │
├────────────────────────────────┤
│  Bonjour, [Nom Boutique] 👋    │
├────────────────────────────────┤
│  KPI du mois :                 │
│  [12 ventes] [340 commandes]  │
│  [1 250 000 FCFA estimés]     │
├────────────────────────────────┤
│  Ventes actives                │
│  [Card vente LIVE]             │
│  [Card vente programmée]      │
├────────────────────────────────┤
│  [+ Créer une nouvelle vente] │  ← CTA rouge pleine largeur
└────────────────────────────────┘
```

### 3. `flash_sales/list.html`

- Tabs : Programmées / En cours / Terminées
- Card par vente : titre, dates, nb produits, nb commandes, statut badge
- Quick actions : Voir dashboard / Ouvrir / Modifier
- Empty state : illustration + "Créez votre première vente"

### 4. `flash_sales/create.html`

- Formulaire en carte unique
- Cover image : upload drag & drop (Alpine.js preview)
- DateTime picker natif mobile (type="datetime-local")
- Validation en temps réel (Alpine.js)
- CTA : "Créer la vente →"

### 5. `flash_sales/detail.html`

Section 1 — Infos vente :
- Titre + statut badge
- Dates, zone livraison, max commandes
- Cover image
- Actions : [Ouvrir LIVE] [Modifier] [Partager] [Voir publiquement]

Section 2 — Produits :
- Grid 1 col (mobile) / 2 col (desktop)
- Card produit : image, nom, prix, stock (barre de progression), actions [Modifier] [Supprimer]
- Bouton "Ajouter un produit" en bas

Section 3 — Lien de partage :
- URL courte affichée
- Boutons : [Copier] [WhatsApp] [QR Code]

### 6. `orders/dashboard.html` (LIVE)

Cf. WORKFLOW_P3 — s'assurer que le design est complet :
- Header fixe avec badge LIVE + countdown
- KPI cards avec icônes Lucide
- Liste orders avec animations slide-in
- Actions 1-clic avec confirmation modal
- Stock critique : alerte rouge si stock < 20%

### 7. `orders/client_order.html`

Cf. WORKFLOW_P3 — page de commande client :
- Hero produit (image + nom + prix + stock)
- Formulaire épuré 5 champs max
- GPS avec feedback animé
- CTA "Commander" 56px
- Confirmation : toast + card résumé commande

### 8. `delivery/deliveries_dashboard.html`

- Liste livraisons par statut (Tabs)
- Card livraison : nom client, adresse, montant COD, lien Google Maps
- Actions rapides : [En transit] [Livré] [Échec]
- Totaux COD en bas : collecté / à collecter

### 9. `analytics/flash_sale_public.html` + `seller_public.html`

Pages publiques SEO-optimisées :
- flash_sale_public : countdown + produits + bouton Commander
- seller_public : profil vendeur + ventes actives + historique

---

## Composants Alpine.js à Créer

### `static/js/hf-components.js`

```javascript
// Timer countdown
function countdown(endTimeISO) {
  return {
    end: new Date(endTimeISO),
    now: new Date(),
    interval: null,
    init() {
      this.interval = setInterval(() => { this.now = new Date(); }, 1000);
    },
    destroy() { clearInterval(this.interval); },
    get remaining() {
      const diff = Math.max(0, this.end - this.now);
      const h = Math.floor(diff / 3600000);
      const m = Math.floor((diff % 3600000) / 60000);
      const s = Math.floor((diff % 60000) / 1000);
      return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    },
    get isOver()   { return this.now >= this.end; },
    get isUrgent() { return (this.end - this.now) < 300000; },
  };
}

// Toast manager
function toasts() {
  return {
    items: [],
    add(msg, type = 'info') {
      const id  = Date.now();
      const colors = {
        success: 'bg-success', error: 'bg-danger',
        warning: 'bg-warning', info: 'bg-gray-800'
      };
      this.items.push({ id, msg, color: colors[type] || colors.info });
      setTimeout(() => this.remove(id), 4000);
    },
    remove(id) { this.items = this.items.filter(t => t.id !== id); },
  };
}

// Quantity picker
function quantityPicker(initial = 1, max = 99) {
  return {
    qty: initial,
    max,
    inc() { if (this.qty < this.max) this.qty++; },
    dec() { if (this.qty > 1) this.qty--; },
  };
}

// GPS capture
function gpsCapture() {
  return {
    status: 'idle',   // idle | loading | success | error
    lat: null,
    lng: null,
    accuracy: null,
    address: '',
    capture() {
      if (!navigator.geolocation) { this.status = 'error'; return; }
      this.status = 'loading';
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          this.lat      = pos.coords.latitude;
          this.lng      = pos.coords.longitude;
          this.accuracy = Math.round(pos.coords.accuracy);
          this.status   = 'success';
        },
        () => { this.status = 'error'; },
        { timeout: 10000, maximumAge: 60000 }
      );
    },
    get statusText() {
      const map = {
        idle: '', loading: 'Localisation en cours...',
        success: `Position capturée (±${this.accuracy}m)`,
        error: 'Position non disponible — saisissez votre adresse',
      };
      return map[this.status] || '';
    },
  };
}

// Online status
function onlineStatus() {
  return {
    online: navigator.onLine,
    init() {
      window.addEventListener('online',  () => this.online = true);
      window.addEventListener('offline', () => this.online = false);
    },
  };
}
```

---

## Étape 4.x — Image Preview pour l'upload

Dans les formulaires avec upload d'image :

```html
<div x-data="{ preview: null }">
  <label class="block cursor-pointer">
    <div class="border-2 border-dashed border-gray-300 rounded-xl p-6 text-center hover:border-primary transition-colors">
      <template x-if="!preview">
        <div>
          <i data-lucide="image" class="w-8 h-8 text-gray-400 mx-auto mb-2"></i>
          <p class="text-sm text-gray-500">Cliquez pour ajouter une image</p>
          <p class="text-xs text-gray-400">JPG, PNG — max 5 Mo</p>
        </div>
      </template>
      <template x-if="preview">
        <img :src="preview" class="max-h-40 mx-auto rounded-lg object-cover" />
      </template>
      <input
        type="file" accept="image/*" class="hidden" name="cover_image"
        @change="preview = $event.target.files[0] ? URL.createObjectURL($event.target.files[0]) : null"
      />
    </div>
  </label>
</div>
```

---

## Étape 4.y — Empty States

Chaque liste doit avoir un empty state illustré :

```html
<!-- Pas de ventes -->
<div class="text-center py-16">
  <div class="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
    <i data-lucide="zap" class="w-8 h-8 text-gray-400"></i>
  </div>
  <h3 class="text-lg font-semibold text-gray-900 mb-1">Aucune vente pour l'instant</h3>
  <p class="text-gray-500 text-sm mb-6">Créez votre première vente flash et commencez à vendre en live !</p>
  <a href="{% url 'flash_sales:create' %}" class="inline-flex items-center gap-2 bg-primary text-white font-bold px-6 py-3 rounded-xl">
    <i data-lucide="plus" class="w-4 h-4"></i>
    Créer ma première vente
  </a>
</div>
```

---

## Checklist Finale P4

- [ ] Lighthouse Mobile Score > 85 sur la page commande client
- [ ] Lighthouse Mobile Score > 80 sur le dashboard LIVE
- [ ] Aucun CSS inline sur les 8 pages critiques
- [ ] Touch targets ≥ 48px sur tous les CTA
- [ ] `hf-components.js` chargé dans `base.html`
- [ ] Countdown fonctionnel sur dashboard LIVE et page publique vente
- [ ] GPS capture avec feedback visuel sur page commande
- [ ] Empty states sur toutes les listes
- [ ] Image upload avec preview sur les formulaires
- [ ] Design cohérent sur 375px (iPhone SE) et 414px (standard Android)
