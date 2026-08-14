"""Reale Einsatzhistorie-Auswertung fuer ALLE Geraete (nicht nur Hugo).

Wertet die echten Closed Jobs (SMax Sheet 3, api/import_real_data.py) je
Techniker/Cluster aus, um eine realistische Jahresauslastung (Vor-Ort-
Stunden/Jahr) statt der reinen STK/Jahr-Rohsumme zu berechnen. Nutzt die
Einsatzdauer je Model Code aus Sheet 2 (2_Durchscnittliche_Zeit_MC), wo
vorhanden (~88% der Closed Jobs), sonst den Gesamt-Durchschnitt aller
bekannten Model Codes als Fallback.

WICHTIG (Grenze der Datenlage): PM/STK vs. Repair ist auf Auftragsebene NICHT
unterscheidbar. Weder Closed Jobs noch Open Jobs enthalten ein
Auftragstyp-Feld -- SMaxOffenerAuftrag.auftragstyp bleibt im Code bewusst
"UNBEKANNT", SMaxGeschlossenAuftrag hat gar kein solches Feld (siehe
api/import_real_data.py). Jede Funktion hier arbeitet daher ausschliesslich
auf Cluster-/Techniker-/Zeit-Ebene, nie auf PM-vs-Repair-Ebene -- keine
erfundenen Zahlen.

Methodische Einordnung: Die berechnete Auslastung misst reine
Vor-Ort-Servicezeit ÷ volle Aussendienst-Wochenkapazitaet. Fahrzeit ist NICHT
enthalten (siehe bestehende Ratio-Kennzahl: Vor-Ort-Std. ÷ Fahrt-Std. in
reporting/dashboard.py). Der realistische Vollauslastungswert liegt daher
strukturell unter 100%.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Callable, Optional


def einsatzdauer_map(einsatzdauern: list) -> dict[str, int]:
    """model_code -> mittelwert_min aus Sheet 2. Nur Eintraege mit
    model_code und mittelwert_min > 0 (0/leer = keine verwertbaren Daten)."""
    return {
        d.model_code: d.mittelwert_min
        for d in einsatzdauern
        if d.model_code and d.mittelwert_min > 0
    }


def durchschnittsdauer_min(einsatzdauern: list) -> int:
    """Fallback-Dauer (Minuten) fuer Model Codes ohne eigenen Sheet-2-Eintrag:
    Durchschnitt ueber alle bekannten Model Codes. 0 wenn keine Daten."""
    werte = [d.mittelwert_min for d in einsatzdauern if d.model_code and d.mittelwert_min > 0]
    return round(sum(werte) / len(werte)) if werte else 0


def jobs_je_cluster(closed_jobs: list, cluster_lookup: Callable) -> dict[str, int]:
    """Gruppiert Closed Jobs nach Cluster ueber cluster_lookup(model_code) ->
    ClusterInfo|None (z.B. api.cluster_mapping.finde_cluster). Jobs mit
    unbekanntem/fehlendem Cluster-Mapping landen unter 'UNBEKANNT'."""
    z: dict[str, int] = defaultdict(int)
    for job in closed_jobs:
        info = cluster_lookup(job.model_code)
        z[info.cluster if info else "UNBEKANNT"] += 1
    return dict(z)


def jobs_je_techniker_und_cluster(
    closed_jobs: list, cluster_lookup: Callable
) -> dict[str, dict[str, int]]:
    """{techniker_name: {cluster: anzahl}}. Jobs ohne Technician-Feld werden
    ignoriert (keine Zuordnung moeglich)."""
    z: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for job in closed_jobs:
        if not job.techniker:
            continue
        info = cluster_lookup(job.model_code)
        z[job.techniker][info.cluster if info else "UNBEKANNT"] += 1
    return {k: dict(v) for k, v in z.items()}


def einsatzstunden_pro_jahr(
    closed_jobs_fuer_techniker: list,
    dauer_map: dict[str, int],
    fallback_min: int,
    beobachtungszeitraum_jahre: float,
) -> float:
    """Annualisierte Vor-Ort-Einsatzstunden/Jahr eines Technikers aus dessen
    realen Closed Jobs x Einsatzdauer je Model Code (Sheet 2, Fallback:
    Gesamt-Durchschnitt). Wie STK/Jahr annualisiert ueber den tatsaechlichen
    Beobachtungszeitraum -- keine Ad-hoc-Schaetzung."""
    gesamt_min = sum(
        dauer_map.get(job.model_code, fallback_min)
        for job in closed_jobs_fuer_techniker
    )
    zeitraum = beobachtungszeitraum_jahre if beobachtungszeitraum_jahre > 0 else 1.0
    return round(gesamt_min / 60.0 / zeitraum, 1)


def auslastung_pct(
    stunden_pro_jahr: float,
    kapazitaet_wochenstunden: float,
    arbeitswochen_pro_jahr: int,
) -> float:
    """Auslastung in % der Jahreskapazitaet (kapazitaet_wochenstunden x
    arbeitswochen_pro_jahr) -- reine Vor-Ort-Zeit, ohne Fahrzeit."""
    kapazitaet_jahr = kapazitaet_wochenstunden * arbeitswochen_pro_jahr
    if kapazitaet_jahr <= 0:
        return 0.0
    return round(stunden_pro_jahr / kapazitaet_jahr * 100, 1)


def klassifiziere_korridor(pct: float, ziel_min: float, ziel_max: float) -> str:
    """'unter' / 'im_korridor' / 'ueber' relativ zum Auslastungs-Zielkorridor.
    Referenzwert, keine harte Regel."""
    if pct < ziel_min:
        return "unter"
    if pct > ziel_max:
        return "ueber"
    return "im_korridor"


def durchschnittlicher_abstand_tage(erledigung_daten: list[datetime]) -> Optional[float]:
    """Durchschnittlicher Abstand (Tage) zwischen aufeinanderfolgenden
    Einsaetzen eines Technikers, aus (unsortierten) erledigung_datum-Werten.
    None wenn < 2 Datenpunkte (kein Abstand berechenbar) -- kein Absturz."""
    daten = sorted(erledigung_daten)
    if len(daten) < 2:
        return None
    abstaende = [(daten[i + 1] - daten[i]).days for i in range(len(daten) - 1)]
    return round(sum(abstaende) / len(abstaende), 1)
