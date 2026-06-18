# Field Service AI — Projektkontext für Claude Code

## 1. Projekt
KI-gestütztes Field Service Planning System
Medtronic GmbH · Service & Repair Deutschland
IHK KI-Manager Zertifizierungsprojekt · Marc Liebhardt · T10 · Balingen · Hugo Key Account

Das System hat drei Kernfunktionen:
1. **Technikerempfehlung** – Empfiehlt den optimalen Techniker für einen Serviceauftrag basierend auf Portfolio-Trainingsmatrix, Einsatzgebiet (PLZ/Region) und aktueller Auslastung.
2. **Ersatzteilempfehlung** – Empfiehlt benötigte Ersatzteile bei Repair-Aufträgen anhand von Gerätetyp und Fehlerhistorie.
3. **Crosstraining-Steuerung** – Identifiziert Trainingsbedarfe basierend auf regionalem Gerätevolumen und vorhandener Qualifikationsmatrix.

## 2. Technischer Stack
- Python 3.12 · Pydantic v2
- Hauptverzeichnis: C:\Projekte\FieldServiceAI
- Tests: pytest · aktuell 516 Tests grün · 9 Testdateien
- Dashboard: reporting/dashboard.py → reporting/dashboard.html
- Abhängigkeiten: pydantic>=2.0, pandas>=2.0, openpyxl>=3.1, pytest>=8.0, flake8>=7.0

| Bereich | Status | Details |
|---|---|---|
| `techniker/` | ✅ fertig | models.py, scoring.py, loader.py |
| `auftraege/` | ✅ fertig | models.py, dispatcher.py, kv_pruefung.py, abschlusskontrolle.py, workflow.py, tour_optimierung.py, einsatz_dauer.py, trunkstock.py, dokumente_qa.py |
| `reporting/` | ✅ fertig | crosstraining_analyse.py, dashboard.py → dashboard.html |
| `ersatzteile/` | ⚠️ leer | Platzhalter-Schätzlisten in workflow.py; echte Stücklisten fehlen |
| Daten | ⚠️ Beispieldaten | daten/ enthält plausible Stichprobendaten, keine echten Medtronic-Daten |

**Offene Punkte für Produktivbetrieb:**
1. **SMax-API** – kein `smax_connector.py`; `TagesStatus` ist Default 0 h; kein Rückschreiben von Zuweisungen
2. **Kalender-Integration (kritisch)** – Auslastung = Schätzwert ohne SMax Work Order Kalender + Microsoft Graph API (Outlook: Urlaub, Kranktage, interne Termine). `tages_status` in `workflow.py` ist vorbereitet aber nie mit Echtdaten befüllt. Basis: 32 h/Woche (Mo–Do), Freitag = Home Office.
3. **Historien-Modul** – `letzte_wartung` ist Rückrechnung aus STK-Zyklus; keine echte Wartungshistorie
4. **Kundenkontakt** – nur generierte SMax-URL; kein Ansprechpartner/Telefon in `kliniken.csv`
5. **Klinik-Coverage** – 103 Kliniken in geraete.csv vs. 82 in kliniken.csv = 21 ohne Scoring möglich

**Technische Schulden:**
- `_GERAET_ZU_TRAINING` ist in `dispatcher.py` und `crosstraining_analyse.py` doppelt gepflegt → zentralisieren
- Kein Persistenz-Layer – Aufträge existieren nur im Arbeitsspeicher

## 3. Scoring-Algorithmus
Kompetenz 40% + Fahrzeit 35% + Auslastung 25%
Haversine-Distanz × Faktor 1.35 (Realverkehr)

Score = Kompetenz x 0.40 + Fahrzeit x 0.35 + Auslastung x 0.25. GPS-Koordinaten aller 82 Kliniken in `_KLINIK_COORDS` (scoring.py).

Filtert Techniker nach Qualifikation für die Geräteklasse → bewertet nach Entfernung zum Standort → gewichtet nach Auslastung → gibt gerankte Top-3 Liste zurück.

## 4. Kapazitätsmodell
- Basis: 32h/Woche Mo–Do · Freitag = Home Office
- Hugo KA (T1/T6/T10/T11): 25.6h (80% von 32h) · 20% Reserve
- ArbZG: Warnung ab 34h · Ausschluss ab 36h · Maximum 45h
- Hugo-Einsatz: 8h · Frühwarnung >80% Auslastung

