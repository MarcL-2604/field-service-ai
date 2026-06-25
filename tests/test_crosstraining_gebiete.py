"""
tests/test_crosstraining_gebiete.py
=====================================
Tests fuer gebietsbezogene Crosstraining-Berechnung.

Testet:
  - finde_repair_familie(): kanonischer Familien-Schluessel fuer repair=True Geraete
  - _haversine_km(): Luftlinien-Distanz-Formel
  - Crosstraining-Schwellwert-Konstanten in smax_cache
"""

import pytest

from api.cluster_mapping import finde_repair_familie
from api.smax_cache import _CT_LUFTLINIE_KM, _CT_RADIUS_KM, _CT_ROAD_FAKTOR, _haversine_km


# ══════════════════════════════════════════════════════════════════════════════
# finde_repair_familie: repair=True Geraete
# ══════════════════════════════════════════════════════════════════════════════

class TestFindRepairFamilie:

    def test_hugo_praefix_familie(self):
        assert finde_repair_familie("MC-HUGO-3DDOF") == "MC-HUGO"

    def test_hugo_variante_gleiche_familie(self):
        assert finde_repair_familie("MC-HUGO-123") == "MC-HUGO"
        assert finde_repair_familie("MC-HUGO-456") == "MC-HUGO"

    def test_840_praefix_familie(self):
        assert finde_repair_familie("MC-840-A") == "MC-840"

    def test_840_ohne_suffix_praefix_familie(self):
        assert finde_repair_familie("MC-840") == "MC-840"

    def test_mr8_praefix_familie(self):
        """Affera-Katheter-Familie — Praefix mit Bindestrich."""
        assert finde_repair_familie("MC-MR8-AA07") == "MC-MR8-"

    def test_mr8_variante(self):
        assert finde_repair_familie("MC-MR8-AA09") == "MC-MR8-"

    def test_8253_praefix_familie(self):
        assert finde_repair_familie("MC-8253001") == "MC-8253"

    def test_9735_praefix_familie(self):
        assert finde_repair_familie("MC-9735-A") == "MC-9735"

    def test_bi70_praefix_familie(self):
        assert finde_repair_familie("MC-BI70-X") == "MC-BI70"

    def test_pb_praefix_familie(self):
        assert finde_repair_familie("MC-PB840") == "MC-PB"

    # ── Exact-Match Geraete (repair=True) ────────────────────────────────────

    def test_nitron_exact_familie(self):
        assert finde_repair_familie("MC-NITRON") == "MC-NITRON"

    def test_ft10_exact_familie(self):
        assert finde_repair_familie("MC-FT10") == "MC-FT10"

    def test_ls10_exact_familie(self):
        assert finde_repair_familie("MC-LS10") == "MC-LS10"

    def test_vlfx8_exact_familie(self):
        assert finde_repair_familie("MC-VLFX8") == "MC-VLFX8"

    def test_argon4_exact_familie(self):
        assert finde_repair_familie("MC-ARGON4") == "MC-ARGON4"

    # ── repair=False → None ──────────────────────────────────────────────────

    def test_vista_repair_false_gibt_none(self):
        assert finde_repair_familie("MC-VISTA") is None

    def test_illumisite_repair_false_gibt_none(self):
        assert finde_repair_familie("MC-ILLUMISITE") is None

    def test_pm7100_repair_false_gibt_none(self):
        assert finde_repair_familie("MC-PM7100-BL") is None

    def test_rapidvac_repair_false_gibt_none(self):
        assert finde_repair_familie("MC-RAPIDVAC") is None

    def test_scope_repair_false_gibt_none(self):
        assert finde_repair_familie("MC-SCOPE-ABC") is None

    # ── Unbekannte Codes → None ──────────────────────────────────────────────

    def test_unbekannt_gibt_none(self):
        assert finde_repair_familie("MC-UNBEKANNT-9999") is None

    def test_leer_gibt_none(self):
        assert finde_repair_familie("") is None

    def test_ohne_mc_prefix_gibt_none(self):
        assert finde_repair_familie("HUGO-123") is None

    # ── Case-Insensitiv ──────────────────────────────────────────────────────

    def test_case_insensitiv_hugo(self):
        assert finde_repair_familie("mc-hugo-123") == "MC-HUGO"

    def test_case_insensitiv_nitron(self):
        assert finde_repair_familie("mc-nitron") == "MC-NITRON"

    def test_case_insensitiv_vista_none(self):
        assert finde_repair_familie("mc-vista") is None

    # ── Konsistenz mit finde_cluster ─────────────────────────────────────────

    def test_ergebnis_konsistent_mit_cluster_repair_flag(self):
        """finde_repair_familie gibt genau dann einen Wert zurueck wenn finde_cluster.repair=True."""
        from api.cluster_mapping import finde_cluster
        codes = [
            "MC-HUGO-001", "MC-840-A", "MC-NITRON", "MC-FT10",
            "MC-VISTA", "MC-SCOPE-ABC", "MC-ILLUMISITE", "MC-MR8-AA07",
        ]
        for code in codes:
            info = finde_cluster(code)
            familie = finde_repair_familie(code)
            if info is None or not info.repair:
                assert familie is None, f"{code}: erwartet None, got {familie!r}"
            else:
                assert familie is not None, f"{code}: erwartet Familie, got None"


# ══════════════════════════════════════════════════════════════════════════════
# _haversine_km: Distanz-Formel
# ══════════════════════════════════════════════════════════════════════════════

class TestHaversineKm:

    def test_gleicher_punkt_ist_null(self):
        assert _haversine_km(48.27, 8.85, 48.27, 8.85) == pytest.approx(0.0, abs=1e-9)

    def test_balingen_hamburg_ca_680km(self):
        """Balingen (48.27, 8.85) → Hamburg (53.55, 9.99) ≈ 595 km Luftlinie."""
        d = _haversine_km(48.2747, 8.8522, 53.5505, 9.9937)
        assert 580 < d < 620

    def test_balingen_obertshausen_ca_175km(self):
        """Balingen (48.27, 8.85) → Obertshausen (50.07, 8.86) ≈ 199 km."""
        d = _haversine_km(48.2747, 8.8522, 50.0706, 8.8614)
        assert 190 < d < 210

    def test_berlin_muenchen_ca_505km(self):
        d = _haversine_km(52.52, 13.405, 48.135, 11.582)
        assert 490 < d < 520

    def test_symmetrisch(self):
        """Haversine ist symmetrisch: d(A,B) == d(B,A)."""
        d1 = _haversine_km(48.27, 8.85, 53.55, 9.99)
        d2 = _haversine_km(53.55, 9.99, 48.27, 8.85)
        assert d1 == pytest.approx(d2, rel=1e-10)


# ══════════════════════════════════════════════════════════════════════════════
# Crosstraining-Konstanten
# ══════════════════════════════════════════════════════════════════════════════

class TestCrosstKonstanten:

    def test_radius_150km(self):
        assert _CT_RADIUS_KM == pytest.approx(150.0)

    def test_road_faktor_1_35(self):
        assert _CT_ROAD_FAKTOR == pytest.approx(1.35)

    def test_luftlinie_ca_111km(self):
        assert _CT_LUFTLINIE_KM == pytest.approx(150.0 / 1.35, rel=1e-6)

    def test_luftlinie_schwellwert_korrekt(self):
        """Punkte <= 111km Luftlinie sollen im Gebiet sein (≤150km Straße)."""
        assert _CT_LUFTLINIE_KM < 115.0
        assert _CT_LUFTLINIE_KM > 108.0
