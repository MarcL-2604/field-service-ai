"""Tests fuer die Dashboard-Integration des Auslastungs-Zielkorridors
(config.AUSLASTUNG_ZIEL_MIN_PCT/MAX_PCT, api/auslastung_analyse.py):
Badge-Rendering, Ampel-Karten- und Gebietsoptimierungs-Tabellen-Anzeige.
"""

from config import AUSLASTUNG_ZIEL_MIN_PCT, AUSLASTUNG_ZIEL_MAX_PCT
from reporting.dashboard import _render_ampel_karten, _render_gebietsoptimierung, _render_korridor_badge


class TestKorridorKonstanten:
    def test_zielkorridor_80_bis_95(self):
        assert AUSLASTUNG_ZIEL_MIN_PCT == 80
        assert AUSLASTUNG_ZIEL_MAX_PCT == 95


class TestRenderKorridorBadge:
    def test_unter_korridor(self):
        html = _render_korridor_badge("unter", 24.5)
        assert "24%" in html
        assert "korridor-unter" in html
        assert "unter Korridor" in html

    def test_im_korridor(self):
        html = _render_korridor_badge("im_korridor", 87.0)
        assert "87%" in html
        assert "korridor-im" in html
        assert "im Korridor" in html

    def test_ueber_korridor(self):
        html = _render_korridor_badge("ueber", 130.0)
        assert "130%" in html
        assert "korridor-ueber" in html

    def test_fehlende_daten_leerer_string(self):
        assert _render_korridor_badge(None, None) == ""
        assert _render_korridor_badge("unter", None) == ""
        assert _render_korridor_badge(None, 50.0) == ""

    def test_tooltip_erklaert_methodik(self):
        html = _render_korridor_badge("unter", 24.5)
        assert "Fahrzeit ist nicht enthalten" in html
        assert "keine harte Regel" in html


class TestAmpelKartenKorridorAnzeige:
    AMPELN = [
        {"techniker_id": "T1", "standort": "Hamburg", "region": "Nord",
         "ampel_css": "ampel-gelb", "ampel_label": "GELB", "qualifiziert": 10,
         "regional": 20, "abdeckung_pct": 50, "fehlend_count": 10, "zusatz_stk": 100.0},
    ]

    def test_badge_erscheint_wenn_echtdaten_vorhanden(self):
        techniker = {"T1": {"auslastung_korridor": "unter", "auslastung_pct_real": 24.5}}
        html = _render_ampel_karten(self.AMPELN, [], techniker)
        assert "korridor-badge" in html

    def test_kein_badge_ohne_echtdaten_demo_modus(self):
        """Demo-Modus liefert kein techniker-Dict mit den *_real-Feldern --
        darf nicht crashen, Badge bleibt einfach leer."""
        html = _render_ampel_karten(self.AMPELN, [], {"T1": {}})
        assert "korridor-badge" not in html

    def test_ohne_techniker_param_kein_absturz(self):
        html = _render_ampel_karten(self.AMPELN, [])
        assert isinstance(html, str)


class TestGebietsoptimierungKorridorSpalte:
    M_AKT = [{"id": "T1", "standort": "Hamburg", "kliniken": 12, "avg_fahrzeit": 45,
              "max_fahrzeit": 90, "fahrtstunden_jahr": 200, "onsite_stunden": 400, "ratio": 2.0}]
    M_OPT = [{"id": "T1", "standort": "Hamburg", "kliniken": 12, "avg_fahrzeit": 45,
              "max_fahrzeit": 90, "fahrtstunden_jahr": 200, "onsite_stunden": 400, "ratio": 2.0,
              "verschoben": 0, "verschoben_gewonnen": 0, "verschoben_abgegeben": 0}]

    def test_auslastungsspalte_im_tabellenkopf(self):
        techniker = {"T1": {"standort": "Hamburg", "lat": 53.55, "lon": 9.99}}
        html = _render_gebietsoptimierung(self.M_AKT, self.M_OPT, techniker)
        assert "Auslastung" in html

    def test_badge_in_tabellenzeile_bei_echtdaten(self):
        techniker = {"T1": {
            "standort": "Hamburg", "lat": 53.55, "lon": 9.99,
            "auslastung_korridor": "im_korridor", "auslastung_pct_real": 88.0,
        }}
        html = _render_gebietsoptimierung(self.M_AKT, self.M_OPT, techniker)
        assert "korridor-badge" in html
        assert "88%" in html

    def test_bindestrich_ohne_echtdaten(self):
        techniker = {"T1": {"standort": "Hamburg", "lat": 53.55, "lon": 9.99}}
        html = _render_gebietsoptimierung(self.M_AKT, self.M_OPT, techniker)
        assert "&ndash;</td>" in html
