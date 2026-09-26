/* HayaFlash — scripts communs a toutes les pages (charge par templates/base.html).
 *
 * Remplace les <script> inline et les attributs on*= des templates (CSP sans
 * 'unsafe-inline', voir GOVERNANCE_SECURITE.md categorie 4). Les donnees
 * serveur arrivent par attributs data-* ou {{ value|json_script }}, jamais par
 * interpolation dans du JS.
 *
 * Actions declaratives (delegation, fonctionnent aussi apres un swap HTMX) :
 *   data-hf-confirm="Message"        sur <form> (submit) ou bouton/lien (click)
 *   data-hf-copy="texte"             copie le texte puis affiche « ✓ Copié »
 *   data-hf-copy-from="#sel"         copie le textContent de l'element cible
 *   data-hf-show="#sel"              retire la classe hidden de la cible
 *   data-hf-hide="#sel"              ajoute la classe hidden a la cible
 *   data-hf-close="#sel"             retire la classe open de la cible (drawers)
 *   data-hf-backdrop                 clic sur l'element lui-meme (pas ses
 *                                    enfants) -> ajoute hidden (modales)
 *   data-hf-call="nom"               appelle une fonction globale de la liste
 *                                    blanche HF_CALLS ci-dessous, sans argument
 *   data-hf-speak="texte"            lecture vocale (hfSpeak, hf-public.js)
 *   data-hf-waiting-alert="ms"       bouton « M'alerter » (hf-public.js)
 *   data-hf-interest="slug"          + data-hf-interest-sfx : formulaire
 *                                    d'interet (submitInterest, hf-public.js)
 *   data-hf-nav-prefix="?a=1&b="     <select> : navigue vers prefix + valeur
 *   img[data-zoom]                   double-clic -> lightbox plein ecran
 */
