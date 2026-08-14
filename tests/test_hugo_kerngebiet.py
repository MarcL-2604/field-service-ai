"""Tests fuer reporting/hugo_kerngebiet.py: Hugo-Kerngebiet-Konzept.

Kerngebiet = Fahrzeit-Radius um den WOHNORT des Hugo-Technikers (nicht um
den Hugo-Standort!). Ersetzt das fruehere "Hugo-Zusatzgebiet"
(tests/test_hugo_zusatzgebiet.py, entfernt)."""

from config import HUGO_KERNGEBIET_MAX_FAHRZEIT_MIN
from config_hugo_standorte import HUGO_SPRINGER, HUGO_STANDORTE, HUGO_TEAM_GROESSE
from reporting.hugo_kerngebiet import (
    berechne_hugo_kerngebiete,
    hugo_standort_marker,
    hugo_techniker_namen,
)
from reporting.dashboard import (
    _build_gebiets_script,
    _build_gebiets_svg,
    _render_gebietsoptimierung,
)


# Techniker-Dict im Echtdaten-Kurzform-Schema ("Vorname N.") -- wie
# api/smax_cache.py._display_name_kurz es bei PSEUDONYMISIERUNG_AKTIV=False
# liefert.
TECHNIKER_ECHTDATEN = {
    "Marc L.":    {"standort": "Balingen",  "lat": 48.27, "lon": 8.85},
    "Dirk H.":    {"standort": "Hamburg",   "lat": 53.55, "lon": 9.99},
    "Hector C.":  {"standort": "Schenefeld", "lat": 53.60, "lon": 9.83},
    "Michael G.": {"standort": "Bochum",    "lat": 51.48, "lon": 7.22},
    "Ahmed A.":   {"standort": "Köln",      "lat": 50.94, "lon": 6.96},
    "Sonstiger T.": {"standort": "München", "lat": 48.14, "lon": 11.58},
}

# Techniker-Dict mit Klarnamen als ID (z.B. Demo/Test ohne Kurzform-Mapping).
TECHNIKER_KLARNAMEN = {
    "Marc Liebhardt": {"standort": "Balingen", "lat": 48.27, "lon": 8.85},
}

HUGO_STANDORTE_TEST = {
    "Ulm":     {"anzahl_systeme": 1, "haupt_techniker": ["Marc Liebhardt"], "lat": 48.40, "lon": 9.99},
    "Hamburg": {"anzahl_systeme": 4, "haupt_techniker": ["Dirk Häbel", "Hector C."], "lat": 53.55, "lon": 9.99},
    "Dresden":  {"anzahl_systeme": 1, "haupt_techniker": ["Ahmed Awadallah"],
                 "hinweis": "Springer-Zuständigkeit", "lat": 51.05, "lon": 13.74},
}
HUGO_SPRINGER_TEST = "Ahmed Awadallah"


class TestHugoTechnikerNamen:
    def test_enthaelt_haupt_techniker_und_springer(self):
        namen = hugo_techniker_namen(HUGO_STANDORTE_TEST, HUGO_SPRINGER_TEST)
        assert set(namen) == {"Marc Liebhardt", "Dirk Häbel", "Hector C.", "Ahmed Awadallah"}

    def test_dedupliziert_springer_der_auch_haupt_techniker_ist(self):
        standorte = {"X": {"haupt_techniker": ["Ahmed Awadallah"], "lat": 0, "lon": 0}}
        namen = hugo_techniker_namen(standorte, "Ahmed Awadallah")
        assert namen.count("Ahmed Awadallah") == 1


