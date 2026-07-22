# E-Bike Deal Finder

Durchsucht 21 deutsche E-Bike-Shops nach Angeboten ab einem Mindestrabatt
(Standard 50 %) und listet je Treffer **Direktlink**, **Preis/UVP** und die
**verfügbaren Größen bzw. Rahmenhöhen**.

Wo ein Shop eine eigene Sale-Kategorie hat, steigt der Scraper dort ein statt
im Gesamtkatalog — weniger Requests, weniger Rauschen. Shops ohne Sale-Filter
(jobrad-loop) bekommen dafür ein größeres Seitenbudget (`page_budget`).

## Start

```bash
python run.py                          # ≥50 %, alle Shops, bericht.html
python run.py -d 65 --open             # ≥65 %, Bericht direkt öffnen
python run.py -s bikeexchange -s boc24 # nur einzelne Shops
python run.py --json deals.json        # zusätzlich Rohdaten als JSON
python run.py --cache .cache           # HTTP-Cache für schnelle Wiederholung
python audit.py                        # jeden Adapter auf Plausibilität prüfen
```

## Bericht

Der HTML-Bericht ist eine einzelne, in sich geschlossene Datei:

* **Shops einzeln an-/abwählbar** — jeder Chip schaltet nur seinen Shop,
  „Alle Shops abwählen/auswählen“ als Umschalter
* **Volltextsuche** über Titel, Marke, Shop, Zustand, Größen, Akku und
  Hinweise; mehrere Wörter sind UND-verknüpft („cube bosch“). `/` fokussiert
  das Feld, `Esc` leert es
* **Sortierung** nach Rabatt, Preis auf-/absteigend, Ersparnis in €,
  Akkukapazität oder größtem Preisrückgang
* **Preis von/bis** als Zahlenfelder
* **Rahmengrößen-Filter**: Buchstabengrößen einzeln, Zentimeterangaben in
  5-cm-Gruppen (`50-54cm`) — mehrere Größen sind ODER-verknüpft
* **Körpergröße** in cm, geprüft gegen die empfohlenen Bereiche der Shops
* **Akku von/bis** in Wh
* **„Angebote ohne passende Angabe ausblenden“** — siehe unten
* **Nur Neuware** blendet refurbished, Testbikes und Leasingrückläufer aus
* **Filterzustand in der URL** — die Adresse ist teilbar und übersteht ein
  Neuladen. Ein Link setzt beim Öffnen genau den Zustand des Absenders; nicht
  genannte Filter werden zurückgesetzt, nicht mit dem eigenen vermischt
* Trefferzähler, Hell/Dunkel nach Systemeinstellung

### Umgang mit fehlenden und unscharfen Angaben

Nicht jeder Shop nennt jede Eigenschaft, und manche nennen sie nur ungefähr.
Drei Abstufungen, die im Bericht unterschieden werden:

| Fall | Beispiel | Anzeige | Verhalten beim Filtern |
|---|---|---|---|
| exakt | `625 Wh` | `625 Wh` | normal geprüft |
| Untergrenze | upway taggt `600+ Wh` | `≥ 600 Wh` | erfüllt „ab 600“, aber nie eine Obergrenze |
| geschätzt | Rahmen 54 cm → 163–192 cm | Zähler weist es aus | nur mit aktivem Haken |
| fehlt | — | — | sichtbar, sofern nicht strikt gefiltert |

Eine Untergrenze von `400+ Wh` beweist bei einem Filter „ab 600 Wh“ **nichts** —
weder dass das Rad passt, noch dass es nicht passt. Solche Angebote laufen als
„keine Angabe“, nicht als Ausschluss.

Filtert man auf ein Feld, das ein Angebot gar nicht angibt, wäre stilles
Wegfiltern die falsche Antwort — dann sähe der Filter strenger aus, als er
belegt ist.

