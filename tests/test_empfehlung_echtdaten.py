"""
tests/test_empfehlung_echtdaten.py
=====================================
Tests fuer Schritt 3 der Modul-1-Vervollstaendigung: Techniker-Vorauswahl
(KI-Scoring) fuer echte offene SMax-Auftraege statt nur fuer den
Musterauftrag in workflow_demo.html.
"""

import datetime
import json
from pathlib import Path

import pytest

import reporting.dashboard as dash
from techniker.scoring import EmpfehlungErgebnis, berechne_empfehlung_echtdaten

_ROOT = Path(__file__).parent.parent


def _techniker(pseudonym_id, lat, lon, auslastung_pct=50.0,
               qualifiziert=None, qualifiziert_repair=None):
    return {
        "pseudonym_id": pseudonym_id,
        "lat": lat,
        "lon": lon,
        "auslastung_pct_real": auslastung_pct,
        "qualifizierte_model_codes": qualifiziert or [],
        "qualifizierte_model_codes_repair": qualifiziert_repair or [],
    }


class TestBerechneEmpfehlungEchtdaten:
    def test_leer_wenn_plz_nicht_aufloesbar(self):
        ergebnis = berechne_empfehlung_echtdaten(
            "MC-FT10", "00000000-keine-plz", [_techniker("A", 50.0, 8.0, qualifiziert=["MC-FT10"])])
        assert ergebnis == []

    def test_filtert_auf_qualifizierte_techniker(self):
        techniker = [
            _techniker("Qualifiziert", 48.0, 9.0, qualifiziert=["MC-FT10"]),
            _techniker("NichtQualifiziert", 48.0, 9.0, qualifiziert=["MC-ANDERES"]),
        ]
        ergebnis = berechne_empfehlung_echtdaten("MC-FT10", "72336", techniker)
        ids = {e.techniker_id for e in ergebnis}
        assert ids == {"Qualifiziert"}

    def test_repair_erforderlich_nutzt_repair_feld(self):
        techniker = [_techniker("A", 48.0, 9.0, qualifiziert=["MC-FT10"], qualifiziert_repair=[])]
        ergebnis = berechne_empfehlung_echtdaten("MC-FT10", "72336", techniker, repair_erforderlich=True)
        assert ergebnis == []

        techniker[0]["qualifizierte_model_codes_repair"] = ["MC-FT10"]
        ergebnis = berechne_empfehlung_echtdaten("MC-FT10", "72336", techniker, repair_erforderlich=True)
        assert len(ergebnis) == 1

    def test_naeherer_techniker_hat_hoeheren_fahrzeit_score(self):
        # Balingen (72336) als Referenzklinik
        techniker = [
            _techniker("Nah", 48.2747, 8.8522, qualifiziert=["MC-FT10"]),  # Balingen selbst
            _techniker("Fern", 53.5, 10.0, qualifiziert=["MC-FT10"]),      # Hamburg
        ]
        ergebnis = berechne_empfehlung_echtdaten("MC-FT10", "72336", techniker)
        nah = next(e for e in ergebnis if e.techniker_id == "Nah")
        fern = next(e for e in ergebnis if e.techniker_id == "Fern")
        assert nah.fahrzeit_score > fern.fahrzeit_score
        assert nah.distanz_km < fern.distanz_km

    def test_niedrigere_auslastung_hoeherer_score(self):
        techniker = [
            _techniker("Frei", 48.0, 9.0, auslastung_pct=10.0, qualifiziert=["MC-FT10"]),
            _techniker("Voll", 48.0, 9.0, auslastung_pct=90.0, qualifiziert=["MC-FT10"]),
        ]
        ergebnis = berechne_empfehlung_echtdaten("MC-FT10", "72336", techniker)
        frei = next(e for e in ergebnis if e.techniker_id == "Frei")
        voll = next(e for e in ergebnis if e.techniker_id == "Voll")
        assert frei.auslastung_score > voll.auslastung_score
        assert frei.score > voll.score

    def test_kompetenz_score_immer_binaer_100(self):
        """Reale SMax-Skillmatrix kennt keine Level -- qualifiziert bedeutet
        immer volle Kompetenz (100), nie ein Zwischenwert."""
        techniker = [_techniker("A", 48.0, 9.0, qualifiziert=["MC-FT10"])]
        ergebnis = berechne_empfehlung_echtdaten("MC-FT10", "72336", techniker)
        assert ergebnis[0].kompetenz_score == 100.0
        assert ergebnis[0].level == "L3"

    def test_begrenzt_auf_top_3(self):
        techniker = [
            _techniker(f"T{i}", 48.0 + i * 0.1, 9.0, qualifiziert=["MC-FT10"])
            for i in range(6)
        ]
        ergebnis = berechne_empfehlung_echtdaten("MC-FT10", "72336", techniker)
        assert len(ergebnis) == 3

    def test_sortiert_absteigend_nach_score(self):
        techniker = [
            _techniker("A", 48.0, 9.0, auslastung_pct=80.0, qualifiziert=["MC-FT10"]),
            _techniker("B", 48.0, 9.0, auslastung_pct=10.0, qualifiziert=["MC-FT10"]),
        ]
        ergebnis = berechne_empfehlung_echtdaten("MC-FT10", "72336", techniker)
        scores = [e.score for e in ergebnis]
        assert scores == sorted(scores, reverse=True)

    def test_ohne_techniker_ohne_koordinaten_uebersprungen(self):
        techniker = [_techniker("KeineKoords", 0.0, 0.0, qualifiziert=["MC-FT10"])]
        ergebnis = berechne_empfehlung_echtdaten("MC-FT10", "72336", techniker)
        assert ergebnis == []

    def test_ergebnis_ist_liste_von_empfehlungergebnis(self):
        techniker = [_techniker("A", 48.0, 9.0, qualifiziert=["MC-FT10"])]
        ergebnis = berechne_empfehlung_echtdaten("MC-FT10", "72336", techniker)
        assert isinstance(ergebnis[0], EmpfehlungErgebnis)


