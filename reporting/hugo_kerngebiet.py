"""Hugo-Kerngebiet: Alltags-Kleingebiet um den Wohnort des Hugo-Technikers.

WICHTIG (fachlicher Hintergrund, ersetzt das fruehere "Hugo-Zusatzgebiet"):
Hugo-Systeme stehen an wenigen, teils weit vom Techniker-Wohnort entfernten
Standorten (z.B. Ulm/Mannheim liegen ~2,5h von Balingen). Diese Entfernung
zum Hugo-SYSTEM ist normal und wird NICHT begrenzt.

Begrenzt wird stattdessen das ALLTAGS-Gebiet (Small Capital, PM-only) um den
WOHNORT des Hugo-Technikers: ein kleines/kompaktes Kerngebiet (Standard:
config.HUGO_KERNGEBIET_MAX_FAHRZEIT_MIN Minuten Fahrzeit), damit der
Techniker taeglich nach Hause zurueckkehrt (reine Tagestouren, keine
Uebernachtung fuers Alltagsgeschaeft) und bei einer Hugo-Stoerungsmeldung
sein Equipment bereits zuhause hat und sofort am Folgetag zum Hugo-Einsatz
aufbrechen kann. Das kleine Kerngebiet ist also eine Verfuegbarkeits-Garantie
fuer schnelle Hugo-Reaktion, KEINE Entfernungsbegrenzung zum Hugo-System.

Die Zuordnung Techniker <-> Hugo-Standort (config_hugo_standorte.HUGO_STANDORTE)
ist manuell gepflegt, keine automatische Distanzberechnung.
"""

from __future__ import annotations


def _kurzname(name: str) -> str:
    """'Vorname Nachname' -> 'Vorname N.' -- gleiches Format wie
    api/smax_cache.py._display_name_kurz, damit HUGO_STANDORTE-Klarnamen im
    Echtdaten-Modus (PSEUDONYMISIERUNG_AKTIV=False) auf die Techniker-Dict-IDs
    matchen, die dort bereits in Kurzform vorliegen.
    """
    parts = name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[-1][0]}."
    return name.strip()


def _match_techniker_id(name: str, techniker: dict[str, dict]) -> str | None:
    """Findet die Techniker-Dict-ID zu einem vollen Namen aus HUGO_STANDORTE.

    Matcht sowohl auf den vollen Namen (Demo-/Test-Daten mit Klarnamen als ID)
    als auch auf den Kurznamen 'Vorname N.' (Echtdaten-Modus). Liefert None,
    wenn kein passender Techniker gefunden wird -- z.B. bei aktiver
    Pseudonymisierung, wo der Klarname nicht mehr rekonstruierbar ist, oder
    wenn der Techniker (noch) nicht im aktuellen Datensatz vorkommt.
    """
    if name in techniker:
        return name
    kurz = _kurzname(name)
    if kurz in techniker:
        return kurz
    return None


def hugo_techniker_namen(hugo_standorte: dict[str, dict], hugo_springer: str) -> list[str]:
    """Alle Techniker-Klarnamen, die ein Hugo-Kerngebiet erhalten: jeder
    haupt_techniker aus hugo_standorte plus der Springer -- dedupliziert,
    alphabetisch sortiert.
    """
    namen: set[str] = set()
    for standort in hugo_standorte.values():
        namen.update(standort.get("haupt_techniker", []))
    if hugo_springer:
        namen.add(hugo_springer)
    return sorted(namen)


def _radius_km_aus_fahrzeit(max_fahrzeit_min: float, umweg_faktor: float) -> float:
    """Radius in km, den ein Techniker in max_fahrzeit_min bei effektiver
    Geschwindigkeit 100/umweg_faktor km/h zuruecklegen kann (gleiches
    Fahrzeit-Modell wie in reporting/dashboard.py._berechne_gebietsmetriken).
    """
    eff_speed_kmh = 100.0 / umweg_faktor
    return max_fahrzeit_min / 60.0 * eff_speed_kmh


def berechne_hugo_kerngebiete(
    techniker: dict[str, dict],
    hugo_standorte: dict[str, dict],
    hugo_springer: str,
    max_fahrzeit_min: float,
    umweg_faktor: float,
) -> list[dict]:
    """Berechnet fuer jeden Hugo-Techniker (haupt_techniker aus hugo_standorte
    + Springer) das Kerngebiet: max_fahrzeit_min Fahrzeit-Radius um seinen
    WOHNORT (techniker[...]['lat']/['lon']) -- NICHT um einen Hugo-Standort.

    Ein Eintrag pro Techniker (nicht pro Hugo-Standort), auch wenn ein
    Techniker fuer mehrere Hugo-Standorte zustaendig ist. Techniker, die
    nicht im aktuellen Datensatz gefunden werden (z.B. Pseudonymisierung
    aktiv oder Demo-Modus ohne diese Person), werden uebersprungen -- kein
    Absturz, einfach kein Eintrag.
    """
    radius_km = _radius_km_aus_fahrzeit(max_fahrzeit_min, umweg_faktor)
    ergebnis: list[dict] = []
    for name in hugo_techniker_namen(hugo_standorte, hugo_springer):
        tid = _match_techniker_id(name, techniker)
        if tid is None:
            continue
        td = techniker[tid]
        if not td.get("lat"):
            continue
        ergebnis.append({
            "id": tid,
            "name": name,
            "standort": td.get("standort", "–"),
            "lat": td["lat"],
            "lon": td["lon"],
            "radius_km": round(radius_km, 1),
            "ist_springer": name == hugo_springer,
        })
    return ergebnis


def hugo_standort_marker(
    hugo_standorte: dict[str, dict],
    techniker: dict[str, dict],
) -> list[dict]:
    """Baut Marker-Daten fuer die tatsaechlichen Hugo-Standorte, unabhaengig
    von deren Entfernung zum zustaendigen Techniker (die Distanz Wohnort <->
    Hugo-Standort ist fachlich irrelevant, siehe Modul-Docstring). Jeder
    Marker enthaelt die IDs der zustaendigen Techniker (fuer die
    Verbindungslinie im Dashboard), soweit diese im aktuellen Datensatz
    gefunden werden.
    """
    ergebnis: list[dict] = []
    for standort, daten in sorted(hugo_standorte.items()):
        zustaendige_ids = [
            tid for name in daten.get("haupt_techniker", [])
            if (tid := _match_techniker_id(name, techniker)) is not None
        ]
        ergebnis.append({
            "standort": standort,
            "lat": daten["lat"],
            "lon": daten["lon"],
            "anzahl_systeme": daten.get("anzahl_systeme", 0),
            "haupt_techniker": daten.get("haupt_techniker", []),
            "zustaendige_ids": zustaendige_ids,
            "hinweis": daten.get("hinweis", ""),
            "status": daten.get("status", ""),
        })
    return ergebnis
