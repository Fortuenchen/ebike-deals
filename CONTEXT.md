# Kontext: Wie diese Anwendung funktioniert

Diese Seite fasst zusammen, was man über das Projekt wissen muss, ohne die
Entstehungsgeschichte zu kennen. Sie richtet sich an alle, die daran
weiterarbeiten — auch an ein KI-Modell in einer neuen Sitzung.

**Kurz:** Ein Scanner, der 21 deutsche E-Bike-Shops nach Angeboten ab einem
Mindestrabatt durchsucht und einen HTML-Bericht mit Direktlink, Preis/UVP,
Größen, Akku, Standort und Preisverlauf erzeugt.

Repository: https://github.com/Fortuenchen/ebike-deals (öffentlich, MIT)

---

## 1. Grundentscheidungen

| Entscheidung | Grund |
|---|---|
| Python, einzige Pflichtabhängigkeit `httpx` | läuft ohne Installationsorgie; eigener Mini-DOM statt BeautifulSoup |
| `playwright` optional | nur für `--render` (ein Shop) |
| Bericht = **eine** HTML-Datei | funktioniert offline, per Doppelklick, auch in fünf Jahren |
| keine externen CDNs, keine Kartenkacheln | kein Fremdzugriff beim Öffnen, kein Verraten des Lesers |
| Kommentare erklären das *Warum* | das *Was* steht im Code |

**Sprachmischung:** Ältere Module sind englisch kommentiert, neuere deutsch.
Das ist gewachsen, nicht geplant. Bei Änderungen die Sprache der umgebenden
Datei beibehalten.

---

## 2. Architektur

```
run.py ──> ebikedeals/cli.py ──> runner.py  (Orchestrierung)
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
   adapters/*                    net.py                    report.py
   (je Shopsystem)          (HTTP, Cache, Limits)         (HTML/JSON)
        │                           │                           │
        │                      cachetags.py               standorte.py
        │                       robots.py                  affiliate.py
        │                                                    fit.py
   model.py (Offer)          history.py (Preisverlauf)    ratings.py
                             sizes.py (Nachladen)
```

### Ablauf eines Laufs

1. `cli.py` baut `RunConfig` aus den Argumenten
2. `runner.run()` legt `Fetcher` an, räumt abgelaufene Cache-Einträge weg
3. Bewertungen einsammeln (`ratings.collect`, wöchentlich zwischengespeichert)
4. Bis zu 5 Shops parallel: `_scrape_shop` je Adapter im Thread-Pool
5. Je Angebot: Rabattfilter → Ausverkauft-Filter → Zustand → Akku aus Titel
6. Deduplizierung je Shop
7. Nachladen der Produktseite, wo Größen fehlen (+ Preisstichprobe, + Akku)
8. Preisverlauf: erst lesen (Historie anhängen), dann heutigen Tag schreiben
9. `report.py` erzeugt `bericht.html` und optional `deals.json`

### Module

| Modul | Aufgabe | Besonderheit |
|---|---|---|
| `model.py` | `Offer`, Preis-/Größen-Parser | deutsche Zahlformate, Zustandserkennung, Akku-Regex |
| `net.py` | HTTP, Cache, Drosselung, Retry | LZMA-Cache, Rate-Limit-Budget, curl-Rückfall |
| `cachetags.py` | Kategorien für Cache-Einträge | shop/kind/label |
| `robots.py` | eigener robots.txt-Parser | Python-Standardparser ist unbrauchbar (s. u.) |
| `history.py` | Preisverlauf | Tagesdateien als Wahrheit, SQLite als Index |
| `sizes.py` | Größen/Akku von Produktseiten | mehrere Strategien, erste plausible gewinnt |
| `fit.py` | Rahmengröße → Körpergröße | Schätzung, klar gekennzeichnet |
| `standorte.py` | Orte, Entfernungen | Haversine, Daten aus `standorte.json` |
| `ratings.py` | Shop-Bewertungen | Trusted Shops per API, Trustpilot nur Link |
| `affiliate.py` | Partnerlinks | erzwingt Werbekennzeichnung |
| `render.py` | Headless-Chromium | optional, nur für lucky-bike |
| `report.py` | HTML + JSON | gesamte UI, ~900 Zeilen |