class TestBaueEmpfehlungenEchtdaten:
    def _job(self, auftragsnummer, model_code="MC-FT10", plz="72336",
             klinik="Klinikum Test", repair_kandidat=False):
        return {
            "auftragsnummer": auftragsnummer, "model_code": model_code,
            "plz": plz, "klinik": klinik, "repair_kandidat": repair_kandidat,
        }

    def test_nur_angeforderte_auftragsnummern_enthalten(self):
        jobs = [self._job("A"), self._job("B"), self._job("C")]
        ergebnis = dash._baue_empfehlungen_echtdaten(jobs, {"A", "C"}, [])
        assert set(ergebnis.keys()) == {"A", "C"}

    def test_enthaelt_klinik_und_geraet(self):
        jobs = [self._job("A", model_code="MC-XY", klinik="Klinikum Musterstadt")]
        ergebnis = dash._baue_empfehlungen_echtdaten(jobs, {"A"}, [])
        assert ergebnis["A"]["klinik"] == "Klinikum Musterstadt"
        assert ergebnis["A"]["geraet"] == "MC-XY"

    def test_empfehlungen_leer_ohne_techniker(self):
        jobs = [self._job("A")]
        ergebnis = dash._baue_empfehlungen_echtdaten(jobs, {"A"}, [])
        assert ergebnis["A"]["empfehlungen"] == []

    def test_empfehlungen_gefuellt_mit_qualifiziertem_techniker(self):
        jobs = [self._job("A", model_code="MC-FT10", plz="72336")]
        techniker = [_techniker("Marc L.", 48.2747, 8.8522, qualifiziert=["MC-FT10"])]
        ergebnis = dash._baue_empfehlungen_echtdaten(jobs, {"A"}, techniker)
        assert len(ergebnis["A"]["empfehlungen"]) == 1
        assert ergebnis["A"]["empfehlungen"][0]["techniker_id"] == "Marc L."

    def test_leere_menge_ergibt_leeres_dict(self):
        assert dash._baue_empfehlungen_echtdaten([self._job("A")], set(), []) == {}


class TestUiWiring:
    _ROW = {
        "auftrag_id": "SMAX-0001", "klinik": "Klinikum Test", "geraet": "MC-FT10",
        "produkt": "HF_CHIRURGIE", "faelligkeit": "&ndash;", "termine_vorschlag": "&ndash;",
        "dringlichkeit": "NORMAL", "tage": "&ndash;",
    }

    def test_stk_tabelle_ohne_empfehlung_button_per_default(self):
        html = dash._render_stk_tabelle([self._ROW])
        assert "showEmpfehlung" not in html

    def test_stk_tabelle_mit_empfehlung_button_wenn_angefordert(self):
        html = dash._render_stk_tabelle([self._ROW], zeige_empfehlung=True)
        assert "showEmpfehlung('SMAX-0001')" in html

    def test_offene_echtdaten_tabelle_hat_immer_empfehlung_button(self):
        rows = dash._baue_repair_verdacht_rows_echtdaten(
            [{
                "auftragsnummer": "SMAX-0099", "klinik": "K", "model_code": "MC-X",
                "produktfamilie": "SMALL_CAPITAL", "status": "Open", "repair_kandidat": True,
                "faellig_iso": None,
            }],
            n=10,
        )
        html = dash._render_offene_echtdaten_tabelle(rows)
        assert "showEmpfehlung('SMAX-0099')" in html

    def test_abschnitt1_ohne_spalte_per_default(self):
        html = dash._render_auftraege_abschnitt1("<tr></tr>", "", "Titel", "Hinweis")
        assert "th.recommendation" not in html

    def test_abschnitt1_mit_spalte_wenn_angefordert(self):
        html = dash._render_auftraege_abschnitt1(
            "<tr></tr>", "", "Titel", "Hinweis", zeige_empfehlung_spalte=True)
        assert 'data-i18n="th.recommendation"' in html