**ArbZG-Enforcement** (scoring.py): Wochenmax 45h absolut / 32h Planungsziel, Tagesmax 8h normal / 10h absolut, 11h Mindestruhezeit (§5), Pausenregeln (§4), kein Wochenende, Freitag nur für Repair-Notfälle.

**Übernachtungsregel** (scoring.py):
- Fahrzeit > 3h einfache Strecke → Übernachtung nötig
- `MAX_UEBERNACHTUNGEN_PRO_WOCHE = 1`
- Übernachtungskosten: +150 EUR Pauschale
- `TagesStatus.uebernachtungen_diese_woche` für Wochentracking
- Bei max. erreicht: Warnung "anderen Techniker wählen oder Auftrag verschieben"

## 5. 14 Techniker (Demo-Daten · konfigurierbar)
T1  Obertshausen  · Hugo KA · Hessen
T2  Wehingen      · BaWü-Süd
T3  Weimar        · Thüringen
T4  Erlangen      · Bayern-Nord
T5  Oberhausen    · NRW-West · L3
T6  Schenefeld    · Hugo KA · Nord (UKE Hamburg)
T7  Wildenberg    · Bayern-Ost
T8  Hennef        · NRW-Süd · L2
T9  Hamburg       · Nord
T10 Balingen      · Hugo KA · BaWü-Süd · UKL Ulm
T11 Gangelt       · Hugo KA · NRW-West
T12 Frankfurt     · Hessen
T13 Meckenheim    · NRW-Süd
T14 Waldachtal    · BaWü-Süd

## 6. Produkt-Cluster (Demo-Daten · erweiterbar)

Kurzübersicht:
SMALL_CAP        : NIM, PROG, ACT, IPC/EC300/AEX, Neurophys. | STK L2 · PM L3 · kein Repair
HF_CHIRURGIE     : HF-Chirurgie (Sonderfall)                  | STK L2 · PM L2 · Repair L3
CLUSTER1_OR      : Hugo, Mazor, StealthStation, O-arm         | alles L3 · TC+10h Handon
CLUSTER2_CARDIAC : Affera, Arctic Front, Nitron               | alles L3 · TC+8h Handon
CLUSTER3_MON     : Ventilation, Monitoring                    | STK L2 · PM+Repair L3
CLUSTER4_DIG     : Touch Surgery                              | alles L2 · Online/Teams

**Vollständige Produkt-Klassifizierung** (Single Source of Truth in `techniker/models.py`):

| Cluster | Familien | STK | PM | Repair | Training |
|---|---|---|---|---|---|
| **SMALL_CAPITAL** | Neuromonitoring, Programmer, ACT, Kardiovaskulaer_IPC, Neurophysiologie, Energie, Kardiovaskulaer | L2 | L3 | kein Feld-Repair | 0 EUR intern |
| **SMALL_CAPITAL_MIT_REPAIR** | HF_Chirurgie / Elektrochirurgie | L2 | L2 | **L3 Pflicht** | STK/PM 0 EUR; Repair T&E anfragen * |
| **CLUSTER1_OR** | Hugo, Wirbelsaeule/Mazor, Navigation/OArm/StealthStation | L3 | L3 | L3 | 10h Handon + T&E anfragen * |
| **CLUSTER2_CARDIAC** | Kardiovaskulaer_Ablation, Affera, ArcticFront, Nitron | L3 | L3 | L3 | 10h Handon + T&E anfragen * |
| **CLUSTER3_MONITORING** | Beatmung/Ventilation, Capnografie, Endoskopie, Gastroenterologie, Monitoring | L2 | L3 | L3 | T&E anfragen * |
| **CLUSTER4_DIGITAL** | TouchSurgery | L2 | L2 | - | Online/Teams moeglich * |

EC300/IPC = Small Capital (Kardiovaskulaer_IPC). L2 reicht fuer STK.
HF_Chirurgie = Sonderfall: STK/PM → L2 reicht (Small Capital Regel), Repair → L3 Pflicht (Trainingscenter).