Deshalb bleiben Angebote ohne die betreffende Angabe standardmäßig sichtbar,
und die Trefferzeile sagt, wie viele das sind: *„412 von 1614 Angeboten · 87
davon ohne Angabe dazu“*. Wer das nicht will, setzt den Haken **„Angebote ohne
passende Angabe ausblenden“**.

### Rahmengröße und Körpergröße

Zwei Systeme, die nicht dasselbe meinen: **Rahmengröße** (S/M/L, 54 cm) kommt
von Shops mit Größenvarianten, **Körpergröße** (165–175 cm) von
Refurbished-Shops, die Einzelräder verkaufen. Ohne Brücke erreicht ein
Körpergrößen-Filter nur die eine Hälfte des Katalogs.

`fit.py` schätzt deshalb aus einer Rahmengröße, welche Körpergrößen sie bedient
(Haken **„Rahmengröße mitprüfen (geschätzt)“**). Rechenweg: Rahmenhöhe ≈
Schrittlänge × 0,66, Schrittlänge ≈ Körpergröße × 0,47 — ein Trekkingrahmen ist
also grob Körpergröße × 0,31, ein MTB-Rahmen × 0,26.

Entscheidend ist die **Einheit**, nicht der Produkttitel: Shops geben
Trekking- und Cityrahmen in Zentimetern an, MTB-Rahmen in Zoll. Nach dem Titel
zu gehen ging schief — ein „54 cm“-Rahmen an einem Rad namens „Stereo Hybrid
Fully“ wurde als MTB gelesen und landete bei 205–211 cm Körpergröße.

Die Schätzung ist bewusst großzügig (54 cm → 163–192 cm): Wer eine Stufe
danebenliegt, hat eine Anpassungsfrage, keinen Grund, das Angebot gar nicht zu
sehen. Der Trefferzähler weist geschätzte Treffer getrennt aus, und ohne den
Haken zählen sie als „keine Angabe“.

Weitere Ideen stehen in [BACKLOG.md](BACKLOG.md).

## Shop-Bewertungen

Jeder Shop wird mit seiner Bewertung verlinkt – in der Quellentabelle
ausführlich, auf jeder Angebotskarte kompakt (`TS 4,86`).

**Trusted Shops** betreibt eine öffentliche, schlüsselfreie API. Der Shop-Name
wird über `/rest/public/v2/shops.json?url=…` aufgelöst, die Note kommt aus
`/quality/reviews.json`. 10 der 21 Shops haben ein Profil.

Dabei sind zwei Fallen abgefangen, die sonst **fremde Bewertungen** an einen
Shop hängen:

* Der Lookup matcht unscharf. `www.bike24.de` liefert „MEGA Bike“, `fahrrad.de`
  ein *gelöschtes* Profil von `ps-fahrrad.de`. Die zurückgegebene Domain muss
  deshalb exakt mit der angefragten übereinstimmen — das verhindert drei
  Fehlzuordnungen.
* Ein Shop kann mehrere Profile je Markt haben: jobrad-loop hat ein deutsches
  (4,33) und ein niederländisches mit anderer Note. Es gewinnt `targetMarketISO3
  = DEU`.

**Trustpilot** beendet seine robots.txt mit `User-agent: * / Disallow: /`.
Namentlich genannte Crawler dürfen, diese Anwendung gehört nicht dazu, und sich
als einer auszugeben wäre eine Falschangabe darüber, wer anfragt. Es wird
deshalb **keine Note abgerufen**. Verlinkt wird nur, wo der Shop sein
Trustpilot-Profil selbst auf der Seite ausweist — das belegt zugleich, dass es
existiert (4 Shops).

Wer Trustpilot-Noten sehen will, trägt sie selbst ein: aus
`bewertungen_manuell.beispiel.json` eine `bewertungen_manuell.json` machen.
Manuelle Werte überschreiben abgerufene und sind im Tooltip als solche
gekennzeichnet.

Die Noten werden in `bewertungen.json` zwischengespeichert und wöchentlich
erneuert (`--ratings`, `--no-ratings`).

