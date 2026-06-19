"""Tests fuer config.py: Zentrale Konstanten korrekt importiert und konsistent."""

from config import (
    PLANUNGSHORIZONT_WOCHEN,
    PLANUNGSHORIZONT_MIN_WOCHEN,
    PLANUNGSHORIZONT_MAX_WOCHEN,
    UMPLANUNGS_PRIORITAETEN,
    STK_PM_FAELLIGKEIT_MONATSGENAU,
    STK_PM_TOLERANZ_TAGE_VOR,
    STK_PM_TOLERANZ_TAGE_NACH,
    STK_PM_AUSNAHME_LETZTER_WERKTAG,
    STK_PM_ZYKLEN_MONATE,
    OP_KLINIK_TAGE,
    MAX_UEBERNACHTUNGEN_HUGO,
    LETZTER_AUSSENEINSATZ_WOCHENTAG,
    KEIN_WOCHENENDEINSATZ,
)
from config import (
    SCORING_KOMPETENZ,
    SCORING_FAHRZEIT,
    SCORING_AUSLASTUNG,
    HAVERSINE_UMWEG_FAKTOR,
    ARBZG_MAX_STUNDEN,
    AUSSENDIENST_STUNDEN,
    FREITAG_NUR_HOME_OFFICE,
    WARNUNG_STUNDEN,
    AUSSCHLUSS_STUNDEN,
    HUGO_KA_FAKTOR,
    HUGO_KA_ZIEL_STUNDEN,
    HUGO_KA_RESERVE_PROZENT,
    HUGO_EINSATZ_STUNDEN,
    HUGO_KA_IDS,
    HUGO_EINSATZDAUER_TAGE,
    PLANUNGSHORIZONT_TAGE,
    PLANUNGSHORIZONT_MIN,
    VORLAUF_STANDARD_TAGE,
    TERMINVORSCHLAEGE_ANZAHL,
    OP_KLINIK_MAX_WOCHENTAG,
    REPAIR_SLA_STUNDEN,
    REPAIR_ZIEL_STUNDEN,
    REPAIR_WARNUNG_STUNDEN,
    REPAIR_ESKALATION_STUNDEN,
    ERSATZTEIL_SOFORT_TAGE,
    ERSATZTEIL_LAGER_TAGE,
    ERSATZTEIL_BESTELL_TAGE,
    MAX_EINSATZ_STUNDEN,
    SYNERGIEEFFEKT_FAKTOR,
    RUESTZEIT_MINUTEN,
    MAX_UEBERNACHTUNGEN_WOCHE,
    MAX_UEBERNACHTUNGEN_WOCHE_AUSNAHME,
    UEBERNACHTUNG_KOSTEN_EUR,
    UEBERNACHTUNG_TRIGGER_H,
    PUFFER_BASIS_MIN,
    PUFFER_EINSCHLEUSUNG_MIN,
    PUFFER_GROSSGERAET_MIN,
    PUFFER_GESPRAECH_MIN,
    PUFFER_MESSMITTEL_LADEN,
    TRAINING_SMALL_CAPITAL_EUR,
    TRAINING_HF_CHIRURGIE_EUR,
    HANDON_REPAIR_STUNDEN,
    HANDON_PM_STUNDEN,
    BUENDELUNG_RADIUS_KM,
    BUENDELUNG_GLEICHE_KLINIK,
    KALENDER_INTEGRIERT,
)


