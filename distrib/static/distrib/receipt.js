/* Acces 1 de la confirmation cliente (SPEC_03 §15.3). CSP : fichier 'self', aucun script inline.
   Appelle /distrib/recu/ avec l'id de commande ET le telephone saisi ; le serveur ne rend le code
   que si les deux correspondent, et pose le cookie HttpOnly hf_receipts.
   Utilise par /order/ (formulaire) et par le tiroir de /f/<slug>/. Resultat : { lines, blocked }.
   - 429 : jamais de nouvel essai, `blocked` est vrai pour que l'ecran previenne la cliente ;
   - un nouvel essai seulement si le serveur dit que la ligne de suivi n'est pas encore creee (`retry`). */
window.hfDistribReceipt = function (orderId, phone) {
  var empty = { lines: [], blocked: false };
  var box = document.querySelector('[data-distrib-hint-url]');
  if (!box || !orderId) return Promise.resolve(empty);
  if (!phone) {
    var phoneInput = document.querySelector('[x-ref="customerPhone"]');
    phone = phoneInput ? phoneInput.value : '';
  }
  if (!phone) return Promise.resolve(empty);
  var body = new URLSearchParams();
  body.set('order_id', orderId);
  body.set('phone', phone);

  function cookieToken() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : (box.dataset.distribCsrf || '');
  }
  // La page publique d'une vente est servie en cache, sans jeton : on le demande au serveur si besoin.
  function csrfToken() {
    var token = cookieToken();
    if (token) return Promise.resolve(token);
    return fetch(box.dataset.distribCsrfUrl, { credentials: 'same-origin' })
      .then(function (res) { return res.ok ? res.json() : { csrf: '' }; })
      .then(function (data) { return data.csrf || ''; })
      .catch(function () { return ''; });
  }
  function attempt(token, triesLeft) {
    return fetch(box.dataset.distribHintUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': token, 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    })
      .then(function (res) {
        if (res.status === 429) return { lines: [], blocked: true };
        return res.ok ? res.json() : { lines: [] };
      })
      .then(function (data) {
        if (data.blocked) return { lines: [], blocked: true };
        if (!data.lines.length && data.retry && triesLeft > 0) {
          return new Promise(function (resolve) { setTimeout(resolve, 1500); }).then(function () { return attempt(token, triesLeft - 1); });
        }
        return { lines: data.lines, blocked: false };
      })
      .catch(function () { return empty; });
  }
  return csrfToken().then(function (token) { return attempt(token, 2); });
};
