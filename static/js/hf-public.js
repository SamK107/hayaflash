/* HayaFlash — pages publiques acheteur.
 *
 * Charge par analytics/flash_sale_public.html (/f/<slug>/) et
 * flash_sales/public_calendar.html (/ventes/). Ex-scripts inline deplaces ici
 * pour la CSP (GOVERNANCE_SECURITE.md categorie 4). Les fonctions restent
 * globales : x-data="orderDrawer(...)" / "hfWaiting(...)" et les actions
 * data-hf-* de hf-base.js les appellent par leur nom.
 */

/* ════════════════ /f/<slug>/ : page d'une vente ════════════════ */
/* ── PAGE D'ATTENTE : chrono + poll d'ouverture ── */
function hfWaiting(openAtMs) {
  return {
    h: '--', m: '--', s: '--',
    colorBg: 'bg-green-50',
    colorText: 'text-green-800',
    opened: false,
    _tickId: null,
    _pollId: null,
    init() {
      this._tick();
      this._tickId = setInterval(() => this._tick(), 1000);

      // Reload precis a l'heure H + 2s (seulement si l'ouverture est dans le futur)
      const delay = openAtMs - Date.now() + 2000;
      if (delay > 0) {
        setTimeout(() => this._onOpen(), delay);
      }

      // Sync overlays
      ['interest-drawer-w'].forEach(id => {
        const dr = document.getElementById(id);
        const ov = document.getElementById(id.replace('drawer','overlay'));
        if (dr && ov) new MutationObserver(() => {
          ov.classList.toggle('hidden', !dr.classList.contains('open'));
        }).observe(dr, { attributes: true, attributeFilter: ['class'] });
      });
    },
    _onOpen() {
      // Heure d'ouverture atteinte : on verifie en arriere-plan (fetch, sans
      // recharger ni faire clignoter la page) et on ne recharge qu'UNE fois,
      // quand le serveur ne renvoie plus la page d'attente. Intervalle
      // croissant (3s, 6s, 12s... max 30s), abandon apres ~10 min.
      if (this.opened) return;
      if (this._tickId) { clearInterval(this._tickId); this._tickId = null; }
      this.h = '00'; this.m = '00'; this.s = '00';
      this.colorBg = 'bg-red-50'; this.colorText = 'text-red-700';
      this.opened = true;
      const started = Date.now();
      let wait = 3000;
      const check = async () => {
        try {
          const res = await fetch(location.href, { cache: 'no-store', credentials: 'same-origin' });
          const html = await res.text();
          if (res.ok && !html.includes('data-page-state=' + '"waiting"')) {
            location.reload();
            return;
          }
        } catch (e) { /* reseau instable : on reessaie plus tard */ }
        if (Date.now() - started > 10 * 60 * 1000) return;
        wait = Math.min(wait * 2, 30000);
        this._pollId = setTimeout(check, wait);
      };
      this._pollId = setTimeout(check, wait);
    },
    _tick() {
      const rem = Math.max(0, Math.floor((openAtMs - Date.now()) / 1000));
      if (rem <= 0) {
        // Heure passée mais on arrive ici pour la première fois → basculer en poll
        if (!this.opened) this._onOpen();
        return;
      }
      this.h = String(Math.floor(rem / 3600)).padStart(2, '0');
      this.m = String(Math.floor((rem % 3600) / 60)).padStart(2, '0');
      this.s = String(rem % 60).padStart(2, '0');
      if (rem <= 300) {
        this.colorBg = 'bg-red-50';   this.colorText = 'text-red-700';
      } else if (rem <= 900) {
        this.colorBg = 'bg-amber-50'; this.colorText = 'text-amber-700';
      } else {
        this.colorBg = 'bg-green-50'; this.colorText = 'text-green-800';
      }
    }
  };
}

/* ── BOUTON "M'ALERTER" ── */
function hfWaitingAlert(openAtMs) {
  // 1. Web Notification API
  if ('Notification' in window && Notification.permission !== 'denied') {
    Notification.requestPermission().then(p => {
      if (p === 'granted') {
        _hfScheduleNotif(openAtMs);
        _hfNotifConfirmed();
      } else {
        document.getElementById('interest-drawer-w').classList.add('open');
      }
    });
  } else {
    // Pas de notif disponible ou refusee → drawer telephone
    document.getElementById('interest-drawer-w').classList.add('open');
  }
}
function _hfScheduleNotif(openAtMs) {
  const ms = openAtMs - Date.now();
  if (ms > 180000) {
    setTimeout(() => new Notification('HayaFlash — Dans 2 minutes !', {
      body: 'La vente flash ouvre bientot. Soyez pret(e) !'
    }), ms - 120000);
  }
  if (ms > 0) {
    setTimeout(() => new Notification('HayaFlash — C\'est ouvert !', {
      body: 'Commandez maintenant — les stocks partent vite !'
    }), ms);
  }
}
function _hfNotifConfirmed() {
  const btn = document.getElementById('btn-notify-waiting');
  if (!btn) return;
  btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 mr-2 inline" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> Notification activee !';
  btn.className = btn.className.replace('bg-primary','bg-green-600').replace('hover:bg-red-700','hover:bg-green-700');
  btn.disabled = true;
}

