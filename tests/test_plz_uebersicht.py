"""Tests fuer die PLZ-Bereichsuebersicht je Techniker (Gebietsoptimierung-Tab).

Ziel: in der Gebietsoptimierung-Tabelle ("Aktuelle Gebiete" / "Optimierte
Gebiete") soll pro Techniker erkennbar sein, welche PLZ-Bereiche ihm
zugeordnet sind -- als kompakter Von-Bis-Bereich, wenn die PLZ-Praefixe
lueckenlos zusammenhaengen, sonst ehrlich als Praefix-Liste mit Anzahl
(siehe reporting/dashboard.py._plz_uebersicht_je_techniker). Bei den
optimierten Gebieten wird zusaetzlich vorher/nachher gegenuebergestellt.
"""

import csv
import html
import re

import reporting.dashboard as dash
from reporting.dashboard import (
    LABEL_MAP_EN,
    _DATA_DIR,
    _berechne_gebietsmetriken,
    _plz_uebersicht_je_techniker,
    _render_gebietsoptimierung,
    _render_plz_uebersicht,
)


def _klinik(kid: str, plz: str) -> dict:
    return {"id": kid, "plz": plz, "lat": 50.0, "lon": 8.0, "name": kid, "jobs": 1}


# ===================================================================
# _plz_uebersicht_je_techniker(): reine Aggregationsfunktion
# ===================================================================

class TestPlzUebersichtZusammenhaengend:
    def test_luekenlose_praefixe_ergeben_von_bis_bereich(self):
        kliniken = [
            _klinik("K1", "72070"), _klinik("K2", "72202"),
            _klinik("K3", "73728"), _klinik("K4", "74072"),
        ]
        zuweisung = {"K1": "T1", "K2": "T1", "K3": "T1", "K4": "T1"}
        ergebnis = _plz_uebersicht_je_techniker(kliniken, zuweisung)
        assert ergebnis["T1"]["bereich"] == (72, 74)
        assert ergebnis["T1"]["anzahl"] == 4

    def test_einzelnes_praefix_ist_ebenfalls_ein_bereich(self):
        kliniken = [_klinik("K1", "72070"), _klinik("K2", "72202")]
        zuweisung = {"K1": "T1", "K2": "T1"}
        ergebnis = _plz_uebersicht_je_techniker(kliniken, zuweisung)
        assert ergebnis["T1"]["bereich"] == (72, 72)
        assert ergebnis["T1"]["anzahl"] == 2


class TestPlzUebersichtVerstreut:
    def test_luecken_verhindern_von_bis_bereich(self):
        """72 und 78 sind nicht benachbart -- kein kuenstlicher Bereich."""
        kliniken = [
            *([_klinik(f"K{i}", "72070") for i in range(18)]),
            *([_klinik(f"L{i}", "78045") for i in range(9)]),
            *([_klinik(f"M{i}", "70190") for i in range(4)]),
        ]
        zuweisung = {k["id"]: "T2" for k in kliniken}
        ergebnis = _plz_uebersicht_je_techniker(kliniken, zuweisung)
        info = ergebnis["T2"]
        assert info["bereich"] is None
        assert info["anzahl"] == 31
        # absteigend nach Anzahl sortiert
        assert info["praefixe"][0] == ("72", 18)
        assert info["praefixe"][1] == ("78", 9)
        assert info["praefixe"][2] == ("70", 4)

    def test_praefixe_mit_luecke_von_nur_einer_stelle_auch_nicht_zusammenhaengend(self):
        """72, 74 (73 fehlt) -- keine luekenlose Kette."""
        kliniken = [_klinik("K1", "72000"), _klinik("K2", "74000")]
        zuweisung = {"K1": "T3", "K2": "T3"}
        ergebnis = _plz_uebersicht_je_techniker(kliniken, zuweisung)
        assert ergebnis["T3"]["bereich"] is None


class TestPlzUebersichtEdgeCases:
    def test_techniker_ohne_kliniken_fehlt_im_ergebnis(self):
        kliniken = [_klinik("K1", "72070")]
        zuweisung = {"K1": "T1"}
        ergebnis = _plz_uebersicht_je_techniker(kliniken, zuweisung)
        assert "T9" not in ergebnis

    def test_kliniken_ohne_zuweisung_werden_ignoriert(self):
        kliniken = [_klinik("K1", "72070"), _klinik("K2", "80331")]
        zuweisung = {"K1": "T1"}  # K2 nicht zugewiesen
        ergebnis = _plz_uebersicht_je_techniker(kliniken, zuweisung)
        assert ergebnis["T1"]["anzahl"] == 1

    def test_leere_eingabe_ergibt_leeres_dict(self):
        assert _plz_uebersicht_je_techniker([], {}) == {}


# ===================================================================
# _render_plz_uebersicht(): Textdarstellung (Tooltip-Inhalt)
# ===================================================================

