/**
 * HayaFlash — Composants Alpine.js globaux
 * Charge via base.html : <script src="{% static 'js/hf-components.js' %}"></script>
 */

// ---------------------------------------------------------------------------
// countdown(endTimeISO)
// Usage: x-data="countdown('2026-07-05T18:00:00+00:00')" x-init="init()"
// ---------------------------------------------------------------------------
function countdown(endTimeISO) {
  return {
    end: new Date(endTimeISO),
    now: new Date(),
    _interval: null,
    init() {
      this._interval = setInterval(() => { this.now = new Date(); }, 1000);
    },
    destroy() {
      if (this._interval) clearInterval(this._interval);
    },
    get diff() {
      return Math.max(0, this.end - this.now);
    },
    get remaining() {
      const d = this.diff;
      const h = Math.floor(d / 3600000);
      const m = Math.floor((d % 3600000) / 60000);
      const s = Math.floor((d % 60000) / 1000);
      return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    },
    get isOver()   { return this.diff === 0; },
    get isUrgent() { return this.diff > 0 && this.diff < 300000; }, // < 5 min
  };
}

// ---------------------------------------------------------------------------
// toasts()
// Usage: x-data="toasts()" sur un wrapper global
// API: $dispatch('hf-toast', { msg: '...', type: 'success'|'error'|'info'|'warning' })
// ---------------------------------------------------------------------------
function toasts() {
  return {
    items: [],
    init() {
      window.addEventListener('hf-toast', (e) => {
        this.add(e.detail.msg, e.detail.type || 'info');
      });
    },
    add(msg, type = 'info') {
      const id = Date.now() + Math.random();
      const colors = {
        success: 'bg-green-600',
        error:   'bg-red-600',
        warning: 'bg-amber-500',
        info:    'bg-gray-800',
      };
      this.items.push({ id, msg, color: colors[type] || colors.info });
      setTimeout(() => this.remove(id), 4000);
    },
    remove(id) {
      this.items = this.items.filter(t => t.id !== id);
    },
  };
}

// ---------------------------------------------------------------------------
// hfRoot() -- composant racine de base.html (<html x-data="hfRoot()">).
// Fusionne toasts() + onlineStatus() en appelant LES DEUX init() : l'ancien
// x-data="{ ...toasts(), ...onlineStatus() }" gardait seulement le init() du
// dernier objet etale -> l'ecouteur hf-toast n'etait jamais pose et aucun
// message Django ne s'affichait (constate le 26/09, sprint gouvernance B).
// ---------------------------------------------------------------------------
function hfRoot() {
  const t = toasts();
  const o = onlineStatus();
  return {
    ...t,
    ...o,
    init() {
      t.init.call(this);
      o.init.call(this);
    },
  };
}

// ---------------------------------------------------------------------------
// quantityPicker(initial, max)
// ---------------------------------------------------------------------------
function quantityPicker(initial = 1, max = 99) {
  return {
    qty: initial,
    max,
    inc() { if (this.qty < this.max) this.qty++; },
    dec() { if (this.qty > 1) this.qty--; },
  };
}

// ---------------------------------------------------------------------------
// gpsCapture()
// ---------------------------------------------------------------------------
function gpsCapture() {
  return {
    status: 'idle',   // idle | loading | success | error
    lat: null,
    lng: null,
    accuracy: null,
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
        idle:    '',
        loading: 'Localisation en cours...',
        success: `Position capturée (±${this.accuracy}m)`,
        error:   'Position non disponible — saisissez votre adresse',
      };
      return map[this.status] || '';
    },
  };
}

// ---------------------------------------------------------------------------
// onlineStatus()
// ---------------------------------------------------------------------------
function onlineStatus() {
  return {
    online: navigator.onLine,
    init() {
      window.addEventListener('online',  () => { this.online = true; });
      window.addEventListener('offline', () => { this.online = false; });
    },
  };
}