Konstanten in `techniker/models.py`: `SMALL_CAPITAL`, `SMALL_CAPITAL_MIT_REPAIR`, `BIG_CAPITAL_CLUSTER1_OR`, `BIG_CAPITAL_CLUSTER2_CARDIAC`, `CLUSTER3_MONITORING`, `CLUSTER4_DIGITAL`, `STK_L2_ERLAUBT`

Funktionen: `mindest_level_fuer(produktfamilie, auftragstyp)`, `produkt_cluster(produktfamilie)`, `trainingstyp_fuer_familie(produktfamilie)`

**Trainings-Modell** (models.py + crosstraining_analyse.py):

**TrainingsTyp Enum** in `techniker/models.py`:
- `INTERN`: Small Capital, L4-Trainer im Feld, 1-3 Tage, 0 EUR
- `TRAININGSCENTER`: Big Capital + Monitoring, Medtronic Training Center + Handon
- `DIGITAL`: Software-Plattform, Online/Teams moeglich

**Hands-on Modell** (`HANDON_STUNDEN` in `techniker/models.py`):
- **Repair L3** (Hugo/CAS/Big Capital): **10h Hands-on im Feld PFLICHT** mit zertifiziertem L3-Techniker. Erst danach eigenstaendig einsetzbar.
- **PM L1→L2**: Hands-on NUR waehrend der Schulung selbst. Kein zusaetzliches Feld-Hands-on noetig.
- **PM online**: Einige PM-Schulungen via Teams moeglich.

**Kostenmodell** in `crosstraining_analyse.py` – **PLATZHALTER, NICHT VALIDIERT**:

| Cluster | Kurskosten | Hands-on | Status |
|---|---|---|---|
| INTERN (Small Capital) | 0 EUR | waehrend Schulung | validiert |
| HF-Chirurgie STK/PM | 0 EUR intern | waehrend Schulung | validiert |
| HF-Chirurgie Repair | T&E anfragen | T&E anfragen | **PLATZHALTER** |
| Cluster 1 OR | T&E anfragen | 10h Pflicht | **PLATZHALTER** |
| Cluster 2 Cardiac | T&E anfragen | 10h Pflicht | **PLATZHALTER** |
| Cluster 3 Monitoring | T&E anfragen | T&E anfragen | **PLATZHALTER** |
| Cluster 4 Digital | T&E anfragen | Online/Teams | **PLATZHALTER** |

Genaue Kosten bei Medtronic Training & Education (T&E) anfragen.
Euro-Betraege im Code sind Strukturvorlagen, nicht validiert.

**Crosstraining-Empfehlungen** zeigen: Cluster, Trainingstyp, Hands-on, Dauer, Trainer-ID

## 7. Planungsregeln
- STK/PM: min. 3 Werktage Vorlauf · optimal 5 Tage · 3 Terminvorschläge
- OP-Kliniken: nur Mo–Mi planen (Do/Fr OP-Plan gesperrt)
- Repair: 48h SLA = Kundenkontakt (nicht Abschluss!)
- Freitag: Home Office · kein Außeneinsatz
- Übernachtung: max. 1/Woche · Auslöser >10h Gesamttag
- Puffer: Basis 30min + Uniklinik 20min + Großgerät 30min + MTech 15min
- Synergie: 2. Gerät gleiche Familie = 70% Zeit · Rüstzeit 30min

**Vorausschauende Planung** (workflow.py + tour_optimierung.py):

**Kein Tages-Modus.** Aufträge werden 3–7 Werktage im Voraus geplant.

| Konstante | Wert | Bedeutung |
|---|---|---|
| `PLANUNGSHORIZONT_TAGE` | 7 | Planungsfenster: nächste 7 Werktage |
| `PLANUNGSHORIZONT_MIN` | 3 | Frühester Termin: heute + 3 Werktage |
| `VORLAUF_STANDARD_TAGE` | 5 | Empfehlung: 5 Werktage Vorlauf |

**Gründe für vorausschauende Planung:**
- Messmittel/Prüfmittel müssen 1–2 Tage vorher ins Fahrzeug geladen werden
- OP-Plan wird freitags für die nächste Woche geplant → Gerät evtl. nicht verfügbar
- Kliniken brauchen Vorlaufzeit für Raumbuchung und Einschleusung
- Techniker muss Route und Übernachtung planen
- Trunkstock-Check und Bestellung fehlender Teile

