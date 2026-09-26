/* hf-live-pulse.js — page publique d'une vente (/f/<slug>/).
 *
 * 1. Pouls de la vente : interroge GET /f/<slug>/pulse/ (15 s en direct,
 *    60 s en attente, pause quand l'onglet est cache) pour
 *    - faire baisser le stock affiche quand d'AUTRES acheteurs commandent,
 *    - mettre a jour la preuve sociale (commandes, personnes en attente),
 *    - recharger une fois quand la vente se termine.
 * 2. Acheteur connu : memorise nom / telephone / adresse ecrite sur CET
 *    appareil apres une commande reussie, pour pre-remplir les suivantes
 *    (tunnel de commande raccourci). Rien n'est envoye ailleurs.
 *
 * Racine : <div id="hf-pulse" data-slug="..." data-state="live|waiting|ended">.
 * Textes : miroir exact de analytics.services.live_pulse.social_proof_lines.
 */
(function () {
  'use strict';

  /* ── Acheteur connu (localStorage, best-effort) ───────────────────────── */
  var BUYER_KEY = 'hf_buyer_v1';
  window.hfBuyer = {
    load: function () {
      try {
        var raw = window.localStorage.getItem(BUYER_KEY);
        var d = raw ? JSON.parse(raw) : null;
        return d && d.phone ? d : null;
      } catch (_) { return null; }
    },
    save: function (d) {
      try {
        window.localStorage.setItem(BUYER_KEY, JSON.stringify({
          name: (d.name || '').slice(0, 120),
          phone: (d.phone || '').slice(0, 32),
          address: (d.address || '').slice(0, 500)
        }));
      } catch (_) { /* navigation privee : on ignore */ }
    },
    clear: function () {
      try { window.localStorage.removeItem(BUYER_KEY); } catch (_) {}
    }
  };

  // Formulaires "M'alerter" : pre-remplissage nom / telephone.
  document.addEventListener('DOMContentLoaded', function () {
    var b = window.hfBuyer.load();
    if (!b) return;
    ['-w', '-end'].forEach(function (sfx) {
      var ph = document.getElementById('interest-phone' + sfx);
      var nm = document.getElementById('interest-name' + sfx);
      if (ph && !ph.value) ph.value = b.phone;
      if (nm && !nm.value && b.name) nm.value = b.name;
    });
  });

  /* ── Pouls ────────────────────────────────────────────────────────────── */
  var root = document.getElementById('hf-pulse');
  if (!root || !root.dataset.slug) return;

  var slug = root.dataset.slug;
  var state = root.dataset.state;
  if (state !== 'live' && state !== 'waiting') return;

  var url = '/f/' + encodeURIComponent(slug) + '/pulse/';
  var BASE = { live: 15000, waiting: 60000 };
  var delay = BASE[state];
  var timer = null;
  var inflight = false;
  var stopped = false;

  function plural(n, word) { return n + ' ' + word + (n > 1 ? 's' : ''); }

  function proofText(p) {
    var t = p.thresholds || { interested: 3, orders: 1 };
    var out = { live: '', live_sub: '', waiting: '' };
    if (p.interested >= t.interested) {
      out.waiting = p.interested + " personnes attendent l'ouverture";
    }
    if (p.orders >= t.orders) {
      var txt = plural(p.orders, 'commande');
      if (p.recent_orders >= 2) {
        txt += ' · ' + p.recent_orders + ' ces ' + p.recent_window_minutes + ' dernières min';
      }
      out.live = txt;
      var ago = p.last_order_seconds_ago;
      if (ago !== null && ago !== undefined && ago < 1800) {
        var mins = Math.floor(ago / 60);
        out.live_sub = mins < 1 ? "Dernière commande à l'instant"
                                : 'Dernière commande il y a ' + mins + ' min';
      }
    } else if (p.interested >= t.interested) {
      out.live = p.interested + ' personnes attendaient cette vente';
    }
    return out;
  }

  function setProof(id, txt, sub) {
    var el = document.getElementById(id);
    if (!el) return;
    var main = el.querySelector('[data-proof-main]');
    var s = el.querySelector('[data-proof-sub]');
    if (main) main.textContent = txt || '';
    if (s) { s.textContent = sub || ''; s.classList.toggle('hidden', !sub); }
    el.classList.toggle('hidden', !txt);
  }

  function applyStock(stock) {
    Object.keys(stock || {}).forEach(function (pid) {
      var badge = document.getElementById('stock-badge-' + pid);
      if (!badge) return;
      var cur = parseInt(badge.dataset.stock, 10);
      var next = parseInt(stock[pid], 10);
      // Monotone decroissant cote client : le pouls est cache 5 s cote
      // serveur, il ne doit pas "remonter" un stock que la propre commande
      // de l'acheteur vient de faire baisser.
      if (isNaN(next) || (!isNaN(cur) && next >= cur)) return;
      var initial = parseInt(badge.dataset.stockInitial, 10) || 0;
      if (typeof window.updateProductStockAfterOrder === 'function') {
        window.updateProductStockAfterOrder(parseInt(pid, 10), next, initial);
      }
      window.dispatchEvent(new CustomEvent('hf-stock', {
        detail: { productId: parseInt(pid, 10), stock: next }
      }));
    });
  }

  function apply(p) {
    var txt = proofText(p);
    setProof('hf-proof-waiting', txt.waiting);
    setProof('hf-proof-live', txt.live, txt.live_sub);
    if (state === 'live') {
      applyStock(p.stock);
      if (p.state === 'ended') {
        stop();
        window.location.reload();
      }
    }
    // waiting -> live : deja gere par hfWaiting (poll d'ouverture dedie).
  }

  function schedule(ms) {
    if (stopped) return;
    clearTimeout(timer);
    timer = setTimeout(tick, ms);
  }
  function stop() { stopped = true; clearTimeout(timer); }

  function tick() {
    if (document.hidden) return; // reprend sur visibilitychange
    if (inflight) return schedule(delay);
    inflight = true;
    fetch(url, { cache: 'no-store', credentials: 'omit' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (p) {
        delay = BASE[state];
        apply(p);
      })
      .catch(function () {
        delay = Math.min(delay * 2, 120000); // reseau mobile instable : on espace
      })
      .then(function () {
        inflight = false;
        if (!document.hidden) schedule(delay);
      });
  }

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) schedule(300);
    else clearTimeout(timer);
  });

  // Premier appel rapide : le HTML peut venir d'un 304 (ETag) un peu ancien.
  schedule(1500);
})();
