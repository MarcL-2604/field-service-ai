"""
tests/test_offene_auftraege_echtdaten.py
==========================================
Tests fuer Schritt 1 der Modul-1-Vervollstaendigung: echte offene SMax-
Auftraege werden im Aufraege-Tab als einzelne Zeilen angezeigt (statt nur
als Aggregatzahl), Demo-Modus bleibt unveraendert.
"""

import datetime
import json
from datetime import date
from pathlib import Path

import pytest

import reporting.dashboard as dash

_ROOT = Path(__file__).parent.parent


def _job(auftragsnummer="SMAX-0001", klinik="Klinikum Test", model_code="MC-FT10",
         produktfamilie="HF_CHIRURGIE", faellig_iso=None, status="Scheduled",
         repair_kandidat=False):
    return {
        "auftragsnummer": auftragsnummer,
        "klinik": klinik,
        "ort": "Teststadt",
        "plz": "12345",
        "model_code": model_code,
        "produktfamilie": produktfamilie,
        "faellig_iso": faellig_iso,
        "status": status,
        "on_hold_grund": None,
        "auftragstyp": "UNBEKANNT",
        "repair_kandidat": repair_kandidat,
    }


class TestBaueStkRowsEchtdaten:
    def test_sortiert_nach_faelligkeit_bekannte_zuerst(self):
        jobs = [
            _job("A", faellig_iso=None),
            _job("B", faellig_iso="2026-12-01"),
            _job("C", faellig_iso="2026-09-15"),
        ]
        rows = dash._baue_stk_rows_echtdaten(jobs, heute=date(2026, 9, 10), n=10)
        assert [r["auftrag_id"] for r in rows] == ["C", "B", "A"]

    def test_ohne_datum_zeigt_bindestrich_und_normal(self):
        rows = dash._baue_stk_rows_echtdaten([_job("A", faellig_iso=None)], heute=date(2026, 9, 10))
        assert rows[0]["faelligkeit"] == "&ndash;"
        assert rows[0]["tage"] == "&ndash;"
        assert rows[0]["dringlichkeit"] == "NORMAL"
        assert rows[0]["termine_vorschlag"] == "&ndash;"

    def test_mit_datum_berechnet_echte_dringlichkeit(self):
        rows = dash._baue_stk_rows_echtdaten(
            [_job("A", faellig_iso="2026-09-15")], heute=date(2026, 9, 10))
        assert rows[0]["dringlichkeit"] == "KRITISCH"
        assert rows[0]["faelligkeit"] == "15.09.2026"

    def test_begrenzt_auf_n(self):
        jobs = [_job(f"J{i}", faellig_iso=f"2026-09-{10 + i:02d}") for i in range(15)]
        rows = dash._baue_stk_rows_echtdaten(jobs, heute=date(2026, 9, 1), n=5)
        assert len(rows) == 5

    def test_klinik_ohne_namen_zeigt_bindestrich(self):
        rows = dash._baue_stk_rows_echtdaten([_job("A", klinik="")], heute=date(2026, 9, 10))
        assert rows[0]["klinik"] == "&ndash;"

    def test_leere_liste_ergibt_leere_liste(self):
        assert dash._baue_stk_rows_echtdaten([], heute=date(2026, 9, 10)) == []


class TestBaueRepairVerdachtRowsEchtdaten:
    def test_filtert_auf_repair_kandidat(self):
        jobs = [_job("A", repair_kandidat=True), _job("B", repair_kandidat=False)]
        rows = dash._baue_repair_verdacht_rows_echtdaten(jobs, n=10)
        assert [r["auftrag_id"] for r in rows] == ["A"]

    def test_typ_hinweis_gesetzt(self):
        rows = dash._baue_repair_verdacht_rows_echtdaten([_job("A", repair_kandidat=True)], n=10)
        assert rows[0]["typ_hinweis"] == "Repair (Geraet reparaturfaehig)"

    def test_begrenzt_auf_n(self):
        jobs = [_job(f"J{i}", repair_kandidat=True) for i in range(15)]
        rows = dash._baue_repair_verdacht_rows_echtdaten(jobs, n=5)
        assert len(rows) == 5

    def test_leere_liste_ohne_kandidaten(self):
        jobs = [_job("A", repair_kandidat=False)]
        assert dash._baue_repair_verdacht_rows_echtdaten(jobs, n=10) == []

    def test_sortiert_nach_faelligkeit_wenn_bekannt(self):
        jobs = [
            _job("A", repair_kandidat=True, faellig_iso="2026-12-01"),
            _job("B", repair_kandidat=True, faellig_iso="2026-09-15"),
        ]
        rows = dash._baue_repair_verdacht_rows_echtdaten(jobs, n=10)
        assert [r["auftrag_id"] for r in rows] == ["B", "A"]


