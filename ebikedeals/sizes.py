"""Fill in frame sizes for offers whose listing page did not carry them.

Only offers that already passed the discount filter are enriched, so this
costs one request per *hit* instead of one per product - typically a handful
of requests instead of thousands.

Every shop exposes its size options differently, so this runs several
strategies over the product page and keeps the first that yields plausible
sizes.
"""

from __future__ import annotations

import json
import re

from .htmlutil import parse, script_blocks
from .model import Offer, dedup_sizes, looks_like_size, parse_battery_wh, parse_price

# Attribute/option names that denote a frame size in German shops.
SIZE_LABEL = re.compile(
    r"rahmenh(ö|oe)he|rahmengr(ö|oe)(ss|ß)e|rahmen-?gr|gr(ö|oe)(ss|ß)e|size|frame[_ -]?size",
    re.I,
)


def enrich(offer: Offer, html: str) -> list[str]:
    """Return frame sizes found on a product page (may be empty).

    Strategies are ordered most-trustworthy first and the first plausible
    result wins. Everything here reads *variant* data - no free-text scraping
    of the page, because that reliably picks up the manufacturer's
    body-height/frame-size conversion table instead of the sizes on offer.
    An empty list is a better answer than a wrong one.
    """
    for strategy in (
        _from_jsonld,
        _from_magento_config,
        _from_shopware6,
        _from_shopware5,
        _from_selects,
    ):
        try:
            sizes = strategy(html)
        except Exception:
            continue
        sizes = dedup_sizes(s for s in sizes if looks_like_size(s))
        if sizes and _plausible(sizes):
            return sizes
    return []


_INCH = re.compile(r'^\d{2}\s*(?:"|zoll)$', re.I)
_CM = re.compile(r"^\d{2}(?:[.,]\d)?\s*cm$", re.I)


def _plausible(sizes: list[str]) -> bool:
    """Reject results that look like a size-conversion table rather than stock.

    A real listing offers one size system and rarely more than ~10 options; a
    conversion table pairs inches with centimetres across the full range.
    """
    if len(sizes) > 12:
        return False
    inch = sum(1 for s in sizes if _INCH.match(s))
    cm = sum(1 for s in sizes if _CM.match(s))
    return not (inch >= 3 and cm >= 3)


# ---------------------------------------------------------------------------
def _from_jsonld(html: str) -> list[str]:
    """Sizes from ProductGroup.hasVariant - the only structured JSON-LD source.

    Scanning every Product node instead would also match the page's own
    product, whose name/description mentions unrelated centimetre values.
    """
    out: list[str] = []
    for block in script_blocks(html, "application/ld+json"):
        try:
            data = json.loads(block)
        except Exception:
            continue
        for node in _walk_json(data):
            if not isinstance(node, dict):
                continue
            for variant in _as_list(node.get("hasVariant")):
                if not isinstance(variant, dict):
                    continue
                explicit = variant.get("size")
                if isinstance(explicit, str) and explicit.strip():
                    out.append(explicit.strip())
                    continue
                name = variant.get("name")
                if isinstance(name, str):
                    m = re.search(r"\b(\d{2})\s*cm\b", name)
                    if m:
                        out.append(f"{m.group(1)} cm")
    return out


def _from_magento_config(html: str) -> list[str]:
    """Magento swatch config: jsonConfig.attributes[*].{label, options[]}."""
    out: list[str] = []
    for m in re.finditer(r'"attributes"\s*:\s*\{', html):
        start = m.end() - 1
        raw = _balanced(html, start)
        if not raw:
            continue
        try:
            attrs = json.loads(raw)
        except Exception:
            continue
        for attr in attrs.values():
            if not isinstance(attr, dict):
                continue
            label = f"{attr.get('label', '')} {attr.get('code', '')}"
            if not SIZE_LABEL.search(label):
                continue
            for opt in attr.get("options") or []:
                lbl = opt.get("label")
                if lbl:
                    out.append(str(lbl))
    return out


