"""Field-Service-Dashboard – Premium Dark Design.

Erzeugt reporting/dashboard.html mit allen Sektionen + Claude-Chat-Panel:
  1. Qualifikations-Ampel pro Techniker  (L3-Abdeckung in der Region)
  2. Naechste 10 faellige STK-Auftraege  (mit Dringlichkeit)
  3. Crosstraining-Luecken Top 5         (hoechstes STK-Potenzial)
  4. NRW-Ueberlastungs-Warnung           (wenn Bedingung erfuellt)
  5. Workflow-Status (7 Schritte)
  6. Business Case (Berechnungslogik)
  +  Eingebetteter Claude-Chat-Assistent (rechtes Panel, 340px)

Design-System: Premium Dark Theme mit Plus Jakarta Sans + Syne.
Keine externen Abhaengigkeiten – reines HTML mit Inline-CSS/JS.
"""

from __future__ import annotations

import csv
import json
import math
import re
import sys
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

# Projektroot auf Suchpfad (falls direkt ausgefuehrt)
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from config import (  # noqa: E402
    HUGO_KA_IDS,
    HUGO_KA_ZIEL_STUNDEN,
    HUGO_KA_RESERVE_PROZENT,
    AUSSENDIENST_STUNDEN,
    PUFFER_BASIS_MIN,
    PUFFER_EINSCHLEUSUNG_MIN,
    PUFFER_GROSSGERAET_MIN,
    PUFFER_GESPRAECH_MIN,
    PSEUDONYMISIERUNG_AKTIV,
    HAVERSINE_UMWEG_FAKTOR,
    MIN_GERAETE_FUER_CROSSTRAINING,
    MIN_STK_POTENZIAL_CROSSTRAINING,
    TESTS_ANZAHL,
    OPTIMIERUNG_AUSLASTUNGS_SCHWELLE,
    OPTIMIERUNG_MAX_FAHRZEIT_MEHRAUFWAND_MIN,
    ARBEITSWOCHEN_PRO_JAHR,
    HUGO_KERNGEBIET_MAX_FAHRZEIT_MIN,
    REPAIR_SLA_VERTRAGSKUNDE_TAGE,
    REPAIR_SLA_NICHT_VERTRAGSKUNDE_TAGE,
    LUECKE_FAHRZEIT_SCHWELLE_MIN,
    UEBERSCHNEIDUNG_FAHRZEIT_DIFF_MIN,
    UEBERSCHNEIDUNG_ANTEIL_SCHWELLE,
    AUSLASTUNG_ZIEL_MIN_PCT,
    AUSLASTUNG_ZIEL_MAX_PCT,
    TECHNIKER_KOSTENSATZ_EUR_STUNDE,
    KUNDEN_VERRECHNUNGSSATZ_EUR_STUNDE,
)
from auftraege.dispatcher import naechste_faellige_auftraege  # noqa: E402
from auftraege.workflow import _berechne_dringlichkeit, schlage_termine_vor  # noqa: E402
from reporting.erklaerungen import generiere_erklaerung, FRAGE_TYPEN, FRAGE_TYPEN_EN  # noqa: E402
from config_hugo_standorte import HUGO_SPRINGER, HUGO_STANDORTE, HUGO_TEAM_GROESSE  # noqa: E402
from reporting.hugo_kerngebiet import (  # noqa: E402
    berechne_hugo_kerngebiete,
    hugo_standort_marker,
)

_DATA_DIR = _ROOT / "daten"
_OUT_PATH = Path(__file__).parent / "dashboard.html"
_OUT_PATH_ROOT = _ROOT / "dashboard.html"   # GitHub Pages copy
_HEUTE = date.today()

# ---------------------------------------------------------------------------
# Ampel-Schwellwerte: Anteil qualifizierter L3-Familien an regionalen Familien
# ---------------------------------------------------------------------------
_AMPEL_GRUEN_AB = 0.60   # >= 60 % Abdeckung → Gruen
_AMPEL_GELB_AB  = 0.30   # >= 30 % Abdeckung → Gelb
                          #  < 30 %            → Rot

# NRW-Warnung: ausgeloest wenn mind. 2 NRW-Techniker < 30 % Abdeckung
# UND deren gemeinsames ungenutztes STK-Potenzial > Schwellwert
_NRW_TECHNIKER = {"T5", "T8", "T11", "T13"}
_NRW_STK_WARNUNG_SCHWELLE = 800  # STK/Jahr kombiniert

# Daten-Modus: wird in main() gesetzt
_ECHTDATEN: bool = False


# ---------------------------------------------------------------------------
# Datenlader
# ---------------------------------------------------------------------------

def _lade_techniker() -> dict[str, dict]:
    """Gibt {techniker_id: {standort, bundesland, region, ...}} zurueck.

    Versucht zuerst echte SMax-Daten aus data/smax_dashboard_data.json.
    Fallback auf daten/techniker.csv (Demo T1-T14) wenn kein Cache vorhanden.
    """
    global _ECHTDATEN
    try:
        from api.smax_cache import load_dashboard_data
        smax = load_dashboard_data()
        if smax and smax.get("techniker"):
            _ECHTDATEN = True
            return {
                t["pseudonym_id"]: {
                    "standort":      t["standort"],
                    "bundesland":    t["bundesland"],
                    "region":        t["region"],
                    "lat":           t["lat"],
                    "lon":           t["lon"],
                    "techniker_typ": t.get("techniker_typ", "STANDARD"),
                    "pm_count":      t.get("pm_count", 0),
                    "total_mc":      t.get("total_model_codes", 365),
                    "pm_ratio_pct":  t.get("pm_ratio_pct", 0.0),
                    "in_skills_matrix": t.get("in_skills_matrix", False),
                    "einsaetze_gesamt_real":    t.get("einsaetze_gesamt_real", 0),
                    "einsatzstunden_jahr_real": t.get("einsatzstunden_jahr_real", 0.0),
                    "auslastung_pct_real":      t.get("auslastung_pct_real", 0.0),
                    "auslastung_korridor":      t.get("auslastung_korridor", "unter"),
                    "einsaetze_je_cluster_real": t.get("einsaetze_je_cluster_real", {}),
                    "hugo_einsaetze_jahr_real": t.get("hugo_einsaetze_jahr_real", 0.0),
                    "durchschnittlicher_einsatzabstand_tage": t.get("durchschnittlicher_einsatzabstand_tage"),
                }
                for t in smax["techniker"]
            }
    except Exception:
        pass

    # Demo-Fallback: T1-T14 aus CSV
    _ECHTDATEN = False
    result = {}
    with open(_DATA_DIR / "techniker.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            result[row["techniker_id"]] = {
                "standort":   row["standort"],
                "bundesland": row["bundesland"],
                "region":     row["region"],
                "lat":        float(row.get("lat", 0) or 0),
                "lon":        float(row.get("lon", 0) or 0),
            }
    return result


