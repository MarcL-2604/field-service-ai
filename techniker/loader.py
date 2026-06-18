"""Laedt Technikerprofile und Trainingsmatrizen aus SMax-Exporten (CSV/Excel)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .models import Qualifikationslevel, Techniker, Trainingsmatrix


# Erwartete Spaltennamen im SMax-Export (Techniker-Stammdaten)
_SMAX_COLS_TECHNIKER = {
    "smax_id": "Resource_ID",
    "name": "Resource_Name",
    "email": "Email",
    "heimatort_plz": "Home_Zip",
    "einsatzgebiet_plz": "Territory_Zips",  # Semikolon-getrennte PLZ-Praefixe
}

# Erwartete Spaltennamen im SMax-Export (Trainingsmatrix)
# Jede Geraeteklasse ist eine eigene Spalte; Werte: 0-4 gemaess Qualifikationslevel
_SMAX_COL_RESOURCE_ID = "Resource_ID"


def lade_techniker_aus_csv(pfad: Path) -> list[Techniker]:
    """Laedt Techniker-Stammdaten aus einer SMax-CSV-Exportdatei."""
    df = pd.read_csv(pfad, dtype=str).fillna("")
    return [_zeile_zu_techniker(row) for _, row in df.iterrows()]


def lade_techniker_aus_excel(pfad: Path, blatt: str = "Techniker") -> list[Techniker]:
    """Laedt Techniker-Stammdaten aus einem Excel-SMax-Export."""
    df = pd.read_excel(pfad, sheet_name=blatt, dtype=str).fillna("")
    return [_zeile_zu_techniker(row) for _, row in df.iterrows()]


def lade_trainingsmatrix_aus_excel(
    pfad: Path,
    techniker: list[Techniker],
    blatt: str = "Trainingsmatrix",
) -> list[Techniker]:
    """Liest die Trainingsmatrix aus einem separaten Excel-Blatt und reichert
    die uebergebenen Techniker-Objekte damit an.

    Erwartet: Zeilen = Techniker (Resource_ID), Spalten = Geraeteklassen-IDs.
    Rueckgabe: dieselbe Liste, Trainingsmatrix in-place aktualisiert.
    """
    df = pd.read_excel(pfad, sheet_name=blatt, index_col=_SMAX_COL_RESOURCE_ID, dtype=str).fillna("0")

    techniker_index = {t.smax_id: t for t in techniker}
    geraeteklassen = [col for col in df.columns]

    for smax_id, row in df.iterrows():
        if smax_id not in techniker_index:
            continue
        qualifikationen: dict[str, Qualifikationslevel] = {}
        for gk_id in geraeteklassen:
            try:
                level = Qualifikationslevel(int(row[gk_id]))
            except (ValueError, KeyError):
                level = Qualifikationslevel.KEINE
            if level != Qualifikationslevel.KEINE:
                qualifikationen[str(gk_id)] = level
        techniker_index[smax_id].trainingsmatrix = Trainingsmatrix(qualifikationen=qualifikationen)

    return techniker


def _zeile_zu_techniker(row: pd.Series) -> Techniker:
    col = _SMAX_COLS_TECHNIKER
    plz_roh = row.get(col["einsatzgebiet_plz"], "")
    einsatzgebiet = [p.strip() for p in plz_roh.split(";") if p.strip()] if plz_roh else []

    return Techniker(
        smax_id=row[col["smax_id"]],
        name=row[col["name"]],
        email=row.get(col["email"]) or None,
        heimatort_plz=row.get(col["heimatort_plz"]) or None,
        einsatzgebiet_plz=einsatzgebiet,
    )
