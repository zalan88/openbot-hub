// OpenBot Hub service worker: installable app shell + notifications.
// Push messages carry no content: on a push, the worker fetches the alerts from the hub over the private
// network. Data (/api/) always comes from the network; nothing private is cached.
const SHELL = "hub-shell-v2";
const FILES = ["/", "/style.css", "/app.js", "/icons/icon-192.png"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(SHELL).then((c) => c.addAll(FILES))); self.skipWaiting(); });
self.addEventListener("activate", (e) => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (k !== SHELL) await caches.delete(k);
  await self.clients.claim();
})()));
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  e.respondWith(fetch(e.request).then((r) => {
    const copy = r.clone();
    if (r.ok) caches.open(SHELL).then((c) => c.put(e.request, copy));
    return r;
  }).catch(() => caches.match(e.request).then((r) => r || caches.match("/"))));
});

self.addEventListener("push", (e) => e.waitUntil((async () => {
  let items = [];
  try {
    const r = await fetch("/api/push/latest", { cache: "no-store" });
    if (r.ok) items = (await r.json()).items || [];
  } catch (err) {}
  const live = new Set(items.map((i) => i.tag || i.id));
  for (const n of await self.registration.getNotifications()) if (n.tag && !live.has(n.tag) && n.tag !== "hub-offline") n.close();
  if (!items.length) {
    return self.registration.showNotification("Hub", { body: "Você tem avisos. Ligue a Tailscale para ver.", tag: "hub-offline", icon: "/icons/icon-192.png" });
  }
  const shown = new Map((await self.registration.getNotifications()).map((n) => [n.tag, n.data && n.data.id]));
  const newest = items[items.length - 1];
  for (const i of items) {
    const tag = i.tag || i.id;
    if (shown.get(tag) === i.id && i !== newest) continue;
    await self.registration.showNotification(i.title, {
      body: i.body || "", tag, renotify: i === newest, silent: i !== newest, requireInteraction: !!i.urgent,
      icon: "/icons/icon-192.png", badge: "/icons/icon-192.png",
      actions: (i.actions || []).slice(0, 2).map((a) => ({ action: a.action, title: a.title })),
      data: { id: i.id, url: i.url || "/", actions: i.actions || [] },
    });
  }
})()));

self.addEventListener("notificationclick", (e) => {
  const d = e.notification.data || {};
  const act = (d.actions || []).find((a) => a.action === e.action);
  e.notification.close();
  e.waitUntil((async () => {
    if (act && act.post) {
      let ok = false;
      try {
        const r = await fetch("/api/" + act.post.path, { method: "POST", headers: { "Content-Type": "application/json", "X-Hub": "1" }, body: JSON.stringify(act.post.body || {}) });
        ok = r.ok;
      } catch (err) {}
      return self.registration.showNotification(ok ? "Feito: " + act.title : "Não deu: abra o Hub", { tag: "hub-result", icon: "/icons/icon-192.png", silent: true });
    }
    const url = new URL(d.url || "/", self.location.origin).href;
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const w of wins) if (w.url.startsWith(self.location.origin)) { await w.focus(); return w.navigate(url); }
    return self.clients.openWindow(url);
  })());
});
