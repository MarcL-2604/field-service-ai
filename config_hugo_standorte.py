"""Hugo-Standorte und Zustaendigkeiten (manuell gepflegte Konfiguration).

Hugo-Systeme stehen an wenigen, teils weit von den Wohnorten der zustaendigen
Techniker entfernten Standorten -- diese Zuordnung Techniker <-> Hugo-Standort
ist eine organisatorische Entscheidung, KEINE automatische Distanzberechnung.
Sie wird deshalb hier manuell gepflegt statt aus Fahrzeiten abgeleitet zu
werden (siehe reporting/hugo_kerngebiet.py fuer die Verwendung -- dort wird
lediglich das Alltags-Kerngebiet um den Wohnort jedes hier genannten
Technikers berechnet, nicht die Zuordnung selbst).

Koordinaten sind Stadtzentrum-Naeherungswerte (fuer die Kartendarstellung der
Hugo-Standort-Marker), keine exakten Klinikadressen.
"""

from __future__ import annotations

HUGO_STANDORTE: dict[str, dict] = {
    "Hamburg": {
        "anzahl_systeme": 4,
        "haupt_techniker": ["Dirk Häbel", "Hector C."],
        "lat": 53.5511, "lon": 9.9937,
    },
    "Lübeck": {
        "anzahl_systeme": 1,
        "haupt_techniker": ["Dirk Häbel", "Hector C."],
        "lat": 53.8655, "lon": 10.6866,
    },
    "Bochum": {
        "anzahl_systeme": 1,
        "haupt_techniker": ["Michael Gehlen", "Ahmed Awadallah"],
        "lat": 51.4818, "lon": 7.2162,
    },
    "Herne": {
        "anzahl_systeme": 1,
        "haupt_techniker": ["Michael Gehlen", "Ahmed Awadallah"],
        "lat": 51.5386, "lon": 7.2256,
    },
    "Köln": {
        "anzahl_systeme": 1,
        "haupt_techniker": ["Michael Gehlen", "Ahmed Awadallah"],
        "lat": 50.9375, "lon": 6.9603,
    },
    "Dresden": {
        "anzahl_systeme": 1,
        "haupt_techniker": ["Ahmed Awadallah"],
        "hinweis": "Springer-Zuständigkeit",
        "lat": 51.0504, "lon": 13.7373,
    },
    "Ulm": {
        "anzahl_systeme": 1,
        "haupt_techniker": ["Marc Liebhardt"],
        "lat": 48.4011, "lon": 9.9876,
    },
    "Mannheim": {
        "anzahl_systeme": 1,
        "haupt_techniker": ["Marc Liebhardt"],
        "status": "demnächst",
        "lat": 49.4875, "lon": 8.4660,
    },
    "Heidelberg": {
        "anzahl_systeme": 1,
        "haupt_techniker": ["Marc Liebhardt"],
        "status": "demnächst",
        "lat": 49.3988, "lon": 8.6724,
    },
}

# Experte, zusaetzlich deutschlandweit als Springer fuer ALLE Hugo-Systeme
# verfuegbar (inkl. alleinige Zustaendigkeit fuer Dresden).
HUGO_SPRINGER = "Ahmed Awadallah"

HUGO_TEAM_GROESSE = {
    "PM":     2,   # Wartung/STK erfordert 2 Techniker
    "REPAIR": 1,   # Repair erfordert zu 90% nur 1 Techniker
}
