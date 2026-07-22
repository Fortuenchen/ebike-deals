# UI-Backlog

Ideen für den HTML-Bericht, nach Nutzen/Aufwand sortiert.

**Umgesetzt:** Shop-Chips einzeln an-/abwählbar · Volltextsuche (UND-verknüpft
über Titel, Marke, Shop, Zustand, Größen, Akku) · Sortierung nach Rabatt,
Preis ↑/↓, Ersparnis, Akkukapazität, größtem Preisrückgang · Preis von/bis ·
Rahmengrößen-Filter (Buchstaben einzeln, Zentimeter in 5-cm-Gruppen, ODER) ·
Körpergröße gegen die empfohlenen Bereiche · Akku von/bis in Wh ·
„Angebote ohne passende Angabe ausblenden“ mit Ausweis der Betroffenen ·
„Nur Neuware“ · Filterzustand in der URL (teilbar, übersteht Neuladen) ·
Preisverlauf mit Tiefstpreis-Markierung und Sparkline · Trefferzähler mit
`aria-live` · `/`-Shortcut · Hell/Dunkel automatisch.

Der Bericht ist bewusst eine einzelne, in sich geschlossene HTML-Datei ohne
externe Abhängigkeiten. Punkte, die das aufgeben würden, sind markiert.

---

## Hoher Nutzen, kleiner Aufwand

### 1. Exakte Wh statt Untergrenzen bei upway
96 % der Angebote haben eine Akku-Information, aber 669 davon nur als
Untergrenze (`≥ 600 Wh`), weil upway in Schwellen taggt. Ein Filter „bis
700 Wh“ kann damit nichts anfangen. Die Produktseite nennt womöglich den
exakten Wert — für 669 Angebote wären das 669 zusätzliche Abrufe, also nur
sinnvoll mit Cache und Budget.

*Nebenbefund:* upway vergibt die Schwellen kumulativ (300+/400+/500+/600+).
Wenn das durchgängig stimmt, wäre die höchste Schwelle zugleich eine
Obergrenze — `400+` hieße dann 400–499 Wh. Das ist plausibel, aber nicht
belegt; der Code behandelt es deshalb bewusst nur als Untergrenze. Ein Abgleich
gegen ein paar Produktseiten würde die Frage klären.

### 2. Leerer Zustand mit Ausweg
Statt nur „Keine Treffer“: die restriktivste aktive Bedingung nennen und einen
Knopf „Suche zurücksetzen“ anbieten.

### 3. Barrierefreiheit nachziehen
`aria-pressed` und `aria-live` sind gesetzt. Offen: sichtbarer Fokusring auf
den Chips (nicht nur auf Feldern), `prefers-reduced-motion`, und eine
Ankündigung beim Sortierwechsel.

---

## Mittlerer Aufwand

### 7. Tabellenansicht als Alternative
Umschalter Karten ⇄ kompakte Tabelle (Shop, Modell, Preis, UVP, Rabatt,
Größen). Bei 300+ Treffern ist Scannen in einer Tabelle deutlich schneller.

### 8. Marken-Filter
Chips oder Mehrfach-Dropdown aus `brand`. Die Marke steckt schon im Datenmodell,
wird aber in der UI nirgends als Filter angeboten.

### 9. Gleiches Rad bei mehreren Shops zusammenfassen
Modelle über normalisierten Titel + Jahr gruppieren und die Shop-Preise
nebeneinander zeigen. Der eigentliche Mehrwert eines Multi-Shop-Scanners —
bislang stehen Duplikate unverbunden nebeneinander.
*Heikel: Titel-Normalisierung ist fehleranfällig, lieber konservativ gruppieren
und im Zweifel getrennt lassen.*

### 10. Merkliste
Sterne-Icon je Karte, Ablage in `localStorage`, eigener Filter „nur gemerkte“.

### 11. Diff zum letzten Lauf
Vorherige `deals.json` einlesen und Karten als „neu“ / „Preis gefallen“
markieren. Macht wiederholte Läufe erst richtig nützlich.

### 12. Export
CSV-Download der aktuell gefilterten Auswahl und ein Print-Stylesheet.

### 13. Tastaturnavigation
`j`/`k` durch die Karten, `Enter` öffnet das Angebot, `Esc` leert die Suche
(schon da). Passt zum bereits vorhandenen `/`-Shortcut.

---

## Größerer Aufwand / Grundsatzentscheidungen

### 14. Virtualisiertes Rendern
Ab ~1000 Karten wird das DOM träge. Nur den sichtbaren Bereich rendern.
Erst nötig, wenn die Trefferzahl deutlich wächst.

### 15. Bild-Lazyload mit Platzhaltern
`loading="lazy"` ist gesetzt, aber ohne Skeleton — beim Scrollen springt das
Layout. Feste Seitenverhältnisse plus Platzhalterfläche.

### 16. Preisverlauf ausbauen
Die Basis steht (`preise.db`, Tiefstpreis, Sparkline). Offen: ein Filter
„nur Angebote, die seit dem letzten Lauf günstiger wurden“, ein Detail-Popover
mit der vollen Preistabelle, und eine Aufräumroutine für Angebote, die seit
Monaten nicht mehr auftauchen.

### 17. Mobile Feinschliff
Sticky Filterleiste, Filter als Bottom-Sheet, größere Touch-Ziele.
Die Karten sind responsiv, die Filterleiste wird auf kleinen Displays aber lang.

### 18. Manueller Theme-Umschalter
Aktuell folgt der Bericht dem System. Ein Dreiklang Hell/Dunkel/System mit
`localStorage` ist erwartbar — Aufwand gering, Nutzen aber auch.

---

## Bewusst nicht vorgesehen

* **Frontend-Framework / Build-Schritt.** Der Bericht soll eine Datei bleiben,
  die per Doppelklick funktioniert — auch offline und in fünf Jahren noch.
* **Externe CDNs für Fonts, Icons, Charts.** Gleicher Grund; außerdem lädt
  sonst jeder Berichtsaufruf bei Dritten nach.
* **Endloses Nachladen.** Der Bericht ist eine Momentaufnahme; Paginierung
  gehört auf die Scraper-Seite, nicht in die Anzeige.