class TestRenderHtmlIntegration:
    _TECHNIKER = {"T1": {"standort": "Hamburg", "lat": 53.5, "lon": 10.0}}

    def test_echtdaten_modus_embedded_empfehlung_data(self):
        empfehlungen = {
            "SMAX-0001": {
                "klinik": "Klinikum Test", "geraet": "MC-FT10",
                "empfehlungen": [{
                    "techniker_id": "Marc L.", "score": 91.2, "kompetenz_score": 100.0,
                    "fahrzeit_score": 95.0, "auslastung_score": 70.0, "distanz_km": 12,
                }],
            }
        }
        html = dash.render_html(
            ampeln=[], stk_rows=[], ct_top5=[], techniker=self._TECHNIKER,
            nrw_warnung=None, erstellt_am=datetime.datetime(2026, 9, 10),
            is_echtdaten=True, empfehlungen_echtdaten=empfehlungen,
        )
        assert "var EMPFEHLUNG_DATA" in html
        assert "SMAX-0001" in html
        assert "Marc L." in html
        assert "function showEmpfehlung" in html

    def test_demo_modus_hat_keine_empfehlung_buttons(self):
        html = dash.render_html(
            ampeln=[], stk_rows=[], ct_top5=[], techniker=self._TECHNIKER,
            nrw_warnung=None, erstellt_am=datetime.datetime(2026, 9, 10),
            is_echtdaten=False,
        )
        assert "showEmpfehlung(" not in html.replace("function showEmpfehlung", "")


class TestRealDatensatzRegression:
    """Regressionstest gegen den tatsaechlichen committeten SMax-Datensatz:
    fuer einen bekannten Fall (MC-FT10, PLZ 42283) muss der Sieger-Techniker
    stabil bleiben, solange sich die zugrundeliegenden Rohdaten nicht
    aendern."""

    def test_bekannter_fall_hat_stabilen_sieger(self):
        cache = _ROOT / "data" / "smax_dashboard_data.json"
        if not cache.exists():
            pytest.skip("data/smax_dashboard_data.json nicht vorhanden")
        d = json.loads(cache.read_text(encoding="utf-8"))
        if "qualifizierte_model_codes" not in (d.get("techniker") or [{}])[0]:
            pytest.skip("Cache-Datei noch ohne die fuer Schritt 3 benoetigten Felder")

        ergebnis = berechne_empfehlung_echtdaten("MC-FT10", "42283", d["techniker"])
        assert ergebnis, "erwartet mindestens einen qualifizierten Techniker fuer MC-FT10"
        assert ergebnis[0].techniker_id == "Michael G."
        # Score-Werte muessen sich sinnvoll unterscheiden (nicht alle gleich)
        if len(ergebnis) > 1:
            assert len({round(e.score, 1) for e in ergebnis}) > 1

    def test_verschiedene_auftraege_liefern_unterschiedliche_empfehlungen(self):
        """Plausibilitaetscheck: die Empfehlung ist tatsaechlich
        auftragsabhaengig (unterschiedliche Model Codes/Standorte fuehren zu
        unterschiedlichen Ranglisten), nicht ueberall derselbe Techniker."""
        cache = _ROOT / "data" / "smax_dashboard_data.json"
        if not cache.exists():
            pytest.skip("data/smax_dashboard_data.json nicht vorhanden")
        d = json.loads(cache.read_text(encoding="utf-8"))
        if "qualifizierte_model_codes" not in (d.get("techniker") or [{}])[0]:
            pytest.skip("Cache-Datei noch ohne die fuer Schritt 3 benoetigten Felder")

        offen = d["offene_auftraege"]
        techniker = d["techniker"]
        sieger = set()
        geprueft = 0
        for o in offen:
            if not o.get("plz"):
                continue
            ergebnis = berechne_empfehlung_echtdaten(o["model_code"], o["plz"], techniker)
            if ergebnis:
                sieger.add(ergebnis[0].techniker_id)
                geprueft += 1
            if geprueft >= 30:
                break
        assert len(sieger) > 1, "erwartet unterschiedliche Sieger-Techniker je nach Auftrag"
