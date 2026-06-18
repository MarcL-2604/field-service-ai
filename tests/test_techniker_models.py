import pytest
from techniker.models import (
    Auslastung,
    Qualifikationslevel,
    Techniker,
    TechnikerTyp,
    Trainingsmatrix,
    TrainingsTyp,
    SMALL_CAPITAL,
    BIG_CAPITAL_CLUSTER1_OR,
    BIG_CAPITAL_CLUSTER2_CARDIAC,
    CLUSTER3_MONITORING,
    trainingstyp_fuer_familie,
    produkt_cluster,
    mindest_level_fuer,
)


class TestQualifikationslevel:
    def test_selbststaendig_ist_einsetzbar(self):
        assert Qualifikationslevel.SELBSTSTAENDIG.einsetzbar()

    def test_trainer_ist_einsetzbar(self):
        assert Qualifikationslevel.TRAINER.einsetzbar()

    def test_assistenz_nicht_einsetzbar(self):
        assert not Qualifikationslevel.ASSISTENZ.einsetzbar()

    def test_keine_nicht_einsetzbar(self):
        assert not Qualifikationslevel.KEINE.einsetzbar()


class TestTrainingsmatrix:
    def test_fehlende_geraeteklasse_gibt_keine(self):
        matrix = Trainingsmatrix()
        assert matrix.level("UNBEKANNT") == Qualifikationslevel.KEINE

    def test_einsetzbar_ab_selbststaendig(self):
        matrix = Trainingsmatrix(qualifikationen={"CRM_ICD": Qualifikationslevel.SELBSTSTAENDIG})
        assert matrix.ist_einsetzbar("CRM_ICD")

    def test_nicht_einsetzbar_bei_assistenz(self):
        matrix = Trainingsmatrix(qualifikationen={"CRM_ICD": Qualifikationslevel.ASSISTENZ})
        assert not matrix.ist_einsetzbar("CRM_ICD")

    def test_qualifizierte_klassen_filtert_korrekt(self):
        matrix = Trainingsmatrix(
            qualifikationen={
                "CRM_ICD": Qualifikationslevel.SELBSTSTAENDIG,
                "NEURO_DBS": Qualifikationslevel.ASSISTENZ,
                "DIABETES_CGM": Qualifikationslevel.TRAINER,
            }
        )
        result = matrix.qualifizierte_klassen()
        assert "CRM_ICD" in result
        assert "DIABETES_CGM" in result
        assert "NEURO_DBS" not in result


class TestAuslastung:
    def test_auslastungsgrad_berechnung(self):
        a = Auslastung(kapazitaet_stunden=40.0, geplante_stunden=30.0)
        assert a.auslastungsgrad == pytest.approx(0.75)

    def test_freie_stunden(self):
        a = Auslastung(kapazitaet_stunden=40.0, geplante_stunden=30.0)
        assert a.freie_stunden == pytest.approx(10.0)

    def test_ueberauslastung_nicht_erlaubt(self):
        with pytest.raises(ValueError):
            Auslastung(kapazitaet_stunden=40.0, geplante_stunden=50.0)


class TestTechnikerTyp:
    def test_standard_default(self):
        t = Techniker(smax_id="X", name="X")
        assert t.techniker_typ == TechnikerTyp.STANDARD

    def test_hugo_key_account(self):
        t = Techniker(smax_id="X", name="X",
                      techniker_typ=TechnikerTyp.HUGO_KEY_ACCOUNT)
        assert t.ist_hugo_key_account

    def test_standard_not_hugo(self):
        t = Techniker(smax_id="X", name="X")
        assert not t.ist_hugo_key_account

    def test_key_account_not_hugo(self):
        t = Techniker(smax_id="X", name="X",
                      techniker_typ=TechnikerTyp.KEY_ACCOUNT)
        assert not t.ist_hugo_key_account


class TestTechniker:
    def _make_techniker(self, **kwargs) -> Techniker:
        defaults = dict(smax_id="T001", name="Max Mustermann")
        return Techniker(**{**defaults, **kwargs})

    def test_einsatzgebiet_plz_praefix_match(self):
        t = self._make_techniker(einsatzgebiet_plz=["80", "81"])
        assert t.ist_im_einsatzgebiet("80331")
        assert t.ist_im_einsatzgebiet("81369")
        assert not t.ist_im_einsatzgebiet("70173")

    def test_leeres_einsatzgebiet_ist_bundesweit(self):
        t = self._make_techniker(einsatzgebiet_plz=[])
        assert t.ist_im_einsatzgebiet("10115")
        assert t.ist_im_einsatzgebiet("99999")

    def test_ist_einsetzbar_delegiert_an_matrix(self):
        matrix = Trainingsmatrix(qualifikationen={"CRM_ICD": Qualifikationslevel.SELBSTSTAENDIG})
        t = self._make_techniker(trainingsmatrix=matrix)
        assert t.ist_einsetzbar_fuer("CRM_ICD")
        assert not t.ist_einsetzbar_fuer("NEURO_DBS")


# ---------------------------------------------------------------------------
# TrainingsTyp und trainingstyp_fuer_familie
# ---------------------------------------------------------------------------

