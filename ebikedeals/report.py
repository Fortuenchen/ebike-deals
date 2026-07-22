"""Output: console summary, JSON dump and a self-contained HTML report."""

from __future__ import annotations

import html as html_mod
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from .fit import estimate_body_height
from .model import Offer
from .runner import RunReport


def _eur(v: float | None) -> str:
    if v is None:
        return "–"
    return f"{v:,.2f} €".replace(",", " ").replace(".", ",").replace(" ", ".")


# ---------------------------------------------------------------------------
def print_console(report: RunReport) -> None:
    cfg = report.config
    offers = report.offers
    print()
    print(f"  E-Bike-Deals ab {cfg.min_discount:.0f} % Rabatt")
    print(f"  {len(offers)} Treffer aus {report.total_scanned} geprüften Angeboten")
    print("  " + "─" * 76)

    for r in report.results:
        if r.skipped_reason:
            status = f"übersprungen – {r.skipped_reason[:58]}"
        elif r.error:
            status = f"FEHLER – {r.error[:58]}"
        else:
            status = f"{len(r.offers):>3} Treffer von {r.scanned:>4} geprüft"
            if r.sold_out:
                status += f"  ({r.sold_out} ausverkauft übersprungen)"
        print(f"  {r.name:<26} {status}")

    if not offers:
        print("\n  Keine Angebote über der Rabattschwelle gefunden.\n")
        return

    print()
    print("  " + "─" * 76)
    for o in offers:
        d = o.effective_discount_pct or 0
        sizes = ", ".join(o.sizes) if o.sizes else "keine Größenangabe"
        print(f"\n  −{d:.1f}%  {_eur(o.price)}  (statt {_eur(o.list_price)})   [{o.shop}]")
        print(f"     {o.title[:88]}")
        print(f"     Größen: {sizes}")
        print(f"     {o.url}")
        if o.note:
            print(f"     Hinweis: {o.note}")
    print()


# ---------------------------------------------------------------------------
def write_json(report: RunReport, path: Path) -> None:
    payload = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "min_discount_pct": report.config.min_discount,
        "total_scanned": report.total_scanned,
        "shops": [
            {
                "key": r.key,
                "name": r.name,
                "source_url": r.source_url,
                "scanned": r.scanned,
                "hits": len(r.offers),
                "sold_out_skipped": r.sold_out,
                "error": r.error,
                "skipped_reason": r.skipped_reason,
            }
            for r in report.results
        ],
        "offers": [o.to_dict() for o in report.offers],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
def write_html(report: RunReport, path: Path) -> None:
    path.write_text(_render_html(report), encoding="utf-8")


def _esc(s: str) -> str:
    return html_mod.escape(s or "")


def _rating_badges(entries, compact: bool = False) -> str:
    """Rating chips. A chip without a score is a link to the profile, no more."""
    out = []
    for e in entries or []:
        short = "TS" if e.platform.startswith("Trusted") else "TP"
        if e.score is None:
            label = short if compact else f"{_esc(e.platform)} ansehen"
            cls = "rating rating--link"
            title = f"{e.platform}: Profil ansehen (keine Note abrufbar)"
        else:
            label = f"{short}&nbsp;{e.stars}" if compact else (
                f"{_esc(e.platform)} {e.stars}/5"
                + (f" · {e.count:,}".replace(",", ".") + " Bew." if e.count else "")
            )
            cls = "rating"
            title = (
                f"{e.platform}: {e.stars} von {e.scale:.0f}"
                + (f", {e.count} Bewertungen" if e.count else "")
                + (" (manuell eingetragen)" if e.manual else "")
            )
        out.append(
            f'<a class="{cls}" href="{_esc(e.url)}" target="_blank" rel="noopener nofollow" '
            f'title="{_esc(title)}">{label}</a>'
        )
    return "".join(out)


