/* Barre de filtre des pages Distrib (Stock, Relevés).
 *
 * Filtrage cote navigateur, sans requete serveur. Delegation d'evenements sur
 * `document` : fonctionne aussi apres une navigation hx-boost (pas d'init par page).
 * Fichier separe : la CSP interdit les scripts inline (config/settings/_csp.py).
 *
 * Balisage :
 *   <div data-dx-filter="#cible" data-dx-also="#autre">   barre ; #autre = zone filtree en plus (hors compteur)
 *     <input type="search" data-dx-q>                      recherche libre (ignore les accents)
 *     <select data-dx-key="product">                       compare a data-product du bloc
 *     <select data-dx-key="invite" data-dx-scope="sub">     compare a data-invite des sous-lignes
 *     <span data-dx-count></span> <p data-dx-empty hidden>…</p>
 *   </div>
 *   <div id="cible">
 *     <div data-dx-item data-text="Robe wax" data-product="12">       bloc (carte produit)
 *       <div data-dx-sub data-text="Fanta Keita" data-invite="3">…</div>  sous-ligne (revendeur)
 *
 * Regles : un bloc dont le titre correspond a la recherche s'affiche avec toutes
 * ses sous-lignes ; sinon seules les sous-lignes qui correspondent s'affichent,
 * et le bloc est masque s'il n'en reste aucune. Un select ne s'applique qu'aux
 * elements qui portent l'attribut correspondant.
 */
(function () {
  "use strict";

  function norm(s) {
    return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  function matchesSelects(el, selects) {
    for (var i = 0; i < selects.length; i++) {
      var key = "data-" + selects[i].getAttribute("data-dx-key");
      if (selects[i].value && el.hasAttribute(key) && el.getAttribute(key) !== selects[i].value) return false;
    }
    return true;
  }

  function filterItem(item, q, itemSelects, subSelects, subActive) {
    if (!matchesSelects(item, itemSelects)) {
      item.hidden = true;
      return false;
    }
    var titleOk = !q || norm(item.getAttribute("data-text")).indexOf(q) !== -1;
    var subs = item.querySelectorAll("[data-dx-sub]");
    if (!subs.length) {
      var ok = titleOk && !(subActive && subSelects.length);
      item.hidden = !ok;
      return ok;
    }
    var anySub = false;
    subs.forEach(function (sub) {
      var subOk = matchesSelects(sub, subSelects) &&
        (titleOk || norm(sub.getAttribute("data-text")).indexOf(q) !== -1);
      sub.hidden = !subOk;
      if (subOk) anySub = true;
    });
    item.hidden = !anySub;
    return anySub;
  }

  function apply(bar) {
    var main = document.querySelector(bar.getAttribute("data-dx-filter"));
    if (!main) return;
    var qInput = bar.querySelector("[data-dx-q]");
    var q = norm(qInput ? qInput.value.trim() : "");
    var all = bar.querySelectorAll("select[data-dx-key]");
    var itemSelects = [], subSelects = [], subActive = false;
    all.forEach(function (s) {
      if (s.getAttribute("data-dx-scope") === "sub") {
        subSelects.push(s);
        if (s.value) subActive = true;
      } else {
        itemSelects.push(s);
      }
    });

    var items = main.querySelectorAll("[data-dx-item]");
    var shown = 0;
    items.forEach(function (item) {
      if (filterItem(item, q, itemSelects, subSelects, subActive)) shown++;
    });

    var alsoSel = bar.getAttribute("data-dx-also");
    if (alsoSel) {
      document.querySelectorAll(alsoSel).forEach(function (zone) {
        zone.querySelectorAll("[data-dx-item]").forEach(function (item) {
          filterItem(item, q, itemSelects, subSelects, subActive);
        });
      });
    }

    var count = bar.querySelector("[data-dx-count]");
    if (count) count.textContent = shown + " / " + items.length;
    var empty = bar.querySelector("[data-dx-empty]");
    if (empty) empty.hidden = shown !== 0 || items.length === 0;
  }

  function barOf(el) {
    return el && el.closest ? el.closest("[data-dx-filter]") : null;
  }

  function onChange(e) {
    var bar = barOf(e.target);
    if (bar) apply(bar);
  }
  document.addEventListener("input", onChange);
  document.addEventListener("change", onChange);
  document.addEventListener("click", function (e) {
    if (!e.target.closest || !e.target.closest("[data-dx-reset]")) return;
    var bar = barOf(e.target);
    if (!bar) return;
    bar.querySelectorAll("input[data-dx-q]").forEach(function (i) { i.value = ""; });
    bar.querySelectorAll("select[data-dx-key]").forEach(function (s) { s.value = ""; });
    apply(bar);
  });

  function initAll() {
    document.querySelectorAll("[data-dx-filter]").forEach(apply);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initAll);
  else initAll();
  document.addEventListener("htmx:load", initAll);
})();
