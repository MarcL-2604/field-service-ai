"""
tests/test_skill_korrekturen.py
================================
Tests fuer die manuelle Skill-Korrektur-Pipeline in smax_cache.py.
"""

import pytest

from api.smax_cache import _lade_korrekturen, _wende_korrektur_an


# ══════════════════════════════════════════════════════════════════════════════
# _wende_korrektur_an: Präfix-Filter + Whitelist
# ══════════════════════════════════════════════════════════════════════════════

class TestWendeKorrekturAn:

    def _korr(self, praefixe=None, korrekt=None) -> dict:
        return {
            "praefixe": praefixe or [],
            "korrekt":  set(korrekt or []),
        }

    def test_keine_korrektur_passiert_alles_durch(self):
        mcs = {"MC-FT10", "MC-LS10", "MC-HUGO-123"}
        assert _wende_korrektur_an(mcs, self._korr()) == mcs

    def test_praefix_entfernt_passende_codes(self):
        mcs = {"MC-MR8-AA07", "MC-MR8-AA09", "MC-FT10"}
        result = _wende_korrektur_an(mcs, self._korr(praefixe=["MC-MR8-"]))
        assert result == {"MC-FT10"}

    def test_mehrere_praefixe_werden_alle_entfernt(self):
        mcs = {"MC-MR8-AA07", "MC-8253001", "MC-FT10", "MC-LS10"}
        result = _wende_korrektur_an(mcs, self._korr(praefixe=["MC-MR8-", "MC-8253"]))
        assert result == {"MC-FT10", "MC-LS10"}

    def test_whitelist_beschraenkt_ergebnis(self):
        mcs = {"MC-FT10", "MC-LS10", "MC-ARGON4"}
        result = _wende_korrektur_an(mcs, self._korr(korrekt=["MC-FT10", "MC-LS10"]))
        assert result == {"MC-FT10", "MC-LS10"}

    def test_praefix_plus_whitelist_kombiniert(self):
        """Realer Fall Dirk G.: MR8+8253 raus, dann nur FT10/LS10/VLFX8 zählen."""
        mcs = {"MC-MR8-AA07", "MC-8253001", "MC-FT10", "MC-LS10", "MC-VLFX8"}
        result = _wende_korrektur_an(
            mcs,
            self._korr(
                praefixe=["MC-MR8-", "MC-8253"],
                korrekt=["MC-FT10", "MC-LS10", "MC-VLFX8"],
            ),
        )
        assert result == {"MC-FT10", "MC-LS10", "MC-VLFX8"}

    def test_whitelist_leer_bedeutet_kein_whitelist_filter(self):
        """Leere korrekt-Menge → nur Präfix-Filter, keine Whitelist."""
        mcs = {"MC-MR8-AA07", "MC-FT10"}
        result = _wende_korrektur_an(mcs, self._korr(praefixe=["MC-MR8-"], korrekt=[]))
        assert result == {"MC-FT10"}

    def test_leere_repair_mcs_ergibt_leere_menge(self):
        assert _wende_korrektur_an(set(), self._korr(praefixe=["MC-MR8-"])) == set()

    def test_case_insensitiv_whitelist(self):
        """Whitelist-Vergleich case-insensitiv."""
        mcs = {"MC-ft10", "MC-LS10"}
        result = _wende_korrektur_an(
            mcs, self._korr(korrekt=["MC-FT10", "MC-LS10"])
        )
        assert result == {"MC-ft10", "MC-LS10"}

    def test_case_insensitiv_praefix(self):
        """Präfix-Filter case-insensitiv."""
        mcs = {"mc-mr8-aa07", "MC-FT10"}
        result = _wende_korrektur_an(mcs, self._korr(praefixe=["MC-MR8-"]))
        assert result == {"MC-FT10"}

    def test_dirk_g_realer_fall_kein_match_whitelist(self):
        """Dirk G. hat keine JA-Eintraege fuer FT10/LS10/VLFX8 → Ergebnis 0."""
        # Sein tatsaechlicher repair-Set: nur MR8 und 8253
        mcs = {"MC-MR8-AA07", "MC-MR8-AA09", "MC-8253001", "MC-8253200"}
        result = _wende_korrektur_an(
            mcs,
            self._korr(
                praefixe=["MC-MR8-", "MC-8253"],
                korrekt=["MC-FT10", "MC-LS10", "MC-VLFX8"],
            ),
        )
        assert result == set()
        assert len(result) == 0


# ══════════════════════════════════════════════════════════════════════════════
# _lade_korrekturen: Datei-Loader
# ══════════════════════════════════════════════════════════════════════════════

class TestLadeKorrekturen:

    def test_gibt_dict_zurueck(self):
        result = _lade_korrekturen()
        assert isinstance(result, dict)

    def test_dirk_goralski_vorhanden(self):
        result = _lade_korrekturen()
        # Schluessel ist norm_umlaut("Dirk Goralski") = "Dirk Goralski" (keine Umlaute)
        assert "Dirk Goralski" in result

    def test_dirk_goralski_praefixe(self):
        k = _lade_korrekturen()["Dirk Goralski"]
        assert "MC-MR8-" in k["praefixe"]
        assert "MC-8253" in k["praefixe"]

    def test_dirk_goralski_korrekt_codes(self):
        k = _lade_korrekturen()["Dirk Goralski"]
        assert "MC-FT10"  in k["korrekt"]
        assert "MC-LS10"  in k["korrekt"]
        assert "MC-VLFX8" in k["korrekt"]

    def test_grund_vorhanden(self):
        k = _lade_korrekturen()["Dirk Goralski"]
        assert len(k["grund"]) > 0
