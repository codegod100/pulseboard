'use strict';

// This worker intentionally does not cache authenticated API responses or
// application data. It gives Pulseboard a durable PWA registration without
// persisting a user's reader data in the browser cache.
self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});
