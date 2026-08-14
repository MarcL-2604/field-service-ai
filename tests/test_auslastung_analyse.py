"""Tests fuer api/auslastung_analyse.py: reale Einsatzhistorie-Auswertung
fuer ALLE Geraete-Cluster (nicht nur Hugo), Basis fuer den
Auslastungs-Zielkorridor 80-95%.

Nutzt die echten Model-Code-Praefixe aus data/model_code_cluster_mapping.json
(MC-HUGO=CLUSTER1_OR, MC-MR8-=CLUSTER2_CARDIAC, MC-8253/MC-840=
CLUSTER3_MONITORING, MC-ELEV/MC-NIM4=SMALL_CAPITAL) als Regressionsbasis --
keine erfundenen Cluster-Zuordnungen.
"""

from datetime import datetime

from api.cluster_mapping import finde_cluster
from api.import_real_data import SMaxEinsatzDauer, SMaxGeschlossenAuftrag
from api.auslastung_analyse import (
    durchschnittlicher_abstand_tage,
    durchschnittsdauer_min,
    einsatzdauer_map,
    einsatzstunden_pro_jahr,
    jobs_je_cluster,
    jobs_je_techniker_und_cluster,
    klassifiziere_korridor,
    auslastung_pct,
)


def _job(mc: str, tech: str = "Marc Liebhardt", datum: str = "01.01.2024, 09:00") -> SMaxGeschlossenAuftrag:
    return SMaxGeschlossenAuftrag(
        auftragsnummer="WO-1", account="Klinikum X", ort="Hamburg",
        model_code=mc, erledigung_datum=datum, techniker=tech,
    )


class TestEinsatzdauerMap:
    def test_nur_positive_mittelwerte(self):
        ed = [
            SMaxEinsatzDauer(model_code="MC-HUGO", mittelwert_min=800, median_min=720),
            SMaxEinsatzDauer(model_code="MC-LEER", mittelwert_min=0, median_min=0),
        ]
        m = einsatzdauer_map(ed)
        assert m == {"MC-HUGO": 800}

    def test_leere_liste_gibt_leeres_dict(self):
        assert einsatzdauer_map([]) == {}


class TestDurchschnittsdauer:
    def test_durchschnitt_ueber_alle_codes(self):
        ed = [
            SMaxEinsatzDauer(model_code="MC-A", mittelwert_min=100, median_min=90),
            SMaxEinsatzDauer(model_code="MC-B", mittelwert_min=200, median_min=180),
        ]
        assert durchschnittsdauer_min(ed) == 150

    def test_ohne_daten_null(self):
        assert durchschnittsdauer_min([]) == 0


class TestJobsJeCluster:
    def test_mehrere_cluster_korrekt_gezaehlt(self):
        jobs = [
            _job("MC-HUGO-3DDOF"), _job("MC-HUGO-123"),
            _job("MC-MR8-AA07"),
            _job("MC-8253001"), _job("MC-840-A"), _job("MC-840"),
            _job("MC-ELEV-1"), _job("MC-NIM4CM01"),
        ]
        z = jobs_je_cluster(jobs, finde_cluster)
        assert z["CLUSTER1_OR"] == 2
        assert z["CLUSTER2_CARDIAC"] == 1
        assert z["CLUSTER3_MONITORING"] == 3
        assert z["SMALL_CAPITAL"] == 2

    def test_unbekannter_code_landet_unter_unbekannt(self):
        z = jobs_je_cluster([_job("MC-VOLLKOMMEN-UNBEKANNT-XYZ")], finde_cluster)
        assert z == {"UNBEKANNT": 1}

    def test_leere_jobliste(self):
        assert jobs_je_cluster([], finde_cluster) == {}


class TestJobsJeTechnikerUndCluster:
    def test_gruppiert_korrekt_nach_techniker(self):
        jobs = [
            _job("MC-HUGO-1", tech="Marc Liebhardt"),
            _job("MC-8253-1", tech="Marc Liebhardt"),
            _job("MC-MR8-AA07", tech="Dirk Häbel"),
        ]
        z = jobs_je_techniker_und_cluster(jobs, finde_cluster)
        assert z["Marc Liebhardt"] == {"CLUSTER1_OR": 1, "CLUSTER3_MONITORING": 1}
        assert z["Dirk Häbel"] == {"CLUSTER2_CARDIAC": 1}

    def test_job_ohne_techniker_wird_ignoriert(self):
        jobs = [_job("MC-HUGO-1", tech="")]
        jobs[0].techniker = None
        z = jobs_je_techniker_und_cluster(jobs, finde_cluster)
        assert z == {}


