"""KV-Pruefung (Kostenvoranschlag) fuer Repair-Auftraege.

Ein KV ist erforderlich, wenn:
  - Auftragstyp == Repair UND
  - die Kostenschaetzung den konfigurierten Schwellwert ueberschreitet.

Der Schwellwert ist in _KV_SCHWELLWERT_EUR definiert und soll
nicht in der Logik hart kodiert werden.
"""

from __future__ import annotations

from .models import Auftrag, AuftragsTyp

# Konfiguration: Schwellwert fuer KV-Pflicht (EUR)
_KV_SCHWELLWERT_EUR: float = 500.0


def kv_erforderlich(auftrag: Auftrag) -> bool:
    """Prueft ob fuer diesen Auftrag ein Kostenvoranschlag erforderlich ist.

    Bedingungen (beide muessen zutreffen):
      1. Auftragstyp ist Repair
      2. Kostenschaetzung liegt vor UND ueberschreitet den Schwellwert

    Args:
        auftrag: Der zu pruefende Auftrag.

    Returns:
        True wenn KV benoetigt wird, False sonst.
    """
    if auftrag.auftragstyp != AuftragsTyp.REPAIR:
        return False
    if auftrag.kostenschaetzung_eur is None:
        return False
    return auftrag.kostenschaetzung_eur > _KV_SCHWELLWERT_EUR


def kv_bestaetigen(auftrag: Auftrag, betrag: float) -> None:
    """Setzt die Kostenschaetzung und markiert den KV als bestaetigt.

    Setzt kostenschaetzung_eur und kv_bestaetigt=True auf dem Auftrag.
    Wirft ValueError wenn betrag negativ oder Auftrag kein Repair ist.

    Args:
        auftrag: Der Repair-Auftrag, fuer den der KV bestaetigt wird.
        betrag:  Bestaetiger Betrag in EUR (muss >= 0 sein).

    Raises:
        ValueError: Bei negativem Betrag oder falschem Auftragstyp.
    """
    if auftrag.auftragstyp != AuftragsTyp.REPAIR:
        raise ValueError(
            f"KV-Bestaetigung nur fuer Repair-Auftraege moeglich, "
            f"nicht fuer {auftrag.auftragstyp.value}."
        )
    if betrag < 0:
        raise ValueError(f"KV-Betrag darf nicht negativ sein (erhalten: {betrag}).")
    auftrag.kostenschaetzung_eur = betrag
    auftrag.kv_bestaetigt = True