**OP-kritische Kliniken** (`op_kritisch=True` in kliniken.csv):
- Unikliniken haben Operationssäle → OP-Plan-Abhängigkeit
- Termine nur Mo/Di/Mi (Do = Pre-OP, Fr = OP-Plan wird erstellt)
- Vorlauf: mindestens 5 Werktage (statt 3)
- Kreiskrankenhäuser und Privatkliniken: `op_kritisch=False`

**Messmittel-Vorbereitung** (`PUFFER_MESSMITTEL_LADEN = 30min` in einsatz_dauer.py):
- Wird NICHT in Einsatzdauer eingerechnet
- Separate Info: "Vortag: Messmittel laden (~30 min)"

**API:** `schlage_termine_vor(auftrag, techniker_id, tages_status, heute)` → `list[TerminVorschlag]`

## 8. Einsatzdauer & Puffer (einsatz_dauer.py)

Quelle: Historische SMax-Daten in `daten/labor_zeiten.csv` (aktuell Platzhalter-Schätzwerte).
Für Produktivbetrieb: SMax API Anbindung nötig → automatisch aktualisierte Zeiten.

**Fallback-Kaskade:**
1. Exakter Match: techniker_id + geraete_typ → technikerspezifische Zeit
2. Familien-Durchschnitt: Mittelwert aller Techniker für diese Produktfamilie
3. Standard-Fallback: 90min Service + 30min Admin = 120min

**Synergieeffekt:** Mehrere Geräte gleicher Familie → erstes Gerät volle Zeit, jedes weitere 70% (`SYNERGIE_FAKTOR = 0.70`).

**Rüstzeit:** Wechsel zwischen verschiedenen Produktfamilien: +30min (`RUESTZEIT_FAMILIE_WECHSEL_MIN`).

**Tagesmax:** `MAX_EINSATZ_DAUER_MIN = 360` (6h) — bei Überschreitung wird `ueberschreitet_max` gesetzt.

**Pufferzeit-Logik** (realistisch fuer Klinikalltag — Puffer ist kein Fehler, sondern Realitaet):
- Basis-Puffer: +30min je Einsatz (Parkplatz, Orientierung, Unvorhergesehenes)
- Klinik-Typ: Uniklinikum +20min, Gross/Mittel +10min (Einschleusung, Hygieneschleuse)
- Grossgeraet: Hugo/EC300/O-arm +30min (komplexer Aufbau) — einmalig pro Einsatz
- Gespraechsbedarf: Standard +15min, Erstbesuch +30min, nach Complaint +45min

**Ziel: 0 Ueberstunden durch realistische Planung.**

Dashboard-Anzeige: "Netto Xh + Puffer Yh = Geplant Zh" mit aufklappbaren Puffer-Details.

**Integration:** `tour_optimierung._standard_einsatzdauer()` verwendet labor_zeiten.csv + Puffer statt Pauschalwerte. `buendle_mit_qualifikation()` berechnet echte Dauern pro Techniker.

API: `berechne_einsatz_dauer(geraete_liste, techniker_id, klinik_id, klinik_groesse, gespraech_typ)` → `EinsatzDauer`

## 9. Repair-Aufträge & SLA (workflow.py + trunkstock.py + models.py)

**Repair ≠ STK/PM.** Eigene Reaktionszeit-Logik, getrennt von Vorausplanung.

| Konstante | Wert | Bedeutung |
|---|---|---|
| `REPAIR_SLA_STUNDEN` | 48 | Kundenkontakt-Pflicht innerhalb 48h |
| `REPAIR_ZIEL_KONTAKT` | 24 | Internes Ziel: Kontakt in 24h |

**Planungstyp** (`PlanungsTyp` Enum in models.py):
- `VORAUSPLANUNG`: STK/PM → 3–7 Tage Vorlauf
- `REAKTIONSPLANUNG`: Repair → 48h SLA

