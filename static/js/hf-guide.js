/* HayaFlash — guide « Ta première vente flash » : carrousel accessible, sans dépendance.
   Défilement natif (scroll-snap) + flèches, points, clavier et ancre #etape-N. Rien ne défile tout seul. */
(function () {
  "use strict";
  var track = document.getElementById("hg-track");
  if (!track) return;
  var slides = Array.prototype.slice.call(track.querySelectorAll(".hg-slide"));
  var dots = Array.prototype.slice.call(document.querySelectorAll(".hg-dot"));
  var prev = document.getElementById("hg-prev");
  var next = document.getElementById("hg-next");
  var cur = document.getElementById("hg-current");
  var chap = document.getElementById("hg-chapter");
  var bar = document.getElementById("hg-progress");
  var index = 0;
  var page = document.getElementById("hg");

  /* Hauteur du menu au-dessus du guide : la page occupe exactement le reste de l'écran */
  function fit() {
    if (!page) return;
    /* haut de la zone = bas du menu (le conteneur parent reste dans le flux) */
    var host = page.parentElement || document.body;
    var top = host.getBoundingClientRect().top + (parseFloat(getComputedStyle(host).paddingTop) || 0);
    page.style.setProperty("--hg-top", Math.max(0, Math.round(top)) + "px");
    document.documentElement.classList.add("hg-lock");
    window.scrollTo(0, 0);
    if (slides[index]) track.scrollLeft = slides[index].offsetLeft - track.offsetLeft;
  }
  fit();
  window.addEventListener("resize", fit);
  window.addEventListener("orientationchange", fit);

  function go(i, smooth) {
    i = Math.max(0, Math.min(slides.length - 1, i));
    track.scrollTo({ left: slides[i].offsetLeft - track.offsetLeft, behavior: smooth === false ? "auto" : "smooth" });
  }

  function update(i) {
    index = i;
    cur.textContent = i + 1;
    chap.textContent = slides[i].getAttribute("data-chapter");
    bar.style.width = ((i + 1) / slides.length) * 100 + "%";
    prev.disabled = i === 0;
    next.disabled = i === slides.length - 1;
    dots.forEach(function (d, k) { d.setAttribute("aria-current", k === i ? "true" : "false"); });
    try { history.replaceState(null, "", "#etape-" + (i + 1)); } catch (e) { /* ignoré */ }
  }

  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting && en.intersectionRatio >= 0.6) update(slides.indexOf(en.target));
      });
    }, { root: track, threshold: [0.6] });
    slides.forEach(function (s) { io.observe(s); });
  } else {
    track.addEventListener("scroll", function () {
      update(Math.round(track.scrollLeft / track.clientWidth));
    }, { passive: true });
  }

  prev.addEventListener("click", function () { go(index - 1); });
  next.addEventListener("click", function () { go(index + 1); });
  dots.forEach(function (d) {
    d.addEventListener("click", function () { go(parseInt(d.getAttribute("data-index"), 10)); });
  });
  document.addEventListener("keydown", function (e) {
    if (e.target && /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
    if (e.key === "ArrowRight") { e.preventDefault(); go(index + 1); }
    if (e.key === "ArrowLeft") { e.preventDefault(); go(index - 1); }
  });

  var m = /^#etape-(\d+)$/.exec(location.hash || "");
  var start = m ? parseInt(m[1], 10) - 1 : 0;
  update(Math.max(0, Math.min(slides.length - 1, start)));
  if (start > 0) window.requestAnimationFrame(function () { go(start, false); });
})();