class TestRenderPlzUebersicht:
    def test_kein_techniker_ohne_kliniken(self):
        out = _render_plz_uebersicht(None)
        assert 'data-label-de="Keine Kliniken zugeordnet"' in out

    def test_zusammenhaengender_bereich_zeigt_von_bis(self):
        info = {"anzahl": 23, "bereich": (72, 74), "praefixe": [("72", 10), ("73", 8), ("74", 5)]}
        out = _render_plz_uebersicht(info)
        assert "72xxx" in out and "74xxx" in out
        assert "23" in out
        assert 'data-label-de="PLZ"' in out

    def test_einzelnes_praefix_zeigt_nicht_doppelt(self):
        info = {"anzahl": 5, "bereich": (72, 72), "praefixe": [("72", 5)]}
        out = _render_plz_uebersicht(info)
        assert "72xxx" in out
        assert "72xxx&ndash;72xxx" not in out

    def test_verstreute_praefixe_zeigen_liste_mit_anzahl(self):
        info = {
            "anzahl": 31, "bereich": None,
            "praefixe": [("72", 18), ("78", 9), ("70", 4)],
        }
        out = _render_plz_uebersicht(info)
        assert "72xxx (18" in out
        assert "78xxx (9" in out
        assert "70xxx (4" in out
        assert 'data-label-de="PLZ-Präfixe:"' in out

    def test_mehr_als_fuenf_praefixe_werden_zusammengefasst(self):
        info = {
            "anzahl": 12, "bereich": None,
            "praefixe": [(f"{70+i}", 2) for i in range(6)],
        }
        out = _render_plz_uebersicht(info)
        assert "1" in out and "weitere" in out
        assert 'data-label-de="weitere"' in out


# ===================================================================
# End-to-End: _berechne_gebietsmetriken() haengt plz_info an
# ===================================================================

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


class TestBerechneGebietsmetrikenPlzInfo:
    def setup_method(self):
        self.techniker = _lade_demo_techniker()
        self.akt, self.opt, _, _, _ = _berechne_gebietsmetriken(self.techniker)

    def test_jeder_eintrag_hat_plz_info_feld(self):
        for m in self.akt:
            assert "plz_info" in m
        for m in self.opt:
            assert "plz_info" in m

    def test_techniker_mit_klinken_hat_gefuellte_plz_info(self):
        mit_kliniken = [m for m in self.akt if m["kliniken"] > 0]
        assert mit_kliniken
        for m in mit_kliniken:
            assert m["plz_info"] is not None
            assert m["plz_info"]["anzahl"] == m["kliniken"]

    def test_techniker_ohne_kliniken_hat_plz_info_none(self):
        ohne_kliniken = [m for m in self.akt if m["kliniken"] == 0]
        for m in ohne_kliniken:
            assert m["plz_info"] is None


# ===================================================================
# _render_gebietsoptimierung(): PLZ-Tooltip in beiden Tabellen
# ===================================================================

class TestGebietsoptimierungRenderingMitPlz:
    def setup_method(self):
        self.techniker = _lade_demo_techniker()
        self.akt, self.opt, _, _, status = _berechne_gebietsmetriken(self.techniker)
        self.html = _render_gebietsoptimierung(self.akt, self.opt, self.techniker, gebiete_status=status)

    def test_plz_tooltip_erscheint_in_aktuelle_gebiete_ansicht(self):
        aktuell_teil = self.html.split('id="go-view-optimiert"')[0]
        assert 'class="info-tip"' in aktuell_teil

    def test_plz_tooltip_erscheint_in_optimierte_gebiete_ansicht_mit_vorher_nachher(self):
        optimiert_teil = self.html.split('id="go-view-optimiert"')[1].split('id="go-view-luecken"')[0]
        assert 'class="info-tip"' in optimiert_teil
        assert 'data-label-de="PLZ-Bereich vorher"' in optimiert_teil
        assert 'data-label-de="PLZ-Bereich nachher"' in optimiert_teil

    def test_alle_plz_bezogenen_label_werte_haben_uebersetzung(self):
        # "Optimal" ist bewusst DE/EN identisch (siehe test_i18n_label_map.py
        # TestVollstaendigeLabelAbdeckung._BEWUSST_IDENTISCH) -- unabhaengig
        # von der PLZ-Uebersicht, kommt aber ueber die Luecken-Tabelle
        # in denselben gerenderten HTML-Block.
        bewusst_identisch = {"Optimal"}
        werte = set(html.unescape(m) for m in re.findall(r'data-label-de="([^"]*)"', self.html))
        fehlend = [w for w in werte if w not in LABEL_MAP_EN and w not in bewusst_identisch]
        assert not fehlend, f"data-label-de-Werte ohne LABEL_MAP_EN-Eintrag: {fehlend}"

    def test_kein_data_label_de_wert_enthaelt_html_tags(self):
        assert not re.search(r'data-label-de="[^"]*[<>][^"]*"', self.html)
