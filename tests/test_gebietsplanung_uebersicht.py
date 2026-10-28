"""Tests fuer die uebersichtliche Gebietsplanung und den Crosstraining-Einblick.

Prinzip: Ebene 1 eine Aussage, Ebene 2 Tabelle, Ebene 3 Details auf Klick.
Geprueft werden Begruendungstexte (DE+EN), Detailbereich, Verschiebungsliste,
Hinweisband, Luecken-Status und die Crosstraining-Karten ohne Summen.
"""

import html
import json
import re

import pytest

import reporting.dashboard as dash
from reporting.dashboard import (
    LABEL_MAP_EN,
    _berechne_gebietsmetriken,
    _build_gebiets_script,
    _render_ct_einblick,
    _render_gebietsoptimierung,
)
from reporting.erklaerungen import gebiets_begruendung, generiere_erklaerung, korridor_status
from tests.test_plz_uebersicht import _lade_demo_techniker


@pytest.fixture(scope="module")
def daten():
    techniker = _lade_demo_techniker()
    akt, opt, _, _, status = _berechne_gebietsmetriken(techniker)
    return techniker, akt, opt, status


@pytest.fixture(scope="module")
def gebiets_html(daten):
    techniker, akt, opt, status = daten
    return _render_gebietsoptimierung(akt, opt, techniker, gebiete_status=status)


def _view(page: str, name: str) -> str:
    teile = page.split(f'id="go-view-{name}"')[1]
    return re.split(r'<div class="go-view-content|<details class="go-weitere"', teile)[0]


class TestBegruendungDeEn:
    def test_alle_techniker_mit_kliniken_haben_begruendung_in_beiden_sprachen(self, daten):
        techniker, akt, _, _ = daten
        geprueft = 0
        for m in akt:
            if not m["kliniken"]:
                continue
            de = gebiets_begruendung(m["id"], techniker, akt, "de")
            en = gebiets_begruendung(m["id"], techniker, akt, "en")
            assert set(de) == set(en) == {"regel", "kennzahlen", "alternative", "plz", "einschraenkung"}
            assert all(de.values()) and all(en.values())
            assert "Kliniken" in de["kennzahlen"] and "clinics" in en["kennzahlen"]
            assert "Kliniken" not in en["kennzahlen"]
            geprueft += 1
        assert geprueft > 0

    def test_erklaerfeld_nutzt_denselben_text_wie_detailbereich(self, daten):
        techniker, akt, opt, _ = daten
        tid = next(m["id"] for m in akt if m["kliniken"])
        for sprache in ("de", "en"):
            abschnitte = gebiets_begruendung(tid, techniker, akt, sprache)
            chat = generiere_erklaerung(
                "warum_gebiet", tid, techniker=techniker, metriken_akt=akt,
                metriken_opt=opt, sprache=sprache)
            for text in abschnitte.values():
                assert text.rstrip(".") in chat

    def test_gebietsheuristik_nennt_scoring_gewichte_nicht(self, daten):
        techniker, akt, _, _ = daten
        tid = next(m["id"] for m in akt if m["kliniken"])
        for sprache in ("de", "en"):
            text = " ".join(gebiets_begruendung(tid, techniker, akt, sprache).values())
            assert "40" not in text and "35" not in text

    def test_zeilen_begruendung_ist_gefuellt_und_uebersetzbar(self, gebiets_html):
        zeilen = re.findall(r'<td colspan="5" class="go-begruendung">(.*?)</td>', gebiets_html)
        assert zeilen
        for z in zeilen:
            assert "<span data-label-de=" in z
        labels = {html.unescape(x) for x in re.findall(r'data-label-de="([^"]*)"', gebiets_html)}
        assert not [x for x in labels if x not in LABEL_MAP_EN and x != "Optimal"]

    def test_korridor_status(self):
        assert korridor_status(70) == ("unter", 10)
        assert korridor_status(85) == ("im_korridor", 0)
        assert korridor_status(99) == ("ueber", 4)


