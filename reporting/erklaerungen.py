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
    "warum_auslastung_abweichend": "Warum weicht die Auslastung von {tid} vom Zielkorridor ab?",
}

FRAGE_TYPEN_EN: dict[str, str] = {
    "warum_gebiet":     "Why does {tid} have this territory?",
    "warum_auslastung": "Why is {tid} at capacity?",
    "warum_verschoben": "Why were clinics moved for {tid}?",
    "warum_auslastung_abweichend": "Why does {tid}'s utilization deviate from the target corridor?",
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
    sprache: str = "de",
) -> str:
    td = techniker.get(tid)
    if td is None:
        if sprache == "en":
            return f"No technician found with ID {tid}."
        return f"Kein Techniker mit der ID {tid} gefunden."
    m = _find(metriken_akt, tid)
    if not m or not m.get("kliniken"):
        if sprache == "en":
            return (
                f"{tid} ({td.get('standort', '–')}) currently has no clinics assigned "
                f"in the territory calculation — either no valid location is available "
                f"or no clinics were found within reachable distance."
            )
        return (
            f"{tid} ({td.get('standort', '–')}) hat aktuell keine zugewiesenen Kliniken "
            f"in der Gebietsberechnung — entweder liegt kein gültiger Standort vor "
            f"oder es wurden keine Kliniken in erreichbarer Nähe gefunden."
        )
    alt = _nearest_alternativtechniker(tid, techniker)
    if sprache == "en":
        alt_txt = (
            f" Geographically nearest alternative technician: {alt[0]} ({alt[1]}, "
            f"~{alt[2]} km away)."
            if alt
            else ""
        )
        return (
            f"{tid} ({td.get('standort', '–')}) currently covers {m['kliniken']} clinics with "
            f"an avg. travel time of {m['avg_fahrzeit']} min (max. {m['max_fahrzeit']} min) and "
            f"a utilization ratio of {m['ratio']} (on-site hours per travel hour). The "
            f"territory assignment follows the existing scoring model (competency 40% + travel time 35% + "
            f"utilization 25%, travel time = Haversine distance × {umweg_faktor} road factor): "
            f"each clinic goes to the technician with the shortest effective travel time, as long "
            f"as their utilization is not significantly higher than that of a closer technician."
            f"{alt_txt}"
        )
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
    sprache: str = "de",
) -> str:
    td = techniker.get(tid)
    if td is None:
        if sprache == "en":
            return f"No technician found with ID {tid}."
        return f"Kein Techniker mit der ID {tid} gefunden."
    m = _find(metriken_akt, tid)
    a = _find(ampeln, tid)
    if sprache == "en":
        teile = [f"{tid} ({td.get('standort', '–')}):"]
        if m:
            teile.append(
                f"{m['kliniken']} clinics in territory, {m['fahrtstunden_jahr']} travel hours/year + "
                f"{m['onsite_stunden']} on-site hours/year (ratio {m['ratio']})."
            )
        if a:
            teile.append(
                f"Qualification coverage: {a['qualifiziert']}/{a['regional']} product families "
                f"({a['abdeckung_pct']}%), {a['fehlend_count']} gaps, "
                f"+{a['zusatz_stk']:.0f} STK/year unused cross-training potential in this territory."
            )
        pm_count = td.get("pm_count")
        if pm_count is not None:
            teile.append(
                f"{pm_count} PM qualifications out of {td.get('total_mc', '–')} model codes "
                f"({td.get('pm_ratio_pct', '–')}% PM ratio)."
            )
        if len(teile) == 1:
            teile.append("No utilization data available for this technician.")
        return " ".join(teile)
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
    sprache: str = "de",
) -> str:
    td = techniker.get(tid)
    if td is None:
        if sprache == "en":
            return f"No technician found with ID {tid}."
        return f"Kein Techniker mit der ID {tid} gefunden."
    m_a = _find(metriken_akt, tid)
    m_o = _find(metriken_opt, tid)
    if not m_o:
        if sprache == "en":
            return f"No optimization data available for {tid}."
        return f"Für {tid} liegen keine Optimierungsdaten vor."
    gewonnen = m_o.get("verschoben_gewonnen", 0)
    abgegeben = m_o.get("verschoben_abgegeben", 0)
    ratio_vorher = m_a["ratio"] if m_a else 0.0
    ratio_nachher = m_o["ratio"]
    delta_fz = (m_o["fahrtstunden_jahr"] - m_a["fahrtstunden_jahr"]) if m_a else 0
    if sprache == "en":
        if not gewonnen and not abgegeben:
            return (
                f"For {tid} ({td.get('standort', '–')}) no clinics were moved — "
                f"all clinics are already within the thresholds at the nearest "
                f"technician."
            )
        teile = [f"{tid} ({td.get('standort', '–')}):"]
        if gewonnen:
            teile.append(
                f"{gewonnen} clinic(s) newly added (taken over from less utilized "
                f"neighboring technicians)."
            )
        if abgegeben:
            teile.append(
                f"{abgegeben} clinic(s) given up (to a less utilized, "
                f"similarly close technician)."
            )
        teile.append(
            f"Utilization ratio {ratio_vorher} → {ratio_nachher}, "
            f"Δ travel hours/year: {'+' if delta_fz >= 0 else ''}{delta_fz} h."
        )
        teile.append(
            "Criterion: a clinic moves to the 2nd-nearest technician if their "
            "utilization is significantly lower and the resulting travel time increase "
            "remains acceptable."
        )
        return " ".join(teile)
    if not gewonnen and not abgegeben:
        return (
            f"Bei {tid} ({td.get('standort', '–')}) wurden keine Kliniken verschoben — "
            f"alle Kliniken liegen bereits innerhalb der Schwellwerte beim nächstgelegenen "
            f"Techniker."
        )
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


