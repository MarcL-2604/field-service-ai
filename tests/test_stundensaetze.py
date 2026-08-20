"""Tests fuer Techniker-/Kunden-Stundensatz (config.py) und deren Verwendung
im Business-Case-Tab (Tab 5) und Cross-Training-Tab (Tab 3).

Ersetzt die bisherigen "T&E anfragen"-Platzhalter durch konkrete Euro-
Betraege auf Basis von TECHNIKER_KOSTENSATZ_EUR_STUNDE -- ausdruecklich als
Schaetzwert/Startwert gekennzeichnet (siehe config.py-Kommentar und
Herleitungs-Tooltip im Dashboard), keine von Medtronic T&E bestaetigte
Ist-Zahl.
"""

import html
import inspect
import re

import config
from reporting.dashboard import (
    LABEL_MAP_EN,
    _kostensatz_info_tip,
    _render_business_case,
    _render_ct_tabelle,
)


class TestConfigKonstanten:
    def test_techniker_kostensatz_vorhanden(self):
        assert config.TECHNIKER_KOSTENSATZ_EUR_STUNDE == 45.0

    def test_kunden_verrechnungssatz_vorhanden(self):
        assert config.KUNDEN_VERRECHNUNGSSATZ_EUR_STUNDE == 150.0

    def test_beide_saetze_sind_als_schaetzwert_gekennzeichnet(self):
        """Regressionsschutz: die Herleitung/Schaetzwert-Kennzeichnung muss
        im Quelltext-Kommentar unmittelbar bei den Konstanten stehen, nicht
        nur irgendwo im Dashboard-Code."""
        quelle = inspect.getsource(config)
        block = quelle[quelle.index("TECHNIKER_KOSTENSATZ_EUR_STUNDE"):]
        block = block[:block.index("Trainingskosten")]
        assert "Schaetzung" in block or "Schätzung" in block
        assert "KUNDEN_VERRECHNUNGSSATZ_EUR_STUNDE" in block


class TestKostensatzInfoTip:
    def test_liefert_info_tip_mit_herleitung(self):
        out = _kostensatz_info_tip()
        assert 'class="info-tip"' in out
        assert 'data-label-de="Herleitung' in out


class TestRenderBusinessCaseOhneTEPlatzhalter:
    def test_kein_te_anfragen_mehr_im_output(self):
        html_out = _render_business_case(stk_potenzial_gesamt=0, median_min=0)
        assert "T&E anfragen" not in html_out
        assert "T&amp;E anfragen" not in html_out

    def test_monetaerer_wert_zeigt_berechneten_betrag(self):
        html_out = _render_business_case(stk_potenzial_gesamt=0, median_min=0)
        erwartet = round(4992 * config.TECHNIKER_KOSTENSATZ_EUR_STUNDE)
        erwartet_fmt = f"{erwartet:,}".replace(",", ".")
        assert erwartet_fmt in html_out
        assert erwartet_fmt == "224.640"

    def test_stundensatz_zahl_erscheint_im_output(self):
        html_out = _render_business_case(stk_potenzial_gesamt=0, median_min=0)
        kostensatz_fmt = f"{config.TECHNIKER_KOSTENSATZ_EUR_STUNDE:.0f}"
        assert f"{kostensatz_fmt}&thinsp;&euro;/h" in html_out

    def test_startwert_kennzeichnung_vorhanden(self):
        html_out = _render_business_case(stk_potenzial_gesamt=0, median_min=0)
        assert "Startwert, anpassbar" in html_out or "data-label-de=\"Startwert" in html_out

    def test_crosstraining_roi_ohne_echtdaten_zeigt_konkreten_satz(self):
        html_out = _render_business_case(stk_potenzial_gesamt=0, median_min=0)
        assert "interne Kapazitätsersparnis" in html_out or "data-label-de=\"interne Kapazitätsersparnis" in html_out

    def test_crosstraining_roi_mit_echtdaten_berechnet_euro_wert(self):
        html_out = _render_business_case(stk_potenzial_gesamt=1234, median_min=90)
        erwartet = round(1234 * (90 / 60) * config.TECHNIKER_KOSTENSATZ_EUR_STUNDE)
        erwartet_fmt = f"{erwartet:,}".replace(",", ".")
        assert erwartet_fmt in html_out
        assert erwartet_fmt == "83.295"

    def test_zeitersparnis_formel_unveraendert(self):
        """Die Herleitung der 4.992h/Jahr aendert sich nicht -- nur die
        monetaere Umrechnung war der T&E-Platzhalter."""
        html_out = _render_business_case(stk_potenzial_gesamt=0, median_min=0)
        assert "4.992 h" in html_out


