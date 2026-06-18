"""Datenmodelle fuer den Auftrags-Lifecycle (STK / PM / Repair).

Planungstypen:
    STK/PM:  Vorausplanung 3-7 Werktage (Planungshorizont)
    Repair:  Reaktionsplanung 48h SLA (Kundenkontakt Pflicht)
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from config import REPAIR_SLA_STUNDEN  # noqa: F401 – re-export fuer bestehende Imports
from config import REPAIR_ZIEL_STUNDEN


# ---------------------------------------------------------------------------
# Repair SLA / Reaktionszeit
# ---------------------------------------------------------------------------

REPAIR_ZIEL_KONTAKT = REPAIR_ZIEL_STUNDEN


class PlanungsTyp(str, Enum):
    """Unterscheidet STK/PM-Vorausplanung von Repair-Reaktionsplanung."""
    VORAUSPLANUNG = "Vorausplanung"      # STK/PM: 3-7 Tage Vorlauf
    REAKTIONSPLANUNG = "Reaktionsplanung"  # Repair: 48h SLA


class RepairPhase(str, Enum):
    """Phasen eines Repair-Auftrags (getrennt von allgemeinem AuftragsStatus)."""
    EINGANG = "Eingang"                           # Phase 0: Auftrag eingegangen
    KONTAKT_AUSSTEHEND = "Kontakt ausstehend"     # Phase 1: Techniker muss Klinik anrufen
    KONTAKT_HERGESTELLT = "Kontakt hergestellt"    # Phase 1 abgeschlossen
    ERSATZTEIL_PRUEFEN = "Ersatzteil pruefen"     # Phase 2: Trunkstock / Lager checken
    ERSATZTEIL_BESTELLT = "Ersatzteil bestellt"    # Phase 2: Warte auf Lieferung
    ERSATZTEIL_VERFUEGBAR = "Ersatzteil verfuegbar"  # Phase 2 abgeschlossen
    REPAIR_IN_ARBEIT = "Repair in Arbeit"          # Phase 3: Einsatz laeuft
    ABGESCHLOSSEN = "Abgeschlossen"                # Phase 3 abgeschlossen


class AuftragsTyp(str, Enum):
    STK = "STK"
    PM = "PM"
    REPAIR = "Repair"


class AuftragsStatus(str, Enum):
    NEU = "NEU"
    ZUGEWIESEN = "ZUGEWIESEN"
    IN_ARBEIT = "IN_ARBEIT"
    ABGESCHLOSSEN = "ABGESCHLOSSEN"


class DokumentTyp(str, Enum):
    SERVICEBERICHT = "Servicebericht"
    MESSPROTOKOLL = "Messprotokoll"
    FOTO_VORHER = "Foto_vorher"
    FOTO_NACHHER = "Foto_nachher"
    KV = "KV"
    CHECKLISTE = "Checkliste"


class Dokument(BaseModel):
    """Einzelnes Dokument, das einem Auftrag angehaengt werden kann."""

    typ: DokumentTyp
    angehaengt: bool = False
    pflicht: bool = True

    def fehlt(self) -> bool:
        """True wenn das Dokument Pflicht ist, aber noch nicht angehaengt wurde."""
        return self.pflicht and not self.angehaengt


class Auftrag(BaseModel):
    """Repraesentiert einen Serviceauftrag (STK, PM oder Repair)."""

    auftrag_id: str = Field(description="Eindeutige Auftrags-ID, z.B. 'STK-2025-00001'")
    auftragstyp: AuftragsTyp
    klinik_id: Optional[str] = Field(
        default=None,
        description="Klinik-ID aus kliniken.csv (z.B. 'K001'); None wenn noch nicht aufgeloest",
    )
    klinik_name: str = Field(description="Klartextname der Klinik aus SMax / geraete.csv")
    geraet_id: str = Field(description="Geraetemodell-ID, z.B. 'NIM4CM01'")
    produkt_familie: str = Field(description="Produktfamilie, z.B. 'Neuromonitoring'")
    anzahl_geraete: int = Field(default=1, ge=1, description="Anzahl gleichartiger Geraete")
    faelligkeitsdatum: date
    techniker_id: Optional[str] = None
    status: AuftragsStatus = AuftragsStatus.NEU
    kostenschaetzung_eur: Optional[float] = Field(
        default=None,
        ge=0,
        description="Kostenschaetzung in EUR (nur bei Repair relevant)",
    )
    kv_bestaetigt: bool = False
    dokumente: list[Dokument] = Field(default_factory=list)

    # Repair-spezifische Felder
    eingangsdatum: Optional[datetime] = Field(
        default=None,
        description="Zeitpunkt des Auftragseingangs (fuer SLA-Berechnung bei Repair)",
    )
    repair_phase: RepairPhase = Field(
        default=RepairPhase.EINGANG,
        description="Aktuelle Phase eines Repair-Auftrags",
    )
    kontakt_hergestellt_am: Optional[datetime] = Field(
        default=None,
        description="Zeitpunkt des ersten Kundenkontakts (stoppt SLA-Timer)",
    )
    fehler_beschreibung: Optional[str] = Field(
        default=None,
        description="Fehlerbeschreibung vom Kunden (Repair)",
    )

    def ist_zugewiesen(self) -> bool:
        return self.techniker_id is not None and self.status != AuftragsStatus.NEU

    def fehlende_pflichtdokumente(self) -> list[DokumentTyp]:
        """Gibt alle Pflicht-Dokumenttypen zurueck, die noch nicht angehaengt wurden."""
        return [dok.typ for dok in self.dokumente if dok.fehlt()]

    @property
    def planungstyp(self) -> PlanungsTyp:
        """STK/PM = Vorausplanung, Repair = Reaktionsplanung."""
        if self.auftragstyp == AuftragsTyp.REPAIR:
            return PlanungsTyp.REAKTIONSPLANUNG
        return PlanungsTyp.VORAUSPLANUNG