class TestBerechneHugoKerngebiete:
    def test_kerngebiet_um_wohnort_nicht_um_hugo_standort(self):
        """Kernanforderung: Radius wird um den WOHNORT (Balingen) berechnet,
        nicht um den Hugo-Standort (Ulm), obwohl Ulm ~150km entfernt liegt."""
        ergebnis = berechne_hugo_kerngebiete(
            TECHNIKER_KLARNAMEN, HUGO_STANDORTE_TEST, HUGO_SPRINGER_TEST,
            HUGO_KERNGEBIET_MAX_FAHRZEIT_MIN, umweg_faktor=1.35,
        )
        marc = next(e for e in ergebnis if e["id"] == "Marc Liebhardt")
        assert marc["lat"] == 48.27 and marc["lon"] == 8.85  # Balingen (Wohnort), nicht Ulm

    def test_alle_fuenf_hugo_techniker_qualifizieren_ohne_systemanzahl_limit(self):
        """Neues Konzept kennt kein '<=2 Hugo-Systeme'-Limit mehr -- alle
        HUGO_STANDORTE-Techniker + Springer erhalten ein Kerngebiet, sofern
        im Datensatz vorhanden."""
        ergebnis = berechne_hugo_kerngebiete(
            TECHNIKER_ECHTDATEN, HUGO_STANDORTE, HUGO_SPRINGER,
            HUGO_KERNGEBIET_MAX_FAHRZEIT_MIN, umweg_faktor=1.35,
        )
        ids = {e["id"] for e in ergebnis}
        assert ids == {"Marc L.", "Dirk H.", "Hector C.", "Michael G.", "Ahmed A."}
        assert "Sonstiger T." not in ids

    def test_90_minuten_grenze_wird_angewendet(self):
        ergebnis = berechne_hugo_kerngebiete(
            {"Marc Liebhardt": TECHNIKER_KLARNAMEN["Marc Liebhardt"]},
            {"Ulm": HUGO_STANDORTE_TEST["Ulm"]}, "",
            90, umweg_faktor=1.35,
        )
        assert len(ergebnis) == 1
        erwarteter_radius = 90 / 60.0 * (100.0 / 1.35)
        assert abs(ergebnis[0]["radius_km"] - round(erwarteter_radius, 1)) < 0.05

    def test_radius_skaliert_mit_max_fahrzeit(self):
        kurz = berechne_hugo_kerngebiete(
            TECHNIKER_KLARNAMEN, {"Ulm": HUGO_STANDORTE_TEST["Ulm"]}, "", 60, umweg_faktor=1.35,
        )
        lang = berechne_hugo_kerngebiete(
            TECHNIKER_KLARNAMEN, {"Ulm": HUGO_STANDORTE_TEST["Ulm"]}, "", 90, umweg_faktor=1.35,
        )
        assert lang[0]["radius_km"] > kurz[0]["radius_km"]

    def test_techniker_ohne_koordinaten_wird_uebersprungen(self):
        techniker = {"Marc Liebhardt": {"standort": "Unbekannt", "lat": 0.0, "lon": 0.0}}
        ergebnis = berechne_hugo_kerngebiete(
            techniker, {"Ulm": HUGO_STANDORTE_TEST["Ulm"]}, "", 90, umweg_faktor=1.35,
        )
        assert ergebnis == []

    def test_techniker_nicht_im_datensatz_wird_uebersprungen_ohne_absturz(self):
        ergebnis = berechne_hugo_kerngebiete(
            {}, HUGO_STANDORTE_TEST, HUGO_SPRINGER_TEST, 90, umweg_faktor=1.35,
        )
        assert ergebnis == []

    def test_kurzname_matching_fuer_echtdaten_modus(self):
        """'Dirk Häbel' aus HUGO_STANDORTE matcht 'Dirk H.' im Techniker-Dict
        (Kurzform-Schema von api/smax_cache.py._display_name_kurz)."""
        ergebnis = berechne_hugo_kerngebiete(
            TECHNIKER_ECHTDATEN, {"Hamburg": HUGO_STANDORTE_TEST["Hamburg"]}, "",
            90, umweg_faktor=1.35,
        )
        ids = {e["id"] for e in ergebnis}
        assert ids == {"Dirk H.", "Hector C."}

    def test_springer_markiert(self):
        ergebnis = berechne_hugo_kerngebiete(
            TECHNIKER_ECHTDATEN, HUGO_STANDORTE, HUGO_SPRINGER,
            HUGO_KERNGEBIET_MAX_FAHRZEIT_MIN, umweg_faktor=1.35,
        )
        ahmed = next(e for e in ergebnis if e["id"] == "Ahmed A.")
        assert ahmed["ist_springer"] is True
        marc = next(e for e in ergebnis if e["id"] == "Marc L.")
        assert marc["ist_springer"] is False


