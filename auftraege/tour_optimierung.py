"""Tour-Optimierung: Klinik-Buendelung und Tagestouren.

Drei Optimierungsstufen:
    1. Klinik-Buendelung (einfach): Mehrere STK/PM in derselben Klinik im selben Monat
       → ein Einsatz statt mehrerer Einzeltermine.
    2. Klinik-Buendelung mit Qualifikation: Wie 1., aber prueft ob ein Techniker
       alle Geraete abdeckt. Falls nicht → Aufteilung nach Qualifikationsgruppen.
    3. Tour-Optimierung: Geografisch nahe Kliniken zu Tagestouren buendeln
       → weniger Einzelfahrten, mehr Onsite-Zeit.

Oeffentliche API:
    buendle_auftraege(auftraege) -> list[GebueindelterEinsatz]
    buendle_mit_qualifikation(auftraege) -> list[QualifizierterBuendelPlan]
    optimiere_tagestouren(auftraege, techniker_id) -> list[Tagestour]
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

from config import PLANUNGSHORIZONT_TAGE, PLANUNGSHORIZONT_MIN, VORLAUF_STANDARD_TAGE  # noqa: F401
from config import (
    AUSSENDIENST_STUNDEN,
    HAVERSINE_UMWEG_FAKTOR,
    MAX_EINSATZ_STUNDEN,
    RUESTZEIT_MINUTEN,
    BUENDELUNG_RADIUS_KM,
    MAX_UEBERNACHTUNGEN_WOCHE,
    MAX_UEBERNACHTUNGEN_WOCHE_AUSNAHME,
    MAX_UEBERNACHTUNGEN_HUGO,
    UEBERNACHTUNG_TRIGGER_H,
    LETZTER_AUSSENEINSATZ_WOCHENTAG,
    KEIN_WOCHENENDEINSATZ,
    HUGO_KA_IDS,
)
from techniker.models import (
    BIG_CAPITAL_CLUSTER1_OR,
    BIG_CAPITAL_CLUSTER2_CARDIAC,
    STK_L2_ERLAUBT,
    mindest_level_fuer,
)
from .models import Auftrag

_DATA_DIR = Path(__file__).parent.parent / "daten"

# Buendelung: Ruestzeit pro zusaetzlichem Geraet am selben Standort
RUESTZEIT_PRO_GERAET_STD = RUESTZEIT_MINUTEN / 60.0   # 30 Minuten → 0.5h

# Tour-Optimierung: Maximaler Radius fuer Klinik-Cluster
CLUSTER_RADIUS_KM = float(BUENDELUNG_RADIUS_KM)

# Arbeitszeitlimits (aus config.py)
_WOCHE_ZIEL_STD = float(AUSSENDIENST_STUNDEN)
_MAX_TAG_NORMAL = 8.0

# Rueckwaertskompatible Aliase
SMALL_CAPITAL_L2_REICHT: list[str] = list(STK_L2_ERLAUBT)
BIG_CAPITAL_L3_PFLICHT: list[str] = list(BIG_CAPITAL_CLUSTER1_OR + BIG_CAPITAL_CLUSTER2_CARDIAC)

# Maximale Einsatzdauer pro gebuendeltem Einsatz
MAX_EINSATZ_DAUER_STD = MAX_EINSATZ_STUNDEN

# Fahrzeit-Schaetzung (aus config.py)
_UMWEGFAKTOR = HAVERSINE_UMWEG_FAKTOR
_REISEGESCHWINDIGKEIT_KMH = 90.0

# Uebernachtungsregel (aus config.py)
_UEBERNACHTUNG_TRIGGER_STD = float(UEBERNACHTUNG_TRIGGER_H)
_MAX_UEBERNACHTUNGEN_STANDARD = MAX_UEBERNACHTUNGEN_WOCHE
_MAX_UEBERNACHTUNGEN_AUSNAHME = MAX_UEBERNACHTUNGEN_WOCHE_AUSNAHME
_MAX_UEBERNACHTUNGEN_HUGO = MAX_UEBERNACHTUNGEN_HUGO

# Einsatztage-Regeln (aus config.py)
_LETZTER_AUSSENEINSATZ_WOCHENTAG = LETZTER_AUSSENEINSATZ_WOCHENTAG  # Do=3
_KEIN_WOCHENENDEINSATZ = KEIN_WOCHENENDEINSATZ
_HUGO_KA_IDS_TOUR: set[str] = set(HUGO_KA_IDS)


# ---------------------------------------------------------------------------
# Haversine (konsistent mit scoring.py)
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Luftlinien-Distanz in km nach Haversine-Formel."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def _fahrzeit_std(distanz_km: float) -> float:
    return (distanz_km * _UMWEGFAKTOR) / _REISEGESCHWINDIGKEIT_KMH


# ---------------------------------------------------------------------------
# Datenklassen
# ---------------------------------------------------------------------------

@dataclass
class GebueindelterEinsatz:
    """Zusammengefasste Work Orders fuer eine Klinik in einem Monat."""
    klinik_id: str
    klinik_name: str
    monat: str                          # "YYYY-MM"
    auftraege: list[Auftrag]
    einzeldauern_std: list[float]       # Geschaetzte Dauer je Auftrag
    gesamtdauer_std: float              # Summe + Ruestzeiten
    ruestzeit_std: float                # Ruestzeit fuer Buendelung
    eingesparte_fahrten: int            # Anzahl gesparter Einzelfahrten
    ersparnis_fahrzeit_std: float       # Eingesparte Fahrzeit in Stunden

    def __repr__(self) -> str:
        return (
            f"GebueindelterEinsatz(klinik={self.klinik_name}, "
            f"monat={self.monat}, {len(self.auftraege)} Auftraege, "
            f"gesamt={self.gesamtdauer_std:.1f}h, "
            f"spart {self.eingesparte_fahrten} Fahrt(en))"
        )


@dataclass
class EinsatzZuweisung:
    """Ein Techniker-Einsatz innerhalb eines qualifizierten Buendel-Plans."""
    techniker_id: str
    auftraege: list[Auftrag]
    abgedeckte_familien: list[str]         # Produktfamilien die dieser Tech abdeckt
    qualifikationen: dict[str, str]        # {produktfamilie: "L2"/"L3"}
    dauer_std: float
    begruendung: str                       # Warum dieser Techniker


@dataclass
class QualifizierterBuendelPlan:
    """Buendelplan mit Qualifikations-Check fuer eine Klinik/Monat-Gruppe.

    fall: "A" = ein Techniker deckt alles ab
          "B" = Aufteilung noetig, kein einzelner Techniker reicht
          "C" = Teilueberschneidung, breitestes Portfolio gewaehlt
    """
    klinik_id: str
    klinik_name: str
    monat: str
    fall: str                              # "A", "B" oder "C"
    einsaetze: list[EinsatzZuweisung]      # 1 oder mehr Techniker-Einsaetze
    alle_auftraege: list[Auftrag]
    eingesparte_fahrten: int
    hinweis: str                           # Dashboard-Anzeige-Text
    aufteilungsgrund: Optional[str] = None  # Warum aufgeteilt (nur bei B/C)


@dataclass
class Tagestour:
    """Vorschlag fuer eine optimierte Tagestour."""
    techniker_id: str
    datum: Optional[date]                # Vorgeschlagener Tag (None = flexibel)
    kliniken: list[dict]                 # [{"klinik_id": str, "klinik_name": str, "distanz_km": float}]
    auftraege: list[Auftrag]
    gesamtfahrzeit_std: float            # Wohnort → K1 → K2 → ... → Wohnort
    gesamtdauer_onsite_std: float
    gesamtdauer_tag_std: float           # Fahrzeit + Onsite
    eingesparte_einzelfahrten: int
    hinweis: str
    uebernachtung_noetig: bool = False
    uebernachtungs_ausnahme: bool = False
    uebernachtungs_kommentar: Optional[str] = None
    dashboard_warnung: Optional[str] = None

    def __repr__(self) -> str:
        klinik_namen = [k["klinik_name"] for k in self.kliniken]
        return (
            f"Tagestour({self.techniker_id}: "
            f"{' → '.join(klinik_namen)}, "
            f"{self.gesamtdauer_tag_std:.1f}h gesamt, "
            f"spart {self.eingesparte_einzelfahrten} Einzelfahrt(en))"
        )


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _lade_klinik_coords() -> dict[str, tuple[float, float, str]]:
    """Gibt {klinik_id: (lat, lon, name)} aus kliniken.csv zurueck."""
    df = pd.read_csv(_DATA_DIR / "kliniken.csv", dtype=str)
    # PLZ → GPS Mapping (aus scoring.py uebernommen)
    from techniker.scoring import _KLINIK_COORDS
    result: dict[str, tuple[float, float, str]] = {}
    for _, row in df.iterrows():
        plz = str(row["plz"]).strip().zfill(5)
        if plz in _KLINIK_COORDS:
            lat, lon = _KLINIK_COORDS[plz]
            result[row["klinik_id"]] = (lat, lon, row["name"])
    return result


def _lade_techniker_coords() -> dict[str, tuple[float, float, str]]:
    """Gibt {techniker_id: (lat, lon, standort)} zurueck."""
    df = pd.read_csv(_DATA_DIR / "techniker.csv", dtype=str)
    return {
        row["techniker_id"]: (float(row["lat"]), float(row["lon"]), row["standort"])
        for _, row in df.iterrows()
    }


def _standard_einsatzdauer(auftrag: Auftrag) -> float:
    """Geschaetzte Einsatzdauer in Stunden basierend auf Auftragstyp.

    Verwendet labor_zeiten.csv wenn verfuegbar, sonst Pauschalwerte.
    """
    try:
        from .einsatz_dauer import berechne_einsatz_dauer
        geraete = [{"produkt_familie": auftrag.produkt_familie,
                    "geraete_typ": auftrag.geraet_id,
                     "anzahl": auftrag.anzahl_geraete}]
        result = berechne_einsatz_dauer(geraete)
        return result.gesamt_std
    except Exception:
        # Fallback auf Pauschalwerte
        if auftrag.auftragstyp.value == "Repair":
            return 6.0
        return 4.0 * auftrag.anzahl_geraete


def _lade_trainingsmatrix() -> dict[str, dict[str, str]]:
    """Gibt {techniker_id: {produktfamilie: level_str}} zurueck."""
    df = pd.read_csv(_DATA_DIR / "trainingsmatrix.csv", dtype=str)
    matrix: dict[str, dict[str, str]] = {}
    for _, row in df.iterrows():
        tid = row["techniker_id"]
        if tid not in matrix:
            matrix[tid] = {}
        matrix[tid][row["produktfamilie"]] = row["level"]
    return matrix


def _mindest_level(produkt_familie: str, auftrag_typ: str) -> str:
    """Gibt das Mindest-Level fuer eine Produktfamilie + Auftragstyp zurueck.

    Delegiert an techniker.models.mindest_level_fuer() (Single Source of Truth).
    """
    num = mindest_level_fuer(produkt_familie, auftrag_typ)
    return f"L{num}"


def _tech_deckt_ab(
    tech_quals: dict[str, str],
    auftraege: list[Auftrag],
) -> tuple[list[Auftrag], list[Auftrag]]:
    """Prueft welche Auftraege ein Techniker mit seinen Qualifikationen abdeckt.

    Returns:
        (abgedeckt, nicht_abgedeckt)
    """
    abgedeckt: list[Auftrag] = []
    nicht_abgedeckt: list[Auftrag] = []
    for a in auftraege:
        pf = a.produkt_familie
        level = tech_quals.get(pf)
        if level is None:
            nicht_abgedeckt.append(a)
            continue
        mindest = _mindest_level(pf, a.auftragstyp.value)
        # L3 > L2 > L1
        level_rang = {"L3": 3, "L2": 2, "L1": 1}
        if level_rang.get(level, 0) >= level_rang.get(mindest, 0):
            abgedeckt.append(a)
        else:
            nicht_abgedeckt.append(a)
    return abgedeckt, nicht_abgedeckt


# ---------------------------------------------------------------------------
# Uebernachtungs-Ausnahme-Pruefung
# ---------------------------------------------------------------------------

def pruefe_uebernachtungs_ausnahme(
    fahrzeit_hin_std: float,
    uebernachtungen_diese_woche: int,
    kliniken_kombinierbar: bool,
    techniker_id: Optional[str] = None,
    produkt_familie: Optional[str] = None,
) -> tuple[bool, str]:
    """Prueft ob eine zusaetzliche Uebernachtung wirtschaftlich gerechtfertigt ist.

    Bedingung a: Fahrzeiteinsparung >= 3h (gesparteer Hin-/Rueckweg)
    Bedingung b: Mindestens 2 Kliniken in gleicher Region kombinierbar

    Hugo-KA (T1/T6/T10/T11) und CLUSTER1_OR/CLUSTER2_CARDIAC erhalten
    erhoehtes Limit von MAX_UEBERNACHTUNGEN_HUGO (3) statt Standard (2).

    Kein Einsatz an Samstag (5) oder Sonntag (6).
    Letzter Ausseneinsatz-Tag = Donnerstag (Wochentag 3).

    Returns:
        (ausnahme_erlaubt, kommentar)
    """
    # Hugo-KA oder Big-Capital-Cluster → erhoehtes Uebernachtungslimit
    is_hugo_ka = techniker_id is not None and techniker_id in _HUGO_KA_IDS_TOUR
    is_big_capital = (
        produkt_familie is not None
        and produkt_familie in (BIG_CAPITAL_CLUSTER1_OR + BIG_CAPITAL_CLUSTER2_CARDIAC)
    )
    if is_hugo_ka or is_big_capital:
        max_uebernachtungen = _MAX_UEBERNACHTUNGEN_HUGO
    else:
        max_uebernachtungen = _MAX_UEBERNACHTUNGEN_AUSNAHME

    if uebernachtungen_diese_woche < _MAX_UEBERNACHTUNGEN_STANDARD:
        return False, ""  # Standardlimit noch nicht erreicht

    if uebernachtungen_diese_woche >= max_uebernachtungen:
        return False, ""  # Limit (Standard- oder Hugo-Ausnahme) voll

    fahrzeit_gespart = fahrzeit_hin_std * 2
    bedingung_a = fahrzeit_gespart >= _UEBERNACHTUNG_TRIGGER_STD
    bedingung_b = kliniken_kombinierbar

    if not (bedingung_a or bedingung_b):
        return False, ""

    grundteile: list[str] = []
    if bedingung_a:
        grundteile.append(f"Fahrzeiteinsparung {fahrzeit_gespart:.1f}h")
    if bedingung_b:
        grundteile.append("Kliniken in gleicher Region kombinierbar")
    n = uebernachtungen_diese_woche + 1
    return True, f"Wirtschaftliche Ausnahme: {n} Uebernachtungen ({', '.join(grundteile)})"


# ---------------------------------------------------------------------------
# 1. Klinik-Buendelung (einfach, ohne Qualifikations-Check)
# ---------------------------------------------------------------------------

def buendle_auftraege(
    auftraege: list[Auftrag],
    avg_fahrzeit_std: float = 1.0,
) -> list[GebueindelterEinsatz]:
    """Gruppiert Auftraege nach Klinik + Monat und fasst sie zusammen.

    Args:
        auftraege:        Liste aller offenen Auftraege.
        avg_fahrzeit_std: Durchschnittliche Fahrzeit pro Einsatz in Stunden
                          (fuer Ersparnis-Berechnung). Default: 1.0h.

    Returns:
        Liste von GebueindelterEinsatz (nur Gruppen mit >= 2 Auftraegen).
    """
    # Gruppieren nach klinik_id + Monat
    gruppen: dict[tuple[str, str], list[Auftrag]] = {}
    for a in auftraege:
        if a.klinik_id is None:
            continue
        monat = a.faelligkeitsdatum.strftime("%Y-%m")
        key = (a.klinik_id, monat)
        if key not in gruppen:
            gruppen[key] = []
        gruppen[key].append(a)

    ergebnisse: list[GebueindelterEinsatz] = []
    for (klinik_id, monat), auftraege_gruppe in gruppen.items():
        if len(auftraege_gruppe) < 2:
            continue

        einzeldauern = [_standard_einsatzdauer(a) for a in auftraege_gruppe]
        ruestzeit = RUESTZEIT_PRO_GERAET_STD * (len(auftraege_gruppe) - 1)
        gesamtdauer = sum(einzeldauern) + ruestzeit
        eingesparte_fahrten = len(auftraege_gruppe) - 1
        ersparnis = eingesparte_fahrten * avg_fahrzeit_std

        ergebnisse.append(GebueindelterEinsatz(
            klinik_id=klinik_id,
            klinik_name=auftraege_gruppe[0].klinik_name,
            monat=monat,
            auftraege=auftraege_gruppe,
            einzeldauern_std=einzeldauern,
            gesamtdauer_std=gesamtdauer,
            ruestzeit_std=ruestzeit,
            eingesparte_fahrten=eingesparte_fahrten,
            ersparnis_fahrzeit_std=ersparnis,
        ))

    ergebnisse.sort(key=lambda e: e.eingesparte_fahrten, reverse=True)
    return ergebnisse


# ---------------------------------------------------------------------------
# 2. Klinik-Buendelung mit Qualifikations-Check
# ---------------------------------------------------------------------------

def buendle_mit_qualifikation(
    auftraege: list[Auftrag],
    avg_fahrzeit_std: float = 1.0,
) -> list[QualifizierterBuendelPlan]:
    """Gruppiert Auftraege nach Klinik + Monat und prueft Qualifikation.

    Entscheidungsbaum:
        Fall A: Ein Techniker deckt alle Geraete ab → ein Einsatz
        Fall B: Kein einzelner Techniker reicht → Aufteilung nach Qualifikationsgruppen
        Fall C: Teilueberschneidung → breitestes Portfolio zuerst gewaehlt

    Args:
        auftraege:        Liste aller offenen Auftraege.
        avg_fahrzeit_std: Durchschnittliche Fahrzeit fuer Ersparnis-Berechnung.

    Returns:
        Liste von QualifizierterBuendelPlan (nur Gruppen mit >= 2 Auftraegen).
    """
    matrix = _lade_trainingsmatrix()
    tech_df = pd.read_csv(_DATA_DIR / "techniker.csv", dtype=str)
    aktive_techniker = {
        row["techniker_id"]
        for _, row in tech_df.iterrows()
        if str(row.get("status", "aktiv")).lower() == "aktiv"
    }

    # Gruppieren nach klinik_id + Monat
    gruppen: dict[tuple[str, str], list[Auftrag]] = {}
    for a in auftraege:
        if a.klinik_id is None:
            continue
        monat = a.faelligkeitsdatum.strftime("%Y-%m")
        key = (a.klinik_id, monat)
        if key not in gruppen:
            gruppen[key] = []
        gruppen[key].append(a)

    ergebnisse: list[QualifizierterBuendelPlan] = []

    for (klinik_id, monat), gruppe in gruppen.items():
        if len(gruppe) < 2:
            continue

        klinik_name = gruppe[0].klinik_name
        benoetigte_familien = list({a.produkt_familie for a in gruppe})

        # --- Schritt 1: Finde Techniker die ALLE Geraete abdecken ---
        voll_abdeckend: list[tuple[str, dict[str, str]]] = []
        teil_abdeckend: list[tuple[str, list[Auftrag], list[Auftrag], dict[str, str]]] = []

        for tid in aktive_techniker:
            quals = matrix.get(tid, {})
            abgedeckt, nicht_abgedeckt = _tech_deckt_ab(quals, gruppe)

            if not abgedeckt:
                continue
            if not nicht_abgedeckt:
                voll_abdeckend.append((tid, quals))
            else:
                teil_abdeckend.append((tid, abgedeckt, nicht_abgedeckt, quals))

        # --- Schritt 2: Entscheidungsbaum ---

        if voll_abdeckend:
            # Mehrere Techniker decken alles ab → waehle den mit breitestem Portfolio
            # (= meisten relevanten Qualifikationen)
            if len(voll_abdeckend) == 1 or all(
                len(voll_abdeckend[0][1]) >= len(t[1]) for t in voll_abdeckend
            ):
                fall = "A"
            else:
                fall = "C"

            # Sortiere nach Anzahl der Qualifikationen (breitestes Portfolio zuerst)
            voll_abdeckend.sort(key=lambda x: len(x[1]), reverse=True)
            best_tid, best_quals = voll_abdeckend[0]

            qual_details = {
                a.produkt_familie: best_quals.get(a.produkt_familie, "?")
                for a in gruppe
            }
            familien_text = " + ".join(
                f"{pf} ({qual_details.get(pf, '?')})" for pf in benoetigte_familien
            )

            # Einsatzdauer aus labor_zeiten.csv berechnen
            try:
                from .einsatz_dauer import berechne_einsatz_dauer
                geraete_liste = [
                    {"produkt_familie": a.produkt_familie,
                     "geraete_typ": a.geraet_id,
                     "anzahl": a.anzahl_geraete}
                    for a in gruppe
                ]
                dauer_info = berechne_einsatz_dauer(geraete_liste, best_tid)
                gesamt = dauer_info.gesamt_std
                dauer_text = f"Gesamt: {dauer_info.gesamt_min}min ({gesamt:.1f}h)"
            except Exception:
                dauer = sum(_standard_einsatzdauer(a) for a in gruppe)
                ruestzeit = RUESTZEIT_PRO_GERAET_STD * (len(gruppe) - 1)
                gesamt = dauer + ruestzeit
                dauer_text = f"Gesamt: {gesamt:.1f}h (Schaetzung)"

            einsatz = EinsatzZuweisung(
                techniker_id=best_tid,
                auftraege=list(gruppe),
                abgedeckte_familien=benoetigte_familien,
                qualifikationen=qual_details,
                dauer_std=gesamt,
                begruendung=f"{best_tid} uebernimmt {familien_text}",
            )

            eingesparte = len(gruppe) - 1
            hinweis = (
                f"Klinik {klinik_name} — {len(gruppe)} Geraete faellig im {monat}:\n"
                f"  → {best_tid} uebernimmt {' + '.join(benoetigte_familien)} "
                f"({', '.join(f'{l} {f}' for f, l in qual_details.items())})\n"
                f"  → {dauer_text}\n"
                f"  → 1 Einsatz statt {len(gruppe)} — spart {eingesparte} Fahrt(en)"
            )

            ergebnisse.append(QualifizierterBuendelPlan(
                klinik_id=klinik_id,
                klinik_name=klinik_name,
                monat=monat,
                fall=fall,
                einsaetze=[einsatz],
                alle_auftraege=list(gruppe),
                eingesparte_fahrten=eingesparte,
                hinweis=hinweis,
            ))

        elif teil_abdeckend:
            # Fall B: Kein einzelner Techniker deckt alles ab → Aufteilung
            # Greedy: waehle Techniker der die meisten Auftraege abdeckt,
            # dann fuelle Rest auf
            teil_abdeckend.sort(key=lambda x: len(x[1]), reverse=True)

            einsaetze: list[EinsatzZuweisung] = []
            verbleibend = list(gruppe)
            zugewiesene_ids: set[str] = set()

            for tid, abgedeckt, _, quals in teil_abdeckend:
                if not verbleibend:
                    break
                # Nur Auftraege die noch nicht zugewiesen sind
                jetzt_abgedeckt = [a for a in abgedeckt if a.auftrag_id not in zugewiesene_ids]
                if not jetzt_abgedeckt:
                    continue

                familien = list({a.produkt_familie for a in jetzt_abgedeckt})
                qual_details = {
                    pf: quals.get(pf, "?") for pf in familien
                }

                try:
                    from .einsatz_dauer import berechne_einsatz_dauer
                    geraete_liste = [
                        {"produkt_familie": a.produkt_familie,
                         "geraete_typ": a.geraet_id,
                         "anzahl": a.anzahl_geraete}
                        for a in jetzt_abgedeckt
                    ]
                    dauer_info = berechne_einsatz_dauer(geraete_liste, tid)
                    teil_dauer = dauer_info.gesamt_std
                except Exception:
                    dauer = sum(_standard_einsatzdauer(a) for a in jetzt_abgedeckt)
                    ruestzeit = RUESTZEIT_PRO_GERAET_STD * max(0, len(jetzt_abgedeckt) - 1)
                    teil_dauer = dauer + ruestzeit

                einsaetze.append(EinsatzZuweisung(
                    techniker_id=tid,
                    auftraege=jetzt_abgedeckt,
                    abgedeckte_familien=familien,
                    qualifikationen=qual_details,
                    dauer_std=teil_dauer,
                    begruendung=f"{tid} uebernimmt {' + '.join(familien)}",
                ))

                for a in jetzt_abgedeckt:
                    zugewiesene_ids.add(a.auftrag_id)
                verbleibend = [a for a in verbleibend if a.auftrag_id not in zugewiesene_ids]

            if not einsaetze:
                continue

            # Fehlende Familien dokumentieren
            alle_abgedeckt = set()
            for e in einsaetze:
                alle_abgedeckt.update(e.abgedeckte_familien)
            fehlende = [f for f in benoetigte_familien if f not in alle_abgedeckt]

            eingesparte = max(0, len(gruppe) - len(einsaetze))
            fehlende_info = ""
            if fehlende:
                fehlende_info = f"\n  → OFFEN: {', '.join(fehlende)} — kein qualifizierter Techniker"
            if verbleibend:
                fehlende_info += (
                    f"\n  → {len(verbleibend)} Auftrag/Auftraege brauchen separaten Einsatz"
                )

            # Ermittle warum aufgeteilt wurde
            aufteilungsgruende: list[str] = []
            for e in einsaetze:
                nicht_abgedeckt_familien = [
                    f for f in benoetigte_familien if f not in e.abgedeckte_familien
                ]
                if nicht_abgedeckt_familien:
                    aufteilungsgruende.append(
                        f"{e.techniker_id} fehlt Qualifikation fuer: "
                        f"{', '.join(nicht_abgedeckt_familien)}"
                    )

            tech_zeilen = []
            for e in einsaetze:
                fam_text = " + ".join(
                    f"{f} ({e.qualifikationen.get(f, '?')})" for f in e.abgedeckte_familien
                )
                tech_zeilen.append(f"  → {e.techniker_id} uebernimmt {fam_text}")

            hinweis = (
                f"Klinik {klinik_name} — {len(gruppe)} Geraete faellig im {monat}:\n"
                + "\n".join(tech_zeilen)
                + fehlende_info
                + f"\n  → {len(einsaetze)} Einsaetze statt {len(gruppe)} "
                  f"— spart {eingesparte} Fahrt(en)"
            )

            ergebnisse.append(QualifizierterBuendelPlan(
                klinik_id=klinik_id,
                klinik_name=klinik_name,
                monat=monat,
                fall="B",
                einsaetze=einsaetze,
                alle_auftraege=list(gruppe),
                eingesparte_fahrten=eingesparte,
                hinweis=hinweis,
                aufteilungsgrund="; ".join(aufteilungsgruende) if aufteilungsgruende else None,
            ))

    ergebnisse.sort(key=lambda e: e.eingesparte_fahrten, reverse=True)
    return ergebnisse


# ---------------------------------------------------------------------------
# 3. Tour-Optimierung (Mehrere Kliniken pro Tag)
# ---------------------------------------------------------------------------

def optimiere_tagestouren(
    auftraege: list[Auftrag],
    techniker_id: str,
    max_tag_std: float = _MAX_TAG_NORMAL,
    uebernachtungen_diese_woche: int = 0,
) -> list[Tagestour]:
    """Plant optimierte Tagestouren fuer einen Techniker.

    Gruppiert Kliniken nach geografischer Naehe (< 50km Radius)
    und plant Tagestouren mit 2-3 Kliniken.

    Args:
        auftraege:      Offene Auftraege die geplant werden sollen.
        techniker_id:   Der Techniker, fuer den geplant wird.
        max_tag_std:    Maximale Tagesdauer in Stunden. Default: 8.0h.

    Returns:
        Liste von Tagestour-Vorschlaegen.
    """
    tech_coords = _lade_techniker_coords()
    klinik_coords = _lade_klinik_coords()

    if techniker_id not in tech_coords:
        return []

    tech_lat, tech_lon, tech_standort = tech_coords[techniker_id]

    # Nur Auftraege mit bekannter Klinik-Position
    gueltige: list[tuple[Auftrag, float, float, str]] = []
    for a in auftraege:
        if a.klinik_id and a.klinik_id in klinik_coords:
            lat, lon, name = klinik_coords[a.klinik_id]
            gueltige.append((a, lat, lon, name))

    if not gueltige:
        return []

    # Kliniken clustern: Greedy-Ansatz nach Naehe zum Techniker
    # Sortiere nach Distanz zum Techniker
    gueltige.sort(key=lambda x: _haversine_km(tech_lat, tech_lon, x[1], x[2]))

    touren: list[Tagestour] = []
    verwendet: set[str] = set()

    for auftrag, klat, klon, kname in gueltige:
        if auftrag.auftrag_id in verwendet:
            continue

        # Starte neue Tour mit dieser Klinik
        tour_kliniken = [{"klinik_id": auftrag.klinik_id, "klinik_name": kname,
                          "lat": klat, "lon": klon,
                          "distanz_km": _haversine_km(tech_lat, tech_lon, klat, klon)}]
        tour_auftraege = [auftrag]
        verwendet.add(auftrag.auftrag_id)

        # Suche nahe Kliniken (innerhalb CLUSTER_RADIUS_KM)
        for a2, lat2, lon2, name2 in gueltige:
            if a2.auftrag_id in verwendet:
                continue
            dist_zum_cluster = _haversine_km(klat, klon, lat2, lon2)
            if dist_zum_cluster <= CLUSTER_RADIUS_KM:
                # Pruefen ob Tour noch in Tageslimit passt
                onsite_bisher = sum(_standard_einsatzdauer(ta) for ta in tour_auftraege)
                onsite_neu = onsite_bisher + _standard_einsatzdauer(a2)
                # Fahrzeit: Techniker → erste Klinik + zwischen-Kliniken + letzte Klinik → Techniker
                fahrzeit_geschaetzt = (
                    _fahrzeit_std(_haversine_km(tech_lat, tech_lon, klat, klon))
                    + _fahrzeit_std(dist_zum_cluster)
                    + _fahrzeit_std(_haversine_km(lat2, lon2, tech_lat, tech_lon))
                )
                if onsite_neu + fahrzeit_geschaetzt <= max_tag_std:
                    tour_kliniken.append({"klinik_id": a2.klinik_id, "klinik_name": name2,
                                          "lat": lat2, "lon": lon2,
                                          "distanz_km": _haversine_km(tech_lat, tech_lon, lat2, lon2)})
                    tour_auftraege.append(a2)
                    verwendet.add(a2.auftrag_id)

                if len(tour_kliniken) >= 3:
                    break

        if len(tour_kliniken) < 2:
            continue

        # Fahrzeit berechnen: Techniker → K1 → K2 → ... → Techniker
        gesamt_fahrzeit = 0.0
        prev_lat, prev_lon = tech_lat, tech_lon
        for k in tour_kliniken:
            gesamt_fahrzeit += _fahrzeit_std(_haversine_km(prev_lat, prev_lon, k["lat"], k["lon"]))
            prev_lat, prev_lon = k["lat"], k["lon"]
        gesamt_fahrzeit += _fahrzeit_std(_haversine_km(prev_lat, prev_lon, tech_lat, tech_lon))

        onsite_gesamt = sum(_standard_einsatzdauer(a) for a in tour_auftraege)

        # Bereinige interne Felder aus kliniken-Dicts
        kliniken_clean = [
            {"klinik_id": k["klinik_id"], "klinik_name": k["klinik_name"],
             "distanz_km": round(k["distanz_km"], 1)}
            for k in tour_kliniken
        ]

        klinik_namen = [k["klinik_name"] for k in tour_kliniken]
        eingesparte = len(tour_kliniken) - 1
        region = ""
        try:
            df = pd.read_csv(_DATA_DIR / "kliniken.csv", dtype=str)
            row = df[df["klinik_id"] == tour_kliniken[0]["klinik_id"]]
            if not row.empty:
                region = f" in {row.iloc[0]['region']}"
        except Exception:
            pass

        hinweis = (
            f"{techniker_id} kann {len(tour_kliniken)} Kliniken{region} kombinieren "
            f"({', '.join(klinik_namen)}) — spart {eingesparte} Einzelfahrt(en)"
        )

        # Uebernachtungsregel
        fahrzeit_hin = _fahrzeit_std(tour_kliniken[0]["distanz_km"])
        uebernachtung_noetig = fahrzeit_hin > _UEBERNACHTUNG_TRIGGER_STD
        uebernachtungs_ausnahme = False
        uebernachtungs_kommentar: Optional[str] = None
        dashboard_warnung: Optional[str] = None

        if uebernachtung_noetig:
            kliniken_kombinierbar = len(tour_kliniken) >= 2
            ausnahme, kommentar = pruefe_uebernachtungs_ausnahme(
                fahrzeit_hin,
                uebernachtungen_diese_woche,
                kliniken_kombinierbar,
            )
            uebernachtungs_ausnahme = ausnahme
            if kommentar:
                uebernachtungs_kommentar = kommentar

            gesamt_uebernachtungen = uebernachtungen_diese_woche + 1
            if gesamt_uebernachtungen >= _MAX_UEBERNACHTUNGEN_AUSNAHME:
                dashboard_warnung = (
                    f"Warnung: {gesamt_uebernachtungen} Uebernachtungen diese Woche "
                    f"(Maximum: {_MAX_UEBERNACHTUNGEN_AUSNAHME})"
                )

        touren.append(Tagestour(
            techniker_id=techniker_id,
            datum=None,
            kliniken=kliniken_clean,
            auftraege=tour_auftraege,
            gesamtfahrzeit_std=round(gesamt_fahrzeit, 2),
            gesamtdauer_onsite_std=onsite_gesamt,
            gesamtdauer_tag_std=round(gesamt_fahrzeit + onsite_gesamt, 2),
            eingesparte_einzelfahrten=eingesparte,
            hinweis=hinweis,
            uebernachtung_noetig=uebernachtung_noetig,
            uebernachtungs_ausnahme=uebernachtungs_ausnahme,
            uebernachtungs_kommentar=uebernachtungs_kommentar,
            dashboard_warnung=dashboard_warnung,
        ))

    touren.sort(key=lambda t: t.eingesparte_einzelfahrten, reverse=True)
    return touren