class TestEinsatzstundenProJahr:
    def test_annualisiert_ueber_beobachtungszeitraum(self):
        """3 Jobs x 120 Min = 360 Min = 6h, ueber 2 Jahre annualisiert = 3h/Jahr."""
        ed = [SMaxEinsatzDauer(model_code="MC-A", mittelwert_min=120, median_min=120)]
        dauer_map = einsatzdauer_map(ed)
        jobs = [_job("MC-A")] * 3
        h = einsatzstunden_pro_jahr(jobs, dauer_map, fallback_min=60, beobachtungszeitraum_jahre=2.0)
        assert h == 3.0

    def test_fallback_dauer_fuer_unbekannten_code(self):
        jobs = [_job("MC-UNBEKANNT")]
        h = einsatzstunden_pro_jahr(jobs, {}, fallback_min=60, beobachtungszeitraum_jahre=1.0)
        assert h == 1.0  # 60 min / 60 = 1h

    def test_zeitraum_null_faellt_auf_ein_jahr_zurueck(self):
        jobs = [_job("MC-A")]
        h = einsatzstunden_pro_jahr(jobs, {}, fallback_min=60, beobachtungszeitraum_jahre=0.0)
        assert h == 1.0

    def test_leere_jobliste_null_stunden(self):
        assert einsatzstunden_pro_jahr([], {}, fallback_min=60, beobachtungszeitraum_jahre=1.0) == 0.0


class TestAuslastungPct:
    def test_volle_kapazitaet_ergibt_100_prozent(self):
        # 32h/Woche x 46 Wochen = 1472h/Jahr
        pct = auslastung_pct(1472.0, kapazitaet_wochenstunden=32.0, arbeitswochen_pro_jahr=46)
        assert pct == 100.0

    def test_halbe_kapazitaet_ergibt_50_prozent(self):
        pct = auslastung_pct(736.0, kapazitaet_wochenstunden=32.0, arbeitswochen_pro_jahr=46)
        assert pct == 50.0

    def test_hugo_ka_reduzierte_kapazitaet(self):
        # 25.6h/Woche x 46 Wochen = 1177.6h/Jahr
        pct = auslastung_pct(1177.6, kapazitaet_wochenstunden=25.6, arbeitswochen_pro_jahr=46)
        assert pct == 100.0

    def test_null_kapazitaet_kein_absturz(self):
        assert auslastung_pct(100.0, kapazitaet_wochenstunden=0.0, arbeitswochen_pro_jahr=46) == 0.0


class TestKlassifiziereKorridor:
    def test_unter_korridor(self):
        assert klassifiziere_korridor(50.0, 80, 95) == "unter"

    def test_im_korridor_untere_grenze(self):
        assert klassifiziere_korridor(80.0, 80, 95) == "im_korridor"

    def test_im_korridor_obere_grenze(self):
        assert klassifiziere_korridor(95.0, 80, 95) == "im_korridor"

    def test_im_korridor_mitte(self):
        assert klassifiziere_korridor(87.5, 80, 95) == "im_korridor"

    def test_ueber_korridor(self):
        assert klassifiziere_korridor(120.0, 80, 95) == "ueber"


class TestDurchschnittlicherAbstandTage:
    def test_bekannte_abstaende(self):
        daten = [datetime(2024, 1, 1), datetime(2024, 1, 11), datetime(2024, 1, 21)]
        assert durchschnittlicher_abstand_tage(daten) == 10.0

    def test_unsortierte_daten_werden_sortiert(self):
        daten = [datetime(2024, 1, 21), datetime(2024, 1, 1), datetime(2024, 1, 11)]
        assert durchschnittlicher_abstand_tage(daten) == 10.0

    def test_weniger_als_zwei_datenpunkte_gibt_none(self):
        assert durchschnittlicher_abstand_tage([datetime(2024, 1, 1)]) is None
        assert durchschnittlicher_abstand_tage([]) is None


class TestRegressionGegenBekannteGrunddaten:
    """Reproduziert (verkleinert) die reale Ist-Zustand-Analyse: Marc
    Liebhardt hat historisch sowohl Hugo- (CLUSTER1_OR) als auch
    Small-Capital-Einsaetze (SMALL_CAPITAL) -- Cluster-Aufschluesselung muss
    beide getrennt ausweisen, nicht vermischen."""

    def test_gemischtes_cluster_profil_eines_technikers(self):
        jobs = [
            _job("MC-HUGO-1", tech="Marc Liebhardt", datum="01.03.2024, 08:00"),
            _job("MC-HUGO-2", tech="Marc Liebhardt", datum="15.06.2024, 08:00"),
            _job("MC-NIM4CM01", tech="Marc Liebhardt", datum="01.01.2024, 08:00"),
            _job("MC-ELEV-1", tech="Marc Liebhardt", datum="01.02.2024, 08:00"),
        ]
        z = jobs_je_techniker_und_cluster(jobs, finde_cluster)
        assert z["Marc Liebhardt"]["CLUSTER1_OR"] == 2
        assert z["Marc Liebhardt"]["SMALL_CAPITAL"] == 2

    def test_stk_jahr_normalisierung_bleibt_unveraendert(self):
        """Regressionsschutz: die bestehende STK/Jahr-Berechnung
        (_berechne_stk_jahr in api/smax_cache.py) wird von dieser neuen
        Auslastungsberechnung nicht angetastet."""
        from api.smax_cache import _berechne_stk_jahr
        assert _berechne_stk_jahr(closed_jobs=92, open_jobs=8, beobachtungszeitraum_jahre=2.75) == round(92 / 2.75 + 8, 2)
