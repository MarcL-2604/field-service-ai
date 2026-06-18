"""Tests fuer Repair-Workflow: SLA-Timer, Eskalation, Ersatzteil-Verfuegbarkeit.

Repair-Auftraege haben eigene Reaktionszeit-Logik, getrennt von STK/PM.
"""

from datetime import date, datetime, timedelta

import pytest

from auftraege.models import (
    Auftrag,
    AuftragsTyp,
    PlanungsTyp,
    RepairPhase,
    REPAIR_SLA_STUNDEN,
    REPAIR_ZIEL_KONTAKT,
)
from auftraege.workflow import (
    bewerte_repair_sla,
    repair_kontakt_herstellen,
    repair_einsatz_planen,
    RepairSlaStatus,
    _REPAIR_SLA_GELB,
    _REPAIR_SLA_ROT,
    _REPAIR_SLA_KRITISCH,
)
from auftraege.trunkstock import (
    pruefe_ersatzteil_verfuegbarkeit,
    ErsatzteilVerfuegbarkeit,
    ErsatzteilStatus,
)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _repair_auftrag(
    auftrag_id="REP-001",
    klinik_id="K001",
    klinik_name="UKE Hamburg",
    produkt="Hugo",
    geraet_id="HugoRAS",
    eingangsdatum=None,
    repair_phase=RepairPhase.EINGANG,
    kontakt_hergestellt_am=None,
    fehler_beschreibung=None,
) -> Auftrag:
    return Auftrag(
        auftrag_id=auftrag_id,
        auftragstyp=AuftragsTyp.REPAIR,
        klinik_id=klinik_id,
        klinik_name=klinik_name,
        geraet_id=geraet_id,
        produkt_familie=produkt,
        faelligkeitsdatum=date(2026, 4, 15),
        eingangsdatum=eingangsdatum,
        repair_phase=repair_phase,
        kontakt_hergestellt_am=kontakt_hergestellt_am,
        fehler_beschreibung=fehler_beschreibung,
    )


# ===================================================================
# 1. PLANUNGSTYP
# ===================================================================

class TestPlanungsTyp:
    """STK/PM = Vorausplanung, Repair = Reaktionsplanung."""

    def test_stk_ist_vorausplanung(self):
        a = Auftrag(
            auftrag_id="STK-001", auftragstyp=AuftragsTyp.STK,
            klinik_name="Test", geraet_id="NIM", produkt_familie="NIM",
            faelligkeitsdatum=date(2026, 4, 1),
        )
        assert a.planungstyp == PlanungsTyp.VORAUSPLANUNG

    def test_pm_ist_vorausplanung(self):
        a = Auftrag(
            auftrag_id="PM-001", auftragstyp=AuftragsTyp.PM,
            klinik_name="Test", geraet_id="NIM", produkt_familie="NIM",
            faelligkeitsdatum=date(2026, 4, 1),
        )
        assert a.planungstyp == PlanungsTyp.VORAUSPLANUNG

    def test_repair_ist_reaktionsplanung(self):
        a = _repair_auftrag()
        assert a.planungstyp == PlanungsTyp.REAKTIONSPLANUNG


# ===================================================================
# 2. REPAIR SLA KONSTANTEN
# ===================================================================

class TestRepairKonstanten:

    def test_sla_stunden(self):
        assert REPAIR_SLA_STUNDEN == 48

    def test_ziel_kontakt(self):
        assert REPAIR_ZIEL_KONTAKT == 24

    def test_eskalationsschwellen(self):
        assert _REPAIR_SLA_GELB == 24
        assert _REPAIR_SLA_ROT == 40
        assert _REPAIR_SLA_KRITISCH == 48


# ===================================================================
# 3. REPAIR PHASEN
# ===================================================================

