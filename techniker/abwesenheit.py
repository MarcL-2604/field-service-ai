"""Abwesenheitsverwaltung fuer Servicetechniker.

Unterstuetzte Typen: Urlaub, Krank, Fortbildung, Sonstiges

Oeffentliche API:
    lade_abwesenheiten(daten)                                     -> list[Abwesenheit]
    ist_abwesend(techniker_id, datum, abwesenheiten)              -> bool
    filtere_verfuegbare_techniker(techniker, datum, abwesenheiten) -> list
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


GUELTIGE_TYPEN: frozenset[str] = frozenset(
    {"Urlaub", "Krank", "Fortbildung", "Sonstiges"}
)


@dataclass
class Abwesenheit:
    """Abwesenheitszeitraum eines Technikers."""
    techniker_id: str
    von: date
    bis: date
    typ: str   # Urlaub / Krank / Fortbildung / Sonstiges

    def __post_init__(self) -> None:
        if self.von > self.bis:
            raise ValueError(
                f"Abwesenheit '{self.typ}': von ({self.von}) liegt nach bis ({self.bis})"
            )


def lade_abwesenheiten(daten: list[dict[str, Any]]) -> list[Abwesenheit]:
    """Parst eine Liste von Dicts in Abwesenheit-Objekte.

    Erwartet je Dict die Schluessel: techniker_id, von, bis, typ.
    'von'/'bis' koennen date-Objekte oder ISO-8601-Strings sein.

    Returns:
        Liste von Abwesenheit-Objekten.

    Raises:
        KeyError:   Wenn ein Pflichtschluessel fehlt.
        ValueError: Wenn von > bis oder typ unbekannt.
    """
    result: list[Abwesenheit] = []
    for eintrag in daten:
        von = eintrag["von"]
        bis = eintrag["bis"]
        if not isinstance(von, date):
            von = date.fromisoformat(str(von))
        if not isinstance(bis, date):
            bis = date.fromisoformat(str(bis))
        typ = str(eintrag.get("typ", "Sonstiges"))
        result.append(Abwesenheit(
            techniker_id=str(eintrag["techniker_id"]),
            von=von,
            bis=bis,
            typ=typ,
        ))
    return result


def ist_abwesend(
    techniker_id: str,
    datum: date,
    abwesenheiten: list[Abwesenheit],
) -> bool:
    """Prueft ob ein Techniker an einem bestimmten Datum abwesend ist.

    Inklusive Grenztage: von <= datum <= bis.

    Returns:
        True wenn abwesend, False wenn verfuegbar.
    """
    return any(
        a.techniker_id == techniker_id and a.von <= datum <= a.bis
        for a in abwesenheiten
    )


def filtere_verfuegbare_techniker(
    techniker: list[Any],
    datum: date,
    abwesenheiten: list[Abwesenheit],
) -> list[Any]:
    """Filtert abwesende Techniker aus der Liste heraus.

    'techniker' kann eine Liste von Strings (IDs) oder Objekten mit
    einem 'techniker_id'-Attribut sein.

    Returns:
        Bereinigte Liste ohne abwesende Techniker.
    """
    verfuegbar: list[Any] = []
    for t in techniker:
        tid: str = t if isinstance(t, str) else str(getattr(t, "techniker_id", t))
        if not ist_abwesend(tid, datum, abwesenheiten):
            verfuegbar.append(t)
    return verfuegbar