## Preisverlauf

Jeder Lauf schreibt Preis und UVP je Angebot in eine SQLite-Datei
(`preise.db`, abschaltbar mit `--no-history`). Ab dem zweiten Lauf zeigt jede
Karte:

* **neu im Bericht** — diese URL war vorher nie da
* **▼/▲ Betrag seit …** — Veränderung gegenüber dem letzten Lauf
* **Tiefstpreis** — günstiger als je zuvor beobachtet
* eine kleine Sparkline ab drei Datenpunkten (Inline-SVG, keine Bibliothek)

Das ist der einzige Teil, der einer Rabattangabe widersprechen kann: „60 % unter
UVP“ sagt nichts darüber, ob der Referenzpreis kurz vorher angehoben wurde — eine
Reihe echter Verkaufspreise schon. Der erste Lauf hat naturgemäß noch keine
Historie; dort ist alles „neu im Bericht“.

Gelesen wird immer *vor* dem Schreiben, sonst stünde der heutige Preis schon in
der Tabelle und jedes Angebot wäre automatisch auf „Tiefstpreis“. Ein zweiter
Lauf am selben Tag überschreibt den Tageswert, statt die Reihe aufzublähen.

Einzige Pflichtabhängigkeit ist `httpx` (`pip install -r requirements.txt`).
HTML wird mit einem eigenen Mini-DOM auf Basis der Standardbibliothek geparst.
`playwright` ist optional und nur für `--render` nötig (siehe unten).

## Wie der Rabatt bestimmt wird

`Rabatt = 1 − Verkaufspreis / Streichpreis`

Streichpreis ist die UVP bzw. der shopeigene Referenzpreis. Wenn ein Shop den
Rabatt selbst ausweist (`-61 %`, `(23.09 % gespart)`), wird das als Rückfallwert
genutzt, aber nie ungeprüft dem berechneten Wert vorgezogen.

Zwei Filter laufen zusätzlich:

* **Ausverkauftes wird verworfen.** Shopify behält bei ausverkauften Artikeln
  den `compare_at_price`. Ohne diesen Filter meldete boc24 207 „Treffer“, von
  denen 205 nicht kaufbar waren. Mit `--include-sold-out` wieder einschaltbar.
* **Preis-Gegenprüfung.** Weicht die Produktseite von der Liste ab, steht das
  als Hinweis am Angebot (bike-discount nennt z. B. in der Liste UVP 3.999 €,
  auf der Produktseite 3.799 €). Geprüft wird eine Stichprobe je Shop
  (`--price-check`, Standard 15) — solche Abweichungen liegen am Template des
  Shops, nicht am einzelnen Rad. Angebote **ohne** Größenangabe werden immer
  geladen, weil die Größe von der Produktseite kommen muss.

Zusätzlich wird der **Zustand** aus Titel und URL erkannt (refurbished,
Leasingrückläufer, Testbike, Vorführmodell, Lackschaden, 2. Wahl). Das ist bei
hohen Rabatten die entscheidende Information: Von 320 Treffern eines Laufs
waren nur 19 Neuräder. Der HTML-Bericht hat dafür den Filter „Nur Neuware“.

## Datenmodelle der Shops

| Shop | Technik | Preisquelle | Größen |
|---|---|---|---|
| bikemarket24, boc24, e-bike-only, fahrrad.de, upway | Shopify | `products.json`, `compare_at_price` | Varianten-Optionen |
| ebikestock | WooCommerce | Store API `prices.regular_price` / `.price` | `pa_rahmengroesse` |
| bike-angebot, denfeld, bike-discount, mhw-bike, radwelt-shop | Shopware 6 | `.list-price-price` + `.list-price-percentage` | Konfigurator-Labels |
| fahrrad24, fahrradlagerverkauf | Magento 2 | `data-price-amount` / `data-price-type` | Produktseite (`jsonConfig`) |
| fahrrad-xxl | eigenes Theme | `.fxxl-strike-price` + `.fxxl-discount` | `…__variant-slider-size-item` |
| radfieber | OXID | `.current` / `.old` | JSON-LD `ProductGroup.hasVariant` |
| rad1 | Shopware 5 | `.price--default` / `.price--discount` | Produktseite |
| nubuk-bikes | plentymarkets/Nuxt | `.product-card__price` + UVP-Spalte | – (indizierter Nuxt-Payload) |
| bikeexchange | Next.js (RSC) | `price` / `reducedPrice` in Cent | `sizes[]` **inkl. Link je Größe** |
| jobrad-loop | Next.js | `price` / `recommendedPrice` | `frame_height_manufacturer` |

