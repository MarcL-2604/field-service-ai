"""Tests fuer auftraege.dokumente_qa – 2x woechentliche Dokumenten-QA."""

import pytest
from datetime import date

from auftraege.dokumente_qa import (
    DokumentenPruefung,
    PruefungStatus,
    TechnikerAusnahme,
    AusnahmeGrund,
    AusnahmeQuelle,
    pflichtdokumente_je_typ,
    qa_lauf,
    mail_vorbereiten,
    qa_bericht_erstellen,
    _KV_SCHWELLWERT_EUR,
)
from auftraege.models import Auftrag, AuftragsTyp, AuftragsStatus

_HEUTE = date(2026, 3, 27)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _work_order(
    auftrag_id="STK-TEST-001",
    techniker_id="T5",
    auftragstyp="STK",
    dokumente=None,
    kostenschaetzung_eur=None,
    abgeschlossen_am=None,
) -> dict:
    return {
        "auftrag_id": auftrag_id,
        "techniker_id": techniker_id,
        "auftragstyp": auftragstyp,
        "abgeschlossen_am": abgeschlossen_am or _HEUTE,
        "dokumente": dokumente or [],
        "kostenschaetzung_eur": kostenschaetzung_eur,
    }


def _vollstaendiger_stk() -> dict:
    return _work_order(dokumente=["Messprotokoll", "Servicebericht", "TDS"])


def _vollstaendiger_pm() -> dict:
    return _work_order(auftragstyp="PM", dokumente=["Servicebericht", "Checkliste", "TDS"])


def _vollstaendiger_repair(mit_kv=False) -> dict:
    docs = ["Servicebericht", "Foto_vorher", "Foto_nachher", "TDS"]
    if mit_kv:
        docs.append("KV")
    return _work_order(
        auftragstyp="Repair",
        dokumente=docs,
        kostenschaetzung_eur=600.0 if mit_kv else 100.0,
    )


def _auftrag_zugewiesen() -> Auftrag:
    return Auftrag(
        auftrag_id="STK-TEST-001",
        auftragstyp=AuftragsTyp.STK,
        klinik_name="Testklinik",
        geraet_id="NIM4CM01",
        produkt_familie="Neuromonitoring",
        faelligkeitsdatum=_HEUTE,
        techniker_id="T5",
        status=AuftragsStatus.ZUGEWIESEN,
    )


# ---------------------------------------------------------------------------
# pflichtdokumente_je_typ
# ---------------------------------------------------------------------------

class TestPflichtdokumenteJeTyp:
    def test_stk_enthaelt_messprotokoll(self):
        assert "Messprotokoll" in pflichtdokumente_je_typ("STK")

    def test_stk_enthaelt_servicebericht(self):
        assert "Servicebericht" in pflichtdokumente_je_typ("STK")

    def test_stk_enthaelt_tds(self):
        assert "TDS" in pflichtdokumente_je_typ("STK")

    def test_stk_genau_drei_dokumente(self):
        assert len(pflichtdokumente_je_typ("STK")) == 3

    def test_pm_enthaelt_servicebericht_und_checkliste(self):
        docs = pflichtdokumente_je_typ("PM")
        assert "Servicebericht" in docs
        assert "Checkliste" in docs
        assert "TDS" in docs

    def test_pm_genau_drei_dokumente(self):
        assert len(pflichtdokumente_je_typ("PM")) == 3

    def test_repair_enthaelt_fotos(self):
        docs = pflichtdokumente_je_typ("Repair")
        assert "Foto_vorher" in docs
        assert "Foto_nachher" in docs

    def test_repair_ohne_kv_kein_kv_dokument(self):
        docs = pflichtdokumente_je_typ("Repair", kostenschaetzung_eur=100.0)
        assert "KV" not in docs

    def test_repair_mit_kv_pflicht_enthaelt_kv(self):
        docs = pflichtdokumente_je_typ("Repair", kostenschaetzung_eur=_KV_SCHWELLWERT_EUR + 1)
        assert "KV" in docs

    def test_repair_exakt_schwellwert_kein_kv(self):
        # Schwellwert ist exklusiv (> 500, nicht >= 500)
        docs = pflichtdokumente_je_typ("Repair", kostenschaetzung_eur=_KV_SCHWELLWERT_EUR)
        assert "KV" not in docs

    def test_grosskleinschreibung_stk(self):
        assert pflichtdokumente_je_typ("stk") == pflichtdokumente_je_typ("STK")

    def test_unbekannter_typ_raises(self):
        with pytest.raises(ValueError, match="Unbekannter Auftragstyp"):
            pflichtdokumente_je_typ("WARTUNG")


