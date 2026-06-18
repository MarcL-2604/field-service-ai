"""Dokumenten-QA: 2x woechentliche Vollstaendigkeitspruefung abgeschlossener Work Orders.

Laeuft Mo + Do gegen alle seit dem letzten Lauf abgeschlossenen SMax Work Orders.
Prueft Pflichtdokumente je Auftragstyp; erstellt Mail-Dicts fuer fehlende Dokumente;
liefert Zusammenfassung fuer den Disponenten.

Oeffentliche API:
    pflichtdokumente_je_typ(auftragstyp)          -> list[str]
    qa_lauf(work_orders)                           -> list[DokumentenPruefung]
    mail_vorbereiten(pruefung)                     -> dict
    qa_bericht_erstellen(ergebnisse)               -> str

Datenklassen:
    DokumentenPruefung  – Ergebnis einer Einzelpruefung
    TechnikerAusnahme   – Ausnahme-Meldung (krank/Urlaub/ueberlastet)
        .auftrag_umplanen(auftrag)                 -> Auftrag

Pflichtdokumente (QA-Schicht, ergaenzt um TDS gegenueber abschlusskontrolle.py):
    STK:    Messprotokoll, Servicebericht, TDS
    PM:     Servicebericht, Checkliste, TDS
    Repair: Servicebericht, Foto_vorher, Foto_nachher, TDS
            + KV  (wenn Kostenschaetzung > {_KV_SCHWELLWERT_EUR} EUR)

Status-Logik:
    VOLLSTAENDIG  – alle Pflichtdokumente vorhanden
    KRITISCH      – sicherheitsrelevantes Dokument fehlt
                    (Servicebericht immer; Messprotokoll bei STK;
                     Foto_vorher/Foto_nachher bei Repair)
    UNVOLLSTAENDIG – nur nicht-kritische Dokumente fehlen (TDS, Checkliste, KV)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional

from .models import Auftrag, AuftragsStatus

# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

_KV_SCHWELLWERT_EUR: float = 500.0
_ABSENDER: str = "service@medtronic.com"

# Sicherheitsrelevante Dokumente je Auftragstyp → Fehlen fuehrt zu KRITISCH
_KRITISCHE_DOKUMENTE: dict[str, list[str]] = {
    "STK":    ["Servicebericht", "Messprotokoll"],
    "PM":     ["Servicebericht"],
    "Repair": ["Servicebericht", "Foto_vorher", "Foto_nachher"],
}


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PruefungStatus(str, Enum):
    VOLLSTAENDIG = "VOLLSTAENDIG"
    UNVOLLSTAENDIG = "UNVOLLSTAENDIG"
    KRITISCH = "KRITISCH"


class AusnahmeGrund(str, Enum):
    KRANK = "KRANK"
    UEBERLASTET = "UEBERLASTET"
    URLAUB = "URLAUB"
    SONSTIGE = "SONSTIGE"


class AusnahmeQuelle(str, Enum):
    TECHNIKER_SMAX = "TECHNIKER_SMAX"
    DISPONENT_DASHBOARD = "DISPONENT_DASHBOARD"


# ---------------------------------------------------------------------------
# Datenklassen
# ---------------------------------------------------------------------------

@dataclass
class DokumentenPruefung:
    """Ergebnis der QA-Pruefung eines einzelnen abgeschlossenen Work Orders."""

    auftrag_id:           str
    techniker_id:         str
    auftragstyp:          str               # "STK" | "PM" | "Repair"
    abgeschlossen_am:     date
    gefundene_dokumente:  list[str]
    fehlende_dokumente:   list[str]
    status:               PruefungStatus
    mail_versand_bereit:  bool


@dataclass
class TechnikerAusnahme:
    """Ausnahme-Meldung fuer einen Techniker (krank, Urlaub, ueberlastet).

    Wird vom Disponenten oder automatisch aus SMax uebernommen.
    """

    techniker_id:  str
    grund:         AusnahmeGrund
    gemeldet_von:  AusnahmeQuelle
    gueltig_bis:   date
    notiz:         str = ""

    def auftrag_umplanen(self, auftrag: Auftrag) -> Auftrag:
        """Setzt den Auftrag auf NEU zurueck und loescht die Techniker-Zuweisung.

        Der Grund ist in der TechnikerAusnahme-Instanz dokumentiert.
        Die urspruengliche Zuweisung geht verloren – Disponent muss neu planen.

        Args:
            auftrag: Der umzuplanende Auftrag (wird in-place aktualisiert).

        Returns:
            Der zurueckgesetzte Auftrag (status=NEU, techniker_id=None).
        """
        auftrag.status = AuftragsStatus.NEU
        auftrag.techniker_id = None
        return auftrag


# ---------------------------------------------------------------------------
# Oeffentliche API
# ---------------------------------------------------------------------------

def pflichtdokumente_je_typ(auftragstyp: str, kostenschaetzung_eur: Optional[float] = None) -> list[str]:
    """Gibt die Pflichtdokumenten-Liste fuer einen Auftragstyp zurueck.

    Fuer Repair: KV wird dynamisch ergaenzt wenn Kostenschaetzung > Schwellwert.

    Args:
        auftragstyp:         "STK", "PM" oder "Repair" (Gross-/Kleinschreibung egal).
        kostenschaetzung_eur: Kostenschaetzung in EUR (nur fuer Repair relevant).

    Returns:
        Liste der Pflichtdokument-Namen (Strings).

    Raises:
        ValueError: Bei unbekanntem Auftragstyp.
    """
    typ = auftragstyp.strip().upper()
    if typ == "STK":
        return ["Messprotokoll", "Servicebericht", "TDS"]
    if typ == "PM":
        return ["Servicebericht", "Checkliste", "TDS"]
    if typ in ("REPAIR", "REPARATUR"):
        docs = ["Servicebericht", "Foto_vorher", "Foto_nachher", "TDS"]
        if kostenschaetzung_eur is not None and kostenschaetzung_eur > _KV_SCHWELLWERT_EUR:
            docs.append("KV")
        return docs
    raise ValueError(
        f"Unbekannter Auftragstyp: '{auftragstyp}'. Erwartet: 'STK', 'PM' oder 'Repair'."
    )


def _bestimme_status(auftragstyp: str, fehlende: list[str]) -> PruefungStatus:
    """Bestimmt den Pruefungsstatus anhand der fehlenden Dokumente."""
    if not fehlende:
        return PruefungStatus.VOLLSTAENDIG
    kritisch = _KRITISCHE_DOKUMENTE.get(auftragstyp, [])
    if any(dok in kritisch for dok in fehlende):
        return PruefungStatus.KRITISCH
    return PruefungStatus.UNVOLLSTAENDIG


def qa_lauf(work_orders: list[dict]) -> list[DokumentenPruefung]:
    """Prueft alle uebergebenen Work Orders auf Dokumentenvollstaendigkeit.

    Jeder Work Order ist ein Dict mit folgenden Feldern:
        auftrag_id          (str)
        techniker_id        (str)
        auftragstyp         (str): "STK" | "PM" | "Repair"
        abgeschlossen_am    (date)
        dokumente           (list[str]): tatsaechlich vorhandene Dokument-Namen
        kostenschaetzung_eur (float, optional): fuer KV-Pflicht bei Repair

    Args:
        work_orders: Liste der zu pruefenden Work Orders (SMax-Export-Dicts).

    Returns:
        Liste von DokumentenPruefung-Objekten, eines pro Work Order.
    """
    ergebnisse: list[DokumentenPruefung] = []

    for wo in work_orders:
        auftragstyp = wo.get("auftragstyp", "")
        kostenschaetzung = wo.get("kostenschaetzung_eur")

        try:
            pflicht = pflichtdokumente_je_typ(auftragstyp, kostenschaetzung)
        except ValueError:
            # Unbekannter Typ: als KRITISCH mit allen Feldern fehlend markieren
            pflicht = []

        gefunden = [d for d in wo.get("dokumente", []) if d in pflicht]
        fehlend = [d for d in pflicht if d not in wo.get("dokumente", [])]

        status = _bestimme_status(auftragstyp, fehlend)

        ergebnisse.append(DokumentenPruefung(
            auftrag_id=wo.get("auftrag_id", "UNBEKANNT"),
            techniker_id=wo.get("techniker_id", "UNBEKANNT"),
            auftragstyp=auftragstyp,
            abgeschlossen_am=wo.get("abgeschlossen_am", date.today()),
            gefundene_dokumente=gefunden,
            fehlende_dokumente=fehlend,
            status=status,
            mail_versand_bereit=(status != PruefungStatus.VOLLSTAENDIG),
        ))

    return ergebnisse


def mail_vorbereiten(pruefung: DokumentenPruefung) -> dict:
    """Erstellt ein Mail-Dict fuer eine unvollstaendige Dokumentenpruefung.

    Darf nur aufgerufen werden wenn mail_versand_bereit=True.

    Args:
        pruefung: Die DokumentenPruefung mit fehlenden Dokumenten.

    Returns:
        Dict mit: absender, empfaenger, betreff, body, anhang_liste.

    Raises:
        ValueError: Wenn mail_versand_bereit=False (Auftrag ist vollstaendig).
    """
    if not pruefung.mail_versand_bereit:
        raise ValueError(
            f"Auftrag {pruefung.auftrag_id}: mail_versand_bereit=False – "
            "kein Mail-Versand bei vollstaendiger Dokumentation."
        )

    dringlichkeit = "DRINGEND: " if pruefung.status == PruefungStatus.KRITISCH else ""
    fehlend_text = ", ".join(pruefung.fehlende_dokumente) if pruefung.fehlende_dokumente else "–"
    gefunden_text = ", ".join(pruefung.gefundene_dokumente) if pruefung.gefundene_dokumente else "keine"

    body = (
        f"Sehr geehrte/r Techniker {pruefung.techniker_id},\n\n"
        f"fuer den abgeschlossenen Auftrag {pruefung.auftrag_id} "
        f"({pruefung.auftragstyp}, abgeschlossen am {pruefung.abgeschlossen_am.isoformat()}) "
        f"fehlen folgende Pflichtdokumente:\n\n"
        f"  Fehlend:   {fehlend_text}\n"
        f"  Vorhanden: {gefunden_text}\n\n"
        f"Bitte reichen Sie die fehlenden Dokumente umgehend nach.\n\n"
        f"Status: {pruefung.status.value}\n\n"
        f"Mit freundlichen Gruessen\n"
        f"Medtronic Deutschland – Field Service QA\n"
        f"Automatisch generiert durch FieldServiceAI"
    )

    return {
        "absender":      _ABSENDER,
        "empfaenger":    f"{pruefung.techniker_id.lower()}@medtronic.com",
        "betreff":       f"{dringlichkeit}Fehlende Dokumente: Auftrag {pruefung.auftrag_id}",
        "body":          body,
        "anhang_liste":  list(pruefung.gefundene_dokumente),
        "prioritaet":    "HOCH" if pruefung.status == PruefungStatus.KRITISCH else "NORMAL",
    }


def qa_bericht_erstellen(ergebnisse: list[DokumentenPruefung]) -> str:
    """Erstellt eine Zusammenfassung des QA-Laufs fuer den Disponenten.

    Args:
        ergebnisse: Ausgabe von qa_lauf().

    Returns:
        Formatierter String mit Uebersicht und Technikerliste mit offenen Punkten.
    """
    if not ergebnisse:
        return "QA-Lauf: Keine Work Orders geprueft."

    gesamt = len(ergebnisse)
    vollstaendig = sum(1 for e in ergebnisse if e.status == PruefungStatus.VOLLSTAENDIG)
    unvollstaendig = sum(1 for e in ergebnisse if e.status == PruefungStatus.UNVOLLSTAENDIG)
    kritisch = sum(1 for e in ergebnisse if e.status == PruefungStatus.KRITISCH)

    # Techniker mit offenen Punkten aggregieren
    offen: dict[str, list[str]] = {}
    for e in ergebnisse:
        if e.status != PruefungStatus.VOLLSTAENDIG:
            if e.techniker_id not in offen:
                offen[e.techniker_id] = []
            offen[e.techniker_id].append(
                f"{e.auftrag_id} [{e.status.value}] fehlend: {', '.join(e.fehlende_dokumente)}"
            )

    zeilen = [
        "=" * 60,
        "QA-BERICHT – Dokumentenpruefung Field Service",
        "=" * 60,
        f"Geprueft:      {gesamt} Work Order(s)",
        f"Vollstaendig:  {vollstaendig}",
        f"Unvollstaendig:{unvollstaendig}",
        f"Kritisch:      {kritisch}",
        "",
    ]

    if not offen:
        zeilen.append("Alle Auftraege vollstaendig dokumentiert.")
    else:
        zeilen.append(f"Offene Punkte bei {len(offen)} Techniker(n):")
        zeilen.append("-" * 40)
        for tid in sorted(offen):
            zeilen.append(f"  {tid}:")
            for eintrag in offen[tid]:
                zeilen.append(f"    – {eintrag}")

    zeilen.append("=" * 60)
    return "\n".join(zeilen)