class TestDetailbereich:
    def test_detailbereich_hat_fuenf_feste_abschnitte(self, gebiets_html):
        assert 'id="go-detail"' in gebiets_html
        for sec in ("regel", "kennzahlen", "alternative", "plz", "einschraenkung"):
            assert f'data-sec="{sec}"' in gebiets_html

    def test_klick_oeffnet_detail_json_und_handler(self, daten):
        techniker, akt, _, _ = daten
        detail = {
            m["id"]: {sp: gebiets_begruendung(m["id"], techniker, akt, sp) for sp in ("de", "en")}
            for m in akt if m["kliniken"]
        }
        js = _build_gebiets_script(techniker, [], [{"x": 1, "y": 1, "akt": "T1", "opt": "T1"}], detail)
        assert "function showDetail(" in js
        assert "showDetail(tid);" in js                      # selectTech oeffnet den Bereich
        assert "'#germany-map-opt .td, #germany-map-opt .tl'" in js   # Kartenmarker klickbar
        eingebettet = re.search(r"var DETAIL=(\{.*?\});\n", js, re.S).group(1)
        assert set(json.loads(eingebettet)) == set(detail)

    def test_kartenmarker_tragen_data_tech(self, daten):
        techniker, _, _, status = daten
        svg = dash._build_gebiets_svg(techniker, [], gebiete_status=status)
        assert re.search(r'<circle class="td" data-tech="[^"]+"', svg)


class TestHinweisbandUndAussage:
    def test_hinweisband_auf_allen_drei_ansichten(self, gebiets_html):
        assert gebiets_html.count('class="go-szenario-band"') == 3
        for name in ("aktuell", "optimiert", "luecken"):
            assert 'class="go-szenario-band"' in _view(gebiets_html, name)

    def test_gesamtaussage_je_ansicht(self, gebiets_html):
        for name in ("aktuell", "optimiert", "luecken"):
            assert _view(gebiets_html, name).count('class="go-headline"') == 1

    def test_details_standardmaessig_zu(self, gebiets_html):
        assert '<details class="go-weitere" id="go-weitere">' in gebiets_html
        for pflicht in ("go.sec.ratio", "go.sec.plz", "go.sec.legende", "hugo-kg-toggle"):
            assert pflicht in gebiets_html.split('id="go-weitere"')[1]


class TestVerschiebungen:
    def test_liste_summiert_zu_verschobenen_kliniken(self, daten, gebiets_html):
        _, _, opt, _ = daten
        liste = [v for m in opt for v in m.get("abgaben", [])]
        gewonnen = sum(m["verschoben_gewonnen"] for m in opt)
        abgegeben = sum(m["verschoben_abgegeben"] for m in opt)
        assert sum(v["anzahl"] for v in liste) == gewonnen == abgegeben
        assert gewonnen > 0
        # Gesamtaussage nennt dieselbe Zahl
        kopf = re.search(r'<p class="go-headline">(\d+) ', _view(gebiets_html, "optimiert"))
        assert int(kopf.group(1)) == gewonnen

    def test_sortiert_nach_anzahl_und_mit_grund(self, daten):
        _, _, opt, _ = daten
        liste = sorted((v for m in opt for v in m["abgaben"]), key=lambda v: -v["anzahl"])
        for v in liste:
            assert {"von", "nach", "anzahl", "mehrfahrt_min", "auslastung_von", "auslastung_nach"} <= set(v)
            assert v["von"] != v["nach"]

    def test_zeilen_in_html_in_absteigender_reihenfolge(self, gebiets_html):
        tabelle = _view(gebiets_html, "optimiert").split("go-versch-tabelle")[1].split("</table>")[0]
        zahlen = [int(z) for z in re.findall(r'<td>(\d+)</td></tr><tr class="go-begr-row"', tabelle)]
        assert zahlen == sorted(zahlen, reverse=True) and zahlen