**Repair-Phasen** (`RepairPhase` Enum in models.py):
1. **Eingang** → Techniker zuweisen, SLA-Timer startet
2. **Kontakt ausstehend** → Techniker muss Klinik anrufen (SLA: 48h)
3. **Kontakt hergestellt** → Fehler aufgenommen, SLA-Timer stoppt
4. **Ersatzteil prüfen** → Trunkstock / Lager checken
5. **Ersatzteil bestellt** → Warte auf Lieferung
6. **Ersatzteil verfügbar** → Termin nach Verfügbarkeit planen
7. **Repair in Arbeit** → Einsatz läuft
8. **Abgeschlossen**

**SLA-Eskalation** (`bewerte_repair_sla()` in workflow.py):
- < 24h: GRÜN — innerhalb Ziel
- ≥ 24h ohne Kontakt: GELB — "Kundenkontakt steht aus"
- ≥ 40h ohne Kontakt: ROT — "SLA-Gefährdung! Noch 8h"
- ≥ 48h ohne Kontakt: KRITISCH — "SLA VERLETZT — sofort eskalieren" + automatische Disponent-Benachrichtigung
- Kontakt hergestellt: GRÜN (SLA erfüllt)
- Ersatzteil unterwegs: BLAU

**Ersatzteil-Verfügbarkeit** (`pruefe_ersatzteil_verfuegbarkeit()` in trunkstock.py):
- `SOFORT`: Teil im Fahrzeug → Einsatz in 1–2 Tagen
- `LAGER`: Teil im Zentrallager → 1–3 Tage Lieferzeit
- `BESTELLEN`: Teil extern bestellen → 3–10 Tage
- `UNBEKANNT`: Fehler unklar → Diagnose vor Ort nötig

**Repair-Besonderheiten:**
- SLA 48h = Kundenkontakt, nicht Reparaturabschluss
- Ersatzteil-Verfügbarkeit bestimmt Einsatztermin
- Kein Mindest-Vorlauf wie bei STK/PM (auch 1-2 Tage möglich)
- OP-kritische Geräte: Reparatur nach OP-Plan abstimmen

**APIs:**
- `bewerte_repair_sla(auftrag, jetzt)` → `RepairSlaBewertung`
- `repair_kontakt_herstellen(auftrag, techniker_id)` → `RepairSlaBewertung`
- `repair_einsatz_planen(auftrag, verfuegbarkeit)` → `date`
- `pruefe_ersatzteil_verfuegbarkeit(techniker_id, produktfamilie)` → `ErsatzteilStatus`

## 10. Tour-Optimierung (tour_optimierung.py)

**Klinik-Bündelung (einfach):** Mehrere STK/PM in derselben Klinik im selben Monat → ein Einsatz.
- Gesamtdauer = Summe Einzelzeiten + 30min Rüstzeit pro Zusatzgerät
- API: `buendle_auftraege(auftraege)` → `list[GebueindelterEinsatz]`

**Klinik-Bündelung mit Qualifikations-Check:**
- Prüft ob ein Techniker alle Geräte einer Klinik/Monat-Gruppe abdeckt
- Konstanten: `SMALL_CAPITAL_L2_REICHT` (NIM, PROG, ACT, IPC), `BIG_CAPITAL_L3_PFLICHT` (Hugo, Navigation, Wirbelsaeule, Energie)
- `MAX_EINSATZ_DAUER_STD = 6h`
- Entscheidungsbaum:
  - **Fall A**: Ein Techniker deckt alle Geräte ab → ein Einsatz
  - **Fall B**: Kein einzelner Techniker reicht → Aufteilung nach Qualifikationsgruppen (mehrere Einsätze am selben Tag)
  - **Fall C**: Teilüberschneidung → breitestes Portfolio zuerst gewählt
- API: `buendle_mit_qualifikation(auftraege)` → `list[QualifizierterBuendelPlan]`

**Tour-Optimierung:** Geografisch nahe Kliniken (< 50km Radius) zu Tagestouren bündeln.
- Techniker startet von Wohnort, fährt 2-3 nahe Kliniken, kehrt zurück
- Maximiert Onsite-Zeit, minimiert Fahrzeit
- Berücksichtigt 32h Wochenlimit, 8h Tagesmax
- API: `optimiere_tagestouren(auftraege, techniker_id)` → `list[Tagestour]`

## 11. Hugo Key Account (techniker_typ = HUGO_KEY_ACCOUNT)

