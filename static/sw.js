/* HayaFlash Service Worker — cache assets statiques, offline gracieux */
const CACHE = 'hayaflash-v1';
const STATIC_ASSETS = [
  '/static/manifest.json',
  '/static/js/hf-components.js',
  '/static/img/icon-192.png',
  '/static/img/icon-512.png',
];

/* ── Install : pré-cache les assets critiques ─────────────────────────── */
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

/* ── Activate : nettoie les anciens caches ────────────────────────────── */
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

/* ── Fetch : cache-first pour les assets, network-first pour les pages ── */
self.addEventListener('fetch', event => {
  const { request } = event;

  // Ne pas intercepter les requêtes non-GET
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // Assets statiques : cache-first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then(cached => cached || fetch(request).then(resp => {
        if (resp.ok) {
          const clone = resp.clone();
          caches.open(CACHE).then(c => c.put(request, clone));
        }
        return resp;
      }))
    );
    return;
  }

  // Pages HTML : network-first, fallback cache
  if (request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(
      fetch(request).catch(() => caches.match(request))
    );
    return;
  }
});
