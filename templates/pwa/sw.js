{% load static %}{% autoescape off %}/* Service worker de Esplitiguais. Generado por pwa.views.service_worker. */
const VERSION = "__SW_VERSION__";
const CACHE_PREFIX = "esplitiguais-";
const STATIC_CACHE = CACHE_PREFIX + "static-" + VERSION;
const PAGES_CACHE = CACHE_PREFIX + "pages-" + VERSION;
const STATIC_PREFIX = "{% get_static_prefix %}";
const OFFLINE_URL = "{% url 'pwa:offline' %}";
const PRECACHE_STATIC = [
  "{% static 'css/app.css' %}",
  "{% static 'js/pwa.js' %}",
  "{% static 'js/alias.js' %}",
  "{% static 'fonts/sora-latin-var.woff2' %}",
  "{% static 'icons/icon-192.png' %}",
  "{% static 'icons/icon-512.png' %}",
  "{% static 'icons/icon-maskable-512.png' %}",
  "{% static 'icons/apple-touch-icon.png' %}",
  "{% static 'icons/favicon-32.png' %}",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const staticCache = await caches.open(STATIC_CACHE);
      await staticCache.addAll(PRECACHE_STATIC.map((url) => new Request(url, { cache: "reload" })));
      // La única página que se guarda: la de "Sin conexión" (pública, sin datos de sesión).
      const pagesCache = await caches.open(PAGES_CACHE);
      await pagesCache.add(new Request(OFFLINE_URL, { cache: "reload", credentials: "omit" }));
      await self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keep = new Set([STATIC_CACHE, PAGES_CACHE]);
      const names = await caches.keys();
      await Promise.all(
        names.filter((name) => name.startsWith(CACHE_PREFIX) && !keep.has(name)).map((name) => caches.delete(name))
      );
      await self.clients.claim();
    })()
  );
});

// Nombres con hash de ManifestStaticFilesStorage (app.3f2a1b9c8d7e.css): su contenido
// nunca cambia, así que pueden servirse desde la caché sin consultar la red.
const HASHED_STATIC = /\.[0-9a-f]{12}\.[a-z0-9]+$/i;

async function putStatic(request, response) {
  if (response.ok && response.type === "basic") {
    const cache = await caches.open(STATIC_CACHE);
    await cache.put(request, response.clone());
  }
}

async function cacheFirst(request) {
  const cached = await caches.match(request, { cacheName: STATIC_CACHE });
  if (cached) return cached;
  const response = await fetch(request);
  await putStatic(request, response);
  return response;
}

// Estáticos sin hash (desarrollo, o archivos fuera del manifest): pueden cambiar
// sin cambiar de nombre, así que la caché solo se usa sin conexión.
async function networkFirstStatic(request) {
  try {
    const response = await fetch(request);
    await putStatic(request, response);
    return response;
  } catch (error) {
    const cached = await caches.match(request, { cacheName: STATIC_CACHE });
    if (cached) return cached;
    throw error;
  }
}

async function networkFirst(request) {
  try {
    // Las páginas nunca se guardan: pueden tener datos del usuario.
    return await fetch(request);
  } catch (error) {
    const offline = await caches.match(OFFLINE_URL, { cacheName: PAGES_CACHE });
    return offline || Response.error();
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith(STATIC_PREFIX)) {
    event.respondWith(HASHED_STATIC.test(url.pathname) ? cacheFirst(request) : networkFirstStatic(request));
  } else if (request.mode === "navigate") {
    event.respondWith(networkFirst(request));
  }
});
{% endautoescape %}