# EbikeDeals Preisalarm — Browser-Plugin

Desktop-Benachrichtigung, sobald bei einem Aktualisierungslauf ein **neues
Neuware-Angebot über 66 % Rabatt** auftaucht. Dazu ein Fenster mit **allen**
Angeboten des Alarm-Feeds.

## Wie es funktioniert

Die tägliche Pipeline veröffentlicht nach jedem Lauf einen schlanken Feed
`preisalarm.json` (nur **Neuware** — kein refurbished/gebraucht/Testbike — ab
60 %, ~15 KB). Das Plugin pollt ihn im Hintergrund (Standard: alle 120 min):

- Ein Angebot gilt als **neu**, wenn seine URL dem Alarm noch nicht begegnet ist.
  Beim **ersten** Lauf nach der Installation wird nur eine Baseline gesetzt (kein
  Spam) — gemeldet werden erst danach neu auftauchende Angebote.
- Gemeldet werden nur Angebote **über der eingestellten Schwelle** (Standard
  66 %, im Popup 30–95 % einstellbar). Neuware ist durch den Feed garantiert.
- Klick auf die Benachrichtigung öffnet das Angebot. Das Icon-Badge zeigt, wie
  viele Angebote aktuell über der Schwelle liegen.

Der Feed ist die einzige Datenquelle — kein Tracking, keine weiteren Rechte als
Lesezugriff auf `fortuenchen.github.io`.

## Installieren

**Chrome / Edge**
1. `chrome://extensions` öffnen, **Entwicklermodus** einschalten.
2. **Entpackte Erweiterung laden** → diesen Ordner (`browser-plugin/`) wählen.

**Firefox** — eigener Build (Event-Page-Manifest) unter
[`../browser-plugin-firefox/`](../browser-plugin-firefox/):
1. `about:debugging#/runtime/this-firefox`
2. **Temporäres Add-on laden…** → `browser-plugin-firefox/manifest.json` wählen.

Der Code (background.js, popup.\*, deals.\*, icons) ist in beiden Builds identisch
und über `globalThis.browser || globalThis.chrome` browserneutral.

## Bedienung

- **Icon anklicken** → Popup: Alarm an/aus, Mindestrabatt, Prüfintervall,
  „Jetzt prüfen“, und die aktuell qualifizierenden Angebote.
- **„Alle Preisalarm-Deals →“** → Fenster mit **jedem** Angebot aus
  `preisalarm.json` (Suche, Typ-Filter E-Bike/Fahrrad, Rabatt-Untergrenze,
  Sortierung).

## Voraussetzung

`preisalarm.json` muss auf der Seite liegen. Es entsteht bei jedem Pipeline-Lauf
(`tools/merge_report.py --alarm …`) und wird von `taeglich.yml` mit
veröffentlicht. Nach dem ersten Lauf mit dieser Änderung ist der Feed unter
`https://fortuenchen.github.io/ebike-deals/preisalarm.json` erreichbar.

Feed-Untergrenze anpassen: `--alarm-min-discount` im Merge-Schritt. Die
Alarm-Schwelle (66 %) stellt das Plugin selbst.