class TestLueckenStatus:
    def test_keine_daten_nicht_berechenbar_und_keine_luecke_getrennt(self, daten):
        techniker, akt, opt, _ = daten
        status = {
            "Hamburg": {"typ": "not_computable", "techs": []},
            "Bayern": {"typ": "optimal", "techs": ["T1"], "fahrzeit_min": 40, "anteil_pct": 5},
            "Sachsen": {"typ": "gap", "techs": ["T1"], "naechster": "T1", "fahrzeit_min": 120, "anteil_pct": 0},
        }
        page = _render_gebietsoptimierung(akt, opt, techniker, gebiete_status=status)
        luecken = _view(page, "luecken")
        for label in ("Nicht berechenbar", "Keine Lücke", "Lücke", "Keine Daten"):
            assert f'data-label-de="{label}"' in luecken
        assert luecken.count("go-nodata") >= 2

    def test_kartenmarker_folgen_der_klassifikation(self, daten):
        techniker, _, _, _ = daten
        status = {"Bayern": {"typ": "gap", "techs": ["T1"], "naechster": "T1", "fahrzeit_min": 99}}
        svg = dash._build_gebiets_svg(techniker, [], gebiete_status=status)
        assert 'data-name="Bayern" data-fill-aktuell' in svg
        assert 'data-overlap="gap"' in svg
        assert 'data-overlap="1"' not in svg


class TestCrosstrainingEinblick:
    ROWS = [
        {"techniker_id": f"T{i}", "top_familie": "Beatmung", "top_familie_geraete_anzahl": str(20 + i),
         "top_familie_stk_potenzial": str(100 - 10 * i), "wirtschaftlich_sinnvoll": "Ja",
         "fehlende_familien": "Beatmung;Endoskopie", "top_schulung_dauer": "2 Tage + 4 begleitete Einsaetze"}
        for i in range(1, 6)
    ]
    TECH = {f"T{i}": {"standort": "Ort"} for i in range(1, 6)}

    def test_drei_karten_und_alle_empfehlungen_als_details(self):
        out = _render_ct_einblick(self.ROWS, self.TECH, [])
        assert out.count('class="ct-karte"') == 3
        assert '<details class="ct-alle">' in out and 'data-i18n="ct.alle"' in out
        assert out.count("<tr><td><strong>") == 5
        assert "ct-weitere" in out                       # weitere Familien nur auf Klick

    def test_keine_summen_und_keine_euro_betraege(self):
        out = _render_ct_einblick(self.ROWS, self.TECH, [])
        assert "€" not in out and "&euro;" not in out and "EUR" not in out
        assert "gesamt" not in out.lower() and "summe" not in out.lower()

    def test_tab_ohne_nrw_summenwarnung_und_mit_potenzial_hinweis(self):
        quelle = open(dash.__file__, encoding="utf-8").read()
        tab = quelle.split('<div id="tab-crosstraining"')[1].split("<!-- Tab 4")[0]
        assert "{warnung_html}" not in tab
        assert "nicht\n      aufsummierbar" in tab or "nicht aufsummierbar" in tab

    def test_te_hinweis_einmal_erklaert(self):
        out = _render_ct_einblick(self.ROWS[:1] + [{**self.ROWS[1], "top_schulung_dauer": ""}], self.TECH, [])
        assert out.count('class="ct-fussnote"') == 1          # einmal statt je Kachel

    def test_beschriftungen_sind_uebersetzbar(self):
        out = _render_ct_einblick(self.ROWS, self.TECH, []) + dash._render_ct_wozu()
        labels = {html.unescape(x) for x in re.findall(r'data-label-de="([^"]*)"', out)}
        assert labels
        assert not [x for x in labels if x not in LABEL_MAP_EN]

    def test_wozu_nennt_kriterien_aus_config(self):
        wozu = dash._render_ct_wozu()
        assert f" {dash.MIN_GERAETE_FUER_CROSSTRAINING} " in wozu
        assert f" {dash.MIN_STK_POTENZIAL_CROSSTRAINING} " in wozu
        assert "Hugo, O-arm und CAS" in wozu
