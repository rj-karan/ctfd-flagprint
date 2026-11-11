// Admin-only: polls for shared-flag submissions and shows a toast on every admin page.
(() => {
  const KEY = "flagprint.lastSeen";
  const feed = `${window.CTFd?.config?.urlRoot ?? ""}/admin/flagprint/alerts.json`;
  const monitor = `${window.CTFd?.config?.urlRoot ?? ""}/admin/flagprint`;

  function stored() {
    try {
      const value = localStorage.getItem(KEY);
      return value === null ? null : Number(value);
    } catch {
      return null;
    }
  }

  function remember(id) {
    try {
      localStorage.setItem(KEY, String(id));
    } catch {}
  }

  function stack() {
    let box = document.getElementById("flagprint-toasts");
    if (!box) {
      box = document.createElement("div");
      box.id = "flagprint-toasts";
      box.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2000;display:flex;flex-direction:column;gap:8px;max-width:360px";
      document.body.appendChild(box);
    }
    return box;
  }

  function toast(event) {
    const card = document.createElement("a");
    card.href = monitor;
    card.style.cssText = "display:block;padding:12px 14px;background:#d6261b;color:#fff;border:2px solid #111;box-shadow:4px 4px 0 #111;font:14px/1.4 system-ui,sans-serif;text-decoration:none";
    const title = document.createElement("strong");
    title.textContent = "Flag sharing caught";
    const body = document.createElement("div");
    body.textContent = `${event.submitter} submitted ${event.owner}'s flag on ${event.challenge}`;
    card.append(title, body);
    stack().appendChild(card);
    setTimeout(() => card.remove(), 20000);
  }

  async function poll() {
    const after = stored();
    try {
      const response = await fetch(after === null ? feed : `${feed}?after=${after}`, { credentials: "same-origin" });
      if (!response.ok) return;
      const data = await response.json();
      data.events.forEach(toast);
      remember(data.events.length ? data.events[data.events.length - 1].id : Math.max(after ?? 0, data.latest));
    } catch {}
  }

  poll();
  setInterval(poll, 15000);
})();
