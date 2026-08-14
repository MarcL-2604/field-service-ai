"""Tests fuer den Header-Badge-i18n-Fix (Echtdaten/Demo-Daten).

Bug: Der Header-Badge (und der gleichartige Tab-1-Techniker-Hinweis) berechnete
serverseitig korrekt den tatsaechlichen Datenmodus, aber der i18n-Dict-Eintrag
fuer den Sprachwechsel war ein davon unabhaengiger, statischer Wert -- im
EN-Modus stand deshalb IMMER "Demo Data · Configurable", auch bei
Echtdaten. Fix: _demo_badge_texte()/_demo_hint_texte() liefern je EIN
DE/EN-Wertepaar, das render_html() fuer BEIDE Stellen (initialer Render +
i18n-Dict) verwendet -- keine zweite, unabhaengig gepflegte Quelle mehr.
"""

from reporting.dashboard import _demo_badge_texte, _demo_hint_texte


class TestDemoBadgeTexte:
    def test_echtdaten_ohne_pseudonymisierung(self):
        de, en = _demo_badge_texte(is_echtdaten=True, pseudonymisiert=False)
        assert de == "Echtdaten"
        assert en == "Real Data"

    def test_echtdaten_mit_pseudonymisierung(self):
        de, en = _demo_badge_texte(is_echtdaten=True, pseudonymisiert=True)
        assert "Pseudonymisiert" in de
        assert "Pseudonymized" in en

    def test_demo_modus(self):
        de, en = _demo_badge_texte(is_echtdaten=False, pseudonymisiert=False)
        assert de == "Demo-Daten · Konfigurierbar"
        assert en == "Demo Data · Configurable"

    def test_demo_modus_ignoriert_pseudonymisierung_flag(self):
        """pseudonymisiert ist nur im Echtdaten-Fall relevant."""
        de, en = _demo_badge_texte(is_echtdaten=False, pseudonymisiert=True)
        assert de == "Demo-Daten · Konfigurierbar"
        assert en == "Demo Data · Configurable"

    def test_echtdaten_und_demo_ergeben_unterschiedlichen_text_je_sprache(self):
        de_echt, en_echt = _demo_badge_texte(True, False)
        de_demo, en_demo = _demo_badge_texte(False, False)
        assert de_echt != de_demo
        assert en_echt != en_demo


class TestDemoHintTexte:
    def test_echtdaten_enthaelt_modus_anzahl_und_datum(self):
        de, en = _demo_hint_texte(is_echtdaten=True, technikeranzahl=24, stand_datum="14.08.2026")
        assert "Echtdaten" in de and "24 Techniker" in de and "14.08.2026" in de
        assert "Real Data" in en and "24 technicians" in en and "14.08.2026" in en

    def test_demo_modus_enthaelt_korrekte_technikeranzahl(self):
        """Demo-Modus hat 14 Techniker (T1-T14), nicht die Echtdaten-Anzahl 24 --
        die Anzahl darf nicht hartcodiert sein."""
        de, en = _demo_hint_texte(is_echtdaten=False, technikeranzahl=14, stand_datum="14.08.2026")
        assert "14 Techniker" in de
        assert "14 technicians" in en
        assert "Demo-Daten" in de and "Demo Data" in en

    def test_datum_bleibt_in_beiden_sprachen_identisch_und_erhalten(self):
        """Kernbug: das Datum ging beim Sprachwechsel komplett verloren, weil
        der alte i18n-Dict-Eintrag keinen Platzhalter dafuer hatte."""
        de, en = _demo_hint_texte(is_echtdaten=True, technikeranzahl=24, stand_datum="01.01.2027")
        assert "01.01.2027" in de
        assert "01.01.2027" in en

    def test_englisch_nutzt_as_of_statt_stand(self):
        _, en = _demo_hint_texte(is_echtdaten=True, technikeranzahl=24, stand_datum="14.08.2026")
        assert "As of" in en
        assert "Stand" not in en


class TestDemoBadgeImGerenderetenHtml:
    """Stellt sicher, dass das gerenderte Dashboard-HTML den echten Datenmodus
    im Badge UND im i18n-Dict konsistent widerspiegelt (nicht nur im
    Server-gerenderten DE-Text, sondern auch im EN-Uebersetzungs-Eintrag)."""

    def _render(self, is_echtdaten: bool) -> str:
        import datetime
        import reporting.dashboard as dash
        techniker = {"T1": {"standort": "Hamburg", "lat": 53.5, "lon": 10.0}}
        return dash.render_html(
            ampeln=[], stk_rows=[], ct_top5=[], techniker=techniker,
            nrw_warnung=None, erstellt_am=datetime.datetime(2026, 8, 14),
            is_echtdaten=is_echtdaten,
        )

    def test_echtdaten_i18n_dict_enthaelt_real_data_nicht_demo_data(self):
        import json
        html = self._render(is_echtdaten=True)
        assert f"'header.demo': {json.dumps('Real Data', ensure_ascii=False)}" in html
        assert f"'header.demo': {json.dumps('Demo Data · Configurable', ensure_ascii=False)}" not in html

    def test_demo_modus_i18n_dict_enthaelt_demo_data(self):
        import json
        html = self._render(is_echtdaten=False)
        assert f"'header.demo': {json.dumps('Demo Data · Configurable', ensure_ascii=False)}" in html

    def test_hint_demo_dict_enthaelt_korrekte_technikeranzahl_in_beiden_sprachen(self):
        html = self._render(is_echtdaten=False)
        assert "1 Techniker" in html
        assert "1 technicians" in html