class TestConfigWerte:
    """Erwartete Werte der zentralen Konstanten."""

    # ─── Scoring ───────────────────────────────────
    def test_scoring_gewichte_summe_1(self):
        assert SCORING_KOMPETENZ + SCORING_FAHRZEIT + SCORING_AUSLASTUNG == 1.0

    def test_scoring_kompetenz(self):
        assert SCORING_KOMPETENZ == 0.40

    def test_scoring_fahrzeit(self):
        assert SCORING_FAHRZEIT == 0.35

    def test_scoring_auslastung(self):
        assert SCORING_AUSLASTUNG == 0.25

    def test_umweg_faktor(self):
        assert HAVERSINE_UMWEG_FAKTOR == 1.35

    # ─── Arbeitszeit ───────────────────────────────
    def test_arbzg_max(self):
        assert ARBZG_MAX_STUNDEN == 45

    def test_aussendienst_stunden(self):
        assert AUSSENDIENST_STUNDEN == 32

    def test_freitag_ho(self):
        assert FREITAG_NUR_HOME_OFFICE is True

    def test_warnung_stunden(self):
        assert WARNUNG_STUNDEN == 34

    def test_ausschluss_stunden(self):
        assert AUSSCHLUSS_STUNDEN == 36

    # ─── Hugo Key Account ──────────────────────────
    def test_hugo_ka_faktor(self):
        assert HUGO_KA_FAKTOR == 0.80

    def test_hugo_ka_ziel(self):
        assert HUGO_KA_ZIEL_STUNDEN == 25.6

    def test_hugo_ka_reserve(self):
        assert HUGO_KA_RESERVE_PROZENT == 0.20

    def test_hugo_einsatz(self):
        assert HUGO_EINSATZ_STUNDEN == 8.0

    def test_hugo_einsatzdauer_tage(self):
        assert HUGO_EINSATZDAUER_TAGE == 2.5

    def test_hugo_uebernachtungen_decken_einsatzdauer(self):
        import math
        # 2.5 Tage → 2 Naechte → MAX_UEBERNACHTUNGEN_HUGO muss >= ceil(2.5) - 1 sein
        min_naechte = math.ceil(HUGO_EINSATZDAUER_TAGE) - 1
        assert MAX_UEBERNACHTUNGEN_HUGO >= min_naechte

    def test_hugo_ka_ids(self):
        assert set(HUGO_KA_IDS) == {"T1", "T6", "T10", "T11"}

    # ─── Planung STK/PM ────────────────────────────
    def test_planungshorizont_tage(self):
        assert PLANUNGSHORIZONT_TAGE == 7

    def test_planungshorizont_min(self):
        assert PLANUNGSHORIZONT_MIN == 3

    def test_vorlauf_standard(self):
        assert VORLAUF_STANDARD_TAGE == 5

    def test_terminvorschlaege(self):
        assert TERMINVORSCHLAEGE_ANZAHL == 3

    def test_op_klinik_max_wochentag(self):
        assert OP_KLINIK_MAX_WOCHENTAG == 3

    # ─── Repair SLA ────────────────────────────────
    def test_repair_sla(self):
        assert REPAIR_SLA_STUNDEN == 48

    def test_repair_ziel(self):
        assert REPAIR_ZIEL_STUNDEN == 24

    def test_repair_warnung(self):
        assert REPAIR_WARNUNG_STUNDEN == 40

    def test_repair_eskalation(self):
        assert REPAIR_ESKALATION_STUNDEN == 48

    # ─── Ersatzteile ───────────────────────────────
    def test_ersatzteil_sofort(self):
        assert ERSATZTEIL_SOFORT_TAGE == 2

    def test_ersatzteil_lager(self):
        assert ERSATZTEIL_LAGER_TAGE == 3

    def test_ersatzteil_bestell(self):
        assert ERSATZTEIL_BESTELL_TAGE == 10

    # ─── Tour-Optimierung ──────────────────────────
    def test_max_einsatz(self):
        assert MAX_EINSATZ_STUNDEN == 6.0

    def test_synergieeffekt(self):
        assert SYNERGIEEFFEKT_FAKTOR == 0.70

    def test_ruestzeit(self):
        assert RUESTZEIT_MINUTEN == 30

    def test_max_uebernachtungen(self):
        assert MAX_UEBERNACHTUNGEN_WOCHE == 1

    def test_max_uebernachtungen_ausnahme(self):
        assert MAX_UEBERNACHTUNGEN_WOCHE_AUSNAHME == 2

    def test_uebernachtung_kosten(self):
        assert UEBERNACHTUNG_KOSTEN_EUR == 150

    def test_uebernachtung_trigger(self):
        assert UEBERNACHTUNG_TRIGGER_H == 3.0

    # ─── Puffer ────────────────────────────────────
    def test_puffer_basis(self):
        assert PUFFER_BASIS_MIN == 30

    def test_puffer_einschleusung(self):
        assert PUFFER_EINSCHLEUSUNG_MIN == 20

    def test_puffer_grossgeraet(self):
        assert PUFFER_GROSSGERAET_MIN == 30

    def test_puffer_gespraech(self):
        assert PUFFER_GESPRAECH_MIN == 15

    def test_puffer_messmittel(self):
        assert PUFFER_MESSMITTEL_LADEN == 30

    # ─── Training ──────────────────────────────────
    def test_training_small_capital(self):
        assert TRAINING_SMALL_CAPITAL_EUR == 0

    def test_training_hf_chirurgie(self):
        assert TRAINING_HF_CHIRURGIE_EUR == 0

    def test_handon_repair(self):
        assert HANDON_REPAIR_STUNDEN == 10

    def test_handon_pm(self):
        assert HANDON_PM_STUNDEN == 0

    # ─── Buendelung ────────────────────────────────
    def test_buendelung_radius(self):
        assert BUENDELUNG_RADIUS_KM == 50

    def test_buendelung_gleiche_klinik(self):
        assert BUENDELUNG_GLEICHE_KLINIK is True

    # ─── Kalender ──────────────────────────────────
    def test_kalender_prototyp(self):
        assert KALENDER_INTEGRIERT is False

    # ─── Planungshorizont (Wochen) ─────────────────
    def test_planungshorizont_werte(self):
        assert PLANUNGSHORIZONT_WOCHEN == 6
        assert PLANUNGSHORIZONT_MIN_WOCHEN == 4
        assert PLANUNGSHORIZONT_MAX_WOCHEN == 8
        assert PLANUNGSHORIZONT_MIN_WOCHEN < PLANUNGSHORIZONT_WOCHEN < PLANUNGSHORIZONT_MAX_WOCHEN

    # ─── Umplanungs-Prioritaeten ───────────────────
    def test_umplanungs_prioritaeten_reihenfolge(self):
        assert UMPLANUNGS_PRIORITAETEN['REPAIR_OHNE_ET'] == 1
        assert UMPLANUNGS_PRIORITAETEN['REPAIR_MIT_ET'] == 2
        assert UMPLANUNGS_PRIORITAETEN['STK_PM_UEBERFAELLIG'] == 3
        assert UMPLANUNGS_PRIORITAETEN['STK_PM_AUF_ROUTE'] == 4
        assert UMPLANUNGS_PRIORITAETEN['STK_PM_NORMAL'] == 5
        prios = list(UMPLANUNGS_PRIORITAETEN.values())
        assert prios == sorted(prios), "Prioritaeten muessen aufsteigend sortiert sein"

    # ─── STK/PM Monatsgenau ────────────────────────
    def test_stk_pm_monatsgenau_config(self):
        assert STK_PM_FAELLIGKEIT_MONATSGENAU is True
        assert STK_PM_TOLERANZ_TAGE_VOR == 0
        assert STK_PM_TOLERANZ_TAGE_NACH == 0
        assert STK_PM_AUSNAHME_LETZTER_WERKTAG is True

    # ─── OP-Klinik Tage ───────────────────────────
    def test_op_klinik_tage_montag_bis_donnerstag(self):
        """OP_KLINIK_TAGE muss Mo(0)–Do(3) enthalten, Fr(4) nicht."""
        assert OP_KLINIK_TAGE == [0, 1, 2, 3], "Mo–Do erwartet"
        assert 0 in OP_KLINIK_TAGE  # Montag
        assert 3 in OP_KLINIK_TAGE  # Donnerstag
        assert 4 not in OP_KLINIK_TAGE  # Freitag gesperrt
        assert 5 not in OP_KLINIK_TAGE  # Samstag gesperrt
        assert 6 not in OP_KLINIK_TAGE  # Sonntag gesperrt

    # ─── Hugo Übernachtungen ──────────────────────
    def test_max_uebernachtungen_hugo(self):
        """Hugo/Big Capital erhaelt mehr Uebernachtungen als Standard."""
        from config import MAX_UEBERNACHTUNGEN_WOCHE, MAX_UEBERNACHTUNGEN_WOCHE_AUSNAHME
        assert MAX_UEBERNACHTUNGEN_HUGO == 3
        assert MAX_UEBERNACHTUNGEN_HUGO > MAX_UEBERNACHTUNGEN_WOCHE_AUSNAHME
        assert MAX_UEBERNACHTUNGEN_WOCHE_AUSNAHME > MAX_UEBERNACHTUNGEN_WOCHE

    # ─── Letzter Außeneinsatz ─────────────────────
    def test_letzter_ausseneinsatz_donnerstag(self):
        """Letzter erlaubter Ausseneinsatz-Tag = Donnerstag (Wochentag 3)."""
        assert LETZTER_AUSSENEINSATZ_WOCHENTAG == 3   # Do = Python weekday 3
        assert KEIN_WOCHENENDEINSATZ is True

    # ─── STK/PM Wartungszyklen ─────────────────────
    def test_stk_pm_zyklen_vollstaendig(self):
        """STK_PM_ZYKLEN_MONATE: Vollstaendigkeits- und Plausibilitaetspruefung."""
        assert 'default' in STK_PM_ZYKLEN_MONATE, "default-Schluessel fehlt"
        assert STK_PM_ZYKLEN_MONATE['default'] == 12
        assert STK_PM_ZYKLEN_MONATE['PROG'] == 24
        assert STK_PM_ZYKLEN_MONATE['Mazor'] == 6
        assert STK_PM_ZYKLEN_MONATE['Hugo'] == 6
        # Alle Werte muessen positive ganze Zahlen sein
        for key, monate in STK_PM_ZYKLEN_MONATE.items():
            assert isinstance(monate, int) and monate > 0, (
                f"STK_PM_ZYKLEN_MONATE['{key}'] = {monate!r} ist kein positiver int"
            )


