"""Hugo-Zusatzgebiet-Regel (optional, standardmaessig deaktiviert).

Hugo-KA-Techniker mit wenigen Hugo-Systemen im Kerngebiet sind trotzdem
stark ausgelastet (Hugo ist reparaturanfaellig, bindet viel Kapazitaet).
Fuer sie kann im Dashboard optional ein erweitertes Gebiet (Radius aus
config.HUGO_ZUSATZGEBIET_MAX_FAHRZEIT_MIN) fuer bestimmte
Small-Capital-Zusatzprodukte (config.HUGO_ZUSATZGEBIET_PRODUKTE) aktiviert
werden -- dort gilt immer PM-only (Repair=False), unabhaengig vom normalen
Cluster-Mapping dieser Geraete. Die Regel ist rein additiv: nichts hier
veraendert die bestehende Gebiets-/Crosstraining-Logik, solange sie nicht
explizit im Dashboard aktiviert wird.
"""

from __future__ import annotations

MAX_HUGO_SYSTEME_FUER_ZUSATZGEBIET = 2


def ist_zusatzprodukt(model_code: str, zusatzprodukte: list[str]) -> bool:
    """True wenn model_code eines der Hugo-Zusatzgebiet-Produkte ist.

    Platzhalter-Eintraege (noch ohne echten MC-Code, z.B. "CVG-Platzhalter
    (MC-Code fehlt noch)") matchen nie ein echtes Geraet -- kein Absturz,
    einfach kein Treffer, bis der echte MC-Code ergaenzt wird.
    """
    return model_code in zusatzprodukte


def repair_erlaubt_in_zusatzgebiet(model_code: str, zusatzprodukte: list[str]) -> bool:
    """Im Hugo-Zusatzgebiet gilt fuer Zusatzprodukte IMMER Repair=False --
    unabhaengig vom normalen Cluster-Mapping-Wert dieser Geraete. Fuer alle
    anderen Geraete greift diese Regel nicht (True = keine Einschraenkung).
    """
    return not ist_zusatzprodukt(model_code, zusatzprodukte)


def _radius_km_aus_fahrzeit(max_fahrzeit_min: float, umweg_faktor: float) -> float:
    """Radius in km, den ein Techniker in max_fahrzeit_min bei effektiver
    Geschwindigkeit 100/umweg_faktor km/h zuruecklegen kann (gleiches
    Fahrzeit-Modell wie in reporting/dashboard.py._berechne_gebietsmetriken).
    """
    eff_speed_kmh = 100.0 / umweg_faktor
    return max_fahrzeit_min / 60.0 * eff_speed_kmh


def berechne_hugo_zusatzgebiete(
    techniker: dict[str, dict],
    hugo_ka_ids: set[str],
    hugo_systeme_pro_tech: dict[str, int],
    max_fahrzeit_min: float,
    umweg_faktor: float,
    max_hugo_systeme: int = MAX_HUGO_SYSTEME_FUER_ZUSATZGEBIET,
) -> list[dict]:
    """Ermittelt Hugo-KA-Techniker mit <= max_hugo_systeme Hugo-Geraeten im
    Kerngebiet und berechnet fuer sie den Fahrzeit-Radius (km) fuer die
    Small-Capital-Zusatzprodukte.

    Gibt eine Liste von {id, standort, lat, lon, radius_km, hugo_systeme}
    zurueck -- leer, wenn keine Datengrundlage (hugo_systeme_pro_tech) oder
    kein qualifizierender Techniker vorhanden ist (z.B. im Demo-Modus ohne
    reale Geraetedichte-Daten). Diese Funktion aktiviert die Regel nicht
    selbst -- das Dashboard entscheidet per Toggle, ob das Ergebnis
    angezeigt wird.
    """
    radius_km = _radius_km_aus_fahrzeit(max_fahrzeit_min, umweg_faktor)
    ergebnis: list[dict] = []
    for tid in sorted(hugo_ka_ids):
        td = techniker.get(tid)
        if not td or not td.get("lat"):
            continue
        hugo_count = hugo_systeme_pro_tech.get(tid, 0)
        if hugo_count > max_hugo_systeme:
            continue
        ergebnis.append({
            "id": tid,
            "standort": td.get("standort", "–"),
            "lat": td["lat"],
            "lon": td["lon"],
            "radius_km": round(radius_km, 1),
            "hugo_systeme": hugo_count,
        })
    return ergebnis
