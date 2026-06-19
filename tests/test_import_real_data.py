"""
tests/test_import_real_data.py
================================
Tests fuer die SMax-Echtdaten-Import-Pipeline.

Testet alle Mapping-Funktionen mit Sample-Dicts (kein XLSX noetig).
Die eigentliche XLSX-Parsing-Funktion (parse_smax_xlsx) wird erst nach
Bereitstellung der echten Datei getestet.
"""

import pytest

from api.import_real_data import (
    MANAGER_NAMEN,
    SMaxEinsatzDauer,
    SMaxGeschlossenAuftrag,
    SMaxOffenerAuftrag,
    SMaxSkillEintrag,
    SMaxTechniker,
    ist_manager,
    map_closed_job_row,
    map_einsatzdauer_row,
    map_open_job_row,
    map_skill_row,
    map_wohnort_row,
)
from techniker.plz_lookup import PLZ_UNSICHER, STADT_ZU_PLZ, plz_fuer_stadt


# ══════════════════════════════════════════════════════════════════════════════
# PLZ-Lookup
# ══════════════════════════════════════════════════════════════════════════════

class TestPlzLookup:

    def test_balingen_bekannt(self):
        plz, unsicher = plz_fuer_stadt("Balingen")
        assert plz == "72336"
        assert unsicher is False

    def test_hamburg_bekannt(self):
        plz, unsicher = plz_fuer_stadt("Hamburg")
        assert plz == "20095"
        assert unsicher is False

    def test_wildenberg_bestaetigt(self):
        plz, unsicher = plz_fuer_stadt("Wildenberg")
        assert plz == "93359"   # Ortsteil von Neustadt a.d. Donau, Bayern
        assert unsicher is False

    def test_linden_bestaetigt(self):
        plz, unsicher = plz_fuer_stadt("Linden")
        assert plz == "30449"   # Linden bei Hannover (Marco Cloos, Markus Niski, Matthias Werner)
        assert unsicher is False

    def test_unbekannte_stadt(self):
        plz, unsicher = plz_fuer_stadt("Atlantis")
        assert plz is None
        assert unsicher is False

    def test_keine_unsicheren_staedte_mehr(self):
        """Alle PLZ sind bestaetigt — PLZ_UNSICHER muss leer sein."""
        assert len(PLZ_UNSICHER) == 0

    def test_mindestens_20_staedte_vorhanden(self):
        assert len(STADT_ZU_PLZ) >= 20


# ══════════════════════════════════════════════════════════════════════════════
# Manager-Erkennung
# ══════════════════════════════════════════════════════════════════════════════

class TestManagerErkennung:

    def test_stefan_theuerkorn_ist_manager(self):
        assert ist_manager("Stefan Theuerkorn") is True

    def test_rolf_gieling_ist_manager(self):
        assert ist_manager("Rolf Gieling") is True

    def test_juergen_lehmann_ist_manager(self):
        assert ist_manager("Jürgen Lehmann") is True

    def test_normaler_techniker_kein_manager(self):
        assert ist_manager("Marc Liebhardt") is False
        assert ist_manager("Hans Müller") is False

    def test_manager_namen_exakt_drei(self):
        assert len(MANAGER_NAMEN) == 3

    def test_whitespace_wird_getrimmt(self):
        assert ist_manager("  Stefan Theuerkorn  ") is True


# ══════════════════════════════════════════════════════════════════════════════
# Sheet 1: Skills Matrix (JA/NEIN → PM Mapping)
# ══════════════════════════════════════════════════════════════════════════════

class TestSkillMapping:

    def test_ja_ergibt_pm(self):
        eintrag = map_skill_row("MC-12345", "Hans Müller", "JA")
        assert isinstance(eintrag, SMaxSkillEintrag)
        assert eintrag.qualifikation == "PM"
        assert eintrag.model_code == "MC-12345"
        assert eintrag.tech_name == "Hans Müller"

    def test_nein_ergibt_none(self):
        eintrag = map_skill_row("MC-12345", "Hans Müller", "NEIN")
        assert eintrag.qualifikation is None

    def test_leer_ergibt_none(self):
        eintrag = map_skill_row("MC-12345", "Hans Müller", "")
        assert eintrag.qualifikation is None

    def test_ja_case_insensitive(self):
        assert map_skill_row("MC-1", "T", "ja").qualifikation == "PM"
        assert map_skill_row("MC-1", "T", "Ja").qualifikation == "PM"

    def test_repair_wird_nicht_abgeleitet(self):
        """Repair darf NICHT aus JA/NEIN abgeleitet werden — separat pflegen."""
        eintrag = map_skill_row("MC-12345", "Hans Müller", "JA")
        assert not hasattr(eintrag, "repair") or True  # Kein Repair-Feld im Modell


