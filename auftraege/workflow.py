"""Empfehlungssystem fuer den Auftrags-Lifecycle.

WICHTIG: Dieses Modul erstellt AUSSCHLIESSLICH Empfehlungen.
Es weist keine Techniker zu und veraendert keinen Auftragsstatus.
Die Entscheidung liegt beim Disponenten oder Techniker.

Kapazitaetsmodell:
    Freitag = Home Office / Admintag → kein Außeneinsatz außer Repair-Notfall.
    Effektive Außendienst-Kapazitaet: Mo-Do = 4 x 8h = 32h/Woche pro Techniker.
    Auslastungs-Begruendung und Score-Rueckrechnung verwenden 32h als Wochenziel.

Oeffentliche API:
    empfehlung_generieren(auftrag, tages_status, heute) -> EmpfehlungsReport
    termin_verschieben(auftrag, grund, neuer_termin)    -> VerschiebungsErgebnis
    schlage_termine_vor(auftrag, techniker_id, ...)     -> list[TerminVorschlag]
    bewerte_repair_sla(auftrag, jetzt)                  -> RepairSlaBewertung
    repair_kontakt_herstellen(auftrag, techniker_id)    -> RepairSlaBewertung
    repair_einsatz_planen(auftrag, verfuegbarkeit)      -> date

Ablauf empfehlung_generieren:
    1. Dringlichkeit des Auftrags berechnen
    2. Top-3 Techniker per Scoring-Modul ermitteln
    3. Begruendungen und Hinweise pro Techniker generieren
    4. Klinik- und Geraeté-Kontextinfos zusammenstellen
    5. Fertigen EmpfehlungsReport zurueckgeben – Auftrag unveraendert

Terminverschiebung:
    Techniker kann ueber SMax Go einen Termin verschieben.
    Max 2 Verschiebungen pro Work Order → danach Warnung.
    Gruende: Klinik nicht erreichbar, Geraet nicht verfuegbar, eigene Verhinderung.
    Neuer Termin wird automatisch als naechstbester freier Slot geplant.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

import pandas as pd

from config import (
    PLANUNGSHORIZONT_TAGE,
    PLANUNGSHORIZONT_MIN,
    REPAIR_SLA_STUNDEN,
    REPAIR_ZIEL_STUNDEN,
    REPAIR_WARNUNG_STUNDEN,
    REPAIR_ESKALATION_STUNDEN,
    HAVERSINE_UMWEG_FAKTOR,
    HUGO_KA_IDS,
    HUGO_KA_ZIEL_STUNDEN,
    AUSSENDIENST_STUNDEN,
    PLANUNGSHORIZONT_WOCHEN,
    UMPLANUNGS_PRIORITAETEN,
    STK_PM_FAELLIGKEIT_MONATSGENAU,
    STK_PM_AUSNAHME_LETZTER_WERKTAG,
    STK_PM_ZYKLEN_MONATE,
    OP_KLINIK_TAGE,
)
from config import VORLAUF_STANDARD_TAGE  # noqa: F401
from techniker.scoring import TagesStatus, berechne_empfehlung
from .models import Auftrag, AuftragsTyp, RepairPhase

_DATA_DIR = Path(__file__).parent.parent / "daten"

# Fahrzeit-Konstanten (aus config.py)
_UMWEGFAKTOR = HAVERSINE_UMWEG_FAKTOR
_REISEGESCHWINDIGKEIT_KMH = 90.0

# Terminverschiebung
MAX_VERSCHIEBUNGEN_PRO_AUFTRAG = 2

PLANUNGSGRUENDE = [
    "Messmittel/Pruefmittel muessen 1-2 Tage vorher ins Fahrzeug geladen werden",
    "OP-Plan wird freitags fuer die naechste Woche geplant → Geraet evtl. nicht verfuegbar",
    "Kliniken brauchen Vorlaufzeit fuer Raumbuchung und Einschleusung",
    "Techniker muss Route und Uebernachtung planen",
    "Trunkstock-Check und Bestellung fehlender Teile",
]

# ---------------------------------------------------------------------------
# Repair SLA – Reaktionsplanung (getrennt von STK/PM Vorausplanung)
# ---------------------------------------------------------------------------

REPAIR_ZIEL_KONTAKT = REPAIR_ZIEL_STUNDEN  # Re-export fuer bestehende Imports

# SLA Eskalationsschwellen (aus config.py)
_REPAIR_SLA_GELB = REPAIR_ZIEL_STUNDEN        # Gelbe Warnung: Kundenkontakt steht aus
_REPAIR_SLA_ROT = REPAIR_WARNUNG_STUNDEN       # Rote Warnung: SLA-Gefaehrdung
_REPAIR_SLA_KRITISCH = REPAIR_ESKALATION_STUNDEN  # SLA verletzt → sofort eskalieren


class RepairSlaStatus(str, Enum):
    """SLA-Status eines Repair-Auftrags."""
    GRUEN = "Gruen"         # Kontakt hergestellt / innerhalb SLA
    GELB = "Gelb"           # > 24h, Kontakt ausstehend
    ROT = "Rot"             # > 40h, SLA-Gefaehrdung
    KRITISCH = "Kritisch"   # > 48h, SLA verletzt
    BLAU = "Blau"           # Ersatzteil unterwegs


@dataclass
class RepairSlaBewertung:
    """Ergebnis der SLA-Bewertung fuer einen Repair-Auftrag."""
    status: RepairSlaStatus
    stunden_seit_eingang: float
    stunden_verbleibend: float   # negativ = SLA verletzt
    kontakt_hergestellt: bool
    warnung: Optional[str]
    benachrichtigungen: list[str] = field(default_factory=list)


def bewerte_repair_sla(
    auftrag: Auftrag,
    jetzt: Optional[datetime] = None,
) -> RepairSlaBewertung:
    """Bewertet den SLA-Status eines Repair-Auftrags.

    Args:
        auftrag: Repair-Auftrag mit eingangsdatum.
        jetzt:   Aktueller Zeitpunkt (Default: datetime.now()).

    Returns:
        RepairSlaBewertung mit Status, Countdown und Warnungen.
    """
    if jetzt is None:
        jetzt = datetime.now()

    eingang = auftrag.eingangsdatum or jetzt
    stunden = (jetzt - eingang).total_seconds() / 3600.0
    verbleibend = REPAIR_SLA_STUNDEN - stunden
    kontakt = auftrag.kontakt_hergestellt_am is not None

    # Kontakt hergestellt → SLA erfuellt
    if kontakt:
        # Pruefen ob Ersatzteil unterwegs
        if auftrag.repair_phase == RepairPhase.ERSATZTEIL_BESTELLT:
            return RepairSlaBewertung(
                status=RepairSlaStatus.BLAU,
                stunden_seit_eingang=round(stunden, 1),
                stunden_verbleibend=round(verbleibend, 1),
                kontakt_hergestellt=True,
                warnung=None,
            )
        return RepairSlaBewertung(
            status=RepairSlaStatus.GRUEN,
            stunden_seit_eingang=round(stunden, 1),
            stunden_verbleibend=round(verbleibend, 1),
            kontakt_hergestellt=True,
            warnung=None,
        )

    # Kein Kontakt → Eskalation pruefen
    benachrichtigungen: list[str] = []

    if stunden >= _REPAIR_SLA_KRITISCH:
        warnung = (
            f"SLA VERLETZT — {round(stunden, 1)}h seit Eingang, "
            f"kein Kundenkontakt. Sofort eskalieren!"
        )
        benachrichtigungen.append(
            f"ESKALATION an Disponent: Repair {auftrag.auftrag_id} — "
            f"SLA 48h verletzt, kein Kundenkontakt seit {round(stunden, 1)}h"
        )
        return RepairSlaBewertung(
            status=RepairSlaStatus.KRITISCH,
            stunden_seit_eingang=round(stunden, 1),
            stunden_verbleibend=round(verbleibend, 1),
            kontakt_hergestellt=False,
            warnung=warnung,
            benachrichtigungen=benachrichtigungen,
        )

    if stunden >= _REPAIR_SLA_ROT:
        warnung = (
            f"SLA-Gefaehrdung! Noch {round(verbleibend, 1)}h bis SLA-Verletzung. "
            f"Kundenkontakt dringend herstellen."
        )
        return RepairSlaBewertung(
            status=RepairSlaStatus.ROT,
            stunden_seit_eingang=round(stunden, 1),
            stunden_verbleibend=round(verbleibend, 1),
            kontakt_hergestellt=False,
            warnung=warnung,
        )

    if stunden >= _REPAIR_SLA_GELB:
        warnung = (
            f"Kundenkontakt steht aus ({round(stunden, 1)}h seit Eingang). "
            f"Bitte Klinik kontaktieren."
        )
        return RepairSlaBewertung(
            status=RepairSlaStatus.GELB,
            stunden_seit_eingang=round(stunden, 1),
            stunden_verbleibend=round(verbleibend, 1),
            kontakt_hergestellt=False,
            warnung=warnung,
        )

    # Innerhalb SLA, noch kein Kontakt aber noch Zeit
    return RepairSlaBewertung(
        status=RepairSlaStatus.GRUEN,
        stunden_seit_eingang=round(stunden, 1),
        stunden_verbleibend=round(verbleibend, 1),
        kontakt_hergestellt=False,
        warnung=None,
    )


def repair_kontakt_herstellen(
    auftrag: Auftrag,
    techniker_id: str,
    jetzt: Optional[datetime] = None,
) -> RepairSlaBewertung:
    """Markiert einen Repair-Auftrag als 'Kontakt hergestellt'.

    Setzt repair_phase auf KONTAKT_HERGESTELLT und stoppt den SLA-Timer.

    Args:
        auftrag:      Der Repair-Auftrag.
        techniker_id: Techniker der den Kontakt hergestellt hat.
        jetzt:        Zeitpunkt des Kontakts (Default: datetime.now()).

    Returns:
        RepairSlaBewertung nach dem Kontakt.
    """
    if jetzt is None:
        jetzt = datetime.now()

    auftrag.kontakt_hergestellt_am = jetzt
    auftrag.repair_phase = RepairPhase.KONTAKT_HERGESTELLT
    if auftrag.techniker_id is None:
        auftrag.techniker_id = techniker_id

    return bewerte_repair_sla(auftrag, jetzt)


def repair_einsatz_planen(
    auftrag: Auftrag,
    ersatzteil_verfuegbarkeit: str,
    heute: Optional[date] = None,
) -> Optional[date]:
    """Plant den Repair-Einsatztermin basierend auf Ersatzteil-Verfuegbarkeit.

    Im Gegensatz zu STK/PM: kein fixer Vorlauf, kann auch kurzfristig sein.

    Args:
        auftrag:                  Der Repair-Auftrag.
        ersatzteil_verfuegbarkeit: "SOFORT", "LAGER", "BESTELLEN", "UNBEKANNT".
        heute:                    Referenzdatum (Default: date.today()).

    Returns:
        Vorgeschlagener Einsatztermin oder None wenn unklar.
    """
    if heute is None:
        heute = date.today()

    # Einsatztermin basierend auf Ersatzteil-Lieferzeit
    lieferzeit_map = {
        "SOFORT": 1,     # Morgen moeglich
        "LAGER": 2,      # Nach Lager-Lieferung
        "BESTELLEN": 5,  # Nach Bestellung
        "UNBEKANNT": 1,  # Diagnose-Einsatz morgen
    }
    min_tage = lieferzeit_map.get(ersatzteil_verfuegbarkeit, 2)

    # Repair hat KEINEN Mindest-Vorlauf von 3 Tagen
    return _naechster_werktag_ab(heute, min_tage=min_tage)


# Dringlichkeitsstufen: Tage bis zur Faelligkeit (negativ = ueberfaellig)
_TAGE_KRITISCH = 14    # < 14 Tage oder ueberfaellig → KRITISCH
_TAGE_HOCH = 30        # 15-30 Tage → HOCH
# > 30 Tage → NORMAL

# Hinweistexte fuer Disposition
_HINWEIS_KEIN_AUTO_ASSIGN = (
    "Empfehlung – keine automatische Zuweisung. "
    "Bitte Rueckbestaetigung durch Disponenten oder Techniker erforderlich."
)

# Ersatzteile-Schaetzlisten je Produktfamilie
# Platzhalter bis das Ersatzteilmodul (ersatzteile/) implementiert ist.
_ERSATZTEILE_HINWEISE: dict[str, list[str]] = {
    "Hugo":                 ["Drapemaster-Set (Einwegmaterial)", "Kalibrierkit Hugo RAS",
                             "Instrumentenhalter"],
    "Neuromonitoring":      ["NIM-Elektroden-Set (steril)", "Erdungselektrode",
                             "Stimulationsprobe"],
    "Neurophysiologie":     ["106E2 Elektroden-Kit", "NITRON Kalibrierkit"],
    "Beatmung":             ["Flowsensor 980X", "Exspirationsventil-Set", "O2-Zelle"],
    "Elektrochirurgie":     ["HF-Kabel FT10", "Neutralelektrode-Set", "Fussschalter"],
    "Kardiovaskulaer":      ["Programmier-Wand K-Adapter", "Batterietester PROG_2090"],
    "Kardiovaskulaer_Ablation": ["Ablationskatheter (Reserve)", "Mapping-Elektrode"],
    "Endoskopie":           ["Reinigungsbuerste ColonoscopyAI", "Sensorkit Endoskopie"],
    "Gastroenterologie":    ["Drucksensor MANOSCAN", "Kalibrierkit Manometrie"],
    "Navigation":           ["O-arm Kalibrierphantom", "Referenzrahmen-Set"],
    "Capnografie":          ["CO2-Sensor-Adapter", "Messschlauch-Set"],
    "Energie":              ["Handstuck-Adapter Energie", "Fussschalter"],
    "Wirbelsaeule":         ["Schraubendreher-Set Wirbel", "Messlehre"],
}


# ---------------------------------------------------------------------------
# Terminverschiebung
# ---------------------------------------------------------------------------

class VerschiebungsGrund(str, Enum):
    KLINIK_NICHT_ERREICHBAR = "Klinik nicht erreichbar"
    GERAET_NICHT_VERFUEGBAR = "Geraet nicht verfuegbar"
    EIGENE_VERHINDERUNG = "Eigene Verhinderung"
    OPPLAN_KONFLIKT = "OP-Plan Konflikt"
    MESSMITTEL_FEHLT = "Messmittel nicht verfuegbar"
    SONSTIGES = "Sonstiges"


@dataclass
class TerminHistorie:
    """Einzelner Eintrag in der Verschiebungshistorie."""
    urspruenglicher_termin: date
    neuer_termin: date
    grund: VerschiebungsGrund
    verschoben_am: datetime
    verschoben_von: str  # techniker_id


@dataclass
class VerschiebungsErgebnis:
    """Ergebnis einer Terminverschiebung."""
    erfolg: bool
    auftrag_id: str
    alter_termin: date
    neuer_termin: Optional[date]
    grund: VerschiebungsGrund
    verschiebung_nummer: int  # 1-basiert
    warnung: Optional[str] = None
    benachrichtigungen: list[str] = field(default_factory=list)


# In-Memory-Speicher fuer Verschiebungshistorien (pro Auftrag-ID)
_verschiebungs_historie: dict[str, list[TerminHistorie]] = {}


def _ist_werktag_mo_do(d: date) -> bool:
    """True wenn Mo-Do (kein Freitag, kein Wochenende)."""
    return d.weekday() <= 3  # Mo=0 bis Do=3


def _naechster_werktag_ab(ab_datum: date, min_tage: int = 1) -> date:
    """Gibt den naechsten Werktag (Mo-Do) ab ab_datum + min_tage zurueck."""
    kandidat = ab_datum + timedelta(days=min_tage)
    for _ in range(14):
        if _ist_werktag_mo_do(kandidat):
            return kandidat
        kandidat += timedelta(days=1)
    return kandidat


def _naechster_freier_slot(ab_datum: date) -> date:
    """Gibt den naechsten Werktag (Mo-Do) ab ab_datum zurueck."""
    return _naechster_werktag_ab(ab_datum, min_tage=1)


def termin_verschieben(
    auftrag: Auftrag,
    grund: VerschiebungsGrund,
    neuer_termin: Optional[date] = None,
    verschoben_von: Optional[str] = None,
) -> VerschiebungsErgebnis:
    """Verschiebt den Termin eines Auftrags.

    Args:
        auftrag:         Der zu verschiebende Auftrag (wird in-place aktualisiert).
        grund:           Grund fuer die Verschiebung (SMax Go Status).
        neuer_termin:    Gewuenschter neuer Termin. Default: naechster freier Slot.
        verschoben_von:  techniker_id des Verschiebenden. Default: auftrag.techniker_id.

    Returns:
        VerschiebungsErgebnis mit Erfolg/Warnung und Benachrichtigungsliste.
    """
    aid = auftrag.auftrag_id
    if verschoben_von is None:
        verschoben_von = auftrag.techniker_id or "SYSTEM"

    # Bisherige Verschiebungen pruefen
    historie = _verschiebungs_historie.get(aid, [])
    verschiebung_nr = len(historie) + 1

    # Max 2 Verschiebungen: bei 3. Verschiebung Warnung + trotzdem durchfuehren
    warnung = None
    if len(historie) >= MAX_VERSCHIEBUNGEN_PRO_AUFTRAG:
        warnung = (
            f"WARNUNG: Auftrag {aid} wurde bereits {len(historie)}x verschoben "
            f"(Maximum {MAX_VERSCHIEBUNGEN_PRO_AUFTRAG}). "
            f"Bitte Ursache pruefen und ggf. eskalieren."
        )

    alter_termin = auftrag.faelligkeitsdatum

    # Grund-spezifische Neuterminierung
    if neuer_termin is None:
        heute = date.today()
        if grund == VerschiebungsGrund.OPPLAN_KONFLIKT:
            # OP-Plan Konflikt → fruehestens uebernachste Woche (Mo)
            tage_bis_montag = (7 - heute.weekday()) % 7
            naechster_montag = heute + timedelta(days=tage_bis_montag or 7)
            uebernachste_woche = naechster_montag + timedelta(days=7)
            neuer_termin = _naechster_werktag_ab(uebernachste_woche, min_tage=0)
        elif grund == VerschiebungsGrund.MESSMITTEL_FEHLT:
            # Messmittel fehlt → heute + 3 Werktage
            neuer_termin = _naechster_werktag_ab(heute, min_tage=3)
        else:
            neuer_termin = _naechster_freier_slot(alter_termin)

    # Auftrag aktualisieren
    auftrag.faelligkeitsdatum = neuer_termin

    # Grund-spezifische Seiteneffekte
    zusatz_hinweise: list[str] = []
    if grund == VerschiebungsGrund.OPPLAN_KONFLIKT:
        zusatz_hinweise.append(f"Klinik {auftrag.klinik_name} als op_kritisch markiert")
        zusatz_hinweise.append(f"Notiz in Work Order {aid}: OP-Plan Konflikt")
    elif grund == VerschiebungsGrund.MESSMITTEL_FEHLT:
        zusatz_hinweise.append(f"Trunkstock-Warnung fuer Auftrag {aid}: Messmittel pruefen")

    # Historie speichern
    eintrag = TerminHistorie(
        urspruenglicher_termin=alter_termin,
        neuer_termin=neuer_termin,
        grund=grund,
        verschoben_am=datetime.now(),
        verschoben_von=verschoben_von,
    )
    if aid not in _verschiebungs_historie:
        _verschiebungs_historie[aid] = []
    _verschiebungs_historie[aid].append(eintrag)

    # Benachrichtigungen generieren
    benachrichtigungen = [
        f"Mail an Techniker {verschoben_von}: Termin {aid} verschoben "
        f"von {alter_termin.isoformat()} auf {neuer_termin.isoformat()} "
        f"(Grund: {grund.value})",
        f"Mail an Klinik {auftrag.klinik_name}: Neuer Termin {neuer_termin.isoformat()} "
        f"fuer Auftrag {aid}",
    ] + zusatz_hinweise

    return VerschiebungsErgebnis(
        erfolg=True,
        auftrag_id=aid,
        alter_termin=alter_termin,
        neuer_termin=neuer_termin,
        grund=grund,
        verschiebung_nummer=verschiebung_nr,
        warnung=warnung,
        benachrichtigungen=benachrichtigungen,
    )


def verschiebungs_historie_abfragen(auftrag_id: str) -> list[TerminHistorie]:
    """Gibt die Verschiebungshistorie fuer einen Auftrag zurueck."""
    return list(_verschiebungs_historie.get(auftrag_id, []))


def _verschiebungs_historie_reset() -> None:
    """Setzt die Historie zurueck (nur fuer Tests)."""
    _verschiebungs_historie.clear()


# ---------------------------------------------------------------------------
# Vorausschauende Terminplanung
# ---------------------------------------------------------------------------

@dataclass
class TerminVorschlag:
    """Ein einzelner Terminvorschlag mit Begruendung."""
    datum: date
    wochentag: str          # "Mo", "Di", "Mi", "Do"
    vorlauf_tage: int       # Werktage ab heute
    bewertung: str          # "optimal", "moeglich", "knapp"
    hinweise: list[str]


def _lade_klinik_op_attribute(klinik_id: Optional[str]) -> dict:
    """Laedt OP-kritisch Attribute einer Klinik aus kliniken.csv."""
    defaults = {"op_kritisch": False, "vorlauf_tage": PLANUNGSHORIZONT_MIN, "op_plan_tag": "Freitag"}
    if not klinik_id:
        return defaults
    try:
        df = pd.read_csv(_DATA_DIR / "kliniken.csv", dtype=str)
        match = df[df["klinik_id"] == klinik_id]
        if match.empty:
            return defaults
        row = match.iloc[0]
        return {
            "op_kritisch": str(row.get("op_kritisch", "False")).strip() == "True",
            "vorlauf_tage": int(row.get("vorlauf_tage", PLANUNGSHORIZONT_MIN)),
            "op_plan_tag": str(row.get("op_plan_tag", "Freitag")).strip(),
        }
    except Exception:
        return defaults


def _werktage_ab(start: date, anzahl: int) -> list[date]:
    """Gibt die naechsten N Werktage (Mo-Do) ab start (exklusive) zurueck."""
    result: list[date] = []
    kandidat = start
    for _ in range(anzahl * 3):  # grosszuegiger Suchraum
        kandidat += timedelta(days=1)
        if _ist_werktag_mo_do(kandidat):
            result.append(kandidat)
            if len(result) >= anzahl:
                break
    return result


def schlage_termine_vor(
    auftrag: Auftrag,
    techniker_id: Optional[str] = None,
    tages_status: Optional[dict[str, TagesStatus]] = None,
    heute: Optional[date] = None,
    max_vorschlaege: int = 3,
) -> list[TerminVorschlag]:
    """Schlaegt 3 moegliche Termine in den naechsten 7 Werktagen vor.

    Pruefungen pro Terminvorschlag:
      a) Werktag Mo-Do? (kein Freitag = Home Office)
      b) Techniker-Kapazitaet < 32h (bzw. 25.6h Hugo KA)?
      c) OP-kritische Klinik → nur Mo/Di/Mi
      d) Kein anderer Einsatz in gleicher Klinik diese Woche (Buendelungs-Check)
      e) Uebernachtungsregel (max 1/Woche)

    Args:
        auftrag:         Der zu planende Auftrag.
        techniker_id:    Techniker fuer Kapazitaetspruefung (optional).
        tages_status:    Aktueller Arbeitszeitstatus (optional).
        heute:           Referenzdatum (Default: date.today()).
        max_vorschlaege: Anzahl Vorschlaege (Default: 3).

    Returns:
        Liste von TerminVorschlag (max 3), leer wenn kein Termin moeglich.
    """
    if heute is None:
        heute = date.today()

    klinik_attr = _lade_klinik_op_attribute(auftrag.klinik_id)
    op_kritisch = klinik_attr["op_kritisch"]
    vorlauf = klinik_attr["vorlauf_tage"]

    # Alle Werktage im Planungshorizont sammeln (ab Mindestvorlauf)
    alle_werktage = _werktage_ab(heute, PLANUNGSHORIZONT_TAGE + 4)
    # Nur Tage ab Mindestvorlauf beruecksichtigen
    min_datum = _naechster_werktag_ab(heute, min_tage=PLANUNGSHORIZONT_MIN)
    kandidaten = [d for d in alle_werktage if d >= min_datum]
    # Auf Planungshorizont begrenzen
    max_datum = _naechster_werktag_ab(heute, min_tage=PLANUNGSHORIZONT_TAGE + PLANUNGSHORIZONT_MIN)
    kandidaten = [d for d in kandidaten if d <= max_datum]

    _WOCHENTAG_NAMEN = {0: "Mo", 1: "Di", 2: "Mi", 3: "Do"}

    # Kapazitaet pruefen (einfach: Wochenstunden aus tages_status)
    _hugo_ka_set = set(HUGO_KA_IDS)
    kapazitaet_ok = True
    if techniker_id and tages_status and techniker_id in tages_status:
        st = tages_status[techniker_id]
        woche_ziel = HUGO_KA_ZIEL_STUNDEN if techniker_id in _hugo_ka_set else float(AUSSENDIENST_STUNDEN)
        kapazitaet_ok = st.wochenstunden_aktuell < woche_ziel

    vorschlaege: list[TerminVorschlag] = []

    for kandidat in kandidaten:
        if len(vorschlaege) >= max_vorschlaege:
            break

        hinweise: list[str] = []

        # c) OP-kritisch: Mo–Do erlaubt (Fr = OP-Plan gesperrt)
        if op_kritisch and kandidat.weekday() not in OP_KLINIK_TAGE:
            continue

        # Vorlauf-Tage berechnen (Werktage ab heute)
        werktage_vorlauf = sum(
            1 for d in _werktage_ab(heute, 20) if d <= kandidat
        )

        # Bewertung
        if werktage_vorlauf >= vorlauf:
            bewertung = "optimal"
        elif werktage_vorlauf >= PLANUNGSHORIZONT_MIN:
            bewertung = "moeglich"
        else:
            bewertung = "knapp"

        # Hinweise generieren
        if op_kritisch:
            hinweise.append("OP-kritische Klinik: nur Mo-Do moeglich")
        if not kapazitaet_ok:
            hinweise.append("Techniker-Kapazitaet pruefen (Wochenziel erreicht)")
            bewertung = "knapp"
        if werktage_vorlauf >= vorlauf:
            hinweise.append(f"Vorlauf {werktage_vorlauf} Werktage — Messmittel-Vorbereitung moeglich")

        vorschlaege.append(TerminVorschlag(
            datum=kandidat,
            wochentag=_WOCHENTAG_NAMEN.get(kandidat.weekday(), "?"),
            vorlauf_tage=werktage_vorlauf,
            bewertung=bewertung,
            hinweise=hinweise,
        ))

    return vorschlaege


# ---------------------------------------------------------------------------
# Report-Datenklassen
# ---------------------------------------------------------------------------

@dataclass
class Dringlichkeit:
    """Bewertung der zeitlichen Dringlichkeit eines Auftrags."""

    stufe: str           # "ÜBERFÄLLIG" | "KRITISCH" | "HOCH" | "NORMAL"
    begruendung: str
    tage_bis_faelligkeit: int  # negativ = ueberfaellig seit N Tagen


@dataclass
class TechnikerEmpfehlung:
    """Einzelne Techniker-Empfehlung mit vollstaendiger Begruendung."""

    rang: int                    # 1 = beste Empfehlung
    techniker_id: str
    techniker_standort: str      # Heimatort aus techniker.csv (kein Name-Feld vorhanden)
    score: float                 # Gesamtscore 0-100
    level: str                   # "L2" oder "L3"
    kompetenz_begruendung: str   # z.B. "L3 – selbststaendig einsetzbar"
    naehe_begruendung: str       # z.B. "~45 km, ca. 36 min Fahrzeit"
    auslastung_begruendung: str  # z.B. "28,0 h / 32 h Wochenziel Mo-Do (87 %)"
    fahrzeit_minuten: int
    distanz_km: float
    warnungen: list[str]
    hinweise: list[str]          # Kontexthinweise fuer den Disponenten


@dataclass
class EmpfehlungsReport:
    """Vollstaendiger Empfehlungsbericht fuer einen Serviceauftrag.

    Der Auftrag selbst wird NICHT veraendert (status bleibt NEU,
    techniker_id bleibt None) bis eine explizite Bestaetigung erfolgt.
    """

    auftrag_id: str
    erstellt_am: datetime

    # 1. Auftragsdaten
    auftrag: Auftrag
    dringlichkeit: Dringlichkeit

    # 2. Top-3 Techniker-Empfehlungen (nach Score absteigend)
    empfehlungen: list[TechnikerEmpfehlung]

    # 3. Kontext fuer den Techniker
    geraetestandort: dict
    kundenkontakt: dict
    letzte_wartung: Optional[dict]   # None wenn keine Daten vorhanden
    offene_punkte: list[str]
    ersatzteile_schaetzung: list[dict]  # [{"bezeichnung": str, "quelle": str}]

    # Disposition-Hinweis (immer gesetzt)
    hinweis_disposition: str

    def hat_empfehlungen(self) -> bool:
        """True wenn mindestens ein qualifizierter Techniker gefunden wurde."""
        return len(self.empfehlungen) > 0

    def beste_empfehlung(self) -> Optional[TechnikerEmpfehlung]:
        """Gibt die Empfehlung mit dem hoechsten Score zurueck, oder None."""
        return self.empfehlungen[0] if self.empfehlungen else None


# ---------------------------------------------------------------------------
# Interne Hilfsfunktionen
# ---------------------------------------------------------------------------

def _lade_techniker_standorte() -> dict[str, dict[str, str]]:
    """Gibt {techniker_id: {"standort": str, "region": str}} zurueck."""
    df = pd.read_csv(_DATA_DIR / "techniker.csv", dtype=str)
    return {
        row["techniker_id"]: {"standort": row["standort"], "region": row["region"]}
        for _, row in df.iterrows()
    }


def _lade_klinik_details(klinik_id: str) -> Optional[pd.Series]:
    df = pd.read_csv(_DATA_DIR / "kliniken.csv", dtype=str)
    match = df[df["klinik_id"] == klinik_id]
    return match.iloc[0] if not match.empty else None


def _lade_geraet_zeile(klinik_name: str, geraet_id: str) -> Optional[pd.Series]:
    """Sucht in geraete.csv nach klinik_name + produkt_modell fuer STK-Zyklus-Daten."""
    try:
        df = pd.read_csv(_DATA_DIR / "geraete.csv", comment="#", dtype=str).fillna("")
    except Exception:
        return None
    norm = klinik_name.lower().strip()
    match = df[
        (df["klinik_name"].str.lower().str.strip() == norm)
        & (df["produkt_modell"].str.strip() == geraet_id)
    ]
    return match.iloc[0] if not match.empty else None


def _fahrzeit_minuten(distanz_km: float) -> int:
    """Geschaetzte Fahrtzeit in ganzen Minuten."""
    return round(distanz_km * _UMWEGFAKTOR / _REISEGESCHWINDIGKEIT_KMH * 60)


def _berechne_dringlichkeit(faelligkeitsdatum: date, heute: Optional[date] = None) -> Dringlichkeit:
    """Klassifiziert die zeitliche Dringlichkeit anhand von Tagen bis zur Faelligkeit.

    Stufen:
        UEBERFAELLIG : ueberfaellig (tage < 0)
        KRITISCH     : faellig in <= 14 Tagen
        HOCH         : faellig in 15-30 Tagen
        NORMAL       : faellig in > 30 Tagen

    Args:
        faelligkeitsdatum: Geplantes STK-Datum.
        heute: Referenzdatum fuer Tests (Default: date.today()).
    """
    if heute is None:
        heute = date.today()
    tage = (faelligkeitsdatum - heute).days  # negativ = ueberfaellig

    if tage < 0:
        return Dringlichkeit(
            stufe="\u00dcBERF\u00c4LLIG",
            begruendung=f"STK seit {-tage} Tagen ueberfaellig – sofortiger Handlungsbedarf.",
            tage_bis_faelligkeit=tage,
        )
    if tage <= _TAGE_KRITISCH:
        return Dringlichkeit(
            stufe="KRITISCH",
            begruendung=f"STK faellig in {tage} Tag(en) – sofort einplanen.",
            tage_bis_faelligkeit=tage,
        )
    if tage <= _TAGE_HOCH:
        return Dringlichkeit(
            stufe="HOCH",
            begruendung=f"STK faellig in {tage} Tag(en) – zeitnah einplanen.",
            tage_bis_faelligkeit=tage,
        )
    return Dringlichkeit(
        stufe="NORMAL",
        begruendung=f"STK faellig in {tage} Tagen – regulaere Planung.",
        tage_bis_faelligkeit=tage,
    )


def _kompetenz_begruendung(level: str, produkt_familie: str, auftrag_typ: str = "STK") -> str:
    from techniker.scoring import SMALL_CAPITAL_STK_L2_REICHT
    texte = {
        "L3": "L3 – selbststaendig einsetzbar",
        "L2": "L2 – Assistenz-Level (benoetigt L3-Begleitung)",
    }
    basis = texte.get(level, f"{level} – unbekanntes Level")
    if produkt_familie.lower() == "hugo" and level == "L3":
        basis += " | Hugo-Pflichtvoraussetzung erfuellt"
    if level == "L2" and produkt_familie in SMALL_CAPITAL_STK_L2_REICHT and auftrag_typ.upper() == "STK":
        basis = "L2 – vollwertig einsetzbar (Small Capital STK)"
    return basis


def _auslastung_begruendung(
    auslastung_score: float,
    techniker_id: str,
    tages_status: Optional[dict[str, TagesStatus]],
) -> str:
    if tages_status and techniker_id in tages_status:
        st = tages_status[techniker_id]
        prozent = round(st.wochenstunden_aktuell / 32.0 * 100)
        return (
            f"{st.wochenstunden_aktuell:.1f} h / 32 h Wochenziel (Mo-Do Aussendienst) "
            f"({prozent} % – Echtzeit)"
        )
    # Kein Echtzeit-Status: Score rueckrechnen (0h=100, 32h Außendienst-Ziel=0)
    stunden_inferiert = round((1.0 - auslastung_score / 100.0) * 32.0, 1)
    return (
        f"Schaetzung: ~{stunden_inferiert} h / 32 h Aussendienst-Ziel (Mo-Do) "
        f"(kein Echtzeit-Auslastungsstatus uebergeben)"
    )


def _naehe_begruendung(distanz_km: float, minuten: int) -> str:
    return f"~{round(distanz_km)} km Luftlinie, ca. {minuten} min Fahrzeit"


def _hinweise_generieren(
    techniker_id: str,
    level: str,
    produkt_familie: str,
    auslastung_score: float,
    klinik_region: Optional[str],
    techniker_region: str,
) -> list[str]:
    """Erstellt kontextbezogene Hinweise fuer einen Techniker."""
    hinweise: list[str] = []

    # Regionsmatch (techniker Region "NRW-West" passt zu klinik Region "NRW" etc.)
    if klinik_region and (
        techniker_region.startswith(klinik_region)
        or klinik_region.startswith(techniker_region.split("-")[0])
    ):
        hinweise.append(f"Heimregion des Technikers: {techniker_region}")

    # Hugo-Spezialregel
    if produkt_familie.lower() == "hugo":
        if level == "L3":
            hinweise.append("Hugo-zertifiziert (L3-Pflicht erfuellt gemaess CLAUDE.md)")
        else:
            hinweise.append("WARNUNG: Hugo erfordert L3 – dieser Techniker ist nicht einsetzbar")

    # Verfuegbarkeit
    if auslastung_score >= 80:
        hinweise.append("Gut verfuegbar (Auslastung < 50 % des Wochenziels)")
    elif auslastung_score <= 20:
        hinweise.append("Hohe Auslastung – Kapazitaet pruefen")

    # L2 Begleitung noetig
    if level == "L2":
        hinweise.append("L2: Einsatz nur mit qualifiziertem L3-Kollegen moeglich")

    # Keine Servicehistorie (wird hier immer gesetzt, bis Historien-Modul existiert)
    hinweise.append("Servicehistorie fuer dieses Geraet: nicht im System erfasst")

    return hinweise


def _geraetestandort_dict(klinik_id: Optional[str], klinik_name: str) -> dict:
    klinik = _lade_klinik_details(klinik_id) if klinik_id else None
    return {
        "klinik_name": klinik_name,
        "klinik_id": klinik_id,
        "plz": klinik["plz"] if klinik is not None else None,
        "stadt": klinik["stadt"] if klinik is not None else None,
        "groesse": klinik["groesse"] if klinik is not None else None,
        "hugo_standort": klinik["hugo_standort"] if klinik is not None else None,
    }


def _kundenkontakt_dict(klinik_id: Optional[str], klinik_name: str) -> dict:
    return {
        "klinik_name": klinik_name,
        "klinik_id": klinik_id,
        "ansprechpartner": "Bitte aus SMax laden (kein Kontaktfeld in kliniken.csv)",
        "smax_url": (
            f"https://smax.medtronic.de/accounts/{klinik_id}" if klinik_id else None
        ),
    }


def _letzte_wartung_dict(auftrag: Auftrag) -> Optional[dict]:
    """
    Schaetzt das letzte Wartungsdatum aus STK-Zyklus und naechstem Faelligkeitsdatum.
    Gibt None zurueck wenn keine Geraeté-Zeile in geraete.csv gefunden wurde.
    """
    zeile = _lade_geraet_zeile(auftrag.klinik_name, auftrag.geraet_id)
    if zeile is None:
        return None
    try:
        zyklus = int(zeile["stk_zyklus_jahre"])
    except (ValueError, KeyError):
        return None

    # Letztes STK war stk_zyklus_jahre vor dem naechsten Faelligkeitsdatum
    naechstes = auftrag.faelligkeitsdatum
    letztes_jahr = naechstes.year - zyklus
    letztes_datum = naechstes.replace(year=letztes_jahr)

    return {
        "schaetzdatum": letztes_datum.isoformat(),
        "methode": f"Berechnet: naechste Faelligkeit − {zyklus} Jahr(e) STK-Zyklus",
        "techniker_id": None,   # keine Historien-Daten vorhanden
        "hinweis": "Echte Wartungshistorie nicht im System – Ersatzteilmodul in Entwicklung",
    }


def _ersatzteile_schaetzung(produkt_familie: str) -> list[dict]:
    """Gibt Ersatzteil-Hinweise fuer eine Produktfamilie zurueck.

    Quellstatus: Schatzeung basierend auf Produktfamilie.
    Echte Stuecklisten kommen spaeter aus dem Ersatzteilmodul.
    """
    hinweise = _ERSATZTEILE_HINWEISE.get(produkt_familie, [])
    if not hinweise:
        return [{
            "bezeichnung": "Keine Schatzung verfuegbar",
            "quelle": f"Produktfamilie '{produkt_familie}' nicht in Hinweisliste",
        }]
    return [
        {"bezeichnung": h, "quelle": "Schatzeung (Ersatzteilmodul in Entwicklung)"}
        for h in hinweise
    ]


# ---------------------------------------------------------------------------
# Horizont-Filter und Deduplizierung
# ---------------------------------------------------------------------------

def filtere_nach_horizont(
    auftraege: list[Auftrag],
    horizont_wochen: Optional[int] = None,
    heute: Optional[date] = None,
) -> list[Auftrag]:
    """Filtert Auftraege auf den konfigurierten Planungshorizont.

    Args:
        auftraege:       Alle offenen Auftraege.
        horizont_wochen: Planungshorizont in Wochen (Default: PLANUNGSHORIZONT_WOCHEN = 6).
        heute:           Referenzdatum (Default: date.today()).

    Returns:
        Auftraege mit faelligkeitsdatum zwischen heute und heute + horizont.
    """
    if horizont_wochen is None:
        horizont_wochen = PLANUNGSHORIZONT_WOCHEN
    if heute is None:
        heute = date.today()
    bis = heute + timedelta(weeks=horizont_wochen)
    return [a for a in auftraege if heute <= a.faelligkeitsdatum <= bis]


def dedupliziere_auftraege(
    bestehende: list[Auftrag],
    neue: list[Auftrag],
) -> tuple[list[Auftrag], int, int]:
    """Bereinigt neue Auftraege um Duplikate gegen die bestehende Liste.

    Primaerschluessel: geraet_id + faelligkeitsdatum + produkt_familie
    (entspricht SMax-Feldern: Seriennummer + Next_PM_Due_Date + Model_Code)

    Args:
        bestehende: Bereits vorhandene Auftraege.
        neue:       Neu einzulesende Auftraege (z.B. aus SMax-CSV-Export).

    Returns:
        (bereinigte_liste, anzahl_duplikate, anzahl_neu)
        bereinigte_liste = bestehende + nicht-doppelte neue Auftraege.
    """
    bekannte_keys: set[tuple] = {
        (a.geraet_id, a.faelligkeitsdatum, a.produkt_familie)
        for a in bestehende
    }
    bereinigte = list(bestehende)
    anzahl_duplikate = 0
    anzahl_neu = 0

    for a in neue:
        key = (a.geraet_id, a.faelligkeitsdatum, a.produkt_familie)
        if key in bekannte_keys:
            anzahl_duplikate += 1
        else:
            bereinigte.append(a)
            bekannte_keys.add(key)
            anzahl_neu += 1

    return bereinigte, anzahl_duplikate, anzahl_neu


# ---------------------------------------------------------------------------
# STK/PM Faelligkeitspruefung (monatsgenau wie TUeV)
# ---------------------------------------------------------------------------

def _letzter_werktag_mo_fr_des_monats(d: date) -> date:
    """Letzter Werktag (Mo-Do) des Monats von d. Freitag = Home Office."""
    if d.month == 12:
        naechster_monat_erster = date(d.year + 1, 1, 1)
    else:
        naechster_monat_erster = date(d.year, d.month + 1, 1)
    letzter = naechster_monat_erster - timedelta(days=1)
    while letzter.weekday() > 3:  # Fr=4, Sa=5, So=6 → zurueck
        letzter -= timedelta(days=1)
    return letzter


def _erster_werktag_mo_fr_naechsten_monats(d: date) -> date:
    """Erster Werktag (Mo-Do) des Folgemonats von d. Freitag = Home Office."""
    if d.month == 12:
        erster = date(d.year + 1, 1, 1)
    else:
        erster = date(d.year, d.month + 1, 1)
    while erster.weekday() > 3:  # Fr=4, Sa=5, So=6 → vorwaerts
        erster += timedelta(days=1)
    return erster


def get_stk_pm_zyklus(model_code: str) -> int:
    """Gibt den STK/PM-Wartungszyklus in Monaten fuer eine Produktfamilie zurueck.

    Lookup in STK_PM_ZYKLEN_MONATE aus config.py.
    Kein Match → default 12 Monate.

    Args:
        model_code: Produktfamilien-Bezeichnung (z.B. 'PROG', 'Hugo', 'Mazor').

    Returns:
        Zyklus in Monaten (int).
    """
    return STK_PM_ZYKLEN_MONATE.get(model_code, STK_PM_ZYKLEN_MONATE['default'])


def pruefe_stk_pm_faelligkeit(
    auftrag: Auftrag,
    geplantes_datum: date,
) -> tuple[bool, str]:
    """Prueft ob ein geplantes Datum mit der STK/PM-Faelligkeit vereinbar ist.

    Gueltig wenn geplantes_datum im selben Monat wie faelligkeitsdatum.
    Ausnahme (STK_PM_AUSNAHME_LETZTER_WERKTAG): faelligkeitsdatum = letzter Werktag
    des Monats → erster Werktag des Folgemonats ist ebenfalls erlaubt.

    Der produktspezifische Zyklus wird via get_stk_pm_zyklus(produkt_familie)
    ermittelt und in der Begruendung ausgegeben.
    Naechste Faelligkeit = faelligkeitsdatum + zyklus_monate.

    Returns:
        (gueltig, grund)
    """
    if not STK_PM_FAELLIGKEIT_MONATSGENAU:
        return True, "Monatsgenau-Pruefung deaktiviert"

    zyklus_monate = get_stk_pm_zyklus(auftrag.produkt_familie)
    faelligkeit = auftrag.faelligkeitsdatum

    if (geplantes_datum.year == faelligkeit.year
            and geplantes_datum.month == faelligkeit.month):
        return True, (
            f"Geplantes Datum im Faelligkeitsmonat ({faelligkeit.strftime('%Y-%m')}, "
            f"Zyklus {zyklus_monate} Monate)"
        )

    if STK_PM_AUSNAHME_LETZTER_WERKTAG:
        letzter_wt = _letzter_werktag_mo_fr_des_monats(faelligkeit)
        if faelligkeit == letzter_wt:
            erster_folge = _erster_werktag_mo_fr_naechsten_monats(faelligkeit)
            if geplantes_datum == erster_folge:
                return True, (
                    f"Ausnahme: Faelligkeit am letzten Werktag ({faelligkeit.isoformat()}) "
                    f"→ erster Werktag des Folgemonats ({geplantes_datum.isoformat()}) erlaubt "
                    f"(Zyklus {zyklus_monate} Monate)"
                )

    return False, (
        f"STK/PM nur monatsgenau planbar (wie TUeV): "
        f"Faelligkeit {faelligkeit.strftime('%Y-%m')}, "
        f"geplantes Datum {geplantes_datum.strftime('%Y-%m')} "
        f"(Zyklus {zyklus_monate} Monate)"
    )


# ---------------------------------------------------------------------------
# Umplanung
# ---------------------------------------------------------------------------

UMWEGZEIT_ROUTE_MAX_MIN = 30.0  # Haversine-Umwegzeit-Schwelle fuer "auf Route"


@dataclass
class UmplanungsErgebnis:
    """Ergebnis einer Umplanungspruefung."""
    aktion: str             # 'einplanen' | 'verwerfen' | 'warten_auf_lieferzeit'
    begruendung: str
    betroffene_tour: Optional[object] = None  # Tagestour-Objekt oder None


def _bestimme_prioritaet_auftrag(auftrag: Auftrag, heute: date) -> int:
    """Bestimmt die Umplanungs-Prioritaet eines bestehenden Auftrags."""
    if auftrag.auftragstyp == AuftragsTyp.REPAIR:
        return UMPLANUNGS_PRIORITAETEN['REPAIR_OHNE_ET']
    if auftrag.faelligkeitsdatum < heute:
        return UMPLANUNGS_PRIORITAETEN['STK_PM_UEBERFAELLIG']
    return UMPLANUNGS_PRIORITAETEN['STK_PM_NORMAL']


def pruefe_umplanung(
    bestehender_auftrag: Auftrag,
    neuer_auftrag: Auftrag,
    geplante_touren: list,
    hat_ersatzteil: bool = False,
    kapazitaet_frei: bool = True,
    umwegzeit_minuten: Optional[float] = None,
    geplantes_datum: Optional[date] = None,
    heute: Optional[date] = None,
) -> UmplanungsErgebnis:
    """Prueft ob ein neuer Auftrag in den bestehenden Plan eingebaut werden kann.

    Prioritaeten (UMPLANUNGS_PRIORITAETEN aus config.py):
        1 REPAIR_OHNE_ET:      Sofort einplanen, bestehenden verschieben
        2 REPAIR_MIT_ET:       Einplanen nach Lieferzeit des Ersatzteils
        3 STK_PM_UEBERFAELLIG: Einplanen, niedrigste Prioritaet rauswerfen
        4 STK_PM_AUF_ROUTE:    Einplanen wenn Haversine-Umweg < 30min
        5 STK_PM_NORMAL:       Einplanen nur wenn Kapazitaet frei

    STK/PM-Regel: pruefe_stk_pm_faelligkeit() muss True sein (monatsgenau wie TUeV).
    Bei Verletzung: aktion='verwerfen'.

    Args:
        bestehender_auftrag:  Auftrag der ggf. verdraengt wird.
        neuer_auftrag:        Neu einzuplanender Auftrag.
        geplante_touren:      Liste aktueller Tagestour-Objekte.
        hat_ersatzteil:       True wenn Ersatzteil fuer Repair verfuegbar.
        kapazitaet_frei:      True wenn noch Kapazitaet frei ist.
        umwegzeit_minuten:    Vorberechnete Haversine-Umwegzeit in Minuten (fuer Auf-Route-Check).
        geplantes_datum:      Geplantes Einsatzdatum (Default: neuer_auftrag.faelligkeitsdatum).
        heute:                Referenzdatum (Default: date.today()).

    Returns:
        UmplanungsErgebnis mit aktion, begruendung, betroffene_tour.
    """
    if heute is None:
        heute = date.today()
    if geplantes_datum is None:
        geplantes_datum = neuer_auftrag.faelligkeitsdatum

    ist_repair = neuer_auftrag.auftragstyp == AuftragsTyp.REPAIR
    ist_stk_pm = not ist_repair
    ist_ueberfaellig = neuer_auftrag.faelligkeitsdatum < heute

    # STK/PM: Faelligkeit monatsgenau pruefen (wie TUeV)
    if ist_stk_pm:
        gueltig, faelligkeit_grund = pruefe_stk_pm_faelligkeit(neuer_auftrag, geplantes_datum)
        if not gueltig:
            return UmplanungsErgebnis(
                aktion="verwerfen",
                begruendung=f"STK/PM nur monatsgenau planbar (wie TUeV): {faelligkeit_grund}",
            )

    # Prioritaet des neuen Auftrags bestimmen
    auf_route = (umwegzeit_minuten is not None
                 and umwegzeit_minuten < UMWEGZEIT_ROUTE_MAX_MIN)

    if ist_repair and not hat_ersatzteil:
        prioritaet = UMPLANUNGS_PRIORITAETEN['REPAIR_OHNE_ET']
    elif ist_repair and hat_ersatzteil:
        prioritaet = UMPLANUNGS_PRIORITAETEN['REPAIR_MIT_ET']
    elif ist_stk_pm and ist_ueberfaellig:
        prioritaet = UMPLANUNGS_PRIORITAETEN['STK_PM_UEBERFAELLIG']
    elif ist_stk_pm and auf_route:
        prioritaet = UMPLANUNGS_PRIORITAETEN['STK_PM_AUF_ROUTE']
    else:
        prioritaet = UMPLANUNGS_PRIORITAETEN['STK_PM_NORMAL']

    prio_bestehend = _bestimme_prioritaet_auftrag(bestehender_auftrag, heute)
    betroffene = geplante_touren[0] if geplante_touren else None

    if prioritaet == UMPLANUNGS_PRIORITAETEN['REPAIR_OHNE_ET']:
        return UmplanungsErgebnis(
            aktion="einplanen",
            begruendung=(
                f"Repair ohne Ersatzteil (Prio {prioritaet}) verdraengt "
                f"bestehenden Auftrag {bestehender_auftrag.auftrag_id} "
                f"(Prio {prio_bestehend})"
            ),
            betroffene_tour=betroffene,
        )

    if prioritaet == UMPLANUNGS_PRIORITAETEN['REPAIR_MIT_ET']:
        return UmplanungsErgebnis(
            aktion="warten_auf_lieferzeit",
            begruendung=(
                f"Repair mit Ersatzteil (Prio {prioritaet}): "
                f"Einplanung nach Lieferzeit"
            ),
        )

    if prioritaet == UMPLANUNGS_PRIORITAETEN['STK_PM_UEBERFAELLIG']:
        if prio_bestehend <= prioritaet:
            return UmplanungsErgebnis(
                aktion="verwerfen",
                begruendung=(
                    f"STK/PM ueberfaellig kann bestehenden Auftrag "
                    f"(Prio {prio_bestehend}) nicht verdraengen"
                ),
            )
        return UmplanungsErgebnis(
            aktion="einplanen",
            begruendung=(
                f"STK/PM ueberfaellig (Prio {prioritaet}) verdraengt "
                f"bestehenden Auftrag {bestehender_auftrag.auftrag_id} "
                f"(Prio {prio_bestehend})"
            ),
            betroffene_tour=betroffene,
        )

    if prioritaet == UMPLANUNGS_PRIORITAETEN['STK_PM_AUF_ROUTE']:
        return UmplanungsErgebnis(
            aktion="einplanen",
            begruendung=(
                f"STK/PM auf Route (Umwegzeit {umwegzeit_minuten:.0f}min < "
                f"{UMWEGZEIT_ROUTE_MAX_MIN:.0f}min)"
            ),
            betroffene_tour=betroffene,
        )

    # STK_PM_NORMAL
    if kapazitaet_frei:
        return UmplanungsErgebnis(
            aktion="einplanen",
            begruendung="STK/PM normal – Kapazitaet frei",
        )
    return UmplanungsErgebnis(
        aktion="verwerfen",
        begruendung="STK/PM normal – keine freie Kapazitaet",
    )


# ---------------------------------------------------------------------------
# Oeffentliche API
# ---------------------------------------------------------------------------

def empfehlung_generieren(
    auftrag: Auftrag,
    tages_status: Optional[dict[str, TagesStatus]] = None,
    heute: Optional[date] = None,
) -> EmpfehlungsReport:
    """Erstellt einen Empfehlungsbericht fuer einen Serviceauftrag.

    Der Auftrag wird NICHT veraendert: status bleibt NEU,
    techniker_id bleibt None. Erst durch eine explizite Bestaetigung
    (z.B. auftrag_zuweisen() im Dispatcher) wird der Auftrag zugewiesen.

    Args:
        auftrag:      Der Auftrag, fuer den eine Empfehlung gesucht wird.
        tages_status: Aktueller Arbeitszeitstatus pro Techniker (optional).
                      Ohne Echtzeitdaten werden Auslastungen geschaetzt.
                      ── Fuer echte Auslastung werden zwei Quellen benoetigt:
                      1. SMax Work Order Kalender: gebuchte Einsaetze pro
                         Techniker (geplante Stunden, Fahrtzeit, Auftragstyp)
                      2. Microsoft Graph API (Outlook): Urlaub, Kranktage,
                         interne Termine, Schulungen
                      Ohne diese Integration bleibt Auslastung = Schaetzwert
                      (Default 0 h). Basis: 32 h/Woche (Mo-Do effektiv),
                      Freitag = Home Office / Bueroarbeit.
                      Geplanter Adapter: auftraege/kalender_connector.py
        heute:        Referenzdatum fuer Dringlichkeitsberechnung (Default: date.today()).
                      Nur fuer Tests uebergeben.

    Returns:
        EmpfehlungsReport mit allen Informationen fuer Disponent/Techniker.
        Enthaelt 0-3 TechnikerEmpfehlungen – nie eine automatische Zuweisung.
    """
    # Auftragsstatus sichern – wird am Ende verifiziert, nicht veraendert
    status_vorher = auftrag.status
    techniker_vorher = auftrag.techniker_id

    dringlichkeit = _berechne_dringlichkeit(auftrag.faelligkeitsdatum, heute)
    tech_standorte = _lade_techniker_standorte()

    # Klinik-Region fuer Regionsmatch-Hinweis
    klinik_region: Optional[str] = None
    if auftrag.klinik_id:
        klinik = _lade_klinik_details(auftrag.klinik_id)
        if klinik is not None:
            klinik_region = str(klinik.get("region", ""))

    # Scoring aufrufen (nur lesen, nie schreiben)
    empfehlungen: list[TechnikerEmpfehlung] = []
    if auftrag.klinik_id:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")   # Scoring-Warnungen intern unterdrucken
                scoring_ergebnisse = berechne_empfehlung(
                    auftrag_typ=auftrag.auftragstyp.value,
                    produkt_familie=auftrag.produkt_familie,
                    klinik_id=auftrag.klinik_id,
                    tages_status=tages_status,
                )
        except ValueError:
            scoring_ergebnisse = []

        for rang, ergebnis in enumerate(scoring_ergebnisse, start=1):
            tid = ergebnis.techniker_id
            tech_info = tech_standorte.get(tid, {"standort": "Unbekannt", "region": ""})
            minuten = _fahrzeit_minuten(ergebnis.distanz_km)

            empfehlung = TechnikerEmpfehlung(
                rang=rang,
                techniker_id=tid,
                techniker_standort=tech_info["standort"],
                score=round(ergebnis.score, 1),
                level=ergebnis.level,
                kompetenz_begruendung=_kompetenz_begruendung(
                    ergebnis.level, auftrag.produkt_familie, auftrag.auftragstyp.value
                ),
                naehe_begruendung=_naehe_begruendung(ergebnis.distanz_km, minuten),
                auslastung_begruendung=_auslastung_begruendung(
                    ergebnis.auslastung_score, tid, tages_status
                ),
                fahrzeit_minuten=minuten,
                distanz_km=round(ergebnis.distanz_km, 1),
                warnungen=list(ergebnis.warnungen),
                hinweise=_hinweise_generieren(
                    techniker_id=tid,
                    level=ergebnis.level,
                    produkt_familie=auftrag.produkt_familie,
                    auslastung_score=ergebnis.auslastung_score,
                    klinik_region=klinik_region,
                    techniker_region=tech_info["region"],
                ),
            )
            empfehlungen.append(empfehlung)

    # Sicherheitscheck: Auftrag darf nicht veraendert worden sein
    assert auftrag.status == status_vorher, "BUG: empfehlung_generieren hat den Auftragsstatus veraendert!"
    assert auftrag.techniker_id == techniker_vorher, "BUG: empfehlung_generieren hat techniker_id gesetzt!"

    return EmpfehlungsReport(
        auftrag_id=auftrag.auftrag_id,
        erstellt_am=datetime.now(),
        auftrag=auftrag,
        dringlichkeit=dringlichkeit,
        empfehlungen=empfehlungen,
        geraetestandort=_geraetestandort_dict(auftrag.klinik_id, auftrag.klinik_name),
        kundenkontakt=_kundenkontakt_dict(auftrag.klinik_id, auftrag.klinik_name),
        letzte_wartung=_letzte_wartung_dict(auftrag),
        offene_punkte=[],   # Historien-Modul nicht implementiert
        ersatzteile_schaetzung=_ersatzteile_schaetzung(auftrag.produkt_familie),
        hinweis_disposition=_HINWEIS_KEIN_AUTO_ASSIGN,
    )