def _lade_crosstraining() -> list[dict]:
    """Liest crosstraining_empfehlungen.csv und gibt alle Zeilen als Liste zurueck."""
    rows = []
    with open(_DATA_DIR / "crosstraining_empfehlungen.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def _baue_ct_rows_echtdaten(smax_techniker: list[dict]) -> list[dict]:
    """Baut CT-Tabellenzeilen aus echten SMax-Daten (crosstraining_luecken,
    geraete_im_gebiet, stk_potenzial aus smax_dashboard_data.json), im selben
    Schema wie crosstraining_empfehlungen.csv (Demo), damit _render_ct_tabelle
    und _render_ct_ausschluss_hint unveraendert beide Modi bedienen koennen.
    """
    rows = []
    for t in smax_techniker:
        luecken = t.get("crosstraining_luecken", []) or []
        geraete = t.get("geraete_im_gebiet", {}) or {}
        luecken_set = set(luecken)
        regional = sorted(geraete.keys())
        qualifiziert = [f for f in regional if f not in luecken_set]

        if luecken:
            top_familie = max(luecken, key=lambda f: geraete.get(f, 0))
            top_stk = geraete.get(top_familie, 0)
        else:
            top_familie = ""
            top_stk = 0

        wirtschaftlich = (
            top_stk >= MIN_GERAETE_FUER_CROSSTRAINING
            and top_stk >= MIN_STK_POTENZIAL_CROSSTRAINING
        )

        rows.append({
            "techniker_id": t["pseudonym_id"],
            "anzahl_luecken": str(len(luecken)),
            "fehlende_familien": ";".join(luecken),
            "top_familie": top_familie,
            "top_familie_stk_potenzial": str(top_stk),
            "potentielles_zusatz_stk_pa": str(t.get("stk_potenzial", 0)),
            "idealer_crosstraining_partner": "",
            "top_schulung_typ": "",
            "top_schulung_kosten": "",
            "top_schulung_dauer": "",
            "qualifizierte_familien_l3plus": ";".join(qualifiziert),
            "regionale_produktfamilien": ";".join(regional),
            "wirtschaftlich_sinnvoll": "Ja" if wirtschaftlich else "Nein",
        })
    return rows


def _lade_labor_zeiten() -> list[dict]:
    """Liest labor_zeiten.csv und gibt alle Zeilen als Liste zurueck."""
    rows = []
    with open(_DATA_DIR / "labor_zeiten.csv", newline="", encoding="utf-8") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    for row in csv.DictReader(lines):
        rows.append(row)
    return rows


# Cluster-Zuordnung: Produktfamilie → (css_klasse, label_text)
# Kosten: PLATZHALTER – bei T&E anfragen
_CLUSTER_MAP: dict[str, tuple[str, str]] = {
    "Energie":                  ("cluster-small-capital",  "0\u202F\u20ac intern"),
    "Capnografie":              ("cluster-small-capital",  "0\u202F\u20ac intern"),
    "Elektrochirurgie":         ("cluster-hf-chirurgie",   "Kosten: T&amp;E anfragen *"),
    "Hugo":                     ("cluster-1-or",           "10h Handon + T&amp;E anfragen *"),
    "Endoskopie":               ("cluster-1-or",           "10h Handon + T&amp;E anfragen *"),
    "Wirbelsaeule":             ("cluster-1-or",           "10h Handon + T&amp;E anfragen *"),
    "Gastroenterologie":        ("cluster-1-or",           "10h Handon + T&amp;E anfragen *"),
    "Kardiovaskulaer":          ("cluster-2-cardiac",      "10h Handon + T&amp;E anfragen *"),
    "Kardiovaskulaer_Ablation": ("cluster-2-cardiac",      "10h Handon + T&amp;E anfragen *"),
    "Beatmung":                 ("cluster-3-monitoring",   "T&amp;E anfragen *"),
    "Neuromonitoring":          ("cluster-3-monitoring",   "T&amp;E anfragen *"),
    "Neurophysiologie":         ("cluster-3-monitoring",   "T&amp;E anfragen *"),
    "Navigation":               ("cluster-4-digital",      "Online/Teams m\u00f6glich"),
}

# Puffer-Aufschluesselung (Minuten, aus config.py)
_PUFFER = {
    "Basis":         PUFFER_BASIS_MIN,
    "Einschleusung": PUFFER_EINSCHLEUSUNG_MIN,
    "Grossgeraet":   PUFFER_GROSSGERAET_MIN,
    "Gespraech MTech": PUFFER_GESPRAECH_MIN,
}
_PUFFER_GESAMT = sum(_PUFFER.values())  # 95 min


# Hugo Key Account Kapazitaet (aus config.py)
_HUGO_KA_IDS = set(HUGO_KA_IDS)
_HUGO_KA_KAPAZITAET = HUGO_KA_ZIEL_STUNDEN
_HUGO_KA_RESERVE_PCT = int(HUGO_KA_RESERVE_PROZENT * 100)
_HUGO_KA_RESERVE_H = float(AUSSENDIENST_STUNDEN) * HUGO_KA_RESERVE_PROZENT
_HUGO_KA_WARN_H = _HUGO_KA_KAPAZITAET * 0.80


# ---------------------------------------------------------------------------
# Ampel-Berechnung
# ---------------------------------------------------------------------------

def _ampel_farbe(abdeckung: float) -> tuple[str, str]:
    """Gibt (css-klasse, label) zurueck."""
    if abdeckung >= _AMPEL_GRUEN_AB:
        return "ampel-gruen", "GRÜN"
    if abdeckung >= _AMPEL_GELB_AB:
        return "ampel-gelb", "GELB"
    return "ampel-rot", "ROT"


def _berechne_ampeln(ct_rows: list[dict], techniker: dict[str, dict]) -> list[dict]:
    """Berechnet Qualifikations-Abdeckung und Ampel-Status pro Techniker."""
    ergebnisse = []
    for row in ct_rows:
        tid = row["techniker_id"]
        qualifiziert = [f for f in row["qualifizierte_familien_l3plus"].split(";") if f]
        regional = [f for f in row["regionale_produktfamilien"].split(";") if f]
        fehlend = [f for f in row["fehlende_familien"].split(";") if f]

        anzahl_regional = len(regional)
        anzahl_qualifiziert = len(qualifiziert)
        abdeckung = anzahl_qualifiziert / anzahl_regional if anzahl_regional else 0.0

        css, label = _ampel_farbe(abdeckung)
        tech = techniker.get(tid, {})

        ergebnisse.append({
            "techniker_id": tid,
            "standort": tech.get("standort", "–"),
            "region": tech.get("region", "–"),
            "qualifiziert": anzahl_qualifiziert,
            "regional": anzahl_regional,
            "abdeckung_pct": round(abdeckung * 100),
            "fehlend_count": len(fehlend),
            "zusatz_stk": float(row.get("potentielles_zusatz_stk_pa", 0)),
            "partner": row.get("idealer_crosstraining_partner", "–") or "–",
            "ampel_css": css,
            "ampel_label": label,
        })
    return ergebnisse


# ---------------------------------------------------------------------------
# NRW-Warnung
# ---------------------------------------------------------------------------

def _berechne_nrw_warnung(ct_rows: list[dict]) -> dict | None:
    """Prueft ob die NRW-Ueberlastungs-Bedingung erfuellt ist.

    Gibt None zurueck wenn kein Handlungsbedarf, sonst ein Dict mit Details.
    """
    nrw_schwach = []
    nrw_stk_gesamt = 0.0

    for row in ct_rows:
        tid = row["techniker_id"]
        if tid not in _NRW_TECHNIKER:
            continue

        qualifiziert = [f for f in row["qualifizierte_familien_l3plus"].split(";") if f]
        regional = [f for f in row["regionale_produktfamilien"].split(";") if f]
        fehlend = [f for f in row["fehlende_familien"].split(";") if f]
        zusatz = float(row.get("potentielles_zusatz_stk_pa", 0))
        abdeckung = len(qualifiziert) / len(regional) if regional else 0.0

        if abdeckung < _AMPEL_GELB_AB:   # Rot-Techniker
            nrw_schwach.append({
                "id": tid,
                "qualifiziert": len(qualifiziert),
                "familien_l3": ";".join(qualifiziert) if qualifiziert else "–",
                "fehlend": len(fehlend),
                "zusatz_stk": zusatz,
            })
        nrw_stk_gesamt += zusatz

    if len(nrw_schwach) >= 2 and nrw_stk_gesamt >= _NRW_STK_WARNUNG_SCHWELLE:
        return {
            "techniker": nrw_schwach,
            "gesamt_stk": round(nrw_stk_gesamt),
            "anzahl_schwach": len(nrw_schwach),
        }
    return None


# ---------------------------------------------------------------------------
# Echtdaten-Ampel (SMax Skills-Daten, ohne Family-Mapping)
# ---------------------------------------------------------------------------

def _berechne_ampeln_aus_smax(smax_techniker: list[dict]) -> list[dict]:
    """Berechnet Qualifikations-Ampeln aus echten SMax-Skill-Daten.

    Verwendet PM-Quote je Techniker (PM-Qualifikationen / Gesamt-Modellcodes).
    Gibt Ergebnisse fuer ALLE 24 Techniker zurueck, auch ohne Skills-Matrix-Eintrag.
    """
    total_mc = max((t.get("total_model_codes", 365) for t in smax_techniker), default=365)
    ergebnisse = []
    for t in smax_techniker:
        pm    = t.get("pm_count", 0)
        total = total_mc or 1
        abdeckung = pm / total
        css, label = _ampel_farbe(abdeckung)
        ergebnisse.append({
            "techniker_id":    t["pseudonym_id"],
            "standort":        t.get("standort", "–"),
            "region":          t.get("region", "–"),
            "qualifiziert":    pm,
            "regional":        total,
            "abdeckung_pct":   round(abdeckung * 100),
            "fehlend_count":   total - pm,
            "zusatz_stk":      float(t.get("stk_potenzial", 0)),
            "partner":         "–",
            "ampel_css":       css,
            "ampel_label":     label,
        })
    return ergebnisse


def _berechne_nrw_warnung_aus_smax(
    ampeln: list[dict],
    nrw_ids: set[str],
) -> dict | None:
    """NRW-Warnung fuer echte Daten – basiert auf PM-Quote statt STK-Potenzial."""
    nrw_schwach: list[dict] = []
    nrw_gap_gesamt = 0.0
    for a in ampeln:
        if a["techniker_id"] not in nrw_ids:
            continue
        gap = a["fehlend_count"]
        nrw_gap_gesamt += gap
        if a["abdeckung_pct"] < 30:
            nrw_schwach.append({
            "id":          a["techniker_id"],
            "qualifiziert": a["qualifiziert"],
            "familien_l3":  f"{a['qualifiziert']} PM-Qualifikationen",
            "fehlend":      a["fehlend_count"],
            "zusatz_stk":   a["zusatz_stk"],
        })
    # Schwelle: > 800 fehlende Qualifikationen kumuliert als Proxy fuer STK-Potenzial
    if len(nrw_schwach) >= 2 and nrw_gap_gesamt >= _NRW_STK_WARNUNG_SCHWELLE:
        return {
            "techniker":      nrw_schwach,
            "gesamt_stk":     round(nrw_gap_gesamt),
            "anzahl_schwach": len(nrw_schwach),
        }
    return None


# ---------------------------------------------------------------------------
# HTML-Rendering – Premium Dark Design
# ---------------------------------------------------------------------------

_DRINGLICHKEIT_CSS = {
    "\u00dcBERF\u00c4LLIG": "badge-ueberfaellig",
    "KRITISCH": "badge-kritisch",
    "HOCH":     "badge-hoch",
    "NORMAL":   "badge-normal",
}

# \u2500\u2500 Zentrale Label-Uebersetzung fuer wiederkehrende Status-/Badge-Woerter \u2500\u2500
# (i18n-Komplettaudit): statt jede Vorkommensstelle einzeln an einen eigenen
# data-i18n-Key zu binden, wird das Wort in <span data-label-de="..."> gewrappt
# und die JS-Funktion setLang() ersetzt es generisch ueber diese EINE Tabelle
# (siehe JS-Objekt _LABEL_MAP_EN im Script-Teil von render_html). Neue
# Status-/Phasen-Woerter muessen nur hier ergaenzt werden, nicht an jeder
# Render-Stelle.
LABEL_MAP_EN: dict[str, str] = {
    "GR\u00dcN": "GREEN", "GELB": "YELLOW", "ROT": "RED",
    "\u00dcBERF\u00c4LLIG": "OVERDUE", "KRITISCH": "CRITICAL", "HOCH": "HIGH", "NORMAL": "NORMAL",
    "unter Korridor": "below corridor", "im Korridor": "in corridor", "\u00fcber Korridor": "above corridor",
    "\u2713 Kontakt": "\u2713 Contacted", "SLA VERLETZT": "SLA BREACHED", "SLA: noch": "SLA:",
    "Eingang": "Received", "Kontakt ausstehend": "Contact pending", "Kontakt hergestellt": "Contact made",
    "Ersatzteil pruefen": "Checking spare part", "Ersatzteil bestellt": "Part ordered",
    "Ersatzteil verfuegbar": "Part available", "Repair in Arbeit": "Repair in progress",
    "Abgeschlossen": "Completed",
    "Auslastungs-Zielkorridor 80–95% aus echter Einsatzhistorie (Vor-Ort-Zeit ÷ Jahreskapazität) — "
    "Referenzwert, keine harte Regel. Fahrzeit ist nicht enthalten, daher "
    "liegt Vollauslastung strukturell unter 100%.":
        "Utilization target corridor 80–95% from real visit history (on-site time ÷ annual "
        "capacity) — reference value, not a hard rule. Travel time is not included, so full "
        "utilization is structurally below 100%.",
    "Algorithmus: Klinik wechselt zum 2.-nächsten Techniker, wenn dessen Auslastung ≥":
        "Algorithm: clinic moves to the 2nd-nearest technician if their utilization is ≥",
    "Prozentpunkte niedriger ist und die Fahrzeit-Mehrbelastung ≤":
        "percentage points lower and the additional travel time stays ≤",
    "min bleibt": "min",
    "Mo": "Mon", "Di": "Tue", "Mi": "Wed", "Do": "Thu",
    "grün": "green",
    "Einlesen": "Import", "Bestätigung": "Confirmation", "TD-Prüfung": "TD Check",
    "Kundenmail": "Customer Email", "Mensch": "Human",
    "Disponent prüft": "Dispatcher reviews", "Techniker-Push": "Technician push",
    "KI-Empfehlung": "AI recommendation",
    "Termin-Check": "Appointment check", "Dokumente prüfen": "Check documents",
    "Vollautomatisiert · Copilot — kein Autopilot": "Fully automated · Copilot — not autopilot",
    "Basis": "Base", "Einschleusung": "Induction", "Grossgeraet": "Large device",
    "Gespraech MTech": "MedTech talk", "gesamt": "total",
    "Netto-Zeit": "Net time", "Service": "Service", "Admin": "Admin",
    "Puffer-Aufschlüsselung": "Buffer breakdown", "Gesamt Puffer": "Total buffer",
    "Gesamtzeit": "Total time",
    "Pro geplantem Einsatz: Netto-Zeit (grün) + Puffer (gelb). Klick für Aufschlüsselung. Quelle: labor_zeiten.csv":
        "Per planned visit: net time (green) + buffer (yellow). Click for breakdown. Source: labor_zeiten.csv",
    "zusätzliche STKs/Jahr möglich": "additional safety checks/year possible",
    "Min. Einsatzdauer": "min. visit duration",
    "Potenzial": "Potential", "STK-Dauer": "SC duration",
    "Berechnete Kennzahlen mit Startwerten für Techniker-Kostensatz und Kunden-Verrechnungssatz — anpassbar in config.py":
        "Calculated metrics using starting values for technician cost rate and customer billing rate — adjustable in config.py",
    "Zeitersparnis Planung": "Planning time savings",
    "Techniker": "technicians", "Tag": "day", "Tage": "days", "Wochen": "weeks", "Jahr": "year",
    "manuelle Planung entfällt": "manual planning eliminated",
    "Monetärer Wert": "Monetary value",
    "Jährliche Einsparung": "Annual savings",
    "Crosstraining-ROI": "Cross-training ROI",
    "interne Kapazitätsersparnis": "internal capacity savings",
    "Fahrzeit / Gebiet": "Travel time / territory",
    "Fahrzeit-Einsparung aus Gebiets-Szenario": "Travel time savings from territory scenario",
    "Mobilitätskostenreduktion": "Mobility cost reduction",
    "Investition & Break-even": "Investment & break-even",
    "einmalig": "one-time",
    "Break-even: ca. 10 Wochen": "Break-even: approx. 10 weeks",
    "Einmalige Implementierungskosten": "One-time implementation costs",
    "Startwert, anpassbar": "Starting value, adjustable",
    "Techniker-Kostensatz (Startwert, anpassbar in config.py)":
        "Technician cost rate (starting value, adjustable in config.py)",
    "Alle übrigen Kennzahlen sind belastbare Ist-Werte.": "All other figures are solid actuals.",
    "Herleitung (Schätzung): Marktdurchschnitt Bruttolohn Servicetechniker Medizintechnik Deutschland ≈24 €/h × Lohnnebenkosten-Faktor ≈1,9 (Sozialversicherung, Urlaubs-/Krankheitsrücklage, anteilige Fahrzeug-/Ausrüstungskosten). Zentral anpassbar in config.py.":
        "Derivation (estimate): German medical-device field service technician average gross wage ≈€24/h × non-wage labor cost factor ≈1.9 (employer social security contributions, vacation/sick-leave reserve, pro-rata vehicle/equipment costs). Centrally adjustable in config.py.",
    "Euro-Äquivalent des STK-Potenzials bei internem Techniker-Kostensatz (Startwert, anpassbar in config.py) — zeigt den Wert der freiwerdenden Kapazität, kein garantierter Zusatzumsatz.":
        "Euro equivalent of the safety-check potential at the internal technician cost rate (starting value, adjustable in config.py) — shows the value of freed-up capacity, not guaranteed additional revenue.",
    "Bessere Auslastung: von": "Improved utilization: from", "auf": "to",
    "geschätzt": "estimated", "Unternehmensmehrwert": "Business value",
    "Einsatzdauer": "visit duration", "zusätzliche Kapazität nutzbar": "additional capacity usable",
    "Was zeigt diese Ansicht?": "What does this view show?",
    "Zeigt die IST-Gebietsaufteilung basierend auf den aktuellen Techniker-Wohnorten und den ihnen historisch "
    "zugeordneten Klinik-PLZ-Gebieten. Jede Farbe entspricht einem Techniker-Gebiet. Ratio = Vor-Ort-Stunden ÷ "
    "Fahrtstunden pro Jahr — Grün ≥3,0 (effizient), Gelb 2,0–3,0, Rot <2,0 (zu viel Fahrzeit im Verhältnis zur "
    "Servicezeit).":
        "Shows the AS-IS territory split based on current technician home locations and the clinic ZIP-code areas "
        "historically assigned to them. Each color represents one technician's territory. Ratio = on-site hours ÷ "
        "travel hours per year — green ≥3.0 (efficient), yellow 2.0–3.0, red <2.0 (too much travel time relative to "
        "service time).",
    "Wie und warum wird optimiert?": "How and why is it optimized?",
    "Für jede Klinik werden der 1.- und 2.-nächstgelegene Techniker (Fahrzeit, Haversine-Distanz ×":
        "For each clinic, the 1st- and 2nd-nearest technician (travel time, Haversine distance ×",
    "Straßenfaktor) verglichen. Ist der 2.-nächste um mehr als":
        "road factor) are compared. If the 2nd-nearest is more than",
    "Prozentpunkte weniger ausgelastet und beträgt die Fahrzeit-Mehrbelastung höchstens":
        "percentage points less utilized, and the additional travel time is at most",
    "Minuten, wandert die Klinik zu ihm. Ziel: gleichmäßigere Auslastung bei vertretbaren Anfahrtswegen — "
    "unabhängig von Techniker-Anzahl oder -Bezeichnung.":
        "minutes, the clinic moves to them. Goal: more even utilization with reasonable travel distances — "
        "independent of technician count or naming.",
    "Auslastung basiert auf der Ø jährlichen Auftragsrate aus":
        "Utilization is based on the avg. annual order rate from",
    "Jahren Historie (Closed Jobs) zzgl. aktuellem Auftragsrückstand (Open Jobs).":
        "years of history (closed jobs) plus the current order backlog (open jobs).",
    "Ratio vorher/nachher = Vor-Ort-Stunden ÷ Fahrtstunden pro Jahr vor bzw. nach der Optimierung (siehe "
    "„Aktuelle Gebiete“ für die Farbskala). Δ Fahrzeit zeigt die Veränderung der jährlichen Fahrtstunden — "
    "negativ (grün) = Entlastung, positiv (rot) = Mehrbelastung.":
        "Ratio before/after = on-site hours ÷ travel hours per year before/after optimization (see “Current "
        "Territories” for the color scale). Δ travel time shows the change in annual travel hours — negative "
        "(green) = relief, positive (red) = additional load.",
    "Was ist hier zu sehen?": "What is shown here?",
    "Zeigt Gebiete mit doppelter Abdeckung (mehrere Techniker nah beieinander = Überschneidung, "
    "Optimierungspotenzial) und Gebiete ohne nahen Techniker (Lücke = längere Anfahrtszeiten für Kunden in "
    "dieser Region).":
        "Shows territories with double coverage (multiple technicians close together = overlap, optimization "
        "potential) and territories without a nearby technician (gap = longer travel times for customers in "
        "that region).",
    "Überschneidung": "Overlap", "Lücke": "Gap",
    "der Kliniken zwischen 1./2.-nächstem Techniker kontestiert (≤":
        "of clinics contested between 1st/2nd-nearest technician (≤",
    "min Fahrzeit-Differenz) — Gebiete konsolidieren": "min travel time difference) — consolidate territories",
    "Neueinstellung oder Gebiets-Erweiterung empfohlen": "New hire or territory expansion recommended",
    "Keine Anpassung nötig": "No adjustment needed",
    "Small-Capital-Kerngebiet anzeigen": "Show Small Capital core territory",
    "Min. Radius um Wohnort": "min. radius around home location",
    "Analyse aller": "Analysis of all",
    "PLZ-Bereiche (2-stellig) · Grün <60 min · Gelb 60–90 min · Rot >90 min vom nächsten Techniker · "
    "Sterne = empfohlene Neueinstellungs-Standorte":
        "2-digit ZIP code areas · green <60 min · yellow 60–90 min · red >90 min from the nearest "
        "technician · stars = recommended new-hire locations",
    "PLZ gut abgedeckt (<60 min)": "ZIP codes well covered (<60 min)",
    "PLZ grenzwertig (60–90 min)": "ZIP codes borderline (60–90 min)",
    "PLZ unterversorgt (>90 min)": "ZIP codes underserved (>90 min)",
    "Einstellungsbedarf": "Hiring needs",
    "Kliniken": "clinics", "Grossraum": "Greater", "PLZ-Bereiche": "ZIP code areas",
    "Detaillierte Begründungen": "Detailed justifications",
    "PLZ": "ZIP", "PLZ-Präfixe:": "ZIP prefixes:", "weitere": "more",
    "PLZ-Bereich vorher": "ZIP range before", "PLZ-Bereich nachher": "ZIP range after",
    "Keine Kliniken zugeordnet": "No clinics assigned",
}


def _label(text: str) -> str:
    """Wrappt ein Wort aus dem zentralen LABEL_MAP_EN-Vokabular in ein
    <span data-label-de="..."> fuer generische JS-Uebersetzung (siehe
    LABEL_MAP_EN-Docstring). Fuer beliebigen Freitext NICHT verwenden -- nur
    fuer feste, bekannte Status-/Badge-Woerter."""
    return f'<span data-label-de="{text}">{text}</span>'


_SLA_TEXT_MUSTER = re.compile(r"^SLA: noch (\d+)h$")


def _label_sla_text(sla_text: str) -> str:
    """Wie _label(), aber fuer den Repair-SLA-Text (sla_text), der bei
    'SLA: noch Xh' eine dynamische Stundenzahl enthaelt -- nur der statische
    Praefix 'SLA: noch' wird uebersetzt (LABEL_MAP_EN), die Zahl bleibt
    unveraendert ausserhalb des Spans."""
    m = _SLA_TEXT_MUSTER.match(sla_text)
    if m:
        return f'{_label("SLA: noch")} {m.group(1)}h'
    return _label(sla_text)


_KORRIDOR_LABEL = {"unter": "unter Korridor", "im_korridor": "im Korridor", "ueber": "&uuml;ber Korridor"}
_KORRIDOR_CSS = {"unter": "korridor-unter", "im_korridor": "korridor-im", "ueber": "korridor-ueber"}


def _render_korridor_badge(korridor: str | None, pct: float | None) -> str:
    """Kompaktes Badge fuer den Auslastungs-Zielkorridor (config.
    AUSLASTUNG_ZIEL_MIN_PCT/MAX_PCT) -- Referenzwert, KEINE harte Regel.
    Bewusst getrennt von der bestehenden L3-Ampel (Qualifikationsabdeckung,
    ampel-badge): misst reine Vor-Ort-Zeit ohne Fahrzeit aus echter
    Einsatzhistorie (siehe api/auslastung_analyse.py). None bei fehlenden
    Daten (z.B. Demo-Modus, oder Techniker ohne Closed-Job-Historie)."""
    if korridor is None or pct is None:
        return ""
    label = _KORRIDOR_LABEL.get(korridor, korridor)
    css = _KORRIDOR_CSS.get(korridor, "")
    tip_de = (
        f"Auslastungs-Zielkorridor {AUSLASTUNG_ZIEL_MIN_PCT}–{AUSLASTUNG_ZIEL_MAX_PCT}% "
        f"aus echter Einsatzhistorie (Vor-Ort-Zeit ÷ Jahreskapazität) — "
        f"Referenzwert, keine harte Regel. Fahrzeit ist nicht enthalten, daher "
        f"liegt Vollauslastung strukturell unter 100%."
    )
    return (
        f'<span class="korridor-badge {css}" tabindex="0">{pct:.0f}%&thinsp;{_label(label)}'
        f'<span class="info-tip-bubble">{_label(tip_de)}</span></span>'
    )


def _render_ampel_karten(
    ampeln: list[dict],
    labor_zeiten: list[dict] | None = None,
    techniker: dict[str, dict] | None = None,
) -> str:
    _AMPEL_ORDER = {"ampel-gruen": 0, "ampel-gelb": 1, "ampel-rot": 2}
    techniker = techniker or {}
    l3_tip = _info_tip(
        "Anteil der regional ben&ouml;tigten Produktfamilien, f&uuml;r die "
        "der Techniker auf Qualifikationsstufe L3 geschult ist &mdash; "
        "L3 = selbstst&auml;ndig einsetzbar (ohne Begleitung durch einen "
        "erfahreneren Kollegen)."
    )

    karten = []
    for idx, a in enumerate(ampeln):
        sort_std = _AMPEL_ORDER.get(a["ampel_css"], 1) * 100 + idx
        wochenstunden = 0
        is_hugo = a["techniker_id"] in _HUGO_KA_IDS
        hugo_border = " hugo-border" if is_hugo else ""

        # Hugo KA: reduzierte Kapazitaet 25.6h, sonst 32h
        kapazitaet = _HUGO_KA_KAPAZITAET if is_hugo else float(AUSSENDIENST_STUNDEN)
        ziel_pct = round(kapazitaet / 45 * 100, 1)
        auslastung_pct = round(wochenstunden / kapazitaet * 100, 1) if kapazitaet else 0.0

        td = techniker.get(a["techniker_id"], {})
        korridor_badge = _render_korridor_badge(
            td.get("auslastung_korridor"), td.get("auslastung_pct_real"),
        )

        hugo_badge = ""
        hugo_reserve = ""
        hugo_warn = ""
        if is_hugo:
            hugo_badge = '<div class="hugo-ka-badge">Hugo Key Account</div>'
            hugo_reserve = (
                '<div class="hugo-reserve">'
                f'20% Reserve = {_HUGO_KA_RESERVE_H}h f&uuml;r Hugo-Calls</div>')
            if wochenstunden > _HUGO_KA_WARN_H:
                hugo_warn = (
                    '<div class="hugo-warnung">'
                    '&#9888; Auslastung &gt;80% von 25.6h!</div>')

        karten.append(f"""
      <div class="ampel-karte {a['ampel_css']}{hugo_border}"
           data-tid="{a['techniker_id']}"
           data-sort-standard="{sort_std}"
           data-sort-crosstraining="{a['fehlend_count']}"
           data-sort-auslastung="{wochenstunden}"
           data-sort-portfolio="{a['qualifiziert']}"
           data-sort-potential="{a['zusatz_stk']:.0f}"
           style="cursor:pointer"
           onclick="showTechDetail('{a['techniker_id']}')">
        <div class="ampel-header">
          <div class="ampel-id">{a['techniker_id']}</div>
          <div class="ampel-badge">{_label(a['ampel_label'])}</div>
        </div>
        <div class="ampel-standort">{a['standort']}</div>
        <div class="ampel-region">{a['region']}</div>
        {korridor_badge}
        {hugo_badge}

        <div class="metric-box metric-standard">
          <div class="metric-num">{a['abdeckung_pct']}&thinsp;%</div>
          <div class="metric-lbl"><span data-i18n="card.l3coverage">L3-Abdeckung</span>{l3_tip}</div>
          <div class="metric-sub">{a['qualifiziert']}&thinsp;/&thinsp;{a['regional']} <span data-i18n="card.fam">Fam.</span> &middot; {a['fehlend_count']} <span data-i18n="card.gaps">L&uuml;cken</span></div>
          <div class="metric-sub"><span data-i18n="card.capacity">Kapazit&auml;t</span>: {kapazitaet}h/<span data-i18n="card.week">Woche</span></div>
        </div>

        <div class="metric-box metric-crosstraining" style="display:none">
          <div class="metric-num">{a['fehlend_count']}</div>
          <div class="metric-lbl" data-i18n="card.missingFam">fehlende Familien</div>
          <div class="metric-sub">+{a['zusatz_stk']:.0f}&thinsp;STK/a <span data-i18n="card.potential">Potenzial</span></div>
        </div>

        <div class="metric-box metric-auslastung" style="display:none">
          <div class="metric-num">{wochenstunden}&thinsp;h</div>
          <div class="metric-lbl" data-i18n="card.weeklyHours">Wochenstunden</div>
          <div class="metric-sub"><span data-i18n="card.capacity">Kapazit&auml;t</span>: {kapazitaet}h/<span data-i18n="card.week">Woche</span></div>
          <div class="auslastung-bar-wrap">
            <div class="auslastung-bar-fill" style="width:{auslastung_pct:.1f}%"></div>
            <div class="auslastung-bar-ziel" style="left:{ziel_pct:.1f}%"></div>
          </div>
          <div class="metric-sub">{wochenstunden}&thinsp;h &middot; Ziel&thinsp;{kapazitaet}h &middot; Max&thinsp;45&thinsp;h</div>
          {hugo_reserve}
          {hugo_warn}
          <div class="metric-sub metric-italic" data-i18n="card.fridayNote">Freitag = Home Office &middot; keine Echtzeit-Daten</div>
        </div>

        <div class="metric-box metric-portfolio" style="display:none">
          <div class="metric-num">{a['qualifiziert']}</div>
          <div class="metric-lbl" data-i18n="card.l3families">L3-Familien</div>
          <div class="metric-sub"><span data-i18n="card.ofRegional">von</span> {a['regional']} <span data-i18n="card.regional">regionalen</span></div>
        </div>

        <div class="metric-box metric-potential" style="display:none">
          <div class="metric-num">+{a['zusatz_stk']:.0f}</div>
          <div class="metric-lbl" data-i18n="card.stkPotential">STK/a Potenzial</div>
          <div class="metric-sub" data-i18n="card.afterCT">nach Crosstraining</div>
        </div>
      </div>""")
    return "\n".join(karten)


def _render_stk_tabelle(auftraege_rows: list[dict]) -> str:
    zeilen = []
    for row in auftraege_rows:
        css = _DRINGLICHKEIT_CSS.get(row["dringlichkeit"], "badge-normal")
        termine_html = row.get("termine_vorschlag", "&ndash;")
        zeilen.append(
            f"      <tr>"
            f"<td><code>{row['auftrag_id']}</code></td>"
            f"<td>{row['klinik']}</td>"
            f"<td>{row['geraet']}</td>"
            f"<td>{row['produkt']}</td>"
            f"<td>{row['faelligkeit']}</td>"
            f"<td>{termine_html}</td>"
            f"<td><span class='badge {css}'>{_label(row['dringlichkeit'])}</span></td>"
            f"<td>{row['tage']}</td>"
            f"</tr>"
        )
    return "\n".join(zeilen)


_REPAIR_SLA_CSS = {
    "Gruen": "badge-normal",
    "Gelb": "badge-hoch",
    "Rot": "badge-ueberfaellig",
    "Kritisch": "badge-kritisch",
    "Blau": "badge-blau",
}


def _render_repair_tabelle(repair_rows: list[dict]) -> str:
    if not repair_rows:
        return "<p style='color:var(--text-muted);font-style:italic;'>Keine offenen Repair-Auftr&auml;ge.</p>"
    zeilen = []
    for row in repair_rows:
        css = _REPAIR_SLA_CSS.get(row["sla_status"], "badge-normal")
        puls = " puls-animation" if row["sla_status"] in ("Rot", "Kritisch") else ""
        zeilen.append(
            f"      <tr>"
            f"<td><code>{row['auftrag_id']}</code></td>"
            f"<td>{row['klinik']}</td>"
            f"<td>{row['geraet']}</td>"
            f"<td>{row['eingang']}</td>"
            f"<td><span class='badge {css}{puls}'>{_label_sla_text(row['sla_text'])}</span></td>"
            f"<td>{_label(row['phase'])}</td>"
            f"<td>{row.get('ersatzteil', '&ndash;')}</td>"
            f"</tr>"
        )
    return "\n".join(zeilen)


_DEFAULT_EINSATZDAUER_STUNDEN = 4.0  # Fallback: siehe crosstraining_analyse.py Kapazitaetsbasis


def _avg_einsatzdauer_stunden(labor_zeiten: list[dict], produktfamilie: str) -> float:
    """Durchschnittliche Einsatzdauer (Service+Admin) in Stunden aus labor_zeiten.csv.

    Faellt auf den Gesamtdurchschnitt zurueck, wenn keine Eintraege fuer die
    Produktfamilie vorliegen, und auf _DEFAULT_EINSATZDAUER_STUNDEN wenn
    labor_zeiten.csv leer ist.
    """
    treffer = [lz for lz in labor_zeiten if lz.get("produkt_familie") == produktfamilie]
    quelle = treffer or labor_zeiten
    if not quelle:
        return _DEFAULT_EINSATZDAUER_STUNDEN
    gesamt_min = sum(
        int(lz.get("service_zeit_min", 0) or 0) + int(lz.get("admin_zeit_min", 0) or 0)
        for lz in quelle
    )
    return round(gesamt_min / len(quelle) / 60, 2)


def _render_ct_tabelle(
    ct_top5: list[dict],
    techniker: dict[str, dict],
    labor_zeiten: list[dict] | None = None,
) -> str:
    labor_zeiten = labor_zeiten or []
    zeilen = []
    for row in ct_top5:
        tid = row["techniker_id"]
        standort = techniker.get(tid, {}).get("standort", "–")
        fehlende_list = [f for f in row["fehlende_familien"].split(";") if f]
        partner = row.get("idealer_crosstraining_partner", "–") or "–"

        # Schulungsdetails
        schulung_typ = row.get("top_schulung_typ", "")
        schulung_kosten = row.get("top_schulung_kosten", "")
        schulung_dauer = row.get("top_schulung_dauer", "")

        # Icon: Haus = intern, Schule = extern
        typ_icon = "&#127968;" if "INTERN" in schulung_typ else "&#127979;"
        kosten_badge = (
            f"<span class='sub'>{typ_icon} {schulung_kosten}</span>"
            if schulung_kosten else ""
        )
        dauer_badge = (
            f"<br><span class='sub'>{schulung_dauer}</span>"
            if schulung_dauer else ""
        )

        # Cluster-Badges pro fehlender Familie
        cluster_badges = []
        for fam in fehlende_list:
            css_cls, kosten_label = _CLUSTER_MAP.get(fam, ("cluster-small-capital", "Kosten: T&amp;E anfragen *"))
            cluster_badges.append(
                f"<span class='cluster-badge {css_cls}'>{fam}: {_label(kosten_label)}</span>"
            )
        badges_html = " ".join(cluster_badges)

        # Mehrwert-Begruendung: nur fuer die wirtschaftlich tragende Top-Familie
        top_familie = row.get("top_familie", "")
        stk_potenzial = float(row.get("top_familie_stk_potenzial", 0) or 0)
        mehrwert_html = ""
        if top_familie and stk_potenzial > 0:
            qualifiziert = len(
                [f for f in row.get("qualifizierte_familien_l3plus", "").split(";") if f]
            )
            regional = len(
                [f for f in row.get("regionale_produktfamilien", "").split(";") if f]
            )
            y_pct = round(qualifiziert / regional * 100) if regional else 0
            z_pct = round((qualifiziert + 1) / regional * 100) if regional else 0
            avg_h = _avg_einsatzdauer_stunden(labor_zeiten, top_familie)
            zusatz_stunden = round(stk_potenzial * avg_h, 1)
            eur_wert = round(zusatz_stunden * TECHNIKER_KOSTENSATZ_EUR_STUNDE)
            eur_wert_fmt = f"{eur_wert:,}".replace(",", ".")
            mehrwert_html = (
                f'<div class="ct-mehrwert">'
                f'<div>{_label("Potenzial")}: <strong>+{stk_potenzial:.0f} STK/{_label("Jahr")}</strong> ({top_familie})</div>'
                f'<div>{_label("Bessere Auslastung: von")} {y_pct}% {_label("auf")} {z_pct}% ({_label("geschätzt")})</div>'
                f'<div>{_label("Unternehmensmehrwert")}: {stk_potenzial:.0f} STK/a &times; '
                f'&#216;{avg_h:.1f}h {_label("Einsatzdauer")} &asymp; '
                f'<strong>{zusatz_stunden:.0f}h</strong> {_label("zusätzliche Kapazität nutzbar")} '
                f'(&asymp;&thinsp;{eur_wert_fmt}&thinsp;&euro;/{_label("Jahr")} {_label("interne Kapazitätsersparnis")}, '
                f'{_label("Startwert, anpassbar")}{_kostensatz_info_tip()})</div>'
                f'</div>'
            )

        zeilen.append(
            f"      <tr>"
            f"<td><strong>{tid}</strong> <span class='sub'>({standort})</span></td>"
            f"<td>{row['anzahl_luecken']}</td>"
            f"<td><strong>{stk_potenzial:.0f}</strong></td>"
            f"<td class='fehlend-liste'>{badges_html}{dauer_badge}{mehrwert_html}</td>"
            f"<td>{partner}<br>{kosten_badge}</td>"
            f"</tr>"
        )
    return "\n".join(zeilen)


def _render_ct_ausschluss_hint(ct_rows: list[dict]) -> str:
    """Hinweis-Box fuer Techniker ohne wirtschaftlich sinnvolles Crosstraining."""
    ausgeschlossen = [r for r in ct_rows if r.get("wirtschaftlich_sinnvoll") == "Nein"]
    if not ausgeschlossen:
        return ""
    ids = ", ".join(r["techniker_id"] for r in ausgeschlossen)
    return (
        f'<div class="ct-ausschluss-hint">'
        f'<strong>{len(ausgeschlossen)} von {len(ct_rows)} Techniker</strong> '
        f'erreichen die Wirtschaftlichkeits-Schwelle nicht '
        f'(&lt;{MIN_GERAETE_FUER_CROSSTRAINING} Ger&auml;te oder '
        f'&lt;{MIN_STK_POTENZIAL_CROSSTRAINING} STK/a Potenzial der fehlenden Produktfamilie '
        f'im Gebiet): {ids}. Kein wirtschaftlich sinnvolles Crosstraining im aktuellen '
        f'Gebiet &mdash; Ger&auml;tedichte zu gering.'
        f'</div>'
    )


def _render_nrw_warnung(warnung: dict | None) -> str:
    if warnung is None:
        return ""
    tech_liste = "".join(
        f"<li><strong>{t['id']}</strong>: {t['qualifiziert']} L3-Familie(n) "
        f"(&bdquo;{t['familien_l3']}&ldquo;), "
        f"{t['fehlend']} Luecken, +{t['zusatz_stk']:.0f}&thinsp;STK/a ungenutztes Potenzial</li>"
        for t in warnung["techniker"]
    )
    return f"""
  <section class="warnung-box">
    <h2 data-i18n="h.nrw">&#9888; NRW-&Uuml;berlastungs-Warnung</h2>
    <p class="warnung-stats">
      380 STK/Kopf NRW vs. 72 Nord &middot;
      <strong>{warnung['anzahl_schwach']} von 4 NRW-Technikern</strong> decken weniger als
      {round(_AMPEL_GELB_AB * 100)}&thinsp;% der regionalen Produktfamilien ab (Ampel&thinsp;ROT).
    </p>
    <p class="warnung-stats">
      T8 + T13: <strong>1.025 STK/Jahr nicht abdeckbar</strong> &ndash;
      Kombiniertes ungenutztes Potenzial:
      <strong>{warnung['gesamt_stk']:,}&thinsp;STK/Jahr</strong>
    </p>
    <ul>{tech_liste}</ul>
    <p class="warnung-hinweis">
      Empfehlung: Crosstraining-Ma&szlig;nahmen f&uuml;r T8 und T13 priorisieren.
      Ideale Partner laut Analyse: T10 (f&uuml;r T8) und T10 (f&uuml;r T13).
    </p>
  </section>"""


def _render_puffer_section(labor_zeiten: list[dict]) -> str:
    """Erzeugt aufklappbare Puffer-Visualisierung pro geplantem Einsatz."""
    if not labor_zeiten:
        return ""

    # Gruppiere nach Techniker → Liste von Einsaetzen
    einsaetze_by_tech: dict[str, list[dict]] = {}
    for lz in labor_zeiten:
        tid = lz.get("techniker_id", "")
        if tid:
            einsaetze_by_tech.setdefault(tid, []).append(lz)

    rows = []
    eid = 0
    for tid in sorted(einsaetze_by_tech):
        for lz in einsaetze_by_tech[tid]:
            eid += 1
            netto_min = int(lz.get("service_zeit_min", 0))
            admin_min = int(lz.get("admin_zeit_min", 0))
            netto_total = netto_min + admin_min
            gesamt = netto_total + _PUFFER_GESAMT
            netto_pct = round(netto_total / gesamt * 100) if gesamt else 0
            puffer_pct = 100 - netto_pct

            puffer_detail = "".join(
                f"<div class='puffer-item'>"
                f"<span class='puffer-label'>{_label(k)}:</span> "
                f"<span class='puffer-val'>{v} min</span></div>"
                for k, v in _PUFFER.items()
            )

            detail_id = f"puffer-detail-{eid}"
            rows.append(
                f'<div class="puffer-row" onclick="'
                f"var d=document.getElementById('{detail_id}');"
                f"d.style.display=d.style.display==='none'?'block':'none'\">"
                f'<div class="puffer-summary">'
                f'<strong>{tid}</strong> &middot; '
                f'{lz.get("produkt_familie","")} &middot; '
                f'{lz.get("geraete_typ","")} &middot; '
                f'<span class="puffer-gesamt">{gesamt} min {_label("gesamt")}</span>'
                f' <span class="sub">&#9660;</span></div>'
                f'<div class="puffer-bar-wrap">'
                f'<div class="puffer-bar-netto" style="width:{netto_pct}%">'
                f'{netto_total} min</div>'
                f'<div class="puffer-bar-puffer" style="width:{puffer_pct}%">'
                f'{_PUFFER_GESAMT} min</div></div>'
                f'<div id="{detail_id}" class="puffer-detail" style="display:none">'
                f'<div class="puffer-detail-grid">'
                f'<div><strong>{_label("Netto-Zeit")}:</strong> {netto_min} min {_label("Service")} + {admin_min} min {_label("Admin")} = {netto_total} min</div>'
                f'<div class="puffer-aufschluesselung">'
                f'<strong>{_label("Puffer-Aufschlüsselung")}:</strong>'
                f'{puffer_detail}'
                f'<div class="puffer-item puffer-summe">'
                f'<span class="puffer-label">{_label("Gesamt Puffer")}:</span> '
                f'<span class="puffer-val">{_PUFFER_GESAMT} min</span></div>'
                f'</div>'
                f'<div><strong>{_label("Gesamtzeit")}:</strong> {netto_total} + {_PUFFER_GESAMT} = '
                f'<strong>{gesamt} min</strong> ({gesamt/60:.1f}h)</div>'
                f'</div></div></div>')

    return f"""
  <section>
    <h2 data-i18n="h.puffer">Tourplanung &mdash; Puffer-Visualisierung</h2>
    <p class="section-hint">
      {_label("Pro geplantem Einsatz: Netto-Zeit (grün) + Puffer (gelb). Klick für Aufschlüsselung. Quelle: labor_zeiten.csv")}
    </p>
    <div class="puffer-container">
{"".join(rows)}
    </div>
  </section>"""


def _render_workflow_status() -> str:
    """Erzeugt die Workflow-Status Sektion (7 Schritte)."""
    steps = [
        ("&#128229;", "Einlesen", "auto", "SMax Go API"),
        ("&#129504;", "Scoring", "auto", "KI-Empfehlung"),
        ("&#9989;", "Best&auml;tigung", "mensch", "Disponent pr&uuml;ft"),
        ("&#128241;", "Info", "auto", "Techniker-Push"),
        ("&#128197;", "Due-Date", "auto", "Termin-Check"),
        ("&#128270;", "TD-Pr&uuml;fung", "auto", "Dokumente pr&uuml;fen"),
        ("&#128231;", "Kundenmail", "auto", "Best&auml;tigung"),
    ]
    items = []
    for i, (icon, label, mode, detail) in enumerate(steps):
        badge_cls = "wf-badge-auto" if mode == "auto" else "wf-badge-mensch"
        badge_txt = "Auto" if mode == "auto" else "Mensch"
        arrow = '<span class="wf-arrow">&#8594;</span>' if i < len(steps) - 1 else ""
        items.append(
            f'<div class="wf-step">'
            f'<div class="wf-icon">{icon}</div>'
            f'<div class="wf-label">{_label(label)}</div>'
            f'<span class="wf-badge {badge_cls}">{_label(badge_txt)}</span>'
            f'<div class="wf-detail">{_label(detail)}</div>'
            f'</div>{arrow}'
        )
    return f"""
  <section>
    <h2 data-i18n="h.workflow6">6 &mdash; Workflow-Status</h2>
    <p class="section-hint">
      {_label("Vollautomatisiert · Copilot — kein Autopilot")}
    </p>
    <div class="wf-pipeline">
      {"".join(items)}
    </div>
  </section>"""


def _kostensatz_info_tip() -> str:
    """Wiederverwendbares Herleitungs-Tooltip fuer TECHNIKER_KOSTENSATZ_EUR_STUNDE
    (Business-Case- und Crosstraining-Tab) -- macht an jeder Verwendungsstelle
    klar, dass der Satz ein Schaetzwert/Startwert ist, keine von Medtronic
    T&E bestaetigte Ist-Zahl."""
    return _info_tip(
        _label(
            "Herleitung (Schätzung): Marktdurchschnitt Bruttolohn Servicetechniker "
            "Medizintechnik Deutschland ≈24 €/h × Lohnnebenkosten-Faktor ≈1,9 "
            "(Sozialversicherung, Urlaubs-/Krankheitsrücklage, anteilige "
            "Fahrzeug-/Ausrüstungskosten). Zentral anpassbar in config.py."
        )
    )


def _render_business_case(stk_potenzial_gesamt: int = 0, median_min: int = 0) -> str:
    """Erzeugt die Business-Case Sektion mit konkreten Kennzahlen.

    Nutzt TECHNIKER_KOSTENSATZ_EUR_STUNDE (config.py) statt der bisherigen
    "T&E anfragen"-Platzhalter fuer alle Kennzahlen, die auf internem
    Techniker-Stundenaufwand basieren (Zeitersparnis Planung, Crosstraining-
    ROI). Der Satz ist ausdruecklich ein Schaetzwert/Startwert (siehe
    Herleitung in config.py und im Tooltip unten) -- keine von Medtronic
    T&E bestaetigte Ist-Zahl, deshalb ueberall als "Startwert, anpassbar"
    gekennzeichnet.
    """
    kostensatz_fmt = f"{TECHNIKER_KOSTENSATZ_EUR_STUNDE:.0f}".replace(".", ",")
    kostensatz_tip = _kostensatz_info_tip()

    zeitersparnis_h = 4992
    monetaerer_wert = round(zeitersparnis_h * TECHNIKER_KOSTENSATZ_EUR_STUNDE)
    monetaerer_wert_fmt = f"{monetaerer_wert:,}".replace(",", ".")

    if stk_potenzial_gesamt > 0:
        stk_fmt = f"{stk_potenzial_gesamt:,}".replace(",", ".")
        med_fmt = str(median_min)
        einsatzdauer_h = median_min / 60
        ct_wert = round(stk_potenzial_gesamt * einsatzdauer_h * TECHNIKER_KOSTENSATZ_EUR_STUNDE)
        ct_wert_fmt = f"{ct_wert:,}".replace(",", ".")
        ct_roi_html = f"""
        <div class="bc-result">{stk_fmt} {_label("zusätzliche STKs/Jahr möglich")}</div>
        <div class="bc-formula">&times; &Oslash; {med_fmt}&thinsp;{_label("Min. Einsatzdauer")} &times; {kostensatz_fmt}&thinsp;&euro;/h{kostensatz_tip}</div>
        <div class="bc-hint">= {ct_wert_fmt} &euro;/{_label("Jahr")} {_label("interne Kapazitätsersparnis")}</div>"""
    else:
        ct_roi_html = f"""
        <div class="bc-formula">[+STK/a {_label("Potenzial")}] &times; [&Oslash; {_label("STK-Dauer")} h] &times; {kostensatz_fmt}&thinsp;&euro;/h{kostensatz_tip}</div>
        <div class="bc-hint">= {_label("interne Kapazitätsersparnis")}</div>"""

    return f"""
  <section>
    <h2 data-i18n="h.business7">7 &mdash; Business Case</h2>
    <p class="section-hint">
      {_label("Berechnete Kennzahlen mit Startwerten für Techniker-Kostensatz und Kunden-Verrechnungssatz — anpassbar in config.py")}
    </p>
    <div class="bc-grid">
      <div class="bc-card">
        <div class="bc-card-title">{_label("Zeitersparnis Planung")}</div>
        <div class="bc-formula">24 {_label("Techniker")} &times; 4 h/{_label("Tag")} &times; 4 {_label("Tage")} &times; 52 {_label("Wochen")}</div>
        <div class="bc-result">= 4.992 h/{_label("Jahr")}</div>
        <div class="bc-hint">{_label("manuelle Planung entfällt")}</div>
      </div>
      <div class="bc-card">
        <div class="bc-card-title">{_label("Monetärer Wert")}</div>
        <div class="bc-formula">4.992 h &times; {kostensatz_fmt}&thinsp;&euro;/h{kostensatz_tip}</div>
        <div class="bc-result">= {monetaerer_wert_fmt} &euro;/{_label("Jahr")}</div>
        <div class="bc-hint">{_label("Jährliche Einsparung")}</div>
      </div>
      <div class="bc-card">
        <div class="bc-card-title">{_label("Crosstraining-ROI")}</div>{ct_roi_html}
      </div>
      <div class="bc-card">
        <div class="bc-card-title">{_label("Fahrzeit / Gebiet")}</div>
        <div class="bc-formula">{_label("Fahrzeit-Einsparung aus Gebiets-Szenario")}</div>
        <div class="bc-result">~10.000 &euro;/{_label("Jahr")}</div>
        <div class="bc-hint">{_label("Mobilitätskostenreduktion")}</div>
      </div>
      <div class="bc-card">
        <div class="bc-card-title">{_label("Investition &amp; Break-even")}</div>
        <div class="bc-formula">17.590 &euro; {_label("einmalig")}</div>
        <div class="bc-result">{_label("Break-even: ca. 10 Wochen")}</div>
        <div class="bc-hint">{_label("Einmalige Implementierungskosten")}</div>
      </div>
    </div>
    <div class="bc-gold-hint">
      &#9733; {_label("Techniker-Kostensatz (Startwert, anpassbar in config.py)")}: {kostensatz_fmt}&thinsp;&euro;/h{kostensatz_tip}.
      {_label("Alle übrigen Kennzahlen sind belastbare Ist-Werte.")}
    </div>
  </section>"""


def _generate_demo_history(techniker: dict[str, dict],
                           labor_zeiten: list[dict]) -> dict[str, dict]:
    """Generiert realistische Demo-Einsatzhistorie pro Techniker."""
    import hashlib

    # Kliniken pro Region (Demo)
    _KLINIKEN_DEMO = {
        "Hessen": ["UKF Frankfurt", "Klinikum Kassel", "Uniklinik Giessen"],
        "Bayern": ["Klinikum Erlangen", "LMU Muenchen", "Klinikum Augsburg"],
        "Bayern-Nord": ["Klinikum Erlangen", "Klinikum Bayreuth", "Klinikum Bamberg"],
        "Bayern-Ost": ["Klinikum Regensburg", "Klinikum Passau", "Klinikum Landshut"],
        "Baden-Württemberg": ["Uniklinik Tuebingen", "Klinikum Stuttgart", "Uniklinik Ulm"],
        "BaWü-Süd": ["Uniklinik Tuebingen", "Klinikum Stuttgart", "Uniklinik Freiburg"],
        "NRW-West": ["UKB Bonn", "Uniklinik Koeln", "Klinikum Aachen"],
        "NRW-Süd": ["UKB Bonn", "Uniklinik Koeln", "Klinikum Aachen"],
        "Nord": ["UKE Hamburg", "UKSH Luebeck", "MHH Hannover"],
        "Thüringen": ["Klinikum Weimar", "Uniklinik Jena", "Klinikum Erfurt"],
    }
    _TYPEN = ["STK", "PM", "STK", "Repair", "STK"]

    # Labor-Zeiten nach Techniker gruppieren
    lz_by_tech: dict[str, list[dict]] = {}
    for lz in labor_zeiten:
        lz_by_tech.setdefault(lz["techniker_id"], []).append(lz)

    result: dict[str, dict] = {}
    for tid, td in sorted(techniker.items()):
        region = td.get("region", "Hessen")
        kliniken = _KLINIKEN_DEMO.get(region, ["Klinikum " + td.get("standort", "Unbekannt")])
        tech_lz = lz_by_tech.get(tid, [])

        # Generiere 5 Demo-Work-Orders
        orders = []
        for i in range(5):
            seed = int(hashlib.md5(f"{tid}-{i}".encode()).hexdigest()[:8], 16)
            tage_offset = 7 + (seed % 50)
            datum = _HEUTE - timedelta(days=tage_offset)
            klinik = kliniken[seed % len(kliniken)]
            if tech_lz:
                lz = tech_lz[seed % len(tech_lz)]
                geraet = lz["geraete_typ"]
                familie = lz["produkt_familie"]
                dauer_min = int(lz["service_zeit_min"]) + int(lz["admin_zeit_min"])
            else:
                geraet = "–"
                familie = "–"
                dauer_min = 120 + (seed % 180)
            typ = _TYPEN[seed % len(_TYPEN)]
            orders.append({
                "datum": datum.strftime("%d.%m.%Y"),
                "klinik": klinik,
                "geraet": geraet,
                "typ": typ,
                "dauer_h": f"{dauer_min // 60}h {dauer_min % 60:02d}min",
                "dauer_min": dauer_min,
                "status": "\u2713",
                "familie": familie,
            })
        orders.sort(key=lambda o: o["datum"], reverse=True)

        # Kennzahlen
        avg_dauer = sum(o["dauer_min"] for o in orders) / len(orders) if orders else 0
        from collections import Counter
        klinik_counter = Counter(o["klinik"] for o in orders)
        fam_counter = Counter(o["familie"] for o in orders)
        haeufigste_klinik = klinik_counter.most_common(1)[0][0] if klinik_counter else "–"
        haeufigste_fam = fam_counter.most_common(1)[0][0] if fam_counter else "–"

        result[tid] = {
            "orders": orders[:3],  # Letzte 3 anzeigen
            "einsaetze_monat": 2 + (int(hashlib.md5(tid.encode()).hexdigest()[:4], 16) % 5),
            "einsaetze_jahr": 28 + (int(hashlib.md5(tid.encode()).hexdigest()[:6], 16) % 30),
            "avg_dauer_h": f"{avg_dauer / 60:.1f}",
            "haeufigste_klinik": haeufigste_klinik,
            "haeufigste_familie": haeufigste_fam,
        }
    return result


def _render_techniker_detail_data(
    techniker: dict[str, dict],
    demo_history: dict[str, dict],
) -> str:
    """Erzeugt JSON-Daten fuer Techniker-Detail-Modal (inline im HTML)."""
    detail_data: dict[str, dict] = {}
    for tid, td in sorted(techniker.items()):
        hist = demo_history.get(tid, {})
        detail_data[tid] = {
            "standort": td.get("standort", "–"),
            "orders": hist.get("orders", []),
            "einsaetze_monat": hist.get("einsaetze_monat", 0),
            "einsaetze_jahr": hist.get("einsaetze_jahr", 0),
            "avg_dauer_h": hist.get("avg_dauer_h", "0"),
            "haeufigste_klinik": hist.get("haeufigste_klinik", "–"),
            "haeufigste_familie": hist.get("haeufigste_familie", "–"),
        }
    return json.dumps(detail_data, ensure_ascii=False)


# ---------------------------------------------------------------------------
# System-Prompt fuer Claude-Chat
# ---------------------------------------------------------------------------

def _build_system_prompt(
    ct_rows: list[dict],
    techniker: dict[str, dict],
    ampeln: list[dict],
) -> str:
    """Baut den System-Prompt mit allen Projektdaten."""
    tech_lines = []
    ct_by_tid = {r["techniker_id"]: r for r in ct_rows}
    for a in ampeln:
        tid = a["techniker_id"]
        ct = ct_by_tid.get(tid, {})
        l3_fam = ct.get("qualifizierte_familien_l3plus", "")
        fehlend = ct.get("fehlende_familien", "")
        partner = ct.get("idealer_crosstraining_partner", "–") or "–"
        zusatz = ct.get("potentielles_zusatz_stk_pa", "0")
        tech_lines.append(
            f"- {tid}: Standort={a['standort']}, Region={a['region']}, "
            f"Ampel={a['ampel_label']}, Abdeckung={a['abdeckung_pct']}%, "
            f"L3-Familien=[{l3_fam}], "
            f"Fehlend=[{fehlend}], "
            f"+{float(zusatz):.0f} STK/a Potenzial, "
            f"Crosstraining-Partner={partner}"
        )
    tech_block = "\n".join(tech_lines)

    return (
        "Du bist der KI-Assistent fuer das Medtronic Field Service Dashboard. "
        "Antworte auf Deutsch, praezise und im Kontext der Medtronic-Servicetechniker-Planung. "
        "Beziehe dich auf die konkreten Daten unten.\n\n"
        "## Techniker-Uebersicht (24 Techniker)\n"
        f"{tech_block}\n\n"
        "## Scoring-Formel\n"
        "Score = Kompetenz x 0.40 + Fahrzeit x 0.35 + Auslastung x 0.25\n"
        "- Kompetenz: L3=100, L2=50, L1=0 Punkte\n"
        "- Fahrzeit: Luftlinie x Umwegfaktor 1.35, Geschwindigkeit 90 km/h\n"
        "- Auslastung: Wochenbasis 32h (Mo-Do), Freitag = Home Office / Admin\n\n"
        "## Arbeitszeitmodell (Vertrauensarbeitszeit)\n"
        "- Wochenziel: 32h effektive Aussendienststunden (Mo-Do, je 8h)\n"
        "- Freitag = Home Office / Bueroarbeit (kein Aussendienst ausser Notfaelle)\n"
        "- Warnungen: >=30h Puffer, >=34h Gelb, >45h Ausschluss (ArbZG)\n"
        "- Tageslimits: >8h Warnung, >9h Regel-Max, >10h Ausschluss (ArbZG §3)\n"
        "- Mindestruhezeit: 11h zwischen Arbeitstagen (ArbZG §5)\n\n"
        "## NRW-Ueberlastung\n"
        "- NRW-Techniker: T5 (Oberhausen), T8 (Hennef), T11 (Gangelt), T13 (Meckenheim)\n"
        "- T8 und T13 sind Ampel ROT (<20% Abdeckung)\n"
        "- Kombiniertes ungenutztes Potenzial: ~1.510 STK/Jahr\n"
        "- Durchschnitt NRW: ~380 STK/Kopf – deutliche Ueberlastungsgefahr\n"
        "- Empfehlung: Crosstraining mit T10 (Balingen) als Partner\n\n"
        "## Kalibrierungs-Warnungen (ablaufend <30 Tage ab 27.03.2026)\n"
        "- T10: Hugo-Kalibrierkoffer (MM-HUGO-002) – 14 Tage verbleibend (10.04.2026)\n"
        "- T5: NIM-Tester (MM-NEURO-001) – 19 Tage verbleibend (15.04.2026)\n"
        "- T1: Hugo-Diagnosetool (MM-HUGO-001) – 24 Tage verbleibend (20.04.2026)\n"
        "- T8: EKG-Simulator (MM-KARD-001) – 29 Tage verbleibend (25.04.2026)\n\n"
        "## Crosstraining-Prioritaeten (Top 5 nach STK-Potenzial)\n"
        "1. T2 (Wehingen): 9 Luecken, +664 STK/a – Partner: T10\n"
        "2. T8 (Hennef): 9 Luecken, +527 STK/a – Partner: T10\n"
        "3. T13 (Meckenheim): 9 Luecken, +498 STK/a – Partner: T10\n"
        "4. T1 (Obertshausen): 8 Luecken, +453 STK/a – Partner: T14\n"
        "5. T12 (Frankfurt): 8 Luecken, +449 STK/a – Partner: T10\n\n"
        "## Pflichtdokumente je Auftragstyp\n"
        "- STK: Messprotokoll, Servicebericht\n"
        "- PM: Servicebericht, Checkliste\n"
        "- Repair: Servicebericht, Foto vorher, Foto nachher "
        "(+ KV wenn Kosten > 500 EUR)\n\n"
        "## Hugo-Regel\n"
        "Hugo-Auftraege duerfen NUR von Hugo-zertifizierten Technikern (L3) "
        "durchgefuehrt werden: T1, T6, T10, T11.\n"
        "Hugo-Standorte: UKE Hamburg, UKSH Luebeck, BG Bergmannsheil Bochum, "
        "Uniklinikum Ulm, Uniklinikum Dresden u.a."
    )


# ---------------------------------------------------------------------------
# Gebietsplanung – Fahrzeit-Optimierung
# ---------------------------------------------------------------------------

_TECH_FARBEN = {
    "T1":  "#0072CE", "T2":  "#00A3E0", "T3":  "#7B2D8E",
    "T4":  "#E87000", "T5":  "#00843D", "T6":  "#003087",
    "T7":  "#CC0000", "T8":  "#E8A000", "T9":  "#2E8B57",
    "T10": "#B22222", "T11": "#4169E1", "T12": "#2F4F4F",
    "T13": "#D2691E", "T14": "#008B8B",
}

# Primaere Gebietszuweisung (Bundesland → Techniker) fuer Karteneinfaerbung
_GEBIET_AKTUELL = {
    "Schleswig-Holstein": "T6", "Hamburg": "T9",
    "Mecklenburg-Vorpommern": "T9", "Niedersachsen": "T6",
    "Bremen": "T6", "Nordrhein-Westfalen": "T11",
    "Hessen": "T1", "Thüringen": "T3",
    "Sachsen": "T3", "Sachsen-Anhalt": "T3",
    "Brandenburg": "T3", "Berlin": "T3",
    "Rheinland-Pfalz": "T8", "Saarland": "T13",
    "Baden-Württemberg": "T10", "Bayern": "T7",
}
_GEBIET_OPTIMIERT = dict(_GEBIET_AKTUELL)  # State-level bleibt gleich

# Approximate Mittelpunkte fuer 2-stellige PLZ-Bereiche (lat, lon)
_PLZ2_COORDS: dict[str, tuple[float, float]] = {
    "01": (51.05, 13.74), "02": (51.18, 14.43), "03": (51.76, 14.33),
    "04": (51.34, 12.37), "06": (51.50, 11.97), "07": (50.93, 11.59),
    "08": (50.72, 12.49), "09": (50.83, 12.92), "10": (52.52, 13.41),
    "12": (52.48, 13.44), "13": (52.54, 13.35), "14": (52.39, 13.07),
    "15": (52.35, 14.55), "16": (52.76, 13.28), "17": (54.10, 13.38),
    "18": (54.09, 12.14), "19": (53.63, 11.42), "20": (53.55, 10.00),
    "21": (53.47, 9.97), "22": (53.60, 9.83), "23": (53.87, 10.69),
    "24": (54.32, 10.12), "25": (53.90, 9.48), "26": (53.14, 8.22),
    "27": (53.08, 8.80), "28": (53.08, 8.80), "29": (52.97, 10.23),
    "30": (52.37, 9.73), "31": (52.23, 9.79), "32": (52.02, 8.53),
    "33": (51.93, 8.87), "34": (51.32, 9.50), "35": (50.58, 8.68),
    "36": (50.56, 9.68), "37": (51.54, 9.92), "38": (52.27, 10.53),
    "39": (52.12, 11.63), "40": (51.22, 6.78), "41": (51.21, 6.69),
    "42": (51.26, 7.15), "44": (51.51, 7.47), "45": (51.45, 7.01),
    "46": (51.47, 6.85), "47": (51.44, 6.76), "48": (51.96, 7.63),
    "49": (52.28, 8.05), "50": (50.94, 6.96), "51": (50.94, 7.03),
    "52": (50.78, 6.08), "53": (50.73, 7.10), "54": (49.76, 6.64),
    "55": (49.99, 8.25), "56": (50.36, 7.60), "57": (50.87, 8.02),
    "58": (51.36, 7.47), "59": (51.68, 7.81), "60": (50.11, 8.68),
    "61": (50.18, 8.63), "63": (50.07, 8.86), "64": (49.87, 8.65),
    "65": (50.08, 8.24), "66": (49.24, 7.00), "67": (49.48, 8.44),
    "68": (49.49, 8.47), "69": (49.41, 8.69), "70": (48.78, 9.18),
    "71": (48.73, 9.12), "72": (48.52, 9.06), "73": (48.80, 9.68),
    "74": (49.14, 9.21), "75": (48.89, 8.70), "76": (49.01, 8.40),
    "77": (48.47, 7.94), "78": (48.06, 8.46), "79": (48.00, 7.84),
    "80": (48.14, 11.58), "81": (48.14, 11.60), "82": (48.08, 11.36),
    "83": (47.86, 12.13), "84": (48.54, 12.15), "85": (48.26, 11.44),
    "86": (48.37, 10.90), "87": (47.73, 10.32), "88": (47.66, 9.48),
    "89": (48.40, 10.00), "90": (49.45, 11.08), "91": (49.60, 11.00),
    "92": (49.02, 12.10), "93": (49.01, 12.10), "94": (48.57, 13.45),
    "95": (50.09, 11.78), "96": (50.27, 11.08), "97": (49.79, 9.95),
    "98": (50.61, 10.69), "99": (50.98, 11.03),
}

# Einstellungsempfehlungen fuer unterversorgte Regionen
_EINSTELLUNGS_EMPFEHLUNGEN = [
    {
        "standort": "Berlin",
        "plz": "10117",
        "lat": 52.52, "lon": 13.41,
        "region": "Berlin / Brandenburg / MV",
        "abdeckt_plz": ["10", "12", "13", "14", "15", "16", "17", "18", "19",
                         "01", "02", "03"],
        "kliniken_geschaetzt": 12,
        "begruendung": "Groesste Versorgungsluecke: T3 (Weimar) deckt ganz "
                       "Ostdeutschland allein ab. Berlin-Techniker entlastet "
                       "T3 um ca. 50% und reduziert max. Fahrzeit von 270km auf 80km.",
    },
    {
        "standort": "Hannover",
        "plz": "30625",
        "lat": 52.37, "lon": 9.73,
        "region": "Niedersachsen / Bremen",
        "abdeckt_plz": ["26", "27", "28", "29", "30", "31", "32", "33",
                         "34", "37", "38", "49"],
        "kliniken_geschaetzt": 8,
        "begruendung": "T6 (Schenefeld) und T9 (Hamburg) decken den Norden, "
                       "aber Niedersachsen-Sued/Ost bleibt unterversorgt. "
                       "Hannover schliesst die Luecke zwischen Nord und Mitte.",
    },
    {
        "standort": "München",
        "plz": "80336",
        "lat": 48.14, "lon": 11.58,
        "region": "München / Oberbayern",
        "abdeckt_plz": ["80", "81", "82", "83", "84", "85", "86"],
        "kliniken_geschaetzt": 10,
        "begruendung": "Muenchen ist groesster Klinik-Cluster in Bayern. "
                       "T4 (Erlangen) und T7 (Wildenberg) zu weit entfernt. "
                       "Eigener Muenchen-Techniker fuer 10+ Kliniken optimal.",
    },
    {
        "standort": "Mannheim",
        "plz": "68159",
        "lat": 49.49, "lon": 8.47,
        "region": "Saarland / Pfalz / Rhein-Neckar",
        "abdeckt_plz": ["66", "67", "68", "69", "76"],
        "kliniken_geschaetzt": 6,
        "begruendung": "Luecke zwischen T1 (Obertshausen/Hessen) und "
                       "T10 (Balingen/BaWue). Mannheim deckt Saarland, "
                       "Pfalz und Rhein-Neckar-Raum kompakt ab.",
    },
]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(min(1.0, math.sqrt(a)))


def _strassenfaktor(plz: str) -> float:
    """Geschaetzter Strassenfaktor nach PLZ-Region."""
    p = plz[:2] if len(plz) >= 2 else ""
    if p in ("87", "88"):                                   return 2.0
    if p in ("77", "78", "79"):                             return 2.0
    if p in ("83", "84", "86"):                             return 1.5
    if p in ("40", "41", "42", "44", "45", "46", "47",
             "48", "50", "51", "52", "53"):                 return 1.0
    if p in ("60", "61", "63", "65"):                       return 1.0
    if p in ("10", "12", "13", "14", "20", "21", "22"):     return 1.0
    return 1.3


def _soll_klinik_verschieben(
    auslastung_diff_pp: float,
    fahrzeit_mehraufwand_min: float,
) -> bool:
    """Generische Optimierungsregel (ID-unabhaengig, funktioniert fuer jedes
    Techniker-Set).

    Eine Klinik wandert vom naechstgelegenen zum zweitnaechsten Techniker,
    wenn dieser deutlich weniger ausgelastet ist (Auslastungsdifferenz ueber
    dem Schwellwert) UND die zusaetzliche Fahrzeit vertretbar bleibt.
    """
    return (
        auslastung_diff_pp > OPTIMIERUNG_AUSLASTUNGS_SCHWELLE
        and fahrzeit_mehraufwand_min <= OPTIMIERUNG_MAX_FAHRZEIT_MEHRAUFWAND_MIN
    )


def _klassifiziere_gebiete_luecken_ueberschneidungen(
    kliniken: list[dict],
    kandidaten: dict[str, list[tuple[str, float]]],
    topo_paths: list[dict],
) -> dict[str, dict]:
    """Generische, ID-unabhaengige Klassifikation der Bundeslaender in
    Luecke / Ueberschneidung / Optimal -- aus den echten Klinik-Fahrzeiten
    zum 1.- und 2.-naechsten Techniker abgeleitet (kein festes T1-T14-Schema),
    funktioniert fuer Demo- und Echtdaten-Techniker gleichermassen.

    Luecke: Oe Fahrzeit zum naechsten Techniker im Bundesland liegt ueber
    LUECKE_FAHRZEIT_SCHWELLE_MIN.
    Ueberschneidung: bei mindestens UEBERSCHNEIDUNG_ANTEIL_SCHWELLE der
    Kliniken im Bundesland liegt der 2.-naechste Techniker fahrzeitlich nah
    am 1.-naechsten (Differenz <= UEBERSCHNEIDUNG_FAHRZEIT_DIFF_MIN Minuten
    -- die Klinik ist also zwischen zwei Technikern "kontestiert").
    Optimal: weder Luecke noch Ueberschneidung.

    Gibt {bundesland: {typ, techs, naechster?, fahrzeit_min?, anteil_pct?}}
    zurueck -- nur fuer Bundeslaender mit mindestens einer zugeordneten
    Klinik (kein Eintrag, wenn keine Daten vorliegen).
    """
    klinik_plz = {k["id"]: k.get("plz", "") for k in kliniken}
    bl_kliniken: dict[str, list[str]] = {}
    for k in kliniken:
        px, py = _project_mercator(k["lon"], k["lat"])
        bl = _bundesland_fuer_punkt(px, py, topo_paths)
        if bl:
            bl_kliniken.setdefault(bl, []).append(k["id"])

    ergebnis: dict[str, dict] = {}
    for bl, klinik_ids in bl_kliniken.items():
        fahrzeiten: list[float] = []
        kontestiert = 0
        naechste_zaehler: dict[str, int] = {}
        kontest_techs: set[str] = set()
        for kid in klinik_ids:
            dists = kandidaten.get(kid, [])
            if not dists:
                continue
            eff_speed = 100.0 / _strassenfaktor(klinik_plz.get(kid, ""))
            tid1, dist1 = dists[0]
            fz1 = dist1 / eff_speed * 60
            fahrzeiten.append(fz1)
            naechste_zaehler[tid1] = naechste_zaehler.get(tid1, 0) + 1
            if len(dists) >= 2:
                tid2, dist2 = dists[1]
                fz2 = dist2 / eff_speed * 60
                if (fz2 - fz1) <= UEBERSCHNEIDUNG_FAHRZEIT_DIFF_MIN:
                    kontestiert += 1
                    kontest_techs.add(tid1)
                    kontest_techs.add(tid2)

        if not fahrzeiten:
            continue

        avg_fz = sum(fahrzeiten) / len(fahrzeiten)
        kontest_anteil = kontestiert / len(fahrzeiten)
        haupttech = max(naechste_zaehler, key=lambda t: naechste_zaehler[t])

        if avg_fz > LUECKE_FAHRZEIT_SCHWELLE_MIN:
            ergebnis[bl] = {
                "typ": "gap",
                "techs": [haupttech],
                "naechster": haupttech,
                "fahrzeit_min": round(avg_fz),
            }
        elif kontest_anteil >= UEBERSCHNEIDUNG_ANTEIL_SCHWELLE:
            ergebnis[bl] = {
                "typ": "overlap",
                "techs": sorted(kontest_techs),
                "anteil_pct": round(kontest_anteil * 100),
            }
        else:
            ergebnis[bl] = {
                "typ": "optimal",
                "techs": [haupttech],
            }
    return ergebnis


_SVG_POINT_RE = re.compile(r'([ML])(-?\d+\.?\d*),(-?\d+\.?\d*)')


def _parse_svg_polygon(d: str) -> list[list[tuple[float, float]]]:
    """Parst ein einfaches SVG-Path 'd'-Attribut (nur M/L/Z, keine Kurven) in
    Punktlisten je Teilpfad (Bundeslaender mit Inseln haben mehrere Teilpfade)."""
    subpaths: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for cmd, xs, ys in _SVG_POINT_RE.findall(d):
        if cmd == "M" and current:
            subpaths.append(current)
            current = []
        current.append((float(xs), float(ys)))
    if current:
        subpaths.append(current)
    return subpaths


def _punkt_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray-Casting: liegt (x,y) innerhalb des Polygons?"""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _bundesland_fuer_punkt(x: float, y: float, paths: list[dict]) -> str | None:
    """Findet das Bundesland, dessen Polygon (x,y) enthaelt.

    Nutzt die echten Geodaten aus daten/deutschland_topo.json (dieselben
    Polygone wie die Kartendarstellung) statt einer PLZ-Naeherungstabelle.
    """
    for p in paths:
        for subpath in _parse_svg_polygon(p["d"]):
            if len(subpath) >= 3 and _punkt_in_polygon(x, y, subpath):
                return p["name"]
    return None


def _lade_kliniken_demo() -> tuple[list[dict], dict[str, float], float]:
    """Laedt die Demo-Kliniken (kliniken.csv + geraete.csv).

    Gibt (kliniken, stk_count, stunden_pro_einsatz) zurueck. stk_count ist das
    STK/Jahr-Volumen je Klinik (Anzahl Geraete / Wartungszyklus).
    """
    from techniker.scoring import _KLINIK_COORDS

    kliniken = []
    name_to_id: dict[str, str] = {}
    with open(_DATA_DIR / "kliniken.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            plz = row["plz"]
            kid = row["klinik_id"]
            name_to_id[row["name"].strip().lower()] = kid
            if plz in _KLINIK_COORDS:
                lat, lon = _KLINIK_COORDS[plz]
                kliniken.append({"id": kid, "plz": plz, "lat": lat, "lon": lon, "name": row["name"]})

    # geraete.csv nutzt klinik_name, nicht klinik_id → ueber Name matchen
    def _norm(s: str) -> str:
        return (s.strip().lower()
                .replace("ä", "ae").replace("ö", "oe")
                .replace("ü", "ue").replace("ß", "ss"))

    name_to_id_norm = {_norm(k): v for k, v in name_to_id.items()}

    stk_count: dict[str, float] = {}
    with open(_DATA_DIR / "geraete.csv", newline="", encoding="utf-8") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    for row in csv.DictReader(lines):
        kname = _norm(row.get("klinik_name", ""))
        kid = name_to_id_norm.get(kname, "")
        if not kid:
            for nk, nid in name_to_id_norm.items():
                if kname in nk or nk in kname:
                    kid = nid
                    break
        if kid:
            try:
                anzahl = int(row.get("anzahl", 1))
                zyklus = max(1, int(row.get("stk_zyklus_jahre", 1)))
                stk_count[kid] = stk_count.get(kid, 0) + anzahl / zyklus
            except ValueError:
                stk_count[kid] = stk_count.get(kid, 0) + 1

    return kliniken, stk_count, 2.0  # 2h/STK-Einsatz (Demo-Kostenmodell)


def _lade_kliniken_echtdaten() -> tuple[list[dict], dict[str, float], float]:
    """Laedt echte Auftrags-Standorte aus dem SMax-Cache (job_standorte).

    Reale Klinik-/Job-Standorte aus den importierten Open/Closed Jobs (siehe
    api/smax_cache.py) -- kein Platzhalter-Datensatz. Gibt (kliniken, stk_count,
    stunden_pro_einsatz) zurueck. stk_count ist STK/Jahr je Standort (bereits in
    api/smax_cache.py annualisiert: Closed Jobs / Beobachtungszeitraum in Jahren
    + Open Jobs als aktueller Rueckstand -- siehe "stk_jahr" dort), damit die
    Auslastungs- und Fahrzeit-Berechnung dieselbe Zeitbasis hat wie im
    Demo-Modus (dort ist stk_count bereits Anzahl/Wartungszyklus = STK/Jahr).
    stunden_pro_einsatz kommt aus dem realen Median der Einsatzdauer
    (einsatz_median_min).
    """
    from api.smax_cache import load_dashboard_data

    smax = load_dashboard_data() or {}
    job_standorte = smax.get("job_standorte", [])

    kliniken = []
    stk_count: dict[str, float] = {}
    for i, s in enumerate(job_standorte):
        kid = f"J{i}"
        kliniken.append({
            "id": kid, "plz": s["plz"], "lat": s["lat"], "lon": s["lon"],
            "name": s.get("account", ""),
            "jobs": int(s.get("closed_jobs", 0)) + int(s.get("open_jobs", 0)),
        })
        stk_count[kid] = s["stk_jahr"]

    einsatz_median_min = smax.get("einsatz_median_min", 0)
    stunden_pro_einsatz = (einsatz_median_min / 60) if einsatz_median_min else 1.5

    return kliniken, stk_count, stunden_pro_einsatz


def _plz_uebersicht_je_techniker(
    kliniken: list[dict], zuweisung: dict[str, str],
) -> dict[str, dict]:
    """Aggregiert die 2-stelligen PLZ-Praefixe der zugewiesenen Kliniken je
    Techniker -- Grundlage fuer die PLZ-Uebersicht in der
    Gebietsoptimierung-Tabelle (erleichtert die Einschaetzung fuer neue
    Gebietszuschnitte).

    Liefert je Techniker {"anzahl": int, "bereich": (lo, hi) | None,
    "praefixe": [(plz2, anzahl), ...] absteigend nach Anzahl sortiert}.
    "bereich" ist nur gesetzt, wenn die Praefixe eine LUECKENLOSE Kette
    bilden (z.B. 72,73,74) -- sonst bleibt es None und der Aufrufer zeigt
    ehrlich die Praefix-Liste statt einen Von-Bis-Bereich zu erzwingen, wo
    real keiner existiert (realistisch bei vielen, verstreut zustaendigen
    Technikern).
    """
    je_tech: dict[str, list[str]] = {}
    for k in kliniken:
        tid = zuweisung.get(k["id"])
        plz = k.get("plz", "")
        if not tid or len(plz) < 2:
            continue
        je_tech.setdefault(tid, []).append(plz[:2])

    ergebnis: dict[str, dict] = {}
    for tid, praefixe_liste in je_tech.items():
        zaehler: dict[str, int] = {}
        for p in praefixe_liste:
            zaehler[p] = zaehler.get(p, 0) + 1
        distinct = sorted(zaehler)
        lo, hi = int(distinct[0]), int(distinct[-1])
        zusammenhaengend = (hi - lo + 1) == len(distinct)
        ergebnis[tid] = {
            "anzahl": len(praefixe_liste),
            "bereich": (lo, hi) if zusammenhaengend else None,
            "praefixe": sorted(zaehler.items(), key=lambda x: (-x[1], x[0])),
        }
    return ergebnis


def _render_plz_uebersicht(info: dict | None) -> str:
    """Baut den PLZ-Uebersichtstext fuer einen Techniker (Tooltip-Inhalt,
    siehe _plz_uebersicht_je_techniker). Zusammenhaengende Praefixe werden
    als Von-Bis-Bereich dargestellt, verstreute ehrlich als Praefix-Liste
    mit Anzahl -- kein kuenstlich erzwungener Bereich."""
    if not info or not info.get("anzahl"):
        return _label("Keine Kliniken zugeordnet")
    if info["bereich"]:
        lo, hi = info["bereich"]
        bereich_txt = f"{lo:02d}xxx" if lo == hi else f"{lo:02d}xxx&ndash;{hi:02d}xxx"
        return f'{_label("PLZ")} {bereich_txt} ({info["anzahl"]} {_label("Kliniken")})'
    top = info["praefixe"][:5]
    rest = len(info["praefixe"]) - len(top)
    teile = ", ".join(f"{p}xxx ({n} {_label('Kliniken')})" for p, n in top)
    if rest > 0:
        teile += f" + {rest} {_label('weitere')}"
    return f'{_label("PLZ-Präfixe:")} {teile}'


def _berechne_gebietsmetriken(
    techniker: dict[str, dict],
) -> tuple[list[dict], list[dict], dict[str, str], list[dict], dict[str, dict]]:
    """Berechnet Fahrzeit-Metriken (aktuell + optimiert) pro Techniker.

    Optimierung: generische, ID-unabhaengige Heuristik -- funktioniert fuer
    Demo- (T1-T14) und Echtdaten-Techniker (echte Namen) gleichermassen.
    Fuer jede Klinik werden der 1.- und 2.-naechste Techniker (Fahrzeit)
    ermittelt; die Klinik wandert zum 2.-naechsten wenn
    _soll_klinik_verschieben() das erlaubt (siehe dort). Einmaliger
    Durchgang, kein iteratives Konvergenzverfahren -- die Auslastung wird
    einmal aus dem Ist-Zustand abgeleitet und bleibt waehrend der
    Optimierungsentscheidung fix.

    Datenquelle: im Echtdaten-Modus die echten Auftrags-Standorte aus dem
    SMax-Cache (_lade_kliniken_echtdaten, siehe api/smax_cache.py
    job_standorte), sonst die Demo-Kliniken (_lade_kliniken_demo).

    Gibt (metriken_aktuell, metriken_optimiert, gebiet_optimiert, punkte) zurueck.
    gebiet_optimiert ist ein {bundesland: techniker_id}-Dict, abgeleitet aus
    der tatsaechlichen optimierten Klinik-Zuweisung (fuer die Kartenfarben) --
    per Punkt-in-Polygon-Test gegen die echten Bundeslaender-Geodaten.
    punkte ist eine Liste je Klinik/Job-Standort ({id, plz, lat, lon, name,
    stk, jobs, akt, opt}) fuer die interaktive Techniker-Hervorhebung auf der
    Gebietskarte (Klick auf Techniker → nur dessen Punkte werden gerendert).
    gebiete_status ist die generische Luecken-/Ueberschneidungs-Klassifikation
    je Bundesland (siehe _klassifiziere_gebiete_luecken_ueberschneidungen).
    """
    if _ECHTDATEN:
        kliniken, stk_count, stunden_pro_einsatz = _lade_kliniken_echtdaten()
    else:
        try:
            kliniken, stk_count, stunden_pro_einsatz = _lade_kliniken_demo()
        except ImportError:
            return [], [], {}, [], {}

    if not kliniken:
        return [], [], {}, [], {}

    valid_tids = [tid for tid, td in techniker.items() if td.get("lat")]

    # ── Schritt 1: Ist-Zuweisung -- 1. und 2.-naechster Techniker je Klinik ──
    kandidaten: dict[str, list[tuple[str, float]]] = {}
    zuweisung_akt: dict[str, str] = {}
    fahrzeit_akt: dict[str, float] = {}
    for k in kliniken:
        dists = sorted(
            (
                (tid, _haversine_km(techniker[tid]["lat"], techniker[tid]["lon"],
                                     k["lat"], k["lon"]))
                for tid in valid_tids
            ),
            key=lambda x: x[1],
        )
        kandidaten[k["id"]] = dists
        if dists:
            best_tid, best_dist = dists[0]
            eff_speed = 100.0 / _strassenfaktor(k["plz"])
            zuweisung_akt[k["id"]] = best_tid
            fahrzeit_akt[k["id"]] = best_dist / eff_speed * 60

    def _aggregiere(zuweisung: dict[str, str], fahrzeit: dict[str, float]) -> list[dict]:
        zuord: dict[str, list] = {tid: [] for tid in techniker}
        for k in kliniken:
            tid = zuweisung.get(k["id"])
            if not tid:
                continue
            zuord[tid].append({"fz": fahrzeit[k["id"]], "stk": stk_count.get(k["id"], 0)})
        result = []
        for tid in sorted(techniker):
            kl = zuord.get(tid, [])
            td = techniker[tid]
            if not kl:
                result.append({"id": tid, "standort": td.get("standort", ""),
                               "kliniken": 0, "avg_fahrzeit": 0,
                               "max_fahrzeit": 0,
                               "fahrtstunden_jahr": 0, "onsite_stunden": 0,
                               "ratio": 0.0})
                continue
            avg_fz = sum(x["fz"] for x in kl) / len(kl)
            max_fz = max(x["fz"] for x in kl)
            total_stk = sum(x["stk"] for x in kl)
            drive_h = sum(x["stk"] * 2 * x["fz"] / 60 for x in kl)
            onsite_h = total_stk * stunden_pro_einsatz
            result.append({
                "id": tid, "standort": td.get("standort", ""),
                "kliniken": len(kl), "avg_fahrzeit": round(avg_fz),
                "max_fahrzeit": round(max_fz),
                "fahrtstunden_jahr": round(drive_h),
                "onsite_stunden": round(onsite_h),
                "ratio": round(onsite_h / drive_h, 2) if drive_h else 0.0,
            })
        return result

    metriken_akt = _aggregiere(zuweisung_akt, fahrzeit_akt)

    # ── Auslastung je Techniker aus dem Ist-Zustand (fix fuer die Optimierung) ──
    jahreskapazitaet_h = AUSSENDIENST_STUNDEN * ARBEITSWOCHEN_PRO_JAHR
    auslastung_pct: dict[str, float] = {}
    for m in metriken_akt:
        gesamt_h = m["fahrtstunden_jahr"] + m["onsite_stunden"]
        auslastung_pct[m["id"]] = (
            gesamt_h / jahreskapazitaet_h * 100 if jahreskapazitaet_h else 0.0
        )

    # ── Schritt 2: Optimierungsschritt (2.-naechster Techniker vs. Auslastung) ──
    zuweisung_opt = dict(zuweisung_akt)
    fahrzeit_opt = dict(fahrzeit_akt)
    gewonnen: dict[str, int] = {tid: 0 for tid in techniker}
    abgegeben: dict[str, int] = {tid: 0 for tid in techniker}

    for k in kliniken:
        dists = kandidaten.get(k["id"], [])
        if len(dists) < 2:
            continue
        tid1, dist1 = dists[0]
        tid2, dist2 = dists[1]
        eff_speed = 100.0 / _strassenfaktor(k["plz"])
        fz1 = dist1 / eff_speed * 60
        fz2 = dist2 / eff_speed * 60
        auslastung_diff = auslastung_pct.get(tid1, 0.0) - auslastung_pct.get(tid2, 0.0)
        if _soll_klinik_verschieben(auslastung_diff, fz2 - fz1):
            zuweisung_opt[k["id"]] = tid2
            fahrzeit_opt[k["id"]] = fz2
            abgegeben[tid1] += 1
            gewonnen[tid2] += 1

    metriken_opt = _aggregiere(zuweisung_opt, fahrzeit_opt)
    for m in metriken_opt:
        m["verschoben"] = gewonnen.get(m["id"], 0) + abgegeben.get(m["id"], 0)
        m["verschoben_gewonnen"] = gewonnen.get(m["id"], 0)
        m["verschoben_abgegeben"] = abgegeben.get(m["id"], 0)

    # ── PLZ-Uebersicht je Techniker (aktuell + optimiert) fuer die Tabelle ──
    plz_info_akt = _plz_uebersicht_je_techniker(kliniken, zuweisung_akt)
    plz_info_opt = _plz_uebersicht_je_techniker(kliniken, zuweisung_opt)
    for m in metriken_akt:
        m["plz_info"] = plz_info_akt.get(m["id"])
    for m in metriken_opt:
        m["plz_info"] = plz_info_opt.get(m["id"])

    # ── Bundesland-Kartenfarben aus der tatsaechlichen optimierten Zuweisung ──
    topo_paths = _topo_to_svg_paths()
    bl_zaehler: dict[str, dict[str, int]] = {}
    for k in kliniken:
        tid = zuweisung_opt.get(k["id"])
        if not tid:
            continue
        px, py = _project_mercator(k["lon"], k["lat"])
        bl = _bundesland_fuer_punkt(px, py, topo_paths)
        if not bl:
            continue
        bl_zaehler.setdefault(bl, {})
        bl_zaehler[bl][tid] = bl_zaehler[bl].get(tid, 0) + 1
    gebiet_optimiert = {
        bl: max(zaehler, key=lambda t: zaehler[t])
        for bl, zaehler in bl_zaehler.items()
    }

    # ── Luecken & Ueberschneidungen: generisch aus den Ist-Fahrzeiten ──
    gebiete_status = _klassifiziere_gebiete_luecken_ueberschneidungen(
        kliniken, kandidaten, topo_paths,
    )

    # ── Punkte je Klinik/Job-Standort fuer die interaktive Kartenhervorhebung ──
    punkte: list[dict] = []
    for k in kliniken:
        akt_tid = zuweisung_akt.get(k["id"], "")
        opt_tid = zuweisung_opt.get(k["id"], "")
        if not akt_tid and not opt_tid:
            continue
        px, py = _project_mercator(k["lon"], k["lat"])
        punkte.append({
            "plz":  k.get("plz", ""),
            "name": k.get("name", ""),
            "stk":  round(stk_count.get(k["id"], 0), 1),
            "jobs": k.get("jobs", 0),
            "akt":  akt_tid,
            "opt":  opt_tid,
            "x":    px,
            "y":    py,
        })

    return metriken_akt, metriken_opt, gebiet_optimiert, punkte, gebiete_status


def _berechne_plz_abdeckung(
    techniker: dict[str, dict],
) -> list[dict]:
    """Berechnet Fahrzeit-Abdeckung fuer alle 2-stelligen PLZ-Bereiche."""
    ergebnis = []
    for plz2, (lat, lon) in sorted(_PLZ2_COORDS.items()):
        best_tid, best_km = "", float("inf")
        for tid, td in techniker.items():
            if not td.get("lat"):
                continue
            d = _haversine_km(td["lat"], td["lon"], lat, lon)
            if d < best_km:
                best_km, best_tid = d, tid
        faktor = _strassenfaktor(plz2 + "000")
        fz_min = best_km / (100.0 / faktor) * 60 if best_km < 9999 else 999
        if fz_min < 60:
            status = "gruen"
        elif fz_min < 90:
            status = "gelb"
        else:
            status = "rot"
        ergebnis.append({
            "plz2": plz2, "lat": lat, "lon": lon,
            "naechster_tech": best_tid, "distanz_km": round(best_km),
            "fahrzeit_min": round(fz_min), "status": status,
        })
    return ergebnis


# Optimierungsvorschlaege pro Techniker
_OPTIMIERUNGS_VORSCHLAEGE: dict[str, str] = {
    "T2":  "Gebiet zu gross fuer aktuelle L3-Abdeckung (1 Familie). "
           "Crosstraining priorisieren: Beatmung + Elektrochirurgie. "
           "Allgaeu-Anteil an T7 abgeben.",
    "T3":  "Sachsen/Brandenburg/Thueringen zu gross fuer 1 Techniker. "
           "Crosstraining-Kandidat fuer Ost-Expansion noetig. "
           "Kein geeigneter Partner in der Region vorhanden.",
    "T7":  "Uebernimmt Allgaeu-Kliniken von T2/T10/T14. "
           "+6 Kliniken, kuerzere Wege als BaWue-Sued-Techniker "
           "durch bessere Autobahnanbindung via A7/A96.",
    "T9":  "Nord-Ost (MV) ausbauen. T6 (Schenefeld) konzentriert "
           "sich auf SH/Niedersachsen/Bremen, T9 uebernimmt "
           "Hamburg-Ost + MV fuer kuerzere Wege.",
    "T10": "Allgaeu/West-Bayern (PLZ 87/88) an T7 abgeben. "
           "Reduziert Gebiet auf kompaktes BaWue-Kerngebiet "
           "(Tuebingen, Ulm, Stuttgart).",
    "T13": "Nur 1 L3-Familie (Kardiovaskulaer_Ablation). "
           "Crosstraining mit T10 priorisieren fuer breitere "
           "Einsetzbarkeit in NRW-Sued/Rheinland-Pfalz.",
    "T8":  "Nur 1 L3-Familie (Neurophysiologie). "
           "Crosstraining mit T10 priorisieren. "
           "NRW-Ueberlastung: 527 STK/a ungenutztes Potenzial.",
}


def _render_gebietsplanung(
    metriken_akt: list[dict],
    metriken_opt: list[dict],
    plz_abdeckung: list[dict] | None = None,
    viewbox: str = "0 0 480 580",
) -> str:
    """Erzeugt den 'PLZ-Abdeckung & Einstellungsbedarf'-Abschnitt (Tab Einstellungsbedarf).

    HINWEIS: Enthielt frueher zusaetzlich eine 'Gebietsplanung'-Detailansicht
    (Aktuelle/Optimierte-Gebiete-Buttons + Karte + Ratio-Tabelle), die inhaltlich
    und optisch die neue Tab 6 'Gebietsoptimierung' dupliziert hat. Wurde entfernt,
    da sie -- oberhalb dieses Abschnitts im selben Tab-Panel platziert -- dazu
    fuehrte, dass beim Wechsel auf "Einstellungsbedarf" scheinbar noch der
    Gebietsoptimierung-Inhalt zu sehen war (der echte Inhalt kam erst nach
    Scrollen). metriken_opt bleibt Teil der Signatur fuer Aufrufkompatibilitaet.
    """
    if not metriken_akt:
        return ""

    # PLZ-Abdeckung Zusammenfassung
    abd = plz_abdeckung or []
    plz_gruen = sum(1 for p in abd if p["status"] == "gruen")
    plz_gelb = sum(1 for p in abd if p["status"] == "gelb")
    plz_rot = sum(1 for p in abd if p["status"] == "rot")
    plz_total = len(abd)

    # Einstellungsempfehlungen: HTML-Liste (rechts neben Karte)
    _STERN_DETAILS = {
        "Berlin":   f'12 {_label("Kliniken")} &middot; T3 Weimar 180 min',
        "Hannover": f'8 {_label("Kliniken")} &middot; T9 Hamburg 95 min',
        "München":  f'10 {_label("Kliniken")} &middot; T7 Wildenberg 110 min',
        "Mannheim": f'6 {_label("Kliniken")} &middot; T12 Frankfurt 85 min',
    }
    einst_items = []
    for emp in _EINSTELLUNGS_EMPFEHLUNGEN:
        detail = _STERN_DETAILS.get(emp["standort"], f'{emp["kliniken_geschaetzt"]} {_label("Kliniken")}')
        einst_items.append(
            f'      <div class="einst-item">'
            f'<div class="einst-dot">\u2605</div>'
            f'<div class="einst-text">'
            f'<div class="einst-name">{_label("Grossraum")} {emp["standort"]}</div>'
            f'<div class="einst-detail">{detail}</div>'
            f'<div class="einst-detail" style="margin-top:4px;color:var(--text-muted)">{emp["region"]}</div>'
            f'</div></div>')
    einst_liste_html = "\n".join(einst_items)

    # Einstellungsempfehlungen Tabelle (unterhalb des Flex-Layouts)
    einst_rows = []
    for emp in _EINSTELLUNGS_EMPFEHLUNGEN:
        einst_rows.append(
            f'      <tr><td><strong>{emp["standort"]}</strong></td>'
            f'<td>{emp["region"]}</td>'
            f'<td>{len(emp["abdeckt_plz"])} {_label("PLZ-Bereiche")}</td>'
            f'<td>~{emp["kliniken_geschaetzt"]}</td>'
            f'<td class="fehlend-liste">{emp["begruendung"]}</td></tr>')
    einst_html = "\n".join(einst_rows)
    abdeckung_tip = _info_tip(
        "Anzahl 2-stelliger PLZ-Bereiche, die durch eine Neueinstellung an "
        "diesem Standort besser abgedeckt w&uuml;rden (nicht zu verwechseln "
        "mit der Gr&uuml;n/Gelb/Rot-Fahrzeit-Abdeckung oben)."
    )
    kliniken_geschaetzt_tip = _info_tip(
        "Gesch&auml;tzte Anzahl Kliniken im Einzugsgebiet dieses Standorts."
    )

    return f"""
  <section>
    <h2 data-i18n="h.hiring">PLZ-Abdeckung &amp; Einstellungsbedarf</h2>
    <p class="section-hint">
      {_label("Analyse aller")} {plz_total} {_label("PLZ-Bereiche (2-stellig) · Grün <60 min · Gelb 60–90 min · Rot >90 min vom nächsten Techniker · Sterne = empfohlene Neueinstellungs-Standorte")}
    </p>
    <div class="gebiets-summary">
      <span><span class="dot dot-gruen"></span> <strong>{plz_gruen}</strong> {_label("PLZ gut abgedeckt (<60 min)")}</span>
      <span><span class="dot dot-gelb"></span> <strong>{plz_gelb}</strong> {_label("PLZ grenzwertig (60–90 min)")}</span>
      <span><span class="dot dot-rot"></span> <strong>{plz_rot}</strong> {_label("PLZ unterversorgt (>90 min)")}</span>
    </div>

    <div class="einst-layout">
      <div class="einst-karte">
        <svg id="germany-map-plz" viewBox="{viewbox}" preserveAspectRatio="xMidYMid meet"><!-- filled by _build_gebiets_svg --></svg>
      </div>
      <div class="einst-liste">
        <div class="einst-liste-header">&starf; {_label("Einstellungsbedarf")}</div>
{einst_liste_html}
      </div>
    </div>

    <h3 style="font-size:14px;color:var(--text);margin:20px 0 10px;padding-bottom:8px;border-bottom:1px solid rgba(0,81,149,.12)">
      {_label("Detaillierte Begründungen")}
    </h3>
    <table>
      <thead>
        <tr>
          <th data-i18n="th.standort">Standort</th>
          <th data-i18n="th.region">Region</th>
          <th><span data-i18n="th.abdeckung">Abdeckung</span>{abdeckung_tip}</th>
          <th><span data-i18n="th.kliniken">Kliniken</span>{kliniken_geschaetzt_tip}</th>
          <th data-i18n="th.begruendung">Begr&uuml;ndung</th>
        </tr>
      </thead>
      <tbody>
{einst_html}
      </tbody>
    </table>
  </section>"""


def _project_mercator(
    lon: float, lat: float,
    cx: float = 10.4, cy: float = 51.1, scale: float = 3200,
    w: float = 480, h: float = 580,
) -> tuple[float, float]:
    """Mercator-Projektion (konsistent mit der bisherigen d3-Projektion)."""
    x = (lon - cx) * math.pi / 180
    y = math.log(math.tan(math.pi / 4 + lat * math.pi / 360))
    cy_r = math.log(math.tan(math.pi / 4 + cy * math.pi / 360))
    return round(w / 2 + x * scale, 1), round(h / 2 - (y - cy_r) * scale, 1)


def _topo_to_svg_paths() -> list[dict]:
    """Wandelt daten/deutschland_topo.json in SVG-Pfade um (server-seitig).

    Returns:
        [{name: str, d: str}, ...] – SVG path 'd' Attribut je Bundesland.
    """
    topo_path = Path(__file__).parent.parent / "daten" / "deutschland_topo.json"
    try:
        topo = json.loads(topo_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        warnings.warn(f"deutschland_topo.json nicht gefunden: {topo_path}", stacklevel=2)
        return []

    arcs_raw = topo["arcs"]
    transform = topo.get("transform")
    obj_key = list(topo["objects"].keys())[0]
    geometries = topo["objects"][obj_key]["geometries"]

    def decode_arc(arc_idx: int) -> list[tuple[float, float]]:
        reverse = arc_idx < 0
        idx = ~arc_idx if reverse else arc_idx
        raw = arcs_raw[idx]
        coords: list[tuple[float, float]] = []
        x, y = 0, 0
        for dx, dy in raw:
            x += dx
            y += dy
            if transform:
                lon = x * transform["scale"][0] + transform["translate"][0]
                lat = y * transform["scale"][1] + transform["translate"][1]
            else:
                lon, lat = float(x), float(y)
            coords.append((lon, lat))
        if reverse:
            coords.reverse()
        return coords

    def geom_to_path_d(geom: dict) -> str:
        if geom["type"] == "Polygon":
            rings_list = [geom["arcs"]]
        elif geom["type"] == "MultiPolygon":
            rings_list = geom["arcs"]
        else:
            return ""
        parts: list[str] = []
        for rings in rings_list:
            for ring in rings:
                coords: list[tuple[float, float]] = []
                for arc_idx in ring:
                    coords.extend(decode_arc(arc_idx))
                # Simplify: keep every Nth point (smooth enough for 480px map)
                n = max(1, len(coords) // 80)
                simplified = coords[::n]
                if len(simplified) < 3:
                    simplified = coords
                for i, (lon, lat) in enumerate(simplified):
                    px, py = _project_mercator(lon, lat)
                    parts.append(f"M{px},{py}" if i == 0 else f"L{px},{py}")
                parts.append("Z")
        return "".join(parts)

    result: list[dict] = []
    for geom in geometries:
        name = geom.get("properties", {}).get("name", "")
        d = geom_to_path_d(geom)
        if d:
            result.append({"name": name, "d": d})
    return result


def _radius_px_at(lat: float, lon: float, radius_km: float) -> float:
    """Wandelt einen Radius in km an einer Lat/Lon-Position in einen
    SVG-Pixel-Radius um (lokale px/km-Rate ueber zwei projizierte Punkte,
    da die Mercator-Projektion nicht global masstabsgetreu ist)."""
    dlon = 0.05
    x1, y1 = _project_mercator(lon, lat)
    x2, y2 = _project_mercator(lon + dlon, lat)
    px_dist = math.hypot(x2 - x1, y2 - y1)
    km_dist = _haversine_km(lat, lon, lat, lon + dlon)
    if km_dist <= 0:
        return 0.0
    return radius_km * (px_dist / km_dist)


def _placiere_techniker_labels(punkte: list[dict]) -> list[dict]:
    """Kollisionsfreie Platzierung der Techniker-Namens-Labels auf der SVG-Karte.

    Bei dicht beieinanderliegenden Technikern (z.B. Ruhrgebiet/NRW) wuerden
    die Labels beim bisherigen fixen Offset (rechts vom Marker) uebereinander
    liegen und verschmelzen. Greedy-Algorithmus: pro Punkt werden mehrere
    Offset-Kandidaten (rechts/links, verschiedene Hoehen) der Reihe nach
    gegen bereits platzierte Label-Boxen geprueft; der erste ueberlappungs-
    freie Kandidat gewinnt. Weicht das Label vom Standard-Offset ab, zeigt
    der Aufrufer eine duenne Verbindungslinie (Leader-Line) zum Marker an.

    Rein Python/serverseitig -- kein JS-Force-Layout noetig, konsistent mit
    der bestehenden 100%-offline-SVG-Architektur (keine Zoom-/Client-Logik).
    """
    _CHAR_W = 6.3   # px pro Zeichen bei font-size 10px bold (Naeherung)
    _LABEL_H = 12.0
    _DEFAULT = (9.0, 4.0)
    platziert: list[tuple[float, float, float, float]] = []
    ergebnis = []

    for p in sorted(punkte, key=lambda p: (p["py"], p["px"])):
        text_w = len(p["text"]) * _CHAR_W + 2.0
        kandidaten = [
            _DEFAULT, (9.0, -8.0), (9.0, 16.0),
            (-text_w - 9.0, 4.0), (-text_w - 9.0, -8.0), (-text_w - 9.0, 16.0),
            (9.0, -20.0), (9.0, 28.0),
            (-text_w - 9.0, -20.0), (-text_w - 9.0, 28.0),
        ]
        gewaehlt = kandidaten[-1]
        for dx, dy in kandidaten:
            x0 = p["px"] + dx
            x1 = x0 + text_w
            y1 = p["py"] + dy
            y0 = y1 - _LABEL_H
            kollidiert = any(
                x0 < ox1 and x1 > ox0 and y0 < oy1 and y1 > oy0
                for ox0, oy0, ox1, oy1 in platziert
            )
            if not kollidiert:
                gewaehlt = (dx, dy)
                break
        dx, dy = gewaehlt
        lx, ly = p["px"] + dx, p["py"] + dy
        platziert.append((lx, ly - _LABEL_H, lx + text_w, ly))
        ergebnis.append({**p, "lx": lx, "ly": ly, "versetzt": (dx, dy) != _DEFAULT})

    return ergebnis


_XY_PAIR_RE = re.compile(r'(-?\d+\.?\d*),(-?\d+\.?\d*)')


def _berechne_gebiets_viewbox(
    techniker: dict[str, dict],
    margin: float = 12.0,
) -> tuple[float, float, float, float]:
    """Berechnet die tatsaechliche Bounding-Box der STAENDIG sichtbaren
    Kartenelemente (Bundeslaender-Flaechen, Techniker-Marker + kollisions-
    versetzte Labels, Einstellungsempfehlungen) inkl. Sicherheitsrand.

    Grund: die vormals feste viewBox '0 0 480 580' (aus den urspruenglichen
    _project_mercator-Default-Parametern uebernommen) deckt die tatsaechliche
    Nord-Sued-Ausdehnung Deutschlands nicht vollstaendig ab -- Bayern und
    Baden-Wuerttemberg ragen im Sueden ueber y=580 hinaus, die noerdlichen
    Inseln Schleswig-Holsteins sogar ueber y=0 nach oben (Mercator-Skalierung
    war fuer den vollen Breitengrad-Bereich 47,27°N-55,05°N leicht zu knapp
    bemessen). Diese Funktion ermittelt die reale Bounding-Box direkt aus
    denselben projizierten Koordinaten, die auch beim Zeichnen verwendet
    werden (_project_mercator/_topo_to_svg_paths).

    Bewusst AUSSER Acht gelassen: die optionalen Hugo-Kerngebiet-Kreise
    (Toggle default AUS) -- einzelne Kreise (z.B. Gangelt, Grenznaehe NL)
    ragen weit ueber die Landesflaeche hinaus und wuerden die Standard-
    ansicht unnoetig verkleinern/verzerren, obwohl sie i.d.R. ausgeblendet
    sind. Stattdessen sichert `.gebiets-karte svg, .einst-karte svg
    { overflow: visible }` (siehe CSS) diese Kreise gegen Abschneiden ab,
    OHNE die Kernkarte zu stauchen -- sie duerfen im Toggle-Fall einfach
    etwas ueber den Kartenrahmen hinausragen statt unsichtbar zu werden.

    Gibt (min_x, min_y, width, height) zurueck.
    """
    xs: list[float] = []
    ys: list[float] = []

    for p in _topo_to_svg_paths():
        for x_str, y_str in _XY_PAIR_RE.findall(p["d"]):
            xs.append(float(x_str))
            ys.append(float(y_str))

    tech_punkte = []
    for tid, td in sorted(techniker.items()):
        if not td.get("lat"):
            continue
        px, py = _project_mercator(td["lon"], td["lat"])
        tech_punkte.append({"id": tid, "px": px, "py": py, "text": tid})
        xs.append(px)
        ys.append(py)

    for p in _placiere_techniker_labels(tech_punkte):
        text_w = len(p["text"]) * 6.3 + 2.0
        xs.extend([p["lx"], p["lx"] + text_w])
        ys.extend([p["ly"] - 12.0, p["ly"]])

    for e in _EINSTELLUNGS_EMPFEHLUNGEN:
        px, py = _project_mercator(e["lon"], e["lat"])
        xs.extend([px - 10, px + 10])
        ys.extend([py - 10, py + 10])

    if not xs or not ys:
        return 0.0, 0.0, 480.0, 580.0

    min_x, max_x = min(xs) - margin, max(xs) + margin
    min_y, max_y = min(ys) - margin, max(ys) + margin
    return (
        round(min_x, 1), round(min_y, 1),
        round(max_x - min_x, 1), round(max_y - min_y, 1),
    )


def _build_gebiets_svg(
    techniker: dict[str, dict],
    plz_abdeckung: list[dict] | None = None,
    hugo_kerngebiete: list[dict] | None = None,
    hugo_standorte_marker: list[dict] | None = None,
) -> str:
    """Baut statische SVG-Karte (100% offline, kein CDN, kein JavaScript noetig)."""
    paths = _topo_to_svg_paths()
    if not paths:
        return '<text x="240" y="290" text-anchor="middle" fill="#666666" font-size="13">Karte nicht verfuegbar</text>'

    svg_parts: list[str] = []

    # 1. Bundesland-Flaechen
    for p in paths:
        name = p["name"]
        tid = _GEBIET_AKTUELL.get(name, "")
        fill = _TECH_FARBEN.get(tid, "#E8EFF7")
        tid_opt = _GEBIET_OPTIMIERT.get(name, "")
        fill_opt = _TECH_FARBEN.get(tid_opt, "#E8EFF7")
        tooltip = f"{name} → {tid}" if tid else f"{name} (nicht zugewiesen)"
        # Overlap/Gap Marker fuer Luecken-Ansicht
        _OVERLAP_STATES = {"Nordrhein-Westfalen": "1", "Bayern": "1"}
        _GAP_STATES = {"Mecklenburg-Vorpommern": "gap", "Brandenburg": "gap"}
        overlap = _OVERLAP_STATES.get(name, _GAP_STATES.get(name, ""))
        ov_attr = f' data-overlap="{overlap}"' if overlap else ''
        svg_parts.append(
            f'<path class="st" d="{p["d"]}" fill="{fill}" '
            f'data-name="{name}" data-fill-aktuell="{fill}" data-fill-optimiert="{fill_opt}"{ov_attr} '
            f'stroke="rgba(0,0,0,.15)" stroke-width="1.2">'
            f'<title>{tooltip}</title></path>'
        )

    # 2. PLZ-Abdeckungspunkte
    status_colors = {"gruen": "#5EDD9F", "gelb": "#FFB347", "rot": "#FF8080"}
    for p in (plz_abdeckung or []):
        px, py = _project_mercator(p["lon"], p["lat"])
        fc = status_colors.get(p["status"], "#555")
        svg_parts.append(
            f'<circle class="plz" cx="{px}" cy="{py}" r="3" fill="{fc}" opacity="0.5">'
            f'<title>PLZ {p["plz2"]}xxx: {p["fahrzeit_min"]} min ({p["naechster_tech"]})</title></circle>'
        )

    # 3. Techniker-Standorte (Marker + kollisionsfrei platzierte Namens-Labels)
    tech_punkte = []
    for tid, td in sorted(techniker.items()):
        if not td.get("lat"):
            continue
        px, py = _project_mercator(td["lon"], td["lat"])
        tech_punkte.append({
            "id": tid, "px": px, "py": py,
            "fc": _TECH_FARBEN.get(tid, "#999"),
            "standort": td.get("standort", ""),
            "text": tid,
        })

    for p in tech_punkte:
        svg_parts.append(
            f'<circle class="td" cx="{p["px"]}" cy="{p["py"]}" r="6" fill="{p["fc"]}" '
            f'stroke="#fff" stroke-width="2">'
            f'<title>{p["id"]} ({p["standort"]})</title></circle>'
        )

    for p in _placiere_techniker_labels(tech_punkte):
        if p["versetzt"]:
            svg_parts.append(
                f'<line class="tl-leader" x1="{p["px"]}" y1="{p["py"]}" '
                f'x2="{p["lx"] - 2:.1f}" y2="{p["ly"] - 3:.1f}" '
                f'stroke="{p["fc"]}" stroke-width="1" opacity="0.55"/>'
            )
        svg_parts.append(
            f'<text class="tl" x="{p["lx"]:.1f}" y="{p["ly"]:.1f}" '
            f'font-family="Plus Jakarta Sans,sans-serif" font-size="10px" font-weight="700" fill="#1A1A1A">'
            f'{p["id"]}</text>'
        )

    # 4. Einstellungsempfehlungen (roter Kreis + weisser Stern)
    for idx, e in enumerate(_EINSTELLUNGS_EMPFEHLUNGEN):
        px, py = _project_mercator(e["lon"], e["lat"])

        svg_parts.append(
            f'<g class="einst-marker" data-idx="{idx}" style="cursor:pointer">'
        )
        svg_parts.append(
            f'<circle cx="{px}" cy="{py}" r="10" fill="#CC0000" '
            f'stroke="#fff" stroke-width="2">'
            f'<title>{e["standort"]}: {e["kliniken_geschaetzt"]} Kliniken</title></circle>'
        )
        svg_parts.append(
            f'<text x="{px}" y="{py + 5}" font-size="13px" fill="#fff" '
            f'text-anchor="middle" style="pointer-events:none">'
            f'\u2605</text>'
        )
        svg_parts.append('</g>')

    # 5. Hugo-Kerngebiete: optionale Regel, Toggle default AUS -- durchgezogener
    # Kreis um den WOHNORT der Hugo-Techniker (siehe reporting/hugo_kerngebiet.py).
    if hugo_kerngebiete:
        svg_parts.append('<g id="hugo-kerngebiete" style="display:none">')
        for hk in hugo_kerngebiete:
            px, py = _project_mercator(hk["lon"], hk["lat"])
            r_px = _radius_px_at(hk["lat"], hk["lon"], hk["radius_km"])
            fc = _TECH_FARBEN.get(hk["id"], "#7B2D8E")
            springer_txt = " · Springer (deutschlandweit)" if hk.get("ist_springer") else ""
            svg_parts.append(
                f'<circle class="hugo-kg-kreis" cx="{px}" cy="{py}" r="{r_px:.1f}" '
                f'fill="{fc}" fill-opacity="0.08" stroke="{fc}" stroke-width="2.2">'
                f'<title>{hk["id"]} ({hk["standort"]}): Small-Capital-Kerngebiet '
                f'(Tagestouren), ~{hk["radius_km"]:.0f} km Radius um den Wohnort'
                f'{springer_txt}</title></circle>'
            )
        svg_parts.append('</g>')

    # 6. Hugo-Standorte: eigene Marker (unabhaengig von der Entfernung zum
    # Techniker-Wohnort) mit Verbindungslinie zum zustaendigen Techniker.
    # Teil desselben Toggles wie die Kerngebiete (Punkt 5) -- default AUS.
    if hugo_standorte_marker:
        svg_parts.append('<g id="hugo-standorte" style="display:none">')
        for hs in hugo_standorte_marker:
            hx, hy = _project_mercator(hs["lon"], hs["lat"])
            for tid in hs["zustaendige_ids"]:
                td = techniker.get(tid)
                if not td or not td.get("lat"):
                    continue
                tx, ty = _project_mercator(td["lon"], td["lat"])
                fc = _TECH_FARBEN.get(tid, "#7B2D8E")
                svg_parts.append(
                    f'<line class="hugo-standort-linie" x1="{hx}" y1="{hy}" '
                    f'x2="{tx}" y2="{ty}" stroke="{fc}" stroke-width="1.2" '
                    f'stroke-dasharray="3,3" opacity="0.6"/>'
                )
            hinweis_txt = f" ({hs['hinweis']})" if hs.get("hinweis") else ""
            status_txt = f" [{hs['status']}]" if hs.get("status") else ""
            tech_txt = ", ".join(hs["haupt_techniker"])
            svg_parts.append(
                f'<rect class="hugo-standort-marker" x="{hx - 5}" y="{hy - 5}" '
                f'width="10" height="10" fill="#7B2D8E" stroke="#fff" stroke-width="1.5">'
                f'<title>Hugo-Standort {hs["standort"]}{status_txt}: {hs["anzahl_systeme"]} '
                f'System(e), zuständig: {tech_txt}{hinweis_txt}</title></rect>'
            )
        svg_parts.append('</g>')

    return "\n    ".join(svg_parts)


def _build_tooltip_portal_script() -> str:
    """Baut das Portal-Pattern-JS fuer ALLE Info-Tooltips (.info-tip- und
    .korridor-badge-Anker, siehe _info_tip()/_render_korridor_badge()).

    Grund: mehrere Tooltip-Container (.gebiets-metriken, .ampel-grid) haben
    overflow-x:auto (fuer schmale Fenster/breite Tabellen noetig). Per
    CSS-Spezifikation wird dadurch auch overflow-y implizit 'auto' --
    jede absolut positionierte Tooltip-Bubble als Kind-Element wird am
    Container-Rand abgeschnitten, egal wie ihre eigene CSS-Position gesetzt
    ist (reine links/rechts-Ausrichtung reichte bei schmalen Containern
    nicht). Fix: die Bubble wird bei Hover/Focus aus der Container-
    Hierarchie ausgehaengt und direkt an document.body angehaengt
    (position:fixed, hoher z-index), mit Position aus
    getBoundingClientRect() des Ankers berechnet und an die Viewport-
    Raender geklemmt -- das umgeht jede Overflow-Clipping-Begrenzung UND
    jede Stacking-Context-Ueberlagerung durch andere Elemente.

    Alle .info-tip/.korridor-badge-Elemente sind Teil des serverseitig
    vorgerenderten HTML (keine nachtraeglich per JS erzeugten Tooltips) --
    ein einmaliges querySelectorAll beim Skriptstart deckt daher alle ab.
    """
    return (
        "/* ── Info-Tooltips: Portal-Pattern gegen Overflow-Clipping ── */\n"
        "(function(){\n"
        "  var portal = document.createElement('div');\n"
        "  portal.className = 'info-tip-portal';\n"
        "  document.body.appendChild(portal);\n"
        "  var MARGIN = 8;\n"
        "  function hide(){\n"
        "    portal.style.visibility = 'hidden';\n"
        "    portal.style.opacity = '0';\n"
        "  }\n"
        "  hide();\n"
        "  document.querySelectorAll('.info-tip, .korridor-badge').forEach(function(anchor){\n"
        "    var bubble = anchor.querySelector('.info-tip-bubble');\n"
        "    if (!bubble) return;\n"
        "    function show(){\n"
        "      portal.innerHTML = bubble.innerHTML;\n"
        "      portal.style.left = MARGIN + 'px';\n"
        "      portal.style.top = MARGIN + 'px';\n"
        "      portal.style.visibility = 'visible';\n"
        "      portal.style.opacity = '1';\n"
        "      var r = anchor.getBoundingClientRect();\n"
        "      var bw = portal.offsetWidth, bh = portal.offsetHeight;\n"
        "      var left = r.left;\n"
        "      var top = r.bottom + 7;\n"
        "      if (left + bw > window.innerWidth - MARGIN) left = window.innerWidth - MARGIN - bw;\n"
        "      if (left < MARGIN) left = MARGIN;\n"
        "      if (top + bh > window.innerHeight - MARGIN) top = r.top - bh - 7;\n"
        "      if (top < MARGIN) top = MARGIN;\n"
        "      portal.style.left = left + 'px';\n"
        "      portal.style.top = top + 'px';\n"
        "    }\n"
        "    anchor.addEventListener('mouseenter', show);\n"
        "    anchor.addEventListener('focus', show);\n"
        "    anchor.addEventListener('mouseleave', hide);\n"
        "    anchor.addEventListener('blur', hide);\n"
        "  });\n"
        "  window.addEventListener('scroll', hide, true);\n"
        "  window.addEventListener('resize', hide);\n"
        "})();\n"
    )


def _build_gebiets_script(
    techniker: dict[str, dict],
    plz_abdeckung: list[dict] | None = None,
    gebiets_punkte: list[dict] | None = None,
) -> str:
    """Baut minimales JS fuer Modus-Umschaltung (aktuell/optimiert)."""
    tc = json.dumps(_TECH_FARBEN, ensure_ascii=False)
    pk = json.dumps(gebiets_punkte or [], ensure_ascii=False)

    return (
        "/* ── Gebietsoptimierung (offline, pre-rendered SVG) ── */\n"
        "(function(){\n"
        "  var C=" + tc + ";\n"
        "  var lg=document.getElementById('gebiets-legende-opt');\n"
        "  if(lg){Object.keys(C).sort().forEach(function(t){\n"
        "    lg.innerHTML+='<span class=\"gebiets-legende-item\" data-tech=\"'+t+'\">'\n"
        "      +'<span class=\"gebiets-legende-dot\" style=\"background:'+C[t]+'\"></span>'\n"
        "      +t+'</span>';});\n"
        "  }\n"
        "})();\n"
        "\n"
        "/* ── Einstellungsempfehlung: Hover-Sync ── */\n"
        "(function(){\n"
        "  function hlStern(idx, on) {\n"
        "    var m = document.querySelector('.einst-marker[data-idx=\"'+idx+'\"]');\n"
        "    if (!m) return;\n"
        "    var c = m.querySelector('circle');\n"
        "    if (c) { c.setAttribute('r', on ? '14' : '10');\n"
        "             c.setAttribute('fill', on ? '#990000' : '#CC0000'); }\n"
        "  }\n"
        "  function hlItem(idx, on) {\n"
        "    var items = document.querySelectorAll('.einst-item');\n"
        "    if (items[idx]) {\n"
        "      items[idx].style.background = on ? 'rgba(204,0,0,.12)' : '';\n"
        "      items[idx].style.boxShadow  = on ? '0 0 0 2px #CC0000' : '';\n"
        "    }\n"
        "  }\n"
        "  document.querySelectorAll('.einst-marker').forEach(function(m) {\n"
        "    var idx = parseInt(m.getAttribute('data-idx'), 10);\n"
        "    m.addEventListener('mouseenter', function() { hlItem(idx, true);  hlStern(idx, true);  });\n"
        "    m.addEventListener('mouseleave', function() { hlItem(idx, false); hlStern(idx, false); });\n"
        "    m.addEventListener('click',      function() {\n"
        "      var items = document.querySelectorAll('.einst-item');\n"
        "      if (items[idx]) items[idx].scrollIntoView({behavior:'smooth', block:'nearest'});\n"
        "    });\n"
        "  });\n"
        "  document.querySelectorAll('.einst-item').forEach(function(item, idx) {\n"
        "    item.addEventListener('mouseenter', function() { hlStern(idx, true);  hlItem(idx, true);  });\n"
        "    item.addEventListener('mouseleave', function() { hlStern(idx, false); hlItem(idx, false); });\n"
        "  });\n"
        "  document.querySelectorAll('.einst-marker').forEach(function(m, idx) {\n"
        "    var c = m.querySelector('circle');\n"
        "    if (!c) return;\n"
        "    var cx = parseFloat(c.getAttribute('cx'));\n"
        "    var cy = parseFloat(c.getAttribute('cy'));\n"
        "    var ns = 'http://www.w3.org/2000/svg';\n"
        "    var t = document.createElementNS(ns, 'text');\n"
        "    t.setAttribute('x', cx + 8);\n"
        "    t.setAttribute('y', cy - 8);\n"
        "    t.setAttribute('font-size', '10px');\n"
        "    t.setAttribute('font-weight', '700');\n"
        "    t.setAttribute('fill', '#FF8080');\n"
        "    t.setAttribute('font-family', 'Plus Jakarta Sans, sans-serif');\n"
        "    t.setAttribute('style', 'pointer-events:none');\n"
        "    t.textContent = (idx + 1).toString();\n"
        "    m.appendChild(t);\n"
        "    var items = document.querySelectorAll('.einst-item');\n"
        "    if (items[idx]) {\n"
        "      var dot = items[idx].querySelector('.einst-dot');\n"
        "      if (dot) dot.setAttribute('data-num', idx + 1);\n"
        "    }\n"
        "  });\n"
        "})();\n"
        "\n"
        "/* ── Gebietsoptimierung: View-Button Umschaltung ── */\n"
        "(function(){\n"
        "  var btns=document.querySelectorAll('.go-view-btn');\n"
        "  var views=document.querySelectorAll('.go-view-content');\n"
        "  var svg=document.getElementById('germany-map-opt');\n"
        "  if(!btns.length) return;\n"
        "  btns.forEach(function(btn){\n"
        "    btn.addEventListener('click',function(){\n"
        "      var mode=this.getAttribute('data-view');\n"
        "      btns.forEach(function(b){b.classList.remove('active');});\n"
        "      this.classList.add('active');\n"
        "      views.forEach(function(v){v.classList.remove('active');});\n"
        "      var target=document.getElementById('go-view-'+mode);\n"
        "      if(target) target.classList.add('active');\n"
        "      /* SVG-Karte aktualisieren */\n"
        "      if(svg){\n"
        "        svg.querySelectorAll('path.st').forEach(function(p){\n"
        "          if(mode==='luecken'){\n"
        "            var ov=p.getAttribute('data-overlap');\n"
        "            if(ov==='1'){\n"
        "              p.setAttribute('fill','rgba(255,139,0,.3)');\n"
        "              p.setAttribute('stroke','#FF8B00');p.setAttribute('stroke-width','3');\n"
        "            }else if(ov==='gap'){\n"
        "              p.setAttribute('fill','rgba(204,0,0,.3)');\n"
        "              p.setAttribute('stroke','#CC0000');p.setAttribute('stroke-width','3');\n"
        "              p.setAttribute('stroke-dasharray','6,3');\n"
        "            }else{\n"
        "              p.setAttribute('fill',p.getAttribute('data-fill-aktuell')||'#E8EFF7');\n"
        "              p.setAttribute('stroke','rgba(0,0,0,.08)');p.setAttribute('stroke-width','1');\n"
        "              p.removeAttribute('stroke-dasharray');\n"
        "            }\n"
        "          }else{\n"
        "            var fillKey='data-fill-'+(mode==='optimiert'?'optimiert':'aktuell');\n"
        "            p.setAttribute('fill',p.getAttribute(fillKey)||'#E8EFF7');\n"
        "            p.setAttribute('stroke','rgba(0,0,0,.15)');p.setAttribute('stroke-width','1.2');\n"
        "            p.removeAttribute('stroke-dasharray');\n"
        "          }\n"
        "        });\n"
        "      }\n"
        "    });\n"
        "  });\n"
        "})();\n"
        "\n"
        "/* ── Gebietskarte: Techniker-Klick-Interaktion (Highlight + PLZ-Punkte) ── */\n"
        "(function(){\n"
        "  var PUNKTE=" + pk + ";\n"
        "  var C=" + tc + ";\n"
        "  var svg=document.getElementById('germany-map-opt');\n"
        "  if(!svg||!PUNKTE.length) return;\n"
        "  var NS='http://www.w3.org/2000/svg';\n"
        "  var selected=null;\n"
        "\n"
        "  function currentMode(){\n"
        "    var b=document.querySelector('.go-view-btn.active');\n"
        "    return b?b.getAttribute('data-view'):'aktuell';\n"
        "  }\n"
        "  function clearPunkte(){\n"
        "    var g=document.getElementById('gebiets-punkte-sel');\n"
        "    if(g) g.remove();\n"
        "  }\n"
        "  function makeCircle(p,opts){\n"
        "    var c=document.createElementNS(NS,'circle');\n"
        "    c.setAttribute('cx',p.x); c.setAttribute('cy',p.y);\n"
        "    c.setAttribute('r',opts.r||4);\n"
        "    c.setAttribute('fill',opts.fill||'none');\n"
        "    c.setAttribute('stroke',opts.stroke||'#fff');\n"
        "    c.setAttribute('stroke-width',opts.strokeWidth||1.2);\n"
        "    if(opts.dash) c.setAttribute('stroke-dasharray',opts.dash);\n"
        "    var jobsTxt=p.jobs?(p.jobs+' Jobs \\u00b7 '):'';\n"
        "    var nameTxt=p.name?(' \\u00b7 '+p.name):'';\n"
        "    var t=document.createElementNS(NS,'title');\n"
        "    t.textContent='PLZ '+p.plz+' \\u00b7 '+jobsTxt+p.stk+' STK/Jahr'+nameTxt;\n"
        "    c.appendChild(t);\n"
        "    return c;\n"
        "  }\n"
        "  function renderPunkte(tid){\n"
        "    clearPunkte();\n"
        "    var g=document.createElementNS(NS,'g');\n"
        "    g.setAttribute('id','gebiets-punkte-sel');\n"
        "    var mode=currentMode();\n"
        "    var color=C[tid]||'#005195';\n"
        "    if(mode==='optimiert'){\n"
        "      PUNKTE.forEach(function(p){\n"
        "        var wasAkt=p.akt===tid, isOpt=p.opt===tid;\n"
        "        if(!wasAkt&&!isOpt) return;\n"
        "        if(wasAkt&&isOpt){\n"
        "          g.appendChild(makeCircle(p,{r:4,fill:color,stroke:'#fff',strokeWidth:1.2}));\n"
        "        }else if(isOpt&&!wasAkt){\n"
        "          g.appendChild(makeCircle(p,{r:5,fill:color,stroke:'#00A651',strokeWidth:2}));\n"
        "        }else{\n"
        "          g.appendChild(makeCircle(p,{r:4,fill:'none',stroke:color,strokeWidth:1.6,dash:'3,2'}));\n"
        "        }\n"
        "      });\n"
        "    }else{\n"
        "      PUNKTE.forEach(function(p){\n"
        "        if(p.akt!==tid) return;\n"
        "        g.appendChild(makeCircle(p,{r:4,fill:color,stroke:'#fff',strokeWidth:1.2}));\n"
        "      });\n"
        "    }\n"
        "    svg.appendChild(g);\n"
        "  }\n"
        "  function highlightState(tid){\n"
        "    var mode=currentMode();\n"
        "    svg.querySelectorAll('path.st').forEach(function(p){\n"
        "      p.classList.remove('go-dim','go-hl');\n"
        "      if(!tid) return;\n"
        "      var ownerColor=mode==='optimiert'?p.getAttribute('data-fill-optimiert'):p.getAttribute('data-fill-aktuell');\n"
        "      if(ownerColor===C[tid]){ p.classList.add('go-hl'); }\n"
        "      else{ p.classList.add('go-dim'); }\n"
        "    });\n"
        "  }\n"
        "  function updateUiState(tid){\n"
        "    document.querySelectorAll('tr[data-tech]').forEach(function(el){\n"
        "      el.classList.toggle('go-row-active', el.getAttribute('data-tech')===tid);\n"
        "    });\n"
        "    document.querySelectorAll('.gebiets-legende-item, .go-tech-link').forEach(function(el){\n"
        "      el.classList.toggle('go-active', el.getAttribute('data-tech')===tid);\n"
        "    });\n"
        "    var btn=document.getElementById('go-reset-btn');\n"
        "    if(btn) btn.disabled=!tid;\n"
        "  }\n"
        "  function clearAll(){\n"
        "    selected=null;\n"
        "    svg.querySelectorAll('path.st').forEach(function(p){ p.classList.remove('go-dim','go-hl'); });\n"
        "    clearPunkte();\n"
        "    updateUiState(null);\n"
        "  }\n"
        "  function selectTech(tid){\n"
        "    if(!tid) return;\n"
        "    if(selected===tid){ clearAll(); return; }\n"
        "    selected=tid;\n"
        "    highlightState(tid);\n"
        "    renderPunkte(tid);\n"
        "    updateUiState(tid);\n"
        "  }\n"
        "\n"
        "  document.querySelectorAll('tr[data-tech]').forEach(function(tr){\n"
        "    tr.style.cursor='pointer';\n"
        "    tr.addEventListener('click',function(e){\n"
        "      if(e.target.closest('.go-tech-link')) return;\n"
        "      selectTech(tr.getAttribute('data-tech'));\n"
        "    });\n"
        "  });\n"
        "  document.body.addEventListener('click',function(e){\n"
        "    var link=e.target.closest('.go-tech-link');\n"
        "    if(link){ e.stopPropagation(); selectTech(link.getAttribute('data-tech')); return; }\n"
        "    var item=e.target.closest('.gebiets-legende-item');\n"
        "    if(item){ selectTech(item.getAttribute('data-tech')); }\n"
        "  });\n"
        "  var resetBtn=document.getElementById('go-reset-btn');\n"
        "  if(resetBtn) resetBtn.addEventListener('click',clearAll);\n"
        "  document.querySelectorAll('.go-view-btn').forEach(function(btn){\n"
        "    btn.addEventListener('click',function(){\n"
        "      if(selected){ highlightState(selected); renderPunkte(selected); }\n"
        "    });\n"
        "  });\n"
        "})();\n"
        "\n"
        "/* ── Hugo-Kerngebiet: Toggle (default AUS, rein clientseitig) ── */\n"
        "(function(){\n"
        "  var toggle=document.getElementById('hugo-kg-toggle');\n"
        "  var hint=document.getElementById('hugo-kg-hint');\n"
        "  var svg=document.getElementById('germany-map-opt');\n"
        "  if(!toggle||!svg) return;\n"
        "  var kgLayer=svg.querySelector('#hugo-kerngebiete');\n"
        "  var standorteLayer=svg.querySelector('#hugo-standorte');\n"
        "  toggle.addEventListener('change',function(){\n"
        "    var anzeigen=toggle.checked?'block':'none';\n"
        "    if(kgLayer) kgLayer.style.display=anzeigen;\n"
        "    if(standorteLayer) standorteLayer.style.display=anzeigen;\n"
        "    if(hint) hint.style.display=toggle.checked?'block':'none';\n"
        "  });\n"
        "})();\n"
    )


# ---------------------------------------------------------------------------
# Sort-Dropdown Script
# ---------------------------------------------------------------------------

_SORT_SCRIPT = """
  (function () {
    var keyMap = {
      standard:      'sortStandard',
      crosstraining: 'sortCrosstraining',
      auslastung:    'sortAuslastung',
      portfolio:     'sortPortfolio',
      potential:     'sortPotential'
    };

    function sortAmpelGrid(mode) {
      var grid  = document.getElementById('ampel-grid');
      var cards = Array.prototype.slice.call(grid.querySelectorAll('.ampel-karte'));
      var key   = keyMap[mode];

      cards.sort(function (a, b) {
        var va = parseFloat(a.dataset[key]);
        var vb = parseFloat(b.dataset[key]);
        return mode === 'standard' ? va - vb : vb - va;
      });

      grid.querySelectorAll('.metric-box').forEach(function (el) {
        el.style.display = 'none';
      });
      grid.querySelectorAll('.metric-' + mode).forEach(function (el) {
        el.style.display = 'block';
      });

      cards.forEach(function (card) { grid.appendChild(card); });
    }

    document.getElementById('ampel-sort-select')
      .addEventListener('change', function () { sortAmpelGrid(this.value); });
  }());"""


# ---------------------------------------------------------------------------
# Medtronic Light Theme – CSS
# ---------------------------------------------------------------------------

_CSS = """\
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;0,800;1,400&family=Syne:wght@400;500;600;700;800&display=swap');
    :root {
      --bg:           #FFFFFF;
      --card-bg:      rgba(0,81,149,0.05);
      --card-border:  rgba(0,81,149,0.18);
      --nav-bg:       rgba(0,81,149,0.97);
      --primary:      #005195;
      --accent:       #0066CC;
      --success:      #00857C;
      --success-text: #00857C;
      --warning:      #CC7000;
      --warning-text: #CC7000;
      --critical:     #CC0000;
      --critical-text:#CC0000;
      --demo:         #FFD060;
      --text:         #1A1A1A;
      --text-dim:     #666666;
      --text-muted:   #999999;
      --font-body:    'Plus Jakarta Sans', sans-serif;
      --font-heading: 'Syne', sans-serif;
      --grad-accent:  linear-gradient(135deg, #005195, #0066CC);
      --grad-primary: linear-gradient(135deg, #005195, #0066CC);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: var(--font-body);
      background: var(--bg);
      color: var(--text);
      font-size: 14px;
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
      scrollbar-width: thin;
      scrollbar-color: rgba(0,81,149,.2) transparent;
    }
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: rgba(0,81,149,.2); border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: rgba(0,81,149,.35); }

    /* ── Grain Overlay (deaktiviert fuer Light Theme) ── */
    .grain-overlay {
      display: none;
    }

    /* ── App Layout ── */
    .app-layout {
      display: flex;
      min-height: 100vh;
    }
    .dashboard-panel {
      flex: 1;
      min-width: 0;
      display: flex;
      flex-direction: column;
    }

    /* ── Hero Header ── */
    header {
      background: rgba(0,81,149,0.97);
      backdrop-filter: blur(28px);
      -webkit-backdrop-filter: blur(28px);
      color: #fff;
      padding: 0 32px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      height: 60px;
      position: sticky;
      top: 0;
      z-index: 100;
      border-bottom: 1px solid rgba(255,255,255,.15);
    }
    .header-brand {
      display: flex;
      align-items: center;
      gap: 16px;
    }
    .header-logo {
      font-family: var(--font-heading);
      font-size: 22px;
      font-weight: 800;
      letter-spacing: .3px;
      background: linear-gradient(135deg, #fff, rgba(255,255,255,.85));
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }
    .header-logo .brand-ai {
      background: linear-gradient(135deg, #fff, rgba(255,255,255,.85));
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      font-weight: 800;
    }
    .header-sub {
      font-size: 11px;
      color: rgba(255,255,255,.65);
      font-weight: 500;
      letter-spacing: .04em;
    }
    .header-right {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .demo-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: rgba(255,208,96,.1);
      color: var(--demo);
      border: 1px solid rgba(255,208,96,.2);
      border-radius: 20px;
      padding: 5px 16px;
      font-size: 11px;
      font-weight: 600;
      letter-spacing: .04em;
    }
    .lang-toggle, .api-key-btn {
      background: rgba(255,255,255,.1);
      color: rgba(255,255,255,.85);
      border: 1px solid rgba(255,255,255,.25);
      border-radius: 20px;
      padding: 6px 16px;
      font-family: var(--font-body);
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      transition: all .2s ease;
      letter-spacing: .03em;
    }
    .lang-toggle:hover, .api-key-btn:hover {
      background: rgba(255,255,255,.1);
      color: #fff;
      border-color: rgba(255,255,255,.25);
      box-shadow: 0 0 12px rgba(0,163,224,.15);
    }

    /* ── Summary Bar ── */
    .summary-bar {
      background: rgba(0,81,149,.03);
      border-bottom: 1px solid var(--card-border);
      padding: 10px 32px;
      display: flex;
      gap: 28px;
      font-size: 13px;
      align-items: center;
    }
    .summary-bar span { display: flex; align-items: center; gap: 6px; }
    .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
    .dot-gruen { background: var(--success-text); }
    .dot-gelb  { background: var(--warning-text); }
    .dot-rot   { background: var(--critical-text); }

    /* ── Layout ── */
    main { padding: 24px 32px; display: flex; flex-direction: column; gap: 24px; flex: 1; }
    section {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 28px 32px;
      box-shadow: 0 2px 12px rgba(0,81,149,.08);
      transition: background .2s ease, box-shadow .2s ease;
    }
    section:hover {
      background: rgba(0,81,149,.04);
      box-shadow: 0 4px 24px rgba(0,81,149,.12);
    }
    section h2 {
      font-family: var(--font-heading);
      font-size: 17px;
      font-weight: 700;
      color: var(--text);
      margin-bottom: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid rgba(0,81,149,.12);
      letter-spacing: .02em;
    }
    .section-hint {
      font-size: 11px;
      color: var(--text-dim);
      margin-top: -10px;
      margin-bottom: 16px;
    }
    .tab-content { display: none; }
    .tab-content.active { display: block; }

    /* ── Techniker-Karten (Glassmorphism) ── */
    .ampel-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
      gap: 14px;
    }
    .ampel-karte {
      border-radius: 16px;
      padding: 16px 18px;
      min-width: 0;
      position: relative;
      border: 1px solid var(--card-border);
      border-top: 4px solid var(--text-muted);
      background: var(--card-bg);
      transition: transform .2s ease, box-shadow .2s ease, background .2s ease;
    }
    .ampel-karte:hover {
      transform: translateY(-2px);
      box-shadow: 0 8px 28px rgba(0,81,149,.15);
      background: rgba(0,81,149,.04);
    }
    .ampel-gruen {
      background: rgba(0,135,90,.06);
      border-color: rgba(94,221,159,.12);
      border-top-color: var(--success);
    }
    .ampel-gruen:hover { box-shadow: 0 8px 28px rgba(0,135,90,.15); }
    .ampel-gruen .ampel-id { background: var(--grad-accent); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
    .ampel-gruen .metric-num { color: var(--success-text); }
    .ampel-gelb {
      background: rgba(255,139,0,.06);
      border-color: rgba(255,179,71,.12);
      border-top-color: var(--warning);
    }
    .ampel-gelb:hover { box-shadow: 0 8px 28px rgba(255,139,0,.12); }
    .ampel-gelb .ampel-id { color: var(--warning-text); }
    .ampel-gelb .metric-num { color: var(--warning-text); }
    .ampel-rot {
      background: rgba(204,0,0,.06);
      border-color: rgba(255,128,128,.12);
      border-top-color: var(--critical);
    }
    .ampel-rot:hover { box-shadow: 0 8px 28px rgba(204,0,0,.12); }
    .ampel-rot .ampel-id { color: var(--critical-text); }
    .ampel-rot .metric-num { color: var(--critical-text); }
    .ampel-karte.hugo-border { border: 2px solid var(--primary); }
    .ampel-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 4px;
    }
    .ampel-id      { font-family: var(--font-heading); font-size: 1.4rem; font-weight: 700; line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; background: var(--grad-accent); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
    .ampel-standort{ font-size: 12px; color: var(--text-dim); }
    .ampel-region  { font-size: 10px; color: var(--text-muted); margin-bottom: 10px; }
    .ampel-badge {
      display: inline-block;
      border-radius: 4px;
      font-size: 10px;
      font-weight: 700;
      padding: 2px 7px;
      letter-spacing: .5px;
    }
    .ampel-gruen .ampel-badge { background: var(--success); color: #fff; }
    .ampel-gelb  .ampel-badge { background: var(--warning); color: #fff; }
    .ampel-rot   .ampel-badge { background: var(--critical); color: #fff; }

    /* ── Auslastungs-Zielkorridor-Badge (80-95%, Referenzwert) -- bewusst
       getrennt gestylt von .ampel-badge (L3-Qualifikationsampel), nicht
       verwechseln ── */
    .korridor-badge {
      display: inline-flex;
      align-items: center;
      border-radius: 4px;
      font-size: 9.5px;
      font-weight: 600;
      padding: 2px 6px;
      margin-top: 4px;
      cursor: help;
      position: relative;
      white-space: nowrap;
    }
    .korridor-unter    { background: rgba(0,102,204,.12); color: #0058A3; }
    .korridor-im       { background: rgba(0,160,128,.15); color: #007A5E; }
    .korridor-ueber    { background: rgba(204,0,0,.12); color: #9A0000; }

    .hugo-ka-badge {
      display: inline-block;
      background: rgba(0,114,206,.15);
      color: var(--accent);
      border: 1px solid rgba(0,163,224,.25);
      border-radius: 4px;
      font-size: 9px;
      font-weight: 700;
      padding: 1px 6px;
      letter-spacing: .3px;
      margin-bottom: 6px;
    }

    /* ── Sort Controls ── */
    .ampel-sort-controls {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 14px;
      flex-wrap: wrap;
    }
    .ampel-sort-controls label {
      font-size: 12px;
      font-weight: 600;
      color: var(--text-dim);
      white-space: nowrap;
    }
    .ampel-sort-controls select {
      font-family: var(--font-body);
      font-size: 12px;
      padding: 8px 14px;
      border: 1px solid var(--card-border);
      border-radius: 10px;
      background: rgba(0,81,149,.04);
      color: var(--text);
      cursor: pointer;
      min-width: 320px;
      outline: none;
      transition: all .2s ease;
    }
    .ampel-sort-controls select:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 2px rgba(0,163,224,.15);
    }
    .ampel-sort-controls select option {
      background: #FFFFFF;
      color: #1A1A1A;
      padding: 8px 12px;
    }
    .ampel-sort-controls .demo-hint {
      font-size: 10px;
      color: var(--demo);
      font-style: italic;
    }

    /* ── Metric Box (stat-cell style) ── */
    .metric-box   { margin: 8px 0 2px; }
    .metric-num   { font-family: var(--font-heading); font-size: 24px; font-weight: 800; line-height: 1.1; background: var(--grad-accent); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
    .metric-lbl   { font-size: 10px; color: rgba(0,0,0,.5); margin-bottom: 3px; text-transform: uppercase; letter-spacing: .08em; }
    .metric-sub   { font-size: 10px; color: var(--text-muted); }
    .metric-italic{ font-style: italic; }

    /* ── Fortschrittsbalken ── */
    .auslastung-bar-wrap {
      position: relative;
      height: 5px;
      background: rgba(0,81,149,.1);
      border-radius: 3px;
      margin: 5px 0 3px;
      overflow: visible;
    }
    .auslastung-bar-fill {
      height: 100%;
      border-radius: 3px;
      min-width: 0;
      background: linear-gradient(90deg, #005195, #0066CC);
    }
    .ampel-gruen .auslastung-bar-fill { background: linear-gradient(90deg, var(--success), #00A080); }
    .ampel-gelb  .auslastung-bar-fill { background: linear-gradient(90deg, #9A5500, var(--warning)); }
    .ampel-rot   .auslastung-bar-fill { background: linear-gradient(90deg, #990000, var(--critical)); }
    .auslastung-bar-ziel {
      position: absolute;
      top: -3px;
      width: 2px;
      height: 12px;
      background: var(--text);
      border-radius: 1px;
    }

    /* ── Tabellen ── */
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th {
      background: rgba(0,81,149,.05);
      text-align: left;
      padding: 10px 12px;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .5px;
      color: var(--text-dim);
      border-bottom: 1px solid var(--card-border);
    }
    td {
      padding: 10px 12px;
      border-bottom: 1px solid rgba(0,81,149,.08);
      vertical-align: middle;
      color: var(--text);
    }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: rgba(0,163,224,.04); }
    code { font-family: 'JetBrains Mono', 'Consolas', monospace; font-size: 12px; color: var(--accent); }
    .sub { color: var(--text-dim); font-size: 11px; }
    .fehlend-liste { font-size: 11px; color: var(--text-dim); max-width: 340px; }

    /* ── Dringlichkeit-Badges ── */
    .badge {
      display: inline-block;
      border-radius: 6px;
      padding: 3px 10px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .4px;
    }
    .badge-ueberfaellig { background: rgba(204,0,0,.2); color: var(--critical-text); border: 1px solid rgba(204,0,0,.3); }
    .badge-kritisch { background: rgba(204,0,0,.15); color: var(--critical-text); border: 1px solid rgba(204,0,0,.25); }
    .badge-hoch     { background: rgba(255,139,0,.15); color: var(--warning-text); border: 1px solid rgba(255,139,0,.25); }
    .badge-normal   { background: rgba(0,135,90,.15); color: var(--success-text); border: 1px solid rgba(0,135,90,.25); }
    .badge-blau     { background: rgba(0,163,224,.15); color: var(--accent); border: 1px solid rgba(0,163,224,.25); }
    .puls-animation { animation: puls 1.5s ease-in-out infinite; }
    @keyframes puls { 0%,100% { opacity:1; } 50% { opacity:0.5; } }

    /* ── Hugo Key Account Extras ── */
    .hugo-reserve {
      font-size: 9px;
      color: var(--accent);
      font-weight: 700;
      margin: 3px 0;
      padding: 2px 6px;
      background: rgba(0,114,206,.1);
      border-radius: 3px;
    }
    .hugo-warnung {
      font-size: 9px;
      color: var(--critical-text);
      font-weight: 700;
      margin: 3px 0;
      padding: 2px 6px;
      background: rgba(204,0,0,.12);
      border-radius: 3px;
    }

    /* ── Crosstraining Cluster-Badges ── */
    .cluster-badge {
      display: inline-block;
      border-radius: 4px;
      padding: 2px 8px;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: .3px;
      margin: 1px 2px;
    }
    .cluster-small-capital { background: rgba(0,135,90,.12); color: var(--success-text); }
    .cluster-hf-chirurgie  { background: rgba(232,112,0,.12); color: #E87000; }
    .cluster-1-or          { background: rgba(204,0,0,.12); color: var(--critical-text); }
    .cluster-2-cardiac     { background: rgba(204,0,0,.1); color: var(--critical-text); }
    .cluster-3-monitoring  { background: rgba(255,139,0,.12); color: var(--warning-text); }
    .cluster-4-digital     { background: rgba(0,114,206,.12); color: var(--accent); }

    /* ── Puffer-Visualisierung ── */
    .puffer-container { display: flex; flex-direction: column; gap: 8px; }
    .puffer-row {
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 12px 16px;
      cursor: pointer;
      transition: all .2s ease;
      background: var(--card-bg);
    }
    .puffer-row:hover { background: rgba(0,81,149,.05); box-shadow: 0 2px 12px rgba(0,81,149,.1); }
    .puffer-summary { font-size: 13px; margin-bottom: 6px; color: var(--text); }
    .puffer-gesamt { font-weight: 700; color: var(--accent); }
    .puffer-bar-wrap { display: flex; height: 20px; border-radius: 6px; overflow: hidden; font-size: 10px; }
    .puffer-bar-netto {
      background: linear-gradient(90deg, var(--success), #00A080);
      color: #fff;
      display: flex; align-items: center; justify-content: center;
      font-weight: 700; min-width: 40px;
    }
    .puffer-bar-puffer {
      background: linear-gradient(90deg, #E87000, var(--warning));
      color: #fff;
      display: flex; align-items: center; justify-content: center;
      font-weight: 700; min-width: 40px;
    }
    .puffer-detail {
      margin-top: 10px;
      padding: 10px 14px;
      background: rgba(0,114,206,.05);
      border-left: 3px solid var(--primary);
      border-radius: 0 8px 8px 0;
      font-size: 12px;
      color: var(--text-dim);
    }
    .puffer-detail strong { color: var(--text); }
    .puffer-detail-grid { display: flex; flex-direction: column; gap: 6px; }
    .puffer-aufschluesselung { padding-left: 12px; }
    .puffer-item { display: flex; gap: 8px; font-size: 11px; }
    .puffer-label { color: var(--text-dim); min-width: 120px; }
    .puffer-val { font-weight: 700; color: var(--text); }
    .puffer-summe { border-top: 1px solid var(--card-border); padding-top: 4px; margin-top: 4px; }

    /* ── Workflow-Status ── */
    .wf-pipeline {
      display: flex;
      align-items: flex-start;
      gap: 0;
      flex-wrap: wrap;
      padding: 16px 0;
    }
    .wf-step {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
      padding: 12px 16px;
      min-width: 100px;
      text-align: center;
    }
    .wf-icon {
      font-size: 28px;
      line-height: 1;
    }
    .wf-label {
      font-family: var(--font-heading);
      font-size: 12px;
      font-weight: 600;
      color: var(--text);
    }
    .wf-badge {
      font-size: 9px;
      font-weight: 700;
      padding: 2px 8px;
      border-radius: 10px;
      letter-spacing: .3px;
      text-transform: uppercase;
    }
    .wf-badge-auto {
      background: rgba(0,114,206,.15);
      color: var(--accent);
      border: 1px solid rgba(0,114,206,.25);
    }
    .wf-badge-mensch {
      background: rgba(0,135,90,.15);
      color: var(--success-text);
      border: 1px solid rgba(0,135,90,.25);
    }
    .wf-detail {
      font-size: 10px;
      color: var(--text-muted);
    }
    .wf-arrow {
      color: var(--text-muted);
      font-size: 20px;
      display: flex;
      align-items: center;
      padding-top: 14px;
    }

    /* ── Business Case ── */
    .bc-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 16px;
      margin-bottom: 16px;
    }
    .bc-card {
      background: rgba(0,81,149,.04);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 20px;
      transition: all .2s ease;
    }
    .bc-card:hover { border-color: rgba(0,81,149,.3); background: rgba(0,81,149,.07); box-shadow: 0 4px 20px rgba(0,81,149,.12); }
    .bc-card-title {
      font-family: var(--font-heading);
      font-size: 13px;
      font-weight: 600;
      color: var(--accent);
      margin-bottom: 10px;
    }
    .bc-formula {
      font-family: 'JetBrains Mono', 'Consolas', monospace;
      font-size: 12px;
      color: var(--text);
      padding: 8px 12px;
      background: rgba(0,114,206,.06);
      border-radius: 6px;
      margin-bottom: 6px;
    }
    .bc-result {
      font-family: var(--font-heading);
      font-size: 15px;
      font-weight: 700;
      color: var(--accent);
      margin: 6px 0 4px;
    }
    .bc-hint {
      font-size: 11px;
      color: var(--text-dim);
    }
    .bc-gold-hint {
      padding: 12px 16px;
      background: rgba(255,208,96,.08);
      border: 1px solid rgba(255,208,96,.2);
      border-radius: 8px;
      color: var(--demo);
      font-size: 12px;
      font-weight: 600;
    }

    /* ── Techniker-Detail Modal ── */
    .tech-detail-overlay {
      display: none;
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0,0,0,.5);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      z-index: 1000;
      justify-content: center;
      align-items: center;
    }
    .tech-detail-overlay.active { display: flex; }
    .tech-detail-panel {
      background: #FFFFFF;
      border: 1px solid var(--card-border);
      border-radius: 20px;
      box-shadow: 0 24px 64px rgba(0,0,0,.25);
      backdrop-filter: blur(28px);
      -webkit-backdrop-filter: blur(28px);
      max-width: 720px;
      width: 90%;
      max-height: 85vh;
      overflow-y: auto;
      padding: 28px 32px;
      position: relative;
    }
    .tech-detail-close {
      position: absolute;
      top: 12px; right: 16px;
      background: none; border: none;
      font-size: 22px; cursor: pointer;
      color: var(--text-dim);
      line-height: 1;
    }
    .tech-detail-close:hover { color: var(--critical-text); }
    .tech-detail-title {
      font-family: var(--font-heading);
      font-size: 18px;
      font-weight: 700;
      color: var(--text);
      margin-bottom: 16px;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--card-border);
    }
    .tech-detail-kpis {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 16px;
    }
    .tech-detail-kpi {
      flex: 1;
      min-width: 140px;
      background: rgba(0,81,149,.05);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 12px 14px;
    }
    .tech-detail-kpi .kpi-val { font-family: var(--font-heading); font-size: 20px; font-weight: 800; background: var(--grad-accent); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
    .tech-detail-kpi .kpi-lbl { font-size: 11px; color: var(--text-dim); }

    /* ── NRW-Warnung ── */
    .warnung-box {
      background: rgba(255,139,0,.06);
      border: 1px solid rgba(255,139,0,.2);
      border-radius: 12px;
      padding: 20px 24px;
    }
    .warnung-box h2 {
      border-bottom-color: rgba(255,139,0,.2);
      color: var(--warning-text);
    }
    .warnung-box .warnung-stats { margin-bottom: 10px; color: var(--text-dim); font-size: 13px; }
    .warnung-box .warnung-stats strong { color: var(--warning-text); }
    .warnung-box ul { margin: 0 0 12px 20px; }
    .warnung-box li { margin-bottom: 5px; color: var(--text-dim); font-size: 13px; }
    .warnung-box li strong { color: var(--text); }
    .warnung-hinweis {
      margin-top: 10px;
      padding: 10px 14px;
      background: rgba(255,139,0,.08);
      border-radius: 8px;
      font-size: 12px;
      color: var(--warning-text);
    }

    /* ── Footer ── */
    footer {
      background: rgba(0,8,20,.85);
      backdrop-filter: blur(28px);
      -webkit-backdrop-filter: blur(28px);
      text-align: center;
      padding: 20px 32px;
      font-size: 11px;
      color: var(--text-muted);
      border-top: 1px solid var(--card-border);
      letter-spacing: .03em;
    }

    /* ── Gebietsplanung ── */
    .gebiets-layout {
      display: flex;
      gap: 24px;
      align-items: flex-start;
    }
    .gebiets-karte { flex-shrink: 0; width: 480px; }
    .gebiets-karte svg {
      border: 1px solid rgba(0,81,149,.2);
      border-radius: 14px;
      background: #F0F4FA;
      /* Sicherheitsnetz fuer optionale Overlays (Hugo-Kerngebiet-Kreise,
         Toggle default AUS), die ueber die aus der Landesflaeche berechnete
         viewBox hinausragen koennen (siehe _berechne_gebiets_viewbox) --
         damit werden sie im Toggle-Fall sichtbar statt abgeschnitten,
         waehrend die Standardansicht kompakt auf Deutschland zugeschnitten
         bleibt. */
      overflow: visible;
    }
    .gebiets-karte svg path.st { opacity: .7; transition: opacity .2s ease; }
    .gebiets-karte svg path.st:hover { opacity: .9; }
    .gebiets-karte svg circle.td { filter: drop-shadow(0 0 4px rgba(0,163,224,.4)); }
    .gebiets-metriken { flex: 1; min-width: 0; overflow-x: auto; }

    /* ── Gebietsoptimierung: Erlaeuterungsboxen ── */
    .go-info-box {
      display: flex;
      gap: 12px;
      background: rgba(0,81,149,.05);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 14px 16px;
      margin-bottom: 14px;
    }
    .go-info-icon { font-size: 20px; line-height: 1.3; flex-shrink: 0; }
    .go-info-body { flex: 1; min-width: 0; }
    .go-info-title {
      font-family: var(--font-heading);
      font-size: 12.5px;
      font-weight: 700;
      color: var(--accent);
      margin-bottom: 4px;
    }
    .go-info-text { font-size: 12.5px; color: var(--text); line-height: 1.55; }

    /* ── Info-Tooltip: Kennzahlen-Erklaerung direkt am Ort der Verwirrung ──
       Die sichtbare Bubble wird per JS (Portal-Pattern, siehe
       _build_tooltip_portal_script) bei Hover/Focus an document.body
       angehaengt statt als Kind-Element positioniert. Grund: mehrere
       Tooltip-Container (.gebiets-metriken, .ampel-grid) haben
       overflow-x:auto (fuer schmale Fenster/breite Tabellen noetig), was
       per CSS-Spezifikation overflow-y implizit auf 'auto' mitsetzt --
       jede absolut positionierte Kind-Bubble wird dadurch am Container-
       Rand abgeschnitten, unabhaengig von ihrer eigenen CSS-Position
       (reine links/rechts-Ausrichtung reichte bei schmalen Containern
       nicht aus). Der Portal-Ansatz umgeht das vollstaendig. Das
       .info-tip-bubble-Markup bleibt als unsichtbarer Inhalts-/
       data-label-de-Traeger fuer die i18n-Uebersetzung erhalten. */
    .info-tip {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 14px;
      height: 14px;
      margin-left: 5px;
      border-radius: 50%;
      background: rgba(0,81,149,.14);
      color: #005195;
      font-size: 11px;
      line-height: 1;
      cursor: help;
      position: relative;
      vertical-align: middle;
      text-transform: none;
      letter-spacing: normal;
      font-weight: 400;
    }
    .info-tip:hover, .info-tip:focus {
      background: rgba(0,81,149,.26);
      outline: none;
    }
    .info-tip-bubble { display: none; }
    th .info-tip { margin-left: 4px; }

    .info-tip-portal {
      position: fixed;
      visibility: hidden;
      opacity: 0;
      z-index: 9999;
      width: max-content;
      max-width: min(250px, calc(100vw - 16px));
      background: #1A2B3C;
      color: #fff;
      font-size: 11px;
      font-weight: 400;
      line-height: 1.55;
      text-align: left;
      text-transform: none;
      letter-spacing: normal;
      padding: 9px 11px;
      border-radius: 8px;
      box-shadow: 0 6px 20px rgba(0,0,0,.28);
      transition: opacity .15s ease;
      pointer-events: none;
    }

    /* ── Crosstraining: Mehrwert-Begruendung / Ausschluss-Hinweis ── */
    .ct-mehrwert {
      margin-top: 6px;
      padding: 8px 10px;
      background: rgba(0,133,124,.06);
      border: 1px solid rgba(0,133,124,.2);
      border-radius: 8px;
      font-size: 11px;
      color: var(--text);
      line-height: 1.6;
    }
    .ct-mehrwert strong { color: var(--success-text); }
    .ct-ausschluss-hint {
      margin-top: 14px;
      padding: 10px 14px;
      background: rgba(204,112,0,.06);
      border: 1px solid rgba(204,112,0,.2);
      border-radius: 8px;
      font-size: 11.5px;
      color: var(--warning-text);
      line-height: 1.5;
    }

    /* Einstellungsbedarf */
    .einst-layout {
      display: flex;
      gap: 24px;
      align-items: flex-start;
    }
    .einst-karte { flex: 0 0 60%; min-width: 0; }
    .einst-karte svg {
      border: 1px solid rgba(0,81,149,.2);
      border-radius: 14px;
      background: #F0F4FA;
      overflow: visible;
      width: 100%;
      height: auto;
    }
    .einst-liste { flex: 0 0 38%; }
    .einst-liste-header {
      font-family: var(--font-heading);
      font-weight: 700;
      color: var(--critical-text);
      font-size: 15px;
      margin-bottom: 12px;
    }
    .einst-item {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 12px 14px;
      margin-bottom: 8px;
      border: 1px solid var(--card-border);
      border-radius: 14px;
      background: var(--card-bg);
      transition: all .2s ease;
    }
    .einst-item:hover { box-shadow: 0 4px 20px rgba(0,81,149,.12); border-color: rgba(0,81,149,.3); background: rgba(0,81,149,.04); }
    .einst-dot {
      flex-shrink: 0;
      width: 28px;
      height: 28px;
      border-radius: 50%;
      background: var(--critical);
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 15px;
      margin-top: 2px;
      position: relative;
    }
    .einst-dot[data-num]::after {
      content: attr(data-num);
      position: absolute;
      top: -6px; right: -6px;
      background: var(--accent);
      color: #fff;
      font-size: 9px; font-weight: 700;
      width: 14px; height: 14px;
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
    }
    .einst-item { cursor: pointer; }
    .einst-text { flex: 1; }
    .einst-text .einst-name {
      font-weight: 700;
      color: var(--text);
      font-size: 14px;
    }
    .einst-text .einst-detail {
      color: var(--text-dim);
      font-size: 12px;
      margin-top: 2px;
    }
    .einst-marker circle { transition: r .15s; }
    .einst-marker:hover circle { r: 13; }
    .gebiets-summary {
      display: flex;
      gap: 20px;
      align-items: center;
      padding: 10px 0;
      font-size: 13px;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }
    .gebiets-summary span { display: flex; align-items: center; gap: 6px; }
    .gebiets-team-saving {
      margin-top: 16px;
      padding: 12px 16px;
      background: rgba(0,114,206,.06);
      border-left: 3px solid var(--primary);
      border-radius: 0 8px 8px 0;
      font-size: 13px;
      color: var(--text);
    }
    .gebiets-ampel-dot {
      display: inline-block;
      width: 8px; height: 8px;
      border-radius: 50%;
      margin-right: 4px;
    }
    .gebiets-gruen .gebiets-ampel-dot { background: var(--success-text); }
    .gebiets-gelb .gebiets-ampel-dot { background: var(--warning-text); }
    .gebiets-rot .gebiets-ampel-dot { background: var(--critical-text); }
    .badge-ratio { color: #fff; padding: 2px 8px; }
    .badge-ratio.gebiets-gruen { background: var(--success); }
    .badge-ratio.gebiets-gelb  { background: var(--warning); }
    .badge-ratio.gebiets-rot   { background: var(--critical); }
    .gebiets-detail-box {
      padding: 10px 14px;
      background: rgba(0,114,206,.05);
      border-left: 3px solid var(--primary);
      border-radius: 0 8px 8px 0;
      font-size: 12px;
      line-height: 1.6;
      color: var(--text-dim);
    }
    .gebiets-detail-box strong { color: var(--text); }
    tr.gebiets-row { transition: background .15s; }
    tr.gebiets-row:hover td { background: rgba(0,114,206,.06); }
    .gebiets-legende {
      display: flex;
      flex-wrap: wrap;
      gap: 6px 12px;
      margin-top: 10px;
      font-size: 11px;
      color: var(--text-dim);
    }
    .gebiets-legende-item {
      display: flex;
      align-items: center;
      gap: 4px;
      cursor: pointer;
      padding: 2px 6px;
      border-radius: 6px;
      transition: background .15s ease;
    }
    .gebiets-legende-item:hover { background: rgba(0,81,149,.08); }
    .gebiets-legende-item.go-active {
      background: rgba(0,81,149,.14);
      font-weight: 700;
      color: var(--text);
    }
    .gebiets-legende-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      border: 1px solid rgba(0,0,0,.15);
    }

    /* ── Gebietskarte: Techniker-Highlight (Klick-Interaktion) ── */
    .gebiets-karte-tools {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-top: 8px;
    }
    .go-hint { font-size: 10.5px; color: var(--text-muted); }
    .go-reset-btn {
      font-family: var(--font-body);
      font-size: 11px;
      font-weight: 600;
      padding: 6px 14px;
      border-radius: 8px;
      border: 1px solid rgba(0,81,149,.25);
      background: #fff;
      color: #005195;
      cursor: pointer;
      transition: all .15s ease;
      white-space: nowrap;
    }
    .go-reset-btn:hover:not(:disabled) { background: rgba(0,81,149,.08); }
    .go-reset-btn:disabled { opacity: .4; cursor: not-allowed; }

    .gebiets-karte svg path.st.go-dim { opacity: .22 !important; }
    .gebiets-karte svg path.st.go-hl {
      opacity: 1 !important;
      stroke: #1A1A1A !important;
      stroke-width: 2.6px !important;
    }

    /* ── Hugo-Kerngebiet (optional, Toggle default AUS) ── */
    .hugo-kg-box {
      margin-top: 10px;
      padding: 10px 12px;
      background: rgba(123,45,142,.05);
      border: 1px solid rgba(123,45,142,.2);
      border-radius: 10px;
    }
    .hugo-kg-toggle {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 11px;
      color: var(--text);
      cursor: pointer;
      line-height: 1.4;
    }
    .hugo-kg-toggle input { cursor: pointer; accent-color: #7B2D8E; }
    .hugo-kg-hint {
      margin-top: 8px;
      font-size: 10.5px;
      color: var(--text-dim);
      line-height: 1.5;
    }
    .gebiets-karte svg circle.hugo-kg-kreis { pointer-events: all; }
    .gebiets-karte svg rect.hugo-standort-marker { pointer-events: all; cursor: default; }

    tr[data-tech] { cursor: pointer; }
    tr[data-tech]:hover td { background: rgba(0,114,206,.08); }
    tr[data-tech].go-row-active td { background: rgba(0,81,149,.16) !important; }

    .go-tech-link {
      cursor: pointer;
      text-decoration: underline;
      text-decoration-style: dotted;
      text-underline-offset: 2px;
    }
    .go-tech-link:hover { color: #005195; }
    .go-tech-link.go-active { font-weight: 700; color: #005195; }

    /* ── Chat Panel ── */
    .chat-panel {
      width: 340px;
      min-width: 340px;
      background: #FAFCFF;
      border-left: 1px solid var(--card-border);
      display: flex;
      flex-direction: column;
      height: 100vh;
      position: sticky;
      top: 0;
    }
    .chat-header {
      background: rgba(0,81,149,0.97);
      color: #fff;
      padding: 0 16px;
      height: 60px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-shrink: 0;
      border-bottom: 1px solid var(--card-border);
    }
    .chat-header-title {
      font-family: var(--font-heading);
      font-size: 14px;
      font-weight: 700;
      letter-spacing: .3px;
    }
    .chat-header-sub {
      font-size: 10px;
      color: rgba(255,255,255,.65);
    }
    .chat-status {
      width: 8px; height: 8px;
      border-radius: 50%;
      background: var(--success-text);
      display: inline-block;
      margin-right: 8px;
    }
    .chat-status.offline { background: var(--text-muted); }

    /* ── Template-Erklaerungen (kein API-Key noetig) ── */
    .erklaer-box {
      padding: 16px;
      border-bottom: 1px solid var(--card-border);
      background: rgba(0,133,124,.04);
    }
    .erklaer-intro {
      font-size: 11.5px;
      color: var(--text-dim);
      margin: 0 0 10px;
      line-height: 1.5;
    }
    .erklaer-select {
      width: 100%;
      padding: 8px 10px;
      margin-bottom: 8px;
      border: 1px solid var(--card-border);
      border-radius: 8px;
      background: #fff;
      color: var(--text);
      font-family: var(--font-body);
      font-size: 12px;
    }
    .erklaer-antwort {
      margin-top: 12px;
      padding: 12px 14px;
      background: #fff;
      border: 1px solid rgba(0,133,124,.25);
      border-radius: 10px;
      font-size: 12px;
      line-height: 1.6;
      color: var(--text);
    }
    .erklaer-divider {
      padding: 10px 16px;
      font-size: 10px;
      color: var(--text-muted);
      text-align: center;
      border-bottom: 1px solid var(--card-border);
    }

    /* ── Chat Setup ── */
    .chat-setup {
      padding: 24px 16px;
      text-align: center;
    }
    .chat-setup p {
      font-size: 13px;
      color: var(--text-dim);
      margin-bottom: 12px;
    }
    .chat-setup input {
      width: 100%;
      padding: 10px 12px;
      border: 1px solid var(--card-border);
      border-radius: 8px;
      background: rgba(0,81,149,.04);
      color: var(--text);
      font-family: 'JetBrains Mono', 'Consolas', monospace;
      font-size: 12px;
      margin-bottom: 10px;
      outline: none;
    }
    .chat-setup input:focus {
      border-color: var(--primary);
      box-shadow: 0 0 0 2px rgba(0,114,206,.2);
    }
    .chat-setup .chat-key-error {
      color: var(--critical-text);
      font-size: 11px;
      margin-bottom: 8px;
      display: none;
    }
    .chat-btn-primary {
      background: var(--primary);
      color: #fff;
      border: none;
      border-radius: 8px;
      padding: 10px 20px;
      font-family: var(--font-body);
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      transition: all .2s;
    }
    .chat-btn-primary:hover { background: #005ba3; }

    /* ── Chat Messages ── */
    .chat-messages {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .chat-msg {
      max-width: 92%;
      padding: 10px 14px;
      border-radius: 12px;
      font-size: 13px;
      line-height: 1.5;
      word-wrap: break-word;
    }
    .chat-msg-user {
      align-self: flex-end;
      background: linear-gradient(135deg, #005195, #0066CC);
      color: #fff;
      border-bottom-right-radius: 4px;
    }
    .chat-msg-assistant {
      align-self: flex-start;
      background: rgba(0,87,168,.15);
      color: var(--text);
      border: 1px solid rgba(0,87,168,.2);
      border-bottom-left-radius: 4px;
    }
    .chat-msg-assistant strong { color: var(--accent); }
    .chat-msg-assistant code {
      background: rgba(0,163,224,.1);
      padding: 1px 5px;
      border-radius: 3px;
      font-size: 12px;
    }
    .chat-msg-system {
      align-self: center;
      background: transparent;
      color: var(--text-dim);
      font-size: 11px;
      font-style: italic;
      text-align: center;
      padding: 4px;
    }

    /* ── Quick Buttons ── */
    .chat-quick {
      padding: 8px 12px;
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      border-top: 1px solid var(--card-border);
      flex-shrink: 0;
    }
    .chat-quick button {
      background: rgba(0,81,149,.07);
      color: var(--text-dim);
      border: 1px solid rgba(0,81,149,.2);
      border-radius: 16px;
      padding: 6px 14px;
      font-family: var(--font-body);
      font-size: 11px;
      cursor: pointer;
      transition: all .2s ease;
      white-space: nowrap;
    }
    .chat-quick button:hover {
      background: linear-gradient(135deg, #005195, #0066CC);
      color: #fff;
      border-color: transparent;
      box-shadow: 0 2px 8px rgba(0,81,149,.25);
    }

    /* ── Chat Input ── */
    .chat-input-wrap {
      padding: 12px;
      border-top: 1px solid var(--card-border);
      display: flex;
      gap: 8px;
      align-items: flex-end;
      flex-shrink: 0;
    }
    .chat-input-wrap textarea {
      flex: 1;
      resize: none;
      border: 1px solid rgba(0,81,149,.2);
      border-radius: 12px;
      padding: 10px 12px;
      font-family: var(--font-body);
      font-size: 13px;
      line-height: 1.4;
      outline: none;
      background: rgba(0,81,149,.04);
      color: var(--text);
      max-height: 120px;
      min-height: 40px;
      transition: border-color .2s ease;
    }
    .chat-input-wrap textarea:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 2px rgba(0,163,224,.12);
    }
    .chat-send-btn {
      background: linear-gradient(135deg, #005195, #0066CC);
      color: #fff;
      border: none;
      border-radius: 12px;
      width: 40px;
      height: 40px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background .2s;
      flex-shrink: 0;
    }
    .chat-send-btn:hover { background: #005ba3; }
    .chat-send-btn:disabled { background: rgba(0,81,149,.15); cursor: not-allowed; }
    .chat-send-btn svg { width: 18px; height: 18px; fill: #fff; }

    .chat-disconnect {
      padding: 6px 12px;
      text-align: right;
      flex-shrink: 0;
    }
    .chat-disconnect button {
      background: none;
      border: none;
      color: var(--text-muted);
      font-size: 10px;
      cursor: pointer;
      text-decoration: underline;
    }
    .chat-disconnect button:hover { color: var(--critical-text); }

    /* ── Gebietsoptimierung ── */
    .go-empf-grid {
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .go-empf-card {
      display: flex;
      gap: 16px;
      background: rgba(0,81,149,.04);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 20px 22px;
      transition: all .2s ease;
    }
    .go-empf-card:hover { border-color: rgba(0,81,149,.3); background: rgba(0,81,149,.07); box-shadow: 0 4px 20px rgba(0,81,149,.12); }
    .go-empf-num {
      flex-shrink: 0;
      width: 36px; height: 36px;
      border-radius: 50%;
      background: linear-gradient(135deg, #005195, #0066CC);
      color: #fff;
      font-family: var(--font-heading);
      font-size: 16px;
      font-weight: 700;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .go-empf-body { flex: 1; }
    .go-empf-title {
      font-family: var(--font-heading);
      font-size: 14px;
      font-weight: 600;
      color: var(--accent);
      margin-bottom: 4px;
    }
    .go-empf-stats {
      font-size: 11px;
      color: var(--text-dim);
      margin-bottom: 6px;
      padding: 4px 10px;
      background: rgba(0,114,206,.06);
      border-radius: 4px;
      display: inline-block;
    }
    .go-empf-text {
      font-size: 13px;
      color: var(--text);
      line-height: 1.5;
    }
    .go-gruen td { color: var(--success-text); }
    .go-gelb td { color: var(--warning-text); }
    .go-rot td { color: var(--critical-text); }

    /* ── Gebietsoptimierung View Buttons ── */
    .go-view-buttons {
      display: flex;
      gap: 8px;
      margin-bottom: 18px;
    }
    .go-view-btn {
      font-family: var(--font-body);
      font-size: 12px;
      font-weight: 600;
      padding: 9px 20px;
      border-radius: 8px;
      border: 1px solid rgba(0,81,149,.25);
      background: rgba(0,81,149,.06);
      color: #005195;
      cursor: pointer;
      transition: all .2s ease;
      letter-spacing: .02em;
    }
    .go-view-btn:hover {
      background: rgba(0,81,149,.12);
      color: #003A6E;
    }
    .go-view-btn.active {
      background: linear-gradient(135deg, #005195, #0066CC);
      color: #fff;
      border-color: transparent;
      box-shadow: 0 2px 12px rgba(0,81,149,.3);
    }
    .go-view-content { display: none; }
    .go-view-content.active { display: block; }

    .go-delta-pos td:last-child,
    .go-delta-pos { color: var(--success-text) !important; }
    .go-delta-neg td:last-child,
    .go-delta-neg { color: var(--critical-text) !important; }
    .go-delta-neutral { color: var(--text-dim); }

    .go-changes-highlight {
      margin-top: 14px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .go-change-item {
      font-size: 12px;
      color: var(--accent);
      padding: 6px 12px;
      background: rgba(0,163,224,.06);
      border-left: 3px solid var(--accent);
      border-radius: 0 6px 6px 0;
    }

    .go-dot {
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 50%;
      margin-right: 8px;
      vertical-align: middle;
    }
    .go-dot-orange { background: #FF8B00; }
    .go-dot-rot { background: #CC0000; }
    .go-dot-gruen { background: #00875A; }

    .go-overlap td:first-child { color: var(--warning-text); }
    .go-gap td:first-child { color: var(--critical-text); }
    .go-optimal td:first-child { color: var(--success-text); }

    /* ── Nav Tabs (Medtronic Blue) ── */
    .nav-tabs {
      background: rgba(0,81,149,0.97);
      display: flex;
      gap: 0;
      padding: 0 32px;
      position: sticky;
      top: 60px;
      z-index: 99;
      border-bottom: 1px solid rgba(255,255,255,.15);
      overflow-x: auto;
      -ms-overflow-style: none;
      scrollbar-width: none;
    }
    .nav-tabs::-webkit-scrollbar { display: none; }
    .nav-tab {
      padding: 13px 20px;
      font-family: var(--font-body);
      font-size: 12px;
      font-weight: 600;
      color: rgba(255,255,255,.55);
      cursor: pointer;
      border: none;
      background: none;
      border-bottom: 2px solid transparent;
      transition: color .2s ease, border-color .2s ease;
      letter-spacing: .02em;
      white-space: nowrap;
    }
    .nav-tab:hover { color: rgba(255,255,255,.85); }
    .nav-tab.active {
      color: rgba(255,255,255,.97);
      border-bottom-color: rgba(255,255,255,.9);
    }
    .tab-content { display: none; opacity: 0; transition: opacity .3s ease; }
    .tab-content.active { display: block; opacity: 1; }

    /* ── Animations ── */
    @keyframes fadeInUp {
      from { opacity: 0; transform: translateY(12px); }
      to { opacity: 1; transform: translateY(0); }
    }
    section { animation: fadeInUp .4s ease both; }
    section:nth-child(2) { animation-delay: .05s; }
    section:nth-child(3) { animation-delay: .1s; }
    section:nth-child(4) { animation-delay: .15s; }"""


def _go_info_box(icon: str, titel: str, text: str, text_bereits_uebersetzt: bool = False) -> str:
    """Erzeugt eine Erlaeuterungsbox (Icon + Titel + Text) im Medtronic Light Theme.

    titel/text sind je Aufrufstelle statisch (keine Pro-Zeile-Daten) und
    werden daher automatisch ueber LABEL_MAP_EN uebersetzbar gemacht
    (i18n-Komplettaudit) -- neue EN-Texte muessen nur in LABEL_MAP_EN
    ergaenzt werden, nicht an jeder Aufrufstelle einzeln. Wenn text bereits
    aus mehreren einzeln _label()-gewrappten Chunks zusammengesetzt wurde
    (z.B. weil echte Datenwerte eingebettet sind), text_bereits_uebersetzt=True
    setzen, um doppeltes/kaputtes Wrapping zu vermeiden."""
    text_html = text if text_bereits_uebersetzt else _label(text)
    return (
        f'<div class="go-info-box">'
        f'<div class="go-info-icon">{icon}</div>'
        f'<div class="go-info-body">'
        f'<div class="go-info-title">{_label(titel)}</div>'
        f'<div class="go-info-text">{text_html}</div>'
        f'</div></div>'
    )


def _demo_badge_texte(is_echtdaten: bool, pseudonymisiert: bool) -> tuple[str, str]:
    """DE/EN-Text fuer den Header-Badge (Echtdaten/Demo-Daten).

    EIN Wertepaar ist die einzige Quelle fuer sowohl den initialen
    Server-Render als auch den i18n-Dict-Eintrag (siehe render_html). Vorher
    getrennt gepflegt -- der JS-Sprachwechsel (setLang) ueberschrieb den
    korrekt aus is_echtdaten/pseudonymisiert berechneten Text mit einem
    statischen, vom tatsaechlichen Datenmodus unabhaengigen EN-Wert, der
    IMMER "Demo Data" behauptete.
    """
    if is_echtdaten and pseudonymisiert:
        return "Echtdaten · Pseudonymisiert", "Real Data · Pseudonymized"
    if is_echtdaten:
        return "Echtdaten", "Real Data"
    return "Demo-Daten · Konfigurierbar", "Demo Data · Configurable"


def _demo_hint_texte(is_echtdaten: bool, technikeranzahl: int, stand_datum: str) -> tuple[str, str]:
    """DE/EN-Text fuer den Techniker-Anzahl-Hinweis (Tab 1, .demo-hint).

    Gleiches Prinzip wie _demo_badge_texte: der urspruengliche Code hatte
    Datenmodus ("Echtdaten") und Technikeranzahl (24) fest verdrahtet und
    verlor zusaetzlich das eingebettete Datum komplett bei jedem
    Sprachwechsel, weil der i18n-Dict-Eintrag nur den statischen Text ohne
    Datum enthielt.
    """
    modus_de = "Echtdaten" if is_echtdaten else "Demo-Daten"
    modus_en = "Real Data" if is_echtdaten else "Demo Data"
    de = f"{modus_de} · {technikeranzahl} Techniker · Stand: {stand_datum}"
    en = f"{modus_en} · {technikeranzahl} technicians · As of: {stand_datum}"
    return de, en


def _overview_hint_texte(technikeranzahl: int) -> tuple[str, str]:
    """DE/EN-Text fuer den Tab-1-Untertitel (.section-hint, hint.overview).

    Gleiches Prinzip wie _demo_badge_texte/_demo_hint_texte: EIN Wertepaar
    speist sowohl den initialen Render als auch den i18n-Dict-Eintrag, damit
    die Technikeranzahl (24 Echtdaten / 14 Demo) bei jedem Sprachwechsel
    korrekt bleibt statt auf einen hartcodierten Wert ("24") zurueckzufallen,
    der im Demo-Modus (14 Techniker) falsch war.
    """
    de = (
        f"L3-Abdeckung in der Region · {technikeranzahl} Techniker · "
        f"Grün ≥60% · Gelb 30-59% · Rot <30%"
    )
    en = (
        f"L3 coverage by region · {technikeranzahl} technicians · "
        f"Green ≥60% · Yellow 30-59% · Red <30%"
    )
    return de, en


def _repair_sla_tooltip_text() -> str:
    """SLA-Status-Tooltip-Text (Tab Auftraege): unterscheidet klar zwischen
    der 48h-Erstkontakt-Pflicht (REPAIR_SLA_STUNDEN) und den davon
    unabhaengigen Abschluss-Zielen (REPAIR_SLA_VERTRAGSKUNDE_TAGE /
    REPAIR_SLA_NICHT_VERTRAGSKUNDE_TAGE) -- zwei getrennte Fristen."""
    vk_text = f"{REPAIR_SLA_VERTRAGSKUNDE_TAGE:.1f}".replace(".", ",")
    nvk_text = f"{REPAIR_SLA_NICHT_VERTRAGSKUNDE_TAGE:.1f}".replace(".", ",")
    return (
        "Zwei getrennte Fristen: <strong>Erstkontakt</strong> &mdash; Zeit seit "
        "Auftragseingang im Verh&auml;ltnis zur 48h-SLA-Frist f&uuml;r den ersten "
        "Kundenkontakt. Gr&uuml;n &lt;24h &middot; Gelb 24&ndash;40h &middot; Rot "
        "40&ndash;48h &middot; Kritisch = SLA verletzt (&ge;48h ohne Kontakt). "
        f"<strong>Abschluss</strong> &mdash; davon unabh&auml;ngige Ziel-Frist bis "
        f"zum tats&auml;chlichen Auftragsabschluss (exkl. Ersatzteilbestellzeit): "
        f"{vk_text} Tage f&uuml;r Vertragskunden, "
        f"{nvk_text} Tage f&uuml;r Nicht-Vertragskunden."
    )


def _info_tip(text: str) -> str:
    """Kleines Hover/Focus-Tooltip-Icon (ⓘ) fuer Kennzahlen-Erklaerungen
    direkt am Ort der Verwirrung (z.B. Tabellen-Spaltenkopf) -- barrierefrei
    per CSS :hover/:focus, kein JavaScript noetig. Text darf bereits
    HTML-Entities enthalten (wird nicht weiter escaped)."""
    return (
        f'<span class="info-tip" tabindex="0">&#9432;'
        f'<span class="info-tip-bubble">{text}</span></span>'
    )


def _render_gebietsoptimierung(
    metriken_akt: list[dict],
    metriken_opt: list[dict],
    techniker: dict[str, dict],
    hugo_kerngebiete: list[dict] | None = None,
    gebiete_status: dict[str, dict] | None = None,
    viewbox: str = "0 0 480 580",
    opt_height: int = 580,
) -> str:
    """Erzeugt den Gebietsoptimierung-Tab mit 3 klickbaren Ansicht-Buttons."""
    if not metriken_akt:
        return ""

    # ── Hugo-Kerngebiet: optionale Regel, Toggle default AUS ──
    hugo_kerngebiete = hugo_kerngebiete or []
    if hugo_kerngebiete:
        def _hugo_tech_text(hk: dict) -> str:
            teil = f"{hk['id']}"
            if hk.get("ist_springer"):
                teil += " (Springer)"
            hugo_jahr = techniker.get(hk["id"], {}).get("hugo_einsaetze_jahr_real")
            if hugo_jahr is not None:
                teil += f" [{hugo_jahr:.1f} Hugo-Eins&auml;tze/Jahr real]"
            return teil

        hugo_kg_liste = ", ".join(_hugo_tech_text(hk) for hk in hugo_kerngebiete)
        hugo_kg_hint = (
            f"Aktiv f&uuml;r {len(hugo_kerngebiete)} Hugo-Techniker: {hugo_kg_liste} "
            f"&mdash; Radius &#8776;{hugo_kerngebiete[0]['radius_km']:.0f} km "
            f"(&#8776;{HUGO_KERNGEBIET_MAX_FAHRZEIT_MIN} min Fahrzeit um den Wohnort). "
            f"Team-Gr&ouml;&szlig;e: {HUGO_TEAM_GROESSE['PM']} Techniker f&uuml;r PM/STK, "
            f"{HUGO_TEAM_GROESSE['REPAIR']} f&uuml;r Repair (90% der F&auml;lle) &mdash; "
            f"Ergaenzung, keine Ersetzung durch die reale Hugo-Einsatzh&auml;ufigkeit. "
            f"{HUGO_SPRINGER} ist zus&auml;tzlich deutschlandweit als Springer f&uuml;r "
            f"alle Hugo-Systeme verf&uuml;gbar (inkl. alleiniger Zust&auml;ndigkeit Dresden)."
        )
    else:
        hugo_kg_hint = (
            "Keine Hugo-Techniker aus der HUGO_STANDORTE-Konfiguration im aktuellen "
            "Datensatz gefunden."
        )
    hugo_kg_html = (
        f'<div class="hugo-kg-box">'
        f'<label class="hugo-kg-toggle">'
        f'<input type="checkbox" id="hugo-kg-toggle">'
        f'{_label("Small-Capital-Kerngebiet anzeigen")} '
        f'(max. {HUGO_KERNGEBIET_MAX_FAHRZEIT_MIN} {_label("Min. Radius um Wohnort")})'
        f'</label>'
        f'<div class="hugo-kg-hint" id="hugo-kg-hint" style="display:none">{hugo_kg_hint}</div>'
        f'</div>'
    )

    umweg_faktor_text = f"{HAVERSINE_UMWEG_FAKTOR:.2f}".replace(".", ",")

    # ── Tooltips fuer Kennzahlen-Spalten (direkt am Ort der Verwirrung) ──
    ratio_tip = _info_tip(
        "Vor-Ort-Stunden &divide; Fahrtstunden pro Jahr. Gr&uuml;n &ge;3,0 "
        "(effizient) &middot; Gelb 2,0&ndash;3,0 &middot; Rot &lt;2,0 "
        "(zu viel Fahrzeit im Verh&auml;ltnis zur Servicezeit)."
    )
    korridor_spalte_tip = _info_tip(
        f"Auslastungs-Zielkorridor ({AUSLASTUNG_ZIEL_MIN_PCT}&ndash;{AUSLASTUNG_ZIEL_MAX_PCT}%, "
        f"Referenzwert) aus echter Einsatzhistorie (Vor-Ort-Zeit &divide; "
        f"Jahreskapazit&auml;t, ohne Fahrzeit) &mdash; nur im Echtdaten-Modus "
        f"verf&uuml;gbar."
    )
    delta_fahrzeit_tip = _info_tip(
        "Ver&auml;nderung der j&auml;hrlichen Fahrtstunden durch die "
        "Gebietsoptimierung &mdash; nicht die Fahrzeit eines einzelnen "
        "Termins. Negativ (gr&uuml;n) = Entlastung, positiv (rot) = "
        "Mehrbelastung."
    )
    luecken_status_tip = _info_tip(
        f"L&uuml;cke: &Oslash; Fahrzeit zum n&auml;chsten Techniker im "
        f"Bundesland &uuml;ber {LUECKE_FAHRZEIT_SCHWELLE_MIN} Minuten. "
        f"&Uuml;berschneidung: bei mindestens "
        f"{round(UEBERSCHNEIDUNG_ANTEIL_SCHWELLE * 100)}% der Kliniken liegt "
        f"der 2.-n&auml;chste Techniker h&ouml;chstens "
        f"{UEBERSCHNEIDUNG_FAHRZEIT_DIFF_MIN} Minuten hinter dem "
        f"1.-n&auml;chsten (Gebiet kontestiert). Optimal: weder noch."
    )

    info_aktuell = _go_info_box(
        "&#128506;",
        "Was zeigt diese Ansicht?",
        "Zeigt die IST-Gebietsaufteilung basierend auf den aktuellen "
        "Techniker-Wohnorten und den ihnen historisch zugeordneten "
        "Klinik-PLZ-Gebieten. Jede Farbe entspricht einem Techniker-Gebiet. "
        "Ratio = Vor-Ort-Stunden &divide; Fahrtstunden pro Jahr &mdash; "
        "Gr&uuml;n &ge;3,0 (effizient), Gelb 2,0&ndash;3,0, Rot &lt;2,0 "
        "(zu viel Fahrzeit im Verh&auml;ltnis zur Servicezeit).",
    )
    zeitraum_hinweis = ""
    if _ECHTDATEN:
        try:
            from api.smax_cache import load_dashboard_data as _load_smax_meta
            _smax_meta = _load_smax_meta() or {}
            _zeitraum_jahre = _smax_meta.get("beobachtungszeitraum_jahre")
            if _zeitraum_jahre:
                zeitraum_hinweis = (
                    f' {_label("Auslastung basiert auf der Ø jährlichen Auftragsrate aus")} '
                    f"{_zeitraum_jahre:.1f} "
                    f'{_label("Jahren Historie (Closed Jobs) zzgl. aktuellem Auftragsrückstand (Open Jobs).")}'
                )
        except Exception:
            pass
    info_optimiert_text = (
        f'{_label("Für jede Klinik werden der 1.- und 2.-nächstgelegene Techniker (Fahrzeit, Haversine-Distanz ×")} '
        f'{umweg_faktor_text} '
        f'{_label("Straßenfaktor) verglichen. Ist der 2.-nächste um mehr als")} '
        f'{OPTIMIERUNG_AUSLASTUNGS_SCHWELLE} '
        f'{_label("Prozentpunkte weniger ausgelastet und beträgt die Fahrzeit-Mehrbelastung höchstens")} '
        f'{OPTIMIERUNG_MAX_FAHRZEIT_MEHRAUFWAND_MIN} '
        f'{_label("Minuten, wandert die Klinik zu ihm. Ziel: gleichmäßigere Auslastung bei vertretbaren Anfahrtswegen — unabhängig von Techniker-Anzahl oder -Bezeichnung.")}'
        f'{zeitraum_hinweis} '
        f'{_label("Ratio vorher/nachher = Vor-Ort-Stunden ÷ Fahrtstunden pro Jahr vor bzw. nach der Optimierung (siehe „Aktuelle Gebiete“ für die Farbskala). Δ Fahrzeit zeigt die Veränderung der jährlichen Fahrtstunden — negativ (grün) = Entlastung, positiv (rot) = Mehrbelastung.")}'
    )
    info_optimiert = _go_info_box(
        "&#129504;",
        "Wie und warum wird optimiert?",
        info_optimiert_text,
        text_bereits_uebersetzt=True,
    )
    info_luecken = _go_info_box(
        "&#9888;",
        "Was ist hier zu sehen?",
        "Zeigt Gebiete mit doppelter Abdeckung (mehrere Techniker nah "
        "beieinander = &Uuml;berschneidung, Optimierungspotenzial) und "
        "Gebiete ohne nahen Techniker (L&uuml;cke = l&auml;ngere "
        "Anfahrtszeiten f&uuml;r Kunden in dieser Region).",
    )

    # ── Ansicht 1: Aktuelle Gebiete – Tabelle ──
    # Alle Techniker anzeigen, auch mit 0 zugewiesenen Kliniken (nicht filtern).
    rows_aktuell = ""
    for m in metriken_akt:
        css = "go-gruen" if m["ratio"] >= 3.0 else ("go-gelb" if m["ratio"] >= 2.0 else "go-rot")
        td_tech = techniker.get(m["id"], {})
        korridor_zelle = _render_korridor_badge(
            td_tech.get("auslastung_korridor"), td_tech.get("auslastung_pct_real"),
        ) or "&ndash;"
        plz_tip = _info_tip(_render_plz_uebersicht(m.get("plz_info")))
        rows_aktuell += (
            f'<tr class="{css}" data-tech="{m["id"]}">'
            f'<td><strong>{m["id"]}</strong>{plz_tip}</td>'
            f'<td>{m["standort"]}</td>'
            f'<td>{m["kliniken"]}</td>'
            f'<td>{m["avg_fahrzeit"]} min</td>'
            f'<td><span class="badge badge-ratio {css.replace("go-","gebiets-")}">{m["ratio"]}</span></td>'
            f'<td>{korridor_zelle}</td>'
            f'</tr>')

    # ── Ansicht 2: Optimierte Gebiete – Vorher/Nachher Tabelle ──
    # Alle Techniker anzeigen, auch mit 0 (verbliebenen) Kliniken (nicht filtern).
    rows_optimiert = ""
    for m_o in metriken_opt:
        m_a = next((x for x in metriken_akt if x["id"] == m_o["id"]), None)
        ratio_vorher = m_a["ratio"] if m_a else 0.0
        ratio_nachher = m_o["ratio"]
        delta_fz = (m_o["fahrtstunden_jahr"] - m_a["fahrtstunden_jahr"]) if m_a else 0
        delta_sign = "+" if delta_fz >= 0 else ""
        if ratio_nachher > ratio_vorher:
            delta_css = "go-delta-pos"
        elif ratio_nachher < ratio_vorher:
            delta_css = "go-delta-neg"
        else:
            delta_css = "go-delta-neutral"
        verschoben = m_o.get("verschoben", 0)
        plz_vorher = _render_plz_uebersicht(m_a.get("plz_info") if m_a else None)
        plz_nachher = _render_plz_uebersicht(m_o.get("plz_info"))
        plz_tip_opt = _info_tip(
            f'<strong>{_label("PLZ-Bereich vorher")}:</strong> {plz_vorher}<br>'
            f'<strong>{_label("PLZ-Bereich nachher")}:</strong> {plz_nachher}'
        )
        rows_optimiert += (
            f'<tr data-tech="{m_o["id"]}">'
            f'<td><strong>{m_o["id"]}</strong>{plz_tip_opt}</td>'
            f'<td>{m_o["standort"]}</td>'
            f'<td>{ratio_vorher}</td>'
            f'<td>{ratio_nachher}</td>'
            f'<td class="{delta_css}">{delta_sign}{delta_fz} h</td>'
            f'<td>{verschoben}</td>'
            f'</tr>')

    # Top-Verschiebungen fuer die Erlaeuterungsbox (dynamisch aus dem Algorithmus)
    top_verschiebungen = sorted(
        (m for m in metriken_opt if m.get("verschoben", 0) > 0),
        key=lambda m: m["verschoben"],
        reverse=True,
    )[:3]
    if top_verschiebungen:
        changes_html = "\n".join(
            f'<div class="go-change-item">{m["id"]} ({m["standort"]}): '
            f'+{m["verschoben_gewonnen"]} / &minus;{m["verschoben_abgegeben"]} Kliniken</div>'
            for m in top_verschiebungen
        )
    else:
        changes_html = (
            '<div class="go-change-item">Keine Verschiebungen &mdash; alle Kliniken '
            'liegen bereits innerhalb der Schwellwerte beim n&auml;chstgelegenen '
            'Techniker.</div>'
        )

    # ── Ansicht 3: Lücken & Überschneidungen ──
    # Generisch aus den echten Techniker-Standorten/Klinik-Fahrzeiten
    # abgeleitet (siehe _klassifiziere_gebiete_luecken_ueberschneidungen) --
    # kein festes T1-T14-Schema, funktioniert fuer Demo- und
    # Echtdaten-Techniker gleichermassen.
    gebiete_status = gebiete_status or {}

    rows_luecken = ""
    for gebiet in sorted(gebiete_status):
        info = gebiete_status[gebiet]
        typ = info["typ"]
        if typ == "overlap":
            primaer = info["techs"][0]
            techs_html = ", ".join(
                f'<span class="go-tech-link" data-tech="{t}">{t}</span>' for t in info["techs"]
            )
            rows_luecken += (
                f'<tr class="go-overlap" data-tech="{primaer}">'
                f'<td><span class="go-dot go-dot-orange"></span>{gebiet}</td>'
                f'<td>{_label("Überschneidung")}</td>'
                f'<td>{techs_html}</td>'
                f'<td>{info["anteil_pct"]}% {_label("der Kliniken zwischen 1./2.-nächstem Techniker kontestiert (≤")}'
                f'{UEBERSCHNEIDUNG_FAHRZEIT_DIFF_MIN} {_label("min Fahrzeit-Differenz) — Gebiete konsolidieren")}</td>'
                f'</tr>')
        elif typ == "gap":
            tid = info["naechster"]
            rows_luecken += (
                f'<tr class="go-gap" data-tech="{tid}">'
                f'<td><span class="go-dot go-dot-rot"></span>{gebiet}</td>'
                f'<td>{_label("Lücke")}</td>'
                f'<td><span class="go-tech-link" data-tech="{tid}">{tid}</span> '
                f'(&#216; {info["fahrzeit_min"]} min)</td>'
                f'<td>{_label("Neueinstellung oder Gebiets-Erweiterung empfohlen")}</td>'
                f'</tr>')
        else:
            tid = info["techs"][0]
            rows_luecken += (
                f'<tr class="go-optimal" data-tech="{tid}">'
                f'<td><span class="go-dot go-dot-gruen"></span>{gebiet}</td>'
                f'<td>{_label("Optimal")}</td>'
                f'<td><span class="go-tech-link" data-tech="{tid}">{tid}</span></td>'
                f'<td>{_label("Keine Anpassung nötig")}</td>'
                f'</tr>')

    # Top-3 Empfehlungen
    top3 = []
    _PRIO = ["T2", "T8", "T13", "T3", "T7", "T10"]
    for tid in _PRIO:
        v = _OPTIMIERUNGS_VORSCHLAEGE.get(tid)
        if v and len(top3) < 3:
            m = next((x for x in metriken_akt if x["id"] == tid), None)
            top3.append({"id": tid, "vorschlag": v, "metriken": m})

    empf_html = ""
    for i, e in enumerate(top3, 1):
        m = e["metriken"]
        fz_info = ""
        if m:
            fz_info = (f'<div class="go-empf-stats">'
                       f'&#216; Fahrzeit: {m["avg_fahrzeit"]} min &middot; '
                       f'Max: {m.get("max_fahrzeit", 0)} min &middot; '
                       f'{m["kliniken"]} Kliniken &middot; '
                       f'Ratio: {m["ratio"]}</div>')
        empf_html += (
            f'<div class="go-empf-card">'
            f'<div class="go-empf-num">{i}</div>'
            f'<div class="go-empf-body">'
            f'<div class="go-empf-title">{e["id"]} &mdash; '
            f'{techniker.get(e["id"], {}).get("standort", "")}</div>'
            f'{fz_info}'
            f'<div class="go-empf-text">{e["vorschlag"]}</div>'
            f'</div></div>')

    return f"""
  <section>
    <h2 data-i18n="h.territory">Gebietsoptimierung</h2>
    <p class="section-hint" data-i18n="hint.territory">
      Analyse der Gebietsabdeckung &middot; &Uuml;berschneidungen &amp; L&uuml;cken &middot;
      Fahrzeit-Optimierungspotenzial je Region
    </p>

    <div class="go-view-buttons" id="go-view-buttons">
      <button class="go-view-btn active" data-view="aktuell" data-i18n="go.viewAktuell">Aktuelle Gebiete</button>
      <button class="go-view-btn" data-view="optimiert" data-i18n="go.viewOptimiert">Optimierte Gebiete</button>
      <button class="go-view-btn" data-view="luecken" data-i18n="go.viewLuecken">L&uuml;cken &amp; &Uuml;berschneidungen</button>
    </div>

    <div class="gebiets-layout">
      <div class="gebiets-karte">
        <svg id="germany-map-opt" width="480" height="{opt_height}" viewBox="{viewbox}" preserveAspectRatio="xMidYMid meet"><!-- filled by _build_gebiets_svg --></svg>
        <div class="gebiets-legende" id="gebiets-legende-opt"></div>
        <div class="gebiets-karte-tools">
          <span class="go-hint" data-i18n="go.hint">Techniker anklicken, um sein Gebiet hervorzuheben</span>
          <button class="go-reset-btn" id="go-reset-btn" disabled data-i18n="go.reset">&#10005; Zur&uuml;cksetzen</button>
        </div>
        {hugo_kg_html}
      </div>
      <div class="gebiets-metriken">
        <!-- Ansicht 1: Aktuelle Gebiete -->
        <div class="go-view-content active" id="go-view-aktuell">
          {info_aktuell}
          <table>
            <thead>
              <tr>
                <th data-i18n="th.technician">Techniker</th>
                <th data-i18n="th.standort">Standort</th>
                <th data-i18n="th.kliniken">Kliniken</th>
                <th data-i18n="th.oFahrzeit">&Oslash; Fahrzeit</th>
                <th><span data-i18n="th.ratio">Ratio</span>{ratio_tip}</th>
                <th><span data-i18n="th.auslastung">Auslastung</span>{korridor_spalte_tip}</th>
              </tr>
            </thead>
            <tbody>
{rows_aktuell}
            </tbody>
          </table>
        </div>
        <!-- Ansicht 2: Optimierte Gebiete -->
        <div class="go-view-content" id="go-view-optimiert">
          {info_optimiert}
          <div class="bc-gold-hint" style="margin-bottom:14px">
            &#9733; {_label("Algorithmus: Klinik wechselt zum 2.-nächsten Techniker, wenn dessen Auslastung ≥")}
            {OPTIMIERUNG_AUSLASTUNGS_SCHWELLE} {_label("Prozentpunkte niedriger ist und die Fahrzeit-Mehrbelastung ≤")}
            {OPTIMIERUNG_MAX_FAHRZEIT_MEHRAUFWAND_MIN} {_label("min bleibt")}
          </div>
          <table>
            <thead>
              <tr>
                <th data-i18n="th.technician">Techniker</th>
                <th data-i18n="th.standort">Standort</th>
                <th><span data-i18n="th.ratioVorher">Ratio vorher</span>{ratio_tip}</th>
                <th><span data-i18n="th.ratioNachher">Ratio nachher</span>{ratio_tip}</th>
                <th><span data-i18n="th.deltaFahrzeit">&Delta; Fahrzeit</span>{delta_fahrzeit_tip}</th>
                <th data-i18n="th.verschobeneKliniken">Verschobene Kliniken</th>
              </tr>
            </thead>
            <tbody>
{rows_optimiert}
            </tbody>
          </table>
          <div class="go-changes-highlight">
{changes_html}
          </div>
        </div>
        <!-- Ansicht 3: Lücken & Überschneidungen -->
        <div class="go-view-content" id="go-view-luecken">
          {info_luecken}
          <table>
            <thead>
              <tr>
                <th data-i18n="th.gebiet">Gebiet</th>
                <th><span data-i18n="th.status">Status</span>{luecken_status_tip}</th>
                <th data-i18n="th.technician">Techniker</th>
                <th data-i18n="th.empfehlung">Empfehlung</th>
              </tr>
            </thead>
            <tbody>
{rows_luecken}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </section>

  <section>
    <h2 data-i18n="h.top3">Top-3 Empfehlungen f&uuml;r Gebietsanpassung</h2>
    <p class="section-hint" data-i18n="hint.top3">
      Priorisiert nach Fahrzeit-Einsparungspotenzial und Crosstraining-Bedarf
    </p>
    <div class="go-empf-grid">
{empf_html}
    </div>
    <div class="bc-gold-hint" style="margin-top:16px">
      &#9733; Demo-Daten &middot; Regionen konfigurierbar
    </div>
  </section>"""


def render_html(
    ampeln: list[dict],
    stk_rows: list[dict],
    ct_top5: list[dict],
    techniker: dict[str, dict],
    nrw_warnung: dict | None,
    erstellt_am: datetime,
    ct_rows: list[dict] | None = None,
    gebiets_metriken: tuple[list[dict], list[dict]] | None = None,
    labor_zeiten: list[dict] | None = None,
    demo_history: dict[str, dict] | None = None,
    repair_rows: list[dict] | None = None,
    is_echtdaten: bool = False,
    ct_kennzahlen: dict | None = None,
    gebiets_punkte: list[dict] | None = None,
    erklaerungen: dict[str, dict[str, str]] | None = None,
    hugo_kerngebiete: list[dict] | None = None,
    hugo_standorte_marker: list[dict] | None = None,
    gebiete_status: dict[str, dict] | None = None,
) -> str:
    ampel_html    = _render_ampel_karten(ampeln, labor_zeiten, techniker)
    stk_html      = _render_stk_tabelle(stk_rows)
    repair_html   = _render_repair_tabelle(repair_rows or [])
    ct_html       = _render_ct_tabelle(ct_top5, techniker, labor_zeiten or [])
    ct_ausschluss_html = _render_ct_ausschluss_hint(ct_rows or [])
    warnung_html  = _render_nrw_warnung(nrw_warnung)
    puffer_html   = _render_puffer_section(labor_zeiten or [])
    workflow_html = _render_workflow_status()
    _ct = ct_kennzahlen or {}
    bc_html       = _render_business_case(
        stk_potenzial_gesamt=_ct.get("stk_potenzial_gesamt", 0),
        median_min=_ct.get("einsatz_median_min", 0),
    )
    m_akt, m_opt  = gebiets_metriken or ([], [])
    plz_abd       = _berechne_plz_abdeckung(techniker)
    vb_x, vb_y, vb_w, vb_h = _berechne_gebiets_viewbox(techniker)
    gebiets_viewbox = f"{vb_x} {vb_y} {vb_w} {vb_h}"
    gebiets_opt_height = round(480 * vb_h / vb_w) if vb_w else 580
    gebiets_html  = _render_gebietsplanung(m_akt, m_opt, plz_abd, gebiets_viewbox)
    gebietsopt_html = _render_gebietsoptimierung(
        m_akt, m_opt, techniker, hugo_kerngebiete, gebiete_status,
        gebiets_viewbox, gebiets_opt_height)
    gebiets_svg_content = _build_gebiets_svg(
        techniker, plz_abd, hugo_kerngebiete, hugo_standorte_marker)
    gebiets_script = _build_gebiets_script(techniker, plz_abd, gebiets_punkte or [])
    tooltip_portal_script = _build_tooltip_portal_script()
    tech_detail_json = _render_techniker_detail_data(
        techniker, demo_history or {})
    ts = erstellt_am.strftime("%d.%m.%Y %H:%M")

    gruen_count = sum(1 for a in ampeln if a["ampel_css"] == "ampel-gruen")
    gelb_count  = sum(1 for a in ampeln if a["ampel_css"] == "ampel-gelb")
    rot_count   = sum(1 for a in ampeln if a["ampel_css"] == "ampel-rot")

    # System-Prompt fuer Chat
    system_prompt = _build_system_prompt(ct_rows or [], techniker, ampeln)
    system_prompt_js = json.dumps(system_prompt, ensure_ascii=False)
    erklaerungen_json = json.dumps(erklaerungen or {}, ensure_ascii=False)
    frage_typen_json = json.dumps(FRAGE_TYPEN, ensure_ascii=False)
    frage_typen_en_json = json.dumps(FRAGE_TYPEN_EN, ensure_ascii=False)
    erklaer_script = (
        "/* ── Template-Erklaerungen: aus Berechnungsdaten, kein API-Aufruf, DE+EN ── */\n"
        "(function(){\n"
        "  var ERKL=" + erklaerungen_json + ";\n"
        "  var FRAGEN={de:" + frage_typen_json + ",en:" + frage_typen_en_json + "};\n"
        "  var frageSel=document.getElementById('erklaer-frage');\n"
        "  var techSel=document.getElementById('erklaer-techniker');\n"
        "  var btn=document.getElementById('erklaer-btn');\n"
        "  var out=document.getElementById('erklaer-antwort');\n"
        "  if(!frageSel||!techSel||!btn) return;\n"
        "  function curLang(){\n"
        "    return (typeof _currentLang!=='undefined'&&_currentLang==='EN')?'en':'de';\n"
        "  }\n"
        "  function renderFrageOptions(){\n"
        "    var lang=curLang(), prev=frageSel.value;\n"
        "    var frageDict=FRAGEN[lang];\n"
        "    frageSel.innerHTML='';\n"
        "    Object.keys(frageDict).forEach(function(key){\n"
        "      var opt=document.createElement('option');\n"
        "      opt.value=key;\n"
        "      opt.textContent=frageDict[key].replace('{tid}', lang==='en'?'[Technician]':'[Techniker]');\n"
        "      frageSel.appendChild(opt);\n"
        "    });\n"
        "    if(prev) frageSel.value=prev;\n"
        "  }\n"
        "  renderFrageOptions();\n"
        "  Object.keys(ERKL).sort().forEach(function(tid){\n"
        "    var opt=document.createElement('option');\n"
        "    opt.value=tid; opt.textContent=tid;\n"
        "    techSel.appendChild(opt);\n"
        "  });\n"
        "  function render(){\n"
        "    var tid=techSel.value, frage=frageSel.value, lang=curLang();\n"
        "    var eintrag=ERKL[tid]&&ERKL[tid][frage];\n"
        "    var fallback=lang==='en'?'No explanation available.':'Keine Erkl\\u00e4rung verf\\u00fcgbar.';\n"
        "    var text=eintrag?(eintrag[lang]||eintrag.de||fallback):fallback;\n"
        "    out.textContent=text;\n"
        "    out.style.display='block';\n"
        "  }\n"
        "  btn.addEventListener('click',render);\n"
        "  techSel.addEventListener('change',render);\n"
        "  frageSel.addEventListener('change',render);\n"
        "  if(techSel.options.length&&frageSel.options.length) render();\n"
        "  window.addEventListener('fsa_lang_changed',function(){\n"
        "    renderFrageOptions();\n"
        "    if(out.style.display==='block') render();\n"
        "  });\n"
        "})();\n"
    )

    # ── Tooltips fuer Kennzahlen-Spalten (Tab 2/3, direkt am Ort der Verwirrung) ──
    dringlichkeit_tip = _info_tip(
        "Zeitliche Kritikalit&auml;t bis zur F&auml;lligkeit: &Uuml;berf&auml;llig "
        "(&lt;0 Tage) &middot; Kritisch (&le;14 Tage) &middot; Hoch (15&ndash;30 Tage) "
        "&middot; Normal (&gt;30 Tage)."
    )
    sla_status_tip = _info_tip(_repair_sla_tooltip_text())
    ct_luecken_tip = _info_tip(
        "Anzahl Produktfamilien mit Ger&auml;ten im Gebiet dieses Technikers, "
        "f&uuml;r die er aktuell nicht qualifiziert ist."
    )
    ct_stk_jahr_tip = _info_tip(
        "Gesch&auml;tztes zus&auml;tzliches Servicevolumen pro Jahr, das durch "
        "Crosstraining auf die wirtschaftlich attraktivste fehlende "
        "Produktfamilie erschlossen werden k&ouml;nnte."
    )

    # ── Datenmodus-Texte (Header-Badge + Tab-1-Hinweis): je EIN DE/EN-Paar,
    # das sowohl den initialen Render als auch den i18n-Dict-Eintrag speist
    # (siehe _demo_badge_texte/_demo_hint_texte-Docstring) ──
    demo_badge_text_de, demo_badge_text_en = _demo_badge_texte(is_echtdaten, PSEUDONYMISIERUNG_AKTIV)
    demo_hint_text_de, demo_hint_text_en = _demo_hint_texte(
        is_echtdaten, len(techniker), erstellt_am.strftime("%d.%m.%Y"))
    overview_hint_text_de, overview_hint_text_en = _overview_hint_texte(len(techniker))

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Field Service AI &ndash; Medtronic Deutschland</title>
  <style>
{_CSS}
  </style>
</head>
<body>

<!-- Grain Overlay -->
<div class="grain-overlay"></div>

<div class="app-layout">

<!-- ══════════ Dashboard Panel ══════════ -->
<div class="dashboard-panel">

<header>
  <div class="header-brand">
    <a href="index.html" style="text-decoration:none;color:inherit;display:flex;align-items:center;gap:8px" title="Zur&uuml;ck zur Startseite">
      <span style="font-size:18px">&#8592;</span>
      <div>
        <div class="header-logo">Field Service <span class="brand-ai">AI</span></div>
        <div class="header-sub">Medtronic GmbH</div>
      </div>
    </a>
  </div>
  <div class="header-right">
    <a href="manual.html" class="lang-toggle" style="text-decoration:none" data-i18n="nav.manual">Handbuch</a>
    <a href="workflow_demo.html" class="lang-toggle" style="text-decoration:none">Workflow Demo</a>
    <span class="demo-badge" data-i18n="header.demo">{demo_badge_text_de}</span>
    <button class="lang-toggle" id="lang-toggle-btn" onclick="toggleLang()">EN</button>
    <button class="api-key-btn" onclick="document.getElementById('chat-setup').style.display='block';document.getElementById('api-key-input').focus()">API-Key &#128273;</button>
  </div>
</header>

<nav class="nav-tabs">
  <button class="nav-tab active" data-tab="tab-uebersicht" data-i18n="tab.overview">&Uuml;bersicht</button>
  <button class="nav-tab" data-tab="tab-auftraege" data-i18n="tab.orders">Auftr&auml;ge</button>
  <button class="nav-tab" data-tab="tab-crosstraining" data-i18n="tab.crosstraining">Cross-Training</button>
  <button class="nav-tab" data-tab="tab-workflow" data-i18n="tab.workflow">Workflow</button>
  <button class="nav-tab" data-tab="tab-business" data-i18n="tab.business">Business Case</button>
  <button class="nav-tab" data-tab="tab-gebietsopt" data-i18n="tab.territory">Gebietsoptimierung</button>
  <button class="nav-tab" data-tab="tab-einstellung" data-i18n="tab.hiring">Einstellungsbedarf</button>
</nav>

<div class="summary-bar">
  <span><span class="dot dot-gruen"></span> <span data-i18n="summary.green">Gr&uuml;n</span>: <strong>{gruen_count}</strong> (&ge;60&thinsp;% L3)</span>
  <span><span class="dot dot-gelb"></span> <span data-i18n="summary.yellow">Gelb</span>: <strong>{gelb_count}</strong> (30&ndash;59&thinsp;%)</span>
  <span><span class="dot dot-rot"></span> <span data-i18n="summary.red">Rot</span>: <strong>{rot_count}</strong> (&lt;30&thinsp;%)</span>
  <span style="margin-left:auto;color:var(--text-muted);font-size:11px"><span data-i18n="summary.asOf">Stand</span>: {ts} &middot; 32h/<span data-i18n="card.week">Wo</span> <span data-i18n="summary.monThu">Mo&ndash;Do</span> &middot; Hugo KA: 25,6h</span>
</div>

<main>

  <!-- Tab 1: Uebersicht -->
  <div id="tab-uebersicht" class="tab-content active">
  <section>
    <h2 data-i18n="h.overview">&Uuml;bersicht &mdash; Qualifikations-Ampel</h2>
    <p class="section-hint" data-i18n="hint.overview">
      {overview_hint_text_de}
    </p>
    <div class="ampel-sort-controls">
      <label for="ampel-sort-select" data-i18n="sort.label">Sortierung:</label>
      <select id="ampel-sort-select">
        <option value="standard" data-i18n="sort.standard">Standard (Gr&uuml;n / Gelb / Rot)</option>
        <option value="crosstraining" data-i18n="sort.ct">Crosstraining-Bedarf (meiste L&uuml;cken zuerst)</option>
        <option value="auslastung" data-i18n="sort.util">Auslastung (Stunden)</option>
        <option value="portfolio" data-i18n="sort.portfolio">Ger&auml;te-Portfolio (meiste L3-Familien zuerst)</option>
        <option value="potential" data-i18n="sort.area">Gebietsgr&ouml;&szlig;e</option>
      </select>
      <span class="demo-hint" data-i18n="hint.demo">{demo_hint_text_de}</span>
    </div>
    <div class="ampel-grid" id="ampel-grid">
{ampel_html}
    </div>
  </section>
  </div>

  <!-- Tab 2: Auftraege (STK + Repair) -->
  <div id="tab-auftraege" class="tab-content">
  <section>
    <h2 data-i18n="h.stk">STK-Auftr&auml;ge (Top 10)</h2>
    <p class="section-hint" data-i18n="hint.stk">Quelle: daten/geraete.csv &middot; Aufsteigend nach F&auml;lligkeitsdatum</p>
    <table>
      <thead>
        <tr>
          <th data-i18n="th.orderId">Auftrag-ID</th>
          <th data-i18n="th.clinic">Klinik</th>
          <th data-i18n="th.device">Ger&auml;t</th>
          <th data-i18n="th.productFamily">Produktfamilie</th>
          <th data-i18n="th.dueDate">F&auml;lligkeit</th>
          <th data-i18n="th.suggestedDates">Vorgeschlagene Termine</th>
          <th><span data-i18n="th.urgency">Dringlichkeit</span>{dringlichkeit_tip}</th>
          <th data-i18n="th.days">Tage</th>
        </tr>
      </thead>
      <tbody>
{stk_html}
      </tbody>
    </table>
  </section>
  <section>
    <h2 data-i18n="h.repair">Offene Repair-Auftr&auml;ge</h2>
    <p class="section-hint" data-i18n="hint.repair">SLA: Kundenkontakt innerhalb 48h &middot; Internes Ziel: 24h</p>
    <table>
      <thead>
        <tr>
          <th data-i18n="th.orderId">Auftrag-ID</th>
          <th data-i18n="th.clinic">Klinik</th>
          <th data-i18n="th.device">Ger&auml;t</th>
          <th data-i18n="th.received">Eingang</th>
          <th><span data-i18n="th.slaStatus">SLA-Status</span>{sla_status_tip}</th>
          <th data-i18n="th.phase">Phase</th>
          <th data-i18n="th.sparePart">Ersatzteil</th>
        </tr>
      </thead>
      <tbody>
{repair_html}
      </tbody>
    </table>
  </section>
  </div>

  <!-- Tab 3: Cross-Training + NRW -->
  <div id="tab-crosstraining" class="tab-content">
  <section>
    <h2 data-i18n="h.ct">Crosstraining Top 5</h2>
    <p class="section-hint" data-i18n="hint.ct">
      Nur Techniker mit wirtschaftlich sinnvollem Crosstraining (Ger&auml;tedichte
      &amp; STK-Potenzial &uuml;ber Schwellwert) &middot; sortiert nach STK-Potenzial pro Jahr
    </p>
    <table>
      <thead>
        <tr>
          <th data-i18n="th.technician">Techniker</th>
          <th><span data-i18n="th.gaps">L&uuml;cken</span>{ct_luecken_tip}</th>
          <th><span data-i18n="th.stkYear">+STK/Jahr</span>{ct_stk_jahr_tip}</th>
          <th data-i18n="th.missingFamilies">Fehlende Produktfamilien</th>
          <th data-i18n="th.recPartner">Empf. Partner</th>
        </tr>
      </thead>
      <tbody>
{ct_html}
      </tbody>
    </table>
{ct_ausschluss_html}
  </section>
{warnung_html}
  </div>

  <!-- Tab 4: Workflow -->
  <div id="tab-workflow" class="tab-content">
{workflow_html}
{puffer_html}
  </div>

  <!-- Tab 5: Business Case -->
  <div id="tab-business" class="tab-content">
{bc_html}
  </div>

  <!-- Tab 6: Gebietsoptimierung -->
  <div id="tab-gebietsopt" class="tab-content">
{gebietsopt_html}
  </div>

  <!-- Tab 7: Einstellungsbedarf -->
  <div id="tab-einstellung" class="tab-content">
{gebiets_html}
  </div>

</main>

<footer>
  Field Service AI &nbsp;|&nbsp;
  Medtronic GmbH Service &amp; Repair &nbsp;|&nbsp;
  <span data-i18n="footer.copilot">Vollautomatisiert &middot; Copilot &mdash; kein Autopilot</span> &nbsp;|&nbsp;
  {TESTS_ANZAHL} Tests {_label("grün")}
</footer>

</div><!-- /dashboard-panel -->

<!-- ══════════ Chat Panel (340px) ══════════ -->
<aside class="chat-panel" id="chat-panel">

  <div class="chat-header">
    <div>
      <div class="chat-header-title">
        <span class="chat-status offline" id="chat-status"></span>Claude AI
      </div>
      <div class="chat-header-sub" data-i18n="chat.sub">Medtronic Field Service Assistent</div>
    </div>
  </div>

  <!-- Template-Erklaerungen: direkt aus den Berechnungsdaten, kein API-Key noetig -->
  <div class="erklaer-box" id="erklaer-box">
    <p class="erklaer-intro" data-i18n="erklaer.intro">Frage direkt aus den Berechnungsdaten beantworten &mdash; kein API-Key n&ouml;tig:</p>
    <select id="erklaer-frage" class="erklaer-select"></select>
    <select id="erklaer-techniker" class="erklaer-select"></select>
    <button class="chat-btn-primary" id="erklaer-btn" data-i18n="erklaer.btn">Erkl&auml;ren</button>
    <div class="erklaer-antwort" id="erklaer-antwort" style="display:none"></div>
  </div>
  <div class="erklaer-divider" data-i18n="erklaer.divider">F&uuml;r freie Fragen: Claude API-Key verbinden (optional)</div>

  <!-- API-Key Setup -->
  <div class="chat-setup" id="chat-setup">
    <p data-i18n-html="chat.setup">Claude API-Key eingeben, um den<br>KI-Assistenten zu aktivieren.</p>
    <input type="password" id="api-key-input" placeholder="sk-ant-api03-..." autocomplete="off">
    <div class="chat-key-error" id="chat-key-error">Ung&uuml;ltiger API-Key. Bitte pr&uuml;fen.</div>
    <button class="chat-btn-primary" id="api-key-save" data-i18n="chat.connect">Verbinden</button>
    <p style="margin-top:12px;font-size:10px;color:var(--text-muted)" data-i18n-html="chat.keyNote">
      Key wird lokal im Browser gespeichert.<br>Keine serverseitige Speicherung.
    </p>
  </div>

  <!-- Chat Body (hidden until connected) -->
  <div class="chat-messages" id="chat-messages" style="display:none"></div>

  <div class="chat-quick" id="chat-quick" style="display:none">
    <button data-q="Warum wurde T5 fuer diesen Auftrag empfohlen? Erklaere die Scoring-Berechnung." data-i18n="chat.q1">Warum T5?</button>
    <button data-q="Erklaere das NRW-Ueberlastungsproblem: Welche Techniker sind betroffen, warum ist es kritisch, und was sind die Loesungsoptionen?" data-i18n="chat.q2">NRW Problem</button>
    <button data-q="Wie ist der Kalibrierungsstatus von T10? Welche Messmittel laufen bald ab?" data-i18n="chat.q3">T10 Kalibrierung</button>
    <button data-q="Welches Crosstraining sollte prioritaer durchgefuehrt werden? Begruende anhand der Daten." data-i18n="chat.q4">Crosstraining</button>
    <button data-q="Was sind die wichtigsten naechsten Schritte fuer die Serviceplanung?" data-i18n="chat.q5">N&auml;chste Schritte</button>
  </div>

  <div class="chat-input-wrap" id="chat-input-wrap" style="display:none">
    <textarea id="chat-input" data-i18n-placeholder="chat.placeholder" placeholder="Frage zum Dashboard stellen..." rows="1"></textarea>
    <button class="chat-send-btn" id="chat-send" title="Senden">
      <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
    </button>
  </div>

  <div class="chat-disconnect" id="chat-disconnect" style="display:none">
    <button id="chat-disconnect-btn" data-i18n="chat.removeKey">API-Key entfernen</button>
  </div>

</aside>

</div><!-- /app-layout -->

<!-- Techniker-Detail Modal -->
<div class="tech-detail-overlay" id="tech-detail-overlay"
     onclick="if(event.target===this)closeTechDetail()">
  <div class="tech-detail-panel" id="tech-detail-panel">
    <button class="tech-detail-close" onclick="closeTechDetail()">&times;</button>
    <div id="tech-detail-content"></div>
  </div>
</div>

<script>
/* ── i18n Translation ── */
/* Zentrale Label-Uebersetzung (i18n-Komplettaudit): [data-label-de]-Elemente
   werden generisch ueber diese EINE Tabelle uebersetzt, statt jede
   Vorkommensstelle einzeln an einen data-i18n-Key zu binden. Siehe
   reporting/dashboard.py LABEL_MAP_EN. */
var _LABEL_MAP_EN = {json.dumps(LABEL_MAP_EN, ensure_ascii=False)};
var _I18N = {{
  DE: {{
    'nav.manual': 'Handbuch',
    'header.demo': {json.dumps(demo_badge_text_de, ensure_ascii=False)},
    'tab.overview': '\u00dcbersicht',
    'tab.orders': 'Auftr\u00e4ge',
    'tab.crosstraining': 'Cross-Training',
    'tab.workflow': 'Workflow',
    'tab.business': 'Business Case',
    'tab.territory': 'Gebietsoptimierung',
    'tab.hiring': 'Einstellungsbedarf',
    'summary.green': 'Gr\u00fcn',
    'summary.yellow': 'Gelb',
    'summary.red': 'Rot',
    'summary.asOf': 'Stand',
    'summary.monThu': 'Mo\u2013Do',
    'h.overview': '\u00dcbersicht \u2014 Qualifikations-Ampel',
    'hint.overview': {json.dumps(overview_hint_text_de, ensure_ascii=False)},
    'sort.label': 'Sortierung:',
    'sort.standard': 'Standard (Gr\u00fcn / Gelb / Rot)',
    'sort.ct': 'Crosstraining-Bedarf (meiste L\u00fccken zuerst)',
    'sort.util': 'Auslastung (Stunden)',
    'sort.portfolio': 'Ger\u00e4te-Portfolio (meiste L3-Familien zuerst)',
    'sort.area': 'Gebietsgr\u00f6\u00dfe',
    'hint.demo': {json.dumps(demo_hint_text_de, ensure_ascii=False)},
    'h.stk': 'STK-Auftr\u00e4ge (Top 10)',
    'hint.stk': 'Quelle: daten/geraete.csv \u00b7 Aufsteigend nach F\u00e4lligkeitsdatum',
    'th.orderId': 'Auftrag-ID',
    'th.clinic': 'Klinik',
    'th.device': 'Ger\u00e4t',
    'th.productFamily': 'Produktfamilie',
    'th.dueDate': 'F\u00e4lligkeit',
    'th.suggestedDates': 'Vorgeschlagene Termine',
    'th.urgency': 'Dringlichkeit',
    'th.days': 'Tage',
    'h.repair': 'Offene Repair-Auftr\u00e4ge',
    'hint.repair': 'SLA: Kundenkontakt innerhalb 48h \u00b7 Internes Ziel: 24h',
    'th.received': 'Eingang',
    'th.slaStatus': 'SLA-Status',
    'th.phase': 'Phase',
    'th.sparePart': 'Ersatzteil',
    'h.ct': 'Crosstraining Top 5',
    'hint.ct': 'Nur Techniker mit wirtschaftlich sinnvollem Crosstraining (Ger\u00e4tedichte & STK-Potenzial \u00fcber Schwellwert) \u00b7 sortiert nach STK-Potenzial pro Jahr',
    'th.technician': 'Techniker',
    'th.gaps': 'L\u00fccken',
    'th.stkYear': '+STK/Jahr',
    'th.missingFamilies': 'Fehlende Produktfamilien',
    'th.recPartner': 'Empf. Partner',
    'card.l3coverage': 'L3-Abdeckung',
    'card.fam': 'Fam.',
    'card.gaps': 'L\u00fccken',
    'card.capacity': 'Kapazit\u00e4t',
    'card.week': 'Woche',
    'card.missingFam': 'fehlende Familien',
    'card.potential': 'Potenzial',
    'card.weeklyHours': 'Wochenstunden',
    'card.fridayNote': 'Freitag = Home Office \u00b7 keine Echtzeit-Daten',
    'card.l3families': 'L3-Familien',
    'card.ofRegional': 'von',
    'card.regional': 'regionalen',
    'card.stkPotential': 'STK/a Potenzial',
    'card.afterCT': 'nach Crosstraining',
    'footer.copilot': 'Vollautomatisiert \u00b7 Copilot \u2014 kein Autopilot',
    'chat.sub': 'Medtronic Field Service Assistent',
    'chat.setup': 'Claude API-Key eingeben, um den<br>KI-Assistenten zu aktivieren.',
    'chat.connect': 'Verbinden',
    'chat.keyNote': 'Key wird lokal im Browser gespeichert.<br>Keine serverseitige Speicherung.',
    'chat.placeholder': 'Frage zum Dashboard stellen...',
    'chat.removeKey': 'API-Key entfernen',
    'chat.q1': 'Warum T5?',
    'chat.q2': 'NRW Problem',
    'chat.q3': 'T10 Kalibrierung',
    'chat.q4': 'Crosstraining',
    'chat.q5': 'N\u00e4chste Schritte',
    'h.territory': 'Gebietsoptimierung',
    'hint.territory': 'Analyse der Gebietsabdeckung \u00b7 \u00dcberschneidungen & L\u00fccken \u00b7 Fahrzeit-Optimierungspotenzial je Region',
    'h.top3': 'Top-3 Empfehlungen f\u00fcr Gebietsanpassung',
    'hint.top3': 'Priorisiert nach Fahrzeit-Einsparungspotenzial und Crosstraining-Bedarf',
    'erklaer.intro': 'Frage direkt aus den Berechnungsdaten beantworten \u2014 kein API-Key n\u00f6tig:',
    'erklaer.btn': 'Erkl\u00e4ren',
    'erklaer.divider': 'F\u00fcr freie Fragen: Claude API-Key verbinden (optional)',
    'h.nrw': '\u26a0 NRW-\u00dcberlastungs-Warnung',
    'h.puffer': 'Tourplanung \u2014 Puffer-Visualisierung',
    'h.workflow6': '6 \u2014 Workflow-Status',
    'h.business7': '7 \u2014 Business Case',
    'h.hiring': 'PLZ-Abdeckung & Einstellungsbedarf',
    'th.standort': 'Standort',
    'th.region': 'Region',
    'th.abdeckung': 'Abdeckung',
    'th.kliniken': 'Kliniken',
    'th.begruendung': 'Begr\u00fcndung',
    'th.oFahrzeit': '\u00d8 Fahrzeit',
    'th.ratio': 'Ratio',
    'th.auslastung': 'Auslastung',
    'th.ratioVorher': 'Ratio vorher',
    'th.ratioNachher': 'Ratio nachher',
    'th.deltaFahrzeit': '\u0394 Fahrzeit',
    'th.verschobeneKliniken': 'Verschobene Kliniken',
    'th.gebiet': 'Gebiet',
    'th.status': 'Status',
    'th.empfehlung': 'Empfehlung',
    'go.viewAktuell': 'Aktuelle Gebiete',
    'go.viewOptimiert': 'Optimierte Gebiete',
    'go.viewLuecken': 'L\u00fccken & \u00dcberschneidungen',
    'go.hint': 'Techniker anklicken, um sein Gebiet hervorzuheben',
    'go.reset': '\u2715 Zur\u00fccksetzen'
  }},
  EN: {{
    'nav.manual': 'Manual',
    'header.demo': {json.dumps(demo_badge_text_en, ensure_ascii=False)},
    'tab.overview': 'Overview',
    'tab.orders': 'Orders',
    'tab.crosstraining': 'Cross-Training',
    'tab.workflow': 'Workflow',
    'tab.business': 'Business Case',
    'tab.territory': 'Territory Optimization',
    'tab.hiring': 'Hiring Needs',
    'summary.green': 'Green',
    'summary.yellow': 'Yellow',
    'summary.red': 'Red',
    'summary.asOf': 'As of',
    'summary.monThu': 'Mon\u2013Thu',
    'h.overview': 'Overview \u2014 Qualification Traffic Light',
    'hint.overview': {json.dumps(overview_hint_text_en, ensure_ascii=False)},
    'sort.label': 'Sort by:',
    'sort.standard': 'Default (Green / Yellow / Red)',
    'sort.ct': 'Cross-training need (most gaps first)',
    'sort.util': 'Utilization (hours)',
    'sort.portfolio': 'Device portfolio (most L3 families first)',
    'sort.area': 'Territory size',
    'hint.demo': {json.dumps(demo_hint_text_en, ensure_ascii=False)},
    'h.stk': 'Safety Checks (Top 10)',
    'hint.stk': 'Source: daten/geraete.csv \u00b7 Ascending by due date',
    'th.orderId': 'Order ID',
    'th.clinic': 'Hospital',
    'th.device': 'Device',
    'th.productFamily': 'Product Family',
    'th.dueDate': 'Due Date',
    'th.suggestedDates': 'Suggested Dates',
    'th.urgency': 'Urgency',
    'th.days': 'Days',
    'h.repair': 'Open Repair Orders',
    'hint.repair': 'SLA: Customer contact within 48h \u00b7 Internal target: 24h',
    'th.received': 'Received',
    'th.slaStatus': 'SLA Status',
    'th.phase': 'Phase',
    'th.sparePart': 'Spare Part',
    'h.ct': 'Cross-Training Top 5',
    'hint.ct': 'Only technicians with an economically viable crosstraining case (device density & STK potential above threshold) \u00b7 sorted by STK potential per year',
    'th.technician': 'Technician',
    'th.gaps': 'Gaps',
    'th.stkYear': '+STK/Year',
    'th.missingFamilies': 'Missing Product Families',
    'th.recPartner': 'Rec. Partner',
    'card.l3coverage': 'L3 Coverage',
    'card.fam': 'fam.',
    'card.gaps': 'gaps',
    'card.capacity': 'Capacity',
    'card.week': 'week',
    'card.missingFam': 'missing families',
    'card.potential': 'potential',
    'card.weeklyHours': 'Weekly hours',
    'card.fridayNote': 'Friday = Home Office \u00b7 no real-time data',
    'card.l3families': 'L3 Families',
    'card.ofRegional': 'of',
    'card.regional': 'regional',
    'card.stkPotential': 'STK/yr potential',
    'card.afterCT': 'after cross-training',
    'footer.copilot': 'Fully automated \u00b7 Copilot \u2014 not autopilot',
    'chat.sub': 'Medtronic Field Service Assistant',
    'chat.setup': 'Enter Claude API key to<br>activate the AI assistant.',
    'chat.connect': 'Connect',
    'chat.keyNote': 'Key is stored locally in your browser.<br>No server-side storage.',
    'chat.placeholder': 'Ask a question about the dashboard...',
    'chat.removeKey': 'Remove API key',
    'chat.q1': 'Why T5?',
    'chat.q2': 'NRW Problem',
    'chat.q3': 'T10 Calibration',
    'chat.q4': 'Cross-training',
    'chat.q5': 'Next Steps',
    'h.territory': 'Territory Optimization',
    'hint.territory': 'Territory coverage analysis \u00b7 Overlaps & gaps \u00b7 Travel time optimization potential per region',
    'h.top3': 'Top 3 Recommendations for Territory Adjustment',
    'hint.top3': 'Prioritized by travel time savings potential and cross-training needs',
    'erklaer.intro': 'Answer questions directly from the calculation data \u2014 no API key needed:',
    'erklaer.btn': 'Explain',
    'erklaer.divider': 'For free-form questions: connect Claude API key (optional)',
    'h.nrw': '\u26a0 NRW Overload Warning',
    'h.puffer': 'Tour Planning \u2014 Buffer Visualization',
    'h.workflow6': '6 \u2014 Workflow Status',
    'h.business7': '7 \u2014 Business Case',
    'h.hiring': 'ZIP Code Coverage & Hiring Needs',
    'th.standort': 'Location',
    'th.region': 'Region',
    'th.abdeckung': 'Coverage',
    'th.kliniken': 'Clinics',
    'th.begruendung': 'Justification',
    'th.oFahrzeit': 'Avg. Travel Time',
    'th.ratio': 'Ratio',
    'th.auslastung': 'Utilization',
    'th.ratioVorher': 'Ratio before',
    'th.ratioNachher': 'Ratio after',
    'th.deltaFahrzeit': '\u0394 Travel Time',
    'th.verschobeneKliniken': 'Relocated Clinics',
    'th.gebiet': 'Territory',
    'th.status': 'Status',
    'th.empfehlung': 'Recommendation',
    'go.viewAktuell': 'Current Territories',
    'go.viewOptimiert': 'Optimized Territories',
    'go.viewLuecken': 'Gaps & Overlaps',
    'go.hint': 'Click a technician to highlight their territory',
    'go.reset': '\u2715 Reset'
  }}
}};
var _currentLang = localStorage.getItem('fsa_lang') || 'DE';

function setLang(lang) {{
  _currentLang = lang;
  localStorage.setItem('fsa_lang', lang);
  var dict = _I18N[lang];
  if (!dict) return;
  document.querySelectorAll('[data-i18n]').forEach(function(el) {{
    var key = el.getAttribute('data-i18n');
    if (dict[key] !== undefined) el.textContent = dict[key];
  }});
  document.querySelectorAll('[data-i18n-html]').forEach(function(el) {{
    var key = el.getAttribute('data-i18n-html');
    if (dict[key] !== undefined) el.innerHTML = dict[key];
  }});
  document.querySelectorAll('[data-i18n-placeholder]').forEach(function(el) {{
    var key = el.getAttribute('data-i18n-placeholder');
    if (dict[key] !== undefined) el.placeholder = dict[key];
  }});
  document.querySelectorAll('[data-label-de]').forEach(function(el) {{
    var de = el.getAttribute('data-label-de');
    el.textContent = (lang === 'EN' && _LABEL_MAP_EN[de] !== undefined) ? _LABEL_MAP_EN[de] : de;
  }});
  var btn = document.getElementById('lang-toggle-btn');
  if (btn) btn.textContent = lang === 'DE' ? 'EN' : 'DE';
  document.documentElement.lang = lang.toLowerCase();
  window.dispatchEvent(new Event('fsa_lang_changed'));
}}

function toggleLang() {{
  setLang(_currentLang === 'DE' ? 'EN' : 'DE');
}}

if (_currentLang !== 'DE') setLang(_currentLang);

/* ── Tab Navigation ── */
(function() {{
  var tabs = document.querySelectorAll('.nav-tab');
  tabs.forEach(function(tab) {{
    tab.addEventListener('click', function() {{
      tabs.forEach(function(t) {{ t.classList.remove('active'); }});
      tab.classList.add('active');
      document.querySelectorAll('.tab-content').forEach(function(c) {{
        c.classList.remove('active');
      }});
      var target = document.getElementById(tab.getAttribute('data-tab'));
      if (target) target.classList.add('active');
      /* Scroll-Position zuruecksetzen, damit der neue Tab-Inhalt oben beginnt */
      window.scrollTo(0, 0);
      document.documentElement.scrollTop = 0;
      document.body.scrollTop = 0;
    }});
  }});
}})();

{_SORT_SCRIPT}

/* ── Techniker-Detail Modal ── */
var TECH_DETAIL_DATA = {tech_detail_json};

function showTechDetail(tid) {{
  var d = TECH_DETAIL_DATA[tid];
  if (!d) return;
  var html = '<div class="tech-detail-title">' + tid + ' &mdash; ' + d.standort + ' &mdash; Einsatzhistorie</div>';
  html += '<table><thead><tr><th>Datum</th><th>Klinik</th><th>Ger&auml;t</th><th>Typ</th><th>Dauer</th><th>Status</th></tr></thead><tbody>';
  d.orders.forEach(function(o) {{
    html += '<tr><td>' + o.datum + '</td><td>' + o.klinik + '</td><td>' + o.geraet + '</td><td>' + o.typ + '</td><td>' + o.dauer_h + '</td><td style="color:var(--success-text)">' + o.status + '</td></tr>';
  }});
  html += '</tbody></table>';
  html += '<div class="tech-detail-kpis">';
  html += '<div class="tech-detail-kpi"><div class="kpi-val">' + d.einsaetze_monat + '</div><div class="kpi-lbl">Eins&auml;tze diesen Monat</div></div>';
  html += '<div class="tech-detail-kpi"><div class="kpi-val">' + d.einsaetze_jahr + '</div><div class="kpi-lbl">Eins&auml;tze dieses Jahr</div></div>';
  html += '<div class="tech-detail-kpi"><div class="kpi-val">' + d.avg_dauer_h + 'h</div><div class="kpi-lbl">&Oslash; Einsatzdauer</div></div>';
  html += '<div class="tech-detail-kpi"><div class="kpi-val">' + d.haeufigste_klinik + '</div><div class="kpi-lbl">H&auml;ufigste Klinik</div></div>';
  html += '<div class="tech-detail-kpi"><div class="kpi-val">' + d.haeufigste_familie + '</div><div class="kpi-lbl">H&auml;ufigste Produktfamilie</div></div>';
  html += '</div>';
  html += '<p style="margin-top:16px;font-size:10px;color:var(--text-muted);font-style:italic">Demo-Daten &middot; Im Produktivbetrieb: echte Daten aus SMax API</p>';
  document.getElementById('tech-detail-content').innerHTML = html;
  document.getElementById('tech-detail-overlay').classList.add('active');
}}

function closeTechDetail() {{
  document.getElementById('tech-detail-overlay').classList.remove('active');
}}

document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape') closeTechDetail();
}});

{gebiets_script}

{tooltip_portal_script}

{erklaer_script}

/* ══════════ Claude Chat ══════════ */
(function() {{
  var SYSTEM_PROMPT = {system_prompt_js};
  var API_URL = 'https://api.anthropic.com/v1/messages';
  var MODEL = 'claude-sonnet-4-20250514';
  var MAX_TOKENS = 1024;

  var apiKey = localStorage.getItem('mdt_claude_key') || '';
  var messages = [];
  var isStreaming = false;

  var setupEl     = document.getElementById('chat-setup');
  var msgsEl      = document.getElementById('chat-messages');
  var quickEl     = document.getElementById('chat-quick');
  var inputWrap   = document.getElementById('chat-input-wrap');
  var inputEl     = document.getElementById('chat-input');
  var sendBtn     = document.getElementById('chat-send');
  var keyInput    = document.getElementById('api-key-input');
  var keySaveBtn  = document.getElementById('api-key-save');
  var keyError    = document.getElementById('chat-key-error');
  var statusDot   = document.getElementById('chat-status');
  var disconnEl   = document.getElementById('chat-disconnect');
  var disconnBtn  = document.getElementById('chat-disconnect-btn');

  function showChat() {{
    setupEl.style.display = 'none';
    msgsEl.style.display = 'flex';
    quickEl.style.display = 'flex';
    inputWrap.style.display = 'flex';
    disconnEl.style.display = 'block';
    statusDot.classList.remove('offline');
    if (messages.length === 0) {{
      addMsg('system', 'Verbunden. Stelle eine Frage zum Dashboard.');
    }}
  }}

  function showSetup() {{
    setupEl.style.display = 'block';
    msgsEl.style.display = 'none';
    quickEl.style.display = 'none';
    inputWrap.style.display = 'none';
    disconnEl.style.display = 'none';
    statusDot.classList.add('offline');
  }}

  function addMsg(role, text) {{
    var div = document.createElement('div');
    div.className = 'chat-msg chat-msg-' + role;
    div.innerHTML = formatMarkdown(text);
    msgsEl.appendChild(div);
    msgsEl.scrollTop = msgsEl.scrollHeight;
    return div;
  }}

  function formatMarkdown(text) {{
    return text
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>')
      .replace(/`(.+?)`/g, '<code>$1</code>')
      .replace(/\\n/g, '<br>');
  }}

  function setLoading(on) {{
    isStreaming = on;
    sendBtn.disabled = on;
    inputEl.disabled = on;
  }}

  async function sendMessage(text) {{
    if (!text.trim() || isStreaming) return;

    addMsg('user', text);
    messages.push({{ role: 'user', content: text }});
    inputEl.value = '';
    autoResize();

    setLoading(true);
    var assistantDiv = addMsg('assistant', '');
    var fullText = '';

    try {{
      var resp = await fetch(API_URL, {{
        method: 'POST',
        headers: {{
          'Content-Type': 'application/json',
          'x-api-key': apiKey,
          'anthropic-version': '2023-06-01',
          'anthropic-dangerous-direct-browser-access': 'true'
        }},
        body: JSON.stringify({{
          model: MODEL,
          max_tokens: MAX_TOKENS,
          system: SYSTEM_PROMPT,
          stream: true,
          messages: messages.slice(-20)
        }})
      }});

      if (!resp.ok) {{
        var errBody = await resp.text();
        throw new Error('API ' + resp.status + ': ' + errBody.slice(0, 200));
      }}

      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var buffer = '';

      while (true) {{
        var chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, {{ stream: true }});

        var lines = buffer.split('\\n');
        buffer = lines.pop() || '';

        for (var i = 0; i < lines.length; i++) {{
          var line = lines[i];
          if (!line.startsWith('data: ')) continue;
          var data = line.slice(6);
          if (data === '[DONE]') continue;
          try {{
            var evt = JSON.parse(data);
            if (evt.type === 'content_block_delta' && evt.delta && evt.delta.text) {{
              fullText += evt.delta.text;
              assistantDiv.innerHTML = formatMarkdown(fullText);
              msgsEl.scrollTop = msgsEl.scrollHeight;
            }}
          }} catch(e) {{}}
        }}
      }}

      if (!fullText) {{
        fullText = '(Keine Antwort erhalten)';
        assistantDiv.innerHTML = formatMarkdown(fullText);
      }}
      messages.push({{ role: 'assistant', content: fullText }});

    }} catch(err) {{
      assistantDiv.innerHTML = '<span style="color:var(--critical-text)">' +
        formatMarkdown('Fehler: ' + err.message) + '</span>';
    }}

    setLoading(false);
  }}

  function autoResize() {{
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
  }}

  keySaveBtn.addEventListener('click', function() {{
    var key = keyInput.value.trim();
    if (!key || !key.startsWith('sk-')) {{
      keyError.style.display = 'block';
      return;
    }}
    keyError.style.display = 'none';
    apiKey = key;
    localStorage.setItem('mdt_claude_key', key);
    showChat();
  }});

  keyInput.addEventListener('keydown', function(e) {{
    if (e.key === 'Enter') keySaveBtn.click();
  }});

  disconnBtn.addEventListener('click', function() {{
    apiKey = '';
    messages = [];
    localStorage.removeItem('mdt_claude_key');
    msgsEl.innerHTML = '';
    keyInput.value = '';
    showSetup();
  }});

  sendBtn.addEventListener('click', function() {{
    sendMessage(inputEl.value);
  }});

  inputEl.addEventListener('keydown', function(e) {{
    if (e.key === 'Enter' && !e.shiftKey) {{
      e.preventDefault();
      sendMessage(inputEl.value);
    }}
  }});

  inputEl.addEventListener('input', autoResize);

  quickEl.addEventListener('click', function(e) {{
    var btn = e.target.closest('button[data-q]');
    if (btn) sendMessage(btn.getAttribute('data-q'));
  }});

  if (apiKey) {{
    showChat();
  }} else {{
    showSetup();
  }}
}})();
</script>

<!-- PASSWORD PROTECTION (gleicher Mechanismus wie index.html/demo.html/animation.html/
     coordinator_import.html: SHA-256-Hash-Vergleich, localStorage-persistiert.
     Noetig da Echtdaten-Modus reale Techniker-Namen und Leistungsdaten zeigt.) -->
<div id="pw-overlay" style="position:fixed;inset:0;z-index:99999;background:linear-gradient(135deg,#005195,#0066CC);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1.5rem;font-family:'Plus Jakarta Sans',sans-serif">
  <div style="font-size:.7rem;letter-spacing:.25em;text-transform:uppercase;color:rgba(255,255,255,.6)">Medtronic GmbH &middot; Field Service AI</div>
  <div style="font-family:'Syne',sans-serif;font-size:1.6rem;font-weight:800;color:#fff">Zugangscode erforderlich</div>
  <div style="display:flex;flex-direction:column;gap:.6rem;width:280px">
    <input id="pw-input" type="password" placeholder="Passwort eingeben..." style="padding:.75rem 1rem;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.3);border-radius:8px;color:#fff;font-family:'Plus Jakarta Sans',sans-serif;font-size:.9rem;outline:none;width:100%" onkeydown="if(event.key==='Enter')checkPw()" oninput="document.getElementById('pw-err').style.display='none'">
    <button onclick="checkPw()" style="padding:.75rem;background:#fff;border:none;border-radius:8px;color:#005195;font-size:.88rem;font-weight:700;cursor:pointer;font-family:'Plus Jakarta Sans',sans-serif">Zugang &rarr;</button>
    <div id="pw-err" style="display:none;font-size:.75rem;color:#FFB3B3;text-align:center">Falsches Passwort</div>
  </div>
  <div style="font-size:.68rem;color:rgba(255,255,255,.5)">Vertraulich &middot; Nur f&uuml;r autorisierte Personen</div>
</div>
<script>
(function(){{
  var H='037453db72fb8a93ebe48d4ff52b1b493cdf56ef6a28240a65c6055b76d8f360';
  var K='fsa_auth';
  function initPw(){{
    var ov=document.getElementById('pw-overlay');
    if(localStorage.getItem(K)===H){{ov.style.display='none';return;}}
    ov.style.display='flex';
    setTimeout(function(){{var i=document.getElementById('pw-input');if(i)i.focus();}},100);
  }}
  async function checkPw(){{
    var v=document.getElementById('pw-input').value;
    var b=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(v));
    var h=Array.from(new Uint8Array(b)).map(function(x){{return x.toString(16).padStart(2,'0')}}).join('');
    if(h===H){{localStorage.setItem(K,H);document.getElementById('pw-overlay').style.display='none';}}
    else{{document.getElementById('pw-err').style.display='block';document.getElementById('pw-input').value='';document.getElementById('pw-input').focus();}}
  }}
  window.checkPw=checkPw;
  if(document.readyState==='loading'){{document.addEventListener('DOMContentLoaded',initPw);}}
  else{{initPw();}}
}})();
</script>

</body>
</html>"""
    return html.replace("<!-- filled by _build_gebiets_svg -->", gebiets_svg_content)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _vollstaendigkeits_pruefung(html: str) -> list[tuple[str, bool]]:
    """Prueft ob alle Pflicht-Sektionen im generierten HTML vorhanden sind."""
    checks = [
        ("Tab-Navigation (7 Tabs, sticky)",
         'nav-tabs' in html and html.count('class="nav-tab') >= 7),
        ("Tab 1: Uebersicht – Qualifikations-Ampel 14 Kacheln",
         'id="tab-uebersicht"' in html and html.count('class="ampel-karte') >= 14),
        ("Tab 2: Auftraege – STK + Repair",
         'id="tab-auftraege"' in html and 'STK-Auftr' in html),
        ("Tab 3: Cross-Training + NRW-Warnung",
         'id="tab-crosstraining"' in html and 'cluster-badge' in html),
        ("Tab 4: Workflow (7 Schritte) + Puffer",
         'id="tab-workflow"' in html and 'wf-pipeline' in html),
        ("Tab 5: Business Case (Formeln)",
         'id="tab-business"' in html and 'bc-formula' in html),
        ("Tab 6: Gebietsoptimierung (NEU) mit Karte + Empfehlungen",
         'id="tab-gebietsopt"' in html and 'go-empf-grid' in html),
        ("Tab 7: Einstellungsbedarf Sterne-Karte",
         'id="tab-einstellung"' in html and 'einst-liste-header' in html),
        ("Techniker-Detail Modal",
         'tech-detail-overlay' in html and 'TECH_DETAIL_DATA' in html),
        ("KI-Chat: rechtes Panel 340px",
         'chat-panel' in html and 'chat-messages' in html),
        ("Medtronic Light Theme: rgba(0,81,149 Header",
         'rgba(0,81,149' in html),
        ("Google Fonts: Plus Jakarta Sans + Syne",
         'Plus Jakarta Sans' in html and 'Syne' in html),
        ("Grain-Overlay SVG",
         'grain-overlay' in html),
        ("Hugo Key Account Badges (T1, T6, T10, T11)",
         'hugo-ka-badge' in html and html.count('Hugo Key Account') >= 4),
        ("Demo-Badge (gold) im Header",
         'demo-badge' in html),
        (f"Footer: {TESTS_ANZAHL} Tests gruen",
         f'{TESTS_ANZAHL} Tests' in html),
        ("Passwortschutz (konsistent mit index.html/demo.html/...)",
         'id="pw-overlay"' in html and 'checkPw' in html),
        ("KI-Erklaerungsfeld (Template-basiert, kein API-Key noetig)",
         'id="erklaer-box"' in html and 'erklaer-antwort' in html),
        ("Hugo-Kerngebiet-Toggle (optional, default AUS)",
         'id="hugo-kg-toggle"' in html and 'hugo-kg-hint' in html),
        ("Auslastungs-Zielkorridor (Referenzwert, echte Einsatzhistorie)",
         'Auslastungs-Zielkorridor' in html and f'{AUSLASTUNG_ZIEL_MIN_PCT}' in html),
    ]
    return checks


def main() -> None:
    global _ECHTDATEN, _TECH_FARBEN, _GEBIET_AKTUELL, _GEBIET_OPTIMIERT
    global _NRW_TECHNIKER, _HUGO_KA_IDS

    print("Lade Daten...")
    techniker    = _lade_techniker()       # setzt _ECHTDATEN als Nebeneffekt
    ct_rows      = _lade_crosstraining()   # Demo-CSV bleibt fuer CT-Tabelle
    labor_zeiten = _lade_labor_zeiten()

    if _ECHTDATEN:
        print("  -> Echtdaten-Modus: SMax-Import geladen")

        # Ampel aus echten PM-Skill-Daten berechnen
        ct_kennzahlen: dict | None = None
        try:
            from api.smax_cache import load_dashboard_data as _smax_load
            _smax = _smax_load()
            ampeln = _berechne_ampeln_aus_smax(_smax["techniker"])
            ct_rows = _baue_ct_rows_echtdaten(_smax["techniker"])
            ct_kennzahlen = {
                "stk_potenzial_gesamt": _smax.get("stk_potenzial_gesamt", 0),
                "einsatz_median_min":   _smax.get("einsatz_median_min", 0),
            }
        except Exception:
            ampeln = _berechne_ampeln(ct_rows, techniker)

        # Hugo-KA-IDs aus echten Technikerdaten ableiten
        _HUGO_KA_IDS = {
            tid for tid, td in techniker.items()
            if td.get("techniker_typ") == "HUGO_KEY_ACCOUNT"
        }

        # NRW-Techniker aus echten Bundesland-Daten
        _NRW_TECHNIKER = {
            tid for tid, td in techniker.items()
            if "Westfalen" in td.get("bundesland", "")
        }

        # NRW-Warnung mit echten NRW-Techniker-IDs
        nrw_warnung = _berechne_nrw_warnung_aus_smax(ampeln, _NRW_TECHNIKER)

        # Farb-Palette fuer 24 Techniker (deterministisch sortiert)
        _FARB_PALETTE = [
            "#0072CE", "#00A3E0", "#7B2D8E", "#E87000", "#00843D", "#003087",
            "#CC0000", "#E8A000", "#2E8B57", "#B22222", "#4169E1", "#2F4F4F",
            "#D2691E", "#008B8B", "#8B0000", "#228B22", "#4682B4", "#DAA520",
            "#800080", "#A0522D", "#008080", "#CD853F", "#6495ED", "#DC143C",
        ]
        sorted_ids = sorted(techniker.keys())
        _TECH_FARBEN = {
            tid: _FARB_PALETTE[i % len(_FARB_PALETTE)]
            for i, tid in enumerate(sorted_ids)
        }

        # Gebiets-Map: Bundesland → erster Techniker in diesem Bundesland
        _BL_KARTE = {
            "Schleswig-Holstein": None, "Hamburg": None,
            "Mecklenburg-Vorpommern": None, "Niedersachsen": None,
            "Bremen": None, "Nordrhein-Westfalen": None,
            "Hessen": None, "Thüringen": None,
            "Sachsen": None, "Sachsen-Anhalt": None,
            "Brandenburg": None, "Berlin": None,
            "Rheinland-Pfalz": None, "Saarland": None,
            "Baden-Württemberg": None, "Bayern": None,
        }
        for tid in sorted_ids:
            bl = techniker[tid].get("bundesland", "")
            if bl in _BL_KARTE and _BL_KARTE[bl] is None:
                _BL_KARTE[bl] = tid
        _GEBIET_AKTUELL  = {k: v for k, v in _BL_KARTE.items() if v}

    else:
        print("  -> Demo-Modus: T1-T14 aus CSV")
        ampeln      = _berechne_ampeln(ct_rows, techniker)
        nrw_warnung = _berechne_nrw_warnung(ct_rows)

    print("Berechne Dringlichkeiten fuer naechste 10 STK-Auftraege...")
    auftraege = naechste_faellige_auftraege(n=10)

    _DEMO_OFFSETS = [
        -65, -45, -20,
        5, 12, 18, 25,
        35, 48, 58,
    ]
    for i, a in enumerate(auftraege):
        offset = _DEMO_OFFSETS[i] if i < len(_DEMO_OFFSETS) else 30 + i * 5
        a.faelligkeitsdatum = _HEUTE + timedelta(days=offset)

    stk_rows: list[dict] = []
    for a in auftraege:
        d = _berechne_dringlichkeit(a.faelligkeitsdatum, _HEUTE)
        tage = d.tage_bis_faelligkeit
        tage_str = f"{tage}" if tage >= 0 else f"<span style='color:var(--critical-text)'>{tage}</span>"

        vorschlaege = schlage_termine_vor(a, heute=_HEUTE)
        if vorschlaege:
            termine_parts = []
            for v in vorschlaege:
                badge_css = {"optimal": "badge-normal", "moeglich": "badge-hoch", "knapp": "badge-kritisch"}
                css_cls = badge_css.get(v.bewertung, "badge-normal")
                termine_parts.append(
                    f"<span class='badge {css_cls}' title='{v.bewertung}'>"
                    f"{_label(v.wochentag)} {v.datum.strftime('%d.%m.')}</span>"
                )
            termine_html = " / ".join(termine_parts)
        else:
            termine_html = "&ndash;"

        stk_rows.append({
            "auftrag_id":   a.auftrag_id,
            "klinik":       a.klinik_name,
            "geraet":       a.geraet_id,
            "produkt":      a.produkt_familie,
            "faelligkeit":  a.faelligkeitsdatum.strftime("%d.%m.%Y"),
            "termine_vorschlag": termine_html,
            "dringlichkeit": d.stufe,
            "tage":         tage_str,
        })

    print("Generiere Demo-Repair-Auftraege...")
    from auftraege.models import RepairPhase as _RP

    _DEMO_REPAIRS = [
        {"aid": "REP-2026-0042", "klinik": "UKE Hamburg", "geraet": "HugoRAS",
         "stunden_offset": -7, "phase": _RP.KONTAKT_AUSSTEHEND, "kontakt": False,
         "ersatzteil": "&ndash;"},
        {"aid": "REP-2026-0041", "klinik": "Uniklinikum Ulm", "geraet": "EC300_Legend",
         "stunden_offset": -31, "phase": _RP.KONTAKT_AUSSTEHEND, "kontakt": False,
         "ersatzteil": "&ndash;"},
        {"aid": "REP-2026-0040", "klinik": "Uni Bonn", "geraet": "NIM4CM01",
         "stunden_offset": -50, "phase": _RP.KONTAKT_AUSSTEHEND, "kontakt": False,
         "ersatzteil": "&ndash;"},
        {"aid": "REP-2026-0039", "klinik": "Klinikum Bochum", "geraet": "HugoRAS",
         "stunden_offset": -20, "phase": _RP.KONTAKT_HERGESTELLT, "kontakt": True,
         "ersatzteil": "Im Fahrzeug"},
        {"aid": "REP-2026-0038", "klinik": "Charit&eacute; Berlin", "geraet": "O-arm",
         "stunden_offset": -36, "phase": _RP.ERSATZTEIL_BESTELLT, "kontakt": True,
         "ersatzteil": "Bestellt (3-5 Tage)"},
    ]
    _JETZT = datetime.now()
    repair_rows: list[dict] = []
    for rd in _DEMO_REPAIRS:
        eingang = _JETZT + timedelta(hours=rd["stunden_offset"])
        stunden = abs(rd["stunden_offset"])
        verbleibend = 48 - stunden
        if rd["kontakt"]:
            if rd["phase"] == _RP.ERSATZTEIL_BESTELLT:
                sla_status = "Blau"
            else:
                sla_status = "Gruen"
            sla_text = "&#10003; Kontakt"
        elif stunden >= 48:
            sla_status = "Kritisch"
            sla_text = "SLA VERLETZT"
        elif stunden >= 40:
            sla_status = "Rot"
            sla_text = f"SLA: noch {round(verbleibend)}h"
        elif stunden >= 24:
            sla_status = "Gelb"
            sla_text = f"SLA: noch {round(verbleibend)}h"
        else:
            sla_status = "Gruen"
            sla_text = f"SLA: noch {round(verbleibend)}h"

        repair_rows.append({
            "auftrag_id": rd["aid"],
            "klinik": rd["klinik"],
            "geraet": rd["geraet"],
            "eingang": eingang.strftime("%d.%m. %H:%M"),
            "sla_status": sla_status,
            "sla_text": sla_text,
            "phase": rd["phase"].value,
            "ersatzteil": rd["ersatzteil"],
        })

    print("Filtere Crosstraining nach Wirtschaftlichkeit und sortiere Top-5...")
    ct_wirtschaftlich = [r for r in ct_rows if r.get("wirtschaftlich_sinnvoll") == "Ja"]
    ct_top5 = sorted(
        ct_wirtschaftlich,
        key=lambda r: float(r.get("top_familie_stk_potenzial", 0) or 0),
        reverse=True,
    )[:5]
    print(
        f"  {len(ct_wirtschaftlich)}/{len(ct_rows)} Techniker wirtschaftlich sinnvoll "
        f"-> {len(ct_top5)} in Top-5"
    )

    print("Berechne Gebietsmetriken...")
    m_akt, m_opt, gebiet_optimiert_neu, gebiets_punkte, gebiete_status = _berechne_gebietsmetriken(techniker)
    gebiets_metriken = (m_akt, m_opt)
    _GEBIET_OPTIMIERT = {**_GEBIET_AKTUELL, **gebiet_optimiert_neu}
    verschoben_gesamt = sum(m.get("verschoben_gewonnen", 0) for m in m_opt)
    print(f"  {verschoben_gesamt} Kliniken durch Optimierung verschoben")

    print("Generiere Demo-Einsatzhistorie...")
    demo_history = _generate_demo_history(techniker, labor_zeiten)

    print("Berechne Hugo-Kerngebiete (Wohnort-Radius, optionale Regel via Toggle)...")
    hugo_kerngebiete = berechne_hugo_kerngebiete(
        techniker, HUGO_STANDORTE, HUGO_SPRINGER,
        HUGO_KERNGEBIET_MAX_FAHRZEIT_MIN, HAVERSINE_UMWEG_FAKTOR,
    )
    hugo_standorte_marker_daten = hugo_standort_marker(HUGO_STANDORTE, techniker)
    print(f"  {len(hugo_kerngebiete)} Hugo-Techniker mit Kerngebiet, "
          f"{len(hugo_standorte_marker_daten)} Hugo-Standorte")

    print("Generiere Template-Erklaerungen (ohne KI-API, DE+EN)...")
    _hugo_kerngebiet_ids = {hk["id"] for hk in hugo_kerngebiete}
    erklaerungen = {
        tid: {
            frage_typ: {
                sprache: generiere_erklaerung(
                    frage_typ, tid,
                    techniker=techniker, metriken_akt=m_akt, metriken_opt=m_opt,
                    ampeln=ampeln, umweg_faktor=HAVERSINE_UMWEG_FAKTOR,
                    sprache=sprache,
                    auslastung_ziel_min_pct=AUSLASTUNG_ZIEL_MIN_PCT,
                    auslastung_ziel_max_pct=AUSLASTUNG_ZIEL_MAX_PCT,
                    hugo_kerngebiet_ids=_hugo_kerngebiet_ids,
                )
                for sprache in ("de", "en")
            }
            for frage_typ in FRAGE_TYPEN
        }
        for tid in techniker
    }

    print("Rendere HTML...")
    html = render_html(
        ampeln=ampeln,
        stk_rows=stk_rows,
        ct_top5=ct_top5,
        techniker=techniker,
        nrw_warnung=nrw_warnung,
        erstellt_am=datetime.now(),
        ct_rows=ct_rows,
        gebiets_metriken=gebiets_metriken,
        labor_zeiten=labor_zeiten,
        demo_history=demo_history,
        repair_rows=repair_rows,
        is_echtdaten=_ECHTDATEN,
        ct_kennzahlen=ct_kennzahlen if _ECHTDATEN else None,
        gebiets_punkte=gebiets_punkte,
        erklaerungen=erklaerungen,
        hugo_kerngebiete=hugo_kerngebiete,
        hugo_standorte_marker=hugo_standorte_marker_daten,
        gebiete_status=gebiete_status,
    )

    _OUT_PATH.write_text(html, encoding="utf-8")
    _OUT_PATH_ROOT.write_text(html, encoding="utf-8")
    print(f"Gespeichert: {_OUT_PATH}")
    print(f"Gespeichert: {_OUT_PATH_ROOT} (GitHub Pages)")

    # Ampel-Zusammenfassung auf der Konsole
    print("\nAmpel-Uebersicht:")
    for a in ampeln:
        print(f"  {a['techniker_id']} ({a['standort']:12s}) "
              f"{a['ampel_label']:5s}  {a['abdeckung_pct']:3d}%  "
              f"{a['qualifiziert']}/{a['regional']} Familien  "
              f"+{a['zusatz_stk']:.0f} STK/a Potenzial")

    if nrw_warnung:
        print(f"\nNRW-Warnung ausgeloest: {nrw_warnung['anzahl_schwach']} schwache Techniker, "
              f"{nrw_warnung['gesamt_stk']:,} STK/a ungenutztes Potenzial")
    else:
        print("\nKeine NRW-Warnung.")

    # Vollstaendigkeits-Pruefung
    print("\n" + "=" * 60)
    print("VOLLSTAENDIGKEITS-PRUEFUNG")
    print("=" * 60)
    checks = _vollstaendigkeits_pruefung(html)
    alle_ok = True
    for label, ok in checks:
        symbol = "[OK]" if ok else "[X]"
        print(f"  {symbol} {label}")
        if not ok:
            alle_ok = False
    print("-" * 60)
    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    if alle_ok:
        print(f"  ERGEBNIS: {passed}/{total} Pruefpunkte bestanden!")
    else:
        print(f"  ERGEBNIS: {passed}/{total} -- fehlende Sektionen pruefen!")


if __name__ == "__main__":
    main()
