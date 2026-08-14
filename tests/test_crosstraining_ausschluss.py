"""Tests fuer die Crosstraining-Ausschlussliste (AUFGABE 3).

Produktgruppen aus config.CROSSTRAINING_AUSGESCHLOSSENE_CLUSTER_PRAEFIXE
(Hugo, O-arm, CAS-Platzhalter, CryoConsole-Platzhalter) duerfen NIEMALS als
Crosstraining-Empfehlung erscheinen -- weder im Echtdaten-Pfad
(api/smax_cache.py) noch im Demo-Pfad (reporting/crosstraining_analyse.py) --
auch wenn sie wirtschaftlich sinnvoll waeren.
"""

from config import CROSSTRAINING_AUSGESCHLOSSENE_CLUSTER_PRAEFIXE
from api.smax_cache import _crosstraining_ausgeschlossen
from reporting.crosstraining_analyse import (
    PRODUKTFAMILIE_ZU_MC_PRAEFIX,
    fehlende_familien,
    ist_crosstraining_ausgeschlossen,
)


class TestConfigKonstante:
    def test_enthaelt_hugo_und_oarm(self):
        assert "MC-HUGO" in CROSSTRAINING_AUSGESCHLOSSENE_CLUSTER_PRAEFIXE
        assert "MC-BI70" in CROSSTRAINING_AUSGESCHLOSSENE_CLUSTER_PRAEFIXE

    def test_enthaelt_platzhalter_fuer_cas_und_cryo(self):
        assert any("CAS" in p for p in CROSSTRAINING_AUSGESCHLOSSENE_CLUSTER_PRAEFIXE)
        assert any("CRYO" in p.upper() for p in CROSSTRAINING_AUSGESCHLOSSENE_CLUSTER_PRAEFIXE)


class TestSmaxCacheAusschluss:
    """Echtdaten-Pfad: 'familie' = laengster MC-Code-Praefix (finde_repair_familie)."""

    def test_hugo_praefix_ausgeschlossen(self):
        assert _crosstraining_ausgeschlossen("MC-HUGO") is True

    def test_oarm_praefix_ausgeschlossen(self):
        assert _crosstraining_ausgeschlossen("MC-BI70") is True

    def test_hugo_variante_mit_suffix_ausgeschlossen(self):
        assert _crosstraining_ausgeschlossen("MC-HUGO-3DDOF") is True

    def test_normales_geraet_nicht_ausgeschlossen(self):
        assert _crosstraining_ausgeschlossen("MC-840") is False
        assert _crosstraining_ausgeschlossen("MC-NITRON") is False

    def test_case_insensitiv(self):
        assert _crosstraining_ausgeschlossen("mc-hugo") is True

    def test_platzhalter_matcht_kein_echtes_geraet(self):
        """Platzhalter-Eintraege (CAS/CryoConsole, MC-Code noch offen) duerfen
        niemals ein reales Geraet treffen -- kein Absturz, einfach kein Match."""
        assert _crosstraining_ausgeschlossen("MC-IRGENDWAS") is False
        assert _crosstraining_ausgeschlossen("MC-CRYOCATH") is False


class TestCrosstrainingAnalyseAusschluss:
    """Demo-Pfad: Produktfamilie-Namen statt MC-Codes."""

    def test_hugo_produktfamilie_ausgeschlossen(self):
        assert ist_crosstraining_ausgeschlossen("Hugo") is True

    def test_navigation_oarm_produktfamilie_ausgeschlossen(self):
        assert ist_crosstraining_ausgeschlossen("Navigation") is True

    def test_andere_produktfamilie_nicht_ausgeschlossen(self):
        assert ist_crosstraining_ausgeschlossen("Elektrochirurgie") is False
        assert ist_crosstraining_ausgeschlossen("Beatmung") is False

    def test_unbekannte_familie_ohne_mapping_nicht_ausgeschlossen(self):
        """CAS/CryoConsole existieren (noch) nicht in den Demo-Daten -- kein
        Mapping-Eintrag heisst kein Absturz, einfach kein Treffer."""
        assert ist_crosstraining_ausgeschlossen("CAS") is False
        assert ist_crosstraining_ausgeschlossen("CryoConsole") is False

    def test_mapping_konsistent_mit_config_praefixen(self):
        for praefix in PRODUKTFAMILIE_ZU_MC_PRAEFIX.values():
            assert praefix in CROSSTRAINING_AUSGESCHLOSSENE_CLUSTER_PRAEFIXE

    def test_fehlende_familien_filtert_hugo_trotz_wirtschaftlichkeit(self):
        """Hugo hat hohes STK-Volumen (waere wirtschaftlich attraktiv) -- muss
        trotzdem nie in der Luecken-Liste erscheinen."""
        qualifikationen = {}  # Techniker qualifiziert fuer nichts -> alles fehlend
        reg_volumen = {"Hugo": 999.0, "Elektrochirurgie": 50.0}
        fehlend = fehlende_familien(qualifikationen, reg_volumen)
        assert "Hugo" not in fehlend
        assert "Elektrochirurgie" in fehlend

    def test_fehlende_familien_filtert_navigation_oarm(self):
        qualifikationen = {}
        reg_volumen = {"Navigation": 500.0}
        fehlend = fehlende_familien(qualifikationen, reg_volumen)
        assert "Navigation" not in fehlend
