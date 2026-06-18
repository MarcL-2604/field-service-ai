# FieldServiceAI – Projektstatus
**Stand:** 27. März 2026
**Umgebung:** Python 3.12 · Pydantic v2 · pandas · pytest
**Scope:** 14 Außendienst-Servicetechniker · Medtronic Deutschland · Prototyp

---

## 1. Fertige Module, Tests, Features

### Codebase-Übersicht

| Datei | LOC | Beschreibung |
|---|---|---|
| `techniker/models.py` | 126 | Kerndatenmodell: `Techniker`, `Trainingsmatrix`, `Qualifikationslevel`, `Auslastung` |
| `techniker/loader.py` | 81 | CSV/Excel-Loader für SMax-Exporte |
| `techniker/scoring.py` | 470 | Scoring-Engine: Kompetenz · Fahrzeit · Auslastung · ArbZG-Checks |
| `auftraege/models.py` | 75 | `Auftrag`, `AuftragsTyp`, `AuftragsStatus`, `Dokument`, `DokumentTyp` |
| `auftraege/dispatcher.py` | 288 | Fälligkeiten aus geraete.csv · Zuweisung · Benachrichtigungs-Dict |
| `auftraege/kv_pruefung.py` | 60 | KV-Pflicht-Logik für Repair-Aufträge |
| `auftraege/abschlusskontrolle.py` | 70 | Pflichtdokumente je Auftragstyp (STK/PM/Repair) |
| `auftraege/workflow.py` | 470 | **Empfehlungssystem** – `empfehlung_generieren()` → `EmpfehlungsReport` |
| `reporting/crosstraining_analyse.py` | 443 | Crosstraining-Bedarfsanalyse für alle 14 Techniker |
| `reporting/dashboard.py` | 604 | HTML-Dashboard-Generator |
| `tests/test_techniker_models.py` | 85 | 16 Tests für Kerndatenmodell |
| `tests/test_scoring.py` | 315 | 37 Tests für Scoring-Engine + ArbZG |
| `tests/test_auftraege.py` | 825 | 106 Tests für Auftrags-Lifecycle + Workflow |
| **Gesamt** | **3.920** | |

### Testabdeckung: 159 Tests · 0 Fehler

| Testklasse | Tests | Bereich |
|---|---|---|
| `TestEmpfehlungGenerieren` | 26 | Workflow: Empfehlungssystem |
| `TestPflichtdokumentePruefen` | 14 | Abschlusskontrolle |
| `TestBerechne_Dringlichkeit` | 12 | Dringlichkeitsstufen |
| `TestBerechneEmpfehlung` | 12 | Scoring-Engine |
| `TestAuftragBenachrichtigen` | 9 | Dispatcher-Benachrichtigung |
| `TestWochenstunden` | 8 | ArbZG-Wochenlimits |
| `TestQuartalZuDatum` | 7 | Quartal-Parsing |
| `TestNaechsteFaelligeAuftraege` | 7 | Dispatcher-Fälligkeiten |
| `TestKvErforderlich` | 7 | KV-Schwellwert-Logik |
| `TestAuftragModel` | 7 | Pydantic-Validierung |
| `TestTagesstunden` | 6 | ArbZG-Tageslimits |
| `TestKvBestaetigen` | 5 | KV-Bestätigung |
| `TestAuftragZuweisen` | 5 | Dispatcher-Zuweisung |
| `TestEmpfehlungsReportDatenklassen` | 4 | Report-Datenklassen |
| `TestTrainingsmatrix` | 4 | Qualifikationsmatrix |
| `TestQualifikationslevel` | 4 | Level-Enum |
| `TestFreitag` | 4 | ArbZG-Freitagsregel |
| `TestTechniker` | 3 | Techniker-Modell |
| `TestWochenende` | 3 | Wochenend-Ausschluss |
| `TestPausenpflicht` | 3 | ArbZG §4 |
| `TestMindestruhezeit` | 3 | ArbZG §5 |
| `TestDokument` | 3 | Dokumentmodell |
| `TestAuslastung` | 3 | Kapazitätsmodell |
| **Gesamt** | **159** | |

### Implementierte Features im Detail

**Techniker-Scoring** (`techniker/scoring.py`)
- Score-Formel: Kompetenz × 0,40 + Fahrzeit × 0,35 + Auslastung × 0,25
- Haversine-Entfernungsberechnung (Luftlinie → Fahrzeit-Schätzung mit Umwegfaktor 1,35)
- Hugo-Regel: ausschließlich L3, keine Ausnahmen
- ArbZG-Checks: Wochen-Max 45 h · Tages-Max 10 h · Mindestruhezeit 11 h (§5) · Pausenpflicht (§4) · Freitags-Sperre für STK/PM
- Warnlevel-System: PUFFER (≥ 38 h) · GELB (≥ 42 h) · AUSSCHLUSS (> 45 h)