def _from_shopware6(html: str) -> list[str]:
    doc = parse(html)
    out: list[str] = []
    for group in doc.find_all(cls="product-detail-configurator-group"):
        title = group.find(cls="product-detail-configurator-group-title")
        if title is not None and not SIZE_LABEL.search(title.text):
            continue
        for lbl in group.find_all(cls="product-detail-configurator-option-label"):
            out.append(lbl.get("title") or lbl.text)
    if not out:
        for lbl in doc.find_all(cls="product-detail-configurator-option-label"):
            out.append(lbl.get("title") or lbl.text)
    return out


def _from_shopware5(html: str) -> list[str]:
    doc = parse(html)
    out: list[str] = []
    for group in doc.find_all(cls="configurator--group"):
        label = group.find(cls="configurator--label")
        if label is not None and not SIZE_LABEL.search(label.text):
            continue
        for opt in group.find_all("option"):
            out.append(opt.text)
        for opt in group.find_all(cls="option--label"):
            out.append(opt.text)
    return out


def _from_selects(html: str) -> list[str]:
    """Any <select> whose name/id/label mentions a size."""
    doc = parse(html)
    out: list[str] = []
    for sel in doc.find_all("select"):
        ident = " ".join((sel.get("name"), sel.get("id"), sel.get("class"), sel.get("aria-label")))
        if not SIZE_LABEL.search(ident):
            continue
        for opt in sel.find_all("option"):
            if opt.get("disabled"):
                continue
            out.append(opt.text)
    return out


# ---------------------------------------------------------------------------
# Battery capacity from the product page
# ---------------------------------------------------------------------------
BATTERY_LABEL = re.compile(
    r"akku|batter|kapazit(ä|ae)t|energieinhalt|capacity", re.I
)


def read_battery_wh(html: str) -> int | None:
    """Exact capacity in Wh from a product page's spec table.

    Shopware and Magento both render specs as label/value pairs; matching the
    label first avoids picking up a "500 Wh" that appears in marketing copy
    about a different model.
    """
    doc = parse(html)

    # Property tables: <tr><th>Akkukapazität</th><td>625 Wh</td></tr> and the
    # <dt>/<dd> variant Shopware 6 uses.
    for row in doc.find_all("tr") + doc.find_all("li"):
        cells = row.find_all("th") + row.find_all("td") + row.find_all("dt") + row.find_all("dd")
        if len(cells) < 2:
            continue
        label = cells[0].text
        if not BATTERY_LABEL.search(label):
            continue
        wh = parse_battery_wh(" ".join(c.text for c in cells[1:]))
        if wh:
            return wh

    for dl in doc.find_all("dl"):
        kids = [c for c in dl.children if c.tag in ("dt", "dd")]
        for i, node in enumerate(kids):
            if node.tag == "dt" and BATTERY_LABEL.search(node.text) and i + 1 < len(kids):
                wh = parse_battery_wh(kids[i + 1].text)
                if wh:
                    return wh

    # Shopware 6 renders specs as sibling divs rather than a table:
    #   <div class="properties-label">Akku :</div><div class="properties-value">545 Wh</div>
    for label_el in doc.find_by_class_prefix("properties-label"):
        if not BATTERY_LABEL.search(label_el.text):
            continue
        parent = label_el.parent
        if parent is None:
            continue
        siblings = [c for c in parent.children if c.tag != "#text"]
        try:
            idx = siblings.index(label_el)
        except ValueError:
            continue
        for nxt in siblings[idx + 1:idx + 3]:
            wh = parse_battery_wh(nxt.text)
            if wh:
                return wh

    # JSON-LD additionalProperty entries.
    for block in script_blocks(html, "application/ld+json"):
        try:
            data = json.loads(block)
        except Exception:
            continue
        for node in _walk_json(data):
            if not isinstance(node, dict):
                continue
            name = str(node.get("name", ""))
            if BATTERY_LABEL.search(name):
                wh = parse_battery_wh(str(node.get("value", "")))
                if wh:
                    return wh
    return None


