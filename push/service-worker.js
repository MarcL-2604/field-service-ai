/*
 * push/service-worker.js
 * =======================
 * STATUS: Grundgeruest, nicht aktiv.
 *
 * PWA-/Web-Push-Grundstruktur fuer Techniker-Benachrichtigungen (siehe
 * Modul 3, "Operativer Workflow"). Rein client-seitig -- es gibt aktuell
 * KEINEN echten Push-Server/Cloud-Function, der diese Datei anspricht.
 *
 * Benoetigt fuer Scharfschaltung (echter Server-Push, alle Techniker):
 *   1) Backend-Entscheidung (interner Server vs. Cloud-Dienst -- offene
 *      Frage, siehe manual.html, Kapitel 1.10)
 *   2) VAPID-Schluessel
 *   3) IT-Freigabe
 *
 * AUSNAHME -- lokale Demo (techniker_app.html): diese eine Seite registriert
 * diesen Service Worker aktiv, ausschliesslich fuer (a) Offline-Caching des
 * App-Shells und (b) rein lokal ausgeloeste Benachrichtigungen ueber
 * registration.showNotification() -- ohne jede Server-/Netzwerkverbindung,
 * ohne echte Techniker-Daten. Alle anderen Seiten registrieren diese Datei
 * NICHT (kein navigator.serviceWorker.register()-Aufruf dort im Code).
 */

var CACHE_NAME = 'fsa-techniker-app-v1';
var APP_SHELL = [
  '../techniker_app.html',
  './manifest.json',
  './icon.svg',
];

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(function (cache) { return cache.addAll(APP_SHELL); })
      .catch(function () { /* Precaching ist best-effort -- kein harter Fehler beim Install */ })
  );
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (namen) {
      return Promise.all(
        namen.filter(function (n) { return n !== CACHE_NAME; }).map(function (n) { return caches.delete(n); })
      );
    }).then(function () { return self.clients.claim(); })
  );
});

// Offline-Strategie: same-origin GET-Requests cache-first mit Netzwerk-
// Fallback (und Nachtrag in den Cache) -- damit techniker_app.html nach der
// Installation auch offline oeffnet.
self.addEventListener('fetch', function (event) {
  if (event.request.method !== 'GET' || new URL(event.request.url).origin !== self.location.origin) return;

  event.respondWith(
    caches.match(event.request).then(function (cached) {
      if (cached) return cached;
      return fetch(event.request).then(function (response) {
        if (response && response.ok) {
          var kopie = response.clone();
          caches.open(CACHE_NAME).then(function (cache) { cache.put(event.request, kopie); });
        }
        return response;
      }).catch(function () { return cached; });
    })
  );
});

// Web Push API: eingehende Push-Nachricht eines (noch nicht existierenden)
// Push-Servers in eine Browser-Benachrichtigung uebersetzen. Fuer die lokale
// Demo IRRELEVANT (dort wird showNotification() direkt aus der Seite
// aufgerufen) -- bleibt als Grundgeruest fuer einen spaeteren echten Server.
self.addEventListener('push', function (event) {
  if (!event.data) return;

  var payload;
  try {
    payload = event.data.json();
  } catch (e) {
    payload = { title: 'Field Service AI', body: event.data.text() };
  }

  var titel = payload.title || 'Field Service AI';
  var optionen = {
    body: payload.body || '',
    icon: payload.icon || 'icon.svg',
    data: payload.data || {},
  };

  event.waitUntil(self.registration.showNotification(titel, optionen));
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  var ziel = (event.notification.data && event.notification.data.url) || '../techniker_app.html';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (clientList) {
      for (var i = 0; i < clientList.length; i++) {
        var client = clientList[i];
        if ('focus' in client) {
          // Seite ist schon offen -- per postMessage zur Auftragsdetail-Ansicht
          // navigieren lassen, statt die Seite neu zu laden.
          client.postMessage({ type: 'fsa-open-auftrag', url: ziel });
          return client.focus();
        }
      }
      return self.clients.openWindow(ziel);
    })
  );
});
