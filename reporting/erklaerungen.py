"""Template-basierte Erklaerungen fuer Gebiets- und Auslastungsentscheidungen.

Erzeugt nachvollziehbare Text-Antworten ausschliesslich aus den bereits im
Dashboard berechneten Daten (Gebietsmetriken, Ampeln, Scoring-Gewichtung) --
kein externer KI-API-Aufruf, keine Kosten, funktioniert offline. Wird beim
Dashboard-Build einmal fuer alle Techniker/Fragetypen vorberechnet und als
JSON in die statische HTML eingebettet (siehe reporting/dashboard.py).
"""

from __future__ import annotations

import math

FRAGE_TYPEN: dict[str, str] = {
    "warum_gebiet":     "Warum hat {tid} dieses Gebiet?",
    "warum_auslastung": "Warum ist {tid} ausgelastet?",
    "warum_verschoben": "Warum wurden bei {tid} Kliniken verschoben?",
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _find(rows: list[dict], tid: str) -> dict | None:
    return next((r for r in rows if r.get("id") == tid or r.get("techniker_id") == tid), None)


def _nearest_alternativtechniker(
    tid: str, techniker: dict[str, dict]
) -> tuple[str, str, int] | None:
    """Geografisch naechstgelegener anderer Techniker (Haversine)."""
    td = techniker.get(tid, {})
    if not td.get("lat"):
        return None
    best_id, best_km = None, float("inf")
    for other_id, other in techniker.items():
        if other_id == tid or not other.get("lat"):
            continue
        km = _haversine_km(td["lat"], td["lon"], other["lat"], other["lon"])
        if km < best_km:
            best_id, best_km = other_id, km
    if best_id is None:
        return None
    return best_id, techniker[best_id].get("standort", "–"), round(best_km)


def erklaere_warum_gebiet(
    tid: str,
    techniker: dict[str, dict],
    metriken_akt: list[dict],
    umweg_faktor: float = 1.35,
) -> str:
    td = techniker.get(tid)
    if td is None:
        return f"Kein Techniker mit der ID {tid} gefunden."
    m = _find(metriken_akt, tid)
    if not m or not m.get("kliniken"):
        return (
            f"{tid} ({td.get('standort', '–')}) hat aktuell keine zugewiesenen Kliniken "
            f"in der Gebietsberechnung — entweder liegt kein gültiger Standort vor "
            f"oder es wurden keine Kliniken in erreichbarer Nähe gefunden."
        )
    alt = _nearest_alternativtechniker(tid, techniker)
    alt_txt = (
        f" Geografisch nächstgelegener Alternativtechniker: {alt[0]} ({alt[1]}, "
        f"~{alt[2]} km entfernt)."
        if alt
        else ""
    )
    return (
        f"{tid} ({td.get('standort', '–')}) betreut aktuell {m['kliniken']} Kliniken mit "
        f"einer Ø Fahrzeit von {m['avg_fahrzeit']} min (max. {m['max_fahrzeit']} min) und "
        f"einer Auslastungs-Ratio von {m['ratio']} (Vor-Ort-Stunden je Fahrtstunde). Die "
        f"Gebietszuordnung folgt dem bestehenden Scoring-Modell (Kompetenz 40% + Fahrzeit 35% + "
        f"Auslastung 25%, Fahrzeit = Haversine-Distanz × {umweg_faktor} Straßenfaktor): "
        f"jede Klinik geht an den Techniker mit der kürzesten effektiven Fahrzeit, solange "
        f"dessen Auslastung nicht deutlich höher liegt als bei einem näheren Techniker."
        f"{alt_txt}"
    )


def erklaere_warum_auslastung(
    tid: str,
    techniker: dict[str, dict],
    metriken_akt: list[dict],
    ampeln: list[dict],
) -> str:
    td = techniker.get(tid)
    if td is None:
        return f"Kein Techniker mit der ID {tid} gefunden."
    m = _find(metriken_akt, tid)
    a = _find(ampeln, tid)
    teile = [f"{tid} ({td.get('standort', '–')}):"]
    if m:
        teile.append(
            f"{m['kliniken']} Kliniken im Gebiet, {m['fahrtstunden_jahr']} Fahrtstunden/Jahr + "
            f"{m['onsite_stunden']} Vor-Ort-Stunden/Jahr (Ratio {m['ratio']})."
        )
    if a:
        teile.append(
            f"Qualifikations-Abdeckung: {a['qualifiziert']}/{a['regional']} Produktfamilien "
            f"({a['abdeckung_pct']}%), {a['fehlend_count']} Lücken, "
            f"+{a['zusatz_stk']:.0f} STK/Jahr ungenutztes Crosstraining-Potenzial im Gebiet."
        )
    pm_count = td.get("pm_count")
    if pm_count is not None:
        teile.append(
            f"{pm_count} PM-Qualifikationen von {td.get('total_mc', '–')} Modellcodes "
            f"({td.get('pm_ratio_pct', '–')}% PM-Quote)."
        )
    if len(teile) == 1:
        teile.append("Keine Auslastungsdaten für diesen Techniker verfügbar.")
    return " ".join(teile)


def erklaere_warum_verschoben(
    tid: str,
    techniker: dict[str, dict],
    metriken_akt: list[dict],
    metriken_opt: list[dict],
) -> str:
    td = techniker.get(tid)
    if td is None:
        return f"Kein Techniker mit der ID {tid} gefunden."
    m_a = _find(metriken_akt, tid)
    m_o = _find(metriken_opt, tid)
    if not m_o:
        return f"Für {tid} liegen keine Optimierungsdaten vor."
    gewonnen = m_o.get("verschoben_gewonnen", 0)
    abgegeben = m_o.get("verschoben_abgegeben", 0)
    if not gewonnen and not abgegeben:
        return (
            f"Bei {tid} ({td.get('standort', '–')}) wurden keine Kliniken verschoben — "
            f"alle Kliniken liegen bereits innerhalb der Schwellwerte beim nächstgelegenen "
            f"Techniker."
        )
    ratio_vorher = m_a["ratio"] if m_a else 0.0
    ratio_nachher = m_o["ratio"]
    delta_fz = (m_o["fahrtstunden_jahr"] - m_a["fahrtstunden_jahr"]) if m_a else 0
    teile = [f"{tid} ({td.get('standort', '–')}):"]
    if gewonnen:
        teile.append(
            f"{gewonnen} Klinik(en) neu hinzugekommen (von weniger ausgelasteten "
            f"Nachbartechnikern übernommen)."
        )
    if abgegeben:
        teile.append(
            f"{abgegeben} Klinik(en) abgegeben (an einen weniger ausgelasteten, "
            f"ähnlich nahen Techniker)."
        )
    teile.append(
        f"Auslastungs-Ratio {ratio_vorher} → {ratio_nachher}, "
        f"Δ Fahrtstunden/Jahr: {'+' if delta_fz >= 0 else ''}{delta_fz} h."
    )
    teile.append(
        "Kriterium: Eine Klinik wechselt zum 2.-nächstgelegenen Techniker, wenn dessen "
        "Auslastung deutlich niedriger ist und die Fahrzeit-Mehrbelastung dabei vertretbar "
        "bleibt."
    )
    return " ".join(teile)


def generiere_erklaerung(
    frage_typ: str,
    techniker_id: str,
    *,
    techniker: dict[str, dict],
    metriken_akt: list[dict],
    metriken_opt: list[dict] | None = None,
    ampeln: list[dict] | None = None,
    umweg_faktor: float = 1.35,
) -> str:
    """Erzeugt eine nachvollziehbare Text-Erklaerung rein aus vorhandenen
    Berechnungsdaten (Gebietsmetriken, Ampeln, Scoring-Gewichtung) -- ohne
    externen KI-API-Aufruf.
    """
    metriken_opt = metriken_opt or []
    ampeln = ampeln or []
    if frage_typ == "warum_gebiet":
        return erklaere_warum_gebiet(techniker_id, techniker, metriken_akt, umweg_faktor)
    if frage_typ == "warum_auslastung":
        return erklaere_warum_auslastung(techniker_id, techniker, metriken_akt, ampeln)
    if frage_typ == "warum_verschoben":
        return erklaere_warum_verschoben(techniker_id, techniker, metriken_akt, metriken_opt)
    return f"Unbekannter Fragetyp: {frage_typ}"
