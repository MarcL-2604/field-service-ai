"""
Import-Routen (api/import_routes.py)
=====================================
5 Endpunkte für CSV-Datenimport durch den Koordinator.
Kompatibel mit FastAPI. Für Flask: siehe Kommentare unten.

Endpunkte:
  POST /api/import/geraete          → Gerätedaten & Verträge
  POST /api/import/skillmatrix      → Skillmatrix (Level + Repair)
  POST /api/import/messmittel       → Messmittel & Kalibrierungen
  POST /api/import/wartungshistorie → Erledigte Wartungen (3 Jahre)
  POST /api/import/techniker        → Techniker-Stammdaten
  GET  /api/import/status           → Status aller Importe

Verwendung:
  from api.import_routes import router
  app.include_router(router)   # FastAPI
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from fastapi import APIRouter, UploadFile, File
from pydantic import BaseModel, Field

from techniker.stammdaten import techniker_aus_csv_zeile
from techniker.skill_matrix import skillmatrix_aus_csv_zeile


router = APIRouter(prefix="/api/import", tags=["Import"])


# ── In-Memory Store (Phase 1 / Test) ─────────────────────────────────────────
# In Phase 2 (Flask + SQLite) durch DB-Session ersetzen

_store: dict[str, list[dict]] = {
    "geraete": [],
    "skillmatrix": [],
    "messmittel": [],
    "wartungshistorie": [],
    "techniker": [],
}
_import_meta: dict[str, dict] = {}


# ── Response-Modelle ──────────────────────────────────────────────────────────

class ImportResult(BaseModel):
    modul: str
    zeilen_gesamt: int
    zeilen_ok: int
    zeilen_fehler: int
    fehler: list[str] = Field(default_factory=list)
    warnungen: list[str] = Field(default_factory=list)
    timestamp: str


class ImportStatus(BaseModel):
    geraete: int
    skillmatrix: int
    messmittel: int
    wartungshistorie: int
    techniker: int
    alle_geladen: bool
    letzte_imports: dict[str, str]


# ── CSV-Helper ────────────────────────────────────────────────────────────────

async def _csv_zu_dicts(file: UploadFile) -> list[dict]:
    """Liest CSV-Upload und gibt Liste von Dicts zurück."""
    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    # Delimiter erkennen
    delim = ";" if text.count(";") > text.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    return [
        {k.strip(): v.strip() if v else "" for k, v in row.items()}
        for row in reader
    ]


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── Endpunkt 1: Gerätedaten ───────────────────────────────────────────────────

@router.post("/geraete", response_model=ImportResult)
async def import_geraete(file: UploadFile = File(...)):
    """
    Importiert Gerätedaten, Wartungsverträge und Fälligkeiten.

    Pflichtfelder: seriennummer, produktfamilie, cluster, klinik_name,
                   klinik_plz, klinik_ort, vertragstyp
    """
    zeilen = await _csv_zu_dicts(file)
    ok, fehler, warnungen = [], [], []
    PFLICHT = {"seriennummer", "produktfamilie", "cluster", "klinik_name",
               "klinik_plz", "klinik_ort", "vertragstyp"}

    seriennummern: set[str] = set()

    for i, z in enumerate(zeilen, 1):
        # Pflichtfelder prüfen
        miss = [f for f in PFLICHT if not z.get(f)]
        if miss:
            fehler.append(f"Zeile {i}: Pflichtfelder fehlen: {', '.join(miss)}")
            continue

        sn = z["seriennummer"]
        if sn in seriennummern:
            warnungen.append(f"Zeile {i}: Doppelte Seriennummer {sn!r}")
        seriennummern.add(sn)

        plz = z.get("klinik_plz", "")
        if not (len(plz) == 5 and plz.isdigit()):
            warnungen.append(f"Zeile {i}: Ungültige PLZ {plz!r} für {sn}")

        ok.append(z)

    _store["geraete"] = ok
    _import_meta["geraete"] = {"timestamp": _now_iso(), "count": len(ok)}

    return ImportResult(
        modul="geraete",
        zeilen_gesamt=len(zeilen),
        zeilen_ok=len(ok),
        zeilen_fehler=len(fehler),
        fehler=fehler[:20],
        warnungen=warnungen[:20],
        timestamp=_now_iso(),
    )


# ── Endpunkt 2: Skillmatrix ───────────────────────────────────────────────────

@router.post("/skillmatrix", response_model=ImportResult)
async def import_skillmatrix(file: UploadFile = File(...)):
    """
    Importiert Skillmatrix der Techniker.

    STK-Level = PM-Level — ein Level-Wert pro Cluster.
    Repair ist separat (L3 oder leer).

    Pflichtfelder: tech_id, name
    Cluster-Spalten: c1_level, c1_repair, c2_level, c2_repair, ...
    """
    zeilen = await _csv_zu_dicts(file)
    ok, fehler, warnungen = [], [], []
    gesehen_ids: set[str] = set()

    for i, z in enumerate(zeilen, 1):
        tech_id = z.get("tech_id", "").strip().upper()
        if not tech_id:
            fehler.append(f"Zeile {i}: tech_id fehlt")
            continue

        if tech_id in gesehen_ids:
            warnungen.append(f"Zeile {i}: Doppelte tech_id {tech_id!r} — wird überschrieben")
        gesehen_ids.add(tech_id)

        # Level-Werte validieren
        CLUSTER_LEVELS = ["c1_level", "c2_level", "c3_level", "c4_level", "cs_level", "ch_level"]
        for lk in CLUSTER_LEVELS:
            v = z.get(lk, "")
            if v and v.upper() not in ("L2", "L3"):
                warnungen.append(f"Zeile {i} ({tech_id}): Ungültiger Level-Wert {v!r} in {lk}")

        # Pydantic-Modell erstellen
        try:
            skill = skillmatrix_aus_csv_zeile(z)
            ok.append(skill.model_dump())
        except Exception as e:
            fehler.append(f"Zeile {i} ({tech_id}): {e}")

    _store["skillmatrix"] = ok
    _import_meta["skillmatrix"] = {"timestamp": _now_iso(), "count": len(ok)}

    return ImportResult(
        modul="skillmatrix",
        zeilen_gesamt=len(zeilen),
        zeilen_ok=len(ok),
        zeilen_fehler=len(fehler),
        fehler=fehler[:20],
        warnungen=warnungen[:20],
        timestamp=_now_iso(),
    )


# ── Endpunkt 3: Messmittel ────────────────────────────────────────────────────

@router.post("/messmittel", response_model=ImportResult)
async def import_messmittel(file: UploadFile = File(...)):
    """
    Importiert Messmittel und Spezialwerkzeug.

    Pflichtfelder: tool_id, tool_typ, tech_id, produktfamilie
    Kalibrierung_bis wird gegen heutiges Datum geprüft.
    """
    zeilen = await _csv_zu_dicts(file)
    ok, fehler, warnungen = [], [], []
    heute = date.today()
    in_90_tagen = date.fromordinal(heute.toordinal() + 90)
    PFLICHT = {"tool_id", "tool_typ", "tech_id", "produktfamilie"}

    for i, z in enumerate(zeilen, 1):
        miss = [f for f in PFLICHT if not z.get(f)]
        if miss:
            fehler.append(f"Zeile {i}: Pflichtfelder fehlen: {', '.join(miss)}")
            continue

        # Kalibrierung prüfen
        kal_str = z.get("kalib_bis", "").strip()
        if kal_str:
            try:
                kal = date.fromisoformat(kal_str)
                if kal < heute:
                    warnungen.append(
                        f"Tool {z['tool_id']} ({z['tech_id']}): "
                        f"Kalibrierung ABGELAUFEN seit {kal_str}"
                    )
                elif kal <= in_90_tagen:
                    warnungen.append(
                        f"Tool {z['tool_id']} ({z['tech_id']}): "
                        f"Kalibrierung fällig in <90 Tagen ({kal_str})"
                    )
            except ValueError:
                warnungen.append(f"Zeile {i}: Ungültiges Datum {kal_str!r} in kalib_bis")

        ok.append(z)

    _store["messmittel"] = ok
    _import_meta["messmittel"] = {"timestamp": _now_iso(), "count": len(ok)}

    return ImportResult(
        modul="messmittel",
        zeilen_gesamt=len(zeilen),
        zeilen_ok=len(ok),
        zeilen_fehler=len(fehler),
        fehler=fehler[:20],
        warnungen=warnungen[:20],
        timestamp=_now_iso(),
    )


# ── Endpunkt 4: Wartungshistorie ──────────────────────────────────────────────

@router.post("/wartungshistorie", response_model=ImportResult)
async def import_wartungshistorie(file: UploadFile = File(...)):
    """
    Importiert erledigte Wartungen (3 Jahre).
    STK, PM und Repair werden alle verarbeitet.

    Pflichtfelder: auftrag_nr, datum, tech_id, produktfamilie,
                   auftragstyp, dauer_min
    """
    zeilen = await _csv_zu_dicts(file)
    ok, fehler, warnungen = [], [], []
    heute = date.today()
    vor_3_jahren = date(heute.year - 3, heute.month, heute.day)
    PFLICHT = {"auftrag_nr", "datum", "tech_id", "produktfamilie", "auftragstyp", "dauer_min"}
    TYPEN = {"STK", "PM", "REPAIR"}
    typen_gefunden: set[str] = set()
    ausserhalb_zeitraum = 0

    for i, z in enumerate(zeilen, 1):
        miss = [f for f in PFLICHT if not z.get(f)]
        if miss:
            fehler.append(f"Zeile {i}: Pflichtfelder fehlen: {', '.join(miss)}")
            continue

        # Auftragstyp normalisieren
        at = z.get("auftragstyp", "").strip().upper()
        at_norm = "REPAIR" if "REP" in at else ("PM" if "PM" in at or "WART" in at else ("STK" if "STK" in at else at))
        if at_norm not in TYPEN:
            warnungen.append(f"Zeile {i}: Unbekannter Auftragstyp {at!r} (erwartet STK/PM/Repair)")
        else:
            typen_gefunden.add(at_norm)
            z["auftragstyp_norm"] = at_norm

        # Dauer validieren
        try:
            dauer = int(z.get("dauer_min", 0))
            if dauer <= 0:
                warnungen.append(f"Zeile {i}: Einsatzdauer {dauer} Min ungültig")
        except (ValueError, TypeError):
            fehler.append(f"Zeile {i}: dauer_min ist keine Zahl: {z.get('dauer_min')!r}")
            continue

        # Datum prüfen (3-Jahres-Fenster)
        datum_str = z.get("datum", "").strip()
        if datum_str:
            try:
                datum = date.fromisoformat(datum_str)
                if datum < vor_3_jahren:
                    ausserhalb_zeitraum += 1
            except ValueError:
                warnungen.append(f"Zeile {i}: Ungültiges Datum {datum_str!r}")

        ok.append(z)

    if ausserhalb_zeitraum:
        warnungen.insert(0, f"{ausserhalb_zeitraum} Einträge außerhalb 3-Jahres-Fenster (vor {vor_3_jahren})")

    fehlende_typen = TYPEN - typen_gefunden
    if fehlende_typen:
        warnungen.insert(0, f"Auftragstypen nicht gefunden: {', '.join(fehlende_typen)}")

    _store["wartungshistorie"] = ok
    _import_meta["wartungshistorie"] = {"timestamp": _now_iso(), "count": len(ok)}

    return ImportResult(
        modul="wartungshistorie",
        zeilen_gesamt=len(zeilen),
        zeilen_ok=len(ok),
        zeilen_fehler=len(fehler),
        fehler=fehler[:20],
        warnungen=warnungen[:20],
        timestamp=_now_iso(),
    )


# ── Endpunkt 5: Techniker-Stammdaten ─────────────────────────────────────────

@router.post("/techniker", response_model=ImportResult)
async def import_techniker(file: UploadFile = File(...)):
    """
    Importiert Techniker-Stammdaten (Wohnort, PLZ, Koordinaten, Kontakt).
    Gebietsplanung wird abgeleitet aus PLZ — kein separates Gebietsmodul.

    Pflichtfelder: tech_id, nachname, vorname, plz, ort
    """
    zeilen = await _csv_zu_dicts(file)
    ok, fehler, warnungen = [], [], []

    for i, z in enumerate(zeilen, 1):
        try:
            tech = techniker_aus_csv_zeile(z)
            ok.append(tech.model_dump())
            # Koordinaten-Hinweis
            if not tech.hat_koordinaten:
                warnungen.append(
                    f"{tech.tech_id}: Keine Koordinaten — PLZ-Näherung wird verwendet"
                )
        except Exception as e:
            fehler.append(f"Zeile {i}: {e}")

    _store["techniker"] = ok
    _import_meta["techniker"] = {"timestamp": _now_iso(), "count": len(ok)}

    return ImportResult(
        modul="techniker",
        zeilen_gesamt=len(zeilen),
        zeilen_ok=len(ok),
        zeilen_fehler=len(fehler),
        fehler=fehler[:20],
        warnungen=warnungen[:20],
        timestamp=_now_iso(),
    )


# ── Status-Endpunkt ───────────────────────────────────────────────────────────

@router.get("/status", response_model=ImportStatus)
async def import_status():
    """Gibt den aktuellen Import-Status aller 5 Module zurück."""
    counts = {k: len(v) for k, v in _store.items()}
    return ImportStatus(
        geraete=counts["geraete"],
        skillmatrix=counts["skillmatrix"],
        messmittel=counts["messmittel"],
        wartungshistorie=counts["wartungshistorie"],
        techniker=counts["techniker"],
        alle_geladen=all(v > 0 for v in counts.values()),
        letzte_imports={k: v.get("timestamp", "—") for k, v in _import_meta.items()},
    )


# ── Daten abrufen (intern) ────────────────────────────────────────────────────

def get_imported(modul: str) -> list[dict]:
    """Interne Funktion: importierte Daten für andere Module abrufen."""
    return _store.get(modul, [])
