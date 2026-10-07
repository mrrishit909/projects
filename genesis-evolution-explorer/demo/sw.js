// Offline cache for the museum kiosk: the app shell and data are cached as they are fetched (network first, cache as fallback),
// so a kiosk keeps running through a network outage. Bump VERSION to drop old caches.
const VERSION = "genesis-v1";
self.addEventListener("install", (e) => { self.skipWaiting(); e.waitUntil(caches.open(VERSION).then((c) => c.addAll([self.registration.scope, self.registration.scope + "data/genesis.json", self.registration.scope + "data/fossils.json"]).catch(() => {}))); });
self.addEventListener("activate", (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== VERSION).map((k) => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;
  e.respondWith(fetch(req).then((res) => { if (res.ok) { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(req, copy)); } return res; })
    .catch(() => caches.match(req, { ignoreSearch: true }).then((hit) => hit || caches.match(self.registration.scope))));
});
