"""Tests fuer Crosstraining-Wirtschaftlichkeits-Schwellwerte.

Prueft:
  - config.py: MIN_GERAETE_FUER_CROSSTRAINING / MIN_STK_POTENZIAL_CROSSTRAINING
  - crosstraining_analyse.py: load_geraete_anzahl() + generierte CSV-Felder
  - dashboard.py: _avg_einsatzdauer_stunden() + _render_ct_ausschluss_hint()
"""

import csv

import pytest

from config import MIN_GERAETE_FUER_CROSSTRAINING, MIN_STK_POTENZIAL_CROSSTRAINING
from reporting.crosstraining_analyse import (
    BASE,
    load_geraete,
    load_geraete_anzahl,
    load_klinik_bl_map,
)


# ===================================================================
# Schwellwert-Konstanten
# ===================================================================

class TestSchwellwertKonstanten:
    def test_min_geraete_default(self):
        assert MIN_GERAETE_FUER_CROSSTRAINING == 5

    def test_min_stk_potenzial_default(self):
        assert MIN_STK_POTENZIAL_CROSSTRAINING == 15

    def test_beide_positiv(self):
        assert MIN_GERAETE_FUER_CROSSTRAINING > 0
        assert MIN_STK_POTENZIAL_CROSSTRAINING > 0


# ===================================================================
# load_geraete_anzahl()
# ===================================================================

class TestLoadGeraeteAnzahl:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.klinik_bl_map = load_klinik_bl_map()
        self.bl_anzahl = load_geraete_anzahl(self.klinik_bl_map)

    def test_gibt_nichtleeres_dict_zurueck(self):
        assert isinstance(self.bl_anzahl, dict)
        assert self.bl_anzahl

    def test_werte_sind_positive_ints(self):
        for familien in self.bl_anzahl.values():
            for anzahl in familien.values():
                assert isinstance(anzahl, int)
                assert anzahl > 0

    def test_rohe_anzahl_ist_mindestens_stk_pro_jahr_volumen(self):
        """load_geraete_anzahl() summiert die rohe Geraeteanzahl (nicht Anzahl/Zyklus)."""
        bl_volumen = load_geraete(self.klinik_bl_map)
        for bl, familien in bl_volumen.items():
            for familie, volumen in familien.items():
                anzahl = self.bl_anzahl.get(bl, {}).get(familie, 0)
                assert anzahl >= volumen


# ===================================================================
# crosstraining_empfehlungen.csv: neue Felder
# ===================================================================

class TestCrosstrainingEmpfehlungenCsv:
    @pytest.fixture(autouse=True)
    def setup(self):
        pfad = BASE / "crosstraining_empfehlungen.csv"
        with open(pfad, newline="", encoding="utf-8") as f:
            self.rows = list(csv.DictReader(f))

    def test_csv_nicht_leer(self):
        assert self.rows

    def test_neue_felder_vorhanden(self):
        for feld in (
            "top_familie",
            "top_familie_geraete_anzahl",
            "top_familie_stk_potenzial",
            "wirtschaftlich_sinnvoll",
        ):
            assert feld in self.rows[0]

    def test_wirtschaftlich_sinnvoll_ist_ja_oder_nein(self):
        for row in self.rows:
            assert row["wirtschaftlich_sinnvoll"] in ("Ja", "Nein")

    def test_wirtschaftlich_ja_erfuellt_beide_schwellwerte(self):
        for row in self.rows:
            if row["wirtschaftlich_sinnvoll"] == "Ja":
                assert int(row["top_familie_geraete_anzahl"]) >= MIN_GERAETE_FUER_CROSSTRAINING
                assert float(row["top_familie_stk_potenzial"]) >= MIN_STK_POTENZIAL_CROSSTRAINING

    def test_wirtschaftlich_nein_verletzt_mindestens_einen_schwellwert(self):
        for row in self.rows:
            if row["wirtschaftlich_sinnvoll"] == "Nein" and row["top_familie"]:
                geraete = int(row["top_familie_geraete_anzahl"])
                stk = float(row["top_familie_stk_potenzial"])
                unterschritten = (
                    geraete < MIN_GERAETE_FUER_CROSSTRAINING
                    or stk < MIN_STK_POTENZIAL_CROSSTRAINING
                )
                assert unterschritten

    def test_ohne_luecken_nicht_wirtschaftlich(self):
        """Kein top_familie (keine Luecken) -> kann nicht wirtschaftlich sein."""
        for row in self.rows:
            if not row["top_familie"]:
                assert row["wirtschaftlich_sinnvoll"] == "Nein"


# ===================================================================
# dashboard.py: _avg_einsatzdauer_stunden() + _render_ct_ausschluss_hint()
# ===================================================================

class TestAvgEinsatzdauerStunden:
    @pytest.fixture(autouse=True)
    def setup(self):
        from reporting.dashboard import _avg_einsatzdauer_stunden, _DEFAULT_EINSATZDAUER_STUNDEN
        self.func = _avg_einsatzdauer_stunden
        self.default = _DEFAULT_EINSATZDAUER_STUNDEN

    def test_leere_liste_gibt_default_zurueck(self):
        assert self.func([], "Beatmung") == self.default

    def test_berechnet_durchschnitt_fuer_passende_familie(self):
        labor_zeiten = [
            {"produkt_familie": "Beatmung", "service_zeit_min": "90", "admin_zeit_min": "30"},
            {"produkt_familie": "Beatmung", "service_zeit_min": "150", "admin_zeit_min": "30"},
        ]
        # (120 + 180) / 2 = 150 min = 2.5h
        assert self.func(labor_zeiten, "Beatmung") == pytest.approx(2.5)

    def test_faellt_auf_gesamtdurchschnitt_zurueck_wenn_familie_fehlt(self):
        labor_zeiten = [
            {"produkt_familie": "Hugo", "service_zeit_min": "180", "admin_zeit_min": "60"},
        ]
        # keine "Elektrochirurgie"-Eintraege -> Fallback auf Gesamtdurchschnitt (240min = 4h)
        assert self.func(labor_zeiten, "Elektrochirurgie") == pytest.approx(4.0)


class TestCtAusschlussHint:
    @pytest.fixture(autouse=True)
    def setup(self):
        from reporting.dashboard import _render_ct_ausschluss_hint
        self.func = _render_ct_ausschluss_hint

    def test_leer_wenn_alle_wirtschaftlich(self):
        rows = [{"techniker_id": "T1", "wirtschaftlich_sinnvoll": "Ja"}]
        assert self.func(rows) == ""

    def test_zeigt_anzahl_und_ids_bei_ausschluss(self):
        rows = [
            {"techniker_id": "T1", "wirtschaftlich_sinnvoll": "Ja"},
            {"techniker_id": "T2", "wirtschaftlich_sinnvoll": "Nein"},
            {"techniker_id": "T3", "wirtschaftlich_sinnvoll": "Nein"},
        ]
        html = self.func(rows)
        assert "2 von 3 Techniker" in html
        assert "T2" in html and "T3" in html
        assert "Ger&auml;tedichte zu gering" in html