def erklaere_warum_auslastung_abweichend(
    tid: str,
    techniker: dict[str, dict],
    ziel_min_pct: float = 80.0,
    ziel_max_pct: float = 95.0,
    ist_hugo_kerngebiet: bool = False,
    sprache: str = "de",
) -> str:
    """Erklaert die Abweichung der echten Auslastung (auslastung_pct_real,
    aus api/auslastung_analyse.py) vom Zielkorridor -- referenziert die
    bestehende Gebietsoptimierungs-Logik als Empfehlung, aendert aber nichts
    automatisch (Referenzwert, keine harte Regel)."""
    td = techniker.get(tid)
    if td is None:
        if sprache == "en":
            return f"No technician found with ID {tid}."
        return f"Kein Techniker mit der ID {tid} gefunden."

    pct = td.get("auslastung_pct_real")
    korridor = td.get("auslastung_korridor")
    if pct is None or korridor is None:
        if sprache == "en":
            return (
                f"No real utilization data available for {tid} (only available in "
                f"real-data mode, computed from actual visit history)."
            )
        return (
            f"Für {tid} liegen keine echten Auslastungsdaten vor (nur im "
            f"Echtdaten-Modus verfügbar, berechnet aus der tatsächlichen "
            f"Einsatzhistorie)."
        )

    einsaetze = td.get("einsaetze_gesamt_real", 0)
    stunden = td.get("einsatzstunden_jahr_real", 0.0)
    hugo_hinweis_de = (
        " Als Hugo-Kerngebiet-Techniker kann die Auslastung strukturell vom "
        "Zielkorridor abweichen: das kleine Small-Capital-Kerngebiet ist eine "
        "Verfügbarkeits-Garantie für schnelle Hugo-Reaktion, keine "
        "Auslastungsoptimierung (Verfügbarkeit vor Auslastung)."
        if ist_hugo_kerngebiet else ""
    )
    hugo_hinweis_en = (
        " As a Hugo core-territory technician, utilization can structurally "
        "deviate from the target corridor: the small Small-Capital core territory "
        "is an availability guarantee for fast Hugo response, not a utilization "
        "optimization (availability over utilization)."
        if ist_hugo_kerngebiet else ""
    )

    if sprache == "en":
        basis = (
            f"{tid}: {pct:.1f}% real utilization ({einsaetze} visits, "
            f"{stunden:.0f}h/year on-site time ÷ annual capacity -- travel "
            f"time not included, so full utilization is structurally below 100%)."
        )
        if korridor == "im_korridor":
            return (
                f"{basis} This is within the {ziel_min_pct:.0f}-{ziel_max_pct:.0f}% "
                f"target corridor -- no notable deviation.{hugo_hinweis_en}"
            )
        if korridor == "unter":
            return (
                f"{basis} This is below the {ziel_min_pct:.0f}-{ziel_max_pct:.0f}% "
                f"target corridor. Possible reasons: low device density in the "
                f"territory, a recently assigned/small territory, or genuinely "
                f"available capacity. Recommendation: check the territory-"
                f"optimization suggestions (Tab 6) and cross-training gaps (Tab 3) "
                f"for this technician -- reference only, no automatic "
                f"reassignment.{hugo_hinweis_en}"
            )
        return (
            f"{basis} This is above the {ziel_min_pct:.0f}-{ziel_max_pct:.0f}% "
            f"target corridor -- risk of overload. Recommendation: check whether "
            f"the territory-optimization logic (Tab 6) suggests moving a clinic "
            f"to a less utilized nearby technician -- reference only, no "
            f"automatic reassignment.{hugo_hinweis_en}"
        )

    basis = (
        f"{tid}: {pct:.1f}% echte Auslastung ({einsaetze} Einsätze, "
        f"{stunden:.0f}h/Jahr Vor-Ort-Zeit ÷ Jahreskapazität — "
        f"Fahrzeit ist nicht enthalten, daher liegt Vollauslastung strukturell "
        f"unter 100%)."
    )
    if korridor == "im_korridor":
        return (
            f"{basis} Das liegt im Zielkorridor {ziel_min_pct:.0f}–"
            f"{ziel_max_pct:.0f}% — keine nennenswerte Abweichung."
            f"{hugo_hinweis_de}"
        )
    if korridor == "unter":
        return (
            f"{basis} Das liegt unter dem Zielkorridor {ziel_min_pct:.0f}–"
            f"{ziel_max_pct:.0f}%. Mögliche Gründe: geringe Gerätedichte im "
            f"Gebiet, ein kürzlich zugewiesenes/kleines Gebiet, oder tatsächlich "
            f"freie Kapazität. Empfehlung: Gebietsoptimierungs-Vorschläge "
            f"(Tab 6) und Crosstraining-Lücken (Tab 3) für diesen Techniker "
            f"prüfen — reine Referenz, keine automatische "
            f"Umverteilung.{hugo_hinweis_de}"
        )
    return (
        f"{basis} Das liegt über dem Zielkorridor {ziel_min_pct:.0f}–"
        f"{ziel_max_pct:.0f}% — Risiko einer Überlastung. Empfehlung: "
        f"prüfen ob die Gebietsoptimierungs-Logik (Tab 6) eine Klinik-"
        f"Verschiebung zu einem weniger ausgelasteten, nahen Techniker "
        f"vorschlägt — reine Referenz, keine automatische "
        f"Umverteilung.{hugo_hinweis_de}"
    )


