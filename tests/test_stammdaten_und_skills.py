"""
tests/test_stammdaten_und_skills.py
====================================
Tests für:
  - TechnikerStammdaten (Wohnort, PLZ, Koordinaten, Hugo-KA)
  - TechnikerSkillmatrix (Level + Repair, STK=PM)
  - Import-Helper-Funktionen
"""

import pytest
from pydantic import ValidationError

from techniker.stammdaten import (
    TechnikerStammdaten,
    techniker_aus_csv_zeile,
    HUGO_KA_IDS,
)
from techniker.skill_matrix import (
    ClusterSkill,
    TechnikerSkillmatrix,
    skillmatrix_aus_csv_zeile,
)


# ══════════════════════════════════════════════════════════════════════════════
# TechnikerStammdaten
# ══════════════════════════════════════════════════════════════════════════════

class TestTechnikerStammdaten:

    def _basis(self, **kwargs) -> dict:
        return {
            "tech_id": "T10",
            "nachname": "Liebhardt",
            "vorname": "Marc",
            "plz": "72336",
            "ort": "Balingen",
            **kwargs,
        }

    def test_erstellt_korrekt(self):
        t = TechnikerStammdaten(**self._basis())
        assert t.tech_id == "T10"
        assert t.nachname == "Liebhardt"
        assert t.plz == "72336"

    def test_hugo_ka_automatisch(self):
        """T1, T6, T10, T11 sollen automatisch hugo_ka=True bekommen."""
        for tid in HUGO_KA_IDS:
            t = TechnikerStammdaten(**self._basis(tech_id=tid))
            assert t.hugo_ka is True, f"{tid} sollte Hugo-KA sein"

    def test_kein_hugo_ka(self):
        t = TechnikerStammdaten(**self._basis(tech_id="T2"))
        assert t.hugo_ka is False

    def test_effektive_kapazitaet_hugo(self):
        t = TechnikerStammdaten(**self._basis(tech_id="T10", kapazitaet_h=32.0))
        assert t.effektive_kapazitaet_h == pytest.approx(25.6)
        assert t.hugo_reserve_h == pytest.approx(6.4)

    def test_effektive_kapazitaet_normal(self):
        t = TechnikerStammdaten(**self._basis(tech_id="T2", kapazitaet_h=32.0))
        assert t.effektive_kapazitaet_h == 32.0
        assert t.hugo_reserve_h == 0.0

    def test_name_voll(self):
        t = TechnikerStammdaten(**self._basis())
        assert t.name_voll == "Marc Liebhardt"

    def test_plz_validierung_ungueltig(self):
        with pytest.raises(ValidationError):
            TechnikerStammdaten(**self._basis(plz="1234"))   # nur 4 Stellen
        with pytest.raises(ValidationError):
            TechnikerStammdaten(**self._basis(plz="ABCDE"))  # keine Ziffern

    def test_tech_id_format(self):
        with pytest.raises(ValidationError):
            TechnikerStammdaten(**self._basis(tech_id="Techniker10"))

    def test_haversine_balingen_hamburg(self):
        t = TechnikerStammdaten(**self._basis(lat=48.2752, lon=8.8556))
        # Hamburg UKE ca. ~650 km Luftlinie von Balingen
        dist = t.distanz_km(53.5985, 9.8267)
        assert dist is not None
        assert 580 < dist < 650

    def test_fahrzeit_berechnung(self):
        t = TechnikerStammdaten(**self._basis(lat=48.2752, lon=8.8556))
        ft = t.fahrzeit_min(53.5985, 9.8267)
        assert ft is not None
        assert ft > 300  # > 5 Stunden nach Hamburg

    def test_keine_koordinaten(self):
        t = TechnikerStammdaten(**self._basis())
        assert t.hat_koordinaten is False
        assert t.distanz_km(53.0, 9.0) is None
        assert t.fahrzeit_min(53.0, 9.0) is None

    def test_plz_naehe(self):
        t = TechnikerStammdaten(**self._basis(plz="72336"))  # Balingen
        assert t.plz_naehe("72336") is True    # gleiche PLZ
        assert t.plz_naehe("72379") is True    # benachbart (72...)
        assert t.plz_naehe("20251") is False   # Hamburg — weit weg

    def test_kapazitaet_max_arbzg(self):
        with pytest.raises(ValidationError):
            TechnikerStammdaten(**self._basis(kapazitaet_h=46.0))  # > 45h ArbZG