// ---------------------------------------------------------------------------
// clientOrderForm(config)
// Usage: x-data="clientOrderForm({ flashSaleId, productId, shareRef,
//        trackingSource, price, maxQty, apiUrl })" sur le wrapper englobant
//        le <form> ET le bloc de confirmation (le scope Alpine doit couvrir
//        les deux, la confirmation ne fait pas partie du <form>).
// Poste en JSON vers /api/v1/orders/ (seul endpoint qui cree reellement une
// commande - voir orders/api.py::api_v1_orders_create). Un <form
// method="POST"> classique vers /order/ echoue toujours en 405 (cette vue
// est @require_GET) : voir Phase 10.0.
// ---------------------------------------------------------------------------
function clientOrderForm(config) {
  const cfg = config || {};
  return {
    submitting: false,
    submitted: false,
    submitError: '',
    orderResult: null,
    qty: 1,
    maxQty: cfg.maxQty || 99,
    inc() { if (this.qty < this.maxQty) this.qty++; },
    dec() { if (this.qty > 1) this.qty--; },
    ...gpsCapture(),
    get total() {
      const price = Number(cfg.price) || 0;
      return (price * this.qty).toLocaleString('fr-FR') + ' FCFA';
    },
    async submitOrder() {
      if (this.submitting) return;
      this.submitError = '';

      const name = (this.$refs.customerName?.value || '').trim();
      const phone = (this.$refs.customerPhone?.value || '').trim();
      const address = (this.$refs.deliveryAddress?.value || '').trim();
      const notes = (this.$refs.deliveryNotes?.value || '').trim();

      if (!name || !phone || !address) {
        this.submitError = 'Merci de renseigner votre nom, votre téléphone et votre adresse.';
        return;
      }

      const clientRequestId = (window.crypto && crypto.randomUUID)
        ? crypto.randomUUID()
        : ('order-' + Date.now() + '-' + Math.random().toString(36).slice(2));

      const payload = {
        flash_sale_id: cfg.flashSaleId,
        product_id: cfg.productId,
        name,
        phone,
        quantity: this.qty,
        address_text: address,
        delivery_notes: notes,
        client_request_id: clientRequestId,
      };
      if (this.lat) payload.latitude = this.lat;
      if (this.lng) payload.longitude = this.lng;
      if (this.accuracy) payload.geo_accuracy = this.accuracy;
      if (this.status === 'success') payload.geo_method = 'gps';
      if (cfg.shareRef) payload.ref = cfg.shareRef;
      if (cfg.trackingSource) payload.src = cfg.trackingSource;

      this.submitting = true;
      try {
        const res = await fetch(cfg.apiUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          const firstVal = Object.values(data)[0];
          this.submitError = Array.isArray(firstVal)
            ? String(firstVal[0])
            : String(firstVal || 'Une erreur est survenue, veuillez réessayer.');
          window.dispatchEvent(new CustomEvent('hf-toast', {
            detail: { msg: this.submitError, type: 'error' },
          }));
          return;
        }
        this.orderResult = data;
        this.submitted = true;
        if (window.hfInstallInvite) window.hfInstallInvite('buyer', { delay: 2500 });
        window.dispatchEvent(new CustomEvent('hf-toast', {
          detail: { msg: 'Commande envoyée !', type: 'success' },
        }));
      } catch (e) {
        this.submitError = 'Connexion impossible. Vérifiez votre réseau et réessayez.';
      } finally {
        this.submitting = false;
      }
    },
  };
}

// ---------------------------------------------------------------------------
// imagePreview()
// Usage: x-data="imagePreview()" sur le wrapper du champ file
// ---------------------------------------------------------------------------
function imagePreview() {
  return {
    preview: null,
    onChange(event) {
      const file = event.target.files[0];
      this.preview = file ? URL.createObjectURL(file) : null;
    },
    clear() {
      this.preview = null;
    },
  };
}