(function () {
  'use strict';

  // Seules ces fonctions globales sont appelables via data-hf-call : un
  // attribut injecte ne doit pas pouvoir declencher n'importe quel window.*.
  var HF_CALLS = ['hfPwaInstall', 'hfOpenInterestEnd', 'hfCloseInterestEnd', 'hfZoomClose'];

  function $(sel) { return sel ? document.querySelector(sel) : null; }

  /* ── HTMX : en-tete CSRF (lu depuis le cookie) ── */
  document.addEventListener('DOMContentLoaded', function () {
    var token = document.cookie.match(/csrftoken=([^;]+)/);
    if (token) {
      document.body.setAttribute('hx-headers', JSON.stringify({ 'X-CSRFToken': token[1] }));
    }
  });

  /* ── Messages Django -> toasts (<div data-hf-toast> dans base.html) ── */
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-hf-toast]').forEach(function (el) {
      window.dispatchEvent(new CustomEvent('hf-toast', {
        detail: { msg: el.dataset.hfToast, type: el.dataset.hfToastType || 'info' }
      }));
    });
  });

  /* ── Invitation a installer la PWA demandee par la vue precedente ── */
  document.addEventListener('DOMContentLoaded', function () {
    var el = document.querySelector('[data-hf-install-invite]');
    if (el && window.hfInstallInvite) {
      window.hfInstallInvite(el.dataset.hfInstallInvite, { delay: 2500 });
    }
  });

  /* ── Icones Lucide ── */
  function markZoomables(root) {
    (root || document).querySelectorAll('img[data-zoom]').forEach(function (img) {
      img.style.cursor = 'zoom-in';
    });
  }
  document.addEventListener('DOMContentLoaded', function () {
    if (window.lucide) lucide.createIcons();
    markZoomables();
  });
  document.addEventListener('htmx:afterSwap', function () {
    if (window.lucide) lucide.createIcons();
    markZoomables();
  });

  /* ── Lightbox universelle (hfZoom / hfZoomClose) ── */
  var ov = null;
  function buildOverlay() {
    if (ov) return;
    ov = document.createElement('div');
    ov.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.92);'
      + 'display:none;align-items:center;justify-content:center;cursor:zoom-out';
    var img = document.createElement('img');
    img.id = 'hf-zoom-ov-img';
    img.style.cssText = 'width:90vw;height:90vh;object-fit:contain;'
      + 'border-radius:8px;user-select:none;cursor:default';
    img.addEventListener('click', function (e) { e.stopPropagation(); });
    img.addEventListener('dblclick', function (e) { e.stopPropagation(); window.hfZoomClose(); });
    var btn = document.createElement('button');
    btn.textContent = '✕';
    btn.style.cssText = 'position:absolute;top:12px;right:12px;width:38px;height:38px;'
      + 'background:rgba(255,255,255,.2);border:none;border-radius:50%;color:#fff;'
      + 'font-size:20px;cursor:pointer;line-height:1';
    btn.addEventListener('click', function () { window.hfZoomClose(); });
    ov.appendChild(img);
    ov.appendChild(btn);
    ov.addEventListener('click', function () { window.hfZoomClose(); });
    document.body.appendChild(ov);
  }
  window.hfZoom = function (imgEl) {
    buildOverlay();
    var img = document.getElementById('hf-zoom-ov-img');
    img.src = imgEl.src;
    img.alt = imgEl.alt || '';
    ov.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  };
  window.hfZoomClose = function () {
    if (ov) ov.style.display = 'none';
    document.body.style.overflow = '';
  };
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') window.hfZoomClose(); });
  document.addEventListener('dblclick', function (e) {
    var img = e.target.closest && e.target.closest('img[data-zoom]');
    if (img) window.hfZoom(img);
  });

  /* ── Actions declaratives data-hf-* ── */
  function flashCopied(btn) {
    if (!btn.dataset.hfCopyLabel) btn.dataset.hfCopyLabel = btn.textContent;
    btn.textContent = '✓ Copié';
    setTimeout(function () { btn.textContent = btn.dataset.hfCopyLabel; }, 2000);
  }

  document.addEventListener('click', function (e) {
    var t = e.target;
    if (!t.closest) return;

    // Clic sur le fond d'une modale (pas sur son contenu) -> fermeture.
    if (t.hasAttribute('data-hf-backdrop')) {
      t.classList.add('hidden');
      return;
    }

    var confirmEl = t.closest('[data-hf-confirm]:not(form)');
    if (confirmEl && !window.confirm(confirmEl.dataset.hfConfirm)) {
      e.preventDefault();
      e.stopImmediatePropagation();
      return;
    }

    var el = t.closest('[data-hf-copy], [data-hf-copy-from]');
    if (el) {
      var text = el.hasAttribute('data-hf-copy')
        ? el.dataset.hfCopy
        : (($(el.dataset.hfCopyFrom) || {}).textContent || '').trim();
      if (navigator.clipboard) navigator.clipboard.writeText(text);
      flashCopied(el);
      return;
    }

    el = t.closest('[data-hf-show], [data-hf-hide], [data-hf-close]');
    if (el) {
      var target;
      if ((target = $(el.dataset.hfShow))) target.classList.remove('hidden');
      if ((target = $(el.dataset.hfHide))) target.classList.add('hidden');
      if ((target = $(el.dataset.hfClose))) target.classList.remove('open');
      return;
    }

    el = t.closest('[data-hf-call]');
    if (el) {
      var name = el.dataset.hfCall;
      if (HF_CALLS.indexOf(name) !== -1 && typeof window[name] === 'function') window[name]();
      return;
    }

    el = t.closest('[data-hf-speak]');
    if (el && window.hfSpeak) { window.hfSpeak(el, el.dataset.hfSpeak); return; }

    el = t.closest('[data-hf-waiting-alert]');
    if (el && window.hfWaitingAlert) { window.hfWaitingAlert(Number(el.dataset.hfWaitingAlert)); }
  });

  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (form.hasAttribute('data-hf-confirm') && !window.confirm(form.dataset.hfConfirm)) {
      e.preventDefault();
      return;
    }
    if (form.hasAttribute('data-hf-interest') && window.submitInterest) {
      window.submitInterest(e, form.dataset.hfInterest, form.dataset.hfInterestSfx || '');
    }
  });

  document.addEventListener('change', function (e) {
    var sel = e.target;
    if (sel.hasAttribute && sel.hasAttribute('data-hf-nav-prefix') && sel.value) {
      window.location.href = sel.dataset.hfNavPrefix + encodeURIComponent(sel.value);
    }
  });

  /* ── PWA : service worker ── */
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      // Ancien SW enregistre sous /static/ (portee inutile) : on le retire.
      if (navigator.serviceWorker.getRegistrations) {
        navigator.serviceWorker.getRegistrations().then(function (regs) {
          regs.forEach(function (r) { if (/\/static\/$/.test(r.scope)) r.unregister(); });
        });
      }
      navigator.serviceWorker.register('/sw.js', { scope: '/' })
        .catch(function (err) { console.warn('SW registration failed:', err); });
    });
  }
})();
