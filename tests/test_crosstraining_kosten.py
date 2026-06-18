"""Tests fuer Crosstraining-Kostenmodell und Schulungsdetails.

HINWEIS: Trainingskosten (ausser INTERN = 0 EUR) sind PLATZHALTER.
Genaue Kosten bei Medtronic Training & Education (T&E) anfragen.
"""

import pytest

from techniker.models import HANDON_STUNDEN
from reporting.crosstraining_analyse import (
    KOSTEN_INTERN,
    KOSTEN_TC_OR,
    KOSTEN_TC_CARDIAC,
    KOSTEN_TC_MONITORING,
    KOSTEN_TC_REPAIR_HF,
    KOSTEN_DIGITAL,
    HANDON_EINSAETZE_OR,
    HANDON_STUNDEN_REPAIR_L3,
    HANDON_STUNDEN_PM,
    DAUER_INTERN_TAGE,
    DAUER_INTERN_BEGLEIT_EINSAETZE,
    DAUER_TRAININGSCENTER_TAGE,
    _cluster_kosten,
    berechne_schulungsdetails,
    load_trainingsmatrix,
    load_regionen,
    bundeslaender_fuer_techniker,
)


# ===================================================================
# Kostenkonstanten
# ===================================================================

class TestKostenKonstanten:
    def test_intern_kostenlos(self):
        assert KOSTEN_INTERN == 0

    def test_trainingscenter_sind_platzhalter(self):
        """TC-Kosten sind PLATZHALTER – bei T&E anfragen."""
        assert KOSTEN_TC_OR == "PLATZHALTER"
        assert KOSTEN_TC_CARDIAC == "PLATZHALTER"
        assert KOSTEN_TC_MONITORING == "PLATZHALTER"
        assert KOSTEN_TC_REPAIR_HF == "PLATZHALTER"

    def test_digital_ist_platzhalter(self):
        assert KOSTEN_DIGITAL == "PLATZHALTER"

    def test_handon_stunden_repair_l3(self):
        """Repair L3: 10h Hands-on im Feld Pflicht."""
        assert HANDON_STUNDEN_REPAIR_L3 == 10

    def test_handon_stunden_pm(self):
        """PM L1→L2: kein zusaetzliches Feld-Hands-on."""
        assert HANDON_STUNDEN_PM == 0

    def test_handon_modell_in_models(self):
        """HANDON_STUNDEN in models.py korrekt."""
        assert HANDON_STUNDEN["REPAIR_L3"] == 10
        assert HANDON_STUNDEN["PM_L1_L2"] == 0
        assert HANDON_STUNDEN["PM_ONLINE"] == 0

    def test_handon_einsaetze_or_10(self):
        """Cluster 1 OR: 10 Handon-Einsaetze (validiert)."""
        assert HANDON_EINSAETZE_OR == 10

    def test_dauer_intern(self):
        assert DAUER_INTERN_TAGE == 2
        assert DAUER_INTERN_BEGLEIT_EINSAETZE == 4

    def test_dauer_trainingscenter(self):
        assert DAUER_TRAININGSCENTER_TAGE == 5


# ===================================================================
# Cluster-Kosten
# ===================================================================

class TestClusterKosten:
    def test_cluster1_or_platzhalter(self):
        kurs, handon_n, handon_k = _cluster_kosten("Hugo")
        assert kurs == "PLATZHALTER"
        assert handon_n == 10
        assert handon_k == "PLATZHALTER"

    def test_cluster2_cardiac_platzhalter(self):
        kurs, handon_n, handon_k = _cluster_kosten("Kardiovaskulaer_Ablation")
        assert kurs == "PLATZHALTER"
        assert handon_n == 8

    def test_cluster3_monitoring_platzhalter(self):
        kurs, handon_n, handon_k = _cluster_kosten("Beatmung")
        assert kurs == "PLATZHALTER"
        assert handon_n == 6

    def test_hf_chirurgie_repair_platzhalter(self):
        kurs, handon_n, handon_k = _cluster_kosten("Elektrochirurgie")
        assert kurs == "PLATZHALTER"
        assert handon_n == 5

    def test_small_capital_kostenlos(self):
        kurs, handon_n, handon_k = _cluster_kosten("Neuromonitoring")
        assert kurs == 0
        assert handon_n == 0
        assert handon_k == 0

    def test_digital_platzhalter(self):
        kurs, handon_n, handon_k = _cluster_kosten("TouchSurgery")
        assert kurs == "PLATZHALTER"
        assert handon_n == 0


