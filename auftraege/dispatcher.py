"""Auftrags-Dispatcher: Faelligkeiten ermitteln, zuweisen, benachrichtigen.

Funktionen (oeffentliche API):
    naechste_faellige_auftraege(n)  -> list[Auftrag]
    auftrag_zuweisen(auftrag, tages_status) -> Auftrag | None
    auftrag_benachrichtigen(auftrag) -> dict
"""

from __future__ import annotations

import re
import warnings
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

from techniker.scoring import TagesStatus, berechne_empfehlung
from .models import Auftrag, AuftragsStatus, AuftragsTyp

_DATA_DIR = Path(__file__).parent.parent / "daten"

# Mapping: Produktfamilie aus geraete.csv -> Produktfamilie in trainingsmatrix.csv
# (identisch zur crosstraining_analyse, zentralisiert hier als Single Source of Truth)
_GERAET_ZU_TRAINING: dict[str, str] = {
    "Hugo":              "Hugo",
    "Beatmung":          "Beatmung",
    "Neurophysiologie":  "Neurophysiologie",
    "HF_Chirurgie":      "Elektrochirurgie",
    "NIM":               "Neuromonitoring",
    "O_arm":             "Navigation",
    "Gastro_Manometrie": "Gastroenterologie",
    "Gastro_Endoskopie": "Endoskopie",
    "Ablation_HF":       "Kardiovaskulaer_Ablation",
    "Ablation_RF":       "Kardiovaskulaer_Ablation",
    "Cryo":              "Kardiovaskulaer_Ablation",
    "IPC":               "Kardiovaskulaer",
    "Schrittmacher_Prog": "Kardiovaskulaer",
    "AEX":               "Kardiovaskulaer",
    "ACT":               "Kardiovaskulaer",
}

# Quartals-Anfangsmonate: Q1=Jan, Q2=Apr, Q3=Jul, Q4=Okt
_QUARTAL_MONAT: dict[int, int] = {1: 1, 2: 4, 3: 7, 4: 10}


# ---------------------------------------------------------------------------
# Interne Hilfsfunktionen
# ---------------------------------------------------------------------------

def _quartal_zu_datum(q_str: str) -> date:
    """Wandelt 'YYYY-QN' in den ersten Tag des Quartals um.

    Beispiele: '2025-Q1' -> 2025-01-01, '2026-Q3' -> 2026-07-01
    """
    match = re.fullmatch(r"(\d{4})-Q([1-4])", q_str.strip())
    if not match:
        raise ValueError(f"Unbekanntes Quartal-Format: '{q_str}'. Erwartet: 'YYYY-QN'")
    year = int(match.group(1))
    monat = _QUARTAL_MONAT[int(match.group(2))]
    return date(year, monat, 1)


def _normalize(text: str) -> str:
    return (text.lower()
            .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
            .replace("ß", "ss").strip())


def _lade_klinik_id_map() -> dict[str, str]:
    """Gibt normalized klinik_name -> klinik_id aus kliniken.csv zurueck."""
    df = pd.read_csv(_DATA_DIR / "kliniken.csv", dtype=str)
    return {_normalize(row["name"]): row["klinik_id"] for _, row in df.iterrows()}


def _lade_klinik_details(klinik_id: str) -> Optional[pd.Series]:
    df = pd.read_csv(_DATA_DIR / "kliniken.csv", dtype=str)
    match = df[df["klinik_id"] == klinik_id]
    return match.iloc[0] if not match.empty else None


def _klinik_id_lookup(klinik_name: str, klinik_id_map: dict[str, str]) -> Optional[str]:
    """Versucht ueber normalisierten Namen oder Teilstring-Match eine klinik_id zu finden."""
    n = _normalize(klinik_name)
    if n in klinik_id_map:
        return klinik_id_map[n]
    # Teilstring-Match (Fallback)
    for kn, kid in klinik_id_map.items():
        if kn in n or n in kn:
            return kid
    return None


