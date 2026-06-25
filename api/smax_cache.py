"""
api/smax_cache.py
==================
Liest KI_gestuetzte_Planung.xlsx und erstellt Dashboard-Daten.
Speichert unter data/smax_dashboard_data.json fuer offline-Nutzung durch dashboard.py.

Pseudonymisierung (steuerbar via config.PSEUDONYMISIERUNG_AKTIV):
  True  → SHA256(name)[:4] als "T-xxxx"  (stabil, deterministisch)
  False → Echter Nachname (letztes Wort im vollstaendigen Namen)
Hugo-KA: wird per Stadtname ermittelt (4 Standorte, manuelle Pflege)
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import PSEUDONYMISIERUNG_AKTIV

_ROOT         = Path(__file__).resolve().parent.parent
_XLSX         = _ROOT / "data" / "KI_gestuetzte_Planung.xlsx"
_CACHE        = _ROOT / "data" / "smax_dashboard_data.json"
_KORREKTUREN  = _ROOT / "data" / "skill_korrekturen.json"

# Crosstraining: Umkreis-Berechnung
_CT_RADIUS_KM     = 150.0   # Straßenkilometer-Radius
_CT_ROAD_FAKTOR   = 1.35    # Luftlinie → Fahrtstrecke (aus config.HAVERSINE_UMWEG_FAKTOR)
_CT_LUFTLINIE_KM  = _CT_RADIUS_KM / _CT_ROAD_FAKTOR  # ≈ 111.1 km Luftlinie

# ── Hugo-KA-Städte ────────────────────────────────────────────────────────────
_HUGO_KA_STAEDTE: frozenset[str] = frozenset({
    "obertshausen",  # T1-Äquivalent
    "schenefeld",    # T6-Äquivalent
    "balingen",      # T10 = Marc Liebhardt
    "gangelt",       # T11-Äquivalent
})

# ── Koordinaten (lowercase-Keys für case-insensitives Lookup) ─────────────────
_STADT_COORDS: dict[str, tuple[float, float]] = {
    "obertshausen":      (50.0706,  8.8614),
    "neubiberg":         (48.0700, 11.6500),
    "wehingen":          (48.1102,  8.7856),
    "weimar":            (50.9793, 11.3293),
    "erlangen":          (49.5953, 11.0045),
    "oberhausen":        (51.4713,  6.8524),
    "schenefeld":        (53.6003,  9.8345),
    "wildenberg":        (48.8333, 11.9167),
    "hennef":            (50.7756,  7.2837),
    "hamburg":           (53.5505,  9.9937),
    "malschwitz":        (51.2300, 14.3700),
    "essen":             (51.4556,  7.0116),
    "balingen":          (48.2747,  8.8522),
    "linden":            (52.4167,  9.6833),
    "siegburg":          (50.7950,  7.2100),
    "gangelt":           (51.0075,  6.0028),
    "saarbrücken":       (49.2333,  7.0000),
    "saarbruecken":      (49.2333,  7.0000),
    "frankfurt am main": (50.1109,  8.6821),
    "meckenheim":        (50.6297,  7.0214),
    "darmstadt":         (49.8728,  8.6512),
    "waldachtal":        (48.4667,  8.5667),
    "brakel":            (51.7167,  9.1833),
    "bad aibling":       (47.8614, 12.0086),
    "berlin":            (52.5200, 13.4050),
    "magdeburg":         (52.1200, 11.6333),
}

# ── Region + Bundesland (lowercase-Keys) ─────────────────────────────────────
_STADT_REGION: dict[str, tuple[str, str]] = {
    "obertshausen":      ("Hessen",              "Hessen"),
    "neubiberg":         ("Bayern-Süd",           "Bayern"),
    "wehingen":          ("BaWü-Süd",             "Baden-Württemberg"),
    "weimar":            ("Thüringen",            "Thüringen"),
    "erlangen":          ("Bayern-Nord",          "Bayern"),
    "oberhausen":        ("NRW-West",             "Nordrhein-Westfalen"),
    "schenefeld":        ("Nord",                 "Schleswig-Holstein"),
    "wildenberg":        ("Bayern-Ost",           "Bayern"),
    "hennef":            ("NRW-Süd",              "Nordrhein-Westfalen"),
    "hamburg":           ("Nord",                 "Hamburg"),
    "malschwitz":        ("Sachsen",              "Sachsen"),
    "essen":             ("NRW-West",             "Nordrhein-Westfalen"),
    "balingen":          ("BaWü-Süd",             "Baden-Württemberg"),
    "linden":            ("Niedersachsen",        "Niedersachsen"),
    "siegburg":          ("NRW-Süd",              "Nordrhein-Westfalen"),
    "gangelt":           ("NRW-West",             "Nordrhein-Westfalen"),
    "saarbrücken":       ("Saarland",             "Saarland"),
    "saarbruecken":      ("Saarland",             "Saarland"),
    "frankfurt am main": ("Hessen",               "Hessen"),
    "meckenheim":        ("NRW-Süd",              "Nordrhein-Westfalen"),
    "darmstadt":         ("Hessen",               "Hessen"),
    "waldachtal":        ("BaWü-Süd",             "Baden-Württemberg"),
    "brakel":            ("NRW-Ost",              "Nordrhein-Westfalen"),
}


def _pseudonym_id(name: str) -> str:
    """Stabiler 4-stelliger Hex-Code aus SHA256(name), z.B. 'T-7f3a'."""
    h = hashlib.sha256(name.encode("utf-8")).hexdigest()
    return f"T-{h[:4]}"


def _display_name_kurz(name: str) -> str:
    """Vorname + erster Buchstabe Nachname + Punkt. Fallback: vollstaendiger Name."""
    parts = name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[-1][0]}."
    return name.strip()


def _display_id(name: str) -> str:
    """Gibt Pseudonym oder Anzeigenamen (Vorname Initial) zurueck, je nach PSEUDONYMISIERUNG_AKTIV."""
    if PSEUDONYMISIERUNG_AKTIV:
        return _pseudonym_id(name)
    return _display_name_kurz(name)


def _norm_umlaut(s: str) -> str:
    """Normalisiert Umlaute fuer robustes Name-Matching zwischen Sheets."""
    return (s.strip()
            .replace("ä", "ae").replace("Ä", "Ae")
            .replace("ö", "oe").replace("Ö", "Oe")
            .replace("ü", "ue").replace("Ü", "Ue")
            .replace("ß", "ss"))


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Luftlinien-Distanz in km (Haversine-Formel)."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _lade_korrekturen() -> dict[str, dict]:
    """Lädt skill_korrekturen.json; {} wenn Datei fehlt (keine Pflicht-Datei)."""
    if not _KORREKTUREN.exists():
        return {}
    try:
        raw = json.loads(_KORREKTUREN.read_text(encoding="utf-8"))
        result: dict[str, dict] = {}
        for k in raw.get("korrekturen", []):
            nn = _norm_umlaut(k["techniker"])
            result[nn] = {
                "praefixe": [p.strip().upper() for p in k.get("repair_codes_ignorieren_praefixe", [])],
                "korrekt":  {c.strip().upper() for c in k.get("repair_codes_korrekt", [])},
                "grund":    k.get("grund", ""),
            }
        return result
    except Exception:
        return {}


def _wende_korrektur_an(repair_mcs: set[str], korrektur: dict) -> set[str]:
    """Filtert repair_mcs gemaess Korrektur-Eintrag.

    1. Entfernt Codes deren Prefix in korrektur['praefixe'] steht.
    2. Schneidet das Ergebnis mit korrektur['korrekt'] (Whitelist), falls nicht leer.
    """
    praefixe = korrektur.get("praefixe", [])
    korrekt  = korrektur.get("korrekt", set())
    nach_filter = {c for c in repair_mcs if not any(c.upper().startswith(p) for p in praefixe)}
    if korrekt:
        return {c for c in nach_filter if c.upper() in korrekt}
    return nach_filter


def build_dashboard_data() -> dict:
    """Parst XLSX und erstellt dashboard-kompatible Daten mit pseudonymisierten IDs."""
    from api.import_real_data import parse_smax_xlsx
    from api.cluster_mapping import finde_repair_familie
    from techniker.scoring import _KLINIK_COORDS

    if not _XLSX.exists():
        raise FileNotFoundError(f"XLSX nicht gefunden: {_XLSX}")

    ergebnis = parse_smax_xlsx(_XLSX.read_bytes(), sample_limit=None)
    korrekturen = _lade_korrekturen()

    # Skill-Map: normalisierter Name → {PM-Codes, Alle-Codes}
    # Normalisierung notwendig: Skills-Sheet hat "Dirk Haebel", Wohnorte "Dirk Hübel"
    skill_pm:     dict[str, set[str]] = {}
    skill_repair: dict[str, set[str]] = {}
    skill_alle:   dict[str, set[str]] = {}
    all_mc:       set[str] = set()
    all_repair_mc: set[str] = set()  # alle Codes mit repair=True im Mapping

    for entry in ergebnis.skills:
        tn_norm = _norm_umlaut(entry.tech_name)
        all_mc.add(entry.model_code)
        skill_alle.setdefault(tn_norm, set()).add(entry.model_code)
        if entry.qualifikation == "PM":
            skill_pm.setdefault(tn_norm, set()).add(entry.model_code)
            if entry.repair is True:
                # Gerät ist Repair-fähig → zählt für PM-Abdeckung (Repair-Geräte)
                all_repair_mc.add(entry.model_code)
                skill_repair.setdefault(tn_norm, set()).add(entry.model_code)

    total_mc = len(all_mc)
    total_repair_mc = len(all_repair_mc)

    # Crosstraining: Repair-Jobs mit bekannten PLZ-Koordinaten vorverarbeiten
    job_repair_orte: list[tuple[str, float, float]] = []  # (familie, lat, lon)
    for auftrag in ergebnis.geschlossene_auftraege + ergebnis.offene_auftraege:
        familie = finde_repair_familie(auftrag.model_code)
        if familie is None:
            continue
        plz = (auftrag.plz or "").strip()
        if not plz:
            continue
        coords = _KLINIK_COORDS.get(plz.zfill(5))
        if coords is None:
            continue
        job_repair_orte.append((familie, coords[0], coords[1]))

    techniker_list: list[dict] = []
    for tech in ergebnis.techniker:
        ort      = tech.ort.strip()
        ort_key  = ort.lower()
        lat, lon = _STADT_COORDS.get(ort_key, (0.0, 0.0))
        region, bundesland = _STADT_REGION.get(ort_key, ("Unbekannt", "Unbekannt"))

        tn_norm    = _norm_umlaut(tech.name)
        pm_mcs     = skill_pm.get(tn_norm, set())
        alle_mcs   = skill_alle.get(tn_norm, set())
        pm_count   = len(pm_mcs)

        repair_mcs_raw = skill_repair.get(tn_norm, set())
        if tn_norm in korrekturen:
            repair_mcs = _wende_korrektur_an(repair_mcs_raw, korrekturen[tn_norm])
        else:
            repair_mcs = repair_mcs_raw
        pm_repair_count = len(repair_mcs)

        # Crosstraining-Potenzial: Repair-Familien im 150-km-Umkreis
        tech_repair_familien: set[str] = set()
        for mc in repair_mcs:
            fam = finde_repair_familie(mc)
            if fam:
                tech_repair_familien.add(fam)

        geraete_im_gebiet: dict[str, int] = {}
        stk_potenzial = 0
        if lat != 0.0 or lon != 0.0:
            for familie, jlat, jlon in job_repair_orte:
                dist = _haversine_km(lat, lon, jlat, jlon)
                if dist <= _CT_LUFTLINIE_KM:
                    geraete_im_gebiet[familie] = geraete_im_gebiet.get(familie, 0) + 1
                    if familie not in tech_repair_familien:
                        stk_potenzial += 1

        crosstraining_luecken = sorted(
            f for f in geraete_im_gebiet if f not in tech_repair_familien
        )

        techniker_list.append({
            "pseudonym_id":      _display_id(tech.name),
            "standort":          ort,
            "plz":               tech.plz or "",
            "region":            region,
            "bundesland":        bundesland,
            "status":            "aktiv",
            "lat":               lat,
            "lon":               lon,
            "hugo_ka":           ort_key in _HUGO_KA_STAEDTE,
            "techniker_typ":     "HUGO_KEY_ACCOUNT" if ort_key in _HUGO_KA_STAEDTE else "STANDARD",
            "in_skills_matrix":  bool(alle_mcs),
            "pm_count":          pm_count,
            "pm_repair_count":   pm_repair_count,
            "total_model_codes": total_mc,
            "total_repair_codes": total_repair_mc,
            "pm_ratio_pct":      round(pm_count / total_mc * 100, 1) if total_mc else 0.0,
            "repair_abdeckung_pct": round(pm_repair_count / total_repair_mc * 100, 1) if total_repair_mc else 0.0,
            "crosstraining_luecken": crosstraining_luecken,
            "stk_potenzial":         stk_potenzial,
            "geraete_im_gebiet":     geraete_im_gebiet,
        })

    dauern = [d for d in ergebnis.einsatzdauern if d.median_min > 0]
    einsatz_median_min = round(sum(d.median_min for d in dauern) / len(dauern)) if dauern else 0

    return {
        "techniker":                  techniker_list,
        "total_model_codes":          total_mc,
        "total_repair_codes":         total_repair_mc,
        "total_skills_eintraege":     len(ergebnis.skills),
        "pm_skills_eintraege":        sum(1 for e in ergebnis.skills if e.qualifikation == "PM"),
        "pm_repair_skills_eintraege": sum(1 for e in ergebnis.skills if e.qualifikation == "PM" and e.repair is True),
        "closed_jobs":                len(ergebnis.geschlossene_auftraege),
        "open_jobs":                  len(ergebnis.offene_auftraege),
        "stk_potenzial_gesamt":       sum(t["stk_potenzial"] for t in techniker_list),
        "einsatz_median_min":         einsatz_median_min,
        "generated_at":               datetime.now().isoformat(timespec="seconds"),
    }


def save_dashboard_data() -> dict:
    """Erstellt und speichert den JSON-Cache."""
    data = build_dashboard_data()
    _CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def load_dashboard_data() -> Optional[dict]:
    """Lädt gespeicherten Cache, gibt None zurück wenn nicht vorhanden."""
    if not _CACHE.exists():
        return None
    try:
        return json.loads(_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return None


if __name__ == "__main__":
    print("Erstelle SMax Dashboard-Cache...")
    try:
        data = save_dashboard_data()
        print(f"Gespeichert: {_CACHE}")
        print(f"  Techniker:               {len(data['techniker'])}")
        print(f"  Skills gesamt:           {data['total_skills_eintraege']}")
        print(f"  davon PM:                {data['pm_skills_eintraege']}")
        print(f"  PM auf Repair-Geraete:   {data['pm_repair_skills_eintraege']}")
        print(f"  Model Codes gesamt:      {data['total_model_codes']}")
        print(f"  davon Repair-relevant:   {data['total_repair_codes']}")
        print(f"  Closed Jobs:             {data['closed_jobs']}")
        print(f"  Open Jobs:               {data['open_jobs']}")
        modus = "pseudonymisiert (SHA256)" if PSEUDONYMISIERUNG_AKTIV else "echte Namen (Nachname)"
        print()
        print(f"Techniker ({modus})  [PM-Codes / PM auf Repair-Geraeten / Abdeckung%]:")
        for t in data["techniker"]:
            ka = " [Hugo KA]" if t["hugo_ka"] else ""
            mx = " [Skills-Matrix]" if t["in_skills_matrix"] else " [keine Skills]"
            ct = f"  STK-Pot: {t['stk_potenzial']:3d}" if t["stk_potenzial"] > 0 else ""
            print(f"  {t['pseudonym_id']:14s}  {t['standort']:20s}  "
                  f"PM: {t['pm_count']:3d}  RepairPM: {t['pm_repair_count']:3d}"
                  f"  Abdeckung: {t['repair_abdeckung_pct']:5.1f}%{ct}{ka}{mx}")
    except FileNotFoundError as e:
        print(f"FEHLER: {e}")