def generiere_erklaerung(
    frage_typ: str,
    techniker_id: str,
    *,
    techniker: dict[str, dict],
    metriken_akt: list[dict],
    metriken_opt: list[dict] | None = None,
    ampeln: list[dict] | None = None,
    umweg_faktor: float = 1.35,
    sprache: str = "de",
    auslastung_ziel_min_pct: float = 80.0,
    auslastung_ziel_max_pct: float = 95.0,
    hugo_kerngebiet_ids: set[str] | None = None,
) -> str:
    """Erzeugt eine nachvollziehbare Text-Erklaerung rein aus vorhandenen
    Berechnungsdaten (Gebietsmetriken, Ampeln, Scoring-Gewichtung) -- ohne
    externen KI-API-Aufruf. `sprache` ("de"/"en") waehlt nur die Formulierung --
    alle Zahlen/Fakten kommen unveraendert aus denselben Berechnungsdaten.
    """
    sprache = "en" if sprache == "en" else "de"
    metriken_opt = metriken_opt or []
    ampeln = ampeln or []
    if frage_typ == "warum_gebiet":
        return erklaere_warum_gebiet(techniker_id, techniker, metriken_akt, umweg_faktor, sprache)
    if frage_typ == "warum_auslastung":
        return erklaere_warum_auslastung(techniker_id, techniker, metriken_akt, ampeln, sprache)
    if frage_typ == "warum_verschoben":
        return erklaere_warum_verschoben(techniker_id, techniker, metriken_akt, metriken_opt, sprache)
    if frage_typ == "warum_auslastung_abweichend":
        ist_hugo = techniker_id in (hugo_kerngebiet_ids or set())
        return erklaere_warum_auslastung_abweichend(
            techniker_id, techniker, auslastung_ziel_min_pct, auslastung_ziel_max_pct,
            ist_hugo, sprache,
        )
    if sprache == "en":
        return f"Unknown question type: {frage_typ}"
    return f"Unbekannter Fragetyp: {frage_typ}"
