/* HayaFlash — installation PWA (bouton permanent + bandeau d'invitation).
 *
 * - Capture unique de `beforeinstallprompt` (Android/Chrome) : affiche les
 *   boutons `.hf-pwa-install` / `#hf-pwa-btn` et expose `hfPwaInstall()`.
 * - `hfInstallInvite(context)` affiche un bandeau d'invitation au BON moment :
 *     'buyer'  -> appele apres une commande reussie ou un "M'alerter"
 *     'seller' -> appele sur les pages vendeur (nav vendeur)
 *   Jamais si l'app est deja installee ; "Plus tard" = pas de nouvel
 *   affichage pendant 7 jours ; iPhone/iPad = instructions manuelles
 *   (Safari n'emet pas `beforeinstallprompt`).
 * Styles en ligne : le build Tailwind purge ne scanne pas ce fichier.
 */
(function () {
  'use strict';

  var SNOOZE_DAYS = 7;
  var deferredPrompt = null;
  var waiters = [];

  function store(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      window.localStorage.setItem(key, value);
    } catch (e) { /* navigation privee / stockage bloque : on ignore */ }
    return null;
  }

  function isStandalone() {
    return (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches)
      || window.navigator.standalone === true;
  }

  function isIOS() {
    var ua = window.navigator.userAgent || '';
    return /iphone|ipad|ipod/i.test(ua)
      || (window.navigator.platform === 'MacIntel' && window.navigator.maxTouchPoints > 1);
  }

  function setInstallButtons(visible) {
    document.querySelectorAll('.hf-pwa-install').forEach(function (el) {
      el.style.display = visible ? 'flex' : 'none';
    });
    var btn = document.getElementById('hf-pwa-btn');
    if (btn) {
      btn.classList.toggle('hidden', !visible);
      btn.classList.toggle('flex', visible);
    }
  }

  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    deferredPrompt = e;
    setInstallButtons(true);
    waiters.splice(0).forEach(function (fn) { fn(); });
  });

  window.addEventListener('appinstalled', function () {
    deferredPrompt = null;
    store('hf_installed', '1');
    setInstallButtons(false);
    closeBanner();
  });

  window.hfPwaInstall = function () {
    if (!deferredPrompt) return Promise.resolve(false);
    var p = deferredPrompt;
    deferredPrompt = null;
    p.prompt();
    return p.userChoice.then(function (r) {
      if (r && r.outcome === 'accepted') {
        store('hf_installed', '1');
        setInstallButtons(false);
        return true;
      }
      return false;
    });
  };

  /* ── Bandeau ─────────────────────────────────────────────────────────── */

  var TEXTS = {
    buyer: {
      icon: '/static/img/apple-touch-icon-buyer.png',
      title: 'Installez HayaFlash',
      body: 'Suivez votre commande et soyez alerté des prochaines ventes, en un clic depuis votre écran d’accueil.'
    },
    seller: {
      icon: '/static/img/apple-touch-icon.png',
      title: 'Installez votre espace vendeur',
      body: 'Vos ventes et vos commandes en un clic depuis l’écran d’accueil, même pendant votre live.'
    }
  };
  var IOS_BODY = 'Touchez <b>Partager</b> <span aria-hidden="true">'
    + '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    + 'style="vertical-align:-2px"><path d="M12 3v12M7 8l5-5 5 5"/><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/></svg>'
    + '</span> en bas de l’écran, puis <b>« Sur l’écran d’accueil »</b>.';

  var banner = null;

  function closeBanner() {
    if (!banner) return;
    var b = banner;
    banner = null;
    b.style.transform = 'translateY(120%)';
    setTimeout(function () { if (b.parentNode) b.parentNode.removeChild(b); }, 300);
  }

  function snooze(context) {
    store('hf_install_snooze_' + context, String(Date.now() + SNOOZE_DAYS * 86400000));
  }

  function isSnoozed(context) {
    var until = parseInt(store('hf_install_snooze_' + context) || '0', 10);
    return until && Date.now() < until;
  }

  function btnStyle(primary) {
    return 'flex:1;border:0;border-radius:12px;padding:12px 10px;font:700 14px/1 inherit;cursor:pointer;'
      + (primary ? 'background:#FF4D2E;color:#fff;' : 'background:#F3F4F6;color:#374151;');
  }

  function showBanner(context, ios) {
    if (banner) return;
    var t = TEXTS[context] || TEXTS.buyer;
    banner = document.createElement('div');
    banner.id = 'hf-install-banner';
    banner.setAttribute('role', 'dialog');
    banner.setAttribute('aria-label', t.title);
    banner.style.cssText = 'position:fixed;left:12px;right:12px;bottom:12px;z-index:10000;'
      + 'max-width:480px;margin:0 auto;background:#fff;border-radius:20px;padding:16px;'
      + 'box-shadow:0 10px 40px rgba(26,26,46,.25);font-family:inherit;color:#1A1A2E;'
      + 'transform:translateY(120%);transition:transform .3s cubic-bezier(.32,.72,0,1);';
    banner.innerHTML =
      '<div style="display:flex;gap:12px;align-items:flex-start">'
      + '<img src="' + t.icon + '" alt="" width="48" height="48" style="border-radius:12px;flex-shrink:0">'
      + '<div style="flex:1;min-width:0">'
      + '<p style="margin:0 0 4px;font-weight:800;font-size:15px">' + t.title + '</p>'
      + '<p style="margin:0;font-size:13px;line-height:1.45;color:#4B5563">' + (ios ? IOS_BODY : t.body) + '</p>'
      + '</div></div>'
      + '<div style="display:flex;gap:8px;margin-top:14px">'
      + (ios
        ? '<button type="button" data-hf="later" style="' + btnStyle(true) + '">J’ai compris</button>'
        : '<button type="button" data-hf="later" style="' + btnStyle(false) + '">Plus tard</button>'
          + '<button type="button" data-hf="install" style="' + btnStyle(true) + '">Installer</button>')
      + '</div>';
    banner.addEventListener('click', function (e) {
      var action = e.target.closest && e.target.closest('[data-hf]');
      if (!action) return;
      if (action.getAttribute('data-hf') === 'install') {
        window.hfPwaInstall().then(function (ok) { if (!ok) snooze(context); });
      } else {
        snooze(context);
      }
      closeBanner();
    });
    document.body.appendChild(banner);
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { if (banner) banner.style.transform = 'translateY(0)'; });
    });
  }

  /**
   * Propose l'installation si pertinent. `opts.delay` (ms) laisse le temps a
   * l'utilisateur de voir la confirmation de sa commande avant le bandeau.
   */
  window.hfInstallInvite = function (context, opts) {
    context = context === 'seller' ? 'seller' : 'buyer';
    var delay = (opts && opts.delay) || 0;
    if (isStandalone() || store('hf_installed') === '1' || isSnoozed(context)) return;

    setTimeout(function () {
      if (isIOS()) { showBanner(context, true); return; }
      if (deferredPrompt) { showBanner(context, false); return; }
      // Chrome n'a pas encore emis l'evenement : on l'attend 15 s maximum.
      var done = false;
      waiters.push(function () { if (!done) { done = true; showBanner(context, false); } });
      setTimeout(function () { done = true; }, 15000);
    }, delay);
  };
})();