def _offer_card(o: Offer, ratings=None) -> str:
    d = o.effective_discount_pct or 0
    if o.size_links:
        sizes = " ".join(
            f'<a class="size" href="{_esc(link)}" target="_blank" rel="noopener">{_esc(s)}</a>'
            for s, link in o.size_links.items()
        )
    elif o.sizes:
        sizes = " ".join(f'<span class="size">{_esc(s)}</span>' for s in o.sizes)
    else:
        sizes = '<span class="size size--none">keine Größenangabe gefunden</span>'

    img = (
        f'<img loading="lazy" src="{_esc(o.image)}" alt="">'
        if o.image
        else '<div class="noimg"></div>'
    )
    saving = f"<span class='saving'>− {_esc(_eur(o.saving))}</span>" if o.saving else ""
    note = f'<p class="note">{_esc(o.note)}</p>' if o.note else ""
    avail = f'<span class="avail">{_esc(o.availability)}</span>' if o.availability else ""

    cond = (
        f'<span class="cond">{_esc(o.condition)}</span>'
        if o.condition
        else '<span class="cond cond--new">Neuware</span>'
    )
    if o.battery_wh:
        battery = f'<span class="spec">{o.battery_wh}&nbsp;Wh</span>'
    elif o.battery_min_wh:
        # Lower bound only - the "≥" is the whole point, see Offer.battery_min_wh.
        battery = f'<span class="spec">≥&nbsp;{o.battery_min_wh}&nbsp;Wh</span>'
    else:
        battery = ""

    # Rider heights this bike plausibly fits, derived from its frame sizes when
    # the shop does not state a range itself.
    est_lo, est_hi = (None, None)
    if not o.body_height_min:
        est_lo, est_hi = estimate_body_height(o.sizes, o.title)
    # Everything the search box should match, lower-cased once at build time so
    # filtering stays a substring test even with hundreds of cards.
    haystack = " ".join(
        [o.title, o.brand, o.shop, o.condition, o.note, o.availability]
        + o.sizes
        + ([f"{o.battery_wh}wh"] if o.battery_wh else [])
    ).lower()

    return f"""
    <article class="card" data-shop="{_esc(o.shop)}" data-discount="{d}" data-price="{o.price}"
             data-condition="{'used' if o.condition else 'new'}"
             data-battery="{o.battery_wh or 0}"
             data-bhmin="{o.body_height_min or 0}" data-bhmax="{o.body_height_max or 0}"
             data-bhest-min="{est_lo or 0}" data-bhest-max="{est_hi or 0}"
             data-batmin="{o.battery_min_wh or 0}"
             data-saving="{o.saving or 0}"
             data-drop="{o.price_change if o.price_change is not None else 0}"
             data-sizes="{_esc('|'.join(_size_keys(o)))}"
             data-search="{_esc(haystack)}">
      <div class="thumb">{img}<span class="badge">−{d:.0f}&nbsp;%</span>{cond}</div>
      <div class="body">
        <p class="shop">{_esc(o.shop)} {avail}{_rating_badges(ratings, compact=True)}</p>
        <h3><a href="{_esc(o.url)}" target="_blank" rel="noopener">{_esc(o.title)}</a></h3>
        <p class="prices">
          <span class="now">{_esc(_eur(o.price))}</span>
          <span class="was">{_esc(_eur(o.list_price))}</span>
          {saving}
          {battery}
        </p>
        {_history_block(o)}
        <p class="sizes"><span class="lbl">Größen/Rahmenhöhen:</span> {sizes}</p>
        {note}
        <a class="cta" href="{_esc(o.url)}" target="_blank" rel="noopener">Zum Angebot →</a>
      </div>
    </article>"""


# Frame sizes come in three incompatible systems, so the filter groups them
# instead of offering 60 individual chips.
_LETTER_SIZES = ["XXS", "XS", "S", "M", "L", "XL", "XXL"]


def _size_keys(o: Offer) -> list[str]:
    """Filter keys for one offer: letter sizes plus a 5 cm bucket per cm size."""
    keys: list[str] = []
    for raw in o.sizes:
        s = raw.strip().upper()
        if s in _LETTER_SIZES:
            keys.append(s)
            continue
        m = re.match(r"^(\d{2})(?:[.,]\d)?\s*CM", s)
        if m:
            cm = int(m.group(1))
            low = cm - (cm % 5)
            keys.append(f"{low}-{low + 4}cm")
            continue
        m = re.match(r"^(\d{2})\s*\"?$", s)
        if m and 30 <= int(m.group(1)) <= 70:  # bare number = cm on these shops
            cm = int(m.group(1))
            low = cm - (cm % 5)
            keys.append(f"{low}-{low + 4}cm")
    return sorted(set(keys))


