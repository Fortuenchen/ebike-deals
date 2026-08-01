// "Alle Deals"-Fenster: zeigt jedes Angebot aus preisalarm.json (Neuware ab der
// Feed-Untergrenze), mit Suche, Typ-/Rabattfilter und Sortierung.
const FEED_URL = "https://fortuenchen.github.io/ebike-deals/preisalarm.json";
let ALL = [];
let FLOOR = 60;
const $ = (id) => document.getElementById(id);

async function load() {
  $("meta").textContent = "Lade …";
  let data;
  try {
    const res = await fetch(FEED_URL, { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    data = await res.json();
  } catch (e) {
    $("meta").textContent = "Fehler beim Laden des Feeds: " + e;
    return;
  }
  ALL = Array.isArray(data.offers) ? data.offers : [];
  FLOOR = data.min_discount || 60;
  if (!$("minpct").value) $("minpct").value = Math.round(FLOOR);
  $("meta").textContent =
    `${ALL.length} Neuware-Angebote ab ${Math.round(FLOOR)} % · Stand ${fmtTime(data.generated)}`;
  render();
}

function render() {
  const terms = $("q").value.toLowerCase().split(/\s+/).filter(Boolean);
  const minpct = parseFloat($("minpct").value) || 0;
  const type = $("type").value;
  const sort = $("sort").value;

  let list = ALL.filter(
    (o) =>
      Number(o.discount) >= minpct &&
      (type === "alle" || (o.bike_type || "ebike") === type) &&
      (!terms.length ||
        terms.every((t) =>
          (o.title + " " + o.shop + " " + (o.brand || "")).toLowerCase().includes(t)
        ))
  );
  const cmp = {
    discount: (a, b) => b.discount - a.discount,
    "price-asc": (a, b) => a.price - b.price,
    "price-desc": (a, b) => b.price - a.price,
  }[sort];
  list.sort(cmp);

  const grid = $("grid");
  grid.innerHTML = "";
  if (!list.length) {
    grid.innerHTML = '<p class="empty">Keine Angebote für diese Filter.</p>';
    return;
  }
  const frag = document.createDocumentFragment();
  for (const o of list) frag.appendChild(card(o));
  grid.appendChild(frag);
}

function card(o) {
  const el = document.createElement("div");
  el.className = "card";
  const was = o.list_price ? `<span class="was">${eur(o.list_price)}</span>` : "";
  const seen = o.first_seen ? `<span class="seen">gelistet seit ${fmtDate(o.first_seen)}</span>` : "";
  const img = o.image
    ? `<img src="${esc(o.image)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
    : "";
  const isFahrrad = (o.bike_type || "ebike") === "fahrrad";
  el.innerHTML =
    `<a href="${esc(o.url)}" target="_blank" rel="noopener">` +
    `<div class="thumb">${img}<span class="badge">−${Math.round(o.discount)} %</span>` +
    `<span class="type">${isFahrrad ? "Fahrrad" : "E-Bike"}</span></div>` +
    `<div class="body">` +
    `<span class="shop">${esc(o.shop)}${o.brand ? " · " + esc(o.brand) : ""}</span>` +
    `<span class="ti">${esc(o.title)}</span>` +
    `<div class="prices"><span class="now">${eur(o.price)}</span>${was}</div>` +
    `${seen}</div></a>`;
  return el;
}

$("q").addEventListener("input", render);
$("minpct").addEventListener("input", render);
$("type").addEventListener("change", render);
$("sort").addEventListener("change", render);
$("refresh").addEventListener("click", load);

function eur(n) {
  return Math.round(Number(n)).toLocaleString("de-DE") + " €";
}
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function fmtTime(iso) {
  try {
    return new Date(iso).toLocaleString("de-DE",
      { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  } catch (_e) {
    return iso || "?";
  }
}
function fmtDate(iso) {
  if (!iso || iso.length < 10) return iso || "";
  return iso.slice(8, 10) + "." + iso.slice(5, 7) + ".";
}

load();