class TestRepairPhasen:

    def test_alle_phasen_vorhanden(self):
        assert len(RepairPhase) == 8

    def test_phase_reihenfolge(self):
        phasen = list(RepairPhase)
        namen = [p.name for p in phasen]
        assert namen[0] == "EINGANG"
        assert namen[-1] == "ABGESCHLOSSEN"

    def test_default_phase_ist_eingang(self):
        a = _repair_auftrag()
        assert a.repair_phase == RepairPhase.EINGANG

    def test_repair_felder_optional(self):
        """Repair-Felder koennen None sein (fuer STK/PM-Auftraege)."""
        a = Auftrag(
            auftrag_id="STK-001", auftragstyp=AuftragsTyp.STK,
            klinik_name="Test", geraet_id="NIM", produkt_familie="NIM",
            faelligkeitsdatum=date(2026, 4, 1),
        )
        assert a.eingangsdatum is None
        assert a.kontakt_hergestellt_am is None
        assert a.fehler_beschreibung is None


# ===================================================================
# 4. SLA-BEWERTUNG
# ===================================================================

class TestRepairSlaBewertung:
    """Tests fuer bewerte_repair_sla()."""

    def test_frischer_auftrag_gruen(self):
        """< 24h, kein Kontakt → trotzdem GRUEN (noch Zeit)."""
        jetzt = datetime(2026, 4, 2, 10, 0)
        a = _repair_auftrag(eingangsdatum=jetzt - timedelta(hours=5))
        sla = bewerte_repair_sla(a, jetzt=jetzt)
        assert sla.status == RepairSlaStatus.GRUEN
        assert sla.stunden_seit_eingang == pytest.approx(5.0, abs=0.1)
        assert sla.stunden_verbleibend == pytest.approx(43.0, abs=0.1)
        assert sla.kontakt_hergestellt is False
        assert sla.warnung is None

    def test_24h_ohne_kontakt_gelb(self):
        """>= 24h ohne Kontakt → GELB."""
        jetzt = datetime(2026, 4, 2, 10, 0)
        a = _repair_auftrag(eingangsdatum=jetzt - timedelta(hours=25))
        sla = bewerte_repair_sla(a, jetzt=jetzt)
        assert sla.status == RepairSlaStatus.GELB
        assert "Kundenkontakt steht aus" in sla.warnung

    def test_40h_ohne_kontakt_rot(self):
        """>= 40h ohne Kontakt → ROT."""
        jetzt = datetime(2026, 4, 2, 10, 0)
        a = _repair_auftrag(eingangsdatum=jetzt - timedelta(hours=41))
        sla = bewerte_repair_sla(a, jetzt=jetzt)
        assert sla.status == RepairSlaStatus.ROT
        assert "Gefaehrdung" in sla.warnung

    def test_48h_ohne_kontakt_kritisch(self):
        """>= 48h ohne Kontakt → KRITISCH + Eskalation."""
        jetzt = datetime(2026, 4, 2, 10, 0)
        a = _repair_auftrag(eingangsdatum=jetzt - timedelta(hours=50))
        sla = bewerte_repair_sla(a, jetzt=jetzt)
        assert sla.status == RepairSlaStatus.KRITISCH
        assert "VERLETZT" in sla.warnung
        assert sla.stunden_verbleibend < 0
        assert len(sla.benachrichtigungen) >= 1
        assert any("ESKALATION" in b for b in sla.benachrichtigungen)

    def test_kontakt_hergestellt_gruen(self):
        """Kontakt hergestellt → immer GRUEN."""
        jetzt = datetime(2026, 4, 2, 10, 0)
        a = _repair_auftrag(
            eingangsdatum=jetzt - timedelta(hours=30),
            kontakt_hergestellt_am=jetzt - timedelta(hours=5),
            repair_phase=RepairPhase.KONTAKT_HERGESTELLT,
        )
        sla = bewerte_repair_sla(a, jetzt=jetzt)
        assert sla.status == RepairSlaStatus.GRUEN
        assert sla.kontakt_hergestellt is True
        assert sla.warnung is None

    def test_ersatzteil_bestellt_blau(self):
        """Kontakt hergestellt + Ersatzteil bestellt → BLAU."""
        jetzt = datetime(2026, 4, 2, 10, 0)
        a = _repair_auftrag(
            eingangsdatum=jetzt - timedelta(hours=30),
            kontakt_hergestellt_am=jetzt - timedelta(hours=5),
            repair_phase=RepairPhase.ERSATZTEIL_BESTELLT,
        )
        sla = bewerte_repair_sla(a, jetzt=jetzt)
        assert sla.status == RepairSlaStatus.BLAU

    def test_ohne_eingangsdatum_nutzt_jetzt(self):
        """Ohne eingangsdatum → 0h seit Eingang."""
        jetzt = datetime(2026, 4, 2, 10, 0)
        a = _repair_auftrag(eingangsdatum=None)
        sla = bewerte_repair_sla(a, jetzt=jetzt)
        assert sla.stunden_seit_eingang == pytest.approx(0.0, abs=0.1)
        assert sla.status == RepairSlaStatus.GRUEN

    def test_exakt_grenze_24h(self):
        jetzt = datetime(2026, 4, 2, 10, 0)
        a = _repair_auftrag(eingangsdatum=jetzt - timedelta(hours=24))
        sla = bewerte_repair_sla(a, jetzt=jetzt)
        assert sla.status == RepairSlaStatus.GELB

    def test_exakt_grenze_40h(self):
        jetzt = datetime(2026, 4, 2, 10, 0)
        a = _repair_auftrag(eingangsdatum=jetzt - timedelta(hours=40))
        sla = bewerte_repair_sla(a, jetzt=jetzt)
        assert sla.status == RepairSlaStatus.ROT

    def test_exakt_grenze_48h(self):
        jetzt = datetime(2026, 4, 2, 10, 0)
        a = _repair_auftrag(eingangsdatum=jetzt - timedelta(hours=48))
        sla = bewerte_repair_sla(a, jetzt=jetzt)
        assert sla.status == RepairSlaStatus.KRITISCH