class TestTrainingsTyp:
    def test_enum_werte(self):
        assert TrainingsTyp.INTERN == "INTERN"
        assert TrainingsTyp.TRAININGSCENTER == "TRAININGSCENTER"
        assert TrainingsTyp.DIGITAL == "DIGITAL"

    def test_small_capital_ist_intern(self):
        for pf in ["Neuromonitoring", "Neurophysiologie", "Energie",
                    "Kardiovaskulaer"]:
            assert trainingstyp_fuer_familie(pf) == TrainingsTyp.INTERN, (
                f"{pf} sollte INTERN sein"
            )

    def test_hf_chirurgie_ist_intern(self):
        for pf in ["HF_Chirurgie", "Elektrochirurgie"]:
            assert trainingstyp_fuer_familie(pf) == TrainingsTyp.INTERN, (
                f"{pf} sollte INTERN sein"
            )

    def test_big_capital_ist_trainingscenter(self):
        for pf in ["Hugo", "Navigation", "Wirbelsaeule",
                    "Kardiovaskulaer_Ablation"]:
            assert trainingstyp_fuer_familie(pf) == TrainingsTyp.TRAININGSCENTER, (
                f"{pf} sollte TRAININGSCENTER sein"
            )

    def test_monitoring_ist_trainingscenter(self):
        for pf in ["Beatmung", "Capnografie", "Endoskopie"]:
            assert trainingstyp_fuer_familie(pf) == TrainingsTyp.TRAININGSCENTER, (
                f"{pf} sollte TRAININGSCENTER sein"
            )

    def test_digital_ist_digital(self):
        assert trainingstyp_fuer_familie("TouchSurgery") == TrainingsTyp.DIGITAL

    def test_unbekannte_familie_ist_intern(self):
        assert trainingstyp_fuer_familie("Unbekannt") == TrainingsTyp.INTERN

    def test_listen_nicht_leer(self):
        assert len(SMALL_CAPITAL) > 0
        assert len(BIG_CAPITAL_CLUSTER1_OR) > 0
        assert len(BIG_CAPITAL_CLUSTER2_CARDIAC) > 0
        assert len(CLUSTER3_MONITORING) > 0

    def test_keine_ueberschneidung_cluster1_cluster2(self):
        assert not set(BIG_CAPITAL_CLUSTER1_OR) & set(BIG_CAPITAL_CLUSTER2_CARDIAC)


class TestMindestLevel:
    """Tests fuer mindest_level_fuer (Kombination Produktfamilie + Auftragstyp)."""

    def test_small_capital_stk_l2(self):
        for pf in ["Neuromonitoring", "Programmer", "ACT", "Kardiovaskulaer_IPC"]:
            assert mindest_level_fuer(pf, "STK") == 2

    def test_small_capital_repair_l3(self):
        for pf in ["Neuromonitoring", "Programmer"]:
            assert mindest_level_fuer(pf, "Repair") == 3

    def test_hf_chirurgie_stk_l2(self):
        """HF_Chirurgie STK → L2 reicht."""
        assert mindest_level_fuer("HF_Chirurgie", "STK") == 2
        assert mindest_level_fuer("Elektrochirurgie", "STK") == 2

    def test_hf_chirurgie_pm_l2(self):
        """HF_Chirurgie PM → L2 reicht."""
        assert mindest_level_fuer("HF_Chirurgie", "PM") == 2
        assert mindest_level_fuer("Elektrochirurgie", "PM") == 2

    def test_hf_chirurgie_repair_l3(self):
        """HF_Chirurgie Repair → L3 Pflicht!"""
        assert mindest_level_fuer("HF_Chirurgie", "Repair") == 3
        assert mindest_level_fuer("Elektrochirurgie", "Repair") == 3

    def test_big_capital_or_immer_l3(self):
        for pf in ["Hugo", "Navigation", "Wirbelsaeule"]:
            for typ in ["STK", "PM", "Repair"]:
                assert mindest_level_fuer(pf, typ) == 3

    def test_monitoring_stk_l2(self):
        assert mindest_level_fuer("Beatmung", "STK") == 2
        assert mindest_level_fuer("Capnografie", "STK") == 2

    def test_monitoring_repair_l3(self):
        assert mindest_level_fuer("Beatmung", "Repair") == 3

    def test_digital_immer_l2(self):
        assert mindest_level_fuer("TouchSurgery", "STK") == 2
        assert mindest_level_fuer("TouchSurgery", "Repair") == 2


class TestProduktCluster:
    def test_hugo_ist_cluster1_or(self):
        assert produkt_cluster("Hugo") == "CLUSTER1_OR"

    def test_ablation_ist_cluster2_cardiac(self):
        assert produkt_cluster("Kardiovaskulaer_Ablation") == "CLUSTER2_CARDIAC"

    def test_beatmung_ist_cluster3_monitoring(self):
        assert produkt_cluster("Beatmung") == "CLUSTER3_MONITORING"

    def test_touchsurgery_ist_cluster4(self):
        assert produkt_cluster("TouchSurgery") == "CLUSTER4_DIGITAL"

    def test_hf_chirurgie_sonderfall(self):
        assert produkt_cluster("HF_Chirurgie") == "SMALL_CAPITAL_MIT_REPAIR"
        assert produkt_cluster("Elektrochirurgie") == "SMALL_CAPITAL_MIT_REPAIR"

    def test_nim_ist_small_capital(self):
        assert produkt_cluster("Neuromonitoring") == "SMALL_CAPITAL"

    def test_unbekannt_ist_small_capital(self):
        assert produkt_cluster("Unbekannt") == "SMALL_CAPITAL"
