"""
tests/test_cluster_mapping.py
==============================
Tests fuer präfix-basiertes Cluster-Mapping und integrierte map_skill_row-Logik.
"""

import pytest

from api.cluster_mapping import ClusterInfo, finde_cluster
from api.import_real_data import SMaxSkillEintrag, map_skill_row


# ══════════════════════════════════════════════════════════════════════════════
# Cluster-Mapping: Exakter Match
# ══════════════════════════════════════════════════════════════════════════════

class TestExacterMatch:

    def test_illumisite_cluster1_repair_false(self):
        info = finde_cluster("MC-ILLUMISITE")
        assert info == ClusterInfo(cluster="CLUSTER1_OR", repair=False)

    def test_nitron_cluster2_repair_true(self):
        info = finde_cluster("MC-NITRON")
        assert info == ClusterInfo(cluster="CLUSTER2_CARDIAC", repair=True)

    def test_vista_monitoring_repair_false(self):
        info = finde_cluster("MC-VISTA")
        assert info == ClusterInfo(cluster="CLUSTER3_MONITORING", repair=False)

    def test_pm7100pa_monitoring_repair_false(self):
        """MC-PM7100PA ist Einzelcode mit repair=False, Präfix MC-PM7100 hat repair=True."""
        info = finde_cluster("MC-PM7100PA")
        assert info == ClusterInfo(cluster="CLUSTER3_MONITORING", repair=False)

    def test_ft10_hf_chirurgie_repair_true(self):
        info = finde_cluster("MC-FT10")
        assert info == ClusterInfo(cluster="HF_CHIRURGIE", repair=True)

    def test_rapidvac_hf_chirurgie_repair_false(self):
        info = finde_cluster("MC-RAPIDVAC")
        assert info == ClusterInfo(cluster="HF_CHIRURGIE", repair=False)

    def test_840_exact_ist_small_capital(self):
        """MC-840 exakt → SMALL_CAPITAL (repair=False), nicht CLUSTER3 Präfix."""
        info = finde_cluster("MC-840")
        assert info == ClusterInfo(cluster="SMALL_CAPITAL", repair=False)

    def test_cagenhp_exact_ist_small_capital(self):
        """MC-CAGENHP exakt → SMALL_CAPITAL; Präfix MC-CAGENHP → CLUSTER2."""
        info = finde_cluster("MC-CAGENHP")
        assert info == ClusterInfo(cluster="SMALL_CAPITAL", repair=False)

    def test_emprint_exact_ist_small_capital(self):
        info = finde_cluster("MC-EMPRINT")
        assert info == ClusterInfo(cluster="SMALL_CAPITAL", repair=False)

    def test_case_insensitive(self):
        assert finde_cluster("mc-nitron") == ClusterInfo(cluster="CLUSTER2_CARDIAC", repair=True)
        assert finde_cluster("MC-NITRON") == ClusterInfo(cluster="CLUSTER2_CARDIAC", repair=True)
        assert finde_cluster("Mc-Nitron") == ClusterInfo(cluster="CLUSTER2_CARDIAC", repair=True)

    def test_leerzeichen_werden_ignoriert(self):
        assert finde_cluster("  MC-VISTA  ") == ClusterInfo(cluster="CLUSTER3_MONITORING", repair=False)


# ══════════════════════════════════════════════════════════════════════════════
# Cluster-Mapping: Präfix-Match (längster gewinnt)
# ══════════════════════════════════════════════════════════════════════════════

class TestPraefixMatch:

    def test_hugo_prefix_cluster1(self):
        info = finde_cluster("MC-HUGO-123")
        assert info == ClusterInfo(cluster="CLUSTER1_OR", repair=True)

    def test_9735_prefix_cluster1(self):
        info = finde_cluster("MC-9735-A")
        assert info == ClusterInfo(cluster="CLUSTER1_OR", repair=True)

    def test_mr8_prefix_cluster2(self):
        info = finde_cluster("MC-MR8-500")
        assert info == ClusterInfo(cluster="CLUSTER2_CARDIAC", repair=True)

    def test_cagenhp_prefix_mit_suffix_cluster2(self):
        """MC-CAGENHP mit Suffix → Präfix → CLUSTER2 (exakter Match MC-CAGENHP → SMALL_CAPITAL)."""
        info = finde_cluster("MC-CAGENHP-X")
        assert info == ClusterInfo(cluster="CLUSTER2_CARDIAC", repair=True)

    def test_pm7100_prefix_monitoring_repair_true(self):
        """MC-PM7100 als Präfix → repair=True; MC-PM7100PA (exakt) → repair=False."""
        info = finde_cluster("MC-PM7100-BL")
        assert info == ClusterInfo(cluster="CLUSTER3_MONITORING", repair=True)

    def test_840_prefix_cluster3(self):
        """MC-840xyz → Präfix MC-840 → CLUSTER3 (exakt MC-840 → SMALL_CAPITAL)."""
        info = finde_cluster("MC-840-A")
        assert info == ClusterInfo(cluster="CLUSTER3_MONITORING", repair=True)

    def test_scope5_schlaegt_scope(self):
        """MC-SCOPE5-XY → Präfix MC-SCOPE5 (SMALL_CAPITAL) schlägt MC-SCOPE (CLUSTER2)."""
        info = finde_cluster("MC-SCOPE5-XY")
        assert info == ClusterInfo(cluster="SMALL_CAPITAL", repair=False)

    def test_scope_ohne_zahl_cluster2(self):
        info = finde_cluster("MC-SCOPE-ABC")
        assert info == ClusterInfo(cluster="CLUSTER2_CARDIAC", repair=True)

    def test_catheter_aa_repair_false(self):
        info = finde_cluster("MC-AA500")
        assert info == ClusterInfo(cluster="CLUSTER2_CARDIAC", repair=False)

    def test_nim4_prefix_small_capital(self):
        info = finde_cluster("MC-NIM4-PRO")
        assert info == ClusterInfo(cluster="SMALL_CAPITAL", repair=False)

    def test_ph_prefix_small_capital(self):
        """MC-PH → SMALL_CAPITAL; MC-PHCATHETER → CLUSTER2 (Präfix, exakter match)."""
        info = finde_cluster("MC-PH-100")
        assert info == ClusterInfo(cluster="SMALL_CAPITAL", repair=False)

    def test_phcatheter_prefix_cluster2(self):
        info = finde_cluster("MC-PHCATHETER-A")
        assert info == ClusterInfo(cluster="CLUSTER2_CARDIAC", repair=False)

    def test_hrm_prefix_small_capital(self):
        info = finde_cluster("MC-HRM-100")
        assert info == ClusterInfo(cluster="SMALL_CAPITAL", repair=False)

    def test_hrmcatheter_prefix_cluster2(self):
        info = finde_cluster("MC-HRMCATHETER-A")
        assert info == ClusterInfo(cluster="CLUSTER2_CARDIAC", repair=False)

    def test_f104_schlaegt_f10(self):
        """MC-F104-X → Präfix MC-F104 schlägt MC-F10 (beide SMALL_CAPITAL aber Länge entscheidet)."""
        info = finde_cluster("MC-F104-X")
        assert info == ClusterInfo(cluster="SMALL_CAPITAL", repair=False)

    def test_om_prefix_small_capital(self):
        info = finde_cluster("MC-OM-200")
        assert info == ClusterInfo(cluster="SMALL_CAPITAL", repair=False)

    def test_ku_prefix_small_capital(self):
        info = finde_cluster("MC-KU-XYZ")
        assert info == ClusterInfo(cluster="SMALL_CAPITAL", repair=False)