# ---------------------------------------------------------------------------
# DokumentenPruefung Datenklasse
# ---------------------------------------------------------------------------

class TestDokumentenPruefungDatenklasse:
    def test_vollstaendig_erstellen(self):
        p = DokumentenPruefung(
            auftrag_id="STK-001",
            techniker_id="T5",
            auftragstyp="STK",
            abgeschlossen_am=_HEUTE,
            gefundene_dokumente=["Messprotokoll", "Servicebericht", "TDS"],
            fehlende_dokumente=[],
            status=PruefungStatus.VOLLSTAENDIG,
            mail_versand_bereit=False,
        )
        assert p.auftrag_id == "STK-001"
        assert p.status == PruefungStatus.VOLLSTAENDIG
        assert p.mail_versand_bereit is False

    def test_unvollstaendig_mail_bereit(self):
        p = DokumentenPruefung(
            auftrag_id="STK-002", techniker_id="T8", auftragstyp="STK",
            abgeschlossen_am=_HEUTE,
            gefundene_dokumente=["Messprotokoll", "Servicebericht"],
            fehlende_dokumente=["TDS"],
            status=PruefungStatus.UNVOLLSTAENDIG,
            mail_versand_bereit=True,
        )
        assert p.mail_versand_bereit is True
        assert "TDS" in p.fehlende_dokumente

    def test_pruefung_status_enum_werte(self):
        assert PruefungStatus.VOLLSTAENDIG.value == "VOLLSTAENDIG"
        assert PruefungStatus.UNVOLLSTAENDIG.value == "UNVOLLSTAENDIG"
        assert PruefungStatus.KRITISCH.value == "KRITISCH"


# ---------------------------------------------------------------------------
# qa_lauf
# ---------------------------------------------------------------------------