**Empfehlungssystem** (`auftraege/workflow.py`)
- `empfehlung_generieren(auftrag)` → `EmpfehlungsReport` mit Top-3 Technikern
- Status bleibt garantiert `NEU` – keine automatische Zuweisung, per `assert` abgesichert
- Dringlichkeit: KRITISCH · HOCH · NORMAL · NIEDRIG (konfigurierbare Tagesschwellen)
- Begründungen pro Techniker: Kompetenz · Nähe · Auslastung · Hinweise
- Ersatzteile-Schätzliste pro Produktfamilie (13 Familien hinterlegt)
- Letzte-Wartung-Schätzung aus STK-Zyklus rückgerechnet
- Hugo-Zertifizierungs-Hinweis bei Hugo-Aufträgen

**Crosstraining-Analyse** (`reporting/crosstraining_analyse.py`)
- Analysiert alle 14 Techniker gegen regionales STK-Volumen
- Produktfamilien-Mapping: 15 geraete.csv-Typen → 13 Trainingsmatrix-Familien
- Klinik → Bundesland-Auflösung über kliniken.csv + Stadtname-Heuristik (70+ Stichworte)
- Ausgabe: `daten/crosstraining_empfehlungen.csv`
- Befund: T3 (Thüringen/Sachsen/Brandenburg) ohne Crosstraining-Partner – strukturelle Lücke

**HTML-Dashboard** (`reporting/dashboard.py`, `reporting/dashboard.html`)
- Qualifikations-Ampel: 3 GRÜN · 6 GELB · 5 ROT (von 14 Technikern)
- Ampel-Metrik: L3-qualifizierte Familien / regionale Familien
- Nächste 10 STK-Aufträge mit farbcodierten Dringlichkeits-Badges
- Crosstraining-Top-5 nach ungenutztem STK-Potenzial
- NRW-Überlastungs-Warnung (bei ≥ 2 ROT-Technikern + > 800 STK/a kombiniert)

**Daten-Infrastruktur**
- 82 Kliniken in `kliniken.csv` – alle mit GPS-Koordinaten in `scoring.py` hinterlegt
- 561 Gerätzeilen in `geraete.csv` · 103 Kliniken · 15 Produktfamilien
- 53 Trainingsmatrix-Einträge · 14 Techniker · 13 Produktfamilien
- 5 Hugo-Standorte korrekt erfasst (UKE, Lübeck, Bochum, Dresden, Ulm)

---

## 2. Was der Demo-Run zeigt

```
python reporting/crosstraining_analyse.py   → daten/crosstraining_empfehlungen.csv
python reporting/dashboard.py               → reporting/dashboard.html
```

**Crosstraining-Demo** (3 kritischste Techniker):

| Techniker | Standort | L3-Familien | Lücken | Zusatz-STK/a | Partner |
|---|---|---|---|---|---|
| T2 | Wehingen | Navigation (1) | 9 | +664 | T10 |
| T8 | Hennef | Neurophysiologie (1) | 9 | +527 | T10 |
| T13 | Meckenheim | Kardiovaskulaer_Ablation (1) | 9 | +498 | T10 |

**Empfehlungs-Demo** (`empfehlung_generieren()` für 3 nächste STK-Aufträge):

- UKE Hamburg · Kardiovaskulaer (EC300_Legend): Nur 2 Kandidaten gefunden. T5 (Oberhausen, 316 km, L3) als einzige eigenständige Option – Fahrzeit-Warnung (> 8 h Tag). Zeigt reale Versorgungslücke für Hamburg/Kardiovaskulaer.
- Uniklinik Bonn · Neuromonitoring (NIM4CM01): T5 mit Score 90,7 (84 km, L3, Heimregion NRW). Sauberste Empfehlung im Demo.
- Uniklinik Bonn · Kardiovaskulaer (AEX): Score-Formel korrekt beobachtbar – T8 (13 km, L2, Score 78,5) verliert gegen T5 (84 km, L3, Score 90,3): Kompetenz-Gewicht (40 %) schlägt Fahrzeitvorteil.

**NRW-Warnung ausgelöst:** T8 + T13 (je 1 L3-Familie) · 1.025 STK/Jahr nicht abdeckbar · Crosstraining-Empfehlung: T10 als Partner für beide.

---

## 3. Offene Punkte für Produktivbetrieb

### 3.1 Echtzeit-Anbindung ServiceMax (SMax)

