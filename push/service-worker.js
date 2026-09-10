/*
 * push/service-worker.js
 * =======================
 * STATUS: Grundgeruest, nicht aktiv.
 *
 * PWA-/Web-Push-Grundstruktur fuer Techniker-Benachrichtigungen (siehe
 * Modul 3, "Operativer Workflow"). Rein client-seitig -- es gibt aktuell
 * KEINEN echten Push-Server/Cloud-Function, der diese Datei anspricht.
 *
 * Benoetigt fuer Scharfschaltung:
 *   1) Backend-Entscheidung (interner Server vs. Cloud-Dienst -- offene
 *      Frage, siehe manual.html, Kapitel 1.10)
 *   2) VAPID-Schluessel
 *   3) IT-Freigabe
 *
 * Bis dahin: Registrierung/Installation dieser Datei ist im Dashboard NICHT
 * verdrahtet (kein navigator.serviceWorker.register()-Aufruf im Code).
 */

self.addEventListener('install', function (event) {
  // Kein Precaching -- Grundgeruest, noch keine Offline-Strategie definiert.
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(self.clients.claim());
});

// Web Push API: eingehende Push-Nachricht eines (noch nicht existierenden)
// Push-Servers in eine Browser-Benachrichtigung uebersetzen.
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
    icon: payload.icon || '/favicon.ico',
    data: payload.data || {},
  };

  event.waitUntil(self.registration.showNotification(titel, optionen));
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  var ziel = (event.notification.data && event.notification.data.url) || '/dashboard.html';
  event.waitUntil(self.clients.openWindow(ziel));
});
