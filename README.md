# E-Bike Deal Finder

Durchsucht 21 deutsche E-Bike-Shops nach Angeboten ab einem Mindestrabatt
(Standard 50 %) und listet je Treffer **Direktlink**, **Preis/UVP** und die
**verfügbaren Größen bzw. Rahmenhöhen**.

Wo ein Shop eine eigene Sale-Kategorie hat, steigt der Scraper dort ein — aber
**nicht ausschließlich**. Eine Sale-Kategorie ist die kuratierte Auswahl des
Shops, keine vollständige Liste des Reduzierten:

| Shop | Sale-Kategorie | Gesamtkategorie | zusätzliche Treffer |
|---|---|---|---|
| fahrrad24 | 89 Produkte / 41 Treffer | 474 / 72 | **+31** |
| e-bike-only | 256 / 4 | 1308 / 11 | **+7** |
| upway | 796 / 711 | 3500 / 71 | +38 |
| fahrrad-xxl | 1066 / 57 | 923 / 28 | +5 |
| denfeld, radwelt | – | – | 0 |

Bei fahrrad24 fehlte so unter anderem ein Greens Corwen F750 MTB mit 64 %
Rabatt. Wo die Lücke messbar ist, wird zusätzlich die Gesamtkategorie gescannt
(`extra_urls` bzw. eine zweite Collection); Doppelte fallen über die
Deduplizierung heraus.

**Vorsicht bei der Messung:** Eine Kategorie nach Rabatten zu vergleichen reicht
nicht, die Verfügbarkeit gehört dazu. upways `all` enthält 3500 Räder, davon
sind nur 126 lieferbar — es ist das Archiv inklusive verkaufter Räder, während
`sale` mit 796 Produkten der aktuelle Bestand ist. Nach Rabatt allein sortiert
sah `all` wie die bessere Quelle aus; der Umstieg hätte 646 echte Angebote
gekostet. Jetzt werden beide gescannt und der Ausverkauft-Filter trennt sie.

Shops ohne Sale-Filter (jobrad-loop) bekommen ein größeres Seitenbudget
(`page_budget`).

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

## Täglicher Lauf über GitHub Actions

`.github/workflows/taeglich.yml` startet den Scanner jeden Morgen um 04:00 UTC
(06:00 deutsche Sommerzeit) und lässt sich unter *Actions → Tägliche
Aktualisierung → Run workflow* auch von Hand auslösen — dort sind Mindestrabatt
und `--render` einstellbar.

**Der Preisverlauf wird ins Repository zurückgeschrieben.** Das ist keine
Bequemlichkeit, sondern Bedingung: Ein CI-Runner startet mit leerem Dateisystem,
ohne versionierte `preise.db` wäre an jedem Tag jedes Angebot „neu im Bericht“.
Deshalb ist die Datei bewusst *nicht* in `.gitignore` — und deshalb kommt auch
kein `actions/cache` in Frage, den GitHub nach sieben Tagen ohne Zugriff
abräumen darf.

*Fürs lokale Arbeiten:* vor einem eigenen Lauf `git pull`, sonst kollidiert der
lokale Stand mit dem Bot-Commit. SQLite-Dateien lassen sich nicht mergen.

### Plausibilitätsprüfung

Vor dem Zurückschreiben läuft `ci_check.py`. Ein Scraper aus einem Rechenzentrum
wird irgendwann von einem Teil der Shops abgewiesen — das Ergebnis ist dann kein
Absturz, sondern ein *kleinerer* Bericht, der aussieht wie ein ruhiger Tag. Der
Check vergleicht deshalb gegen den letzten Tag in `preise.db` und bricht ab bei:

* weniger als 50 % der Angebote des Vortages,
* mehr als 3 Shops mit Fehler,
* fehlender `deals.json`.

Der Vergleich ist selbstkalibrierend: keine feste Erwartung, nur „deutlich
weniger als gestern ist verdächtig“. Bewusst übersprungene Shops (bike24) zählen
nicht als Fehler.

### Ergebnisse

Bericht und Rohdaten liegen 30 Tage als Artefakt am jeweiligen Lauf
(*Actions → Lauf → Artifacts*).

Wer den Bericht lieber als Webseite hätte: den zweiten Job aktiviert die
Repository-Variable `PUBLISH_PAGES = true` (Settings → Variables), zusätzlich
muss unter Settings → Pages die Quelle auf „GitHub Actions“ stehen. **Bei
privaten Repositories brauchen GitHub Pages einen bezahlten Plan** — deshalb ist
der Job standardmäßig aus.

