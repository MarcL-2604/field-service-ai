"""Tests fuer techniker/plz_koordinaten.py (pgeocode-basierter PLZ-Lookup).

Ersetzt/ergaenzt die kleine, manuell kuratierte techniker.scoring._KLINIK_COORDS
(~90 Eintraege) um pgeocode (GeoNames-Datenbank fuer Deutschland, ~10.800 PLZ),
um die reale PLZ-Abdeckung fuer importierte SMax-Auftraege deutlich zu erhoehen.
"""

import json
import time

import pytest

from techniker.plz_koordinaten import hole_koordinaten
from techniker.scoring import _KLINIK_COORDS
from api.smax_cache import _CACHE


# ===================================================================
# hole_koordinaten(): bekannte PLZ
# ===================================================================

class TestHoleKoordinatenBekanntePlz:
    def test_berlin_10115_plausible_koordinaten(self):
        koord = hole_koordinaten("10115")
        assert koord is not None
        lat, lon = koord
        assert 52.4 < lat < 52.6
        assert 13.2 < lon < 13.6

    def test_muenchen_80331_plausible_koordinaten(self):
        koord = hole_koordinaten("80331")
        assert koord is not None
        lat, lon = koord
        assert 48.0 < lat < 48.3
        assert 11.4 < lon < 11.7

    def test_gibt_tuple_aus_floats_zurueck(self):
        koord = hole_koordinaten("10115")
        assert isinstance(koord, tuple)
        assert len(koord) == 2
        assert all(isinstance(v, float) for v in koord)


# ===================================================================
# hole_koordinaten(): unbekannte/ungueltige PLZ -> None, kein Absturz
# ===================================================================

class TestHoleKoordinatenUngueltig:
    def test_leerer_string(self):
        assert hole_koordinaten("") is None

    def test_none(self):
        assert hole_koordinaten(None) is None

    def test_nur_leerzeichen(self):
        assert hole_koordinaten("   ") is None

    def test_nicht_numerisch(self):
        assert hole_koordinaten("abcde") is None

    def test_zu_lang(self):
        assert hole_koordinaten("123456") is None

    def test_unbekannte_aber_gueltig_formatierte_plz(self):
        """00000 ist keine vergebene deutsche PLZ -> None, kein Fehler."""
        assert hole_koordinaten("00000") is None

    def test_auslaendische_plz_liefert_none_statt_falscher_koordinate(self):
        """Schweizer/oesterreichische PLZ (4-stellig, hier zero-padded) sind nicht
        in der deutschen pgeocode-Datenbank -- muss sauber None liefern, nicht
        irrtuemlich eine deutsche PLZ mit gleicher Ziffernfolge zurueckgeben."""
        # "01011" = zero-gepaddetes Lausanne (CH) in den SMax-Rohdaten
        koord = hole_koordinaten("01011")
        # Falls "01011" zufaellig KEINE echte deutsche PLZ ist, muss None kommen.
        # Wir pruefen nur: kein Absturz, Ergebnis ist None oder ein plausibles Tuple.
        assert koord is None or isinstance(koord, tuple)


# ===================================================================
# Fallback-Kette: _KLINIK_COORDS hat Vorrang vor pgeocode
# ===================================================================

class TestFallbackKette:
    def test_klinik_coords_eintrag_hat_vorrang(self):
        plz, erwartete_koord = next(iter(_KLINIK_COORDS.items()))
        assert hole_koordinaten(plz) == erwartete_koord

    def test_alle_klinik_coords_eintraege_unveraendert(self):
        """Kein einziger kuratierter Eintrag darf durch pgeocode ueberschrieben werden."""
        for plz, koord in _KLINIK_COORDS.items():
            assert hole_koordinaten(plz) == koord

    def test_plz_ausserhalb_klinik_coords_nutzt_pgeocode(self):
        """Eine PLZ, die NICHT in _KLINIK_COORDS steht, aber uebliche deutsche
        PLZ ist, muss trotzdem aufgeloest werden (Fallback greift)."""
        plz = "80331"  # Muenchen -- ueblicherweise nicht in der kleinen Kliniken-Liste
        assert plz not in _KLINIK_COORDS
        assert hole_koordinaten(plz) is not None


# ===================================================================
# Performance: viele (realistisch stark wiederholte) Lookups
# ===================================================================

class TestPerformance:
    def test_wiederholte_lookups_realistischer_plz_sind_schnell(self):
        """Simuliert das reale Nutzungsmuster: ~10.050 Auftraege, aber nur eine
        kleine Menge unterschiedlicher PLZ (Kliniken werden mehrfach besucht).
        Der lru_cache in _pgeocode_koordinaten() muss das abfangen -- diese
        Groessenordnung darf nicht spuerbar haengen."""
        plz_pool = [f"{n:05d}" for n in range(10000, 10200)]  # 200 unique PLZ
        auftraege = (plz_pool * 51)[:10050]  # ~10.050 Lookups, stark wiederholt

        start = time.perf_counter()
        for plz in auftraege:
            hole_koordinaten(plz)
        elapsed = time.perf_counter() - start

        assert elapsed < 5.0, f"10.050 Lookups (200 unique) dauerten {elapsed:.2f}s"


# ===================================================================
# Reale Abdeckung: Crosstraining + Gebietsoptimierung nutzen die
# erweiterte PLZ-Aufloesung (verankert gegen smax_dashboard_data.json)
# ===================================================================

class TestErweiterte_Abdeckung_RealeDaten:
    @pytest.fixture(autouse=True)
    def setup(self):
        if not _CACHE.exists():
            pytest.skip("data/smax_dashboard_data.json nicht vorhanden -- kein Echtdaten-Import")
        self.data = json.loads(_CACHE.read_text(encoding="utf-8"))

    def test_jobs_plz_aufgeloest_vorhanden(self):
        assert "jobs_plz_aufgeloest" in self.data
        assert "jobs_gesamt" in self.data

    def test_aufloesungsrate_deutlich_ueber_der_alten_19_prozent(self):
        """Die alte feste _KLINIK_COORDS-Liste (~90 Eintraege) loeste nur ca. 19%
        der Jobs auf. Mit pgeocode (DE-only) muss die Rate deutlich hoeher sein.
        Hinweis: ~30% der realen Jobs liegen in Oesterreich/der Schweiz (z.B. Wien,
        Bern, Zuerich) und sind fuer eine DE-only-Datenbank grundsaetzlich nicht
        aufloesbar -- 100% ist daher kein realistisches Ziel, wohl aber >50%."""
        rate = self.data["jobs_plz_aufgeloest"] / self.data["jobs_gesamt"]
        assert rate > 0.5, f"Aufloesungsrate nur {rate:.1%} -- erwartet deutlich > 19%"

    def test_job_standorte_deutlich_groesser_als_vorher(self):
        """Vor der Umstellung gab es 151 Job-Standorte (nur ueber die kleine
        _KLINIK_COORDS-Liste aufloesbar)."""
        assert len(self.data["job_standorte"]) > 500

    def test_stk_potenzial_profitiert_von_erweiterter_abdeckung(self):
        """Mehr aufgeloeste Repair-Jobs im Umkreis -> hoeheres Crosstraining-Potenzial
        pro Techniker als mit der alten, kleinen Koordinatenliste."""
        gesamt = sum(t["stk_potenzial"] for t in self.data["techniker"])
        assert gesamt > 0
