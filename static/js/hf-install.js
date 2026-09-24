/* HayaFlash — installation PWA (bouton permanent + bandeau d'invitation).
 *
 * - Capture unique de `beforeinstallprompt` (Chrome, Edge, Samsung Internet) :
 *   affiche les boutons `.hf-pwa-install` / `#hf-pwa-btn` et expose
 *   `hfPwaInstall()` (dialogue d'installation natif, 1 clic de confirmation
 *   impose par le navigateur -> icone bureau / ecran d'accueil).
 * - `hfInstallInvite(context)` affiche le bandeau d'invitation, UNIQUEMENT aux
 *   moments choisis (pas d'invitation spontanee a la visite) :
 *     'buyer'  -> apres une commande reussie ou un "M'alerter"
 *     'seller' -> apres la creation de sa 1re vente flash (flag de session,
 *                 voir core.context_processors.pwa_install)
 *   Au plus 2 fois par appareil et par contexte (1re fois + une relance au
 *   prochain declencheur si "Plus tard"), jamais si l'app est deja installee.
 * - Navigateurs sans installation native (iPhone, Firefox, navigateur integre
 *   WhatsApp/Facebook/Instagram…) : marche a suivre adaptee au navigateur.
 * - `appinstalled` -> message "HayaFlash est installee ✓".
 * Styles en ligne : le build Tailwind purge ne scanne pas ce fichier.
 */
