// EbikeDeals Preisalarm - Service Worker (MV3).
//
// Pollt den schlanken Fed preisalarm.json (nur Neuware, von der Pipeline nach
// jedem Lauf veröffentlicht) und meldet NEUE Angebote über der Schwelle als
// Desktop-Benachrichtigung. "Neu" = URL, die der Alarm noch nicht gesehen hat;
// beim allerersten Lauf wird nur eine Baseline gesetzt (kein Spam).

// Eine Referenz für beide Browser: browser (Firefox, Promise-basiert) bzw.
// chrome (Chrome/Edge). So läuft dieselbe Datei in beiden Builds.
const api = globalThis.browser || globalThis.chrome;

const FEED_URL = "https://fortuenchen.github.io/ebike-deals/preisalarm.json";
const SITE_URL = "https://fortuenchen.github.io/ebike-deals/";
const DEFAULTS = { enabled: true, threshold: 66, intervalMin: 120 };
const SEEN_CAP = 4000; // gegen unbegrenztes Wachsen der gesehen-Liste
const ALARM = "ebd-check";

api.runtime.onInstalled.addListener(async () => {
  const st = await api.storage.local.get(["settings", "seen"]);
  if (!st.settings) await api.storage.local.set({ settings: DEFAULTS });
  if (!st.seen) await api.storage.local.set({ seen: [], seeded: false });
  await scheduleAlarm();
  await runCheck();
});

api.runtime.onStartup.addListener(scheduleAlarm);

api.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM) runCheck();
});

// Nachrichten aus dem Popup: sofort prüfen / Intervall neu setzen.
api.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "checkNow") {
    runCheck().then(() => sendResponse({ ok: true }));
    return true;
  }
  if (msg && msg.type === "reschedule") {
    scheduleAlarm().then(() => sendResponse({ ok: true }));
    return true;
  }
});

api.notifications.onClicked.addListener((id) => {
  const url = id === "ebd-report" ? SITE_URL : id;
  api.tabs.create({ url });
  api.notifications.clear(id);
});

async function scheduleAlarm() {
  const { settings } = await api.storage.local.get("settings");
  const period = Math.max(15, (settings || DEFAULTS).intervalMin);
  await api.alarms.clear(ALARM);
  api.alarms.create(ALARM, { periodInMinutes: period, delayInMinutes: 1 });
}

async function runCheck() {
  const store = await api.storage.local.get(["settings", "seen", "seeded"]);
  const cfg = store.settings || DEFAULTS;
  if (!cfg.enabled) {
    await updateBadge(0);
    return;
  }

  let data;
  try {
    const res = await fetch(FEED_URL, { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    data = await res.json();
  } catch (e) {
    await api.storage.local.set({ lastError: String(e), lastCheck: Date.now() });
    return;
  }

  const offers = Array.isArray(data.offers) ? data.offers : [];
  // Der Feed enthält bereits nur Neuware; hier nur noch die eigene Schwelle.
  const qualifying = offers.filter((o) => Number(o.discount) > cfg.threshold);
  const seen = new Set(store.seen || []);
  const fresh = qualifying.filter((o) => !seen.has(o.url));

  qualifying.forEach((o) => seen.add(o.url));
  const seenArr = [...seen].slice(-SEEN_CAP);

  await api.storage.local.set({
    seen: seenArr,
    generated: data.generated,
    current: qualifying,
    lastCheck: Date.now(),
    lastError: null,
  });

  await updateBadge(qualifying.length);

  // Erster Lauf nach Installation: nur Baseline, nichts melden.
  if (!store.seeded) {
    await api.storage.local.set({ seeded: true });
    return;
  }
  if (fresh.length) notifyFresh(fresh, cfg.threshold);
}

function notifyFresh(fresh, threshold) {
  if (fresh.length === 1) {
    const o = fresh[0];
    const was = o.list_price ? " statt " + eur(o.list_price) : "";
    createNotification(o.url, `−${Math.round(o.discount)} % · ${o.title}`,
      `${eur(o.price)}${was} · ${o.shop}`);
  } else {
    const lines = fresh
      .slice(0, 4)
      .map((o) => `−${Math.round(o.discount)} %  ${o.title}`)
      .join("\n");
    createNotification("ebd-report",
      `${fresh.length} neue Angebote über ${threshold} %`, lines);
  }
}

function createNotification(id, title, message) {
  api.notifications.create(id, {
    type: "basic",
    iconUrl: "icons/icon128.png",
    title,
    message,
    priority: 2,
  });
}

async function updateBadge(n) {
  try {
    await api.action.setBadgeText({ text: n ? String(n) : "" });
    await api.action.setBadgeBackgroundColor({ color: "#c0392b" });
  } catch (_e) {
    /* setBadge kann in manchen Kontexten fehlen - unkritisch */
  }
}

function eur(n) {
  return Math.round(Number(n)).toLocaleString("de-DE") + " €";
}
