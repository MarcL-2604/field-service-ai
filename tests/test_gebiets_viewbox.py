"""Tests fuer die dynamische Gebietskarten-viewBox (reporting/dashboard.py).

Die vormals feste viewBox '0 0 480 580' deckte die tatsaechliche Nord-Sued-
Ausdehnung Deutschlands nicht vollstaendig ab: Bayern und Baden-Wuerttemberg
ragten im Sueden ueber y=580 hinaus, die noerdlichen Schleswig-Holstein-
Inseln sogar ueber y=0 nach oben -- beides fuehrte dazu, dass die Karte in
allen 3 Unter-Reitern der Gebietsoptimierung am Rand abgeschnitten wurde
(SVG-Default overflow:hidden). _berechne_gebiets_viewbox() berechnet die
reale Bounding-Box aus denselben projizierten Koordinaten, die auch beim
Zeichnen verwendet werden.
"""

import csv

from reporting.dashboard import (
    _DATA_DIR,
    _berechne_gebiets_viewbox,
    _project_mercator,
    _render_gebietsoptimierung,
    _render_gebietsplanung,
    _topo_to_svg_paths,
    _XY_PAIR_RE,
)


def _lade_demo_techniker() -> dict[str, dict]:
    result = {}
    with open(_DATA_DIR / "techniker.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            result[row["techniker_id"]] = {
                "standort": row["standort"],
                "bundesland": row["bundesland"],
                "lat": float(row.get("lat", 0) or 0),
                "lon": float(row.get("lon", 0) or 0),
            }
    return result


class TestBerechneGebietsViewbox:
    def setup_method(self):
        self.techniker = _lade_demo_techniker()
        self.vb_x, self.vb_y, self.vb_w, self.vb_h = _berechne_gebiets_viewbox(self.techniker)

    def test_gibt_viertupel_aus_zahlen_zurueck(self):
        assert isinstance(self.vb_x, float)
        assert isinstance(self.vb_y, float)
        assert self.vb_w > 0
        assert self.vb_h > 0

    def test_umschliesst_alle_bundesland_koordinaten_vollstaendig(self):
        """Regressionsschutz fuer den gemeldeten Bug: Bayern/Baden-Wuerttemberg
        im Sueden und Schleswig-Holstein im Norden duerfen nicht ausserhalb
        der berechneten viewBox liegen."""
        for p in _topo_to_svg_paths():
            for x_str, y_str in _XY_PAIR_RE.findall(p["d"]):
                x, y = float(x_str), float(y_str)
                assert self.vb_x <= x <= self.vb_x + self.vb_w, (
                    f"{p['name']}: x={x} ausserhalb viewBox [{self.vb_x}, {self.vb_x + self.vb_w}]"
                )
                assert self.vb_y <= y <= self.vb_y + self.vb_h, (
                    f"{p['name']}: y={y} ausserhalb viewBox [{self.vb_y}, {self.vb_y + self.vb_h}]"
                )

    def test_bayern_suedlichster_punkt_liegt_innerhalb(self):
        """Der urspruengliche Bug: Bayern ragte ueber die alte feste
        Boxhoehe (580) hinaus."""
        bayern = next(p for p in _topo_to_svg_paths() if p["name"] == "Bayern")
        max_y = max(float(y) for _, y in _XY_PAIR_RE.findall(bayern["d"]))
        assert max_y > 580, "Testdaten-Annahme verletzt: Bayern sollte ueber y=580 hinausragen"
        assert max_y <= self.vb_y + self.vb_h

    def test_schleswig_holstein_noerdlichster_punkt_liegt_innerhalb(self):
        """Der urspruengliche Bug: die noerdlichen Inseln ragten ueber
        y=0 nach oben hinaus (negative y-Koordinaten)."""
        sh = next(p for p in _topo_to_svg_paths() if p["name"] == "Schleswig-Holstein")
        min_y = min(float(y) for _, y in _XY_PAIR_RE.findall(sh["d"]))
        assert min_y < 0, "Testdaten-Annahme verletzt: Schleswig-Holstein sollte ueber y=0 hinausragen"
        assert min_y >= self.vb_y

    def test_alte_feste_480x580_box_haette_bayern_abgeschnitten(self):
        """Dokumentiert den urspruenglichen Bug als Kontrollwert."""
        bayern = next(p for p in _topo_to_svg_paths() if p["name"] == "Bayern")
        max_y = max(float(y) for _, y in _XY_PAIR_RE.findall(bayern["d"]))
        assert max_y > 580

    def test_techniker_marker_liegen_innerhalb_der_viewbox(self):
        for tid, td in self.techniker.items():
            if not td.get("lat"):
                continue
            px, py = _project_mercator(td["lon"], td["lat"])
            assert self.vb_x <= px <= self.vb_x + self.vb_w, tid
            assert self.vb_y <= py <= self.vb_y + self.vb_h, tid

    def test_ohne_techniker_bleibt_die_box_gueltig(self):
        """Ohne Techniker-Marker tragen weiterhin die Bundeslaender-Pfade
        und Einstellungsempfehlungen zur Box bei (kein Leerfall)."""
        vb_x, vb_y, vb_w, vb_h = _berechne_gebiets_viewbox({})
        assert vb_w > 0
        assert vb_h > 0

    def test_margin_vergroessert_die_box(self):
        eng = _berechne_gebiets_viewbox(self.techniker, margin=1.0)
        weit = _berechne_gebiets_viewbox(self.techniker, margin=50.0)
        assert weit[2] > eng[2]
        assert weit[3] > eng[3]


class TestViewboxInGerendertemHtml:
    def setup_method(self):
        self.techniker = _lade_demo_techniker()
        self.viewbox = "%s %s %s %s" % _berechne_gebiets_viewbox(self.techniker)

    def test_gebietsoptimierung_svg_enthaelt_berechnete_viewbox(self):
        html = _render_gebietsoptimierung(
            [{"id": "T1", "standort": "Test", "kliniken": 1, "avg_fahrzeit": 1,
              "max_fahrzeit": 1, "fahrtstunden_jahr": 1, "onsite_stunden": 1, "ratio": 1.0}],
            [{"id": "T1", "standort": "Test", "kliniken": 1, "avg_fahrzeit": 1,
              "max_fahrzeit": 1, "fahrtstunden_jahr": 1, "onsite_stunden": 1, "ratio": 1.0,
              "verschoben": 0, "verschoben_gewonnen": 0, "verschoben_abgegeben": 0}],
            self.techniker,
            viewbox=self.viewbox, opt_height=613,
        )
        assert f'viewBox="{self.viewbox}"' in html
        assert 'height="613"' in html

    def test_gebietsplanung_svg_enthaelt_uebergebene_viewbox(self):
        html = _render_gebietsplanung(
            [{"id": "T1", "standort": "Test", "kliniken": 1, "avg_fahrzeit": 1,
              "max_fahrzeit": 1, "fahrtstunden_jahr": 1, "onsite_stunden": 1, "ratio": 1.0}],
            [], [], viewbox=self.viewbox,
        )
        assert f'viewBox="{self.viewbox}"' in html

    def test_default_viewbox_ist_die_alte_480x580_box(self):
        html = _render_gebietsplanung(
            [{"id": "T1", "standort": "Test", "kliniken": 1, "avg_fahrzeit": 1,
              "max_fahrzeit": 1, "fahrtstunden_jahr": 1, "onsite_stunden": 1, "ratio": 1.0}],
            [], [],
        )
        assert 'viewBox="0 0 480 580"' in html