8 klinisch installierte Systeme (Vertrag + aktiver Servicebetrieb):

| Klinik | Systeme |
|---|---|
| Universitätsklinikum Hamburg-Eppendorf (UKE) | 4 |
| Uniklinikum Lübeck | 1 |
| Klinikum Bochum | 1 |
| Städtisches Klinikum Dresden | 1 |
| Universitätsklinikum Ulm | 1 |

Stuttgart (Katharinenhospital): kein klinisches Gerät – Demo/kein Vertrag, nicht in Serviceplanung aufnehmen.

Hugo-Regel: Nur Techniker mit Qualifikationslevel L3 (SELBSTSTAENDIG) dürfen Hugo-Aufträge übernehmen. Keine Ausnahmen.

| Techniker | Standort | Hugo-Standort | Systeme |
|---|---|---|---|
| T1 | Obertshausen | TBD Hessen | – |
| T6 | Schenefeld | UKE Hamburg | 4 |
| T10 | Balingen | Uniklinikum Ulm | 1 |
| T11 | Gangelt | Klinikum Bochum | 1 |

**Key Account Regeln:**
- Hugo-Einsätze = 8h pro Einsatz (Ganztag, komplex)
- 20% Kapazitätsreserve für ungeplante Hugo-Calls → effektive Außendienstkapazität: 32h × 0.80 = 25.6h/Woche
- Bei STK/PM-Einsätzen: normale Scoring-Logik, aber reduzierte Kapazitätsbasis
- Bei Hugo-Einsätzen: höchste Priorität, kein Freitag
- Warnung wenn Hugo Key Account für einfache STK verplant wird während Kapazität > 80%

## 12. Terminverschiebung (workflow.py)

Techniker kann in SMax Go Status setzen: `TERMIN_VERSCHIEBEN`
- Gründe (`VerschiebungsGrund` Enum):
  - `KLINIK_NICHT_ERREICHBAR`: Zugang verweigert → nächster freier Slot
  - `GERAET_NICHT_VERFUEGBAR`: Gerät nicht verfügbar → nächster freier Slot
  - `EIGENE_VERHINDERUNG`: Krank/Urlaub/Überlastet → nächster freier Slot
  - `OPPLAN_KONFLIKT`: Gerät wird in OP benötigt → frühestens übernächste Woche, Klinik wird automatisch als `op_kritisch` markiert
  - `MESSMITTEL_FEHLT`: Prüfmittel nicht verfügbar → heute + 3 Werktage, Trunkstock-Warnung
  - `SONSTIGES`: Freitext
- System plant automatisch neu → nächstbester freier Slot (Mo-Do)
- Neuer Termin per Mail an Techniker + Klinik
- Ursprünglicher Termin wird in Historie gespeichert
- Max 2 Verschiebungen pro Work Order (`MAX_VERSCHIEBUNGEN_PRO_AUFTRAG`) → dann Warnung + Eskalation
- API: `termin_verschieben(auftrag, grund, neuer_termin)` → `VerschiebungsErgebnis`

## 13. Design-System (für alle HTML-Dateien)
Hintergrund : #000810
Primär      : #0072CE
Akzent      : #00A3E0
Frost       : #6EC6FF
Erfolg      : #00875A · Text #5EDD9F
Warnung     : #FF8B00 · Text #FFB347
Kritisch    : #CC0000 · Text #FF8080
Demo-Gold   : #FFD060
Cards       : rgba(255,255,255,.03) · border 1px solid rgba(255,255,255,.09)
Nav         : rgba(0,8,20,.85) · backdrop-filter blur(28px)
Font Body   : Plus Jakarta Sans (Google Fonts)
Font Head   : Syne (Google Fonts)
Grain       : SVG noise · opacity 2.5% · position fixed · mix-blend-mode overlay

## 14. Wichtige Regeln (IMMER einhalten)
- KEINE erfundenen Eurobeträge → immer "T&E anfragen"
- Demo-Daten immer mit goldenem Badge kennzeichnen
- Trainingskosten: immer "T&E anfragen" — nie Pauschalbeträge
- Framing: Marc hat Prototyp eigeninitiativ entwickelt
  VOR formaler KI-Ausbildung — dieses Framing beibehalten
- Neuron7 (N7) in Manager-Dokumenten NICHT namentlich nennen