class TestQaLauf:
    def test_vollstaendiger_stk_ist_vollstaendig(self):
        ergebnisse = qa_lauf([_vollstaendiger_stk()])
        assert len(ergebnisse) == 1
        assert ergebnisse[0].status == PruefungStatus.VOLLSTAENDIG
        assert ergebnisse[0].mail_versand_bereit is False

    def test_vollstaendiger_pm_ist_vollstaendig(self):
        ergebnisse = qa_lauf([_vollstaendiger_pm()])
        assert ergebnisse[0].status == PruefungStatus.VOLLSTAENDIG

    def test_vollstaendiger_repair_ohne_kv_vollstaendig(self):
        ergebnisse = qa_lauf([_vollstaendiger_repair(mit_kv=False)])
        assert ergebnisse[0].status == PruefungStatus.VOLLSTAENDIG

    def test_vollstaendiger_repair_mit_kv_vollstaendig(self):
        ergebnisse = qa_lauf([_vollstaendiger_repair(mit_kv=True)])
        assert ergebnisse[0].status == PruefungStatus.VOLLSTAENDIG

    def test_fehlende_tds_ist_unvollstaendig(self):
        wo = _work_order(dokumente=["Messprotokoll", "Servicebericht"])  # TDS fehlt
        ergebnisse = qa_lauf([wo])
        assert ergebnisse[0].status == PruefungStatus.UNVOLLSTAENDIG
        assert "TDS" in ergebnisse[0].fehlende_dokumente

    def test_fehlende_checkliste_pm_ist_unvollstaendig(self):
        wo = _work_order(auftragstyp="PM", dokumente=["Servicebericht", "TDS"])
        ergebnisse = qa_lauf([wo])
        assert ergebnisse[0].status == PruefungStatus.UNVOLLSTAENDIG
        assert "Checkliste" in ergebnisse[0].fehlende_dokumente

    def test_fehlender_servicebericht_ist_kritisch(self):
        wo = _work_order(dokumente=["Messprotokoll", "TDS"])  # Servicebericht fehlt
        ergebnisse = qa_lauf([wo])
        assert ergebnisse[0].status == PruefungStatus.KRITISCH

    def test_fehlende_messprotokoll_stk_ist_kritisch(self):
        wo = _work_order(dokumente=["Servicebericht", "TDS"])  # Messprotokoll fehlt
        ergebnisse = qa_lauf([wo])
        assert ergebnisse[0].status == PruefungStatus.KRITISCH

    def test_fehlende_foto_repair_ist_kritisch(self):
        wo = _work_order(
            auftragstyp="Repair",
            dokumente=["Servicebericht", "TDS"],  # Fotos fehlen
        )
        ergebnisse = qa_lauf([wo])
        assert ergebnisse[0].status == PruefungStatus.KRITISCH

    def test_repair_fehlende_kv_bei_hoher_kostenschaetzung_unvollstaendig(self):
        wo = _work_order(
            auftragstyp="Repair",
            dokumente=["Servicebericht", "Foto_vorher", "Foto_nachher", "TDS"],
            kostenschaetzung_eur=800.0,  # KV erforderlich, aber fehlt
        )
        ergebnisse = qa_lauf([wo])
        assert ergebnisse[0].status == PruefungStatus.UNVOLLSTAENDIG
        assert "KV" in ergebnisse[0].fehlende_dokumente

    def test_gefundene_dokumente_enthaelt_nur_pflichtdokumente(self):
        # "Foto_intern" ist kein Pflichtdokument fuer STK
        wo = _work_order(dokumente=["Messprotokoll", "Servicebericht", "TDS", "Foto_intern"])
        ergebnisse = qa_lauf([wo])
        assert "Foto_intern" not in ergebnisse[0].gefundene_dokumente

    def test_leere_liste_gibt_leere_liste(self):
        assert qa_lauf([]) == []

    def test_mehrere_auftraege(self):
        ergebnisse = qa_lauf([_vollstaendiger_stk(), _vollstaendiger_pm()])
        assert len(ergebnisse) == 2

    def test_auftrag_id_wird_uebernommen(self):
        wo = _work_order(auftrag_id="STK-CUSTOM-999", dokumente=["Messprotokoll", "Servicebericht", "TDS"])
        ergebnisse = qa_lauf([wo])
        assert ergebnisse[0].auftrag_id == "STK-CUSTOM-999"

    def test_mail_bereit_wenn_unvollstaendig(self):
        wo = _work_order(dokumente=["Messprotokoll", "Servicebericht"])  # TDS fehlt
        ergebnisse = qa_lauf([wo])
        assert ergebnisse[0].mail_versand_bereit is True

    def test_mail_nicht_bereit_wenn_vollstaendig(self):
        ergebnisse = qa_lauf([_vollstaendiger_stk()])
        assert ergebnisse[0].mail_versand_bereit is False


# ---------------------------------------------------------------------------
# mail_vorbereiten
# ---------------------------------------------------------------------------

