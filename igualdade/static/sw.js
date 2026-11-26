// Service worker mínimo: guarda só os arquivos visuais (CSS, JS, brasão).
// As páginas com dados sempre vêm do servidor, para nunca mostrar informação desatualizada.
const CACHE = "igualdade-v43";
const ARQUIVOS = ["/static/style.css?v=40", "/static/app.js?v=20", "/static/icon-192.png", "/static/icon-512.png", "/static/brasao.png", "/static/brasao-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ARQUIVOS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((nomes) => Promise.all(nomes.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || !url.pathname.startsWith("/static/")) return;
  e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
});