class TestHugoStandortMarker:
    def test_ein_marker_pro_hugo_standort(self):
        marker = hugo_standort_marker(HUGO_STANDORTE_TEST, TECHNIKER_KLARNAMEN)
        assert {m["standort"] for m in marker} == {"Ulm", "Hamburg", "Dresden"}

    def test_marker_enthaelt_anzahl_systeme_und_koordinaten(self):
        marker = hugo_standort_marker(HUGO_STANDORTE_TEST, TECHNIKER_KLARNAMEN)
        ulm = next(m for m in marker if m["standort"] == "Ulm")
        assert ulm["anzahl_systeme"] == 1
        assert ulm["lat"] == 48.40 and ulm["lon"] == 9.99

    def test_zustaendige_ids_nur_fuer_gefundene_techniker(self):
        marker = hugo_standort_marker(HUGO_STANDORTE_TEST, TECHNIKER_KLARNAMEN)
        ulm = next(m for m in marker if m["standort"] == "Ulm")
        assert ulm["zustaendige_ids"] == ["Marc Liebhardt"]
        hamburg = next(m for m in marker if m["standort"] == "Hamburg")
        assert hamburg["zustaendige_ids"] == []  # Dirk/Hector nicht in TECHNIKER_KLARNAMEN

    def test_dresden_hinweis_springer_zustaendigkeit(self):
        marker = hugo_standort_marker(HUGO_STANDORTE_TEST, TECHNIKER_KLARNAMEN)
        dresden = next(m for m in marker if m["standort"] == "Dresden")
        assert dresden["hinweis"] == "Springer-Zuständigkeit"

    def test_reale_config_neun_standorte(self):
        marker = hugo_standort_marker(HUGO_STANDORTE, {})
        assert len(marker) == 9
        assert sum(m["anzahl_systeme"] for m in marker) == 12  # 4+1+1+1+1+1+1+1+1


class TestConfigHugoStandorte:
    def test_team_groesse_pm_zwei_repair_eins(self):
        assert HUGO_TEAM_GROESSE["PM"] == 2
        assert HUGO_TEAM_GROESSE["REPAIR"] == 1

    def test_springer_ist_ahmed_awadallah(self):
        assert HUGO_SPRINGER == "Ahmed Awadallah"

    def test_dresden_nur_springer_zustaendig(self):
        assert HUGO_STANDORTE["Dresden"]["haupt_techniker"] == ["Ahmed Awadallah"]

    def test_marc_liebhardt_drei_standorte(self):
        marc_standorte = [
            name for name, d in HUGO_STANDORTE.items()
            if "Marc Liebhardt" in d["haupt_techniker"]
        ]
        assert set(marc_standorte) == {"Ulm", "Mannheim", "Heidelberg"}


# ---------------------------------------------------------------------------
# Toggle-Rendering (Hugo-Kerngebiet ist wieder ein optionales Ein/Aus-Feature,
# Standard AUS -- kein permanentes Overlay mehr).
# ---------------------------------------------------------------------------

_M_AKT = [{"id": "T1", "standort": "Hamburg", "kliniken": 12, "avg_fahrzeit": 45,
           "max_fahrzeit": 90, "fahrtstunden_jahr": 200, "onsite_stunden": 400, "ratio": 2.0}]
_M_OPT = [{"id": "T1", "standort": "Hamburg", "kliniken": 12, "avg_fahrzeit": 45,
           "max_fahrzeit": 90, "fahrtstunden_jahr": 200, "onsite_stunden": 400, "ratio": 2.0,
           "verschoben": 0, "verschoben_gewonnen": 0, "verschoben_abgegeben": 0}]
_TOGGLE_TECHNIKER = {"T1": {"standort": "Hamburg", "lat": 53.55, "lon": 9.99}}
_TOGGLE_HUGO_KERNGEBIETE = berechne_hugo_kerngebiete(
    {"Marc Liebhardt": {"standort": "Balingen", "lat": 48.27, "lon": 8.85}},
    {"Ulm": {"anzahl_systeme": 1, "haupt_techniker": ["Marc Liebhardt"], "lat": 48.40, "lon": 9.99}},
    "", HUGO_KERNGEBIET_MAX_FAHRZEIT_MIN, umweg_faktor=1.35,
)
_TOGGLE_HUGO_STANDORTE_MARKER = hugo_standort_marker(
    {"Ulm": {"anzahl_systeme": 1, "haupt_techniker": ["Marc Liebhardt"], "lat": 48.40, "lon": 9.99}},
    {"Marc Liebhardt": {"standort": "Balingen", "lat": 48.27, "lon": 8.85}},
)


