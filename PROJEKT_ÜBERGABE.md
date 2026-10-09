# Medtronic Field Service AI — Projekt-Übergabe

## Kontext
Ich bin Marc Liebhardt, Techniker T10 bei Medtronic GmbH Service & Repair Deutschland (Balingen).
Ich entwickle ein KI-gestütztes Field Service System als IHK KI-Manager Zertifizierungsprojekt.
Bitte setze die Arbeit an diesem Projekt fort ohne nochmal von vorne zu erklären.

## Aktueller Stand
- **516 Tests grün** (pytest, 9 Testdateien)
- **Dashboard 11/11 Prüfpunkte vollständig**
- **Projektpfad:** `C:\Projekte\FieldServiceAI`
- **Dashboard:** `C:\Projekte\FieldServiceAI\reporting\dashboard.html`
- **Claude Code** wird für Backend-Entwicklung genutzt

## Technischer Stack
- Python 3.12, Pydantic v2
- Hauptdateien: techniker/, auftraege/, reporting/, tests/
- config.py mit allen Konstanten zentral
- Scoring: Kompetenz 40% + Fahrzeit 35% + Auslastung 25% (Haversine, Faktor 1.35)

## 6 Produkt-Cluster (FINAL)
| Cluster | Familien | STK | PM | Repair | Training |
|---|---|---|---|---|---|
| SMALL_CAPITAL | NIM, PROG, ACT, IPC/EC300/AEX, Neurophysiologie | L2 | L3 | kein Feld | intern 0€ |
| SMALL_CAPITAL_MIT_REPAIR | HF_Chirurgie (Sonderfall) | L2 | L2 | L3 Pflicht | 0€ / T&E* |
| CLUSTER1_OR | Hugo, Mazor, StealthStation, O-arm | L3 | L3 | L3 | TC+10h Handon T&E* |
| CLUSTER2_CARDIAC | Affera, Arctic Front, Nitron | L3 | L3 | L3 | TC+8h Handon T&E* |
| CLUSTER3_MONITORING | Ventilation (980X1DEDRAC), Monitoring | L2 | L3 | L3 | TC+6h Handon T&E* |
| CLUSTER4_DIGITAL | Touch Surgery | L2 | L2 | — | Online/Teams |
*Kosten bei Training & Education anfragen — Platzhalter

## Hugo Key Account
- T1 (Obertshausen), T6 (Schenefeld/UKE Hamburg), T10 (Balingen/UKL Ulm), T11 (Gangelt/Bochum)
- Kapazität: 32h × 0.80 = 25.6h/Woche · 20% Reserve für Hugo-Calls
- Hugo-Einsatz = 8h · Warnung bei >80% Auslastung

## Planungslogik
- **STK/PM:** Mindestens 3 Werktage Vorlauf (Messmittel laden) · Optimal 5 Tage · 3 Terminvorschläge
- **OP-Kliniken:** Nur Mo–Mi planen (Do/Fr OP-Plan gesperrt)
- **Repair:** 48h SLA = Kundenkontakt (nicht Abschluss!) · intern 24h anstreben
- **Ersatzteile:** Sofort=1-2 Tage · Lager=1-3 Tage · Bestellen=3-10 Tage
- **Freitag:** Home Office · kein Außeneinsatz
- **Übernachtung:** Max 1/Woche · Auslöser >10h Gesamttag · +150€
- **Puffer:** Basis 30min + Einschleusung Uniklinik 20min + Grossgerät 30min + Gespräch MTech 15min
- **Synergieeffekt:** 2. Gerät gleiche Familie = 70% Zeit · Rüstzeit 30min zwischen Familien

## Techniker (14 gesamt)
T1 Obertshausen (Hugo KA, Hessen) · T2 Wehingen (BaWü-Süd) · T3 Weimar (Thüringen) ·
T4 Erlangen (Bayern-Nord) · T5 Oberhausen (NRW-West, L3) · T6 Schenefeld (Hugo KA, Nord) ·
T7 Wildenberg (Bayern-Ost) · T8 Hennef (NRW-Süd, L2) · T9 Hamburg (Nord) ·
T10 Balingen (Hugo KA, BaWü-Süd, UKL Ulm) · T11 Gangelt (Hugo KA, NRW-West) ·
T12 Frankfurt (Hessen) · T13 Meckenheim (NRW-Süd) · T14 Waldachtal (BaWü-Süd)

## Portfolio
- 1.985 Vertragsgeräte · 82 Kliniken · 15 Produktfamilien · Deutschland

## ArbZG
- Außendienst: 32h/Woche Mo–Do · Freitag Home Office
- ArbZG Maximum: 45h/Woche · Warnung ab 34h · Ausschluss ab 36h
- Hugo KA: 25.6h Ziel (80% von 32h)

## HTML-Dateien (aktuell, in outputs/)
- `FieldServiceAI_Demo_v2.html` — 8-Schritte Work Order Demo (CORS-Fix, API-Key in localStorage)
- `FieldServiceAI_Praesentation_v2.html` — 10 Folien inkl. ROI (Folie 10)
- `FieldServiceAI_Workflow_Animation.html` — 8-Schritte automatische Animation
- `Demo_Ablaufplan_Manager.docx` — 30-Minuten Regieanweisung für Manager-Demo
- `Medtronic_AI_Field_Service_Konzept_v3.2.docx` — Vollständiges Konzept
- `Antrag_Weiterbildung_Projektfreigabe.docx` — Formaler Antrag

## Demo-Navigation (8 Schritte)
s0→s1→s2→s2b→s4→s5→s6→s7
goStep IDs: ['s0','s1','s2','s2b','s4','s5','s6','s7']
Indices:      0    1    2    3     4    5    6    7

## ROI (Folie 10)
- Crosstraining: +192.000€/Jahr · Gebietsoptimierung: +29.250€/Jahr
- Admin+QA: +18.000€/Jahr · Hugo-Ausfälle: +15.000€/Jahr
- Investition: 17.590€ einmalig (Annahme, Weiterbildung + API)
- Trainingskosten: T&E anfragen (Platzhalter)
- Break-even: nicht fest behauptet — im Dashboard (Business Case) rechnerisch aus Investition / (Jahreswert/52) mit den Annahmen aus config.py (BC_*); alle Beträge sind Annahmen, im Pilot zu messen

## IHK KI-Manager
- Anbieter: DIHK-Bildungs-gGmbH · Live-Online abends · 64 UE · ca. 2.590€
- Nächste Termine: 17.08–26.11.2026 · 24.08–03.12.2026
- Projektarbeit = dieses System

## Offene Punkte / Zuletzt bearbeitet
- Demo v2 Navigation vollständig gefixt (8 Schritte, goStep ID-basiert)
- Workflow Animation läuft (Cloudflare-Fix, Script vollständig)
- Dashboard: Einstellungsbedarf-Sterne Labels als HTML rechts neben Karte (noch offen)
- Nächster Schritt: Manager-Demo vorbereiten