/* ── Met a jour le stock affiche pour un produit, sans recharger la page ── */
function updateProductStockAfterOrder(productId, newStock, stockInitial) {
  newStock = Math.max(0, newStock);

  const badge = document.getElementById('stock-badge-' + productId);
  if (badge) {
    badge.dataset.stock = String(newStock);
    if (newStock <= 0) {
      badge.innerHTML = '<span class="text-sm font-bold text-gray-400">Épuisé</span>';
    } else if (newStock <= 5) {
      badge.innerHTML = '<span class="text-sm font-bold text-red-500">Plus que ' + newStock + ' !</span>';
    } else {
      badge.innerHTML = '<span class="text-sm text-gray-400">' + newStock + ' restant(s)</span>';
    }
  }

  const fill = document.getElementById('stock-bar-fill-' + productId);
  if (fill && stockInitial > 0) {
    const pct = Math.max(0, Math.round((newStock / stockInitial) * 100));
    fill.style.width = pct + '%';
    fill.classList.remove('bg-gray-300', 'bg-red-400', 'bg-green-400');
    fill.classList.add(newStock <= 0 ? 'bg-gray-300' : (newStock <= 5 ? 'bg-red-400' : 'bg-green-400'));
  }

  if (newStock <= 0) {
    const cta = document.getElementById('order-cta-' + productId);
    if (cta) {
      cta.innerHTML = '<div class="w-full bg-gray-100 text-gray-400 py-3.5 rounded-xl font-bold text-sm text-center">Épuisé</div>';
    }
  }
}