def _history_block(o: Offer) -> str:
    """Price-history line: new / change since last run / all-time low + sparkline."""
    if o.is_new:
        return '<p class="hist"><span class="tag tag--new">neu im Bericht</span></p>'

    bits = []
    change = o.price_change
    if change is not None and abs(change) >= 1:
        cls = "down" if change < 0 else "up"
        arrow = "▼" if change < 0 else "▲"
        bits.append(
            f'<span class="tag tag--{cls}">{arrow} {_esc(_eur(abs(change)))} '
            f'seit {_esc(o.price_prev and _eur(o.price_prev) or "")}</span>'
        )
    elif change is not None:
        bits.append('<span class="tag">Preis unverändert</span>')
    if o.is_all_time_low:
        bits.append('<span class="tag tag--low">Tiefstpreis</span>')

    spark = _sparkline(o.price_points)
    return f'<p class="hist">{"".join(bits)}{spark}</p>' if bits or spark else ""


def _sparkline(points: list, width: int = 96, height: int = 22) -> str:
    """Tiny inline SVG price curve - no library, no external request."""
    values = [p[1] for p in points if isinstance(p, (list, tuple)) and len(p) == 2]
    if len(values) < 3:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    step = width / (len(values) - 1)
    coords = " ".join(
        f"{i * step:.1f},{height - 2 - (v - lo) / span * (height - 4):.1f}"
        for i, v in enumerate(values)
    )
    last_x = width
    last_y = height - 2 - (values[-1] - lo) / span * (height - 4)
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" '
        f'height="{height}" aria-hidden="true">'
        f'<polyline points="{coords}" fill="none" stroke="currentColor" '
        f'stroke-width="1.5" stroke-linejoin="round"/>'
        f'<circle cx="{last_x - 1:.1f}" cy="{last_y:.1f}" r="2" fill="currentColor"/>'
        f"</svg>"
    )


def _render_html(report: RunReport) -> str:
    cfg = report.config
    offers = report.offers
    generated = datetime.now().strftime("%d.%m.%Y, %H:%M")

    shop_rows = []
    for r in report.results:
        if r.skipped_reason:
            cls, status = "warn", _esc(r.skipped_reason)
        elif r.error:
            cls, status = "err", _esc(r.error)
        else:
            cls, status = "ok", f"{r.scanned} Angebote geprüft"
            if r.sold_out:
                status += f" · {r.sold_out} ausverkauft übersprungen"
        badges = _rating_badges(report.ratings.get(r.key)) or (
            '<span class="muted">–</span>'
        )
        shop_rows.append(
            f'<tr class="{cls}"><td><a href="{_esc(r.source_url)}" target="_blank" '
            f'rel="noopener">{_esc(r.name)}</a></td>'
            f"<td class='num'>{len(r.offers)}</td><td class='ratings'>{badges}</td>"
            f"<td>{status}</td></tr>"
        )

    shop_counts = Counter(o.shop for o in offers)
    n_new = sum(1 for o in offers if not o.condition)
    # Shops start selected; clicking one toggles just that shop.
    shop_chips = "".join(
        f'<button class="chip chip--shop active" data-shop="{_esc(s)}" aria-pressed="true">'
        f'{_esc(s)}<span class="n">{n}</span></button>'
        for s, n in sorted(shop_counts.items())
    )
    # Size chips, letter sizes in their natural order and cm buckets ascending.
    size_counts = Counter(k for o in offers for k in _size_keys(o))

    def size_order(key: str):
        if key in _LETTER_SIZES:
            return (0, _LETTER_SIZES.index(key))
        return (1, int(key.split("-")[0]))

    size_chips = "".join(
        f'<button class="chip chip--size" data-size="{_esc(k)}" aria-pressed="false">'
        f'{_esc(k)}<span class="n">{n}</span></button>'
        for k, n in sorted(size_counts.items(), key=lambda kv: size_order(kv[0]))
    )

    prices = [o.price for o in offers if o.price]
    price_lo = int(min(prices)) if prices else 0
    price_hi = int(max(prices)) + 1 if prices else 0

    batteries = [o.battery_wh for o in offers if o.battery_wh]
    bat_lo = min(batteries) if batteries else 0
    bat_hi = max(batteries) if batteries else 0
    n_bat = len(batteries)
    n_bh = sum(1 for o in offers if o.body_height_min)

    hs = report.history_stats
    history_note = ""
    if report.history_error:
        history_note = f'<p class="sub">Preisverlauf nicht verfügbar: {_esc(report.history_error)}</p>'
    elif hs:
        history_note = (
            f'<p class="sub">Preisverlauf: {hs["runs"]} Läufe seit {_esc(hs["since"] or "-")}, '
            f'{hs["urls"]} beobachtete Angebote</p>'
        )

    cards = "\n".join(
        _offer_card(o, report.ratings.get(o.shop)) for o in offers
    ) or '<p class="empty">Keine Angebote über der Rabattschwelle gefunden.</p>'

    return f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>E-Bike-Deals ab {cfg.min_discount:.0f}% Rabatt</title>