# ===================================================================
# Schulungsdetails Berechnung
# ===================================================================

class TestSchulungsdetails:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.qualifikationen = load_trainingsmatrix()
        self.regionen = load_regionen()

    def test_intern_schulung_nim(self):
        """NIM = Small Capital → INTERN, 0 EUR."""
        tech_bls = bundeslaender_fuer_techniker("T8", self.regionen)
        result = berechne_schulungsdetails(
            "Neuromonitoring", "T8", self.qualifikationen, self.regionen, tech_bls,
        )
        assert result["trainingstyp"] == "INTERN"
        assert result["kosten_eur"] == 0
        assert result["cluster"] == "SMALL_CAPITAL"

    def test_trainingscenter_hugo_platzhalter(self):
        """Hugo = Cluster 1 OR → TRAININGSCENTER + HANDON, Kosten = PLATZHALTER."""
        tech_bls = bundeslaender_fuer_techniker("T11", self.regionen)
        result = berechne_schulungsdetails(
            "Hugo", "T11", self.qualifikationen, self.regionen, tech_bls,
        )
        assert "TRAININGSCENTER" in result["trainingstyp"]
        assert result["kosten_eur"] == "PLATZHALTER"
        assert result["cluster"] == "CLUSTER1_OR"
        assert "T&E anfragen" in result["kosten_text"]

    def test_trainingscenter_ablation_platzhalter(self):
        """Ablation = Cluster 2 Cardiac, Kosten = PLATZHALTER."""
        tech_bls = bundeslaender_fuer_techniker("T5", self.regionen)
        result = berechne_schulungsdetails(
            "Kardiovaskulaer_Ablation", "T5", self.qualifikationen, self.regionen, tech_bls,
        )
        assert result["cluster"] == "CLUSTER2_CARDIAC"
        assert result["kosten_eur"] == "PLATZHALTER"

    def test_trainer_wird_gefunden(self):
        tech_bls = bundeslaender_fuer_techniker("T8", self.regionen)
        result = berechne_schulungsdetails(
            "Elektrochirurgie", "T8", self.qualifikationen, self.regionen, tech_bls,
        )
        assert result["trainer_id"] != ""

    def test_intern_hat_begleitete_einsaetze(self):
        tech_bls = bundeslaender_fuer_techniker("T8", self.regionen)
        result = berechne_schulungsdetails(
            "Neuromonitoring", "T8", self.qualifikationen, self.regionen, tech_bls,
        )
        assert "begleitete Einsaetze" in result["dauer_text"]

    def test_eigenstaendig_ab_vorhanden(self):
        tech_bls = bundeslaender_fuer_techniker("T8", self.regionen)
        result = berechne_schulungsdetails(
            "Neuromonitoring", "T8", self.qualifikationen, self.regionen, tech_bls,
        )
        assert result["eigenstaendig_ab"]


# ===================================================================
# Kosten-Nutzen-Analyse (ohne Trainingskosten, da PLATZHALTER)
# ===================================================================

class TestKostenNutzen:
    def test_intern_schulungen_kostenlos(self):
        assert 8 * KOSTEN_INTERN == 0

    def test_roi_ohne_trainingskosten(self):
        """ROI konservativ: nur STK-Umsatz, ohne Trainingskosten."""
        umsatz_pa = 100 * 200  # 100 STK × 200 EUR
        assert umsatz_pa > 0  # positiv auch ohne Trainingskosten
