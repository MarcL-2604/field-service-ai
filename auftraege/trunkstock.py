"""Trunkstock-Verwaltung: Fahrzeugbestand pro Techniker.

Prüft Messmittel-Verfügbarkeit, Kalibrierungsfristen und
stellt Auftrags-spezifische Bestandslisten zusammen.

Ersatzteil-Verfuegbarkeit fuer Repair-Auftraege:
    pruefe_ersatzteil_verfuegbarkeit(techniker_id, produktfamilie, fehler)
    → ErsatzteilStatus mit Lieferzeit-Schaetzung
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from pathlib import Path
from typing import List, Optional

import pandas as pd

from config import (
    ERSATZTEIL_SOFORT_TAGE,
    ERSATZTEIL_LAGER_TAGE,
    ERSATZTEIL_BESTELL_TAGE,
)

_DATA_DIR = Path(__file__).parent.parent / "daten"

# ---------------------------------------------------------------------------
# Pflicht-Messmittel je Produktfamilie (Artikel-Nummern)
# ---------------------------------------------------------------------------
_MESSMITTEL_PRO_FAMILIE: dict[str, list[str]] = {
    "Hugo":                   ["MM-HUGO-001", "MM-HUGO-002"],
    "Beatmung":               ["MM-BEAT-001", "MM-BEAT-002"],
    "Neuromonitoring":        ["MM-NEURO-001", "MM-NEURO-002"],
    "Elektrochirurgie":       ["MM-ECHI-001", "MM-ECHI-002"],
    "Kardiovaskulaer":        ["MM-KARD-001", "MM-KARD-002"],
    "Kardiovaskulaer_Ablation": ["MM-KABL-001", "MM-KABL-002"],
    "Wirbelsaeule":           ["MM-WIRB-001"],
    "Navigation":             ["MM-NAVI-001", "MM-NAVI-002"],
    "Endoskopie":             ["MM-ENDO-001", "MM-ENDO-002"],
    "Neurophysiologie":       ["MM-NPHY-001", "MM-NPHY-002"],
    "Gastroenterologie":      ["MM-GAST-001"],
    "Capnografie":            ["MM-CAPN-001"],
    "Energie":                ["MM-ENER-001"],
}

# Welche Kategorien sind je Auftragstyp Pflicht?
_KATEGORIEN_PRO_AUFTRAGSTYP: dict[str, list[str]] = {
    "STK":    ["MESSMITTEL"],
    "PM":     ["MESSMITTEL", "VERBRAUCHSMATERIAL"],
    "Repair": ["MESSMITTEL", "WERKZEUG", "VERBRAUCHSMATERIAL"],
}


# ---------------------------------------------------------------------------
# Daten laden
# ---------------------------------------------------------------------------
def _lade_trunkstock() -> pd.DataFrame:
    return pd.read_csv(
        _DATA_DIR / "trunkstock.csv", comment="#", dtype=str,
    ).fillna("")


# ---------------------------------------------------------------------------
# 1) Messmittel verfügbar?
# ---------------------------------------------------------------------------
def messmittel_verfuegbar(techniker_id: str, produktfamilie: str) -> bool:
    """True wenn der Techniker alle Pflicht-Messmittel für die Familie hat."""
    pflicht = _MESSMITTEL_PRO_FAMILIE.get(produktfamilie)
    if pflicht is None:
        return False

    df = _lade_trunkstock()
    bestand = set(
        df.loc[
            (df["techniker_id"] == techniker_id)
            & (df["kategorie"] == "MESSMITTEL"),
            "artikel_nr",
        ]
    )
    return all(art in bestand for art in pflicht)


# ---------------------------------------------------------------------------
# 2) Kalibrierung prüfen
# ---------------------------------------------------------------------------
def kalibrierung_pruefen(
    techniker_id: str, *, stichtag: date | None = None, tage: int = 30,
) -> List[dict]:
    """Messmittel die innerhalb von *tage* Tagen ab *stichtag* ablaufen."""
    if stichtag is None:
        stichtag = date.today()
    grenze = stichtag + timedelta(days=tage)

    df = _lade_trunkstock()
    mm = df.loc[
        (df["techniker_id"] == techniker_id)
        & (df["kategorie"] == "MESSMITTEL")
        & (df["kalibriert_bis"] != "")
    ].copy()

    mm["_kb"] = pd.to_datetime(mm["kalibriert_bis"]).dt.date
    faellig = mm.loc[(mm["_kb"] >= stichtag) & (mm["_kb"] <= grenze)]

    return [
        {
            "artikel_nr": r["artikel_nr"],
            "bezeichnung": r["bezeichnung"],
            "kalibriert_bis": r["kalibriert_bis"],
            "tage_verbleibend": (r["_kb"] - stichtag).days,
        }
        for _, r in faellig.iterrows()
    ]


# ---------------------------------------------------------------------------
# 3) Trunkstock für Auftrag
# ---------------------------------------------------------------------------
def trunkstock_fuer_auftrag(
    techniker_id: str, auftragstyp: str, produktfamilie: str,
) -> dict:
    """Gibt benötigte und vorhandene Artikel für einen Auftrag zurück.

    Returns dict mit Schlüsseln:
        techniker_id, auftragstyp, produktfamilie,
        messmittel, werkzeug, verbrauchsmaterial, dokumentation,
        vollstaendig (bool), fehlende_messmittel (list)
    """
    df = _lade_trunkstock()
    bestand = df.loc[df["techniker_id"] == techniker_id]

    def _artikel_liste(kategorie: str) -> list[dict]:
        teil = bestand.loc[bestand["kategorie"] == kategorie]
        return [
            {
                "artikel_nr": r["artikel_nr"],
                "bezeichnung": r["bezeichnung"],
                "menge": r["menge"],
                "einheit": r["einheit"],
            }
            for _, r in teil.iterrows()
        ]

    # Pflicht-Messmittel für die Produktfamilie
    pflicht = _MESSMITTEL_PRO_FAMILIE.get(produktfamilie, [])
    vorhandene_mm = set(
        bestand.loc[bestand["kategorie"] == "MESSMITTEL", "artikel_nr"]
    )
    fehlend = [art for art in pflicht if art not in vorhandene_mm]

    # Welche Kategorien braucht dieser Auftragstyp?
    pflicht_kat = _KATEGORIEN_PRO_AUFTRAGSTYP.get(auftragstyp, ["MESSMITTEL"])

    ergebnis: dict = {
        "techniker_id": techniker_id,
        "auftragstyp": auftragstyp,
        "produktfamilie": produktfamilie,
        "messmittel": _artikel_liste("MESSMITTEL"),
        "werkzeug": _artikel_liste("WERKZEUG") if "WERKZEUG" in pflicht_kat else [],
        "verbrauchsmaterial": (
            _artikel_liste("VERBRAUCHSMATERIAL")
            if "VERBRAUCHSMATERIAL" in pflicht_kat
            else []
        ),
        "dokumentation": _artikel_liste("DOKUMENTATION"),
        "vollstaendig": len(fehlend) == 0,
        "fehlende_messmittel": fehlend,
    }
    return ergebnis


# ---------------------------------------------------------------------------
# 4) Ersatzteil-Verfügbarkeit für Repair-Aufträge
# ---------------------------------------------------------------------------

class ErsatzteilVerfuegbarkeit(str, Enum):
    """Verfuegbarkeits-Status eines Ersatzteils."""
    SOFORT = "Sofort"        # Teil im Fahrzeug → Einsatz in 1-2 Tagen
    LAGER = "Lager"          # Teil im Zentrallager → 1-3 Tage Lieferzeit
    BESTELLEN = "Bestellen"  # Teil muss bestellt werden → 3-10 Tage
    UNBEKANNT = "Unbekannt"  # Fehler unklar → Diagnose vor Ort noetig


# Lieferzeit-Schaetzung je Verfuegbarkeit (aus config.py)
_LIEFERZEIT_TAGE: dict[ErsatzteilVerfuegbarkeit, tuple[int, int]] = {
    ErsatzteilVerfuegbarkeit.SOFORT:    (1, ERSATZTEIL_SOFORT_TAGE),
    ErsatzteilVerfuegbarkeit.LAGER:     (1, ERSATZTEIL_LAGER_TAGE),
    ErsatzteilVerfuegbarkeit.BESTELLEN: (3, ERSATZTEIL_BESTELL_TAGE),
    ErsatzteilVerfuegbarkeit.UNBEKANNT: (1, 5),  # Diagnose zuerst
}

# Typische Ersatzteile je Produktfamilie (Artikel-Nr-Praefixe fuer Demo)
_REPAIR_TEILE_PRO_FAMILIE: dict[str, list[str]] = {
    "Hugo":                   ["ET-HUGO-001", "ET-HUGO-002", "ET-HUGO-003"],
    "Beatmung":               ["ET-BEAT-001", "ET-BEAT-002"],
    "Neuromonitoring":        ["ET-NEURO-001", "ET-NEURO-002"],
    "Elektrochirurgie":       ["ET-ECHI-001", "ET-ECHI-002", "ET-ECHI-003"],
    "Kardiovaskulaer":        ["ET-KARD-001"],
    "Kardiovaskulaer_Ablation": ["ET-KABL-001", "ET-KABL-002"],
    "Wirbelsaeule":           ["ET-WIRB-001", "ET-WIRB-002"],
    "Navigation":             ["ET-NAVI-001", "ET-NAVI-002"],
    "Endoskopie":             ["ET-ENDO-001"],
    "Neurophysiologie":       ["ET-NPHY-001"],
    "Gastroenterologie":      ["ET-GAST-001"],
    "Capnografie":            ["ET-CAPN-001"],
    "Energie":                ["ET-ENER-001", "ET-ENER-002"],
}


@dataclass
class ErsatzteilStatus:
    """Ergebnis der Ersatzteil-Verfuegbarkeitspruefung."""
    verfuegbarkeit: ErsatzteilVerfuegbarkeit
    lieferzeit_min_tage: int
    lieferzeit_max_tage: int
    benoetigte_teile: list[str]       # Artikel-Nummern
    im_fahrzeug: list[str]            # Teile die im Trunkstock sind
    fehlende_teile: list[str]         # Teile die nachbestellt werden muessen
    hinweis: str


def pruefe_ersatzteil_verfuegbarkeit(
    techniker_id: str,
    produktfamilie: str,
    fehler_beschreibung: Optional[str] = None,
) -> ErsatzteilStatus:
    """Prueft ob Ersatzteile fuer eine Repair verfuegbar sind.

    Pruefkaskade:
        1. Trunkstock: Teil im Fahrzeug? → SOFORT (1-2 Tage)
        2. Zentrallager (Demo: Werkzeug-Bestand als Proxy) → LAGER (1-3 Tage)
        3. Keins vorhanden → BESTELLEN (3-10 Tage)
        4. Fehler unklar → UNBEKANNT (Diagnose vor Ort)

    Args:
        techniker_id:       Techniker-ID fuer Fahrzeugbestand-Lookup.
        produktfamilie:     Produktfamilie des defekten Geraets.
        fehler_beschreibung: Fehlerbeschreibung (optional, fuer zukuenftige
                            Fehler→Ersatzteil Zuordnung).

    Returns:
        ErsatzteilStatus mit Verfuegbarkeit, Lieferzeit und Teile-Details.
    """
    benoetigte = _REPAIR_TEILE_PRO_FAMILIE.get(produktfamilie, [])

    # Fehler unklar → Diagnose noetig
    if not benoetigte or (fehler_beschreibung and "unklar" in fehler_beschreibung.lower()):
        lz = _LIEFERZEIT_TAGE[ErsatzteilVerfuegbarkeit.UNBEKANNT]
        return ErsatzteilStatus(
            verfuegbarkeit=ErsatzteilVerfuegbarkeit.UNBEKANNT,
            lieferzeit_min_tage=lz[0],
            lieferzeit_max_tage=lz[1],
            benoetigte_teile=benoetigte,
            im_fahrzeug=[],
            fehlende_teile=benoetigte,
            hinweis="Fehlerbild unklar — Diagnose vor Ort noetig, Ersatzteile danach bestellen",
        )

    # Trunkstock laden und pruefen
    df = _lade_trunkstock()
    bestand = set(
        df.loc[df["techniker_id"] == techniker_id, "artikel_nr"]
    )

    im_fahrzeug = [t for t in benoetigte if t in bestand]
    fehlend = [t for t in benoetigte if t not in bestand]

    if not fehlend:
        # Alles im Fahrzeug
        lz = _LIEFERZEIT_TAGE[ErsatzteilVerfuegbarkeit.SOFORT]
        return ErsatzteilStatus(
            verfuegbarkeit=ErsatzteilVerfuegbarkeit.SOFORT,
            lieferzeit_min_tage=lz[0],
            lieferzeit_max_tage=lz[1],
            benoetigte_teile=benoetigte,
            im_fahrzeug=im_fahrzeug,
            fehlende_teile=[],
            hinweis=f"Alle {len(benoetigte)} Ersatzteile im Fahrzeug — Einsatz in 1-2 Tagen moeglich",
        )

    # Pruefen ob fehlende Teile im Lager sind (Demo: pruefen ob andere Techniker sie haben)
    alle_artikel = set(df["artikel_nr"])
    muss_bestellen = [t for t in fehlend if t not in alle_artikel]

    if not muss_bestellen:
        # Fehlende Teile im Lager verfuegbar
        lz = _LIEFERZEIT_TAGE[ErsatzteilVerfuegbarkeit.LAGER]
        return ErsatzteilStatus(
            verfuegbarkeit=ErsatzteilVerfuegbarkeit.LAGER,
            lieferzeit_min_tage=lz[0],
            lieferzeit_max_tage=lz[1],
            benoetigte_teile=benoetigte,
            im_fahrzeug=im_fahrzeug,
            fehlende_teile=fehlend,
            hinweis=f"{len(fehlend)} Teil(e) aus Zentrallager anfordern — Lieferzeit 1-3 Tage",
        )

    # Teil muss extern bestellt werden
    lz = _LIEFERZEIT_TAGE[ErsatzteilVerfuegbarkeit.BESTELLEN]
    return ErsatzteilStatus(
        verfuegbarkeit=ErsatzteilVerfuegbarkeit.BESTELLEN,
        lieferzeit_min_tage=lz[0],
        lieferzeit_max_tage=lz[1],
        benoetigte_teile=benoetigte,
        im_fahrzeug=im_fahrzeug,
        fehlende_teile=fehlend,
        hinweis=f"{len(muss_bestellen)} Teil(e) extern bestellen — Lieferzeit 3-10 Tage",
    )