class TestTechnikerAusCsvZeile:

    def test_volle_zeile(self):
        zeile = {
            "tech_id": "T10",
            "nachname": "Liebhardt",
            "vorname": "Marc",
            "strasse": "Zollernstr. 7",
            "plz": "72336",
            "ort": "Balingen",
            "bundesland": "Baden-Württemberg",
            "lat": "48.2752",
            "lon": "8.8556",
            "telefon": "0151-111",
            "email": "m.liebhardt@medtronic.com",
            "kapazitaet_h": "32",
            "hugo_ka": "j",
        }
        t = techniker_aus_csv_zeile(zeile)
        assert t.tech_id == "T10"
        assert t.lat == pytest.approx(48.2752)
        assert t.hugo_ka is True

    def test_minimale_zeile(self):
        zeile = {"tech_id": "T3", "nachname": "Müller", "vorname": "Klaus", "plz": "99423", "ort": "Weimar"}
        t = techniker_aus_csv_zeile(zeile)
        assert t.tech_id == "T3"
        assert t.hat_koordinaten is False

    def test_hugo_ka_verschiedene_werte(self):
        for val in ("j", "ja", "yes", "true", "1", "J", "JA"):
            z = {"tech_id": "T2", "nachname": "X", "vorname": "Y", "plz": "12345", "ort": "Stadt", "hugo_ka": val}
            t = techniker_aus_csv_zeile(z)
            assert t.hugo_ka is True, f"hugo_ka={val!r} sollte True ergeben"


# ══════════════════════════════════════════════════════════════════════════════
# ClusterSkill
# ══════════════════════════════════════════════════════════════════════════════

class TestClusterSkill:

    def test_voll_qualifiziert(self):
        s = ClusterSkill(level="L3", repair="L3")
        assert s.kann_stk is True
        assert s.kann_pm is True
        assert s.kann_repair is True
        assert s.ist_qualifiziert is True
        assert s.ist_vollstaendig is True

    def test_nur_level(self):
        s = ClusterSkill(level="L2", repair=None)
        assert s.kann_stk is True
        assert s.kann_pm is True
        assert s.kann_repair is False
        assert s.ist_vollstaendig is False

    def test_kein_level(self):
        s = ClusterSkill()
        assert s.ist_qualifiziert is False
        assert s.kann_stk is False
        assert s.kann_repair is False


# ══════════════════════════════════════════════════════════════════════════════
# TechnikerSkillmatrix
# ══════════════════════════════════════════════════════════════════════════════

