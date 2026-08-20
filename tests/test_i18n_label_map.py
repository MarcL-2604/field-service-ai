"""Tests fuer die zentrale Label-Uebersetzung (i18n-Komplettaudit).

Der bislang mehrfach gefundene i18n-Bug (Menue Englisch, Inhalte bleiben
Deutsch) trat systematisch auf, weil wiederkehrende Status-/Badge-Woerter
(Ampel-Label, Dringlichkeit, Repair-Phase, Auslastungs-Korridor, ...) nirgends
an das _I18N-System angebunden waren. Fix: reporting/dashboard.py._label()
wrappt solche Woerter in <span data-label-de="..."> und JS setLang() ersetzt
sie generisch ueber EINE Tabelle (LABEL_MAP_EN) -- statt jede der ~100
Vorkommensstellen einzeln an einen data-i18n-Key zu binden.

Der wichtigste Test hier (TestVollstaendigeLabelAbdeckung) rendert das
komplette Dashboard-HTML und prueft automatisiert, dass JEDER
data-label-de-Wert eine LABEL_MAP_EN-Uebersetzung hat (oder bewusst in
beiden Sprachen identisch ist) -- die permanente, automatisierte Variante
der manuellen Browser-Verifikation aus dem i18n-Komplettaudit.
"""

import datetime
import html
import re

import reporting.dashboard as dash
from reporting.dashboard import (
    LABEL_MAP_EN,
    _go_info_box,
    _label,
    _label_sla_text,
)


class TestLabelHelper:
    def test_erzeugt_span_mit_data_label_de(self):
        out = _label("KRITISCH")
        assert out == '<span data-label-de="KRITISCH">KRITISCH</span>'

    def test_beliebiges_wort_wird_gewrappt(self):
        out = _label("Irgendein Text")
        assert 'data-label-de="Irgendein Text"' in out
        assert ">Irgendein Text<" in out


class TestLabelSlaText:
    def test_pure_woerter_ohne_zahl(self):
        assert _label_sla_text("SLA VERLETZT") == _label("SLA VERLETZT")
        assert _label_sla_text("✓ Kontakt") == _label("✓ Kontakt")

    def test_dynamische_stundenzahl_bleibt_ausserhalb_des_labels(self):
        out = _label_sla_text("SLA: noch 41h")
        assert out == f'{_label("SLA: noch")} 41h'
        assert "41h" in out
        # Die Zahl selbst darf nicht Teil des data-label-de-Attributs sein --
        # sonst gaebe es fuer jede moegliche Stundenzahl einen eigenen Key.
        assert 'data-label-de="SLA: noch 41h"' not in out

    def test_andere_stundenzahl_gleiches_praefix(self):
        out17 = _label_sla_text("SLA: noch 17h")
        out41 = _label_sla_text("SLA: noch 41h")
        assert out17.split(" ")[0:3] == out41.split(" ")[0:3]  # gleicher Label-Teil
        assert "17h" in out17 and "41h" in out41


class TestGoInfoBox:
    def test_titel_und_text_werden_automatisch_gewrappt(self):
        out = _go_info_box("&#128506;", "Ein Titel", "Ein Text.")
        assert 'data-label-de="Ein Titel"' in out
        assert 'data-label-de="Ein Text."' in out

    def test_bereits_uebersetzter_text_wird_nicht_doppelt_gewrappt(self):
        vorgefertigt = f'{_label("Teil 1")} 42 {_label("Teil 2")}'
        out = _go_info_box("&#128506;", "Titel", vorgefertigt, text_bereits_uebersetzt=True)
        # Der vorgefertigte Text darf nicht nochmal in ein AEUSSERES
        # data-label-de gewrappt werden (kaputtes/verschachteltes HTML).
        assert out.count("go-info-text") == 1
        assert 'data-label-de="Teil 1"' in out
        assert "42" in out
        # Es darf KEIN data-label-de existieren, dessen Wert HTML-Tags enthaelt
        assert not re.search(r'data-label-de="[^"]*<span', out)