class TestMailVorbereiten:
    def _unvollstaendige_pruefung(self) -> DokumentenPruefung:
        return DokumentenPruefung(
            auftrag_id="STK-MAIL-001",
            techniker_id="T8",
            auftragstyp="STK",
            abgeschlossen_am=_HEUTE,
            gefundene_dokumente=["Messprotokoll", "Servicebericht"],
            fehlende_dokumente=["TDS"],
            status=PruefungStatus.UNVOLLSTAENDIG,
            mail_versand_bereit=True,
        )

    def test_mail_hat_alle_felder(self):
        mail = mail_vorbereiten(self._unvollstaendige_pruefung())
        for key in ("absender", "empfaenger", "betreff", "body", "anhang_liste", "prioritaet"):
            assert key in mail

    def test_absender_korrekt(self):
        mail = mail_vorbereiten(self._unvollstaendige_pruefung())
        assert mail["absender"] == "service@medtronic.com"

    def test_betreff_enthaelt_auftrag_id(self):
        mail = mail_vorbereiten(self._unvollstaendige_pruefung())
        assert "STK-MAIL-001" in mail["betreff"]

    def test_anhaenge_sind_gefundene_dokumente(self):
        pruefung = self._unvollstaendige_pruefung()
        mail = mail_vorbereiten(pruefung)
        assert mail["anhang_liste"] == pruefung.gefundene_dokumente

    def test_body_enthaelt_fehlende_dokumente(self):
        mail = mail_vorbereiten(self._unvollstaendige_pruefung())
        assert "TDS" in mail["body"]

    def test_body_enthaelt_techniker_id(self):
        mail = mail_vorbereiten(self._unvollstaendige_pruefung())
        assert "T8" in mail["body"]

    def test_kritisch_hat_prioritaet_hoch(self):
        pruefung = DokumentenPruefung(
            auftrag_id="STK-KRIT-001", techniker_id="T9", auftragstyp="STK",
            abgeschlossen_am=_HEUTE,
            gefundene_dokumente=["TDS"],
            fehlende_dokumente=["Servicebericht", "Messprotokoll"],
            status=PruefungStatus.KRITISCH,
            mail_versand_bereit=True,
        )
        mail = mail_vorbereiten(pruefung)
        assert mail["prioritaet"] == "HOCH"
        assert "DRINGEND" in mail["betreff"]

    def test_raises_wenn_mail_nicht_bereit(self):
        pruefung = DokumentenPruefung(
            auftrag_id="STK-OK-001", techniker_id="T5", auftragstyp="STK",
            abgeschlossen_am=_HEUTE,
            gefundene_dokumente=["Messprotokoll", "Servicebericht", "TDS"],
            fehlende_dokumente=[],
            status=PruefungStatus.VOLLSTAENDIG,
            mail_versand_bereit=False,
        )
        with pytest.raises(ValueError, match="mail_versand_bereit=False"):
            mail_vorbereiten(pruefung)


# ---------------------------------------------------------------------------
# qa_bericht_erstellen
# ---------------------------------------------------------------------------

class TestQaBerichtErstellen:
    def test_bericht_ist_string(self):
        ergebnisse = qa_lauf([_vollstaendiger_stk()])
        assert isinstance(qa_bericht_erstellen(ergebnisse), str)

    def test_leere_ergebnisse(self):
        bericht = qa_bericht_erstellen([])
        assert "Keine Work Orders" in bericht

    def test_bericht_enthaelt_vollstaendig_count(self):
        ergebnisse = qa_lauf([_vollstaendiger_stk(), _vollstaendiger_pm()])
        bericht = qa_bericht_erstellen(ergebnisse)
        assert "2" in bericht

    def test_bericht_enthaelt_techniker_mit_offenen_punkten(self):
        wo = _work_order(techniker_id="T8", dokumente=["Messprotokoll", "Servicebericht"])
        ergebnisse = qa_lauf([wo])
        bericht = qa_bericht_erstellen(ergebnisse)
        assert "T8" in bericht

    def test_bericht_ohne_offene_punkte(self):
        ergebnisse = qa_lauf([_vollstaendiger_stk()])
        bericht = qa_bericht_erstellen(ergebnisse)
        assert "vollstaendig dokumentiert" in bericht.lower() or "Vollstaendig" in bericht

    def test_bericht_enthaelt_kritisch_count(self):
        wo = _work_order(dokumente=["TDS"])  # Servicebericht + Messprotokoll fehlen → KRITISCH
        ergebnisse = qa_lauf([wo])
        bericht = qa_bericht_erstellen(ergebnisse)
        assert "1" in bericht
        assert "Kritisch" in bericht or "KRITISCH" in bericht


# ---------------------------------------------------------------------------
# TechnikerAusnahme
# ---------------------------------------------------------------------------