### Verwendete Sale-Einstiegs-URLs

| Shop | Listing |
|---|---|
| fahrrad-xxl | `/angebote/angebote-fahrraeder/e-bike-pedelec/` (~23 Seiten statt 2.600er Katalog) |
| bike-angebot | `/hot-deals/e-bikes-im-sale` (+ Gesamtkategorie als Netz) |
| bikemarket24 | `collections/angebote-e-bike` (+ `e-bike`) |
| boc24 | `collections/e-bikes-reduziert` (+ `e-bikes`) |
| mhw-bike | `/sale/e-bikes/` + `/sale/2.-wahl/e-bikes/` |
| radwelt-shop | `/sale/e-bike-sale/` |
| e-bike-only, fahrrad.de | `collections/e-bike-sale` |
| nubuk-bikes | `/sale/e-bike-sale` |
| rad1 | `/e-bikes/` + `/sale/` (dort werden Nicht-E-Bikes herausgefiltert) |
| fahrrad24, radfieber, denfeld | hatten bereits eine Sale-Kategorie |

Ohne Sale-Filter bleiben **fahrradlagerverkauf** (der ganze Shop ist Abverkauf),
**bike-discount** (robots.txt verbietet alle URLs mit Query) und **jobrad-loop**
(`/top-deals` rendert clientseitig, die `relative_savings`-Facette existiert nur
in der internen API — dafür `page_budget = 55`).

