/* Bandeau discret « Tu as reçu ta commande ? » (SPEC_03 §15.3). CSP : fichier 'self'.
   Le fragment HTML du pied de page est identique pour tous ; le bandeau, lui, est charge ici depuis
   un endpoint prive (no-store) qui lit le cookie HttpOnly. Aucun appel reseau sans le drapeau hf_rc. */
(function () {
  var holder = document.getElementById('hf-distrib-banner');
  if (!holder || document.cookie.indexOf('hf_rc=1') === -1) return;
  try { if (sessionStorage.getItem('hf_distrib_banner_closed') === '1') return; } catch (e) { /* stockage indisponible */ }
  fetch(holder.dataset.url, { credentials: 'same-origin' })
    .then(function (res) { return res.status === 200 ? res.text() : ''; })
    .then(function (html) {
      if (!html.trim()) return;
      holder.innerHTML = html;
      holder.hidden = false;
      var close = holder.querySelector('[data-distrib-dismiss]');
      if (close) {
        close.addEventListener('click', function () {
          holder.hidden = true;
          try { sessionStorage.setItem('hf_distrib_banner_closed', '1'); } catch (e) { /* ignore */ }
        });
      }
    })
    .catch(function () { /* discret : jamais d'erreur visible */ });
})();
