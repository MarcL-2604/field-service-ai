"""Tests für auftraege.trunkstock – Fahrzeugbestand / Messmittel."""

from datetime import date

import pytest

from auftraege.trunkstock import (
    kalibrierung_pruefen,
    messmittel_verfuegbar,
    trunkstock_fuer_auftrag,
)


# ======================================================================
# messmittel_verfuegbar
# ======================================================================
class TestMessmittelVerfuegbar:
    """Prüft ob ein Techniker die Pflicht-Messmittel hat."""

    # --- positive Fälle ---
    def test_t1_hat_hugo_messmittel(self):
        assert messmittel_verfuegbar("T1", "Hugo") is True

    def test_t1_hat_elektrochirurgie_messmittel(self):
        assert messmittel_verfuegbar("T1", "Elektrochirurgie") is True

    def test_t5_hat_neuromonitoring_messmittel(self):
        assert messmittel_verfuegbar("T5", "Neuromonitoring") is True

    def test_t5_hat_kardiovaskulaer_messmittel(self):
        assert messmittel_verfuegbar("T5", "Kardiovaskulaer") is True

    def test_t10_hat_hugo_messmittel(self):
        assert messmittel_verfuegbar("T10", "Hugo") is True

    def test_t10_hat_wirbelsaeule_messmittel(self):
        assert messmittel_verfuegbar("T10", "Wirbelsaeule") is True

    def test_t13_hat_ablation_messmittel(self):
        assert messmittel_verfuegbar("T13", "Kardiovaskulaer_Ablation") is True

    def test_t4_hat_navigation_messmittel(self):
        assert messmittel_verfuegbar("T4", "Navigation") is True

    def test_t7_hat_gastroenterologie_messmittel(self):
        assert messmittel_verfuegbar("T7", "Gastroenterologie") is True

    def test_t9_hat_neurophysiologie_messmittel(self):
        assert messmittel_verfuegbar("T9", "Neurophysiologie") is True

    def test_t2_hat_capnografie_messmittel(self):
        assert messmittel_verfuegbar("T2", "Capnografie") is True

    def test_t11_hat_energie_messmittel(self):
        assert messmittel_verfuegbar("T11", "Energie") is True

    # --- negative Fälle ---
    def test_t1_hat_keine_navigation_messmittel(self):
        """T1 ist nicht für Navigation trainiert → keine Nav-Messmittel."""
        assert messmittel_verfuegbar("T1", "Navigation") is False

    def test_t13_hat_keine_beatmung_messmittel(self):
        """T13 ist nur Ablations-Spezialist."""
        assert messmittel_verfuegbar("T13", "Beatmung") is False

    def test_t5_hat_keine_hugo_messmittel(self):
        assert messmittel_verfuegbar("T5", "Hugo") is False

    def test_unbekannte_produktfamilie(self):
        assert messmittel_verfuegbar("T1", "Fantasie") is False

    def test_unbekannter_techniker(self):
        assert messmittel_verfuegbar("T99", "Beatmung") is False

    # --- Hugo-Techniker (T1, T6, T10, T11) ---
    @pytest.mark.parametrize("tid", ["T1", "T6", "T10", "T11"])
    def test_hugo_techniker_haben_hugo_messmittel(self, tid):
        assert messmittel_verfuegbar(tid, "Hugo") is True

    @pytest.mark.parametrize("tid", ["T2", "T3", "T4", "T5", "T7",
                                      "T8", "T9", "T12", "T13", "T14"])
    def test_nicht_hugo_techniker_fehlt_hugo(self, tid):
        assert messmittel_verfuegbar(tid, "Hugo") is False