class TestTechnikerAusnahme:
    def test_ausnahme_erstellen(self):
        ausnahme = TechnikerAusnahme(
            techniker_id="T8",
            grund=AusnahmeGrund.KRANK,
            gemeldet_von=AusnahmeQuelle.DISPONENT_DASHBOARD,
            gueltig_bis=date(2026, 4, 3),
        )
        assert ausnahme.techniker_id == "T8"
        assert ausnahme.grund == AusnahmeGrund.KRANK

    def test_ausnahme_grund_enum_werte(self):
        assert AusnahmeGrund.KRANK.value == "KRANK"
        assert AusnahmeGrund.UEBERLASTET.value == "UEBERLASTET"
        assert AusnahmeGrund.URLAUB.value == "URLAUB"
        assert AusnahmeGrund.SONSTIGE.value == "SONSTIGE"

    def test_ausnahme_quelle_enum_werte(self):
        assert AusnahmeQuelle.TECHNIKER_SMAX.value == "TECHNIKER_SMAX"
        assert AusnahmeQuelle.DISPONENT_DASHBOARD.value == "DISPONENT_DASHBOARD"

    def test_auftrag_umplanen_setzt_status_neu(self):
        ausnahme = TechnikerAusnahme(
            techniker_id="T8",
            grund=AusnahmeGrund.KRANK,
            gemeldet_von=AusnahmeQuelle.TECHNIKER_SMAX,
            gueltig_bis=date(2026, 4, 3),
        )
        auftrag = _auftrag_zugewiesen()
        assert auftrag.status == AuftragsStatus.ZUGEWIESEN
        ausnahme.auftrag_umplanen(auftrag)
        assert auftrag.status == AuftragsStatus.NEU

    def test_auftrag_umplanen_loescht_techniker_id(self):
        ausnahme = TechnikerAusnahme(
            techniker_id="T5",
            grund=AusnahmeGrund.URLAUB,
            gemeldet_von=AusnahmeQuelle.DISPONENT_DASHBOARD,
            gueltig_bis=date(2026, 4, 10),
        )
        auftrag = _auftrag_zugewiesen()
        assert auftrag.techniker_id == "T5"
        ausnahme.auftrag_umplanen(auftrag)
        assert auftrag.techniker_id is None

    def test_auftrag_umplanen_gibt_auftrag_zurueck(self):
        ausnahme = TechnikerAusnahme(
            techniker_id="T5",
            grund=AusnahmeGrund.UEBERLASTET,
            gemeldet_von=AusnahmeQuelle.DISPONENT_DASHBOARD,
            gueltig_bis=date(2026, 4, 5),
        )
        auftrag = _auftrag_zugewiesen()
        result = ausnahme.auftrag_umplanen(auftrag)
        assert result is auftrag  # gleiche Objektinstanz

    def test_auftrag_umplanen_in_arbeit_auf_neu(self):
        ausnahme = TechnikerAusnahme(
            techniker_id="T5",
            grund=AusnahmeGrund.KRANK,
            gemeldet_von=AusnahmeQuelle.TECHNIKER_SMAX,
            gueltig_bis=date(2026, 4, 3),
        )
        auftrag = _auftrag_zugewiesen()
        auftrag.status = AuftragsStatus.IN_ARBEIT
        ausnahme.auftrag_umplanen(auftrag)
        assert auftrag.status == AuftragsStatus.NEU

    def test_notiz_default_leer(self):
        ausnahme = TechnikerAusnahme(
            techniker_id="T5",
            grund=AusnahmeGrund.SONSTIGE,
            gemeldet_von=AusnahmeQuelle.DISPONENT_DASHBOARD,
            gueltig_bis=date(2026, 4, 1),
        )
        assert ausnahme.notiz == ""

    def test_notiz_kann_gesetzt_werden(self):
        ausnahme = TechnikerAusnahme(
            techniker_id="T5",
            grund=AusnahmeGrund.KRANK,
            gemeldet_von=AusnahmeQuelle.TECHNIKER_SMAX,
            gueltig_bis=date(2026, 4, 3),
            notiz="Krankenschein liegt vor",
        )
        assert "Krankenschein" in ausnahme.notiz