**Aktuell:** Alle Daten sind statische CSV-Dateien. Techniker-Auslastung wird in `TagesStatus` manuell übergeben oder fehlt (Default: 0 h).

**Benötigt für Produktion:**
- SMax-API-Anbindung für Auftragsstatus und Technikerplanung (Modul: `auftraege/smax_connector.py`)
- Polling oder Webhook für Echtzeit-`TagesStatus`-Updates pro Techniker
- Schreibzugriff auf SMax: Auftragszuweisung nach manueller Bestätigung rückschreiben
- Authentifizierung (OAuth2/API-Key) und Fehlerbehandlung bei SMax-Ausfall
- `loader.py` bereits auf SMax-Spaltennamen vorbereitet (`Resource_ID`, `Territory_Zips` etc.) – Adapter-Logik fehlt

### 3.2 Historien-Modul (letzte Wartungen)

**Aktuell:** `letzte_wartung` im `EmpfehlungsReport` ist eine Rückrechnung aus `STK-Zyklus - 1 Jahr`. Keine echte Wartungshistorie. Techniker-ID der letzten Wartung: immer `None`.

**Benötigt für Produktion:**
- Modul `ersatzteile/` ist leer – Stücklisten und Reparaturhistorie fehlen komplett
- Historien-Tabelle pro Klinik + Gerät: wer hat wann gewartet, welche Teile verbaut
- Daraus: "Hat dieses Gerät schon gewartet" – derzeit hart als Hinweis gesetzt
- Offene Punkte aus Vorwartungen (Mängel, Austausch geplant) – aktuell immer leere Liste
- SMax enthält diese Daten in `Work Order History` – braucht Extrakt und Mapping

### 3.3 Kundenkontakt-Daten aus SMax

**Aktuell:** `kundenkontakt` im Report enthält nur Klinikname + generierte SMax-URL. Kein Ansprechpartner, keine Telefonnummer, keine E-Mail.

**Benötigt für Produktion:**
- `kliniken.csv` hat kein Kontaktfeld – Erweiterung nötig oder SMax-Live-Abfrage
- Typischerweise: MTM-Verantwortlicher + OP-Koordinator je Klinik
- Für Hugo-Standorte: zusätzlich Einweisungskoordinator (Pflicht vor Einsatz)
- Modul-Erweiterung: `auftraege/dispatcher.py → auftrag_benachrichtigen()` gibt `smax_kontakt_url` zurück – Zielsystem soll direkten Kontakt liefern

### 3.4 GPS-Koordinaten für alle Kliniken

**Aktuell:** Alle 82 Kliniken aus `kliniken.csv` haben GPS-Koordinaten in `techniker/scoring.py` hinterlegt (manuelle Lookup-Tabelle nach PLZ). Stand: vollständig.

**Risiken in Produktion:**
- Neue Kliniken → `ValueError` in `berechne_empfehlung()` wenn PLZ nicht in `_KLINIK_COORDS`
- Gastroenterologische Praxen und MVZ in `geraete.csv` sind **nicht** in `kliniken.csv` – kein Scoring für diese Standorte möglich
- 103 Kliniken in `geraete.csv` vs. 82 in `kliniken.csv` = 21 Kliniken ohne korrekte Zuordnung
- Lösung: Geocoding-Service (z. B. Nominatim/HERE) statt statischer Tabelle; `_KLINIK_COORDS` als Cache

### 3.5 Kalender-Integration (kritische Abhängigkeit)

**Aktuell:** Auslastungsdaten sind Schätzwerte (Default 0 h). `tages_status` in `workflow.py` ist als Parameter vorbereitet, wird aber nie mit Echtdaten befüllt. Das Dashboard zeigt "keine Echtzeit-Daten" bei Auslastung.

**Benötigt für echte Auslastungsberechnung:**
- **SMax Work Order Kalender** – gebuchte Einsätze pro Techniker (geplante Stunden, Fahrtzeit, Auftragstyp)
- **Microsoft Graph API (Outlook)** – Urlaub, Krankheitstage, interne Termine, Schulungen
- Ohne beide Quellen bleibt Auslastung = Schätzwert, nicht Echtzeit
- Basis: 32 h/Woche effektiv (Mo–Do), Freitag = Home Office / Büroarbeit

**Technischer Anknüpfungspunkt:**
- `auftraege/workflow.py`: `empfehlung_generieren(tages_status=...)` nimmt `dict[str, TagesStatus]`
- `techniker/models.py`: `TagesStatus` hat Felder `geleistete_stunden`, `geplante_auftraege`
- `techniker/scoring.py`: Auslastungs-Score nutzt `TagesStatus` wenn vorhanden, sonst Default 0 h
- Integration: Adapter-Modul `auftraege/kalender_connector.py` (noch nicht angelegt) soll SMax + Graph zusammenführen und `tages_status`-Dict liefern

