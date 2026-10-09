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

import re
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


def _norm_ort(s: str | None) -> str:
    t = str(s or "").casefold()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def ort_passt(ort: str | None, ortsname: str | None) -> bool:
    """Tolerant: Gross-/Kleinschreibung, Umlaute (ae/ä), Teilstring und Stadtteile
    ('Leipzig, Stadt' ~ 'Leipzig', 'Berlin Mitte' ~ 'Berlin')."""
    a, b = _norm_ort(ort), _norm_ort(ortsname)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    ta = {t for t in a.split() if len(t) >= 4}
    tb = {t for t in b.split() if len(t) >= 4}
    return any(x in y or y in x for x in ta for y in tb)


@lru_cache(maxsize=None)
def _pgeocode_ortsname(plz5: str) -> str:
    name = _NOMI.query_postal_code(plz5).place_name
    return name if isinstance(name, str) else ""


def normalisiere_plz(plz: str | None, ort: str | None = None) -> str | None:
    """5-stellige deutsche PLZ oder None.

    5 Ziffern: unveraendert. 4 Ziffern: nur wenn der aufgefuellte Wert (zfill(5)) einen
    Ortsnamen hat, der zur City-Spalte passt (deutsche PLZ mit fuehrender 0 kommen aus
    Excel teils als Zahl ohne Null); sonst None (Ausland, z.B. AT/CH, oder unklar).
    Ohne Ort bleibt eine 4-stellige PLZ None. Mehr als 5 Stellen, Buchstaben oder
    weniger als 4 Stellen -> None."""
    p = (plz or "").strip()
    if not p.isdigit():
        return None
    if len(p) == 5:
        return p
    if len(p) == 4 and ort and str(ort).strip():
        p5 = p.zfill(5)
        if ort_passt(ort, _pgeocode_ortsname(p5)):
            return p5
    return None


def hole_koordinaten(plz: str | None, ort: str | None = None) -> tuple[float, float] | None:
    """Loest eine deutsche PLZ zu (lat, lon) auf, oder None wenn nicht auflösbar.

    4-stellige PLZ werden nur mit passendem Ort aufgefuellt (siehe normalisiere_plz);
    AT/CH-PLZ ergeben so None statt einer ostdeutschen 0xxxx-PLZ.

    Fallback-Kette:
        1. _KLINIK_COORDS -- kuratierte, ggf. praezisere Eintraege (Vorrang)
        2. pgeocode -- GeoNames-Datenbank, deckt praktisch jede echte PLZ ab
        3. None -- ungueltige/leere PLZ oder unbekannt in beiden Quellen
    """
    plz_norm = normalisiere_plz(plz, ort)
    if plz_norm is None:
        return None

    if plz_norm in _KLINIK_COORDS:
        return _KLINIK_COORDS[plz_norm]

    return _pgeocode_koordinaten(plz_norm)