def _auftrag_id(klinik_name: str, produkt: str, modell: str, idx: int) -> str:
    kuerzel = re.sub(r"[^A-Za-z0-9]", "", klinik_name)[:10].upper()
    pf = re.sub(r"[^A-Za-z]", "", produkt)[:6].upper()
    return f"STK-{kuerzel}-{pf}-{idx:04d}"


# ---------------------------------------------------------------------------
# Oeffentliche API
# ---------------------------------------------------------------------------

def naechste_faellige_auftraege(n: int = 10) -> list[Auftrag]:
    """Liest geraete.csv und gibt die n naechsten faelligen STK-Auftraege zurueck.

    Sortiert nach Faelligkeitsdatum aufsteigend (ueberfaelligste zuerst).
    Zeilen mit unbekanntem Quartal-Format oder fehlenden Pflichtfeldern werden
    uebersprungen (Warnung wird ausgegeben).

    Args:
        n: Maximale Anzahl zurueckgegebener Auftraege. Default: 10.

    Returns:
        Liste von Auftrag-Objekten (Typ STK, Status NEU), aufsteigend nach Faelligkeitsdatum.
    """
    klinik_id_map = _lade_klinik_id_map()

    geraete_df = pd.read_csv(
        _DATA_DIR / "geraete.csv",
        comment="#",
        dtype=str,
    ).fillna("")

    auftraege: list[Auftrag] = []

    for idx, row in geraete_df.iterrows():
        klinik_name = row.get("klinik_name", "").strip()
        produkt_geraet = row.get("produkt_familie", "").strip()
        modell = row.get("produkt_modell", "").strip()
        faelligkeit_roh = row.get("naechste_stk_faellig", "").strip()
        anzahl_roh = row.get("anzahl", "1").strip()

        if not klinik_name or not faelligkeit_roh:
            continue

        try:
            faelligkeitsdatum = _quartal_zu_datum(faelligkeit_roh)
        except ValueError as exc:
            warnings.warn(str(exc), UserWarning, stacklevel=2)
            continue

        try:
            anzahl = int(anzahl_roh)
        except ValueError:
            anzahl = 1

        produkt_training = _GERAET_ZU_TRAINING.get(produkt_geraet, produkt_geraet)
        klinik_id = _klinik_id_lookup(klinik_name, klinik_id_map)

        auftraege.append(
            Auftrag(
                auftrag_id=_auftrag_id(klinik_name, produkt_geraet, modell, int(str(idx))),
                auftragstyp=AuftragsTyp.STK,
                klinik_id=klinik_id,
                klinik_name=klinik_name,
                geraet_id=modell,
                produkt_familie=produkt_training,
                anzahl_geraete=anzahl,
                faelligkeitsdatum=faelligkeitsdatum,
                status=AuftragsStatus.NEU,
            )
        )

    auftraege.sort(key=lambda a: a.faelligkeitsdatum)
    return auftraege[:n]