def read_og_image(html: str) -> str:
    """Main product image from a detail page's Open Graph / JSON-LD metadata.

    A fallback for listings that build their thumbnails in JavaScript (nubuk),
    so the static listing HTML carries no usable <img>. Product pages set
    og:image reliably; when the page is fetched anyway for sizes, the image
    costs no extra request.
    """
    doc = parse(html)
    for meta in doc.find_all("meta"):
        prop = (meta.get("property") or meta.get("name") or "").lower()
        if prop in ("og:image", "og:image:secure_url", "twitter:image"):
            url = (meta.get("content") or "").strip()
            if url and not url.startswith("data:"):
                return url

    for block in script_blocks(html, "application/ld+json"):
        try:
            data = json.loads(block)
        except Exception:
            continue
        for node in _walk_json(data):
            if not isinstance(node, dict) or node.get("@type") != "Product":
                continue
            img = node.get("image")
            if isinstance(img, list):
                img = img[0] if img else ""
            if isinstance(img, dict):
                img = img.get("url") or ""
            if isinstance(img, str) and img.strip():
                return img.strip()
    return ""


# ---------------------------------------------------------------------------
# Datenblatt-Merkmale: Schaltungstyp, Motor, Bremsen, Radgröße
# ---------------------------------------------------------------------------
# Motor-eigene Marken (eindeutig ein Antrieb, kein Schaltungshersteller).
_MOTOR_BRANDS = re.compile(
    r"\b(Bosch|Yamaha|Brose|Bafang|Fazua|Panasonic|Mahle|TQ|Pinion|Neodrives|"
    r"Ananda|Impulse|Continental|Specialized)\b", re.I)
# Shimano baut Motor UND Schaltung - als Motor nur mit STEPS/EP-Kennung zählen.
_MOTOR_SHIMANO = re.compile(r"Shimano\s*(?:STEPS|EP\s?\d|E\d{3,4}|DU[- ])", re.I)
_HUB = re.compile(r"\b(Nabenschaltung|Nexus|Inter[- ]?\d|Enviolo|NuVinci|Rohloff|Alfine)\b", re.I)
_DERAIL = re.compile(
    r"\b(Kettenschaltung|Schaltwerk|Kassette|Umwerfer|Deore|SLX|XTR?|Alivio|Acera|"
    r"Altus|Tourney|Cues|GRX|Microshift|Sensah|Advent|SRAM\s*(?:GX|NX|SX|X0|X1))\b", re.I)
_WHEEL = re.compile(r"\b(20|24|26|27[.,]5|28|29)\s*(?:zoll|inch|[\"″'])", re.I)


def _motor_of(text: str) -> str:
    if _MOTOR_SHIMANO.search(text):
        return "Shimano"
    m = _MOTOR_BRANDS.search(text or "")
    return m.group(1)[0].upper() + m.group(1)[1:] if m else ""


def _wheel_of(text: str) -> str:
    m = _WHEEL.search(text or "")
    return f'{m.group(1).replace(",", ".")}"' if m else ""


def _drivetrain_of(text: str) -> str:
    if _HUB.search(text or ""):
        return "Nabenschaltung"
    if _DERAIL.search(text or ""):
        return "Kettenschaltung"
    return ""


def _brakes_of(text: str) -> str:
    t = (text or "").lower()
    if "hydraul" in t:
        return "hydraulisch"
    if "mechan" in t or "seilzug" in t:
        return "mechanisch"
    return ""


def specs_from_text(text: str) -> dict:
    """Merkmale, die schon im Titel/Notiz stehen - breite Abdeckung ohne Fetch."""
    return {
        "motor": _motor_of(text),
        "wheel_size": _wheel_of(text),
        "drivetrain": _drivetrain_of(text),
    }