class TestBusinessCaseI18n:
    def _alle_data_label_de_werte(self, html_out: str) -> set[str]:
        return set(html.unescape(m) for m in re.findall(r'data-label-de="([^"]*)"', html_out))

    def test_alle_label_werte_haben_uebersetzung(self):
        html_out = _render_business_case(stk_potenzial_gesamt=1234, median_min=90)
        werte = self._alle_data_label_de_werte(html_out)
        assert werte
        fehlend = [w for w in werte if w not in LABEL_MAP_EN]
        assert not fehlend, f"data-label-de-Werte ohne LABEL_MAP_EN-Eintrag: {fehlend}"

    def test_alle_label_werte_ohne_echtdaten_haben_uebersetzung(self):
        html_out = _render_business_case(stk_potenzial_gesamt=0, median_min=0)
        werte = self._alle_data_label_de_werte(html_out)
        fehlend = [w for w in werte if w not in LABEL_MAP_EN]
        assert not fehlend, f"data-label-de-Werte ohne LABEL_MAP_EN-Eintrag: {fehlend}"

    def test_kein_data_label_de_wert_enthaelt_html_tags(self):
        html_out = _render_business_case(stk_potenzial_gesamt=1234, median_min=90)
        assert not re.search(r'data-label-de="[^"]*[<>][^"]*"', html_out)


class TestCrosstrainingEuroAequivalent:
    _TECHNIKER = {"T1": {"standort": "Testort"}}

    _CT_ROW = {
        "techniker_id": "T1",
        "anzahl_luecken": "1",
        "fehlende_familien": "Beatmung",
        "top_familie": "Beatmung",
        "top_familie_stk_potenzial": "250",
        "idealer_crosstraining_partner": "T2",
        "top_schulung_typ": "EXTERN",
        "top_schulung_kosten": "1.500 €",
        "top_schulung_dauer": "3 Tage",
        "qualifizierte_familien_l3plus": "Energie;Capnografie",
        "regionale_produktfamilien": "Energie;Capnografie;Beatmung",
    }

    _LABOR_ZEITEN = [
        {"produkt_familie": "Beatmung", "service_zeit_min": "100", "admin_zeit_min": "20"},
    ]

    def test_euro_wert_wird_korrekt_berechnet(self):
        html_out = _render_ct_tabelle([self._CT_ROW], self._TECHNIKER, self._LABOR_ZEITEN)
        # avg_h = 120/60 = 2.0h, zusatz_stunden = 250 * 2.0 = 500.0
        # eur = round(500.0 * 45.0) = 22500
        assert "22.500" in html_out

    def test_kein_te_anfragen_im_mehrwert_block(self):
        html_out = _render_ct_tabelle([self._CT_ROW], self._TECHNIKER, self._LABOR_ZEITEN)
        assert "T&E anfragen" not in html_out

    def test_startwert_kennzeichnung_im_mehrwert_block(self):
        html_out = _render_ct_tabelle([self._CT_ROW], self._TECHNIKER, self._LABOR_ZEITEN)
        assert 'data-label-de="Startwert, anpassbar"' in html_out

    def test_alle_label_werte_haben_uebersetzung(self):
        # "T&E anfragen *" kommt aus _CLUSTER_MAP (Schulungskosten-Badge) --
        # ein vorbestehender, bewusst nicht in diesem Scope behobener i18n-
        # Gap (externe Trainingskosten, nicht Techniker-Stundensatz).
        bekannte_luecken = {"T&E anfragen *"}
        html_out = _render_ct_tabelle([self._CT_ROW], self._TECHNIKER, self._LABOR_ZEITEN)
        werte = set(html.unescape(m) for m in re.findall(r'data-label-de="([^"]*)"', html_out))
        assert werte
        fehlend = [w for w in werte if w not in LABEL_MAP_EN and w not in bekannte_luecken]
        assert not fehlend, f"data-label-de-Werte ohne LABEL_MAP_EN-Eintrag: {fehlend}"

    def test_ohne_stk_potenzial_kein_mehrwert_block(self):
        row = {**self._CT_ROW, "top_familie_stk_potenzial": "0"}
        html_out = _render_ct_tabelle([row], self._TECHNIKER, self._LABOR_ZEITEN)
        assert "ct-mehrwert" not in html_out
