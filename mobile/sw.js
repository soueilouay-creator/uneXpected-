const CACHE = 'unexpected-phone-shell-v1';
const SHELL = ['/mobile/', '/mobile/manifest.webmanifest', '/mobile/icon.svg', '/mobile/agents.json', '/mobile/skills.json'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET') return;
  if (url.origin !== self.location.origin) return;
  if (['/health', '/orchestrate', '/test-provider'].includes(url.pathname)) return;
  if (!url.pathname.startsWith('/mobile/')) return;
  event.respondWith(fetch(req).then(response => {
    if (response.ok && SHELL.includes(url.pathname)) {
      const copy = response.clone();
      caches.open(CACHE).then(cache => cache.put(req, copy));
    }
    return response;
  }).catch(() => caches.match(req).then(cached => cached || caches.match('/mobile/'))));
});
