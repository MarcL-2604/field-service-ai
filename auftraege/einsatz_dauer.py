"""Einsatzdauer-Berechnung aus SMax Labor-Zeiten mit Pufferzeiten.

Berechnet realistische Einsatzdauern basierend auf historischen
Servicezeiten aus daten/labor_zeiten.csv plus situationsabhaengige
Pufferzeiten (Kliniktyp, Geraetetyp, Gespraechsbedarf).

Oeffentliche API:
    berechne_einsatz_dauer(geraete_liste, techniker_id, ...) -> EinsatzDauer

Fallback-Kaskade:
    1. Exakter Match: techniker_id + geraete_typ in labor_zeiten.csv
    2. Familien-Durchschnitt: Durchschnitt aller Techniker fuer diese Produktfamilie
    3. Standard-Fallback: 90min Service + 30min Admin = 120min

Puffer-Logik:
    Basis-Puffer:      +30min je Einsatz (Parkplatz, Orientierung, Unvorhergesehenes)
    Einschleusung:     +20min (Uniklinikum) / +10min (Gross/Mittel)
    Grossgeraet:       +30min (Hugo, Energie/EC300, Navigation/O-arm)
    Gespraechsbedarf:  +15min (Standard) / +30min (Erstbesuch) / +45min (nach Complaint)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from techniker.models import BIG_CAPITAL_CLUSTER1_OR
from config import (
    MAX_EINSATZ_STUNDEN,
    SYNERGIEEFFEKT_FAKTOR,
    RUESTZEIT_MINUTEN,
    PUFFER_BASIS_MIN,
    PUFFER_EINSCHLEUSUNG_MIN as _CFG_PUFFER_EINSCHLEUSUNG,
    PUFFER_GROSSGERAET_MIN as _CFG_PUFFER_GROSSGERAET,
    PUFFER_GESPRAECH_MIN as _CFG_PUFFER_GESPRAECH,
    PUFFER_MESSMITTEL_LADEN as _CFG_PUFFER_MESSMITTEL,
)

_DATA_DIR = Path(__file__).parent.parent / "daten"
_LABOR_ZEITEN_CSV = _DATA_DIR / "labor_zeiten.csv"

# Fallback wenn keine Daten in labor_zeiten.csv
STANDARD_SERVICE_MIN = 90
STANDARD_ADMIN_MIN = 30

# Synergieeffekt: gleiches Geraet ab dem 2. Stueck → 70% der Normalzeit
SYNERGIE_FAKTOR = SYNERGIEEFFEKT_FAKTOR

# Ruestzeit zwischen verschiedenen Produktfamilien
RUESTZEIT_FAMILIE_WECHSEL_MIN = RUESTZEIT_MINUTEN

# Maximale Einsatzdauer pro Tag (aus config.py)
MAX_EINSATZ_DAUER_MIN = int(MAX_EINSATZ_STUNDEN * 60)  # 6h → 360min

# ---------------------------------------------------------------------------
# Pufferzeit-Konstanten (aus config.py)
# ---------------------------------------------------------------------------

PUFFER_STANDARD_MIN = PUFFER_BASIS_MIN
PUFFER_NOTFALL_MIN = 45         # Geraet nicht zugaenglich, OP laeuft
PUFFER_EINSCHLEUSUNG_MIN = _CFG_PUFFER_EINSCHLEUSUNG
PUFFER_GESPRAECH_MIN = _CFG_PUFFER_GESPRAECH
PUFFER_GROSSGERAET_MIN = _CFG_PUFFER_GROSSGERAET

# Messmittel-Vorbereitung am Vortag (separate Info, NICHT in Einsatzdauer)
PUFFER_MESSMITTEL_LADEN = _CFG_PUFFER_MESSMITTEL
MESSMITTEL_HINWEIS = f"Vortag: Messmittel laden (~{PUFFER_MESSMITTEL_LADEN} min)"

# Klinik-Typ → Einschleusungs-Puffer
_KLINIK_PUFFER: dict[str, int] = {
    "uni":    PUFFER_EINSCHLEUSUNG_MIN,   # 20min
    "gross":  10,
    "mittel": 10,
}

# Grossgeraet-Familien die Extra-Puffer bekommen (= Big Capital Cluster 1 OR)
_GROSSGERAET_FAMILIEN: set[str] = set(BIG_CAPITAL_CLUSTER1_OR)

# Gespraechsbedarf-Typen
GESPRAECH_STANDARD = "standard"         # +15min
GESPRAECH_ERSTBESUCH = "erstbesuch"     # +30min
GESPRAECH_COMPLAINT = "complaint"       # +45min

_GESPRAECH_PUFFER: dict[str, int] = {
    GESPRAECH_STANDARD: PUFFER_GESPRAECH_MIN,      # 15
    GESPRAECH_ERSTBESUCH: 30,
    GESPRAECH_COMPLAINT: PUFFER_NOTFALL_MIN,        # 45
}


# ---------------------------------------------------------------------------
# Datenklassen
# ---------------------------------------------------------------------------

@dataclass
class PufferDetail:
    """Einzelner Puffer-Posten mit Begruendung."""
    bezeichnung: str
    minuten: int
    begruendung: str


@dataclass
class GeraeteDauer:
    """Berechnete Dauer fuer ein einzelnes Geraet."""
    produkt_familie: str
    geraete_typ: str
    service_min: int
    admin_min: int
    gesamt_min: int
    synergie_angewendet: bool    # True wenn 70%-Regel aktiv
    quelle: str                  # "techniker_match", "familien_durchschnitt", "standard_fallback"


@dataclass
class EinsatzDauer:
    """Berechnete Gesamtdauer fuer einen gebuendelten Einsatz."""
    techniker_id: Optional[str]
    geraete_dauern: list[GeraeteDauer]
    ruestzeiten_min: int              # Gesamte Ruestzeit zwischen Familien
    netto_min: int                    # Geraete + Ruestzeit (ohne Puffer)
    puffer_details: list[PufferDetail]  # Einzelne Puffer-Posten
    puffer_gesamt_min: int            # Summe aller Puffer
    gesamt_min: int                   # netto_min + puffer_gesamt_min
    gesamt_std: float                 # gesamt_min / 60, gerundet auf 2 Stellen
    ueberschreitet_max: bool          # True wenn gesamt_min > MAX_EINSATZ_DAUER_MIN
    dashboard_text: str               # Formatierte Anzeige fuer Dashboard

    def __repr__(self) -> str:
        return (
            f"EinsatzDauer({self.techniker_id}: "
            f"{len(self.geraete_dauern)} Geraete, "
            f"netto={self.netto_min}min + puffer={self.puffer_gesamt_min}min "
            f"= {self.gesamt_min}min ({self.gesamt_std:.1f}h)"
            f"{' [UEBER MAX]' if self.ueberschreitet_max else ''})"
        )


# ---------------------------------------------------------------------------
# Labor-Zeiten laden
# ---------------------------------------------------------------------------

def _lade_labor_zeiten() -> pd.DataFrame:
    """Laedt labor_zeiten.csv. Gibt leeren DataFrame zurueck wenn Datei fehlt."""
    try:
        return pd.read_csv(_LABOR_ZEITEN_CSV, comment="#", dtype=str).fillna("")
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame(columns=[
            "produkt_familie", "geraete_typ", "techniker_id",
            "service_zeit_min", "admin_zeit_min", "quelle",
        ])


def _lookup_zeiten(
    df: pd.DataFrame,
    produkt_familie: str,
    geraete_typ: str,
    techniker_id: Optional[str],
) -> tuple[int, int, str]:
    """Sucht Service- und Admin-Zeiten in der Labor-Zeiten-Tabelle.

    Fallback-Kaskade:
        1. Exakter Match: techniker_id + geraete_typ
        2. Familien-Durchschnitt: alle Eintraege fuer produkt_familie
        3. Standard-Fallback: STANDARD_SERVICE_MIN + STANDARD_ADMIN_MIN

    Returns:
        (service_min, admin_min, quelle)
    """
    if df.empty:
        return STANDARD_SERVICE_MIN, STANDARD_ADMIN_MIN, "standard_fallback"

    # 1. Exakter Match: techniker_id + geraete_typ
    if techniker_id:
        match = df[
            (df["techniker_id"] == techniker_id)
            & (df["geraete_typ"] == geraete_typ)
        ]
        if not match.empty:
            row = match.iloc[0]
            return (
                int(row["service_zeit_min"]),
                int(row["admin_zeit_min"]),
                "techniker_match",
            )

    # 2. Familien-Durchschnitt: alle Eintraege fuer produkt_familie
    fam_match = df[df["produkt_familie"] == produkt_familie]
    if not fam_match.empty:
        avg_service = round(fam_match["service_zeit_min"].astype(int).mean())
        avg_admin = round(fam_match["admin_zeit_min"].astype(int).mean())
        return avg_service, avg_admin, "familien_durchschnitt"

    # 3. Standard-Fallback
    return STANDARD_SERVICE_MIN, STANDARD_ADMIN_MIN, "standard_fallback"


# ---------------------------------------------------------------------------
# Puffer-Berechnung
# ---------------------------------------------------------------------------

def _lade_klinik_groesse(klinik_id: Optional[str]) -> Optional[str]:
    """Gibt die Klinik-Groesse ('uni', 'gross', 'mittel') aus kliniken.csv zurueck."""
    if not klinik_id:
        return None
    try:
        df = pd.read_csv(_DATA_DIR / "kliniken.csv", dtype=str)
        match = df[df["klinik_id"] == klinik_id]
        if not match.empty:
            return str(match.iloc[0].get("groesse", "")).lower().strip()
    except Exception:
        pass
    return None


def berechne_puffer(
    geraete_familien: list[str],
    klinik_id: Optional[str] = None,
    klinik_groesse: Optional[str] = None,
    gespraech_typ: str = GESPRAECH_STANDARD,
) -> list[PufferDetail]:
    """Berechnet alle Puffer-Posten fuer einen Einsatz.

    Args:
        geraete_familien:  Liste der Produktfamilien im Einsatz.
        klinik_id:         Klinik-ID fuer Groesse-Lookup (optional).
        klinik_groesse:    Klinik-Groesse direkt (ueberschreibt Lookup).
        gespraech_typ:     "standard", "erstbesuch" oder "complaint".

    Returns:
        Liste von PufferDetail-Objekten.
    """
    puffer: list[PufferDetail] = []

    # 1. Basis-Puffer (immer)
    puffer.append(PufferDetail(
        bezeichnung="Basis-Puffer",
        minuten=PUFFER_STANDARD_MIN,
        begruendung="Parkplatz, Orientierung, Unvorhergesehenes",
    ))

    # 2. Klinik-Typ Puffer (Einschleusung)
    if klinik_groesse is None and klinik_id:
        klinik_groesse = _lade_klinik_groesse(klinik_id)
    if klinik_groesse and klinik_groesse in _KLINIK_PUFFER:
        puffer_min = _KLINIK_PUFFER[klinik_groesse]
        label_map = {"uni": "Einschleusung Uniklinikum", "gross": "Einschleusung Grossklinik",
                     "mittel": "Einschleusung Klinik"}
        puffer.append(PufferDetail(
            bezeichnung=label_map.get(klinik_groesse, f"Einschleusung ({klinik_groesse})"),
            minuten=puffer_min,
            begruendung="Hygieneschleuse, Sicherheitscheck",
        ))

    # 3. Grossgeraet-Puffer (einmalig, nicht pro Geraet)
    hat_grossgeraet = any(f in _GROSSGERAET_FAMILIEN for f in geraete_familien)
    if hat_grossgeraet:
        grossgeraete = [f for f in geraete_familien if f in _GROSSGERAET_FAMILIEN]
        puffer.append(PufferDetail(
            bezeichnung="Grossgeraet-Aufbau",
            minuten=PUFFER_GROSSGERAET_MIN,
            begruendung=f"Komplexer Aufbau: {', '.join(set(grossgeraete))}",
        ))

    # 4. Gespraechsbedarf
    gespraech_min = _GESPRAECH_PUFFER.get(gespraech_typ, PUFFER_GESPRAECH_MIN)
    gespraech_labels = {
        GESPRAECH_STANDARD: "Gespraech MTech",
        GESPRAECH_ERSTBESUCH: "Erstbesuch-Gespraech",
        GESPRAECH_COMPLAINT: "Gespraech nach Beschwerde",
    }
    gespraech_gruende = {
        GESPRAECH_STANDARD: "Kurze Abstimmung Medizintechnik",
        GESPRAECH_ERSTBESUCH: "Erster Besuch bei dieser Klinik — ausfuehrliches Kennenlernen",
        GESPRAECH_COMPLAINT: "Nach Kundenbeschwerde — ausfuehrliches Gespraech noetig",
    }
    puffer.append(PufferDetail(
        bezeichnung=gespraech_labels.get(gespraech_typ, "Gespraech"),
        minuten=gespraech_min,
        begruendung=gespraech_gruende.get(gespraech_typ, "Abstimmung"),
    ))

    return puffer


# ---------------------------------------------------------------------------
# Oeffentliche API
# ---------------------------------------------------------------------------

def berechne_einsatz_dauer(
    geraete_liste: list[dict],
    techniker_id: Optional[str] = None,
    klinik_id: Optional[str] = None,
    klinik_groesse: Optional[str] = None,
    gespraech_typ: str = GESPRAECH_STANDARD,
) -> EinsatzDauer:
    """Berechnet die Gesamtdauer fuer einen Einsatz mit mehreren Geraeten.

    Args:
        geraete_liste:   Liste von Geraeten, je:
                         {"produkt_familie": str, "geraete_typ": str, "anzahl": int}
                         anzahl ist optional (Default: 1).
        techniker_id:    Techniker-ID fuer technikerspezifische Zeiten.
                         None → Familien-Durchschnitt wird verwendet.
        klinik_id:       Klinik-ID fuer Groesse-Lookup (Einschleusungs-Puffer).
        klinik_groesse:  Klinik-Groesse direkt ("uni", "gross", "mittel").
                         Ueberschreibt klinik_id Lookup.
        gespraech_typ:   "standard" (15min), "erstbesuch" (30min), "complaint" (45min).

    Returns:
        EinsatzDauer mit Netto-Dauer, Puffer-Details und Gesamt inkl. Puffer.

    Synergieeffekt:
        Mehrere Geraete gleicher Familie: erstes Geraet volle Zeit,
        jedes weitere 70% (Ruestzeit entfaellt, Routine-Effekt).

    Ruestzeit:
        Wechsel zwischen verschiedenen Produktfamilien: +30min.

    Puffer:
        Basis (30min) + Einschleusung (10-20min) + Grossgeraet (30min) + Gespraech (15-45min).
    """
    df = _lade_labor_zeiten()
    geraete_dauern: list[GeraeteDauer] = []

    # Zaehle wie oft jede Familie bereits aufgetreten ist (fuer Synergieeffekt)
    familien_zaehler: dict[str, int] = {}

    for geraet in geraete_liste:
        pf = geraet["produkt_familie"]
        gt = geraet["geraete_typ"]
        anzahl = int(geraet.get("anzahl", 1))

        service_min, admin_min, quelle = _lookup_zeiten(df, pf, gt, techniker_id)

        for i in range(anzahl):
            bisherige = familien_zaehler.get(pf, 0)
            synergie = bisherige > 0

            if synergie:
                eff_service = round(service_min * SYNERGIE_FAKTOR)
                eff_admin = round(admin_min * SYNERGIE_FAKTOR)
            else:
                eff_service = service_min
                eff_admin = admin_min

            geraete_dauern.append(GeraeteDauer(
                produkt_familie=pf,
                geraete_typ=gt,
                service_min=eff_service,
                admin_min=eff_admin,
                gesamt_min=eff_service + eff_admin,
                synergie_angewendet=synergie,
                quelle=quelle,
            ))
            familien_zaehler[pf] = bisherige + 1

    # Ruestzeit: +30min fuer jeden Familienwechsel
    ruestzeiten_min = 0
    familien_reihenfolge = [gd.produkt_familie for gd in geraete_dauern]
    for i in range(1, len(familien_reihenfolge)):
        if familien_reihenfolge[i] != familien_reihenfolge[i - 1]:
            ruestzeiten_min += RUESTZEIT_FAMILIE_WECHSEL_MIN

    netto_min = sum(gd.gesamt_min for gd in geraete_dauern) + ruestzeiten_min

    # Puffer berechnen
    alle_familien = [gd.produkt_familie for gd in geraete_dauern]
    puffer_details = berechne_puffer(
        geraete_familien=alle_familien,
        klinik_id=klinik_id,
        klinik_groesse=klinik_groesse,
        gespraech_typ=gespraech_typ,
    )
    puffer_gesamt_min = sum(p.minuten for p in puffer_details)

    gesamt_min = netto_min + puffer_gesamt_min
    gesamt_std = round(gesamt_min / 60.0, 2)

    # Dashboard-Text generieren
    dashboard_text = _formatiere_dashboard(
        techniker_id, geraete_dauern, ruestzeiten_min,
        netto_min, puffer_details, puffer_gesamt_min, gesamt_min,
    )

    return EinsatzDauer(
        techniker_id=techniker_id,
        geraete_dauern=geraete_dauern,
        ruestzeiten_min=ruestzeiten_min,
        netto_min=netto_min,
        puffer_details=puffer_details,
        puffer_gesamt_min=puffer_gesamt_min,
        gesamt_min=gesamt_min,
        gesamt_std=gesamt_std,
        ueberschreitet_max=gesamt_min > MAX_EINSATZ_DAUER_MIN,
        dashboard_text=dashboard_text,
    )


def _fmt_hm(minuten: int) -> str:
    """Formatiert Minuten als 'Xh YYmin'."""
    return f"{minuten // 60}h {minuten % 60:02d}min"


def _formatiere_dashboard(
    techniker_id: Optional[str],
    geraete_dauern: list[GeraeteDauer],
    ruestzeiten_min: int,
    netto_min: int,
    puffer_details: list[PufferDetail],
    puffer_gesamt_min: int,
    gesamt_min: int,
) -> str:
    """Formatiert die Einsatzdauer fuer die Dashboard-Anzeige."""
    zeilen: list[str] = []

    for gd in geraete_dauern:
        synergie_tag = " (70% Synergie)" if gd.synergie_angewendet else ""
        zeilen.append(
            f"  {gd.geraete_typ}: {_fmt_hm(gd.gesamt_min)} "
            f"(Service {gd.service_min}min + Admin {gd.admin_min}min){synergie_tag}"
        )

    if ruestzeiten_min > 0:
        zeilen.append(f"  Ruestzeit: {ruestzeiten_min}min")

    zeilen.append(f"  Netto: {_fmt_hm(netto_min)}")

    # Puffer-Posten
    if puffer_details:
        zeilen.append("  ───────────────────────")
        for p in puffer_details:
            zeilen.append(f"  {p.bezeichnung}: {p.minuten}min")
        zeilen.append(f"  Puffer gesamt: {_fmt_hm(puffer_gesamt_min)}")

    zeilen.append("  ═══════════════════════")
    zeilen.append(
        f"  Netto {_fmt_hm(netto_min)} + Puffer {_fmt_hm(puffer_gesamt_min)} "
        f"= Geplant {_fmt_hm(gesamt_min)}"
    )

    # Messmittel-Hinweis (separate Vorbereitung am Vortag, nicht in Einsatzdauer)
    zeilen.append("  ───────────────────────")
    zeilen.append(f"  {MESSMITTEL_HINWEIS}")

    tech_prefix = f"{techniker_id} · " if techniker_id else ""
    header = f"{tech_prefix}Einsatzplanung:"

    return header + "\n" + "\n".join(zeilen)