# ===================================================================
# 5. KONTAKT HERSTELLEN
# ===================================================================

class TestRepairKontaktHerstellen:

    def test_kontakt_setzt_phase(self):
        a = _repair_auftrag(
            eingangsdatum=datetime(2026, 4, 1, 8, 0),
            repair_phase=RepairPhase.KONTAKT_AUSSTEHEND,
        )
        jetzt = datetime(2026, 4, 1, 14, 0)
        sla = repair_kontakt_herstellen(a, "T6", jetzt=jetzt)
        assert a.repair_phase == RepairPhase.KONTAKT_HERGESTELLT
        assert a.kontakt_hergestellt_am == jetzt
        assert sla.kontakt_hergestellt is True
        assert sla.status == RepairSlaStatus.GRUEN

    def test_kontakt_setzt_techniker(self):
        a = _repair_auftrag()
        repair_kontakt_herstellen(a, "T10")
        assert a.techniker_id == "T10"

    def test_kontakt_nach_sla_verletzung_trotzdem_gruen(self):
        """Auch nach 50h: Kontakt herstellen → GRUEN."""
        jetzt = datetime(2026, 4, 3, 10, 0)
        a = _repair_auftrag(eingangsdatum=jetzt - timedelta(hours=50))
        sla = repair_kontakt_herstellen(a, "T6", jetzt=jetzt)
        assert sla.status == RepairSlaStatus.GRUEN


# ===================================================================
# 6. REPAIR EINSATZ PLANEN
# ===================================================================