<style>
:root {{
  --bg:#f6f7f9; --fg:#14171a; --muted:#5b6470; --card:#fff; --line:#e3e6ea;
  --accent:#0a7d3f; --badge:#c8102e; --chip:#eef1f4;
}}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#14171a; --fg:#e9ecef; --muted:#9aa4b0; --card:#1d2126; --line:#2c3238;
           --accent:#4ade80; --badge:#f0455f; --chip:#262b31; }}
}}
:root[data-theme="dark"] {{ --bg:#14171a; --fg:#e9ecef; --muted:#9aa4b0; --card:#1d2126;
  --line:#2c3238; --accent:#4ade80; --badge:#f0455f; --chip:#262b31; }}
:root[data-theme="light"] {{ --bg:#f6f7f9; --fg:#14171a; --muted:#5b6470; --card:#fff;
  --line:#e3e6ea; --accent:#0a7d3f; --badge:#c8102e; --chip:#eef1f4; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
.wrap {{ max-width:1180px; margin:0 auto; padding:28px 18px 60px; }}
h1 {{ font-size:1.7rem; margin:0 0 4px; letter-spacing:-.02em; }}
.sub {{ color:var(--muted); margin:0 0 24px; }}
details {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:12px 16px; margin-bottom:22px; }}
summary {{ cursor:pointer; font-weight:600; }}
table {{ width:100%; border-collapse:collapse; margin-top:10px; font-size:.88rem; }}
td {{ padding:6px 8px; border-top:1px solid var(--line); vertical-align:top; }}
td.num {{ text-align:right; font-variant-numeric:tabular-nums; width:60px; }}
tr.warn td, tr.err td {{ color:var(--muted); }}
tr.err td:last-child {{ color:var(--badge); }}
a {{ color:inherit; }}
.controls {{ display:flex; flex-wrap:wrap; gap:12px; align-items:center; margin-bottom:14px; }}
#q {{ flex:1 1 320px; background:var(--card); color:var(--fg); border:1px solid var(--line);
  border-radius:10px; padding:11px 14px; font-size:.95rem; font-family:inherit; }}
#q:focus {{ outline:2px solid var(--accent); outline-offset:1px; }}
.toggle {{ display:flex; align-items:center; gap:7px; font-size:.88rem; cursor:pointer;
  white-space:nowrap; }}
.toggle input {{ width:16px; height:16px; accent-color:var(--accent); cursor:pointer; }}
.filters {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom:14px; }}
.chip {{ background:var(--chip); border:1px solid var(--line); color:var(--muted);
  border-radius:999px; padding:6px 13px; font-size:.85rem; cursor:pointer;
  font-family:inherit; display:inline-flex; align-items:center; gap:6px; }}