(function () {
  'use strict';

  var MAX_ASKS = 2;
  function log(msg) { try { console.info('[HayaFlash installation] ' + msg); } catch (e) {} }
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

  var UA = window.navigator.userAgent || '';
  function isIOS() {
    return /iphone|ipad|ipod/i.test(UA)
      || (window.navigator.platform === 'MacIntel' && window.navigator.maxTouchPoints > 1);
  }
  function isAndroid() { return /android/i.test(UA); }
  function isMobile() { return /android|mobi/i.test(UA) || isIOS(); }

  /* Navigateur courant, pour la marche a suivre manuelle. 'inapp' = navigateur
   * integre d'une appli (WhatsApp, Facebook, Instagram, TikTok…), qui ne sait
   * pas installer d'app : il faut rouvrir le lien dans le vrai navigateur. */
  function browserKind() {
    if (/WhatsApp|FBAN|FBAV|FB_IAB|Instagram|Messenger|musical_ly|Bytedance|TikTok|Snapchat|Line\//i.test(UA)
        || (isAndroid() && /; wv\)/.test(UA))) return 'inapp';
    if (isIOS()) return 'ios';
    if (/SamsungBrowser/i.test(UA)) return 'samsung';
    if (/Firefox|FxiOS/i.test(UA)) return 'firefox';
    if (/Edg\//i.test(UA)) return 'edge';
    if (/Safari/i.test(UA) && !/Chrome|Chromium/i.test(UA)) return 'safari';
    return 'chrome';
  }

  var SHARE_ICON = '<span aria-hidden="true"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
    + 'stroke="currentColor" stroke-width="2" style="vertical-align:-2px"><path d="M12 3v12M7 8l5-5 5 5"/>'
    + '<path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/></svg></span>';

  function manualSteps(kind) {
    switch (kind) {
      case 'inapp':
        return isIOS()
          ? 'Ce lien est ouvert dans une application (WhatsApp…) qui ne permet pas l’installation. '
            + 'Touchez <b>•••</b> puis <b>« Ouvrir dans Safari »</b>, puis ' + SHARE_ICON
            + ' <b>Partager</b> → <b>« Sur l’écran d’accueil »</b>.'
          : 'Ce lien est ouvert dans une application (WhatsApp…) qui ne permet pas l’installation. '
            + 'Ouvrez-le dans <b>Chrome</b> (bouton ci-dessous, ou menu <b>⋮</b> → <b>« Ouvrir dans Chrome »</b>).';
      case 'ios':
        return 'Touchez ' + SHARE_ICON + ' <b>Partager</b> en bas de l’écran, puis <b>« Sur l’écran d’accueil »</b>.';
      case 'samsung':
        return 'Touchez le menu <b>≡</b> en bas, puis <b>« Ajouter la page à »</b> → <b>« Écran d’accueil »</b>.';
      case 'firefox':
        return isMobile()
          ? 'Ouvrez le menu <b>⋮</b> de Firefox, puis <b>« Installer »</b> ou <b>« Ajouter à l’écran d’accueil »</b>.'
          : 'Firefox ne sait pas installer d’applications sur ordinateur : ouvrez ce lien dans <b>Chrome</b> ou <b>Edge</b>.';
      case 'edge':
        return 'Menu <b>…</b> d’Edge → <b>« Applications »</b> → <b>« Installer ce site en tant qu’application »</b>.';
      case 'safari':
        return 'Menu <b>Fichier</b> de Safari → <b>« Ajouter au Dock »</b>.';
      default:
        return isMobile()
          ? 'Ouvrez le menu <b>⋮</b> de Chrome, puis <b>« Installer l’application »</b> ou <b>« Ajouter à l’écran d’accueil »</b>.'
          : 'Menu <b>⋮</b> de Chrome → <b>« Caster, enregistrer et partager »</b> → '
            + '<b>« Installer la page en tant qu’application »</b>.';
    }
  }

  /* Rouvre la page courante dans Chrome depuis un navigateur integre Android. */
  function chromeIntentUrl() {
    return 'intent://' + location.host + location.pathname + location.search
      + '#Intent;scheme=' + location.protocol.replace(':', '') + ';package=com.android.chrome;end';
  }

  var INSECURE_NOTE = '<br><i style="color:#B45309">Adresse non sécurisée (http) : '
    + 'l’installation demande un lien en https.</i>';

  function installedWhere() {
    return isMobile() ? 'sur votre écran d’accueil' : 'sur votre bureau et dans le menu Démarrer';
  }

  /* Chrome / Edge / Samsung sans proposition d'installation : le plus souvent
   * l'app est deja installee (l'evenement n'est alors jamais emis). */
  function maybeInstalledNote(kind) {
    return (kind === 'chrome' || kind === 'edge' || kind === 'samsung') && window.isSecureContext
      ? '<b>HayaFlash est peut-être déjà installée</b> : cherchez son icône ' + installedWhere() + '.<br>Sinon : '
      : '';
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
    // Chrome ne propose l'installation que si l'app N'EST PAS installee : le
    // marqueur local est donc perime (app desinstallee depuis) -> on l'oublie,
    // sinon l'invitation ne serait plus jamais reproposee sur cet appareil.
    if (store('hf_installed') === '1') { log('app desinstallee depuis -> marqueur efface'); store('hf_installed', '0'); }
    setInstallButtons(true);
    waiters.splice(0).forEach(function (fn) { fn(); });
    // Le navigateur propose l'installation APRES l'affichage des instructions
    // manuelles (evenement tardif) : on remplace le bandeau par le bouton
    // "Installer" (installation automatique, sans passer par le menu).
    if (banner && banner.getAttribute('data-mode') === 'manual') {
      var ctx = banner.getAttribute('data-context');
      log('installation native disponible -> bandeau "Installer"');
      if (banner.parentNode) banner.parentNode.removeChild(banner);
      banner = null;
      showBanner(ctx, 'native', true);
    }
  });

  window.addEventListener('appinstalled', function () {
    deferredPrompt = null;
    store('hf_installed', '1');
    setInstallButtons(false);
    closeBanner();
    toast('<b>HayaFlash est installée ✓</b><br>Retrouvez son icône ' + installedWhere() + '.', 6000);
  });

  window.hfPwaInstall = function () {
    if (!deferredPrompt) {
      // Le navigateur n'a pas (ou plus) d'installation a proposer : on explique
      // au lieu de ne rien faire.
      var kind = browserKind();
      toast(maybeInstalledNote(kind) + manualSteps(kind) + (window.isSecureContext ? '' : INSECURE_NOTE), 9000);
      return Promise.resolve(false);
    }
    var p = deferredPrompt;
    deferredPrompt = null;
    p.prompt();  // appele dans le clic : geste utilisateur exige par le navigateur
    return p.userChoice.then(function (r) {
      if (r && r.outcome === 'accepted') {
        store('hf_installed', '1');
        setInstallButtons(false);
        return true;
      }
      return false;
    });
  };

  /* Message court en haut de l'ecran (confirmation / aide), ferme au toucher. */
  var toastEl = null;
  function toast(html, ms) {
    if (toastEl && toastEl.parentNode) toastEl.parentNode.removeChild(toastEl);
    var el = toastEl = document.createElement('div');
    el.setAttribute('role', 'status');
    el.style.cssText = 'position:fixed;left:12px;right:12px;top:12px;z-index:10001;max-width:480px;'
      + 'margin:0 auto;background:#1A1A2E;color:#fff;border-radius:16px;padding:14px 16px;'
      + 'font:14px/1.45 inherit;box-shadow:0 10px 40px rgba(26,26,46,.35);cursor:pointer;'
      + 'opacity:0;transition:opacity .25s;';
    el.innerHTML = html;
    el.addEventListener('click', function () { if (el.parentNode) el.parentNode.removeChild(el); });
    document.body.appendChild(el);
    requestAnimationFrame(function () { el.style.opacity = '1'; });
    setTimeout(function () {
      el.style.opacity = '0';
      setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 300);
    }, ms || 5000);
  }

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

  var banner = null;

  function closeBanner() {
    if (!banner) return;
    var b = banner;
    banner = null;
    b.style.transform = 'translateY(120%)';
    setTimeout(function () { if (b.parentNode) b.parentNode.removeChild(b); }, 300);
  }

  function askCount(context) { return parseInt(store('hf_install_asks_' + context) || '0', 10) || 0; }

  function btnStyle(primary) {
    return 'flex:1;border:0;border-radius:12px;padding:12px 10px;font:700 14px/1 inherit;cursor:pointer;'
      + 'text-align:center;text-decoration:none;'
      + (primary ? 'background:#FF4D2E;color:#fff;' : 'background:#F3F4F6;color:#374151;');
  }

  /* mode : 'native' (bouton Installer -> dialogue du navigateur) ou 'manual'
   * (marche a suivre selon le navigateur). */
  function showBanner(context, mode, isUpgrade) {
    if (banner) return;
    var t = TEXTS[context] || TEXTS.buyer;
    var kind = browserKind();
    if (!isUpgrade) store('hf_install_asks_' + context, String(askCount(context) + 1));
    banner = document.createElement('div');
    banner.id = 'hf-install-banner';
    banner.setAttribute('data-mode', mode);
    banner.setAttribute('data-context', context);
    banner.setAttribute('role', 'dialog');
    banner.setAttribute('aria-label', t.title);
    banner.style.cssText = 'position:fixed;left:12px;right:12px;bottom:12px;z-index:10000;'
      + 'max-width:480px;margin:0 auto;background:#fff;border-radius:20px;padding:16px;'
      + 'box-shadow:0 10px 40px rgba(26,26,46,.25);font-family:inherit;color:#1A1A2E;'
      + 'transform:translateY(120%);transition:transform .3s cubic-bezier(.32,.72,0,1);';
    var buttons;
    if (mode === 'native') {
      buttons = '<button type="button" data-hf="later" style="' + btnStyle(false) + '">Plus tard</button>'
        + '<button type="button" data-hf="install" style="' + btnStyle(true) + '">Installer</button>';
    } else if (kind === 'inapp' && isAndroid()) {
      buttons = '<button type="button" data-hf="later" style="' + btnStyle(false) + '">Plus tard</button>'
        + '<a href="' + chromeIntentUrl() + '" data-hf="chrome" style="' + btnStyle(true) + '">Ouvrir dans Chrome</a>';
    } else {
      buttons = '<button type="button" data-hf="later" style="' + btnStyle(true) + '">J’ai compris</button>';
    }
    banner.innerHTML =
      '<div style="display:flex;gap:12px;align-items:flex-start">'
      + '<img src="' + t.icon + '" alt="" width="48" height="48" style="border-radius:12px;flex-shrink:0">'
      + '<div style="flex:1;min-width:0">'
      + '<p style="margin:0 0 4px;font-weight:800;font-size:15px">' + t.title + '</p>'
      + '<p style="margin:0 0 6px;font-size:13px;line-height:1.45;color:#4B5563">' + t.body + '</p>'
      + (mode === 'native' ? '' : '<p style="margin:0;font-size:13px;line-height:1.45;color:#1A1A2E">'
        + maybeInstalledNote(kind) + manualSteps(kind) + (window.isSecureContext ? '' : INSECURE_NOTE) + '</p>')
      + '</div></div>'
      + '<div style="display:flex;gap:8px;margin-top:14px">' + buttons + '</div>';
    banner.addEventListener('click', function (e) {
      var action = e.target.closest && e.target.closest('[data-hf]');
      if (!action) return;
      if (action.getAttribute('data-hf') === 'install') window.hfPwaInstall();
      closeBanner();
    });
    document.body.appendChild(banner);
    if (isUpgrade) { banner.style.transition = 'none'; banner.style.transform = 'translateY(0)'; return; }
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
    if (isStandalone()) { log('deja ouvert en mode app installee'); return; }
    if (store('hf_installed') === '1') { log('deja installee sur cet appareil'); return; }
    if (askCount(context) >= MAX_ASKS) { log('invitation deja proposee ' + MAX_ASKS + ' fois'); return; }

    setTimeout(function () {
      var kind = browserKind();
      if (deferredPrompt) { showBanner(context, 'native'); return; }
      // Pas d'installation native possible dans ces navigateurs : marche a
      // suivre tout de suite, inutile d'attendre l'evenement.
      if (kind === 'inapp' || kind === 'ios' || kind === 'firefox' || kind === 'safari') {
        showBanner(context, 'manual');
        return;
      }
      // Chrome / Edge / Samsung : l'evenement peut arriver apres le chargement
      // -> on l'attend 3 s, sinon marche a suivre manuelle.
      var done = false;
      waiters.push(function () { if (!done) { done = true; showBanner(context, 'native'); } });
      setTimeout(function () {
        if (done) return;
        done = true;
        log('installation native non proposee par le navigateur -> instructions manuelles ('
          + (window.isSecureContext ? 'page securisee : app deja installee, ou certificat en erreur ?'
                                    : 'page NON securisee (http) : installation impossible') + ')');
        showBanner(context, 'manual');
      }, 3000);
    }, delay);
  };
})();