class TestRepairEinsatzPlanen:

    def test_sofort_morgen(self):
        """SOFORT → fruehestens morgen (1 Tag)."""
        heute = date(2026, 4, 6)  # Montag
        termin = repair_einsatz_planen(
            _repair_auftrag(), "SOFORT", heute=heute
        )
        assert termin == date(2026, 4, 7)  # Dienstag

    def test_lager_2_tage(self):
        """LAGER → 2 Tage Lieferzeit."""
        heute = date(2026, 4, 6)  # Montag
        termin = repair_einsatz_planen(
            _repair_auftrag(), "LAGER", heute=heute
        )
        assert termin == date(2026, 4, 8)  # Mittwoch

    def test_bestellen_5_tage(self):
        """BESTELLEN → 5 Tage Lieferzeit."""
        heute = date(2026, 4, 6)  # Montag
        termin = repair_einsatz_planen(
            _repair_auftrag(), "BESTELLEN", heute=heute
        )
        # Mo+5 Kalendertage = Sa → springt auf Mo 13.4.
        assert termin == date(2026, 4, 13)  # Montag

    def test_unbekannt_diagnose_morgen(self):
        """UNBEKANNT → Diagnose-Einsatz morgen."""
        heute = date(2026, 4, 6)  # Montag
        termin = repair_einsatz_planen(
            _repair_auftrag(), "UNBEKANNT", heute=heute
        )
        assert termin == date(2026, 4, 7)  # Dienstag

    def test_kein_mindest_vorlauf_3_tage(self):
        """Repair hat KEINEN 3-Tage-Mindestvorlauf wie STK/PM."""
        heute = date(2026, 4, 6)  # Montag
        termin = repair_einsatz_planen(
            _repair_auftrag(), "SOFORT", heute=heute
        )
        # STK/PM haette mindestens Do 9.4., Repair kann schon Di 7.4.
        assert termin == date(2026, 4, 7)

    def test_einsatz_immer_mo_do(self):
        """Auch Repair-Einsaetze sind Mo-Do."""
        # Donnerstag + 1 = Freitag → springt auf Montag
        heute = date(2026, 4, 9)  # Donnerstag
        termin = repair_einsatz_planen(
            _repair_auftrag(), "SOFORT", heute=heute
        )
        assert termin.weekday() <= 3  # Mo-Do


# ===================================================================
# 7. ERSATZTEIL-VERFUEGBARKEIT
# ===================================================================

class TestErsatzteilVerfuegbarkeit:
    """Tests fuer pruefe_ersatzteil_verfuegbarkeit()."""

    def test_enum_werte(self):
        assert len(ErsatzteilVerfuegbarkeit) == 4
        assert ErsatzteilVerfuegbarkeit.SOFORT.value == "Sofort"
        assert ErsatzteilVerfuegbarkeit.LAGER.value == "Lager"
        assert ErsatzteilVerfuegbarkeit.BESTELLEN.value == "Bestellen"
        assert ErsatzteilVerfuegbarkeit.UNBEKANNT.value == "Unbekannt"

    def test_ergebnis_ist_dataclass(self):
        status = pruefe_ersatzteil_verfuegbarkeit("T1", "Hugo")
        assert isinstance(status, ErsatzteilStatus)
        assert hasattr(status, "verfuegbarkeit")
        assert hasattr(status, "lieferzeit_min_tage")
        assert hasattr(status, "lieferzeit_max_tage")
        assert hasattr(status, "benoetigte_teile")
        assert hasattr(status, "im_fahrzeug")
        assert hasattr(status, "fehlende_teile")
        assert hasattr(status, "hinweis")

    def test_lieferzeiten_positiv(self):
        status = pruefe_ersatzteil_verfuegbarkeit("T1", "Hugo")
        assert status.lieferzeit_min_tage >= 1
        assert status.lieferzeit_max_tage >= status.lieferzeit_min_tage

    def test_unbekannte_familie_unbekannt(self):
        """Unbekannte Produktfamilie → UNBEKANNT."""
        status = pruefe_ersatzteil_verfuegbarkeit("T1", "Fantasie")
        assert status.verfuegbarkeit == ErsatzteilVerfuegbarkeit.UNBEKANNT

    def test_fehler_unklar_unbekannt(self):
        """Fehlerbeschreibung 'unklar' → UNBEKANNT."""
        status = pruefe_ersatzteil_verfuegbarkeit(
            "T1", "Hugo", fehler_beschreibung="Fehler unklar, Geraet piept"
        )
        assert status.verfuegbarkeit == ErsatzteilVerfuegbarkeit.UNBEKANNT
        assert "Diagnose" in status.hinweis

    def test_benoetigte_teile_nicht_leer(self):
        """Bekannte Familien haben mindestens 1 Ersatzteil."""
        status = pruefe_ersatzteil_verfuegbarkeit("T1", "Hugo")
        assert len(status.benoetigte_teile) > 0

    def test_hinweis_nicht_leer(self):
        status = pruefe_ersatzteil_verfuegbarkeit("T1", "Hugo")
        assert len(status.hinweis) > 0

    def test_fehlende_plus_fahrzeug_gleich_benoetigte(self):
        """im_fahrzeug + fehlende_teile = benoetigte_teile."""
        status = pruefe_ersatzteil_verfuegbarkeit("T5", "Neuromonitoring")
        assert set(status.im_fahrzeug) | set(status.fehlende_teile) == set(status.benoetigte_teile)

    def test_sofort_wenn_alles_im_fahrzeug(self):
        """Wenn alle Teile im Trunkstock → SOFORT."""
        # Dies ist ein Demo-Test: ET-*-Teile sind nicht im trunkstock.csv,
        # daher werden die meisten als LAGER oder BESTELLEN klassifiziert.
        # Testen wir die Logik mit der tatsaechlichen Verfuegbarkeit.
        status = pruefe_ersatzteil_verfuegbarkeit("T1", "Hugo")
        # Ergebnis haengt von trunkstock.csv ab, pruefen nur Konsistenz
        if not status.fehlende_teile:
            assert status.verfuegbarkeit == ErsatzteilVerfuegbarkeit.SOFORT
        else:
            assert status.verfuegbarkeit in (
                ErsatzteilVerfuegbarkeit.LAGER,
                ErsatzteilVerfuegbarkeit.BESTELLEN,
            )


