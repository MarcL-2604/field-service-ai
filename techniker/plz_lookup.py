"""PLZ-Lookup fuer Techniker-Wohnorte aus SMax Sheet 5_Wohnorte.

Das Sheet enthaelt nur Stadt, kein PLZ-Feld — dieser Lookup ergaenzt
die fehlenden PLZ-Werte fuer die Gebietsplanung.
"""

from __future__ import annotations

# Stadt → PLZ Mapping
STADT_ZU_PLZ: dict[str, str] = {
    "Obertshausen":      "63179",
    "Neubiberg":         "85579",
    "Wehingen":          "78564",
    "Weimar":            "99423",
    "Erlangen":          "91052",
    "Oberhausen":        "46045",
    "Schenefeld":        "22869",
    "Hennef":            "53773",
    "Hamburg":           "20095",
    "Malschwitz":        "02694",
    "Essen":             "45127",
    "Balingen":          "72336",
    "Siegburg":          "53721",
    "Gangelt":           "52538",
    "Saarbrücken":       "66111",
    "Frankfurt am Main": "60311",
    "Meckenheim":        "53340",
    "Darmstadt":         "64283",
    "Waldachtal":        "72178",
    "Berlin":            "10115",
    "Magdeburg":         "39104",
    "Brakel":            "33034",
    "Bad Aibling":       "83043",
    "Wildenberg":        "93359",   # Ortsteil von Neustadt a.d. Donau, Bayern
    "Linden":            "30449",   # Linden bei Hannover (Marco Cloos, Markus Niski, Matthias Werner)
}

# Keine unsicheren Eintraege mehr — alle PLZ bestaetigt
PLZ_UNSICHER: frozenset[str] = frozenset()

# Case-insensitiver Index (lowercase-Key → original-Key)
_LOOKUP_CI: dict[str, str] = {k.lower(): k for k in STADT_ZU_PLZ}


def plz_fuer_stadt(stadt: str) -> tuple[str | None, bool]:
    """Gibt (plz, ist_unsicher) zurueck.

    Gross-/Kleinschreibung wird ignoriert (MALSCHWITZ == Malschwitz).
    ist_unsicher=True wenn PLZ manuell zu bestaetigen ist.
    Gibt (None, False) wenn Stadt unbekannt.
    """
    # Exakter Treffer zuerst, dann case-insensitiv
    original_key = _LOOKUP_CI.get(stadt.lower())
    if original_key is None:
        return None, False
    plz = STADT_ZU_PLZ[original_key]
    return plz, original_key in PLZ_UNSICHER