def auftrag_zuweisen(
    auftrag: Auftrag,
    tages_status: Optional[dict[str, TagesStatus]] = None,
    einsatz_dauer_std: float = 4.0,
) -> Optional[Auftrag]:
    """Weist dem Auftrag den besten verfuegbaren Techniker zu.

    Nutzt techniker.scoring.berechne_empfehlung() fuer die Bewertung.
    Gibt None zurueck wenn kein geeigneter Techniker gefunden wird
    (z.B. fehlende klinik_id, keine qualifizierten Techniker verfuegbar).

    Args:
        auftrag:           Der zuzuweisende Auftrag (wird in-place aktualisiert).
        tages_status:      Aktueller Arbeitszeitstatus pro Techniker. Default: alle frei.
        einsatz_dauer_std: Erwartete Einsatzdauer in Stunden. Default: 4.0h.

    Returns:
        Der aktualisierte Auftrag (status=ZUGEWIESEN, techniker_id gesetzt)
        oder None wenn keine Zuweisung moeglich.
    """
    if auftrag.klinik_id is None:
        warnings.warn(
            f"Auftrag {auftrag.auftrag_id}: klinik_id fehlt – Scoring nicht moeglich.",
            UserWarning,
            stacklevel=2,
        )
        return None

    try:
        empfehlungen = berechne_empfehlung(
            auftrag_typ=auftrag.auftragstyp.value,
            produkt_familie=auftrag.produkt_familie,
            klinik_id=auftrag.klinik_id,
            einsatz_dauer_std=einsatz_dauer_std,
            tages_status=tages_status,
        )
    except ValueError as exc:
        warnings.warn(
            f"Auftrag {auftrag.auftrag_id}: Scoring fehlgeschlagen – {exc}",
            UserWarning,
            stacklevel=2,
        )
        return None

    if not empfehlungen:
        warnings.warn(
            f"Auftrag {auftrag.auftrag_id}: Kein qualifizierter Techniker verfuegbar "
            f"(Produktfamilie: {auftrag.produkt_familie}, Klinik: {auftrag.klinik_id}).",
            UserWarning,
            stacklevel=2,
        )
        return None

    auftrag.techniker_id = empfehlungen[0].techniker_id
    auftrag.status = AuftragsStatus.ZUGEWIESEN
    return auftrag


def auftrag_benachrichtigen(auftrag: Auftrag) -> dict:
    """Erstellt ein Benachrichtigungs-Dict mit allen relevanten Auftragsinformationen.

    Das Dict eignet sich als Basis fuer E-Mail-Templates, Push-Notifications
    oder API-Responses an SMax.

    Args:
        auftrag: Der (bereits zugewiesene) Auftrag.

    Returns:
        Dict mit den Sektionen: auftragsdaten, geraetestandort, kundenkontakt, anfahrt.
        Fehlende Klinikdaten werden als None zurueckgegeben (kein Fehler).
    """
    klinik_details: Optional[pd.Series] = None
    if auftrag.klinik_id:
        klinik_details = _lade_klinik_details(auftrag.klinik_id)

    geraetestandort: dict = {
        "klinik_name": auftrag.klinik_name,
        "klinik_id": auftrag.klinik_id,
        "plz": klinik_details["plz"] if klinik_details is not None else None,
        "stadt": klinik_details["stadt"] if klinik_details is not None else None,
        "hugo_standort": klinik_details["hugo_standort"] if klinik_details is not None else None,
    }

    kundenkontakt: dict = {
        "klinik_name": auftrag.klinik_name,
        "klinik_id": auftrag.klinik_id,
        # Kontaktdaten muessen ggf. aus SMax nachgeladen werden
        "smax_kontakt_url": (
            f"https://smax.medtronic.de/accounts/{auftrag.klinik_id}"
            if auftrag.klinik_id else None
        ),
    }

    anfahrt: dict = {
        "klinik_plz": klinik_details["plz"] if klinik_details is not None else None,
        "klinik_stadt": klinik_details["stadt"] if klinik_details is not None else None,
        "klinik_groesse": klinik_details["groesse"] if klinik_details is not None else None,
        "hinweis": (
            "Hugo-Standort: besondere Sicherheitseinweisung erforderlich"
            if (klinik_details is not None and str(klinik_details.get("hugo_standort", "")).lower() == "ja")
            else None
        ),
    }

    return {
        "auftragsdaten": {
            "auftrag_id": auftrag.auftrag_id,
            "auftragstyp": auftrag.auftragstyp.value,
            "produkt_familie": auftrag.produkt_familie,
            "geraet_id": auftrag.geraet_id,
            "anzahl_geraete": auftrag.anzahl_geraete,
            "faelligkeitsdatum": auftrag.faelligkeitsdatum.isoformat(),
            "status": auftrag.status.value,
            "techniker_id": auftrag.techniker_id,
        },
        "geraetestandort": geraetestandort,
        "kundenkontakt": kundenkontakt,
        "anfahrt": anfahrt,
    }
