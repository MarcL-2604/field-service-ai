"""PLZ-Koordinaten-Lookup mit breiter Abdeckung ueber pgeocode.

techniker.scoring._KLINIK_COORDS ist eine kleine, manuell kuratierte Liste
(~90 Eintraege) und deckt nur einen Bruchteil der in echten SMax-Auftraegen
vorkommenden Postleitzahlen ab. Dieses Modul ergaenzt sie um pgeocode
(https://github.com/symerio/pgeocode), das die GeoNames-Postleitzahlendatenbank
fuer Deutschland (~10.800 PLZ) offline bereitstellt: pgeocode laedt die
Datenbank beim ersten Zugriff einmalig herunter und cached sie lokal unter
~/.cache/pgeocode/DE.txt -- danach sind keine weiteren Netzwerkzugriffe noetig.

Oeffentliche API:
    hole_koordinaten(plz: str) -> tuple[float, float] | None

Fallback-Kette: _KLINIK_COORDS (kuratiert, praeziser) -> pgeocode (GeoNames,
breite Abdeckung) -> None.
"""

from __future__ import annotations

from functools import lru_cache

import pgeocode

from techniker.scoring import _KLINIK_COORDS

_NOMI = pgeocode.Nominatim("de")


@lru_cache(maxsize=None)
def _pgeocode_koordinaten(plz: str) -> tuple[float, float] | None:
    """pgeocode-Abfrage mit Cache (dieselbe PLZ kann in vielen Auftraegen vorkommen)."""
    row = _NOMI.query_postal_code(plz)
    lat, lon = row.latitude, row.longitude
    try:
        if lat != lat or lon != lon:  # NaN-Check ohne zusaetzliche Abhaengigkeit
            return None
    except TypeError:
        return None
    return (float(lat), float(lon))


def hole_koordinaten(plz: str | None) -> tuple[float, float] | None:
    """Loest eine deutsche PLZ zu (lat, lon) auf, oder None wenn nicht auflösbar.

    Fallback-Kette:
        1. _KLINIK_COORDS -- kuratierte, ggf. praezisere Eintraege (Vorrang)
        2. pgeocode -- GeoNames-Datenbank, deckt praktisch jede echte PLZ ab
        3. None -- ungueltige/leere PLZ oder unbekannt in beiden Quellen
    """
    plz_norm = (plz or "").strip()
    if not plz_norm.isdigit() or len(plz_norm) > 5:
        return None
    plz_norm = plz_norm.zfill(5)

    if plz_norm in _KLINIK_COORDS:
        return _KLINIK_COORDS[plz_norm]

    return _pgeocode_koordinaten(plz_norm)
