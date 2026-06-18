"""Abschlusskontrolle: Prueft ob alle Pflichtdokumente vor Auftragsabschluss vorliegen.

Pflichtdokumente je Auftragstyp:
  STK:    Messprotokoll + Servicebericht
  PM:     Servicebericht + Checkliste
  Repair: Servicebericht + Foto_vorher + Foto_nachher
          + KV (wenn Kostenschaetzung > Schwellwert)

Die KV-Pflicht wird dynamisch ueber kv_pruefung.kv_erforderlich() bestimmt.
"""

from __future__ import annotations

from .kv_pruefung import kv_erforderlich
from .models import Auftrag, AuftragsTyp, DokumentTyp

# Basispflichtdokumente je Auftragstyp (ohne KV-Sonderregel)
_BASISPFLICHT: dict[AuftragsTyp, list[DokumentTyp]] = {
    AuftragsTyp.STK: [
        DokumentTyp.MESSPROTOKOLL,
        DokumentTyp.SERVICEBERICHT,
    ],
    AuftragsTyp.PM: [
        DokumentTyp.SERVICEBERICHT,
        DokumentTyp.CHECKLISTE,
    ],
    AuftragsTyp.REPAIR: [
        DokumentTyp.SERVICEBERICHT,
        DokumentTyp.FOTO_VORHER,
        DokumentTyp.FOTO_NACHHER,
    ],
}


def pflichtdokumente_pruefen(auftrag: Auftrag) -> dict[str, object]:
    """Prueft ob alle Pflichtdokumente fuer den Auftragsabschluss vorliegen.

    Gibt ein Ergebnis-Dict zurueck:
      - vollstaendig (bool): True wenn alle Pflichtdokumente angehaengt sind
      - fehlend (list[str]): DokumentTyp-Namen der fehlenden Dokumente
      - erforderliche_typen (list[str]): alle Pflicht-DokumentTyp-Namen fuer diesen Auftrag

    Die fehlenden Dokumente werden aus der Dokumente-Liste des Auftrags bestimmt.
    Dokumente, die in der Pflichtliste stehen aber nicht in auftrag.dokumente
    vorhanden sind, gelten ebenfalls als fehlend.

    Args:
        auftrag: Der zu pruefende Auftrag.

    Returns:
        Dict mit den Schluesseln 'vollstaendig', 'fehlend', 'erforderliche_typen'.
    """
    erforderlich = list(_BASISPFLICHT[auftrag.auftragstyp])

    # Dynamische KV-Pflicht fuer Repair
    if kv_erforderlich(auftrag) and DokumentTyp.KV not in erforderlich:
        erforderlich.append(DokumentTyp.KV)

    # Schneller Lookup: welche Typen sind als angehaengt markiert?
    angehaengt: set[DokumentTyp] = {
        dok.typ for dok in auftrag.dokumente if dok.angehaengt
    }

    fehlend = [typ for typ in erforderlich if typ not in angehaengt]

    return {
        "vollstaendig": len(fehlend) == 0,
        "fehlend": [t.value for t in fehlend],
        "erforderliche_typen": [t.value for t in erforderlich],
    }