# ===================================================================
# 8. INTEGRATION: REPAIR KOMPLETTER WORKFLOW
# ===================================================================

class TestRepairWorkflowIntegration:
    """End-to-end Test fuer den Repair-Workflow."""

    def test_repair_workflow_happy_path(self):
        """Normaler Ablauf: Eingang → Kontakt → Ersatzteil → Einsatz."""
        jetzt = datetime(2026, 4, 2, 8, 0)

        # Phase 1: Auftrag geht ein
        a = _repair_auftrag(
            eingangsdatum=jetzt,
            repair_phase=RepairPhase.KONTAKT_AUSSTEHEND,
        )
        sla = bewerte_repair_sla(a, jetzt=jetzt)
        assert sla.status == RepairSlaStatus.GRUEN

        # Phase 2: Nach 6h Kontakt herstellen
        kontakt_zeit = jetzt + timedelta(hours=6)
        sla = repair_kontakt_herstellen(a, "T6", jetzt=kontakt_zeit)
        assert sla.status == RepairSlaStatus.GRUEN
        assert a.repair_phase == RepairPhase.KONTAKT_HERGESTELLT

        # Phase 3: Ersatzteil pruefen
        et_status = pruefe_ersatzteil_verfuegbarkeit("T6", a.produkt_familie)
        assert et_status.verfuegbarkeit in ErsatzteilVerfuegbarkeit

        # Phase 4: Einsatz planen
        termin = repair_einsatz_planen(
            a, et_status.verfuegbarkeit.name, heute=kontakt_zeit.date()
        )
        assert termin is not None
        assert termin.weekday() <= 3  # Mo-Do

    def test_repair_sla_eskalation_workflow(self):
        """SLA-Eskalation: GRUEN → GELB → ROT → KRITISCH."""
        eingang = datetime(2026, 4, 1, 8, 0)
        a = _repair_auftrag(eingangsdatum=eingang)

        # 5h: GRUEN
        sla = bewerte_repair_sla(a, jetzt=eingang + timedelta(hours=5))
        assert sla.status == RepairSlaStatus.GRUEN

        # 25h: GELB
        sla = bewerte_repair_sla(a, jetzt=eingang + timedelta(hours=25))
        assert sla.status == RepairSlaStatus.GELB

        # 42h: ROT
        sla = bewerte_repair_sla(a, jetzt=eingang + timedelta(hours=42))
        assert sla.status == RepairSlaStatus.ROT

        # 50h: KRITISCH
        sla = bewerte_repair_sla(a, jetzt=eingang + timedelta(hours=50))
        assert sla.status == RepairSlaStatus.KRITISCH