class TestHugoKerngebietToggleBox:
    def test_toggle_checkbox_vorhanden(self):
        html = _render_gebietsoptimierung(
            _M_AKT, _M_OPT, _TOGGLE_TECHNIKER,
            hugo_kerngebiete=_TOGGLE_HUGO_KERNGEBIETE,
        )
        assert 'id="hugo-kg-toggle"' in html
        assert 'type="checkbox"' in html

    def test_toggle_ist_standardmaessig_nicht_angehakt(self):
        """Kein 'checked'-Attribut auf der Checkbox -- Default AUS."""
        html = _render_gebietsoptimierung(
            _M_AKT, _M_OPT, _TOGGLE_TECHNIKER,
            hugo_kerngebiete=_TOGGLE_HUGO_KERNGEBIETE,
        )
        toggle_start = html.index('id="hugo-kg-toggle"')
        toggle_tag = html[max(0, toggle_start - 60):toggle_start + 60]
        assert "checked" not in toggle_tag

    def test_hint_box_ist_initial_versteckt(self):
        html = _render_gebietsoptimierung(
            _M_AKT, _M_OPT, _TOGGLE_TECHNIKER,
            hugo_kerngebiete=_TOGGLE_HUGO_KERNGEBIETE,
        )
        assert 'id="hugo-kg-hint" style="display:none"' in html

    def test_hint_enthaelt_team_groesse_und_springer_info(self):
        html = _render_gebietsoptimierung(
            _M_AKT, _M_OPT, _TOGGLE_TECHNIKER,
            hugo_kerngebiete=_TOGGLE_HUGO_KERNGEBIETE,
        )
        assert "Team-Gr" in html
        assert "Springer" in html

    def test_label_nennt_90_minuten_und_wohnort(self):
        html = _render_gebietsoptimierung(
            _M_AKT, _M_OPT, _TOGGLE_TECHNIKER,
            hugo_kerngebiete=_TOGGLE_HUGO_KERNGEBIETE,
        )
        assert f"{HUGO_KERNGEBIET_MAX_FAHRZEIT_MIN} Min." in html
        assert "Wohnort" in html


class TestHugoKerngebietSvgDefaultVersteckt:
    def test_kerngebiet_layer_default_versteckt(self):
        svg = _build_gebiets_svg(
            _TOGGLE_TECHNIKER, plz_abdeckung=[],
            hugo_kerngebiete=_TOGGLE_HUGO_KERNGEBIETE,
            hugo_standorte_marker=_TOGGLE_HUGO_STANDORTE_MARKER,
        )
        assert '<g id="hugo-kerngebiete" style="display:none">' in svg

    def test_hugo_standorte_layer_default_versteckt(self):
        svg = _build_gebiets_svg(
            _TOGGLE_TECHNIKER, plz_abdeckung=[],
            hugo_kerngebiete=_TOGGLE_HUGO_KERNGEBIETE,
            hugo_standorte_marker=_TOGGLE_HUGO_STANDORTE_MARKER,
        )
        assert '<g id="hugo-standorte" style="display:none">' in svg

    def test_ohne_daten_werden_keine_hugo_layer_gerendert(self):
        svg = _build_gebiets_svg(_TOGGLE_TECHNIKER, plz_abdeckung=[])
        assert 'id="hugo-kerngebiete"' not in svg
        assert 'id="hugo-standorte"' not in svg


class TestHugoKerngebietToggleJavascript:
    def test_script_verdrahtet_toggle_checkbox(self):
        script = _build_gebiets_script(_TOGGLE_TECHNIKER, plz_abdeckung=[], gebiets_punkte=[])
        assert "hugo-kg-toggle" in script

    def test_script_schaltet_beide_layer_gemeinsam(self):
        script = _build_gebiets_script(_TOGGLE_TECHNIKER, plz_abdeckung=[], gebiets_punkte=[])
        assert "#hugo-kerngebiete" in script
        assert "#hugo-standorte" in script

    def test_script_schaltet_hint_box_mit(self):
        script = _build_gebiets_script(_TOGGLE_TECHNIKER, plz_abdeckung=[], gebiets_punkte=[])
        assert "hugo-kg-hint" in script