/* ── ALPINE : drawer commande (page live) ── */
function orderDrawer(saleId) {
  return {
    drawerOpen: false, orderSuccess: false, orderError: '', submitting: false,
    productId: null, productName: '', productPriceNum: 0, productPrice: '0',
    maxQty: 99, stockInitial: 0, orderUrl: '', qty: 1,
    customerName: '', customerPhone: '', address: '', note: '',
    submittedPhone: '', knownBuyer: false,
    geoStatus: 'idle', geoMethod: 'manual', latitude: null, longitude: null, geoAccuracy: null,
    isRecording: false, audioUrl: null, audioBase64: null,
    mediaRecorder: null, audioChunks: [],
    openOrder(pid, name, price, stock, orderUrl, stockInitial) {
      this.productId = pid; this.productName = name;
      this.productPriceNum = price;
      this.productPrice = Number(price).toLocaleString('fr-FR');
      this.maxQty = stock; this.stockInitial = stockInitial || stock; this.orderUrl = orderUrl;
      this.qty = 1; this.orderError = ''; this.orderSuccess = false;
      // Acheteur deja venu sur cet appareil : nom/tel/adresse pre-remplis
      // (hf-live-pulse.js, localStorage) -> commande en 2 touches.
      const known = window.hfBuyer && window.hfBuyer.load();
      if (known && !this.customerPhone) {
        this.customerName = known.name || '';
        this.customerPhone = known.phone || '';
        if (!this.address) this.address = known.address || '';
        this.knownBuyer = true;
      }
      this.drawerOpen = true; lucide.createIcons();
    },
    forgetBuyer() {
      if (window.hfBuyer) window.hfBuyer.clear();
      this.customerName = ''; this.customerPhone = ''; this.address = '';
      this.knownBuyer = false;
    },
    onStock(d) {
      // Stock baisse par d'autres acheteurs pendant que le tiroir est ouvert.
      if (!d || d.productId !== this.productId || this.orderSuccess) return;
      if (d.stock < this.maxQty) this.maxQty = d.stock;
      if (d.stock <= 0) {
        this.orderError = "Ce produit vient d'être épuisé.";
      } else if (this.qty > d.stock) {
        this.qty = d.stock;
      }
    },
    requestGeoPosition() {
      if (!navigator.geolocation) {
        this.geoStatus = 'unavailable';
        return;
      }
      this.geoStatus = 'loading';
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          this.latitude = pos.coords.latitude;
          this.longitude = pos.coords.longitude;
          this.geoAccuracy = Math.round(pos.coords.accuracy);
          this.geoMethod = 'gps';
          this.geoStatus = 'success';
        },
        (err) => {
          this.latitude = null; this.longitude = null; this.geoAccuracy = null;
          if (err.code === err.TIMEOUT) { this.geoMethod = 'timeout'; this.geoStatus = 'timeout'; }
          else if (err.code === err.PERMISSION_DENIED) { this.geoMethod = 'denied'; this.geoStatus = 'denied'; }
          else { this.geoMethod = 'manual'; this.geoStatus = 'error'; }
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
      );
    },
    startRecording() {
      if (!navigator.mediaDevices) {
        alert("Enregistrement audio non disponible sur ce navigateur.");
        return;
      }
      navigator.mediaDevices.getUserMedia({ audio: true })
        .then(stream => {
          this.audioChunks = [];
          this.mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
          this.mediaRecorder.ondataavailable = e => this.audioChunks.push(e.data);
          this.mediaRecorder.onstop = () => {
            const blob = new Blob(this.audioChunks, { type: 'audio/webm' });
            this.audioUrl = URL.createObjectURL(blob);
            const reader = new FileReader();
            reader.onloadend = () => { this.audioBase64 = reader.result.split(',')[1]; };
            reader.readAsDataURL(blob);
            stream.getTracks().forEach(t => t.stop());
          };
          this.mediaRecorder.start();
          this.isRecording = true;
        })
        .catch(() => alert("Microphone inaccessible."));
    },
    stopRecording() {
      this.mediaRecorder?.stop();
      this.isRecording = false;
    },
    clearAudio() {
      this.audioUrl = null;
      this.audioBase64 = null;
      this.audioChunks = [];
    },
    async submitOrder() {
      this.orderError = '';
      if (!this.customerPhone.trim()) { this.orderError = 'Le numéro de téléphone est obligatoire.'; return; }
      if (!this.address.trim() && !this.audioBase64) {
        this.orderError = "Indiquez votre adresse (par ecrit ou en message vocal).";
        return;
      }
      this.submitting = true;
      const reqId = 'hf-' + Date.now() + '-' + Math.random().toString(36).slice(2);
      const csrfToken = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';
      try {
        const res = await fetch('/api/v1/orders/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
          body: JSON.stringify({
            flash_sale_id: saleId,
            product_id: this.productId,
            name: this.customerName.trim() || 'Client',
            phone: this.customerPhone.trim(),
            quantity: this.qty,
            client_request_id: reqId,
            delivery: {
              address_text: this.address.trim(),
              delivery_notes: this.note.trim(),
              geo_method: this.geoMethod,
              latitude: this.latitude,
              longitude: this.longitude,
              geo_accuracy: this.geoAccuracy,
              audio_base64: this.audioBase64
            }
          })
        });
        const data = await res.json();
        if (res.ok) {
          this.submittedPhone = this.customerPhone.trim();
          this.orderSuccess = true;
          if (window.hfBuyer) window.hfBuyer.save({
            name: this.customerName.trim(), phone: this.customerPhone.trim(), address: this.address.trim()
          });
          this.knownBuyer = true;
          updateProductStockAfterOrder(this.productId, this.maxQty - this.qty, this.stockInitial);
          if (window.hfInstallInvite) window.hfInstallInvite('buyer', { delay: 2500 });
        }
        else { this.orderError = Object.values(data).flat()[0] || 'Une erreur est survenue.'; }
      } catch(e) {
        this.orderError = 'Connexion impossible. Verifiez votre reseau.';
      } finally { this.submitting = false; }
    }
  };
}

/* ── INTÉRÊT / ALERTE ── */
async function submitInterest(e, slug, sfx) {
  e.preventDefault();
  const phone = document.getElementById('interest-phone' + sfx).value.trim();
  const name  = document.getElementById('interest-name'  + sfx).value.trim();
  const errEl = document.getElementById('interest-error'       + sfx);
  const btn   = document.getElementById('interest-submit'      + sfx);
  const txtEl = document.getElementById('interest-submit-text' + sfx);
  const frmEl = document.getElementById('interest-form'        + sfx);
  const sucEl = document.getElementById('interest-success'     + sfx);
  if (!phone) { errEl.textContent = 'Le téléphone est obligatoire.'; errEl.classList.remove('hidden'); return; }
  errEl.classList.add('hidden'); btn.disabled = true; txtEl.textContent = 'Envoi...';
  const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';
  try {
    const res = await fetch('/f/' + slug + '/interest/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
      body: JSON.stringify({ phone, name })
    });
    if (res.ok || res.status === 201) {
      frmEl.classList.add('hidden'); sucEl.classList.remove('hidden'); lucide.createIcons();
      if (window.hfInstallInvite) window.hfInstallInvite('buyer', { delay: 2500 });
    } else {
      let msg = 'Une erreur est survenue. Réessayez.';
      try { const d = await res.json(); if (d && d.error) msg = d.error; } catch (_) {}
      errEl.textContent = msg; errEl.classList.remove('hidden');
      btn.disabled = false; txtEl.textContent = sfx ? 'Je veux etre prevenu(e)' : 'Confirmer ma reservation';
    }
  } catch(ex) {
    errEl.textContent = 'Connexion impossible.'; errEl.classList.remove('hidden');
    btn.disabled = false; txtEl.textContent = sfx ? 'Je veux etre prevenu(e)' : 'Confirmer ma reservation';
  }
}