---

## 3. Adapter: Zuordnung zur Architektur

Alle Adapter erben von `adapters/base.py:Adapter` und liefern `scrape()` als
Generator von `Offer`. Gemeinsame Helfer: `paged_listing()` (Seitenlauf über
mehrere Listing-URLs mit Deduplizierung), `nearest_product_link()`,
`fetch_page()`.

**Wichtige Adapter-Attribute:**

- `source_url` — Haupteinstieg; `extra_urls` — weitere Listings
- `page_budget` — eigenes Seitenlimit (überschreibt `--max-pages` nach oben)
- `needs_render` — braucht `--render`, sonst übersprungen
- `default_condition` — gilt für den ganzen Shop (z. B. upway: refurbished)
- `skipped_reason` — wird im Bericht als Begründung angezeigt

| Datei | Shopsystem | Shops |
|---|---|---|
| `shopify.py` | Shopify `products.json` | bikemarket24, boc24, e-bike-only, fahrrad.de, upway |
| `shopware6.py` | Shopware 6 | bike-angebot, denfeld, bike-discount, mhw-bike, radwelt |
| `magento.py` | Magento 2 | fahrrad24, fahrradlagerverkauf |
| `woocommerce.py` | WooCommerce Store API | ebikestock |
| `custom_html.py` | eigene Themes | fahrrad-xxl, radfieber (OXID), rad1 (Shopware 5), nubuk (plentymarkets) |
| `js_apps.py` | JS-Apps mit Daten im HTML | bikeexchange (Next.js RSC), jobrad-loop (Next.js) |
| `luckybike.py` | OXID, nur gerendert | lucky-bike |
| `__init__.py` | Registry + bike24 (gesperrt) | — |

---

## 4. Wie die Shops angesprochen werden

| Shop | Zugriff | Preisquelle | Größen |
|---|---|---|---|
| bikemarket24, boc24, e-bike-only, fahrrad.de, upway | `products.json` | `compare_at_price` | Varianten-Optionen |
| ebikestock | Store API `on_sale=true` | `regular_price` | `pa_rahmengroesse` |
| bike-angebot, denfeld, bike-discount, mhw-bike, radwelt | HTML | `.list-price-price` | Konfigurator-Labels |
| fahrrad24, fahrradlagerverkauf | HTML | `data-price-amount` | Produktseite |
| fahrrad-xxl | HTML | `.fxxl-strike-price` | Listing + **Filialbestand** |
| radfieber | HTML | `.current`/`.old` | JSON-LD `hasVariant` |
| rad1 | HTML | `.price--default` | Produktseite |
| nubuk | HTML | `.product-card__price` | – |
| bikeexchange | RSC-Payload | Cent-Beträge | `sizes[]` **mit Link je Größe** |
| jobrad-loop | `__NEXT_DATA__` | `recommendedPrice` | `frame_height_manufacturer` |
| lucky-bike | **gerendert** | zweigeteilte Spans | – |
| bike24 | **gesperrt** | – | – |

### Sale-Kategorien sind kuratiert, nicht vollständig

Eine Sale-Kategorie ist die Auswahl des Shops, nicht die Liste alles
Reduzierten. Gemessene Zusatztreffer beim Mitscannen der Gesamtkategorie:
fahrrad24 +31, upway +38, e-bike-only +7, fahrrad-xxl +5.

**Beim Nachmessen nach lieferbaren Treffern zählen, nicht nach Rabatten.**
Genau dieser Fehler ließ upways Archiv `all` (3500 Räder, 126 lieferbar) besser
aussehen als den echten Bestand `sale` (796, alle lieferbar).

