"""Scoring und Empfehlungslogik fuer die Technikerauswahl.

Haupt-API:
    berechne_empfehlung(auftrag_typ, produkt_familie, klinik_id) -> list[EmpfehlungErgebnis]

Score-Formel (0-100):
    Score = Kompetenz * 0.40 + Fahrzeit * 0.35 + Auslastung * 0.25

Arbeitszeitmodell (Vertrauensarbeitszeit):
    Freitag = Home Office / Admintag → kein Außeneinsatz (außer Repair-Notfall).
    Effektive Außendienst-Kapazitaet: Mo-Do = 4 x 8h = 32h/Woche.
    Gesamtwoche contractlich 40h, ArbZG-Absolut-Limit 45h.

    Wochenstunden-Warnlevel (Basis 32h Außendienst-Ziel):
        >= 30h  → PUFFER-Warnung  (2h Puffer vor 32h-Ziel)
        >= 34h  → GELB-Warnung    (2h ueber 32h-Ziel, Vertrauensarbeitszeit aktiv)
        > 45h   → Ausschluss      (ArbZG-Absolut-Maximum ueberschritten)

    Tagesarbeitszeit (Fahrtzeit zaehlt als Arbeitszeit):
        > 8h    → Warnung
        > 9h    → Warnung (Regel-Max)
        > 10h   → Ausschluss (Absolut-Max, ArbZG)

    Weitere harte Ausschluesse:
        - Keine / unzureichende Qualifikation fuer die Produktfamilie
        - Hugo: ausschliesslich Level 3
        - Small Capital (NIM, Programmer, ACT, IPC) + Repair/PM: L3 Pflicht
          Small Capital + STK: L2 vollwertig einsetzbar (Score 100, kein Abzug)
        - Mindestruhezeit < 11h zum letzten Arbeitsende (ArbZG §5)
        - Wochenende (Sa/So)
        - Freitag: nur dringende Repair-Auftraege erlaubt

    Uebernachtungsregel:
        Fahrzeit > 3h einfache Strecke → Uebernachtung noetig (+150 EUR)
        Max 1 Uebernachtung pro Woche und Techniker → Warnung bei Ueberschreitung
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from techniker.models import (
    STK_L2_ERLAUBT,
    mindest_level_fuer,
)
from techniker.abwesenheit import Abwesenheit, ist_abwesend
from config import (
    SCORING_KOMPETENZ as _W_KOMPETENZ,
    SCORING_FAHRZEIT as _W_FAHRZEIT,
    SCORING_AUSLASTUNG as _W_AUSLASTUNG,
    AUSSENDIENST_STUNDEN,
    ARBZG_MAX_STUNDEN,
    WARNUNG_STUNDEN,
    HUGO_KA_FAKTOR,
    HUGO_KA_ZIEL_STUNDEN,
    HUGO_KA_IDS,
    HUGO_EINSATZ_STUNDEN,
    HAVERSINE_UMWEG_FAKTOR,
    MAX_UEBERNACHTUNGEN_WOCHE,
    UEBERNACHTUNG_KOSTEN_EUR,
    UEBERNACHTUNG_TRIGGER_H,
)

_DATA_DIR = Path(__file__).parent.parent / "daten"

# Arbeitszeitgrenzen – Vertrauensarbeitszeit (ArbZG)
# Freitag = HO/Admintag → effektive Außendienst-Kapazitaet Mo-Do = 4 x 8h = 32h
_WOCHE_ZIEL_STD = float(AUSSENDIENST_STUNDEN)
_WOCHE_WARN_PUFFER = 30.0     # Puffer-Warnung: 2h vor 32h-Ziel
_WOCHE_WARN_GELB = float(WARNUNG_STUNDEN)
_WOCHE_MAX_ABSOLUT = float(ARBZG_MAX_STUNDEN)
_MAX_TAG_NORMAL = 8.0         # Normaler Arbeitstag
_MAX_TAG_REGEL = 9.0          # Regel-Maximum
_MAX_TAG_ABSOLUT = 10.0       # Absolutes Tages-Maximum (ArbZG §3)
_MINDESTRUHEZEIT_STD = 11.0   # Mindestruhezeit zwischen Arbeitstagen (ArbZG §5)
_WOCHENTAG_FREITAG = 4        # datetime.weekday(): 0=Mo, 4=Fr, 5=Sa, 6=So

# Kompetenz-Score je Level
_LEVEL_SCORE: dict[str, float] = {"L3": 100.0, "L2": 50.0, "L1": 0.0}

# Hugo Key Account: 20% Kapazitaetsreserve fuer ungeplante Hugo-Calls
_HUGO_KEY_ACCOUNT_IDS: set[str] = set(HUGO_KA_IDS)
_HUGO_KAPAZITAETS_FAKTOR = HUGO_KA_FAKTOR
_HUGO_EINSATZ_DAUER_STD = HUGO_EINSATZ_STUNDEN
_HUGO_WOCHE_ZIEL_STD = HUGO_KA_ZIEL_STUNDEN

# Rueckwaertskompatibel: SMALL_CAPITAL_STK_L2_REICHT fuer bestehende Imports
SMALL_CAPITAL_STK_L2_REICHT: list[str] = list(STK_L2_ERLAUBT)

# Uebernachtungsregel
MAX_UEBERNACHTUNGEN_PRO_WOCHE = MAX_UEBERNACHTUNGEN_WOCHE  # Re-export fuer Tests
_UEBERNACHTUNGS_FAHRZEIT_SCHWELLE_STD = float(UEBERNACHTUNG_TRIGGER_H)
_UEBERNACHTUNGS_KOSTEN_EUR = float(UEBERNACHTUNG_KOSTEN_EUR)

# Fahrzeit-Schaetzung: Luftlinie * Umwegfaktor / Durchschnittsgeschwindigkeit
_UMWEGFAKTOR = HAVERSINE_UMWEG_FAKTOR
_REISEGESCHWINDIGKEIT_KMH = 90.0

# Approximate GPS-Koordinaten fuer alle Kliniken aus kliniken.csv (nach PLZ)
_KLINIK_COORDS: dict[str, tuple[float, float]] = {
    "20246": (53.566, 10.010),  # Hamburg UKE
    "23538": (53.866, 10.687),  # Lübeck UKSH
    "24105": (54.323, 10.123),  # Kiel UKSH
    "22291": (53.587, 10.040),  # Hamburg Barmbek
    "19049": (53.629, 11.415),  # Schwerin
    "18057": (54.089, 12.140),  # Rostock
    "17475": (54.096, 13.382),  # Greifswald
    "17036": (53.557, 13.265),  # Neubrandenburg
    "30625": (52.376, 9.732),   # Hannover MHH
    "38126": (52.269, 10.527),  # Braunschweig
    "37075": (51.541, 9.916),   # Göttingen
    "49076": (52.280, 8.047),   # Osnabrück
    "28177": (53.079, 8.802),   # Bremen
    "48149": (51.961, 7.626),   # Münster
    "40225": (51.222, 6.776),   # Düsseldorf
    "50937": (50.933, 6.922),   # Köln Uni
    "53127": (50.732, 7.115),   # Bonn
    "52074": (50.775, 6.084),   # Aachen
    "44789": (51.482, 7.216),   # Bochum BG
    "44137": (51.514, 7.465),   # Dortmund
    "33617": (52.030, 8.533),   # Bielefeld
    "47166": (51.435, 6.762),   # Duisburg
    "51109": (50.940, 7.030),   # Köln Merheim
    "41462": (51.206, 6.690),   # Neuss
    "41464": (51.206, 6.690),   # Neuss
    "42549": (51.334, 7.044),   # Velbert
    "33332": (51.908, 8.384),   # Gütersloh
    "59071": (51.680, 7.814),   # Hamm
    "60590": (50.094, 8.653),   # Frankfurt Uni
    "35392": (50.584, 8.678),   # Gießen
    "64283": (49.873, 8.651),   # Darmstadt
    "34125": (51.317, 9.498),   # Kassel
    "65199": (50.078, 8.240),   # Wiesbaden Helios
    "36043": (50.556, 9.675),   # Fulda
    "65189": (50.078, 8.240),   # Wiesbaden Josefs
    "55131": (49.993, 8.247),   # Mainz
    "56072": (50.360, 7.598),   # Koblenz
    "67063": (49.481, 8.435),   # Ludwigshafen
    "66421": (49.327, 7.340),   # Homburg/Saar
    "66119": (49.235, 6.997),   # Saarbrücken
    "69120": (49.409, 8.694),   # Heidelberg
    "79106": (47.999, 7.842),   # Freiburg
    "72076": (48.522, 9.058),   # Tübingen
    "89081": (48.397, 9.998),   # Ulm
    "70174": (48.778, 9.180),   # Stuttgart
    "76133": (49.007, 8.404),   # Karlsruhe
    "74078": (49.143, 9.211),   # Heilbronn
    "78052": (48.060, 8.459),   # Villingen-Schwenningen
    "88048": (47.657, 9.479),   # Friedrichshafen
    "77654": (48.474, 7.941),   # Offenburg
    "80336": (48.135, 11.582),  # München LMU
    "81675": (48.137, 11.601),  # München TU rechts der Isar
    "81377": (48.113, 11.472),  # München LMU Großhadern
    "91054": (49.599, 11.003),  # Erlangen
    "97080": (49.791, 9.953),   # Würzburg
    "93053": (49.013, 12.102),  # Regensburg
    "86156": (48.371, 10.898),  # Augsburg
    "90419": (49.452, 11.077),  # Nürnberg
    "85049": (48.767, 11.426),  # Ingolstadt
    "83022": (47.856, 12.129),  # Rosenheim
    "84034": (48.537, 12.154),  # Landshut
    "85221": (48.260, 11.435),  # Dachau
    "87439": (47.726, 10.316),  # Kempten
    "87509": (47.561, 10.221),  # Immenstadt
    "87600": (47.880, 10.623),  # Kaufbeuren
    "87700": (47.984, 10.181),  # Memmingen
    "88131": (47.546, 9.693),   # Lindau
    "22763": (53.553, 9.936),   # Hamburg Altona
    "22087": (53.572, 10.039),  # Hamburg Marienkrankenhaus
    "24939": (54.783, 9.441),   # Flensburg
    "25524": (53.925, 9.514),   # Itzehoe
    "25421": (53.664, 9.800),   # Pinneberg
    "10117": (52.520, 13.405),  # Berlin Mitte
    "13353": (52.542, 13.350),  # Berlin Virchow
    "12351": (52.482, 13.438),  # Berlin Neukölln
    "13125": (52.631, 13.496),  # Berlin Buch
    "14467": (52.391, 13.065),  # Potsdam
    "15236": (52.347, 14.551),  # Frankfurt (Oder)
    "03048": (51.756, 14.333),  # Cottbus
    "01307": (51.050, 13.737),  # Dresden Carus
    "04103": (51.340, 12.373),  # Leipzig
    "04129": (51.366, 12.371),  # Leipzig St. Georg
    "09116": (50.828, 12.921),  # Chemnitz
    "01067": (51.056, 13.722),  # Dresden Friedrichstadt
    "02625": (51.181, 14.423),  # Bautzen
    "06120": (51.497, 11.969),  # Halle
    "39120": (52.121, 11.628),  # Magdeburg
    "06449": (51.759, 11.474),  # Aschersleben
    "07747": (50.927, 11.586),  # Jena
    "99089": (50.979, 11.033),  # Erfurt
    "98527": (50.610, 10.694),  # Suhl
    "99817": (50.980, 10.315),  # Eisenach
}


@dataclass
class TagesStatus:
    """Aktueller Arbeitszeitstatus eines Technikers fuer den Planungstag.

    Wird als optionaler Parameter an berechne_empfehlung() uebergeben.
    Fehlt der Eintrag fuer einen Techniker, wird er als vollstaendig verfuegbar behandelt.
    """
    wochenstunden_aktuell: float = 0.0   # bereits gebuchte Stunden diese Woche
    tagesstunden_aktuell: float = 0.0    # bereits gebuchte Stunden heute
    letztes_arbeitsende: Optional[datetime] = None  # fuer Ruhezeit-Pruefung
    uebernachtungen_diese_woche: int = 0  # geplante Uebernachtungen in der aktuellen Woche


@dataclass
class EmpfehlungErgebnis:
    """Scored Empfehlung fuer einen einzelnen Techniker."""
    techniker_id: str
    score: float               # Gesamtscore 0-100
    kompetenz_score: float     # Teil-Score Kompetenz (0/50/100)
    fahrzeit_score: float      # Teil-Score Fahrzeit (normalisiert 0-100)
    auslastung_score: float    # Teil-Score Auslastung (0-100)
    distanz_km: float          # Luftlinien-Distanz zur Klinik
    level: str                 # "L1", "L2", "L3" oder "–" wenn nicht qualifiziert
    warnungen: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        w = f", {len(self.warnungen)} Warnung(en)" if self.warnungen else ""
        return (
            f"EmpfehlungErgebnis(id={self.techniker_id}, score={self.score:.1f}, "
            f"distanz={self.distanz_km:.0f}km, level={self.level}{w})"
        )


# ---------------------------------------------------------------------------
# Interne Hilfsfunktionen
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Luftlinien-Distanz in km nach Haversine-Formel."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def _fahrzeit_std(distanz_km: float) -> float:
    """Geschaetzte Fahrtzeit in Stunden (Luftlinie * Umwegfaktor / Reisegeschwindigkeit)."""
    return (distanz_km * _UMWEGFAKTOR) / _REISEGESCHWINDIGKEIT_KMH


def _lade_techniker_df() -> pd.DataFrame:
    return pd.read_csv(_DATA_DIR / "techniker.csv", dtype=str)


def _lade_matrix_df() -> pd.DataFrame:
    return pd.read_csv(_DATA_DIR / "trainingsmatrix.csv", dtype=str)


def _lade_klinik_row(klinik_id: str) -> pd.Series:
    df = pd.read_csv(_DATA_DIR / "kliniken.csv", dtype=str)
    match = df[df["klinik_id"] == klinik_id]
    if match.empty:
        raise ValueError(f"Klinik '{klinik_id}' nicht in kliniken.csv gefunden.")
    return match.iloc[0]


def _klinik_gps(klinik: pd.Series) -> tuple[float, float]:
    plz = str(klinik["plz"]).strip().zfill(5)
    if plz in _KLINIK_COORDS:
        return _KLINIK_COORDS[plz]
    raise ValueError(
        f"Keine GPS-Koordinaten fuer PLZ {plz} (Klinik {klinik['klinik_id']}) hinterlegt."
    )


def _pruefe_arbeitszeit(
    techniker_id: str,
    auftrag_typ: str,
    status: TagesStatus,
    einsatz_dauer_std: float,
    einsatz_datetime: datetime,
    distanz_km: float,
) -> tuple[bool, list[str]]:
    """Prueft alle Arbeitszeitregeln (ArbZG + Vertrauensarbeitszeit) fuer einen Techniker.

    Returns:
        (ausgeschlossen, warnungen)
        ausgeschlossen=True → Techniker darf nicht empfohlen werden.
    """
    wochentag = einsatz_datetime.weekday()
    warnungen: list[str] = []

    # --- Harte Filter (Ausschluss) ---

    # Wochenende: Sa=5, So=6
    if wochentag >= 5:
        return True, ["Kein Einsatz an Wochenenden (Sa/So)"]

    # Freitag: nur dringende Repair-Auftraege
    if wochentag == _WOCHENTAG_FREITAG:
        warnungen.append("Freitag-Einsatz geplant (Homeoffice-/Admintag)")
        if auftrag_typ.upper() != "REPAIR":
            return True, warnungen + ["Freitag gesperrt fuer STK/PM – nur dringende Repair erlaubt"]

    # Mindestruhezeit (ArbZG §5): 11h zwischen Arbeitstagen
    if status.letztes_arbeitsende is not None:
        ruhezeit_std = (einsatz_datetime - status.letztes_arbeitsende).total_seconds() / 3600.0
        if ruhezeit_std < _MINDESTRUHEZEIT_STD:
            return True, [
                f"Mindestruhezeit unterschritten ({ruhezeit_std:.1f}h < {_MINDESTRUHEZEIT_STD}h, ArbZG §5)"
            ]

    fz_std = _fahrzeit_std(distanz_km)
    neuer_tagesstand = status.tagesstunden_aktuell + fz_std + einsatz_dauer_std
    neue_woche = status.wochenstunden_aktuell + fz_std + einsatz_dauer_std

    # Tages-Absolut-Maximum (ArbZG §3): 10h nicht ueberschreiten
    if neuer_tagesstand > _MAX_TAG_ABSOLUT:
        return True, [
            f"Tages-Absolut-Maximum ueberschritten "
            f"(Prognose {neuer_tagesstand:.1f}h > {_MAX_TAG_ABSOLUT}h, ArbZG §3)"
        ]

    # Wochen-Absolut-Maximum: > 45h → Ausschluss
    if neue_woche > _WOCHE_MAX_ABSOLUT:
        return True, [
            f"Wochen-Absolut-Maximum ueberschritten "
            f"(Prognose {neue_woche:.1f}h > {_WOCHE_MAX_ABSOLUT}h)"
        ]

    # --- Warnungen (kein Ausschluss) ---

    # Wochenstunden-Warnlevel
    if status.wochenstunden_aktuell >= _WOCHE_WARN_GELB:
        warnungen.append(
            f"GELB: Wochenstunden deutlich ueber Ziel "
            f"({status.wochenstunden_aktuell:.1f}h / Ziel {_WOCHE_ZIEL_STD}h, "
            f"Max {_WOCHE_MAX_ABSOLUT}h)"
        )
    elif status.wochenstunden_aktuell >= _WOCHE_WARN_PUFFER:
        warnungen.append(
            f"PUFFER: Wochenstunden naehern sich Ziel "
            f"({status.wochenstunden_aktuell:.1f}h / {_WOCHE_ZIEL_STD}h)"
        )

    # Tagesstunden-Warnlevel
    if neuer_tagesstand > _MAX_TAG_REGEL:
        warnungen.append(
            f"Tageseinsatz ueberschreitet Regel-Maximum inkl. Fahrt "
            f"(Prognose {neuer_tagesstand:.1f}h > {_MAX_TAG_REGEL}h)"
        )
    elif neuer_tagesstand > _MAX_TAG_NORMAL:
        warnungen.append(
            f"Tageseinsatz ueberschreitet 8h inkl. Fahrt "
            f"(Prognose {neuer_tagesstand:.1f}h)"
        )

    # ArbZG §4 Pausenpflicht
    if neuer_tagesstand >= 9.0:
        warnungen.append("ArbZG §4: Pausenpflicht 45min ab 9h Arbeitszeit")
    elif neuer_tagesstand >= 6.0:
        warnungen.append("ArbZG §4: Pausenpflicht 30min ab 6h Arbeitszeit")

    # Uebernachtungsregel: > 3h einfache Fahrzeit → Uebernachtung noetig
    if fz_std > _UEBERNACHTUNGS_FAHRZEIT_SCHWELLE_STD:
        if status.uebernachtungen_diese_woche >= MAX_UEBERNACHTUNGEN_PRO_WOCHE:
            warnungen.append(
                f"Uebernachtung noetig (Fahrzeit {fz_std:.1f}h > {_UEBERNACHTUNGS_FAHRZEIT_SCHWELLE_STD}h), "
                f"aber max. {MAX_UEBERNACHTUNGEN_PRO_WOCHE} pro Woche bereits erreicht "
                f"({status.uebernachtungen_diese_woche} geplant) "
                f"→ anderen Techniker waehlen oder Auftrag verschieben"
            )
        else:
            warnungen.append(
                f"Uebernachtung noetig (Fahrzeit {fz_std:.1f}h einfach > {_UEBERNACHTUNGS_FAHRZEIT_SCHWELLE_STD}h, "
                f"+{_UEBERNACHTUNGS_KOSTEN_EUR:.0f} EUR Kosten)"
            )

    return False, warnungen


# ---------------------------------------------------------------------------
# Oeffentliche API
# ---------------------------------------------------------------------------

def berechne_empfehlung(
    auftrag_typ: str,
    produkt_familie: str,
    klinik_id: str,
    einsatz_datetime: Optional[datetime] = None,
    einsatz_dauer_std: float = 4.0,
    tages_status: Optional[dict[str, TagesStatus]] = None,
    abwesenheiten: Optional[list[Abwesenheit]] = None,
) -> list[EmpfehlungErgebnis]:
    """Gibt die Top-3 Techniker fuer einen Serviceauftrag zurueck, nach Score gerankt.

    Args:
        auftrag_typ:       "STK", "PM" oder "Repair"
        produkt_familie:   Produktfamilien-ID (z.B. "Hugo", "Beatmung", "Elektrochirurgie")
        klinik_id:         ID aus kliniken.csv (z.B. "K001")
        einsatz_datetime:  Geplanter Einsatzzeitpunkt. Default: naechster Werktag 08:00 Uhr.
        einsatz_dauer_std: Erwartete Einsatzdauer in Stunden (ohne Fahrtzeit). Default: 4.0h.
        tages_status:      Dict techniker_id -> TagesStatus. Default: alle Techniker voll verfuegbar.

    Returns:
        Liste mit bis zu 3 EmpfehlungErgebnis-Objekten, absteigend nach Score sortiert.
        Kann leer sein wenn keine qualifizierten, verfuegbaren Techniker gefunden werden.

    Raises:
        ValueError: Wenn klinik_id unbekannt oder Koordinaten fehlen.
    """
    if einsatz_datetime is None:
        einsatz_datetime = _naechster_werktag()
    if tages_status is None:
        tages_status = {}

    # Stammdaten laden
    tech_df = _lade_techniker_df()
    matrix_df = _lade_matrix_df()
    klinik = _lade_klinik_row(klinik_id)
    klinik_lat, klinik_lon = _klinik_gps(klinik)

    # Trainingsmatrix als schnelles Lookup: techniker_id -> {produktfamilie: level_str}
    matrix: dict[str, dict[str, str]] = {}
    for _, row in matrix_df.iterrows():
        tid = row["techniker_id"]
        if tid not in matrix:
            matrix[tid] = {}
        matrix[tid][row["produktfamilie"]] = row["level"]

    kandidaten: list[EmpfehlungErgebnis] = []

    # Einsatzdatum fuer Abwesenheitspruefung
    _einsatz_datum = einsatz_datetime.date() if einsatz_datetime is not None else None

    for _, tech in tech_df.iterrows():
        tid = str(tech["techniker_id"])
        if str(tech.get("status", "aktiv")).lower() != "aktiv":
            continue

        # --- Abwesenheitspruefung: abwesende Techniker ausschliessen ---
        if abwesenheiten and _einsatz_datum is not None:
            if ist_abwesend(tid, _einsatz_datum, abwesenheiten):
                continue  # Score 0 → aus Top-3 ausgeschlossen

        # --- Qualifikationspruefung ---
        tech_qualifikationen = matrix.get(tid, {})
        level_str = tech_qualifikationen.get(produkt_familie)
        ist_hugo_ka = tid in _HUGO_KEY_ACCOUNT_IDS
        ist_hugo_auftrag = produkt_familie.lower() == "hugo"

        if level_str is None:
            # Keine Qualifikation fuer diese Produktfamilie
            continue

        # Hugo-Regel: ausschliesslich L3
        if ist_hugo_auftrag and level_str != "L3":
            warnings.warn(
                f"{tid}: Hugo-Einsatz erfordert L3 – Techniker hat {level_str}, wird ausgeschlossen.",
                UserWarning,
                stacklevel=2,
            )
            continue

        # L1 = In Ausbildung: nicht selbststaendig einsetzbar (ausser als absolute Ausnahme)
        if level_str == "L1":
            continue

        # Mindest-Level-Pruefung (beruecksichtigt Cluster + Auftragstyp)
        mindest = mindest_level_fuer(produkt_familie, auftrag_typ)
        level_num = int(level_str[1]) if level_str.startswith("L") else 0

        if level_num < mindest:
            warnings.warn(
                f"{tid}: {produkt_familie} {auftrag_typ} erfordert L{mindest} – "
                f"Techniker hat {level_str}, wird ausgeschlossen.",
                UserWarning,
                stacklevel=2,
            )
            continue

        # Kompetenz-Score: L2 vollwertig (100) wenn Mindest-Level L2 und Tech hat L2
        if level_str == "L2" and mindest <= 2:
            kompetenz_score = _LEVEL_SCORE["L3"]  # 100.0
        else:
            kompetenz_score = _LEVEL_SCORE.get(level_str, 0.0)

        # --- Distanzberechnung ---
        try:
            tech_lat = float(tech["lat"])
            tech_lon = float(tech["lon"])
        except (ValueError, KeyError):
            warnings.warn(f"{tid}: Keine GPS-Koordinaten in techniker.csv – Techniker uebersprungen.")
            continue

        distanz_km = _haversine_km(tech_lat, tech_lon, klinik_lat, klinik_lon)

        # --- Arbeitszeitpruefung ---
        status = tages_status.get(tid, TagesStatus())
        ausgeschlossen, warnungen = _pruefe_arbeitszeit(
            tid, auftrag_typ, status, einsatz_dauer_std, einsatz_datetime, distanz_km
        )
        if ausgeschlossen:
            for msg in warnungen:
                warnings.warn(f"{tid} ausgeschlossen: {msg}", UserWarning, stacklevel=2)
            continue

        # Hugo Key Account: reduzierte Kapazitaet (20% Reserve)
        ziel_std = _HUGO_WOCHE_ZIEL_STD if ist_hugo_ka else _WOCHE_ZIEL_STD
        auslastungsgrad = status.wochenstunden_aktuell / ziel_std
        auslastung_score = max(0.0, (1.0 - auslastungsgrad) * 100.0)

        # Hugo Key Account Warnungen
        if ist_hugo_ka and not ist_hugo_auftrag:
            ka_auslastung_pct = (status.wochenstunden_aktuell / ziel_std) * 100
            if ka_auslastung_pct >= 80:
                warnungen.append(
                    f"Hugo Key Account: Auslastung {ka_auslastung_pct:.0f}% "
                    f"({status.wochenstunden_aktuell:.1f}h / {ziel_std}h) – "
                    f"Hugo-Kapazitaet knapp, STK/PM-Einsatz pruefen"
                )

        # Hugo-Einsatz: Ganztag (8h), Freitag gesperrt, hoechste Prioritaet
        if ist_hugo_auftrag:
            kompetenz_score = 100.0  # hoechste Prioritaet

        kandidaten.append(
            EmpfehlungErgebnis(
                techniker_id=tid,
                score=0.0,  # wird nach Normalisierung gesetzt
                kompetenz_score=kompetenz_score,
                fahrzeit_score=0.0,  # wird nach Normalisierung gesetzt
                auslastung_score=auslastung_score,
                distanz_km=distanz_km,
                level=level_str,
                warnungen=warnungen,
            )
        )

    if not kandidaten:
        return []

    # --- Fahrzeit-Score normalisieren (naeher = besser) ---
    max_distanz = max(k.distanz_km for k in kandidaten)
    for k in kandidaten:
        if max_distanz > 0:
            k.fahrzeit_score = (1.0 - k.distanz_km / max_distanz) * 100.0
        else:
            k.fahrzeit_score = 100.0

    # --- Gesamtscore berechnen ---
    for k in kandidaten:
        k.score = (
            k.kompetenz_score * _W_KOMPETENZ
            + k.fahrzeit_score * _W_FAHRZEIT
            + k.auslastung_score * _W_AUSLASTUNG
        )

    kandidaten.sort(key=lambda x: x.score, reverse=True)
    return kandidaten[:3]


def _naechster_werktag() -> datetime:
    """Gibt den naechsten Werktag (Mo-Do) um 08:00 Uhr zurueck."""
    from datetime import timedelta
    basis = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
    for tage in range(1, 8):
        kandidat = basis + timedelta(days=tage)
        if kandidat.weekday() <= 3:  # Mo=0 bis Do=3
            return kandidat
    return basis + timedelta(days=1)  # Fallback