---

## 4. Technische Schulden

### Was ist Beispieldaten – was wäre echte Produktion

| Datei / Feld | Aktueller Stand | Produktionsdaten |
|---|---|---|
| `daten/geraete.csv` | Schätzwerte aus Stichproben-Listen (Kommentar in Zeile 1–4) | SMax-Export `Installed Base` mit echten Seriennummern und Gerätestatus |
| `daten/trainingsmatrix.csv` | 14 fiktive Techniker (T1–T14) mit plausiblen Qualifikationen | Echter SMax-Export `Resource Skills` mit 25 Technikern |
| `daten/techniker.csv` | Standorte plausibel, aber fiktive Personen | SMax `Resource` mit echten Names, Telefon, E-Mail, PLZ-Gebieten |
| `daten/kliniken.csv` | 82 reale Kliniken, Adressen korrekt | + Kontaktpersonen, Zugangsdaten, Hugo-Einweisungsstatus |
| `naechste_stk_faellig` in geraete.csv | Quartalsformat `2025-Q1` bis `2026-Q4` – alle 2025er Daten sind 450 Tage überfällig | Echtes Datum aus SMax `Next PM Date` (ISO 8601) |
| `daten/regionen.csv` | Einsatzgebiete als Bundesland-Listen (manuell gepflegt) | SMax `Territory` mit PLZ-Bereichen |
| Auslastung / `TagesStatus` | Default 0 h – kein Echtzeit-Status | SMax `Schedule Board` live abgefragt |
| Ersatzteil-Schätzliste in `workflow.py` | 13 Produktfamilien mit Platzhalter-Teilenamen | Echte SAP/SMax-Stücklisten aus `ersatzteile/` (noch leer) |
| GPS-Koordinaten in `scoring.py` | Manuelle Tabelle nach PLZ (82 Einträge) | Geocoding-Service oder SMax-Klinik-Stammdaten |
| Hugo-Standorte | 5 Standorte korrekt (UKE, Lübeck, Bochum, Dresden, Ulm) | Laufend aktuell halten bei Rollout-Erweiterung |

### Architekturelle Schulden

**Produktfamilien-Mapping ist doppelt gepflegt.**
`reporting/crosstraining_analyse.py` und `auftraege/dispatcher.py` pflegen beide `GERAET_ZU_TRAINING`. Sollte in eine zentrale `config.py` oder `daten/produkt_mapping.csv` ausgelagert werden.

**Kein Persistenz-Layer.**
`empfehlung_generieren()` nimmt ein `Auftrag`-Objekt – es gibt keine Datenbank. Aufträge, die aus `naechste_faellige_auftraege()` kommen, existieren nur im Arbeitsspeicher. Für Produktion: SQLite oder PostgreSQL mit SQLAlchemy; Auftrag-ID dann als echter Primary Key.

**Klinik-Matching ist fuzzy.**
Die Zuordnung von Kliniken in `geraete.csv` zu Kliniken in `kliniken.csv` erfolgt über normalisierten Teilstring-Vergleich. Bei identisch klingenden Klinik-Namen in verschiedenen Städten gibt es Fehlzuordnungen. Produktions-Lösung: `klinik_id` direkt im SMax-Export mitliefern.

**Schwellwerte sind hart kodiert (teilweise).**
Score-Gewichte, ArbZG-Limits und KV-Schwellwert liegen als Modul-Konstanten vor (`_W_KOMPETENZ = 0.40`, `_KV_SCHWELLWERT_EUR = 500.0`). CLAUDE.md fordert zentrale `config.py` – noch nicht umgesetzt.

**`ersatzteile/` ist leer.**
Das Modul ist in der Projektstruktur angelegt und wird im Empfehlungsbericht als "in Entwicklung" ausgewiesen. Jedes `ersatzteile_schaetzung`-Ergebnis ist eine Schätzliste aus `workflow.py`, nicht aus echten Stücklisten.

---

## Zusammenfassung

```
Status:  Prototyp – alle drei Kernfunktionen implementiert und getestet
Tests:   159 / 159 grün
Code:    3.920 LOC (ohne Testdaten)
Daten:   Beispieldaten, keine echten Medtronic-Daten

Nächster Schritt:  SMax-API-Anbindung (Echtzeit-Auslastung + Historien)
Kritischste Lücke: ersatzteile/ (leer) und Persistenz-Layer
```