---

## 5. Aufgetretene Probleme (und warum sie schwer zu sehen waren)

Alle folgenden Fehler sahen wie plausible Ergebnisse aus. Das ist das
wiederkehrende Muster dieses Projekts: **Ein Scraper scheitert selten mit einer
Ausnahme, er liefert leise weniger.**

| Problem | Symptom | Ursache | Gegenmittel |
|---|---|---|---|
| Verfügbarkeit an Größen gekoppelt | upway 717 → 65 Treffer | Shopify-Einzelräder haben keine Größenvarianten | `in_stock` aus `available`, nicht aus Größen |
| Archiv statt Bestand | upway sah „besser" aus | nur Rabatte gezählt, nicht Verfügbarkeit | `audit.py` warnt bei >70 % ausverkauft |
| Sale-Kategorie unvollständig | Rad mit 64 % fehlte | Kategorie ist kuratiert | `extra_urls` |
| radfieber-Paginierung | 24 statt 103 Räder | `?pgNr=` wird ignoriert, Pfad ist `/2/` | Pfad-Paginierung |
| Marken-Link statt Produkt | 6 statt 36 Angebote | häufigster Link gewann | Taxonomie-Links abgewertet |
| Größentabelle als Größen | 22 „Größen" je Rad | Umrechnungstabelle erwischt | Plausibilitätsprüfung, Notfallstrategie entfernt |
| Laufradgröße als Rahmengröße | 28" als Größe | falsches Attribut | nur `frame_height_manufacturer` |
| lucky-bike Preis | 219999 € statt 2199,99 € | Preis in zwei Spans | zusammensetzen, dann parsen |
| jobrad-loop-URLs | alle 404 | URL-Form geraten | `_url` aus den Daten |
| Trusted-Shops-Fehlzuordnung | bike24 → „MEGA Bike" | Lookup matcht unscharf | Domain muss exakt passen |
| Shopify verschluckte Fehler | „0 von 0 geprüft" | jede Exception gefangen | Fehler auf Seite 1 wirft |
| Cache doppelt | 2× dieselben 19 Dateien | `audit.py` ohne Cache-Kontext | Scope auch dort setzen |
| `robotparser` unbrauchbar | 3 Shops „verboten" | bekam selbst 403, meldete „alles verboten" | eigener Parser in `robots.py` |

### Zwei Fehler in meiner eigenen Diagnose

1. **Kompression zu optimistisch gemessen.** Erst Dateien aneinandergehängt
   (nutzt Redundanz zwischen ihnen), dann korrekt einzeln → 10,5× statt 16,5×.
2. **429 ≠ Rate-Limit.** Ich hielt 429 für behebbar und 403 für IP-Reputation.
   Beides ist IP-Reputation, Shopify signalisiert sie nur als 429. Ein Testlauf
   wartete 41 Minuten zusätzlich und änderte nichts.

---

## 6. Bewusst nicht gemacht

- **bike24.de**: Akamai-Challenge mit Proof-of-Work. Sie zu lösen wäre ein
  Umgehen der Bot-Erkennung.
- **Trustpilot-Noten**: robots.txt endet mit `Disallow: /` für `*`. Namentliche
  Crawler dürfen, diese Anwendung ist keiner — sich als einer auszugeben wäre
  eine Falschangabe.
- **Residential-Proxys, TLS-Fingerprint-Spoofing**: gleiches Prinzip. Der
  Unterschied ist *woher man legitim zugreift* (frei wählbar) gegenüber *sich
  als etwas anderes ausgeben* (nicht).

`--render` für lucky-bike ist bewusst **kein** Verstoß dagegen: Es wird keine
Hürde gelöst, nur JavaScript ausgeführt, und robots.txt erlaubt die Pfade.

---

## 7. Betrieb

### Täglicher Lauf

`.github/workflows/taeglich.yml`, 04:00 UTC, manuell auslösbar.