class TestRenderOffeneEchtdatenTabelle:
    def test_leere_liste_zeigt_hinweistext(self):
        html = dash._render_offene_echtdaten_tabelle([])
        assert "Keine offenen" in html

    def test_rendert_zeile_mit_allen_feldern(self):
        rows = dash._baue_repair_verdacht_rows_echtdaten(
            [_job("SMAX-0007", repair_kandidat=True)], n=10)
        html = dash._render_offene_echtdaten_tabelle(rows)
        assert "SMAX-0007" in html
        assert "Klinikum Test" in html
        assert "MC-FT10" in html
        assert "HF_CHIRURGIE" in html
        assert 'data-label-de="Repair (Geraet reparaturfaehig)"' in html

    def test_status_wird_nicht_data_label_de_gewrappt(self):
        """SMax-Statuswerte sind bereits Englisch (Fremdsystem-Vokabular) --
        keine data-label-de-Uebersetzung noetig/erwuenscht (siehe
        LABEL_MAP_EN-Docstring/i18n-Komplettaudit)."""
        rows = dash._baue_repair_verdacht_rows_echtdaten(
            [_job("A", status="Awaiting Parts", repair_kandidat=True)], n=10)
        html = dash._render_offene_echtdaten_tabelle(rows)
        assert "Awaiting Parts" in html
        assert 'data-label-de="Awaiting Parts"' not in html


class TestSectionTexte:
    def test_stk_texte_unterscheiden_sich_je_modus(self):
        demo = dash._stk_section_texte(False)
        echt = dash._stk_section_texte(True)
        assert demo != echt
        assert "STK-Aufträge" in demo[0]
        assert "SMax" in echt[2]

    def test_repair_texte_unterscheiden_sich_je_modus(self):
        demo = dash._repair_section_texte(False)
        echt = dash._repair_section_texte(True)
        assert demo != echt
        assert "Repair-Aufträge" in demo[0]
        assert "Repair-Verdacht" in echt[0]

    def test_alle_texte_haben_de_und_en_variante(self):
        for fn in (dash._stk_section_texte, dash._repair_section_texte):
            for modus in (True, False):
                h_de, h_en, hint_de, hint_en = fn(modus)
                assert h_de and h_en and hint_de and hint_en
                assert h_de != h_en
                assert hint_de != hint_en


class TestRenderHtmlIntegration:
    _TECHNIKER = {"T1": {"standort": "Hamburg", "lat": 53.5, "lon": 10.0}}

    def test_echtdaten_modus_zeigt_echte_auftraege_und_repair_verdacht(self):
        stk_rows = dash._baue_stk_rows_echtdaten(
            [_job("SMAX-0001", faellig_iso="2026-09-20")], heute=date(2026, 9, 10))
        repair_verdacht_rows = dash._baue_repair_verdacht_rows_echtdaten(
            [_job("SMAX-0099", repair_kandidat=True)], n=10)

        html = dash.render_html(
            ampeln=[], stk_rows=stk_rows, ct_top5=[], techniker=self._TECHNIKER,
            nrw_warnung=None, erstellt_am=datetime.datetime(2026, 9, 10),
            is_echtdaten=True, repair_verdacht_rows=repair_verdacht_rows,
        )
        assert "SMAX-0001" in html
        assert "SMAX-0099" in html
        assert "Repair-Verdacht" in html
        assert "STK-Aufträge (Top 10)" not in html

    def test_demo_modus_bleibt_unveraendert(self):
        html = dash.render_html(
            ampeln=[], stk_rows=[], ct_top5=[], techniker=self._TECHNIKER,
            nrw_warnung=None, erstellt_am=datetime.datetime(2026, 9, 10),
            is_echtdaten=False,
        )
        assert "STK-Aufträge (Top 10)" in html
        assert "Offene Repair-Aufträge" in html
        assert "Repair-Verdacht" not in html


class TestSmaxCacheOffeneAuftraegeReal:
    """Regressionsschutz fuer die tatsaechliche (committete) Cache-Datei,
    falls sie vorhanden ist -- sonst wird der Test uebersprungen."""

    def test_reale_cachedatei_hat_offene_auftraege_mit_erwartetem_schema(self):
        cache = _ROOT / "data" / "smax_dashboard_data.json"
        if not cache.exists():
            pytest.skip("data/smax_dashboard_data.json nicht vorhanden")
        d = json.loads(cache.read_text(encoding="utf-8"))
        if "offene_auftraege" not in d:
            pytest.skip("Cache-Datei noch ohne offene_auftraege-Feld (alter Stand)")
        oa = d["offene_auftraege"]
        assert isinstance(oa, list)
        assert oa, "erwartet mindestens einen offenen Auftrag im echten Datensatz"
        pflichtfelder = (
            "auftragsnummer", "klinik", "model_code", "produktfamilie",
            "faellig_iso", "status", "auftragstyp", "repair_kandidat",
        )
        for key in pflichtfelder:
            assert key in oa[0]
        assert all(o["auftragsnummer"] for o in oa), "Auftragsnummer darf nie leer sein (Fallback SMAX-xxxx)"
        assert all(o["auftragstyp"] == "UNBEKANNT" for o in oa)
        assert any(o["repair_kandidat"] for o in oa)
        assert any(not o["repair_kandidat"] for o in oa)
