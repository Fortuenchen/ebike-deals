// Popup: Einstellungen + Live-Liste der aktuell qualifizierenden Neuware-Angebote.
const SITE_URL = "https://fortuenchen.github.io/ebike-deals/";
const DEFAULTS = { enabled: true, threshold: 66, intervalMin: 120 };
const $ = (id) => document.getElementById(id);

async function load() {
  const st = await chrome.storage.local.get([
    "settings", "current", "lastCheck", "lastError",
  ]);
  const cfg = st.settings || DEFAULTS;
  $("enabled").checked = cfg.enabled;
  $("threshold").value = cfg.threshold;
  $("interval").value = cfg.intervalMin;
  $("siteLink").href = SITE_URL;
  renderStatus(st);
  renderOffers(st.current || [], cfg.threshold);
}

function renderStatus(st) {
  if (st.lastError) {
    $("status").textContent = "Fehler beim Abruf: " + st.lastError;
    return;
  }
  const t = st.lastCheck
    ? new Date(st.lastCheck).toLocaleString("de-DE",
        { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })
    : "noch nie";
  const n = (st.current || []).length;
  $("status").textContent = `${n} Angebot(e) über der Schwelle · zuletzt geprüft ${t}`;
}

function renderOffers(current, threshold) {
  const ul = $("offers");
  ul.innerHTML = "";
  const list = current
    .filter((o) => Number(o.discount) > threshold)
    .sort((a, b) => b.discount - a.discount);
  if (!list.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent =
      "Aktuell keine Neuware über der Schwelle. Der Alarm meldet sich, sobald ein neues Angebot auftaucht.";
    ul.appendChild(li);
    return;
  }
  for (const o of list) {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = o.url;
    a.target = "_blank";
    a.rel = "noopener";
    const was = o.list_price ? ` statt ${eur(o.list_price)}` : "";
    a.innerHTML =
      `<span class="pct">−${Math.round(o.discount)} %</span>` +
      `<span><span class="ti">${esc(o.title)}</span><br>` +
      `<span class="sub">${eur(o.price)}${was} · ${esc(o.shop)}</span></span>`;
    li.appendChild(a);
    ul.appendChild(li);
  }
}

async function saveSettings() {
  const settings = {
    enabled: $("enabled").checked,
    threshold: clamp(parseInt($("threshold").value, 10) || 66, 30, 95),
    intervalMin: clamp(parseInt($("interval").value, 10) || 120, 15, 1440),
  };
  await chrome.storage.local.set({ settings });
  try { await chrome.runtime.sendMessage({ type: "reschedule" }); } catch (_e) {}
  const st = await chrome.storage.local.get(["current", "lastCheck", "lastError"]);
  renderStatus(st);
  renderOffers(st.current || [], settings.threshold);
}

$("enabled").addEventListener("change", saveSettings);
$("threshold").addEventListener("change", saveSettings);
$("interval").addEventListener("change", saveSettings);
$("allDeals").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.tabs.create({ url: chrome.runtime.getURL("deals.html") });
});
$("checkNow").addEventListener("click", async () => {
  $("status").textContent = "Prüfe …";
  try { await chrome.runtime.sendMessage({ type: "checkNow" }); } catch (_e) {}
  await load();
});

function eur(n) {
  return Math.round(Number(n)).toLocaleString("de-DE") + " €";
}
function clamp(n, a, b) {
  return Math.min(b, Math.max(a, n));
}
function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

load();
