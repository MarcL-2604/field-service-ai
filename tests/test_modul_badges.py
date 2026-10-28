"""
tests/test_modul_badges.py
===========================
Tests fuer die Modulaufbau-Kennzeichnung im Dashboard (Teil A der
Pilotmodul-Abgrenzung): Tabs spaeterer Module (Crosstraining, Workflow)
bleiben sichtbar, erhalten aber einen Hinweis-Badge. Modul-1-Tabs
(Uebersicht, Auftraege, Business Case, Gebietsoptimierung,
Einstellungsbedarf) bleiben unveraendert ohne Badge.
"""

import datetime

import reporting.dashboard as dash

_TECHNIKER = {"T1": {"standort": "Hamburg", "lat": 53.5, "lon": 10.0}}


def _render():
    return dash.render_html(
        ampeln=[], stk_rows=[], ct_top5=[], techniker=_TECHNIKER,
        nrw_warnung=None, erstellt_am=datetime.datetime(2026, 9, 10),
        is_echtdaten=False,
    )


class TestModulBadgeAufSpaeterenModulTabs:
    def test_crosstraining_tab_traegt_badge_wenn_modul2_inaktiv(self, monkeypatch):
        monkeypatch.setattr(dash, "MODUL_2_AKTIV", False)
        html = _render()
        idx = html.index('data-tab="tab-crosstraining"')
        button = html[idx:html.index("</button>", idx)]
        assert "modul-badge" in button

    def test_workflow_tab_traegt_badge_wenn_modul3_inaktiv(self, monkeypatch):
        monkeypatch.setattr(dash, "MODUL_3_AKTIV", False)
        html = _render()
        idx = html.index('data-tab="tab-workflow"')
        button = html[idx:html.index("</button>", idx)]
        assert "modul-badge" in button

    def test_crosstraining_tab_ohne_badge_wenn_modul2_aktiv(self, monkeypatch):
        monkeypatch.setattr(dash, "MODUL_2_AKTIV", True)
        html = _render()
        idx = html.index('data-tab="tab-crosstraining"')
        button = html[idx:html.index("</button>", idx)]
        assert "modul-badge" not in button

    def test_workflow_tab_ohne_badge_wenn_modul3_aktiv(self, monkeypatch):
        monkeypatch.setattr(dash, "MODUL_3_AKTIV", True)
        html = _render()
        idx = html.index('data-tab="tab-workflow"')
        button = html[idx:html.index("</button>", idx)]
        assert "modul-badge" not in button


class TestModul1TabsOhneBadge:
    def test_modul_1_tabs_haben_nie_einen_badge(self):
        html = _render()
        for tab_id in ("tab-uebersicht", "tab-auftraege", "tab-business",
                       "tab-gebietsopt", "tab-einstellung"):
            idx = html.index(f'data-tab="{tab_id}"')
            button = html[idx:html.index("</button>", idx)]
            assert "modul-badge" not in button, f"{tab_id} sollte keinen Modul-Badge haben"


class TestModulBadgeI18n:
    def test_badge_key_hat_de_und_en_uebersetzung(self):
        html = _render()
        assert "'tab.modulBadge':" in html
        # DE-Dict und EN-Dict enthalten beide den Key
        assert html.count("'tab.modulBadge':") == 2

    def test_badge_span_nutzt_data_i18n(self):
        html = _render()
        assert 'class="modul-badge" data-i18n="tab.modulBadge"' in html


class TestKurzeBadgesUndDatenstand:
    def test_badges_kurz_mit_tooltip(self):
        import reporting.dashboard as dash
        assert "'tab.modulBadge': 'Modul 3'" in open(dash.__file__, encoding="utf-8").read()
        assert "'tab.modulBadge2': 'Modul 2'" in open(dash.__file__, encoding="utf-8").read()

    def test_datenstand_texte(self):
        import datetime
        import reporting.dashboard as dash
        heute = datetime.date(2026, 10, 28)
        assert "Beispieldaten" in dash._render_datenstand(False, None, heute)
        frisch = dash._render_datenstand(
            True, {"datenstand_excel": "2026-10-20", "datenstand_letzter_auftrag": "2026-10-15"}, heute)
        assert "20.10.2026" in frisch and "15.10.2026" in frisch and "datenstand-warn" not in frisch
        alt = dash._render_datenstand(
            True, {"datenstand_excel": "2026-09-01", "datenstand_letzter_auftrag": "2026-08-30"}, heute)
        assert "datenstand-warn" in alt
        for text in ("Datenstand: Export vom", "Beispieldaten", "Daten älter als 30 Tage — neuen Export einspielen."):
            assert text in dash.LABEL_MAP_EN
