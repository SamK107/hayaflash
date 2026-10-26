/* Ecrans Distrib : rafraichissement HTMX sans casser la saisie, champs « Autre » (SPEC_03 §6, §15.8).
   CSP : fichier 'self', aucun script inline. */
(function () {
  'use strict';

  // 1. Rafraichissement toutes les 30 s : jamais pendant qu'un formulaire est ouvert ou en cours de saisie.
  document.addEventListener('htmx:beforeRequest', function (evt) {
    var el = evt.detail && evt.detail.elt;
    if (!el || !el.hasAttribute || !el.hasAttribute('data-dx-live')) return;
    var typing = document.activeElement && el.contains(document.activeElement) &&
      /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName);
    if (typing || el.querySelector('details[open]')) evt.preventDefault();
  });

  // 2. Compte a rebours entre deux rafraichissements (le serveur reste la reference).
  function fmt(seconds) {
    var m = Math.max(0, Math.floor(seconds / 60));
    var d = Math.floor(m / 1440), h = Math.floor((m % 1440) / 60), mm = m % 60;
    if (d) return d + ' j' + (h ? ' ' + h + ' h' : '');
    if (h) return h + ' h' + (mm ? ' ' + (mm < 10 ? '0' : '') + mm + ' min' : '');
    return Math.max(mm, 1) + ' min';
  }
  function tick() {
    var now = Date.now() / 1000;
    document.querySelectorAll('[data-dx-until]').forEach(function (el) {
      var left = parseInt(el.getAttribute('data-dx-until'), 10) - now;
      if (isNaN(left)) return;
      el.textContent = left <= 0 ? 'Confirmation automatique imminente' : 'Confirmée automatiquement dans ' + fmt(left);
    });
  }
  tick();
  setInterval(tick, 30000);

  // 3. Precision libre uniquement pour le motif « Autre » (SPEC_03 §15.8).
  function syncOther(select) {
    var form = select.form;
    if (!form) return;
    form.querySelectorAll('[data-dx-when-other]').forEach(function (box) {
      var show = select.value === box.getAttribute('data-dx-when-other');
      box.hidden = !show;
      box.querySelectorAll('input').forEach(function (input) { input.required = show; });
    });
  }
  document.addEventListener('change', function (evt) {
    if (evt.target && evt.target.matches && evt.target.matches('[data-dx-reason]')) syncOther(evt.target);
  });
  function init() { tick(); document.querySelectorAll('[data-dx-reason]').forEach(syncOther); }
  document.addEventListener('htmx:afterSwap', init);
  init();
})();