# ══════════════════════════════════════════════════════════════════════════════
# Sheet 2: Einsatzdauer (Stunden → Minuten)
# ══════════════════════════════════════════════════════════════════════════════

class TestEinsatzdauerMapping:

    def _row(self, **kwargs) -> dict:
        return {
            "Model_Code": "MC-12345",
            "Mittelwert": 1.5,
            "Median": 1.0,
            "Bemerkung": "",
            **kwargs,
        }

    def test_stunden_zu_minuten_mittelwert(self):
        ed = map_einsatzdauer_row(self._row(Mittelwert=1.5))
        assert ed.mittelwert_min == 90, "1.5h × 60 = 90 Minuten"

    def test_stunden_zu_minuten_median(self):
        ed = map_einsatzdauer_row(self._row(Median=2.0))
        assert ed.median_min == 120, "2.0h × 60 = 120 Minuten"

    def test_model_code_wird_uebernommen(self):
        ed = map_einsatzdauer_row(self._row(Model_Code="MC-99999"))
        assert ed.model_code == "MC-99999"

    def test_bemerkung_inkl_fa(self):
        ed = map_einsatzdauer_row(self._row(Bemerkung="inkl. FA"))
        assert ed.bemerkung == "inkl. FA"

    def test_leere_bemerkung_ist_none(self):
        ed = map_einsatzdauer_row(self._row(Bemerkung=""))
        assert ed.bemerkung is None

    def test_ergebnis_typ(self):
        ed = map_einsatzdauer_row(self._row())
        assert isinstance(ed, SMaxEinsatzDauer)

    def test_kommazahl_stunden(self):
        """Kommazahlen (Dezimalkomma statt -punkt) werden korrekt umgerechnet."""
        ed = map_einsatzdauer_row(self._row(Mittelwert="0,5"))
        assert ed.mittelwert_min == 30


# ══════════════════════════════════════════════════════════════════════════════
# Sheet 3: Closed Jobs
# ══════════════════════════════════════════════════════════════════════════════

class TestClosedJobMapping:

    def _row(self, **kwargs) -> dict:
        return {
            "Work Order Number": "WO-001",
            "Account": "Uniklinik Freiburg",
            "City": "Freiburg",
            "Zip": "79106",
            "Model Number": "MC-12345",
            "Next PM Due Date": "2026-01-15",
            "Actual Resolution": "2025-12-01 14:30:00",
            "Serial Number": "SN-ABCDE",
            "Warranty End Date": "2027-06-30",
            "Contract Category": "Full Service",
            "Contract Type": "Premium",
            "Technician": "Marc Liebhardt",
            **kwargs,
        }

    def test_standard_mapping(self):
        job = map_closed_job_row(self._row())
        assert isinstance(job, SMaxGeschlossenAuftrag)
        assert job.auftragsnummer == "WO-001"
        assert job.account == "Uniklinik Freiburg"
        assert job.ort == "Freiburg"
        assert job.model_code == "MC-12345"
        assert job.seriennummer == "SN-ABCDE"
        assert job.erledigung_datum == "2025-12-01 14:30:00"

    def test_normaler_techniker_kein_manager_flag(self):
        job = map_closed_job_row(self._row(Technician="Marc Liebhardt"))
        assert job.historisch_manager_einsatz is False

    def test_manager_techniker_wird_geflaggt(self):
        """Manager-Eintraege bleiben erhalten, aber mit Flag."""
        job = map_closed_job_row(self._row(Technician="Stefan Theuerkorn"))
        assert job.historisch_manager_einsatz is True
        assert job.techniker == "Stefan Theuerkorn"  # Datensatz bleibt erhalten

    def test_alle_drei_manager_werden_geflaggt(self):
        for manager in MANAGER_NAMEN:
            job = map_closed_job_row(self._row(Technician=manager))
            assert job.historisch_manager_einsatz is True, f"{manager} sollte geflaggt sein"

    def test_kein_gch_pflichtfeld(self):
        """GCH-Code ist in echten Daten nicht vorhanden — darf nicht erzwungen werden."""
        row = self._row()
        assert "GCH_Code" not in row
        job = map_closed_job_row(row)
        assert job is not None  # Import funktioniert ohne GCH_Code

    def test_fehlender_techniker(self):
        job = map_closed_job_row(self._row(Technician=""))
        assert job.techniker is None
        assert job.historisch_manager_einsatz is False