### Was der erste Lauf zeigen wird

Ob die Shops eine GitHub-Runner-IP akzeptieren, ist offen. fahrradlagerverkauf
weist schon lokal `httpx` ab und braucht den curl-Fallback; aus einem
Rechenzentrum kann das weitere Shops betreffen. Der Plausibilitätscheck fängt
den Fall ab, statt stillschweigend eine dünne Historie aufzubauen — nach dem
ersten Lauf lohnt ein Blick, welche Shops im Log Fehler melden.

Zwei weitere Eigenheiten von GitHub Actions: geplante Läufe verschieben sich
unter Last um bis zu 30 Minuten, und in Repositories ohne Aktivität werden sie
nach 60 Tagen automatisch abgeschaltet.

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
Lauf am selben Tag aktualisiert den Tageswert, statt die Reihe aufzublähen.

### Speicherformat

Zwei Speicher mit klarer Rollenverteilung:

* **`historie/YYYY-MM-DD.jsonl.xz`** ist die Wahrheit und wird versioniert —
  eine LZMA-komprimierte Datei je Lauftag (~50 KB für 1.700 Angebote), die sich
  nach dem Schreiben nie wieder ändert.
* **`preise.db`** ist nur ein daraus abgeleiteter SQLite-Index für schnelle
  Abfragen, steht in `.gitignore` und wird beim Start automatisch aus dem Archiv
  wiederhergestellt, wenn sie fehlt.

Die naheliegende Variante — die SQLite-Datei täglich committen — wäre teuer:
Sie wächst mit jedem Lauf, und Git legt bei jedem Commit eine Kopie der *ganzen*
Datei ab. Nach einem Jahr wären das rund 640.000 Zeilen, eine ~220 MB große
Datei und mehrere Gigabyte Git-Historie. Unveränderliche Tagesdateien kosten
dieselbe Information in etwa 23 MB pro Jahr.

*Geschrieben wird der Tag immer vollständig aus dem Index*, nicht nur die
Angebote des laufenden Durchgangs. Sonst hätte ein Teillauf wie
`--shop denfeld` die Tagesdatei aller Shops durch seine paar Zeilen ersetzt.

## Datensparsamkeit

Der HTTP-Cache liegt LZMA-komprimiert auf der Platte. Shop-HTML ist sehr
redundant — an 40 echten Cache-Dateien einzeln gemessen:

| Verfahren | Faktor | Komprimieren | Dekomprimieren |
|---|---|---|---|
| gzip -6 | 7,9× | 0,45 s | 0,05 s |
| **LZMA preset 1** | **10,5×** | **0,53 s** | 0,16 s |
| LZMA preset 3 | 10,9× | 0,86 s | 0,15 s |

Preset 1 ist der Punkt, an dem mehr Aufwand kaum noch etwas bringt: derselbe
Schreibaufwand wie gzip bei einem Drittel mehr Kompression. `lzma` gehört zur
Standardbibliothek, es kommt also keine Abhängigkeit dazu.

Zusätzlich räumt jeder Lauf abgelaufene Einträge weg — das tat vorher niemand,
der Cache wuchs unbegrenzt. Praktisch gemessen: **350 MB → 201 KB**.

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

## Lizenz

[MIT](LICENSE) — Nutzung, Änderung und Weitergabe frei, auch kommerziell.

Zwei Hinweise für alle, die das Projekt forken:

* **Die Adapter sind an fremde Shops gebunden.** Deren Markup ändert sich ohne
  Vorwarnung. `audit.py` prüft jeden Adapter gegen Plausibilitätsregeln — vor
  dem Vertrauen in einen Bericht bitte laufen lassen.
* **`preise.db` enthält abgeschöpfte Preisdaten.** Einzelne Preisbeobachtungen
  sind Fakten und nicht urheberrechtlich geschützt, aber das EU-weite
  Datenbankherstellerrecht (§ 87b UrhG) schützt wesentliche Teile fremder
  Produktdatenbanken. Wer die Datei weiterverwendet oder das Projekt in großem
  Stil betreibt, sollte das im Blick behalten. Die MIT-Lizenz deckt den Code,
  nicht die damit erhobenen Fremddaten.

## Grenzen

* Preise und Verfügbarkeit ändern sich laufend – der Bericht ist eine
  Momentaufnahme.
* Listenpreise sind teils „ab“-Preise für die günstigste Variante.
* jobrad-loop verkauft **refurbished** Räder; der Rabatt bezieht sich auf die
  Neupreis-UVP. Zustand und Laufleistung stehen am Angebot.