.chip:hover {{ border-color:var(--accent); }}
.chip.active {{ background:var(--accent); color:#fff; border-color:transparent; }}
.chip .n {{ font-size:.75rem; opacity:.75; font-variant-numeric:tabular-nums; }}
.chip--all {{ font-weight:600; color:var(--fg); }}
.count {{ margin:0 0 16px; color:var(--muted); font-size:.85rem;
  font-variant-numeric:tabular-nums; }}
.card[hidden] {{ display:none; }}
.sel {{ display:flex; align-items:center; gap:6px; font-size:.85rem; color:var(--muted);
  white-space:nowrap; }}
.sel select, .sel input {{ background:var(--card); color:var(--fg);
  border:1px solid var(--line); border-radius:8px; padding:8px 10px; font-size:.87rem;
  font-family:inherit; }}
.sel input {{ width:104px; }}
.hint {{ font-size:.75rem; color:var(--muted); white-space:nowrap; }}
th {{ text-align:left; padding:6px 8px; font-size:.78rem; color:var(--muted);
  font-weight:600; text-transform:uppercase; letter-spacing:.04em; }}
th.num {{ text-align:right; }}
.tablenote {{ margin:10px 2px 2px; font-size:.78rem; color:var(--muted); }}
.tablenote code {{ background:var(--chip); padding:1px 5px; border-radius:4px; }}
.muted {{ color:var(--muted); }}
td.ratings {{ white-space:nowrap; }}
.rating {{ display:inline-block; background:var(--chip); border:1px solid var(--line);
  border-radius:5px; padding:1px 7px; margin:0 4px 2px 0; font-size:.76rem;
  text-decoration:none; color:var(--fg); white-space:nowrap; }}
.rating:hover {{ border-color:var(--accent); }}
.rating--link {{ border-style:dashed; color:var(--muted); }}
.shop .rating {{ margin-left:6px; text-transform:none; letter-spacing:0; }}
.sel select:focus, .sel input:focus {{ outline:2px solid var(--accent); outline-offset:1px; }}
.flabel {{ font-size:.85rem; color:var(--muted); align-self:center; margin-right:2px; }}
.chip--size.active {{ background:var(--accent); color:#fff; border-color:transparent; }}
.spec {{ font-size:.8rem; color:var(--muted); background:var(--chip);
  border-radius:5px; padding:1px 7px; }}
.hist {{ margin:0; display:flex; align-items:center; gap:6px; flex-wrap:wrap;
  font-size:.78rem; }}
.tag {{ background:var(--chip); color:var(--muted); border-radius:5px; padding:2px 7px; }}
.tag--new {{ background:transparent; border:1px dashed var(--line); }}
.tag--down {{ background:rgba(10,125,63,.14); color:var(--accent); font-weight:600; }}
.tag--up {{ background:rgba(200,16,46,.12); color:var(--badge); }}
.tag--low {{ background:var(--accent); color:#fff; font-weight:600; }}
.spark {{ color:var(--muted); margin-left:auto; }}
.grid {{ display:grid; gap:16px; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
  overflow:hidden; display:flex; flex-direction:column; }}
.thumb {{ position:relative; background:#fff; aspect-ratio:3/2; }}
.thumb img {{ width:100%; height:100%; object-fit:contain; }}
.noimg {{ width:100%; height:100%; background:var(--chip); }}
.badge {{ position:absolute; top:10px; left:10px; background:var(--badge); color:#fff;
  font-weight:700; font-size:.9rem; padding:4px 9px; border-radius:6px; }}
.cond {{ position:absolute; top:10px; right:10px; background:rgba(20,23,26,.82); color:#fff;
  font-size:.72rem; padding:3px 8px; border-radius:6px; }}
.cond--new {{ background:var(--accent); }}
.body {{ padding:14px 16px 16px; display:flex; flex-direction:column; gap:8px; flex:1; }}
.shop {{ margin:0; font-size:.76rem; text-transform:uppercase; letter-spacing:.06em;
  color:var(--muted); }}
.avail {{ text-transform:none; letter-spacing:0; }}
h3 {{ margin:0; font-size:.98rem; line-height:1.35; }}
h3 a {{ text-decoration:none; }}
h3 a:hover {{ text-decoration:underline; }}
.prices {{ margin:0; display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }}
.now {{ font-size:1.25rem; font-weight:700; }}
.was {{ color:var(--muted); text-decoration:line-through; font-size:.9rem; }}
.saving {{ color:var(--accent); font-size:.85rem; font-weight:600; }}
.sizes {{ margin:0; font-size:.85rem; }}
.lbl {{ color:var(--muted); display:block; margin-bottom:4px; font-size:.78rem; }}
.size {{ display:inline-block; background:var(--chip); border:1px solid var(--line);
  border-radius:6px; padding:2px 8px; margin:0 4px 4px 0; font-size:.83rem;
  text-decoration:none; }}
a.size:hover {{ border-color:var(--accent); }}
.size--none {{ background:transparent; border-style:dashed; color:var(--muted); }}
.note {{ margin:0; font-size:.8rem; color:var(--muted); }}
.cta {{ margin-top:auto; align-self:flex-start; background:var(--accent); color:#fff;
  text-decoration:none; padding:8px 14px; border-radius:8px; font-size:.87rem;
  font-weight:600; }}
.empty {{ color:var(--muted); }}
footer {{ margin-top:36px; color:var(--muted); font-size:.82rem; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>E-Bike-Deals ab {cfg.min_discount:.0f}&nbsp;% Rabatt</h1>
  <p class="sub">{len(offers)} Treffer aus {report.total_scanned} geprüften Angeboten ·
     Stand {generated}</p>
  {history_note}

  <details>
    <summary>Quellen &amp; Status ({len(report.results)} Shops)</summary>
    <table>
      <thead><tr><th>Shop</th><th class="num">Treffer</th>
        <th>Bewertung</th><th>Status</th></tr></thead>
      {''.join(shop_rows)}
    </table>
    <p class="tablenote">Noten von Trusted Shops (öffentliche API, wöchentlich
      aktualisiert). Trustpilot verbietet in seiner robots.txt den automatischen
      Abruf – dort führt der Link zum Profil, eine Note wird nicht angezeigt.
      Eigene Werte lassen sich in <code>bewertungen_manuell.json</code> eintragen.</p>
  </details>

  <div class="controls">
    <input type="search" id="q" placeholder="Suchen: Marke, Modell, Motor, Größe …"
           autocomplete="off" spellcheck="false">
    <label class="sel">Sortierung
      <select id="sort">
        <option value="discount">Rabatt absteigend</option>
        <option value="price-asc">Preis aufsteigend</option>
        <option value="price-desc">Preis absteigend</option>
        <option value="saving">Ersparnis in €</option>
        <option value="battery">Akkukapazität</option>
        <option value="drop">Größter Preisrückgang</option>
      </select>
    </label>
    <label class="sel">Preis von
      <input type="number" id="pmin" min="0" step="50" placeholder="{price_lo}">
    </label>
    <label class="sel">bis
      <input type="number" id="pmax" min="0" step="50" placeholder="{price_hi}">
    </label>
    <label class="toggle"><input type="checkbox" id="onlyNew"> Nur Neuware ({n_new})</label>
  </div>

  <div class="controls">
    <label class="sel">Körpergröße
      <input type="number" id="bh" min="120" max="220" step="1" placeholder="cm">
      <span class="hint">{n_bh} mit Angabe</span>
    </label>
    <label class="toggle" title="Schätzt aus der Rahmengröße, für welche Körpergröße ein Rad passt. Ohne Haken gelten diese Angebote als 'keine Angabe'."><input type="checkbox" id="estimate" checked>
      Rahmengröße mitprüfen (geschätzt)</label>
    <label class="sel">Akku von
      <input type="number" id="bmin" min="0" step="50" placeholder="{bat_lo}">
    </label>
    <label class="sel">bis
      <input type="number" id="bmax" min="0" step="50" placeholder="{bat_hi}">
      <span class="hint">Wh · {n_bat} mit Angabe</span>
    </label>
    <label class="toggle"><input type="checkbox" id="strict">
      Angebote ohne passende Angabe ausblenden</label>
  </div>

  <div class="filters">
    <button class="chip chip--all" id="toggleAll">Alle Shops abwählen</button>
    {shop_chips}
  </div>

  <div class="filters">
    <span class="flabel">Größe</span>
    {size_chips}
    <button class="chip chip--all" id="clearSizes" hidden>Größen zurücksetzen</button>
  </div>

  <p class="count" id="count" aria-live="polite"></p>
  <div class="grid">{cards}</div>
  <p class="empty" id="noHits" hidden>Keine Treffer für diese Auswahl.</p>

  <footer>
    Rabatt = 1 − Verkaufspreis / Streichpreis (UVP bzw. shopeigener Referenzpreis).
    Preise und Verfügbarkeit ändern sich laufend – bitte im Shop prüfen.
  </footer>
</div>
<script>
(function () {{
  var grid = document.querySelector('.grid');
  var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
  var shopChips = Array.prototype.slice.call(document.querySelectorAll('.chip--shop'));
  var sizeChips = Array.prototype.slice.call(document.querySelectorAll('.chip--size'));
  var q = document.getElementById('q');
  var sort = document.getElementById('sort');
  var pmin = document.getElementById('pmin');
  var pmax = document.getElementById('pmax');
  var bh = document.getElementById('bh');
  var bmin = document.getElementById('bmin');
  var bmax = document.getElementById('bmax');
  var strict = document.getElementById('strict');
  var estimate = document.getElementById('estimate');
  var onlyNew = document.getElementById('onlyNew');
  var toggleAll = document.getElementById('toggleAll');
  var clearSizes = document.getElementById('clearSizes');
  var count = document.getElementById('count');
  var noHits = document.getElementById('noHits');

  // Remember the original order so "Rabatt absteigend" can restore it exactly
  // rather than re-deriving it from rounded percentages.
  cards.forEach(function (c, i) {{ c.dataset.order = i; }});

  function num(el) {{
    var v = parseFloat(el.value);
    return isNaN(v) ? null : v;
  }}
  function activeSet(chips, key) {{
    var set = Object.create(null), any = false;
    chips.forEach(function (c) {{
      if (c.classList.contains('active')) {{ set[c.dataset[key]] = true; any = true; }}
    }});
    return any ? set : null;
  }}

  // ---- URL state: shops are stored only when a subset is selected, so a
  // plain link stays short and future shops are included by default.
  function writeState() {{
    var p = new URLSearchParams();
    if (q.value.trim()) p.set('q', q.value.trim());
    if (sort.value !== 'discount') p.set('sort', sort.value);
    if (num(pmin) !== null) p.set('min', num(pmin));
    if (num(pmax) !== null) p.set('max', num(pmax));
    if (num(bh) !== null) p.set('bh', num(bh));
    if (num(bmin) !== null) p.set('wmin', num(bmin));
    if (num(bmax) !== null) p.set('wmax', num(bmax));
    if (strict.checked) p.set('strict', '1');
    if (!estimate.checked) p.set('noest', '1');
    if (onlyNew.checked) p.set('new', '1');
    var offShops = shopChips.filter(function (c) {{ return !c.classList.contains('active'); }});
    if (offShops.length) {{
      p.set('shops', shopChips.filter(function (c) {{ return c.classList.contains('active'); }})
        .map(function (c) {{ return c.dataset.shop; }}).join(','));
    }}
    var onSizes = sizeChips.filter(function (c) {{ return c.classList.contains('active'); }});
    if (onSizes.length) {{
      p.set('sizes', onSizes.map(function (c) {{ return c.dataset.size; }}).join(','));
    }}
    var hash = p.toString();
    history.replaceState(null, '', hash ? '#' + hash : location.pathname + location.search);
  }}

  function setChips(chips, key, wanted) {{
    chips.forEach(function (c) {{
      var on = wanted === null ? key === 'shop' : wanted.indexOf(c.dataset[key]) !== -1;
      c.classList.toggle('active', on);
      c.setAttribute('aria-pressed', on);
    }});
  }}

  // Reset to defaults first, then apply the hash. Merging into the current
  // state instead would mean a shared link does not reproduce the sender's
  // view - whatever the recipient had set would leak into it.
  function readState() {{
    var p = new URLSearchParams(location.hash.replace(/^#/, ''));
    q.value = p.get('q') || '';
    sort.value = p.get('sort') || 'discount';
    pmin.value = p.get('min') || '';
    pmax.value = p.get('max') || '';
    bh.value = p.get('bh') || '';
    bmin.value = p.get('wmin') || '';
    bmax.value = p.get('wmax') || '';
    strict.checked = p.get('strict') === '1';
    estimate.checked = p.get('noest') !== '1';
    onlyNew.checked = p.get('new') === '1';
    setChips(shopChips, 'shop', p.has('shops') ? p.get('shops').split(',') : null);
    setChips(sizeChips, 'size', p.has('sizes') ? p.get('sizes').split(',') : []);
  }}

  var SORTS = {{
    'discount':   function (a, b) {{ return a.order - b.order; }},
    'price-asc':  function (a, b) {{ return a.price - b.price; }},
    'price-desc': function (a, b) {{ return b.price - a.price; }},
    'saving':     function (a, b) {{ return b.saving - a.saving; }},
    'battery':    function (a, b) {{ return b.battery - a.battery; }},
    'drop':       function (a, b) {{ return a.drop - b.drop; }}
  }};

  function apply() {{
    var shops = activeSet(shopChips, 'shop');
    var sizes = activeSet(sizeChips, 'size');
    // Every search word must appear somewhere in the card, so "cube bosch"
    // narrows instead of widening.
    var terms = q.value.toLowerCase().split(/\\s+/).filter(Boolean);
    var lo = num(pmin), hi = num(pmax);
    var height = num(bh), bLo = num(bmin), bHi = num(bmax);
    var visible = [];
    // Offers that only survived because the shop states nothing about the
    // criterion. Reported separately so a filter never looks stricter than it
    // was: 39 % of listings carry no battery figure at all.
    var unknown = 0;
    // Matched only via the frame-size estimate, never stated by the shop.
    var estimated = 0;

    cards.forEach(function (card) {{
      var ok = shops ? !!shops[card.dataset.shop] : false;
      if (ok && onlyNew.checked) ok = card.dataset.condition === 'new';
      if (ok && lo !== null) ok = parseFloat(card.dataset.price) >= lo;
      if (ok && hi !== null) ok = parseFloat(card.dataset.price) <= hi;
      if (ok && sizes) {{
        var own = (card.dataset.sizes || '').split('|');
        ok = own.some(function (s) {{ return s && sizes[s]; }});
      }}

      var missing = false, guessed = false;
      if (ok && height !== null) {{
        var bmn = +card.dataset.bhmin, bmx = +card.dataset.bhmax;
        if (bmn) {{
          ok = height >= bmn && height <= bmx;
        }} else if (estimate.checked && +card.dataset.bhestMin) {{
          // Derived from the frame size, not stated by the shop.
          ok = height >= +card.dataset.bhestMin && height <= +card.dataset.bhestMax;
          guessed = ok;
        }} else {{
          missing = true;
          ok = !strict.checked;
        }}
      }}
      if (ok && (bLo !== null || bHi !== null)) {{
        var wh = +card.dataset.battery;
        var floor = +card.dataset.batmin;
        if (wh) {{
          if (bLo !== null && wh < bLo) ok = false;
          if (bHi !== null && wh > bHi) ok = false;
        }} else if (floor && bHi === null && bLo !== null && floor >= bLo) {{
          // "≥ 600 Wh" proves a 600 minimum is met. It proves nothing about
          // an upper bound, and a floor below the requested minimum proves
          // nothing either - a "400+ Wh" bike may well hold 800. Both of
          // those fall through to "unknown" rather than being excluded.
          ok = true;
        }} else {{
          missing = true;
          ok = !strict.checked;
        }}
      }}

      if (ok && terms.length) {{
        var hay = card.dataset.search;
        ok = terms.every(function (t) {{ return hay.indexOf(t) !== -1; }});
      }}
      card.hidden = !ok;
      if (ok) {{
        visible.push(card);
        if (missing) unknown++;
        if (guessed) estimated++;
      }}
    }});

    // Reordering only the visible cards keeps this cheap on big reports.
    var mode = SORTS[sort.value] ? sort.value : 'discount';
    var keyed = visible.map(function (c) {{
      return {{
        el: c,
        order: +c.dataset.order,
        price: parseFloat(c.dataset.price) || 0,
        saving: parseFloat(c.dataset.saving) || 0,
        battery: parseFloat(c.dataset.battery) || 0,
        drop: parseFloat(c.dataset.drop || '0')
      }};
    }});
    keyed.sort(SORTS[mode]);
    var frag = document.createDocumentFragment();
    keyed.forEach(function (k) {{ frag.appendChild(k.el); }});
    grid.appendChild(frag);

    count.textContent = visible.length + ' von ' + cards.length + ' Angeboten'
      + (estimated ? ' · ' + estimated + ' über geschätzte Rahmengröße' : '')
      + (unknown ? ' · ' + unknown + ' ohne Angabe dazu' : '');
    noHits.hidden = visible.length !== 0;
    var allOn = shopChips.every(function (c) {{ return c.classList.contains('active'); }});
    toggleAll.textContent = allOn ? 'Alle Shops abwählen' : 'Alle Shops auswählen';
    clearSizes.hidden = !sizes;
    writeState();
  }}

  function bindChips(chips) {{
    chips.forEach(function (chip) {{
      chip.addEventListener('click', function () {{
        chip.classList.toggle('active');
        chip.setAttribute('aria-pressed', chip.classList.contains('active'));
        apply();
      }});
    }});
  }}
  bindChips(shopChips);
  bindChips(sizeChips);

  toggleAll.addEventListener('click', function () {{
    var allOn = shopChips.every(function (c) {{ return c.classList.contains('active'); }});
    shopChips.forEach(function (c) {{
      c.classList.toggle('active', !allOn);
      c.setAttribute('aria-pressed', !allOn);
    }});
    apply();
  }});

  clearSizes.addEventListener('click', function () {{
    sizeChips.forEach(function (c) {{
      c.classList.remove('active');
      c.setAttribute('aria-pressed', 'false');
    }});
    apply();
  }});

  [q, pmin, pmax, bh, bmin, bmax].forEach(function (el) {{
    el.addEventListener('input', apply);
  }});
  [sort, onlyNew, strict, estimate].forEach(function (el) {{
    el.addEventListener('change', apply);
  }});
  q.addEventListener('keydown', function (e) {{
    if (e.key === 'Escape') {{ q.value = ''; apply(); }}
  }});
  // "/" focuses the search box, as in most modern list UIs.
  document.addEventListener('keydown', function (e) {{
    if (e.key === '/' && document.activeElement !== q) {{ e.preventDefault(); q.focus(); }}
  }});
  // Back/forward through shared links.
  window.addEventListener('hashchange', function () {{ readState(); apply(); }});

  readState();
  apply();
}})();
</script>
</body>
</html>"""