/* ── DRAWER FIN DE VENTE ── */
function hfOpenInterestEnd() {
  const d = document.getElementById('interest-drawer-end');
  const o = document.getElementById('interest-overlay-end');
  if (d) d.classList.add('open');
  if (o) o.classList.remove('hidden');
}
function hfCloseInterestEnd() {
  const d = document.getElementById('interest-drawer-end');
  const o = document.getElementById('interest-overlay-end');
  if (d) d.classList.remove('open');
  if (o) o.classList.add('hidden');
}

/* ── OVERLAY FIN DE VENTE (page live : déclenché à end_time) ── */
document.addEventListener('DOMContentLoaded', function () {
  // Page live seulement : <div id="hf-sale-end" data-end="..."> pose par le template.
  const marker = document.getElementById('hf-sale-end');
  if (!marker) return;
  const endMs = new Date(marker.dataset.end).getTime();
  const delay = endMs - Date.now();
  function showSaleEnd() {
    const screen = document.getElementById('hf-sale-end-screen');
    if (!screen) return;
    screen.style.pointerEvents = 'auto';
    screen.style.opacity = '1';
    document.body.style.overflow = 'hidden';
    lucide.createIcons();
  }
  if (delay <= 0) {
    showSaleEnd();
  } else {
    setTimeout(showSaleEnd, delay);
  }
});

/* ── TTS ── */
var _hfSpeakBtn = null;
function hfSpeak(btn, text) {
  if (!window.speechSynthesis) return;
  speechSynthesis.cancel();
  if (_hfSpeakBtn) _hfSpeakBtn.classList.remove('btn-speaking', 'bg-orange-200');
  _hfSpeakBtn = btn; btn.classList.add('btn-speaking', 'bg-orange-200');
  var u = new SpeechSynthesisUtterance(text); u.lang = 'fr-FR'; u.rate = 0.95;
  u.onend = function() { btn.classList.remove('btn-speaking', 'bg-orange-200'); _hfSpeakBtn = null; };
  speechSynthesis.speak(u);
}

/* ── PWA : gere par static/js/hf-install.js (hfPwaInstall / hfInstallInvite) ── */

/* ════════════════ /ventes/ : calendrier public ════════════════ */
(function () {
  if (!document.getElementById('hfc-sales')) return;
  // Comptes a rebours de la liste + rafraichissement quand une vente change
  // de groupe (Bientot -> En direct, fin de vente, passage sous 1 h).
  var lastRefresh = 0;
  function refresh() {
    var now = Date.now();
    if (now - lastRefresh < 5000) return;
    lastRefresh = now;
    document.body.dispatchEvent(new Event('hfc-refresh'));
  }
  function fmt(ms) {
    var m = Math.max(0, Math.ceil(ms / 60000));
    if (m < 60) return m + ' min';
    var h = Math.floor(m / 60), r = m % 60;
    return h + ' h' + (r ? ' ' + (r < 10 ? '0' : '') + r : '');
  }
  function tick() {
    var now = Date.now();
    document.querySelectorAll('#hfc-sales .hfc-row').forEach(function (row) {
      var el = row.querySelector('[data-countdown]');
      if (row.dataset.end) {
        var left = Date.parse(row.dataset.end) - now;
        if (left <= 0) { refresh(); return; }
        if (el) el.textContent = 'finit dans ' + fmt(left);
      } else if (row.dataset.start) {
        var until = Date.parse(row.dataset.start) - now;
        if (until <= 0 || (row.dataset.later && until <= 3600000)) { refresh(); return; }
        if (el) el.textContent = 'dans ' + fmt(until);
      }
    });
  }
  tick();
  setInterval(tick, 1000);
})();
