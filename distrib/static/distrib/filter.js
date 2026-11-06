/* Barre de filtre des pages Distrib (Stock, Relevés).
 *
 * Filtrage cote navigateur, sans requete serveur. Delegation d'evenements sur
 * `document` : fonctionne aussi apres une navigation hx-boost (pas d'init par page).
 * Fichier separe : la CSP interdit les scripts inline (config/settings/_csp.py).
 *
 * Balisage attendu :
 *   <div data-dx-filter="#cible">            conteneur de la barre
 *     <input type="search" data-dx-q>         recherche libre (ignore les accents)
 *     <select data-dx-key="product">          compare a data-product de chaque bloc
 *     <span data-dx-count></span>             « 3 / 48 »
 *     <p data-dx-empty hidden>…</p>           message si aucun resultat
 *   </div>
 *   <div id="cible"> <div data-dx-item data-text="…" data-product="12">…</div> … </div>
 */
(function () {
  "use strict";

  function norm(s) {
    return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  function apply(bar) {
    var target = document.querySelector(bar.getAttribute("data-dx-filter"));
    if (!target) return;
    var qInput = bar.querySelector("[data-dx-q]");
    var q = norm(qInput ? qInput.value.trim() : "");
    var selects = bar.querySelectorAll("select[data-dx-key]");
    var items = target.querySelectorAll("[data-dx-item]");
    var shown = 0;
    items.forEach(function (item) {
      var ok = !q || norm(item.getAttribute("data-text")).indexOf(q) !== -1;
      selects.forEach(function (sel) {
        if (ok && sel.value && item.getAttribute("data-" + sel.getAttribute("data-dx-key")) !== sel.value) ok = false;
      });
      item.hidden = !ok;
      if (ok) shown++;
    });
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
