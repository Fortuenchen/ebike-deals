# EbikeDeals Preisalarm — Firefox-Build

Firefox-Variante des Preisalarm-Plugins. **Code identisch** zu `../browser-plugin/`
(background.js, popup.*, deals.*, icons) — einziger Unterschied ist die
`manifest.json`:

- Hintergrund über `background.scripts` (Firefox-Event-Page) statt
  `service_worker`.
- `strict_min_version` 115 (MV3 mit Event-Page).

Die geteilten Skripte greifen über `const api = globalThis.browser ||
globalThis.chrome` auf die WebExtension-APIs zu, laufen also in Firefox
(promise-basiertes `browser.*`) wie in Chrome.

## Installieren (Firefox)

Temporär (zum Testen):
1. `about:debugging#/runtime/this-firefox`
2. **Temporäres Add-on laden…** → die `manifest.json` in *diesem* Ordner wählen.

Dauerhaft installieren geht nur signiert (über addons.mozilla.org bzw. eine
selbst signierte XPI) — für den Eigengebrauch reicht die temporäre Ladung.

## Funktion & Bedienung

Siehe [`../browser-plugin/README.md`](../browser-plugin/README.md): pollt
`preisalarm.json`, meldet neue Neuware-Angebote über der Schwelle (Standard
66 %), Popup mit Einstellungen, „Alle Preisalarm-Deals“-Fenster.
