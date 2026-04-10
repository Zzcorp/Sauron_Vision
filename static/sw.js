const CACHE_NAME = 'sauron-v1';
const STATIC_ASSETS = ['/static/logo/sauron_192.png'];

self.addEventListener('install', e => {
    e.waitUntil(
        caches.open(CACHE_NAME).then(c => c.addAll(STATIC_ASSETS)).catch(() => {})
    );
    self.skipWaiting();
});

self.addEventListener('activate', e => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener('fetch', e => {
    if (e.request.method !== 'GET') return;
    // Only cache static assets; let all other requests fall through
    if (e.request.url.includes('/static/')) {
        e.respondWith(
            caches.match(e.request).then(cached => {
                if (cached) return cached;
                return fetch(e.request).then(resp => {
                    if (resp && resp.status === 200) {
                        var clone = resp.clone();
                        caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
                    }
                    return resp;
                }).catch(() => caches.match(e.request));
            })
        );
    }
    // For non-static: network first, fall back to cache if offline
    else {
        e.respondWith(
            fetch(e.request).catch(() => caches.match(e.request))
        );
    }
});