class TestConfigImportKonsistenz:
    """Alle Module importieren dieselben Werte aus config.py."""

    def test_scoring_gewichte(self):
        from techniker.scoring import _W_KOMPETENZ, _W_FAHRZEIT, _W_AUSLASTUNG
        assert _W_KOMPETENZ == SCORING_KOMPETENZ
        assert _W_FAHRZEIT == SCORING_FAHRZEIT
        assert _W_AUSLASTUNG == SCORING_AUSLASTUNG

    def test_scoring_arbzg(self):
        from techniker.scoring import _WOCHE_ZIEL_STD, _WOCHE_MAX_ABSOLUT
        assert _WOCHE_ZIEL_STD == AUSSENDIENST_STUNDEN
        assert _WOCHE_MAX_ABSOLUT == ARBZG_MAX_STUNDEN

    def test_scoring_umweg(self):
        from techniker.scoring import _UMWEGFAKTOR
        assert _UMWEGFAKTOR == HAVERSINE_UMWEG_FAKTOR

    def test_scoring_hugo(self):
        from techniker.scoring import (
            _HUGO_KAPAZITAETS_FAKTOR,
            _HUGO_KEY_ACCOUNT_IDS,
            _HUGO_EINSATZ_DAUER_STD,
            _HUGO_WOCHE_ZIEL_STD,
        )
        assert _HUGO_KAPAZITAETS_FAKTOR == HUGO_KA_FAKTOR
        assert _HUGO_KEY_ACCOUNT_IDS == set(HUGO_KA_IDS)
        assert _HUGO_EINSATZ_DAUER_STD == HUGO_EINSATZ_STUNDEN
        assert _HUGO_WOCHE_ZIEL_STD == HUGO_KA_ZIEL_STUNDEN

    def test_scoring_uebernachtung(self):
        from techniker.scoring import (
            MAX_UEBERNACHTUNGEN_PRO_WOCHE,
            _UEBERNACHTUNGS_FAHRZEIT_SCHWELLE_STD,
            _UEBERNACHTUNGS_KOSTEN_EUR,
        )
        assert MAX_UEBERNACHTUNGEN_PRO_WOCHE == MAX_UEBERNACHTUNGEN_WOCHE
        assert _UEBERNACHTUNGS_FAHRZEIT_SCHWELLE_STD == UEBERNACHTUNG_TRIGGER_H
        assert _UEBERNACHTUNGS_KOSTEN_EUR == UEBERNACHTUNG_KOSTEN_EUR

    def test_workflow_planung(self):
        from auftraege.workflow import (
            PLANUNGSHORIZONT_TAGE as WF_TAGE,
            PLANUNGSHORIZONT_MIN as WF_MIN,
            VORLAUF_STANDARD_TAGE as WF_VORLAUF,
        )
        assert WF_TAGE == PLANUNGSHORIZONT_TAGE
        assert WF_MIN == PLANUNGSHORIZONT_MIN
        assert WF_VORLAUF == VORLAUF_STANDARD_TAGE

    def test_workflow_repair_sla(self):
        from auftraege.workflow import (
            _REPAIR_SLA_GELB,
            _REPAIR_SLA_ROT,
            _REPAIR_SLA_KRITISCH,
        )
        assert _REPAIR_SLA_GELB == REPAIR_ZIEL_STUNDEN
        assert _REPAIR_SLA_ROT == REPAIR_WARNUNG_STUNDEN
        assert _REPAIR_SLA_KRITISCH == REPAIR_ESKALATION_STUNDEN

    def test_workflow_umweg(self):
        from auftraege.workflow import _UMWEGFAKTOR
        assert _UMWEGFAKTOR == HAVERSINE_UMWEG_FAKTOR

    def test_tour_optimierung_planung(self):
        from auftraege.tour_optimierung import (
            PLANUNGSHORIZONT_TAGE as TO_TAGE,
            PLANUNGSHORIZONT_MIN as TO_MIN,
            VORLAUF_STANDARD_TAGE as TO_VORLAUF,
        )
        assert TO_TAGE == PLANUNGSHORIZONT_TAGE
        assert TO_MIN == PLANUNGSHORIZONT_MIN
        assert TO_VORLAUF == VORLAUF_STANDARD_TAGE

    def test_tour_optimierung_arbzeit(self):
        from auftraege.tour_optimierung import _WOCHE_ZIEL_STD
        assert _WOCHE_ZIEL_STD == AUSSENDIENST_STUNDEN

    def test_tour_optimierung_einsatz(self):
        from auftraege.tour_optimierung import (
            MAX_EINSATZ_DAUER_STD,
            RUESTZEIT_PRO_GERAET_STD,
            CLUSTER_RADIUS_KM,
        )
        assert MAX_EINSATZ_DAUER_STD == MAX_EINSATZ_STUNDEN
        assert RUESTZEIT_PRO_GERAET_STD == RUESTZEIT_MINUTEN / 60.0
        assert CLUSTER_RADIUS_KM == BUENDELUNG_RADIUS_KM

    def test_tour_optimierung_umweg(self):
        from auftraege.tour_optimierung import _UMWEGFAKTOR
        assert _UMWEGFAKTOR == HAVERSINE_UMWEG_FAKTOR

    def test_tour_optimierung_uebernachtung_ausnahme(self):
        from auftraege.tour_optimierung import (
            _MAX_UEBERNACHTUNGEN_STANDARD,
            _MAX_UEBERNACHTUNGEN_AUSNAHME,
            _UEBERNACHTUNG_TRIGGER_STD,
        )
        assert _MAX_UEBERNACHTUNGEN_STANDARD == MAX_UEBERNACHTUNGEN_WOCHE
        assert _MAX_UEBERNACHTUNGEN_AUSNAHME == MAX_UEBERNACHTUNGEN_WOCHE_AUSNAHME
        assert _UEBERNACHTUNG_TRIGGER_STD == UEBERNACHTUNG_TRIGGER_H

    def test_einsatz_dauer_puffer(self):
        from auftraege.einsatz_dauer import (
            PUFFER_STANDARD_MIN,
            PUFFER_EINSCHLEUSUNG_MIN as ED_EINSCHL,
            PUFFER_GROSSGERAET_MIN as ED_GROSS,
            PUFFER_GESPRAECH_MIN as ED_GESPR,
            PUFFER_MESSMITTEL_LADEN as ED_MESS,
        )
        assert PUFFER_STANDARD_MIN == PUFFER_BASIS_MIN
        assert ED_EINSCHL == PUFFER_EINSCHLEUSUNG_MIN
        assert ED_GROSS == PUFFER_GROSSGERAET_MIN
        assert ED_GESPR == PUFFER_GESPRAECH_MIN
        assert ED_MESS == PUFFER_MESSMITTEL_LADEN

    def test_einsatz_dauer_synergieeffekt(self):
        from auftraege.einsatz_dauer import SYNERGIE_FAKTOR, RUESTZEIT_FAMILIE_WECHSEL_MIN
        assert SYNERGIE_FAKTOR == SYNERGIEEFFEKT_FAKTOR
        assert RUESTZEIT_FAMILIE_WECHSEL_MIN == RUESTZEIT_MINUTEN

    def test_einsatz_dauer_max(self):
        from auftraege.einsatz_dauer import MAX_EINSATZ_DAUER_MIN
        assert MAX_EINSATZ_DAUER_MIN == int(MAX_EINSATZ_STUNDEN * 60)

    def test_models_repair_sla(self):
        from auftraege.models import REPAIR_SLA_STUNDEN as MODEL_SLA
        assert MODEL_SLA == REPAIR_SLA_STUNDEN

    def test_models_repair_ziel(self):
        from auftraege.models import REPAIR_ZIEL_KONTAKT
        assert REPAIR_ZIEL_KONTAKT == REPAIR_ZIEL_STUNDEN

    def test_trunkstock_lieferzeiten(self):
        from auftraege.trunkstock import _LIEFERZEIT_TAGE, ErsatzteilVerfuegbarkeit
        assert _LIEFERZEIT_TAGE[ErsatzteilVerfuegbarkeit.SOFORT][1] == ERSATZTEIL_SOFORT_TAGE
        assert _LIEFERZEIT_TAGE[ErsatzteilVerfuegbarkeit.LAGER][1] == ERSATZTEIL_LAGER_TAGE
        assert _LIEFERZEIT_TAGE[ErsatzteilVerfuegbarkeit.BESTELLEN][1] == ERSATZTEIL_BESTELL_TAGE

    def test_crosstraining_kosten(self):
        from reporting.crosstraining_analyse import (
            KOSTEN_INTERN,
            KOSTEN_HF_CHIRURGIE_STK_PM,
            HANDON_STUNDEN_REPAIR_L3,
            HANDON_STUNDEN_PM,
        )
        assert KOSTEN_INTERN == TRAINING_SMALL_CAPITAL_EUR
        assert KOSTEN_HF_CHIRURGIE_STK_PM == TRAINING_HF_CHIRURGIE_EUR
        assert HANDON_STUNDEN_REPAIR_L3 == HANDON_REPAIR_STUNDEN
        assert HANDON_STUNDEN_PM == HANDON_PM_STUNDEN
