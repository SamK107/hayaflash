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
        success: `Position capturee (±${this.accuracy}m)`,
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