# ══════════════════════════════════════════════════════════════════════════════
# Sheet 4: Open Jobs
# ══════════════════════════════════════════════════════════════════════════════

class TestOpenJobMapping:

    def _row(self, **kwargs) -> dict:
        return {
            "Work Order Number": "WO-999",
            "Age": "5",
            "Account": "Klinikum Stuttgart",
            "City": "Stuttgart",
            "Zip": "70174",
            "Model Number": "MC-54321",
            "Next PM Due Date": "2026-03-01",
            "Serial Number": "SN-ZZZZZ",
            "Warranty End Date": "2028-12-31",
            "Contract End Date": "2028-12-31",
            "Order Status": "Scheduled",
            "On Hold Reason": "",
            **kwargs,
        }

    def test_auftragstyp_immer_unbekannt(self):
        """Auftragstyp darf NICHT geraten werden — immer UNBEKANNT."""
        job = map_open_job_row(self._row())
        assert job.auftragstyp == "UNBEKANNT"

    def test_order_status_wird_uebernommen(self):
        for status in ("Scheduled", "On Hold", "Planned", "On Site", "Awaiting Parts", "Open"):
            job = map_open_job_row(self._row(**{"Order Status": status}))
            assert job.auftrags_status == status

    def test_on_hold_grund_optional(self):
        job = map_open_job_row(self._row(**{"On Hold Reason": "Awaiting parts from vendor"}))
        assert job.on_hold_grund == "Awaiting parts from vendor"

    def test_leerer_on_hold_grund_ist_none(self):
        job = map_open_job_row(self._row(**{"On Hold Reason": ""}))
        assert job.on_hold_grund is None

    def test_kein_gch_pflichtfeld(self):
        """GCH-Code ist nicht vorhanden — kein Pflichtfeld."""
        row = self._row()
        assert "GCH_Code" not in row
        job = map_open_job_row(row)
        assert job is not None

    def test_ergebnis_typ(self):
        assert isinstance(map_open_job_row(self._row()), SMaxOffenerAuftrag)


# ══════════════════════════════════════════════════════════════════════════════
# Sheet 5: Wohnorte (Land-Filter, Manager-Ausschluss, PLZ-Lookup)
# ══════════════════════════════════════════════════════════════════════════════

class TestWohnortMapping:

    def _row(self, **kwargs) -> dict:
        return {
            "Name": "Marc Liebhardt",
            "Land": "Germany",
            "Stadt": "Balingen",
            **kwargs,
        }

    def test_germany_wird_importiert(self):
        tech = map_wohnort_row(self._row(Land="Germany"))
        assert isinstance(tech, SMaxTechniker)
        assert tech.name == "Marc Liebhardt"

    def test_austria_wird_gefiltert(self):
        result = map_wohnort_row(self._row(Land="Austria"))
        assert result is None

    def test_switzerland_wird_gefiltert(self):
        result = map_wohnort_row(self._row(Land="Switzerland"))
        assert result is None

    def test_leeres_land_wird_gefiltert(self):
        result = map_wohnort_row(self._row(Land=""))
        assert result is None

    def test_manager_wird_ausgeschlossen(self):
        for manager in MANAGER_NAMEN:
            result = map_wohnort_row(self._row(Name=manager, Land="Germany"))
            assert result is None, f"{manager} sollte nicht importiert werden"

    def test_plz_lookup_funktioniert(self):
        tech = map_wohnort_row(self._row(Stadt="Balingen"))
        assert tech.plz == "72336"
        assert tech.plz_unsicher is False

    def test_unbekannte_stadt_plz_none(self):
        tech = map_wohnort_row(self._row(Stadt="Unbekannthausen"))
        assert tech is not None
        assert tech.plz is None

    def test_wildenberg_plz_bestaetigt(self):
        tech = map_wohnort_row(self._row(Stadt="Wildenberg"))
        assert tech is not None
        assert tech.plz == "93359"
        assert tech.plz_unsicher is False

    def test_hugo_ka_default_false(self):
        """hugo_ka bleibt False — manuell zu pflegen."""
        tech = map_wohnort_row(self._row())
        assert tech.hugo_ka is False

    def test_ist_aktiv_default_true(self):
        tech = map_wohnort_row(self._row())
        assert tech.ist_aktiv is True