## 15. Passwortschutz (alle HTML-Dateien)
Hash : 037453db72fb8a93ebe48d4ff52b1b493cdf56ef6a28240a65c6055b76d8f360
Key  : fsa_auth (sessionStorage)

## 16. GitHub Pages (Live-URL)
https://marcl-2604.github.io/field-service-ai/
Dateien: index.html · demo.html · animation.html · dashboard.html

## 17. ROI / Business Case
- KEINE festen Eurobeträge
- Berechnungslogik zeigen: "14 × [Einsparung h/Woche] × 52 × [Stundensatz €]"
- Investition: IHK ~2.590 € + Claude API (T&E anfragen)
- Break-even: nach Pilotphase messen

## 18. Automatisierter Workflow (7 Schritte)
1. Auftrag einlesen    → Auto  (SMax Go täglich)
2. KI-Scoring          → Auto  (Kompetenz/Fahrzeit/Auslastung)
3. Bestätigung         → Mensch (Disponent bestätigt)
4. Techniker-Info      → Auto  (Push + Mail)
5. PM Due-Date         → Auto  (5 Tage Vorlauf)
6. TD-Prüfung          → Auto  (Vollständigkeit + Version)
7. Kundenmail          → Auto  (Serviceberichte)

## 19. Projektstruktur

```
FieldServiceAI/
├── config.py        # Zentrale Konfiguration – alle Schwellwerte, Gewichtungen, Konstanten
├── techniker/       # Technikerprofile, Trainingsmatrix, Qualifikationen, Einsatzgebiete
├── auftraege/       # Auftragsverarbeitung, Zuweisung, Priorisierung (STK/PM/Repair)
├── ersatzteile/     # Ersatzteilempfehlung, Stücklisten, Reparaturhistorie
├── reporting/       # Auswertungen, Dashboards, Crosstraining-Berichte
├── daten/           # Rohdaten, SMax-Exporte, Referenzdaten (PLZ, Regionen, Gerätekatalog)
└── tests/           # Alle Tests (inkl. test_config.py fuer Konsistenzpruefung)
```

## 20. Entwicklungskommandos

```bash
# Abhängigkeiten installieren
pip install -r requirements.txt

# Tests ausführen
pytest tests/

# Einzelnen Test ausführen
pytest tests/test_<modul>.py::test_<funktion> -v

# Linting
flake8 . --max-line-length=120
```

## 21. SMax-Integration

Daten kommen als CSV/Excel-Exporte aus ServiceMax. Einlesepfad: `daten/`. Spaltennamen folgen dem SMax-Schema (englisch). Transformationslogik liegt im jeweiligen Modul, nicht in `daten/`.

## 22. Konventionen

- Sprache im Code: Englisch (Variablen, Funktionen, Klassen)
- Kommentare und Dokumentation: Deutsch erlaubt, Englisch bevorzugt
- Konfiguration (Schwellwerte, Gewichtungen) zentral in `config.py` im Projektroot. Neue Konstanten immer in config.py anlegen, Module importieren daraus.
- Alle Datumswerte als `datetime`-Objekte, keine Strings in der Verarbeitung
- Pydantic v2 für alle Datenmodelle
- Tests: `pytest tests/` — 516 Tests, alle grün. Einzeltest: `pytest tests/test_<modul>.py::test_<funktion> -v`
- Python 3.12, Abhängigkeiten: pydantic>=2.0, pandas>=2.0, openpyxl>=3.1, pytest>=8.0, flake8>=7.0

## 23. Offene Aufgaben
- [ ] SMax Go API-Anbindung (nach Pilotfreigabe)
- [ ] Outlook Kalender Integration (Auslastung live)
- [ ] Dashboard DE/EN vollständig übersetzen
- [ ] GitHub Pages: alle 4 Dateien aktuell halten
- [ ] `_GERAET_ZU_TRAINING` zentralisieren (doppelt in dispatcher.py + crosstraining_analyse.py)
- [ ] Persistenz-Layer einführen (Aufträge nur im Arbeitsspeicher)
- [ ] Klinik-Coverage: 103 vs. 82 Kliniken abgleichen
- [ ] Ersatzteile-Modul mit echten Stücklisten befüllen