Die reichste Quelle ist bikeexchange: der RSC-Payload enthält pro Größe einen
eigenen Direktlink. Bei jobrad-loop ist zu beachten, dass
`frame_height_manufacturer` die Rahmengröße ist – `wheel_size_*` (28") ist die
Laufradgröße und darf nicht als Größe gelten.

## lucky-bike.de: `--render`

lucky-bike gibt das Listing nur an echte Browser aus. Über normales HTTP kommt
die Filter-UI plus ein „Zuletzt gesehen“-Slider zurück, keine Produktkacheln,
und es gibt kein XHR, aus dem man die Liste stattdessen lesen könnte. Die
Produktseiten liefern zwar JSON-LD über HTTP, aber **ohne Referenzpreis** —
ohne UVP lässt sich kein Rabatt berechnen.

Mit `--render` rendert die App diese Seiten in Headless-Chromium:

```bash
pip install playwright && python -m playwright install chromium
python run.py --render
```

Ohne den Schalter wird der Shop übersprungen und im Bericht mit Begründung
ausgewiesen. Das Rendering blockiert Bilder, Medien und Schriften, hält
dieselbe Pause je Host wie der Rest der App und prüft weiterhin robots.txt.

Es wird dabei **keine Schutzmaßnahme umgangen**: keine Challenge, kein CAPTCHA,
keine vorgetäuschte Identität — Headless-Chromium *ist* eine echte
Browser-Engine, und die robots.txt des Shops erlaubt diese Pfade (nachprüfbar
mit `check_robots.py`).

## bike24.de: bewusst nicht implementiert

bike24 sitzt hinter Akamai Bot Manager. Jede Anfrage ohne gelöste Challenge
bekommt ein Interstitial, das einen Proof-of-Work berechnet und an
`/_sec/verify?provider=interstitial` sendet, um ein Freigabe-Cookie zu bekommen.

Das ist etwas grundsätzlich anderes als bei lucky-bike: Hier stellt der
Betreiber eine aktive Hürde auf, die genau den Zweck hat, automatisierte
Zugriffe auszuschließen. Sie zu lösen wäre ein Umgehen der Bot-Erkennung, und
das ist in dieser Anwendung nicht vorgesehen — unabhängig davon, wer danach
fragt.

Wer bike24-Angebote braucht: Die vorgefilterte Sale-URL steht im Bericht und
lässt sich im eigenen Browser öffnen. Für regelmäßige Auswertungen wäre der
saubere Weg eine Anfrage bei bike24 nach einem Produktdatenfeed oder
API-Zugang.

## WooCommerce

Der WooCommerce-Adapter geht nicht über HTML, sondern über die eingebaute
**Store API** (`/wp-json/wc/store/v1/products`) — schlüssellos, mit
`on_sale=true` als serverseitigem Sale-Filter, analog zu Shopifys
`products.json`. Neue WooCommerce-Shops brauchen deshalb nur noch drei Zeilen:

```python
class MeinShop(WooCommerceAdapter):
    key = "meinshop"
    name = "meinshop.de"
    base = "https://meinshop.de"
    source_url = "https://meinshop.de/e-bikes/"
```

Zwei Fallen sind im Adapter abgefangen: `pa_radgroesse` ist die **Laufrad**größe
(28" ist keine Rahmenhöhe), und die API liefert den ganzen Katalog — Ladegeräte
liegen in Kategorien wie „Elektronische Komponenten“ und würden sonst als
E-Bike durchgehen.

## Geprüft, aber nicht implementiert

| Shop | Technik | Warum offen |
|---|---|---|
| das-radhaus.de | unklar | `/ebikes/e-bike-restposten` gibt nur ~20 KB Navigation zurück |
| fahrrad-goyn.de | unklar | `/sale/` ist eine Landingpage ohne Produktliste |
| ebike24.com, e-bike.de | unklar | weder Shopify- noch WooCommerce-API |
| otto.de | Marktplatz | Sortiment von Drittanbietern, JS-Listing |

Nicht verwendbar ist **upway.co** — das ist die US-Seite mit USD-Preisen. Die
deutsche `upway.de` liefert Euro und ist eingebunden.

## robots.txt

Wird standardmäßig respektiert, und zwar **pro URL**, nicht nur für die
Einstiegsseite. Praktische Folge: bike-discount hat `Disallow: /*?`, dort ist
deshalb nur die erste Listenseite erreichbar (die gefilterte URL aus der
Aufgabenstellung wäre komplett gesperrt). Abschaltbar mit `--ignore-robots`.

`check_robots.py` zeigt den Status je Shop.

## Aufbau

```
ebikedeals/
  model.py      Offer-Datenmodell, deutsche Preis-/Größen-Parser
  htmlutil.py   Mini-DOM auf html.parser (find_all/text/own_text)
  net.py        HTTP: Drosselung je Host, Retries, Cache, Bot-Erkennung
  robots.py     eigener robots.txt-Parser (Google-Matching)
  sizes.py      Größen von der Produktseite + Preis-Gegenprüfung
  runner.py     Parallelisierung, Filter, Deduplizierung
  report.py     Konsole, JSON, HTML-Bericht
  adapters/     ein Modul je Shopsystem
```

Hilfsskripte: `smoke.py` (ein Adapter, eine Seite), `verify_links.py` (prüft,
ob alle gemeldeten Links auflösen), `check_robots.py`.

## Grenzen

* Preise und Verfügbarkeit ändern sich laufend – der Bericht ist eine
  Momentaufnahme.
* Listenpreise sind teils „ab“-Preise für die günstigste Variante.
* jobrad-loop verkauft **refurbished** Räder; der Rabatt bezieht sich auf die
  Neupreis-UVP. Zustand und Laufleistung stehen am Angebot.