def _spec_pairs(doc) -> list[tuple[str, str]]:
    """Label/Wert-Paare aus den üblichen Datenblatt-Formaten (wie read_battery_wh)."""
    pairs: list[tuple[str, str]] = []
    for row in doc.find_all("tr") + doc.find_all("li"):
        cells = row.find_all("th") + row.find_all("td") + row.find_all("dt") + row.find_all("dd")
        if len(cells) >= 2:
            pairs.append((cells[0].text, " ".join(c.text for c in cells[1:])))
    for dl in doc.find_all("dl"):
        kids = [c for c in dl.children if c.tag in ("dt", "dd")]
        for i, node in enumerate(kids):
            if node.tag == "dt" and i + 1 < len(kids) and kids[i + 1].tag == "dd":
                pairs.append((node.text, kids[i + 1].text))
    for lab in doc.find_by_class_prefix("properties-label"):
        parent = lab.parent
        if parent is None:
            continue
        sibs = [c for c in parent.children if c.tag != "#text"]
        try:
            idx = sibs.index(lab)
        except ValueError:
            continue
        if idx + 1 < len(sibs):
            pairs.append((lab.text, sibs[idx + 1].text))
    return pairs


def read_specs(html: str) -> dict:
    """Schaltungstyp/Motor/Bremsen/Radgröße aus dem Datenblatt der Produktseite.

    Erst gezielt über Label (z. B. "Schaltungs-Typ", "Motor", "Bremse"), dann
    als Rückfall aus dem gesamten Datenblatt-Text (Schaltwerk+Kassette ⇒
    Kettenschaltung usw.). Leere Werte, wo der Shop nichts ausweist.
    """
    doc = parse(html)
    pairs = _spec_pairs(doc)
    out = {"drivetrain": "", "motor": "", "brakes": "", "wheel_size": ""}
    for label, value in pairs:
        l = label.lower()
        if not out["drivetrain"] and "schalt" in l and ("typ" in l or "art" in l):
            if "naben" in value.lower():
                out["drivetrain"] = "Nabenschaltung"
            elif "ketten" in value.lower():
                out["drivetrain"] = "Kettenschaltung"
        if not out["motor"] and ("motor" in l or "antrieb" in l):
            out["motor"] = _motor_of(value)
        if not out["brakes"] and "brems" in l:
            out["brakes"] = _brakes_of(value)
        if not out["wheel_size"] and ("laufrad" in l or "radgr" in l or "reifen" in l or "zoll" in l):
            out["wheel_size"] = _wheel_of(value)

    whole = " ".join(f"{k} {v}" for k, v in pairs)
    out["drivetrain"] = out["drivetrain"] or _drivetrain_of(whole)
    out["motor"] = out["motor"] or _motor_of(whole)
    out["brakes"] = out["brakes"] or _brakes_of(whole)
    out["wheel_size"] = out["wheel_size"] or _wheel_of(whole)
    return out


# ---------------------------------------------------------------------------
# Cross-checking the listing price against the product page
# ---------------------------------------------------------------------------
def read_prices(html: str) -> tuple[float | None, float | None]:
    """Best-effort (price, list_price) from a product detail page.

    Shops are not always consistent: bike-discount advertises one UVP on the
    listing and a lower one on the product page. Returning both lets the
    report state the discrepancy instead of silently picking one.
    """
    doc = parse(html)

    # Magento: machine-readable amounts.
    final = old = None
    for el in doc.walk():
        amount = el.get("data-price-amount")
        if not amount:
            continue
        kind = el.get("data-price-type")
        if kind == "finalPrice" and final is None:
            final = parse_price(amount)
        elif kind == "oldPrice" and old is None:
            old = parse_price(amount)
    if final is not None:
        return final, old

    # Shopware 6 detail page.
    price_el = doc.find(cls="product-detail-price")
    if price_el is not None:
        price = parse_price(price_el.own_text) or parse_price(price_el.text)
        list_el = doc.find(cls="list-price-price")
        return price, (parse_price(list_el.text) if list_el is not None else None)

    return None, None


def _balanced(text: str, start: int) -> str | None:
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, min(len(text), start + 400_000)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _walk_json(node):
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk_json(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_json(v)