# ══════════════════════════════════════════════════════════════════════════════
# Cluster-Mapping: Kein Match
# ══════════════════════════════════════════════════════════════════════════════

class TestKeinMatch:

    def test_unbekannter_code_gibt_none(self):
        assert finde_cluster("MC-UNBEKANNT-9999") is None

    def test_leerer_code_gibt_none(self):
        assert finde_cluster("") is None

    def test_ohne_mc_prefix_gibt_none(self):
        assert finde_cluster("HUGO-123") is None

    def test_mc_allein_gibt_none(self):
        assert finde_cluster("MC-") is None


# ══════════════════════════════════════════════════════════════════════════════
# Integration: map_skill_row mit Cluster-Logik
# ══════════════════════════════════════════════════════════════════════════════

class TestMapSkillRowMitCluster:

    def test_ja_cluster_repair_true_ergibt_pm_repair(self):
        eintrag = map_skill_row("MC-HUGO-123", "Hans Müller", "JA")
        assert eintrag.qualifikation == "PM+Repair"
        assert eintrag.cluster == "CLUSTER1_OR"
        assert eintrag.repair is True

    def test_ja_cluster_repair_false_ergibt_pm(self):
        eintrag = map_skill_row("MC-ILLUMISITE", "Hans Müller", "JA")
        assert eintrag.qualifikation == "PM"
        assert eintrag.cluster == "CLUSTER1_OR"
        assert eintrag.repair is False

    def test_ja_kein_cluster_ergibt_pm_ohne_cluster(self):
        eintrag = map_skill_row("MC-12345", "Hans Müller", "JA")
        assert eintrag.qualifikation == "PM"
        assert eintrag.cluster is None
        assert eintrag.repair is None

    def test_nein_ergibt_none_unabhaengig_von_cluster(self):
        eintrag = map_skill_row("MC-HUGO-123", "Hans Müller", "NEIN")
        assert eintrag.qualifikation is None
        assert eintrag.cluster is None

    def test_leer_ergibt_none(self):
        eintrag = map_skill_row("MC-NITRON", "Hans Müller", "")
        assert eintrag.qualifikation is None

    def test_pm7100pa_ja_ergibt_pm_nicht_pm_repair(self):
        """PM7100PA ist Einzelcode mit repair=False → PM, obwohl Präfix repair=True."""
        eintrag = map_skill_row("MC-PM7100PA", "Hans Müller", "JA")
        assert eintrag.qualifikation == "PM"
        assert eintrag.cluster == "CLUSTER3_MONITORING"
        assert eintrag.repair is False

    def test_pm7100_mit_suffix_ja_ergibt_pm_repair(self):
        eintrag = map_skill_row("MC-PM7100-BL", "Hans Müller", "JA")
        assert eintrag.qualifikation == "PM+Repair"
        assert eintrag.cluster == "CLUSTER3_MONITORING"
        assert eintrag.repair is True

    def test_hf_chirurgie_repair_true(self):
        eintrag = map_skill_row("MC-FT10", "Hans Müller", "JA")
        assert eintrag.qualifikation == "PM+Repair"
        assert eintrag.cluster == "HF_CHIRURGIE"

    def test_hf_chirurgie_repair_false(self):
        eintrag = map_skill_row("MC-RAPIDVAC", "Hans Müller", "JA")
        assert eintrag.qualifikation == "PM"
        assert eintrag.cluster == "HF_CHIRURGIE"
        assert eintrag.repair is False

    def test_ergebnis_typ(self):
        assert isinstance(map_skill_row("MC-HUGO-123", "T", "JA"), SMaxSkillEintrag)
