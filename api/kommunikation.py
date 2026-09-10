"""
api/kommunikation.py
=====================
Kommunikations-Grundgeruest fuer automatisierte Techniker-Benachrichtigungen
(Mail). STATUS: Grundgeruest, standardmaessig deaktiviert (siehe
config.KOMMUNIKATION_AUTOMATISCH_AKTIV).

Solange der Schalter False ist, wird NIE eine echte Mail versendet -- jeder
Aufruf schreibt stattdessen einen Log-Eintrag nach
data/kommunikation_log.jsonl ("WUERDE SENDEN AN: ..."). Das gilt auch dann,
wenn der Schalter aktiviert wird, aber die Zieladresse ein Platzhalter ist
(siehe data/techniker_kontakte.json) -- das ist ein bewusstes Sicherheitsnetz
gegen Versand an nicht-existente Adressen.

Ein echter Versand ist nur fuer genau EINEN Fall vorgesehen: Schalter aktiv +
Techniker mit echter Adresse (aktuell nur Marc Liebhardt) + expliziter
Testkontext-Aufruf. Die SMTP-Zugangsdaten kommen ausschliesslich aus
Umgebungsvariablen, nie aus dem Code.

Fuer die Aktivierung im Regelbetrieb fehlen noch: Backend-Entscheidung
(interner Server vs. Cloud-Dienst), echte Adressen aller 24 Techniker,
IT-Freigabe. Siehe manual.html, Kapitel 1.10.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from config import KOMMUNIKATION_AUTOMATISCH_AKTIV

_ROOT = Path(__file__).resolve().parent.parent
_KONTAKTE_DATEI = _ROOT / "data" / "techniker_kontakte.json"
_LOG_DATEI = _ROOT / "data" / "kommunikation_log.jsonl"

_PLATZHALTER_MARKER = "PLATZHALTER"


def lade_techniker_kontakte(pfad: Path | None = None) -> dict[str, str]:
    """Laedt die Techniker-E-Mail-Kontakte.

    Faellt sauber auf ein leeres Dict zurueck, wenn die Datei fehlt (z.B. bei
    anderen Entwicklern/Umgebungen ohne die gitignored Kontaktdatei) oder
    beschaedigt ist -- kein Absturz, einfach Demo-Modus ohne echte Kontakte.
    """
    datei = pfad or _KONTAKTE_DATEI
    try:
        rohdaten = json.loads(datei.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return {k: v for k, v in rohdaten.items() if not k.startswith("_")}


def _ist_platzhalter_adresse(email: str | None) -> bool:
    if not email:
        return True
    return _PLATZHALTER_MARKER in email.upper()


def _auftrag_kurzbeschreibung(auftrag: Any) -> str:
    """Extrahiert eine lesbare Kurzbeschreibung -- funktioniert sowohl mit
    dict-artigen Auftraegen als auch mit auftraege.models.Auftrag-Objekten,
    ohne eine harte Abhaengigkeit auf die Modellklasse einzugehen (Grundgeruest,
    noch nicht in die Auftrags-Pipeline verdrahtet)."""

    def _feld(name: str, default: str = "?") -> str:
        if isinstance(auftrag, dict):
            return str(auftrag.get(name, default))
        return str(getattr(auftrag, name, default))

    return f"{_feld('auftrag_id')} · {_feld('klinik_name')}"


def _log_eintrag(
    *, techniker_name: str, empfaenger: str | None, betreff: str, modus: str, grund: str,
) -> None:
    eintrag = {
        "zeitstempel": datetime.now().isoformat(timespec="seconds"),
        "techniker": techniker_name,
        "empfaenger": empfaenger,
        "betreff": betreff,
        "modus": modus,
        "grund": grund,
    }
    _LOG_DATEI.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_DATEI.open("a", encoding="utf-8") as f:
        f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")


def _sende_echte_mail(empfaenger: str, betreff: str, text: str) -> None:
    """Sendet ueber lokale SMTP-Konfiguration aus Umgebungsvariablen.

    Zugangsdaten werden NIE im Code hinterlegt. Fehlen sie, wird ein
    RuntimeError geworfen -- der Aufrufer faengt das ab und loggt stattdessen
    (Fallback statt Absturz)."""
    host = os.environ.get("FSA_SMTP_HOST")
    port = os.environ.get("FSA_SMTP_PORT")
    absender = os.environ.get("FSA_SMTP_ABSENDER")
    if not host or not port or not absender:
        raise RuntimeError(
            "SMTP nicht konfiguriert (FSA_SMTP_HOST/FSA_SMTP_PORT/FSA_SMTP_ABSENDER fehlen)"
        )

    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = betreff
    msg["From"] = absender
    msg["To"] = empfaenger
    msg.set_content(text)

    user = os.environ.get("FSA_SMTP_USER")
    password = os.environ.get("FSA_SMTP_PASSWORD")
    with smtplib.SMTP(host, int(port), timeout=10) as smtp:
        smtp.starttls()
        if user and password:
            smtp.login(user, password)
        smtp.send_message(msg)


def sende_auftrags_benachrichtigung(
    techniker_name: str,
    auftrag: Any,
    *,
    testkontext: bool = False,
) -> dict[str, Any]:
    """Zentrale Funktion fuer Techniker-Auftragsbenachrichtigungen.

    Sicherheitslogik (siehe Modul-Docstring):
      1. Schalter AUS               -> immer nur Log-Eintrag.
      2. Platzhalter-Adresse        -> immer nur Log-Eintrag, unabhaengig
                                        vom Schalter.
      3. Schalter AN + echte Adresse
         + techniker == "Marc Liebhardt" + testkontext=True
                                     -> echter SMTP-Versand (mit Log-Fallback
                                        bei SMTP-Fehler).
      4. Alle anderen Faelle        -> Log-Eintrag (Sicherheitsnetz).

    Gibt ein Ergebnis-Dict zurueck: {"versendet": bool, "modus": str,
    "empfaenger": str | None}.
    """
    kontakte = lade_techniker_kontakte()
    empfaenger = kontakte.get(techniker_name)
    betreff = f"Field Service AI -- Auftragsbenachrichtigung: {_auftrag_kurzbeschreibung(auftrag)}"
    text = f"Hallo {techniker_name},\n\nneuer Auftrag: {_auftrag_kurzbeschreibung(auftrag)}.\n"

    if not KOMMUNIKATION_AUTOMATISCH_AKTIV:
        _log_eintrag(techniker_name=techniker_name, empfaenger=empfaenger, betreff=betreff,
                     modus="log", grund="KOMMUNIKATION_AUTOMATISCH_AKTIV=False")
        return {"versendet": False, "modus": "log", "empfaenger": empfaenger}

    if _ist_platzhalter_adresse(empfaenger):
        _log_eintrag(techniker_name=techniker_name, empfaenger=empfaenger, betreff=betreff,
                     modus="log", grund="Platzhalter-Adresse -- kein echter Versand moeglich")
        return {"versendet": False, "modus": "log", "empfaenger": empfaenger}

    if techniker_name == "Marc Liebhardt" and testkontext:
        try:
            _sende_echte_mail(empfaenger, betreff, text)
            return {"versendet": True, "modus": "smtp", "empfaenger": empfaenger}
        except Exception as exc:  # noqa: BLE001 -- bewusst breit: SMTP darf nie hart abstuerzen
            _log_eintrag(techniker_name=techniker_name, empfaenger=empfaenger, betreff=betreff,
                         modus="log_fallback", grund=f"SMTP fehlgeschlagen: {exc}")
            return {"versendet": False, "modus": "log_fallback", "empfaenger": empfaenger}

    _log_eintrag(techniker_name=techniker_name, empfaenger=empfaenger, betreff=betreff,
                 modus="log", grund="Kein Testkontext oder nicht Marc Liebhardt -- Sicherheitsnetz")
    return {"versendet": False, "modus": "log", "empfaenger": empfaenger}