**Wo er läuft, entscheidet `RUNNER_LABEL`:**
- nicht gesetzt → `ubuntu-latest`; dort weisen **8 von 21 Shops** die IP ab
  (5× 429, 3× 403) → ~940 statt ~1700 Angebote → `ci_check.py` verwirft
- `self-hosted` → eigener Rechner, alle Shops antworten normal

Einrichtung: `runner_einrichten.ps1` (holt das Token zur Laufzeit, speichert es
nirgends). `-AlsDienst` braucht Administratorrechte.

### Plausibilitätsprüfung

`ci_check.py` bricht ab bei <50 % der Vortagesangebote, >3 fehlerhaften Shops
oder fehlender `deals.json`. Selbstkalibrierend über `preise.db` — keine feste
Erwartung.

### Daten

| Datei | Versioniert? | Zweck |
|---|---|---|
| `historie/*.jsonl.xz` | **ja** | Wahrheit des Preisverlaufs, ~52 KB/Tag |
| `preise.db` | nein | abgeleiteter Index, wird rekonstruiert |
| `standorte.json` | ja | Koordinaten, 11 KB |
| `bewertungen.json` | nein | Cache, wöchentlich neu |
| `affiliate.json` | **nein** | Partner-IDs, öffentliches Repo! |
| `.cache/` | nein | LZMA, ~33 MB, Faktor 10,5 |
| `bericht.html`, `deals.json` | nein | Ausgabe |

`preise.db` täglich zu committen wäre nach einem Jahr mehrere Gigabyte —
unveränderliche Tagesdateien kosten ~23 MB.

### Cache

`.cache/<shop>/<kind>/<hash>.xz`, kind ∈ {listing, product, api, robots,
rating}. **Gesucht wird nur im passenden Fach.** Kontext ist thread-lokal — der
Runner nutzt 5 Threads auf *einem* Fetcher, ein gemeinsamer Zustand würde
Einträge unter dem falschen Shop ablegen. Werkzeug: `cache_tool.py`.

---

## 8. Werkzeuge

```bash
python run.py --render                  # voller Lauf
python audit.py --render                # jeden Adapter prüfen
python cache_tool.py --drop --shop x    # Cache gezielt verwerfen
python verify_links.py                  # Links stichprobenartig prüfen
python check_robots.py                  # robots.txt je Shop
python geocode_standorte.py             # Standorte ergänzen
```

**`audit.py` ist das wichtigste Werkzeug.** Es prüft jeden Adapter gegen
Invarianten (doppelte URLs, Preis ≤ 0, UVP < Preis, >95 % Rabatt, kein
Streichpreis, Laufradgrößen als Rahmengrößen, alles ausverkauft, Zubehör-Anteil).
Vor jedem Vertrauen in einen Bericht laufen lassen.

---

## 9. Wo es als Nächstes bricht

- **Adapter hängen an fremdem CSS/JSON.** Jede Shop-Änderung kann sie leise
  brechen — Symptom ist „0 Treffer", nicht ein Fehler.
- **fahrrad-xxl-Filial-IDs** stehen im Listing-Filter; ändert der Shop sie, sind
  die Standorte falsch zugeordnet, ohne dass etwas auffällt.
- **`fit.py`-Faktoren** sind Näherungen. Bei einer neuen Rahmenform (Cargo,
  Kompakt) können sie danebenliegen.
- **Trusted-Shops-Lookup** matcht unscharf; die Domain-Prüfung muss bleiben.
- **upway `all`** ist ein Archiv. Wenn `sale` einmal wegfällt, nicht
  reflexhaft auf `all` umstellen.
- **Bericht bei >1000 Karten** wird träge (~3,4 MB HTML). Virtualisiertes
  Rendern steht im Backlog.
- **Nominatim** hat Nutzungsregeln (1 Anfrage/s). Kein Bulk-Geocoding.

Weitere Ideen: `BACKLOG.md`. Ausführliche Begründungen: `README.md`.