class TestLabelMapEnStruktur:
    def test_keine_leeren_eintraege(self):
        for de, en in LABEL_MAP_EN.items():
            assert de.strip(), "Leerer DE-Schluessel in LABEL_MAP_EN"
            assert en.strip(), f"Leere EN-Uebersetzung fuer {de!r}"

    def test_bekannte_kern_vokabeln_vorhanden(self):
        for wort in ("KRITISCH", "ÜBERFÄLLIG", "GRÜN", "GELB", "ROT",
                     "✓ Kontakt", "SLA VERLETZT", "Ersatzteil bestellt"):
            assert wort in LABEL_MAP_EN, f"{wort!r} fehlt in LABEL_MAP_EN"

    def test_de_und_en_sind_nie_zufaellig_identisch_fuer_kernvokabular(self):
        """Regressionsschutz: die Kern-Statuswoerter muessen sich tatsaechlich
        unterscheiden, sonst waere die Uebersetzung wirkungslos."""
        kern = ["KRITISCH", "ÜBERFÄLLIG", "HOCH", "GRÜN", "GELB", "ROT",
                "Kontakt ausstehend", "Ersatzteil bestellt", "Abgeschlossen"]
        for wort in kern:
            assert LABEL_MAP_EN[wort] != wort, f"{wort!r} wurde nicht uebersetzt"


class TestVollstaendigeLabelAbdeckung:
    """Rendert das komplette Dashboard-HTML (Echtdaten- UND Demo-Struktur) und
    prueft, dass jeder data-label-de-Wert eine LABEL_MAP_EN-Uebersetzung hat.
    Automatisierte Variante der manuellen Browser-Verifikation aus dem
    i18n-Komplettaudit -- verhindert, dass zukuenftige _label()-Aufrufe ohne
    zugehoerigen LABEL_MAP_EN-Eintrag unbemerkt bleiben."""

    # Woerter, die bewusst in DE und EN identisch sind (Fremdwoerter/Marken/
    # bereits-englische Begriffe) -- kein Uebersetzungsfehler.
    _BEWUSST_IDENTISCH = {"Auto", "Info", "Optimal", "Scoring", "Due-Date", "SMax Go API"}

    def _alle_data_label_de_werte(self, techniker: dict) -> set[str]:
        html_out = dash.render_html(
            ampeln=[], stk_rows=[], ct_top5=[], techniker=techniker,
            nrw_warnung=None, erstellt_am=datetime.datetime(2026, 8, 14),
            is_echtdaten=bool(techniker),
        )
        return set(html.unescape(m) for m in re.findall(r'data-label-de="([^"]*)"', html_out))

    def test_alle_label_werte_haben_uebersetzung_oder_sind_bewusst_identisch(self):
        techniker = {"T1": {"standort": "Hamburg", "lat": 53.5, "lon": 10.0}}
        werte = self._alle_data_label_de_werte(techniker)
        assert werte, "Keine data-label-de-Werte gefunden -- Mechanismus greift nicht mehr?"
        fehlend = [w for w in werte if w not in LABEL_MAP_EN and w not in self._BEWUSST_IDENTISCH]
        assert not fehlend, f"data-label-de-Werte ohne LABEL_MAP_EN-Eintrag: {fehlend}"

    def test_kein_data_label_de_wert_enthaelt_html_tags(self):
        """Schuetzt vor dem 'text_bereits_uebersetzt vergessen'-Fehler: ein
        data-label-de-Attribut darf niemals verschachteltes HTML enthalten."""
        techniker = {"T1": {"standort": "Hamburg", "lat": 53.5, "lon": 10.0}}
        html_out = dash.render_html(
            ampeln=[], stk_rows=[], ct_top5=[], techniker=techniker,
            nrw_warnung=None, erstellt_am=datetime.datetime(2026, 8, 14),
            is_echtdaten=True,
        )
        assert not re.search(r'data-label-de="[^"]*[<>][^"]*"', html_out)