class TestTechnikerSkillmatrix:

    def _t10(self) -> TechnikerSkillmatrix:
        """T10 Balingen — Hugo KA, C1 L3+Repair, C2 L2, HF-Chir L2+Repair."""
        return TechnikerSkillmatrix(
            tech_id="T10",
            hugo_ka=True,
            c1_or=ClusterSkill(level="L3", repair="L3"),
            c2_cardiac=ClusterSkill(level="L2", repair=None),
            c3_monitoring=ClusterSkill(level="L2", repair=None),
            c4_digital=ClusterSkill(level="L2", repair=None),
            small_capital=ClusterSkill(level="L2", repair=None),
            hf_chirurgie=ClusterSkill(level="L2", repair="L3"),
        )

    def test_kann_auftrag_stk(self):
        t = self._t10()
        assert t.kann_auftrag("c1_or", "STK") is True
        assert t.kann_auftrag("c2_cardiac", "STK") is True

    def test_kann_auftrag_pm_gleich_stk(self):
        """STK = PM — gleiche Prüfung."""
        t = self._t10()
        assert t.kann_auftrag("c1_or", "PM") is True
        assert t.kann_auftrag("c2_cardiac", "PM") is True

    def test_kann_repair(self):
        t = self._t10()
        assert t.kann_auftrag("c1_or", "REPAIR") is True
        assert t.kann_auftrag("c2_cardiac", "REPAIR") is False   # kein Repair-Level

    def test_hf_chirurgie_sonderfall(self):
        t = self._t10()
        assert t.kann_auftrag("hf_chirurgie", "STK") is True    # L2 reicht
        assert t.kann_auftrag("hf_chirurgie", "REPAIR") is True  # L3 vorhanden

    def test_digital_kein_repair(self):
        """CLUSTER4_DIGITAL hat nie Repair — auch wenn CSV das setzt."""
        sm = TechnikerSkillmatrix(
            tech_id="T5",
            c4_digital=ClusterSkill(level="L2", repair="L3"),  # wird ignoriert
        )
        assert sm.c4_digital.repair is None
        assert sm.kann_auftrag("c4_digital", "REPAIR") is False

    def test_small_capital_kein_repair(self):
        sm = TechnikerSkillmatrix(
            tech_id="T5",
            small_capital=ClusterSkill(level="L2", repair="L3"),  # wird ignoriert
        )
        assert sm.small_capital.repair is None

    def test_kompetenz_score_voll(self):
        t = self._t10()
        assert t.kompetenz_score("c1_or", "STK") == 1.0
        assert t.kompetenz_score("c1_or", "REPAIR") == 1.0

    def test_kompetenz_score_kein_repair(self):
        t = self._t10()
        # C2 hat Level aber kein Repair → 0.6 (Notfall)
        assert t.kompetenz_score("c2_cardiac", "REPAIR") == pytest.approx(0.6)

    def test_kompetenz_score_nicht_qualifiziert(self):
        t = TechnikerSkillmatrix(tech_id="T8")  # alle leer
        assert t.kompetenz_score("c1_or", "STK") == 0.0
        assert t.kompetenz_score("c1_or", "REPAIR") == 0.0

    def test_qualifizierte_cluster(self):
        t = self._t10()
        qual = t.qualifizierte_cluster()
        assert "c1_or" in qual
        assert "c2_cardiac" in qual

    def test_crosstraining_luecken(self):
        t = self._t10()
        luecken = t.crosstraining_luecken()
        # c2_cardiac hat kein Repair → Lücke
        repair_luecken = [luecke for luecke in luecken if luecke["fehlt"] == "Repair-Training (L3)"]
        assert any(luecke["cluster"] == "c2_cardiac" for luecke in repair_luecken)

    def test_alias_cluster_ids(self):
        """Flexible Cluster-ID-Erkennung."""
        t = self._t10()
        assert t.kann_auftrag("CLUSTER1_OR", "STK") is True
        assert t.kann_auftrag("c1", "STK") is True
        assert t.kann_auftrag("cluster1_or", "STK") is True


class TestSkillmatrixAusCsvZeile:

    def test_volle_zeile(self):
        zeile = {
            "tech_id": "T10",
            "name": "Liebhardt Marc",
            "plz": "72336",
            "hugo_ka": "j",
            "cert_bis": "2027-06-30",
            "c1_level": "L3", "c1_repair": "L3",
            "c2_level": "L2", "c2_repair": "",
            "c3_level": "L2", "c3_repair": "",
            "c4_level": "L2",
            "cs_level": "L2",
            "ch_level": "L2", "ch_repair": "L3",
        }
        sm = skillmatrix_aus_csv_zeile(zeile)
        assert sm.tech_id == "T10"
        assert sm.c1_or.level == "L3"
        assert sm.c1_or.repair == "L3"
        assert sm.c2_cardiac.repair is None
        assert sm.hf_chirurgie.repair == "L3"
        assert sm.hugo_ka is True

    def test_ungueltige_level_werden_none(self):
        zeile = {
            "tech_id": "T2", "name": "Schmidt", "plz": "78564",
            "c1_level": "L4",   # ungültig → None
            "c2_level": "L2",
        }
        sm = skillmatrix_aus_csv_zeile(zeile)
        assert sm.c1_or.level is None    # L4 nicht erlaubt
        assert sm.c2_cardiac.level == "L2"

    def test_leere_zeile(self):
        zeile = {"tech_id": "T8", "name": "Meier"}
        sm = skillmatrix_aus_csv_zeile(zeile)
        assert sm.tech_id == "T8"
        assert sm.c1_or.ist_qualifiziert is False
