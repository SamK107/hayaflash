/* Acces 1 de la confirmation cliente (SPEC_03 §15.3). CSP : fichier 'self', aucun script inline.
   Appelle /distrib/recu/ avec l'id de commande ET le telephone saisi ; le serveur ne rend le code
   que si les deux correspondent, et pose le cookie HttpOnly hf_receipts. */
window.hfDistribReceipt = function (orderId) {
  var box = document.querySelector('[data-distrib-hint-url]');
  var phoneInput = document.querySelector('[x-ref="customerPhone"]');
  if (!box || !orderId || !phoneInput) return Promise.resolve([]);
  var body = new URLSearchParams();
  body.set('order_id', orderId);
  body.set('phone', phoneInput.value || '');
  function attempt(triesLeft) {
    return fetch(box.dataset.distribHintUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': box.dataset.distribCsrf || '', 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    })
      .then(function (res) { return res.ok ? res.json() : { lines: [] }; })
      .then(function (data) {
        // La ligne de suivi est creee juste apres la commande (rappel differe) : un court nouvel essai.
        if (!data.lines.length && triesLeft > 0) {
          return new Promise(function (resolve) { setTimeout(resolve, 1500); }).then(function () { return attempt(triesLeft - 1); });
        }
        return data.lines;
      })
      .catch(function () { return []; });
  }
  return attempt(2);
};