# ======================================================================
# kalibrierung_pruefen
# ======================================================================
class TestKalibrierungPruefen:
    """Findet Messmittel deren Kalibrierung bald abläuft."""

    _STICHTAG = date(2026, 3, 27)

    def test_t1_hugo_diagnosetool_laeuft_bald_ab(self):
        """MM-HUGO-001 bei T1: kalibriert_bis=2026-04-20 → 24 Tage."""
        ergebnis = kalibrierung_pruefen("T1", stichtag=self._STICHTAG)
        art_nrs = [e["artikel_nr"] for e in ergebnis]
        assert "MM-HUGO-001" in art_nrs

    def test_t5_nim_tester_laeuft_bald_ab(self):
        """MM-NEURO-001 bei T5: kalibriert_bis=2026-04-15 → 19 Tage."""
        ergebnis = kalibrierung_pruefen("T5", stichtag=self._STICHTAG)
        art_nrs = [e["artikel_nr"] for e in ergebnis]
        assert "MM-NEURO-001" in art_nrs

    def test_t8_ekg_simulator_laeuft_bald_ab(self):
        """MM-KARD-001 bei T8: kalibriert_bis=2026-04-25 → 29 Tage."""
        ergebnis = kalibrierung_pruefen("T8", stichtag=self._STICHTAG)
        art_nrs = [e["artikel_nr"] for e in ergebnis]
        assert "MM-KARD-001" in art_nrs

    def test_t10_hugo_kalibrierkoffer_laeuft_bald_ab(self):
        """MM-HUGO-002 bei T10: kalibriert_bis=2026-04-10 → 14 Tage."""
        ergebnis = kalibrierung_pruefen("T10", stichtag=self._STICHTAG)
        art_nrs = [e["artikel_nr"] for e in ergebnis]
        assert "MM-HUGO-002" in art_nrs

    def test_tage_verbleibend_korrekt(self):
        ergebnis = kalibrierung_pruefen("T10", stichtag=self._STICHTAG)
        hugo_kb = [e for e in ergebnis if e["artikel_nr"] == "MM-HUGO-002"]
        assert len(hugo_kb) == 1
        assert hugo_kb[0]["tage_verbleibend"] == 14

    def test_t2_keine_bald_ablaufenden(self):
        """T2 hat keine Messmittel die vor 2026-04-26 ablaufen."""
        ergebnis = kalibrierung_pruefen("T2", stichtag=self._STICHTAG)
        assert ergebnis == []

    def test_unbekannter_techniker_leer(self):
        ergebnis = kalibrierung_pruefen("T99", stichtag=self._STICHTAG)
        assert ergebnis == []

    def test_stichtag_weit_voraus_findet_mehr(self):
        """Mit Stichtag 2026-01-01 und tage=365 finden wir viel mehr."""
        ergebnis = kalibrierung_pruefen(
            "T1", stichtag=date(2026, 1, 1), tage=365,
        )
        assert len(ergebnis) >= 3

    def test_stichtag_nach_ablauf_findet_nichts(self):
        """Stichtag nach dem Ablauf → Messmittel nicht in der Liste."""
        ergebnis = kalibrierung_pruefen(
            "T1", stichtag=date(2027, 6, 1), tage=30,
        )
        assert ergebnis == []


# ======================================================================
# trunkstock_fuer_auftrag
# ======================================================================
class TestTrunkstockFuerAuftrag:
    """Stellt auftrags-bezogene Bestandslisten zusammen."""

    def test_stk_liefert_messmittel(self):
        res = trunkstock_fuer_auftrag("T1", "STK", "Hugo")
        assert len(res["messmittel"]) > 0

    def test_stk_kein_werkzeug(self):
        """STK braucht kein Werkzeug."""
        res = trunkstock_fuer_auftrag("T1", "STK", "Hugo")
        assert res["werkzeug"] == []

    def test_stk_kein_verbrauchsmaterial(self):
        res = trunkstock_fuer_auftrag("T1", "STK", "Hugo")
        assert res["verbrauchsmaterial"] == []

    def test_pm_liefert_messmittel_und_verbrauch(self):
        res = trunkstock_fuer_auftrag("T2", "PM", "Beatmung")
        assert len(res["messmittel"]) > 0
        assert len(res["verbrauchsmaterial"]) > 0

    def test_pm_kein_werkzeug(self):
        res = trunkstock_fuer_auftrag("T2", "PM", "Beatmung")
        assert res["werkzeug"] == []

    def test_repair_liefert_alles(self):
        res = trunkstock_fuer_auftrag("T3", "Repair", "Endoskopie")
        assert len(res["messmittel"]) > 0
        assert len(res["werkzeug"]) > 0
        assert len(res["verbrauchsmaterial"]) > 0

    def test_dokumentation_immer_dabei(self):
        for typ in ("STK", "PM", "Repair"):
            res = trunkstock_fuer_auftrag("T1", typ, "Hugo")
            assert len(res["dokumentation"]) > 0

    def test_vollstaendig_true(self):
        """T1 hat alle Hugo-Messmittel."""
        res = trunkstock_fuer_auftrag("T1", "STK", "Hugo")
        assert res["vollstaendig"] is True
        assert res["fehlende_messmittel"] == []

    def test_vollstaendig_false_fehlende_messmittel(self):
        """T13 hat keine Beatmungs-Messmittel → unvollständig."""
        res = trunkstock_fuer_auftrag("T13", "STK", "Beatmung")
        assert res["vollstaendig"] is False
        assert "MM-BEAT-001" in res["fehlende_messmittel"]
        assert "MM-BEAT-002" in res["fehlende_messmittel"]

    def test_ergebnis_metadaten(self):
        res = trunkstock_fuer_auftrag("T5", "PM", "Neuromonitoring")
        assert res["techniker_id"] == "T5"
        assert res["auftragstyp"] == "PM"
        assert res["produktfamilie"] == "Neuromonitoring"

    def test_hugo_techniker_repair_hat_spezialwerkzeug(self):
        """Hugo-Techniker haben WZ-010 im Werkzeug."""
        res = trunkstock_fuer_auftrag("T10", "Repair", "Hugo")
        wz_nrs = [w["artikel_nr"] for w in res["werkzeug"]]
        assert "WZ-010" in wz_nrs

    def test_unbekannte_familie_leer(self):
        res = trunkstock_fuer_auftrag("T1", "STK", "Fantasie")
        assert res["vollstaendig"] is True  # keine Pflicht → nichts fehlt
        assert res["fehlende_messmittel"] == []
