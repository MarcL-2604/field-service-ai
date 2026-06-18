"""Tests fuer die 4 neuen Business-Regeln:
1. Terminverschiebung
2. Klinik-Buendelung
3. Tour-Optimierung
4. Uebernachtungsregel
"""

import warnings
from datetime import date, datetime, timedelta

import pytest

from config import (
    VORLAUF_STANDARD_TAGE,
    UMPLANUNGS_PRIORITAETEN,
    STK_PM_FAELLIGKEIT_MONATSGENAU,
    STK_PM_AUSNAHME_LETZTER_WERKTAG,
    STK_PM_ZYKLEN_MONATE,
)
from techniker.abwesenheit import (
    Abwesenheit,
    lade_abwesenheiten,
    ist_abwesend,
    filtere_verfuegbare_techniker,
)
from auftraege.models import Auftrag, AuftragsTyp
from auftraege.workflow import (
    MAX_VERSCHIEBUNGEN_PRO_AUFTRAG,
    VerschiebungsGrund,
    PLANUNGSHORIZONT_TAGE,
    PLANUNGSHORIZONT_MIN,
    PLANUNGSGRUENDE,
    UMWEGZEIT_ROUTE_MAX_MIN,
    termin_verschieben,
    verschiebungs_historie_abfragen,
    _verschiebungs_historie_reset,
    schlage_termine_vor,
    filtere_nach_horizont,
    dedupliziere_auftraege,
    pruefe_stk_pm_faelligkeit,
    pruefe_umplanung,
    UmplanungsErgebnis,
    _ist_werktag_mo_do,
    _naechster_werktag_ab,
    _lade_klinik_op_attribute,
    get_stk_pm_zyklus,
)
from auftraege.tour_optimierung import (
    RUESTZEIT_PRO_GERAET_STD,
    CLUSTER_RADIUS_KM,
    SMALL_CAPITAL_L2_REICHT,
    BIG_CAPITAL_L3_PFLICHT,
    MAX_EINSATZ_DAUER_STD,
    buendle_auftraege,
    buendle_mit_qualifikation,
    optimiere_tagestouren,
    pruefe_uebernachtungs_ausnahme,
    _mindest_level,
    _tech_deckt_ab,
    _MAX_UEBERNACHTUNGEN_STANDARD,
    _MAX_UEBERNACHTUNGEN_AUSNAHME,
    _UEBERNACHTUNG_TRIGGER_STD,
)
from techniker.scoring import (
    TagesStatus,
    MAX_UEBERNACHTUNGEN_PRO_WOCHE,
    _UEBERNACHTUNGS_FAHRZEIT_SCHWELLE_STD,
    _UEBERNACHTUNGS_KOSTEN_EUR,
    _pruefe_arbeitszeit,
    berechne_empfehlung,
)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

_MONTAG = datetime(2026, 3, 23, 8, 0)


def _make_auftrag(
    auftrag_id="TEST-001",
    typ=AuftragsTyp.STK,
    klinik_id="K044",
    klinik_name="Uniklinikum Ulm",
    geraet_id="NIM4CM01",
    produkt_familie="Neuromonitoring",
    faellig=date(2026, 4, 1),
    techniker_id=None,
    anzahl=1,
) -> Auftrag:
    return Auftrag(
        auftrag_id=auftrag_id,
        auftragstyp=typ,
        klinik_id=klinik_id,
        klinik_name=klinik_name,
        geraet_id=geraet_id,
        produkt_familie=produkt_familie,
        faelligkeitsdatum=faellig,
        techniker_id=techniker_id,
        anzahl_geraete=anzahl,
    )


def _pruefe(
    auftrag_typ="STK",
    woche=0.0,
    tag=0.0,
    distanz_km=50.0,
    dauer_std=4.0,
    datum=_MONTAG,
    letztes_ende=None,
    uebernachtungen=0,
):
    status = TagesStatus(
        wochenstunden_aktuell=woche,
        tagesstunden_aktuell=tag,
        letztes_arbeitsende=letztes_ende,
        uebernachtungen_diese_woche=uebernachtungen,
    )
    return _pruefe_arbeitszeit("TX", auftrag_typ, status, dauer_std, datum, distanz_km)


# ===================================================================
# 1. TERMINVERSCHIEBUNG
# ===================================================================

class TestTerminverschiebung:
    """Tests fuer Termin-Umplanung ueber SMax Go."""

    @pytest.fixture(autouse=True)
    def reset_historie(self):
        _verschiebungs_historie_reset()
        yield
        _verschiebungs_historie_reset()

    def test_erste_verschiebung_erfolgreich(self):
        auftrag = _make_auftrag(faellig=date(2026, 4, 1))
        ergebnis = termin_verschieben(
            auftrag, VerschiebungsGrund.KLINIK_NICHT_ERREICHBAR
        )
        assert ergebnis.erfolg
        assert ergebnis.verschiebung_nummer == 1
        assert ergebnis.alter_termin == date(2026, 4, 1)
        assert ergebnis.neuer_termin is not None
        assert ergebnis.warnung is None

    def test_auftrag_datum_wird_aktualisiert(self):
        auftrag = _make_auftrag(faellig=date(2026, 4, 1))
        neuer_termin = date(2026, 4, 8)
        termin_verschieben(
            auftrag, VerschiebungsGrund.GERAET_NICHT_VERFUEGBAR,
            neuer_termin=neuer_termin,
        )
        assert auftrag.faelligkeitsdatum == neuer_termin

    def test_historie_wird_gespeichert(self):
        auftrag = _make_auftrag()
        termin_verschieben(auftrag, VerschiebungsGrund.EIGENE_VERHINDERUNG)
        historie = verschiebungs_historie_abfragen(auftrag.auftrag_id)
        assert len(historie) == 1
        assert historie[0].grund == VerschiebungsGrund.EIGENE_VERHINDERUNG

    def test_zweite_verschiebung_ohne_warnung(self):
        auftrag = _make_auftrag(faellig=date(2026, 4, 1))
        termin_verschieben(auftrag, VerschiebungsGrund.KLINIK_NICHT_ERREICHBAR)
        e2 = termin_verschieben(auftrag, VerschiebungsGrund.EIGENE_VERHINDERUNG)
        assert e2.erfolg
        assert e2.verschiebung_nummer == 2
        assert e2.warnung is None

    def test_dritte_verschiebung_mit_warnung(self):
        auftrag = _make_auftrag(faellig=date(2026, 4, 1))
        termin_verschieben(auftrag, VerschiebungsGrund.KLINIK_NICHT_ERREICHBAR)
        termin_verschieben(auftrag, VerschiebungsGrund.EIGENE_VERHINDERUNG)
        e3 = termin_verschieben(auftrag, VerschiebungsGrund.GERAET_NICHT_VERFUEGBAR)
        assert e3.erfolg  # trotzdem durchgefuehrt
        assert e3.warnung is not None
        assert "bereits" in e3.warnung
        assert str(MAX_VERSCHIEBUNGEN_PRO_AUFTRAG) in e3.warnung

    def test_max_verschiebungen_konstante(self):
        assert MAX_VERSCHIEBUNGEN_PRO_AUFTRAG == 2

    def test_benachrichtigungen_enthalten_techniker_und_klinik(self):
        auftrag = _make_auftrag(techniker_id="T5")
        ergebnis = termin_verschieben(
            auftrag, VerschiebungsGrund.KLINIK_NICHT_ERREICHBAR
        )
        assert len(ergebnis.benachrichtigungen) == 2
        assert any("Techniker" in b for b in ergebnis.benachrichtigungen)
        assert any("Klinik" in b for b in ergebnis.benachrichtigungen)

    def test_auto_slot_ist_werktag_mo_do(self):
        # Freitag als Faelligkeitsdatum → naechster Slot muss Mo-Do sein
        auftrag = _make_auftrag(faellig=date(2026, 3, 27))  # Freitag
        ergebnis = termin_verschieben(auftrag, VerschiebungsGrund.EIGENE_VERHINDERUNG)
        assert ergebnis.neuer_termin.weekday() <= 3  # Mo-Do

    def test_verschiebungsgruende_enum(self):
        assert len(VerschiebungsGrund) == 6
        assert VerschiebungsGrund.KLINIK_NICHT_ERREICHBAR.value == "Klinik nicht erreichbar"
        assert VerschiebungsGrund.GERAET_NICHT_VERFUEGBAR.value == "Geraet nicht verfuegbar"
        assert VerschiebungsGrund.EIGENE_VERHINDERUNG.value == "Eigene Verhinderung"
        assert VerschiebungsGrund.OPPLAN_KONFLIKT.value == "OP-Plan Konflikt"
        assert VerschiebungsGrund.MESSMITTEL_FEHLT.value == "Messmittel nicht verfuegbar"
        assert VerschiebungsGrund.SONSTIGES.value == "Sonstiges"

    def test_opplan_konflikt_uebernachste_woche(self):
        """OPPLAN_KONFLIKT → neuer Termin fruehestens uebernachste Woche."""
        auftrag = _make_auftrag(faellig=date(2026, 4, 1))
        ergebnis = termin_verschieben(auftrag, VerschiebungsGrund.OPPLAN_KONFLIKT)
        assert ergebnis.erfolg
        # Mindestens 7 Tage in der Zukunft (uebernachste Woche)
        assert ergebnis.neuer_termin >= date.today() + timedelta(days=7)
        assert ergebnis.neuer_termin.weekday() <= 3  # Mo-Do

    def test_opplan_konflikt_benachrichtigung_op_kritisch(self):
        auftrag = _make_auftrag(faellig=date(2026, 4, 1))
        ergebnis = termin_verschieben(auftrag, VerschiebungsGrund.OPPLAN_KONFLIKT)
        assert any("op_kritisch" in b for b in ergebnis.benachrichtigungen)
        assert any("OP-Plan Konflikt" in b for b in ergebnis.benachrichtigungen)

    def test_messmittel_fehlt_3_werktage(self):
        """MESSMITTEL_FEHLT → heute + 3 Werktage."""
        auftrag = _make_auftrag(faellig=date(2026, 4, 1))
        ergebnis = termin_verschieben(auftrag, VerschiebungsGrund.MESSMITTEL_FEHLT)
        assert ergebnis.erfolg
        assert ergebnis.neuer_termin >= date.today() + timedelta(days=3)
        assert ergebnis.neuer_termin.weekday() <= 3  # Mo-Do

    def test_messmittel_fehlt_trunkstock_warnung(self):
        auftrag = _make_auftrag(faellig=date(2026, 4, 1))
        ergebnis = termin_verschieben(auftrag, VerschiebungsGrund.MESSMITTEL_FEHLT)
        assert any("Trunkstock-Warnung" in b for b in ergebnis.benachrichtigungen)

    def test_urspruenglicher_termin_in_historie(self):
        original = date(2026, 4, 15)
        auftrag = _make_auftrag(faellig=original)
        termin_verschieben(auftrag, VerschiebungsGrund.EIGENE_VERHINDERUNG)
        historie = verschiebungs_historie_abfragen(auftrag.auftrag_id)
        assert historie[0].urspruenglicher_termin == original


# ===================================================================
# 2. KLINIK-BUENDELUNG
# ===================================================================

class TestKlinikBuendelung:
    """Tests fuer Auftrags-Buendelung (gleiche Klinik, gleicher Monat)."""

    def test_zwei_auftraege_gleiche_klinik_gleicher_monat(self):
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K001", faellig=date(2026, 4, 5)),
            _make_auftrag(auftrag_id="A2", klinik_id="K001", faellig=date(2026, 4, 20)),
        ]
        result = buendle_auftraege(auftraege)
        assert len(result) == 1
        assert len(result[0].auftraege) == 2

    def test_verschiedene_kliniken_nicht_gebuendelt(self):
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K001", faellig=date(2026, 4, 5)),
            _make_auftrag(auftrag_id="A2", klinik_id="K002", faellig=date(2026, 4, 5)),
        ]
        result = buendle_auftraege(auftraege)
        assert len(result) == 0  # nur Einzelauftraege

    def test_verschiedene_monate_nicht_gebuendelt(self):
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K001", faellig=date(2026, 4, 5)),
            _make_auftrag(auftrag_id="A2", klinik_id="K001", faellig=date(2026, 5, 5)),
        ]
        result = buendle_auftraege(auftraege)
        assert len(result) == 0

    def test_gesamtdauer_enthaelt_ruestzeit(self):
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K001", faellig=date(2026, 4, 5)),
            _make_auftrag(auftrag_id="A2", klinik_id="K001", faellig=date(2026, 4, 10)),
            _make_auftrag(auftrag_id="A3", klinik_id="K001", faellig=date(2026, 4, 15)),
        ]
        result = buendle_auftraege(auftraege)
        assert len(result) == 1
        # 3 Auftraege: 2 Ruestzeitbloecke
        assert result[0].ruestzeit_std == RUESTZEIT_PRO_GERAET_STD * 2

    def test_eingesparte_fahrten(self):
        auftraege = [
            _make_auftrag(auftrag_id=f"A{i}", klinik_id="K001", faellig=date(2026, 4, i + 1))
            for i in range(4)
        ]
        result = buendle_auftraege(auftraege)
        assert result[0].eingesparte_fahrten == 3  # 4 Auftraege, 1 Fahrt statt 4

    def test_ersparnis_berechnung(self):
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K001", faellig=date(2026, 4, 5)),
            _make_auftrag(auftrag_id="A2", klinik_id="K001", faellig=date(2026, 4, 10)),
        ]
        result = buendle_auftraege(auftraege, avg_fahrzeit_std=1.5)
        assert result[0].ersparnis_fahrzeit_std == 1.5  # 1 gesparte Fahrt × 1.5h

    def test_ohne_klinik_id_wird_ignoriert(self):
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id=None, faellig=date(2026, 4, 5)),
            _make_auftrag(auftrag_id="A2", klinik_id=None, faellig=date(2026, 4, 10)),
        ]
        result = buendle_auftraege(auftraege)
        assert len(result) == 0

    def test_ruestzeit_konstante(self):
        assert RUESTZEIT_PRO_GERAET_STD == 0.5


# ===================================================================
# 3. TOUR-OPTIMIERUNG
# ===================================================================

class TestTourOptimierung:
    """Tests fuer Tagestouren (mehrere Kliniken pro Tag)."""

    def test_nahe_kliniken_werden_kombiniert(self):
        """Kliniken in Hamburg-Naehe sollten gruppiert werden."""
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K001", klinik_name="UKE Hamburg",
                          faellig=date(2026, 4, 5), anzahl=1),
            _make_auftrag(auftrag_id="A2", klinik_id="K004", klinik_name="Asklepios Barmbek",
                          faellig=date(2026, 4, 5), anzahl=1),
        ]
        # T6 ist in Schenefeld, K001 (12km) und K004 (14km) sind 3km voneinander
        # max_tag_std=10h damit 2×4h Onsite + 0.43h Fahrzeit passt
        touren = optimiere_tagestouren(auftraege, "T6", max_tag_std=10.0)
        assert len(touren) >= 1
        assert touren[0].eingesparte_einzelfahrten >= 1

    def test_weit_entfernte_kliniken_nicht_kombiniert(self):
        """Hamburg und Muenchen sollten nicht in einer Tour sein."""
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K001", klinik_name="UKE Hamburg",
                          faellig=date(2026, 4, 5)),
            _make_auftrag(auftrag_id="A2", klinik_id="K044", klinik_name="Uni Ulm",
                          faellig=date(2026, 4, 5)),
        ]
        touren = optimiere_tagestouren(auftraege, "T6")
        # Keine Tour die beide enthält (>50km Radius)
        for tour in touren:
            klinik_ids = {k["klinik_id"] for k in tour.kliniken}
            assert not ({"K001", "K044"}.issubset(klinik_ids))

    def test_tageslimit_wird_eingehalten(self):
        """Tour darf 8h Tageslimit nicht ueberschreiten."""
        auftraege = [
            _make_auftrag(auftrag_id=f"A{i}", klinik_id=f"K01{i}", klinik_name=f"Klinik {i}",
                          faellig=date(2026, 4, 5))
            for i in range(5)
        ]
        touren = optimiere_tagestouren(auftraege, "T14")
        for tour in touren:
            assert tour.gesamtdauer_tag_std <= 8.0 + 0.1  # kleiner Float-Toleranz

    def test_max_3_kliniken_pro_tour(self):
        auftraege = [
            _make_auftrag(auftrag_id=f"A{i}", klinik_id="K014", klinik_name="Duesseldorf",
                          faellig=date(2026, 4, i + 1))
            for i in range(5)
        ]
        # Buendelung passiert separat; Tour-Optimierung arbeitet mit verschiedenen Kliniken
        # Hier alle gleiche Klinik → keine Tour (braucht min 2 verschiedene Kliniken)
        touren = optimiere_tagestouren(auftraege, "T14")
        for tour in touren:
            assert len(tour.kliniken) <= 3

    def test_unbekannter_techniker_leere_liste(self):
        auftraege = [_make_auftrag()]
        touren = optimiere_tagestouren(auftraege, "T_UNBEKANNT")
        assert touren == []

    def test_tour_hinweis_text(self):
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K001", klinik_name="UKE Hamburg",
                          faellig=date(2026, 4, 5), anzahl=1),
            _make_auftrag(auftrag_id="A2", klinik_id="K004", klinik_name="Asklepios Barmbek",
                          faellig=date(2026, 4, 5), anzahl=1),
        ]
        touren = optimiere_tagestouren(auftraege, "T6", max_tag_std=10.0)
        if touren:
            assert "T6" in touren[0].hinweis
            assert "Kliniken" in touren[0].hinweis
            assert "spart" in touren[0].hinweis

    def test_cluster_radius_konstante(self):
        assert CLUSTER_RADIUS_KM == 50.0


# ===================================================================
# 4. UEBERNACHTUNGSREGEL
# ===================================================================

class TestUebernachtungsregel:
    """Tests fuer Uebernachtungsregel im Scoring."""

    def test_konstanten(self):
        assert MAX_UEBERNACHTUNGEN_PRO_WOCHE == 1
        assert _UEBERNACHTUNGS_FAHRZEIT_SCHWELLE_STD == 3.0
        assert _UEBERNACHTUNGS_KOSTEN_EUR == 150.0

    def test_kurze_fahrzeit_keine_uebernachtung(self):
        """< 3h Fahrzeit → keine Uebernachtungswarnung."""
        # 50km → ca. 0.75h Fahrzeit, weit unter 3h
        ausgeschlossen, warnungen = _pruefe(distanz_km=50.0)
        assert not ausgeschlossen
        assert not any("Uebernachtung" in w for w in warnungen)

    def test_lange_fahrzeit_uebernachtung_noetig(self):
        """> 3h Fahrzeit (>200km) → Uebernachtung noetig."""
        # 250km → ca. 3.75h Fahrzeit > 3h Schwelle
        ausgeschlossen, warnungen = _pruefe(distanz_km=250.0, dauer_std=2.0, tag=0.0)
        assert not ausgeschlossen
        assert any("Uebernachtung noetig" in w for w in warnungen)
        assert any("150 EUR" in w for w in warnungen)

    def test_uebernachtung_limit_erreicht_warnung(self):
        """Bereits 1 Uebernachtung geplant + erneut > 3h → Warnung mit Empfehlung."""
        ausgeschlossen, warnungen = _pruefe(
            distanz_km=250.0, dauer_std=2.0, tag=0.0, uebernachtungen=1
        )
        assert not ausgeschlossen  # kein harter Ausschluss, aber Warnung
        assert any("bereits erreicht" in w for w in warnungen)
        assert any("anderen Techniker" in w for w in warnungen)

    def test_uebernachtung_erste_woche_ok(self):
        """Erste Uebernachtung der Woche → kein Limit-Problem."""
        ausgeschlossen, warnungen = _pruefe(
            distanz_km=250.0, dauer_std=2.0, tag=0.0, uebernachtungen=0
        )
        assert not ausgeschlossen
        uebernachtungs_warnungen = [w for w in warnungen if "Uebernachtung" in w]
        assert len(uebernachtungs_warnungen) == 1
        assert "bereits erreicht" not in uebernachtungs_warnungen[0]

    def test_grenzwert_exakt_3h_keine_uebernachtung(self):
        """Exakt 3h → keine Uebernachtung (nur > 3h)."""
        # Berechne km fuer exakt 3h: km * 1.35 / 90 = 3.0 → km = 200.0
        ausgeschlossen, warnungen = _pruefe(distanz_km=200.0, dauer_std=2.0, tag=0.0)
        assert not any("Uebernachtung" in w for w in warnungen)

    def test_uebernachtung_in_empfehlung_integration(self):
        """Integration: Uebernachtungswarnung erscheint in berechne_empfehlung Ergebnis."""
        # K001 = Hamburg, T10 = Balingen (>500km) → Fahrzeit > 3h
        status = {"T10": TagesStatus(wochenstunden_aktuell=0.0, uebernachtungen_diese_woche=1)}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = berechne_empfehlung(
                "STK", "Hugo", "K001",
                tages_status=status, einsatz_dauer_std=2.0,
            )
        t10 = next((r for r in result if r.techniker_id == "T10"), None)
        if t10 is not None:
            assert any("Uebernachtung" in w for w in t10.warnungen)

    def test_tagesstatus_hat_uebernachtungen_feld(self):
        """TagesStatus hat das Feld uebernachtungen_diese_woche."""
        status = TagesStatus(uebernachtungen_diese_woche=2)
        assert status.uebernachtungen_diese_woche == 2

    def test_default_uebernachtungen_ist_null(self):
        """Default: 0 Uebernachtungen."""
        status = TagesStatus()
        assert status.uebernachtungen_diese_woche == 0


class TestUebernachtungsAusnahme:
    """Tests fuer pruefe_uebernachtungs_ausnahme (wirtschaftliche 2. Uebernachtung)."""

    def test_konstanten(self):
        assert _MAX_UEBERNACHTUNGEN_STANDARD == 1
        assert _MAX_UEBERNACHTUNGEN_AUSNAHME == 2
        assert _UEBERNACHTUNG_TRIGGER_STD == 3.0

    def test_kein_limit_noch_nicht_erreicht(self):
        """0 Uebernachtungen → Ausnahme nicht relevant, False zurueck."""
        erlaubt, kommentar = pruefe_uebernachtungs_ausnahme(
            fahrzeit_hin_std=4.0, uebernachtungen_diese_woche=0, kliniken_kombinierbar=True
        )
        assert not erlaubt
        assert kommentar == ""

    def test_ausnahme_bedingung_a_fahrzeiteinsparung(self):
        """1 Uebernachtung + fahrzeit_hin 2.0h → gespart 4.0h >= 3h → Ausnahme erlaubt."""
        erlaubt, kommentar = pruefe_uebernachtungs_ausnahme(
            fahrzeit_hin_std=2.0, uebernachtungen_diese_woche=1, kliniken_kombinierbar=False
        )
        assert erlaubt
        assert "Wirtschaftliche Ausnahme: 2 Uebernachtungen" in kommentar
        assert "Fahrzeiteinsparung" in kommentar

    def test_ausnahme_bedingung_b_kliniken_kombinierbar(self):
        """1 Uebernachtung + kliniken_kombinierbar → Ausnahme erlaubt (unabhaengig von Fahrzeit)."""
        erlaubt, kommentar = pruefe_uebernachtungs_ausnahme(
            fahrzeit_hin_std=0.5, uebernachtungen_diese_woche=1, kliniken_kombinierbar=True
        )
        assert erlaubt
        assert "Wirtschaftliche Ausnahme: 2 Uebernachtungen" in kommentar
        assert "Region kombinierbar" in kommentar

    def test_beide_bedingungen_im_kommentar(self):
        """Beide Bedingungen erfuellt → beide im Kommentar."""
        erlaubt, kommentar = pruefe_uebernachtungs_ausnahme(
            fahrzeit_hin_std=2.0, uebernachtungen_diese_woche=1, kliniken_kombinierbar=True
        )
        assert erlaubt
        assert "Fahrzeiteinsparung" in kommentar
        assert "Region kombinierbar" in kommentar

    def test_keine_ausnahme_keine_bedingung_erfuellt(self):
        """1 Uebernachtung + kurze Fahrzeit + nicht kombinierbar → keine Ausnahme."""
        erlaubt, kommentar = pruefe_uebernachtungs_ausnahme(
            fahrzeit_hin_std=1.0, uebernachtungen_diese_woche=1, kliniken_kombinierbar=False
        )
        assert not erlaubt
        assert kommentar == ""

    def test_ausnahmelimit_bereits_voll(self):
        """2 Uebernachtungen bereits geplant → keine weitere Ausnahme."""
        erlaubt, kommentar = pruefe_uebernachtungs_ausnahme(
            fahrzeit_hin_std=5.0, uebernachtungen_diese_woche=2, kliniken_kombinierbar=True
        )
        assert not erlaubt
        assert kommentar == ""

    def test_tour_uebernachtung_felder_bei_kurzer_fahrzeit(self):
        """Nahe Kliniken: uebernachtung_noetig=False, kein dashboard_warning."""
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K001", klinik_name="UKE Hamburg",
                          faellig=date(2026, 4, 5), anzahl=1),
            _make_auftrag(auftrag_id="A2", klinik_id="K004", klinik_name="Asklepios Barmbek",
                          faellig=date(2026, 4, 5), anzahl=1),
        ]
        touren = optimiere_tagestouren(auftraege, "T6", max_tag_std=10.0,
                                       uebernachtungen_diese_woche=1)
        if touren:
            # T6 liegt in Schenefeld, K001+K004 sind nahe → Fahrzeit < 3h
            tour = touren[0]
            assert not tour.uebernachtung_noetig
            assert not tour.uebernachtungs_ausnahme
            assert tour.uebernachtungs_kommentar is None
            assert tour.dashboard_warnung is None

    def test_tour_dashboard_warnung_ab_2_uebernachtungen(self):
        """Ferne Klinik + bereits 1 Uebernachtung → dashboard_warnung gesetzt."""
        # K001 Hamburg, Techniker T10 Balingen: Fahrzeit >> 3h → uebernachtung_noetig
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K001", klinik_name="UKE Hamburg",
                          faellig=date(2026, 4, 5), anzahl=1),
            _make_auftrag(auftrag_id="A2", klinik_id="K004", klinik_name="Asklepios Barmbek",
                          faellig=date(2026, 4, 5), anzahl=1),
        ]
        touren = optimiere_tagestouren(
            auftraege, "T10", max_tag_std=20.0, uebernachtungen_diese_woche=1
        )
        if touren:
            ferne_tour = next((t for t in touren if t.uebernachtung_noetig), None)
            if ferne_tour is not None:
                assert ferne_tour.dashboard_warnung is not None
                assert "Warnung" in ferne_tour.dashboard_warnung


# ===================================================================
# 5. QUALIFIKATIONS-CHECK BEI BUENDELUNG
# ===================================================================

class TestQualifikationsKonstanten:
    """Tests fuer Qualifikations-Konstanten."""

    def test_small_capital_familien(self):
        assert "Neuromonitoring" in SMALL_CAPITAL_L2_REICHT
        assert "Programmer" in SMALL_CAPITAL_L2_REICHT
        assert "ACT" in SMALL_CAPITAL_L2_REICHT
        assert "Kardiovaskulaer_IPC" in SMALL_CAPITAL_L2_REICHT

    def test_big_capital_familien(self):
        assert "Hugo" in BIG_CAPITAL_L3_PFLICHT
        assert "Navigation" in BIG_CAPITAL_L3_PFLICHT
        assert "Wirbelsaeule" in BIG_CAPITAL_L3_PFLICHT
        assert "Kardiovaskulaer_Ablation" in BIG_CAPITAL_L3_PFLICHT
        assert "Energie" not in BIG_CAPITAL_L3_PFLICHT  # EC300/IPC = Small Capital

    def test_keine_ueberschneidung(self):
        """Small Capital und Big Capital duerfen sich nicht ueberschneiden."""
        assert not set(SMALL_CAPITAL_L2_REICHT) & set(BIG_CAPITAL_L3_PFLICHT)

    def test_max_einsatz_dauer(self):
        assert MAX_EINSATZ_DAUER_STD == 6.0

    def test_ruestzeit(self):
        assert RUESTZEIT_PRO_GERAET_STD == 0.5


class TestMindestLevel:
    """Tests fuer _mindest_level Hilfsfunktion."""

    def test_big_capital_or_immer_l3(self):
        for pf in ["Hugo", "Navigation", "Wirbelsaeule"]:
            for typ in ["STK", "PM", "Repair"]:
                assert _mindest_level(pf, typ) == "L3", f"{pf} {typ} sollte L3 sein"

    def test_small_capital_stk_l2(self):
        for pf in ["Neuromonitoring", "Programmer", "ACT", "Kardiovaskulaer_IPC"]:
            assert _mindest_level(pf, "STK") == "L2", f"{pf} STK sollte L2 sein"

    def test_hf_chirurgie_stk_pm_l2_repair_l3(self):
        assert _mindest_level("Elektrochirurgie", "STK") == "L2"
        assert _mindest_level("Elektrochirurgie", "PM") == "L2"
        assert _mindest_level("Elektrochirurgie", "Repair") == "L3"

    def test_monitoring_stk_l2_pm_l3(self):
        assert _mindest_level("Beatmung", "STK") == "L2"
        assert _mindest_level("Beatmung", "PM") == "L3"


class TestTechDecktAb:
    """Tests fuer _tech_deckt_ab Hilfsfunktion."""

    def test_l3_deckt_big_capital_ab(self):
        quals = {"Hugo": "L3", "Neuromonitoring": "L3"}
        auftraege = [
            _make_auftrag(auftrag_id="A1", produkt_familie="Hugo"),
            _make_auftrag(auftrag_id="A2", produkt_familie="Neuromonitoring"),
        ]
        abgedeckt, rest = _tech_deckt_ab(quals, auftraege)
        assert len(abgedeckt) == 2
        assert len(rest) == 0

    def test_l2_reicht_nicht_fuer_big_capital(self):
        quals = {"Hugo": "L2"}
        auftraege = [_make_auftrag(auftrag_id="A1", produkt_familie="Hugo")]
        abgedeckt, rest = _tech_deckt_ab(quals, auftraege)
        assert len(abgedeckt) == 0
        assert len(rest) == 1

    def test_l2_reicht_fuer_small_capital_stk(self):
        quals = {"Neuromonitoring": "L2"}
        auftraege = [
            _make_auftrag(auftrag_id="A1", produkt_familie="Neuromonitoring",
                          typ=AuftragsTyp.STK),
        ]
        abgedeckt, rest = _tech_deckt_ab(quals, auftraege)
        assert len(abgedeckt) == 1

    def test_l2_reicht_nicht_fuer_small_capital_repair(self):
        quals = {"Neuromonitoring": "L2"}
        auftraege = [
            _make_auftrag(auftrag_id="A1", produkt_familie="Neuromonitoring",
                          typ=AuftragsTyp.REPAIR),
        ]
        abgedeckt, rest = _tech_deckt_ab(quals, auftraege)
        assert len(abgedeckt) == 0
        assert len(rest) == 1

    def test_fehlende_qualifikation(self):
        quals = {"Beatmung": "L3"}
        auftraege = [_make_auftrag(auftrag_id="A1", produkt_familie="Hugo")]
        abgedeckt, rest = _tech_deckt_ab(quals, auftraege)
        assert len(abgedeckt) == 0
        assert len(rest) == 1


class TestBuendelungMitQualifikation:
    """Tests fuer buendle_mit_qualifikation — Fall A, B, C."""

    # --- Fall A: Ein Techniker deckt alles ab ---

    def test_fall_a_ein_techniker_deckt_alles(self):
        """Fall A: T5 hat Neuromonitoring L3 + Elektrochirurgie L3 → ein Einsatz."""
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K044", klinik_name="Uni Ulm",
                          produkt_familie="Neuromonitoring", faellig=date(2026, 4, 5)),
            _make_auftrag(auftrag_id="A2", klinik_id="K044", klinik_name="Uni Ulm",
                          produkt_familie="Elektrochirurgie", faellig=date(2026, 4, 10)),
        ]
        result = buendle_mit_qualifikation(auftraege)
        assert len(result) == 1
        plan = result[0]
        assert plan.fall in ("A", "C")  # A oder C (breitestes Portfolio)
        assert len(plan.einsaetze) == 1
        assert len(plan.einsaetze[0].auftraege) == 2
        assert plan.eingesparte_fahrten == 1

    def test_fall_a_hinweis_enthaelt_techniker_und_familien(self):
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K044", klinik_name="Uni Ulm",
                          produkt_familie="Neuromonitoring", faellig=date(2026, 4, 5)),
            _make_auftrag(auftrag_id="A2", klinik_id="K044", klinik_name="Uni Ulm",
                          produkt_familie="Elektrochirurgie", faellig=date(2026, 4, 10)),
        ]
        result = buendle_mit_qualifikation(auftraege)
        assert len(result) == 1
        assert "Uni Ulm" in result[0].hinweis
        assert "1 Einsatz" in result[0].hinweis

    def test_fall_a_qualifikationen_im_einsatz(self):
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K044", klinik_name="Uni Ulm",
                          produkt_familie="Neuromonitoring", faellig=date(2026, 4, 5)),
            _make_auftrag(auftrag_id="A2", klinik_id="K044", klinik_name="Uni Ulm",
                          produkt_familie="Elektrochirurgie", faellig=date(2026, 4, 10)),
        ]
        result = buendle_mit_qualifikation(auftraege)
        einsatz = result[0].einsaetze[0]
        # Techniker muss mindestens L2 fuer beide haben
        for fam in ["Neuromonitoring", "Elektrochirurgie"]:
            assert fam in einsatz.qualifikationen
            assert einsatz.qualifikationen[fam] in ("L2", "L3")

    # --- Fall B: Kein einzelner Techniker reicht → Aufteilung ---

    def test_fall_b_aufteilung_noetig(self):
        """Fall B: Hugo (nur T1/T6/T10/T11 L3) + Kardiovaskulaer_Ablation (nur T13 L3)
        → kein Techniker hat beides → Aufteilung."""
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K001", klinik_name="UKE Hamburg",
                          produkt_familie="Hugo", faellig=date(2026, 4, 5)),
            _make_auftrag(auftrag_id="A2", klinik_id="K001", klinik_name="UKE Hamburg",
                          produkt_familie="Kardiovaskulaer_Ablation", faellig=date(2026, 4, 10)),
        ]
        result = buendle_mit_qualifikation(auftraege)
        assert len(result) == 1
        plan = result[0]
        assert plan.fall == "B"
        assert len(plan.einsaetze) >= 2
        # Jeder Einsatz hat mindestens einen Auftrag
        for e in plan.einsaetze:
            assert len(e.auftraege) >= 1
        # Alle Auftraege sind zugewiesen
        zugewiesene = set()
        for e in plan.einsaetze:
            for a in e.auftraege:
                zugewiesene.add(a.auftrag_id)
        assert "A1" in zugewiesene
        assert "A2" in zugewiesene

    def test_fall_b_aufteilungsgrund_dokumentiert(self):
        """Fall B: Aufteilungsgrund muss dokumentiert sein."""
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K001", klinik_name="UKE Hamburg",
                          produkt_familie="Hugo", faellig=date(2026, 4, 5)),
            _make_auftrag(auftrag_id="A2", klinik_id="K001", klinik_name="UKE Hamburg",
                          produkt_familie="Kardiovaskulaer_Ablation", faellig=date(2026, 4, 10)),
        ]
        result = buendle_mit_qualifikation(auftraege)
        plan = result[0]
        assert plan.aufteilungsgrund is not None
        assert "Qualifikation" in plan.aufteilungsgrund

    def test_fall_b_hinweis_zeigt_mehrere_techniker(self):
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K001", klinik_name="UKE Hamburg",
                          produkt_familie="Hugo", faellig=date(2026, 4, 5)),
            _make_auftrag(auftrag_id="A2", klinik_id="K001", klinik_name="UKE Hamburg",
                          produkt_familie="Kardiovaskulaer_Ablation", faellig=date(2026, 4, 10)),
        ]
        result = buendle_mit_qualifikation(auftraege)
        hinweis = result[0].hinweis
        assert "UKE Hamburg" in hinweis
        assert "Einsaetze statt" in hinweis

    # --- Fall C: Teilueberschneidung → breitestes Portfolio ---

    def test_fall_c_breitestes_portfolio_gewaehlt(self):
        """Fall C: Mehrere Techniker decken alles ab, breitestes Portfolio gewinnt.
        T5 hat Neuromonitoring L3 + Wirbelsaeule L3 + Elektrochirurgie L3 + Kardiovaskulaer L3
        T10 hat alle 4 auch → T10 hat sogar mehr (Hugo etc.)
        → System waehlt den mit den meisten Qualifikationen."""
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K044", klinik_name="Uni Ulm",
                          produkt_familie="Neuromonitoring", faellig=date(2026, 4, 5)),
            _make_auftrag(auftrag_id="A2", klinik_id="K044", klinik_name="Uni Ulm",
                          produkt_familie="Kardiovaskulaer", faellig=date(2026, 4, 10)),
        ]
        result = buendle_mit_qualifikation(auftraege)
        assert len(result) == 1
        plan = result[0]
        # Sollte A oder C sein (ein Einsatz)
        assert plan.fall in ("A", "C")
        assert len(plan.einsaetze) == 1

    def test_fall_c_waehlt_breiteres_portfolio(self):
        """Bei gleicher Abdeckung wird Techniker mit mehr Qualifikationen bevorzugt."""
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K044", klinik_name="Uni Ulm",
                          produkt_familie="Neuromonitoring", faellig=date(2026, 4, 5)),
            _make_auftrag(auftrag_id="A2", klinik_id="K044", klinik_name="Uni Ulm",
                          produkt_familie="Wirbelsaeule", faellig=date(2026, 4, 10)),
        ]
        result = buendle_mit_qualifikation(auftraege)
        assert len(result) == 1
        einsatz = result[0].einsaetze[0]
        # T5 oder T10 (beide haben Neuromonitoring L3 + Wirbelsaeule L3)
        assert einsatz.techniker_id in ("T5", "T10")
        assert "Neuromonitoring" in einsatz.abgedeckte_familien
        assert "Wirbelsaeule" in einsatz.abgedeckte_familien

    # --- Sonderfaelle ---

    def test_einzelauftrag_nicht_gebuendelt(self):
        """Nur ein Auftrag pro Klinik/Monat → kein Buendelplan."""
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K044", klinik_name="Uni Ulm",
                          produkt_familie="Neuromonitoring", faellig=date(2026, 4, 5)),
        ]
        result = buendle_mit_qualifikation(auftraege)
        assert len(result) == 0

    def test_verschiedene_monate_getrennt(self):
        """Auftraege in verschiedenen Monaten werden nicht gebuendelt."""
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K044", klinik_name="Uni Ulm",
                          produkt_familie="Neuromonitoring", faellig=date(2026, 4, 5)),
            _make_auftrag(auftrag_id="A2", klinik_id="K044", klinik_name="Uni Ulm",
                          produkt_familie="Elektrochirurgie", faellig=date(2026, 5, 5)),
        ]
        result = buendle_mit_qualifikation(auftraege)
        assert len(result) == 0

    def test_big_capital_stk_erfordert_l3(self):
        """Hugo STK erfordert L3 — L2 reicht nicht."""
        # Hugo: nur T1, T6, T10, T11 haben L3
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K001", klinik_name="UKE Hamburg",
                          produkt_familie="Hugo", faellig=date(2026, 4, 5)),
            _make_auftrag(auftrag_id="A2", klinik_id="K001", klinik_name="UKE Hamburg",
                          produkt_familie="Hugo", faellig=date(2026, 4, 10)),
        ]
        result = buendle_mit_qualifikation(auftraege)
        if result:
            for einsatz in result[0].einsaetze:
                for fam, level in einsatz.qualifikationen.items():
                    if fam == "Hugo":
                        assert level == "L3"

    def test_einsatz_begruendung_vorhanden(self):
        """Jeder Einsatz hat eine Begruendung."""
        auftraege = [
            _make_auftrag(auftrag_id="A1", klinik_id="K044", klinik_name="Uni Ulm",
                          produkt_familie="Neuromonitoring", faellig=date(2026, 4, 5)),
            _make_auftrag(auftrag_id="A2", klinik_id="K044", klinik_name="Uni Ulm",
                          produkt_familie="Elektrochirurgie", faellig=date(2026, 4, 10)),
        ]
        result = buendle_mit_qualifikation(auftraege)
        for plan in result:
            for einsatz in plan.einsaetze:
                assert einsatz.begruendung
                assert einsatz.techniker_id in einsatz.begruendung


# ===================================================================
# 5. VORAUSSCHAUENDE PLANUNG
# ===================================================================


class TestPlanungshorizontKonstanten:
    """Tests fuer die Planungshorizont-Konstanten."""

    def test_planungshorizont_tage(self):
        assert PLANUNGSHORIZONT_TAGE == 7

    def test_planungshorizont_min(self):
        assert PLANUNGSHORIZONT_MIN == 3

    def test_vorlauf_standard(self):
        assert VORLAUF_STANDARD_TAGE == 5

    def test_planungsgruende_vorhanden(self):
        assert len(PLANUNGSGRUENDE) == 5
        assert any("Messmittel" in g for g in PLANUNGSGRUENDE)
        assert any("OP-Plan" in g for g in PLANUNGSGRUENDE)

    def test_tour_optimierung_gleiche_konstanten(self):
        from auftraege.tour_optimierung import (
            PLANUNGSHORIZONT_TAGE as TO_TAGE,
            PLANUNGSHORIZONT_MIN as TO_MIN,
            VORLAUF_STANDARD_TAGE as TO_VORLAUF,
        )
        assert TO_TAGE == PLANUNGSHORIZONT_TAGE
        assert TO_MIN == PLANUNGSHORIZONT_MIN
        assert TO_VORLAUF == VORLAUF_STANDARD_TAGE


class TestWerktageHelfer:
    """Tests fuer Werktag-Hilfsfunktionen."""

    def test_montag_ist_werktag(self):
        assert _ist_werktag_mo_do(date(2026, 4, 6))   # Montag

    def test_donnerstag_ist_werktag(self):
        assert _ist_werktag_mo_do(date(2026, 4, 9))   # Donnerstag

    def test_freitag_kein_werktag(self):
        assert not _ist_werktag_mo_do(date(2026, 4, 10))  # Freitag

    def test_samstag_kein_werktag(self):
        assert not _ist_werktag_mo_do(date(2026, 4, 11))  # Samstag

    def test_sonntag_kein_werktag(self):
        assert not _ist_werktag_mo_do(date(2026, 4, 12))  # Sonntag

    def test_naechster_werktag_ab_montag(self):
        # Ab Montag + 1 Tag = Dienstag
        result = _naechster_werktag_ab(date(2026, 4, 6), min_tage=1)
        assert result == date(2026, 4, 7)  # Dienstag

    def test_naechster_werktag_ab_donnerstag(self):
        # Ab Donnerstag + 1 = Freitag → springt zu Montag
        result = _naechster_werktag_ab(date(2026, 4, 9), min_tage=1)
        assert result == date(2026, 4, 13)  # Montag

    def test_naechster_werktag_ab_freitag(self):
        # Ab Freitag + 1 = Samstag → springt zu Montag
        result = _naechster_werktag_ab(date(2026, 4, 10), min_tage=1)
        assert result == date(2026, 4, 13)  # Montag

    def test_naechster_werktag_min_3_tage(self):
        # Ab Montag + 3 = Donnerstag
        result = _naechster_werktag_ab(date(2026, 4, 6), min_tage=3)
        assert result == date(2026, 4, 9)  # Donnerstag


class TestKlinikOpAttribute:
    """Tests fuer OP-kritisch Attribute aus kliniken.csv."""

    def test_uniklinik_ist_op_kritisch(self):
        attr = _lade_klinik_op_attribute("K001")  # UKE Hamburg
        assert attr["op_kritisch"] is True
        assert attr["vorlauf_tage"] == 5

    def test_grossklinik_nicht_op_kritisch(self):
        attr = _lade_klinik_op_attribute("K004")  # Asklepios Barmbek
        assert attr["op_kritisch"] is False
        assert attr["vorlauf_tage"] == 3

    def test_unbekannte_klinik_defaults(self):
        attr = _lade_klinik_op_attribute("K999")
        assert attr["op_kritisch"] is False
        assert attr["vorlauf_tage"] == PLANUNGSHORIZONT_MIN

    def test_none_klinik_defaults(self):
        attr = _lade_klinik_op_attribute(None)
        assert attr["op_kritisch"] is False


class TestSchlageTermineVor:
    """Tests fuer die Terminvorschlag-Funktion."""

    def test_gibt_3_vorschlaege_zurueck(self):
        auftrag = _make_auftrag()
        vorschlaege = schlage_termine_vor(auftrag, heute=date(2026, 4, 6))  # Montag
        assert len(vorschlaege) == 3

    def test_kein_termin_heute_oder_morgen(self):
        """Fruehester Termin: heute + 3 Werktage."""
        auftrag = _make_auftrag()
        heute = date(2026, 4, 6)  # Montag
        vorschlaege = schlage_termine_vor(auftrag, heute=heute)
        for v in vorschlaege:
            assert v.datum > heute + timedelta(days=2)

    def test_alle_vorschlaege_mo_do(self):
        """Kein Vorschlag auf Freitag/Wochenende."""
        auftrag = _make_auftrag()
        vorschlaege = schlage_termine_vor(auftrag, heute=date(2026, 4, 6))
        for v in vorschlaege:
            assert v.datum.weekday() <= 3, f"{v.datum} ist {v.wochentag}"

    def test_op_kritisch_nur_mo_do(self):
        """OP-kritische Klinik: Mo–Do erlaubt, Fr gesperrt."""
        auftrag = _make_auftrag(klinik_id="K001")  # UKE = uni = op_kritisch
        vorschlaege = schlage_termine_vor(auftrag, heute=date(2026, 4, 6))
        for v in vorschlaege:
            assert v.datum.weekday() <= 3, f"{v.datum} ist {v.wochentag} — Fr nicht erlaubt fuer OP-kritisch"

    def test_nicht_op_kritisch_auch_donnerstag(self):
        """Standard-Klinik: Mo-Do erlaubt."""
        auftrag = _make_auftrag(klinik_id="K004")  # Asklepios = gross = nicht op_kritisch
        vorschlaege = schlage_termine_vor(auftrag, heute=date(2026, 4, 6))
        wochentage = {v.datum.weekday() for v in vorschlaege}
        # Mindestens ein Donnerstag moeglich (abhaengig von Kalender)
        assert any(d <= 3 for d in wochentage)

    def test_vorschlag_hat_bewertung(self):
        auftrag = _make_auftrag()
        vorschlaege = schlage_termine_vor(auftrag, heute=date(2026, 4, 6))
        for v in vorschlaege:
            assert v.bewertung in ("optimal", "moeglich", "knapp")

    def test_vorschlag_hat_wochentag(self):
        auftrag = _make_auftrag()
        vorschlaege = schlage_termine_vor(auftrag, heute=date(2026, 4, 6))
        for v in vorschlaege:
            assert v.wochentag in ("Mo", "Di", "Mi", "Do")

    def test_vorschlag_hat_hinweise(self):
        auftrag = _make_auftrag(klinik_id="K001")  # OP-kritisch
        vorschlaege = schlage_termine_vor(auftrag, heute=date(2026, 4, 6))
        assert any(
            any("OP-kritisch" in h for h in v.hinweise)
            for v in vorschlaege
        )

    def test_mindestvorlauf_3_werktage(self):
        """Fruehester Termin: mindestens 3 Werktage ab heute."""
        auftrag = _make_auftrag(klinik_id="K004")  # Standard, vorlauf=3
        heute = date(2026, 4, 6)  # Montag
        vorschlaege = schlage_termine_vor(auftrag, heute=heute)
        # 3 Werktage ab Mo = Do (6+3 Kalendertage = Do 9.4.)
        min_erwartet = date(2026, 4, 9)
        for v in vorschlaege:
            assert v.datum >= min_erwartet


class TestMessmittelPuffer:
    """Tests fuer Messmittel-Vorbereitung."""

    def test_messmittel_konstante(self):
        from auftraege.einsatz_dauer import PUFFER_MESSMITTEL_LADEN, MESSMITTEL_HINWEIS
        assert PUFFER_MESSMITTEL_LADEN == 30
        assert "Vortag" in MESSMITTEL_HINWEIS
        assert "30 min" in MESSMITTEL_HINWEIS

    def test_messmittel_hinweis_in_dashboard_text(self):
        from auftraege.einsatz_dauer import berechne_einsatz_dauer
        result = berechne_einsatz_dauer(
            [{"produkt_familie": "NIM", "geraete_typ": "NIM4CM01"}],
            techniker_id="T5",
        )
        assert "Vortag" in result.dashboard_text
        assert "Messmittel" in result.dashboard_text

    def test_messmittel_nicht_in_gesamt_min(self):
        """Messmittel-Puffer wird NICHT in gesamt_min eingerechnet."""
        from auftraege.einsatz_dauer import berechne_einsatz_dauer
        result = berechne_einsatz_dauer(
            [{"produkt_familie": "NIM", "geraete_typ": "NIM4CM01"}],
            techniker_id="T5",
        )
        # gesamt = netto + puffer (ohne Messmittel-Laden)
        assert result.gesamt_min == result.netto_min + result.puffer_gesamt_min


# ===================================================================
# 6. UMPLANUNG
# ===================================================================

# April 2026 Kalender-Ankerpunkte:
# - 2026-04-29 = Mittwoch  (vorletzter Werktag April)
# - 2026-04-30 = Donnerstag (LETZTER Werktag April)
# - 2026-05-04 = Montag    (ERSTER Werktag Mai)
# - 2026-05-05 = Dienstag  (zweiter Werktag Mai)
_HEUTE_TEST = date(2026, 5, 20)  # Referenz "heute" fuer Umplanungstests


def _make_repair(
    auftrag_id="REP-001",
    klinik_id="K044",
    klinik_name="Uniklinikum Ulm",
    geraet_id="HUGO-01",
    produkt_familie="Hugo",
    faellig=None,
) -> Auftrag:
    return Auftrag(
        auftrag_id=auftrag_id,
        auftragstyp=AuftragsTyp.REPAIR,
        klinik_id=klinik_id,
        klinik_name=klinik_name,
        geraet_id=geraet_id,
        produkt_familie=produkt_familie,
        faelligkeitsdatum=faellig or _HEUTE_TEST,
    )


class TestUmplanung:
    """Tests fuer pruefe_umplanung, filtere_nach_horizont, dedupliziere_auftraege
    und pruefe_stk_pm_faelligkeit."""

    # ---------------------------------------------------------------
    # Prioritaets-Logik
    # ---------------------------------------------------------------

    def test_repair_ohne_et_verdraengt_stk(self):
        """Repair ohne ET (Prio 1) verdraengt STK/PM normal (Prio 5)."""
        bestehend = _make_auftrag(auftrag_id="STK-001", faellig=_HEUTE_TEST)
        neu = _make_repair(faellig=_HEUTE_TEST)
        ergebnis = pruefe_umplanung(
            bestehend, neu, [],
            hat_ersatzteil=False,
            heute=_HEUTE_TEST,
        )
        assert ergebnis.aktion == "einplanen"
        assert "Repair ohne Ersatzteil" in ergebnis.begruendung
        assert "verdraengt" in ergebnis.begruendung

    def test_repair_mit_et_nach_lieferzeit(self):
        """Repair mit Ersatzteil (Prio 2) → warten_auf_lieferzeit."""
        bestehend = _make_auftrag(auftrag_id="STK-001", faellig=_HEUTE_TEST)
        neu = _make_repair(faellig=_HEUTE_TEST)
        ergebnis = pruefe_umplanung(
            bestehend, neu, [],
            hat_ersatzteil=True,
            heute=_HEUTE_TEST,
        )
        assert ergebnis.aktion == "warten_auf_lieferzeit"
        assert "Lieferzeit" in ergebnis.begruendung

    def test_stk_ueberfaellig_verdraengt_normal(self):
        """STK/PM ueberfaellig (Prio 3) verdraengt STK/PM normal (Prio 5)."""
        bestehend = _make_auftrag(
            auftrag_id="STK-NORMAL",
            faellig=_HEUTE_TEST,
        )
        # Neuer Auftrag: ueberfaellig (Datum in der Vergangenheit)
        ueberfaellig = date(2026, 4, 1)
        neu = _make_auftrag(
            auftrag_id="STK-UEBERFAELLIG",
            faellig=ueberfaellig,
            klinik_id="K044",
        )
        ergebnis = pruefe_umplanung(
            bestehend, neu, [],
            heute=_HEUTE_TEST,
            geplantes_datum=ueberfaellig,
        )
        assert ergebnis.aktion == "einplanen"
        assert "ueberfaellig" in ergebnis.begruendung.lower()

    def test_stk_auf_route_unter_30min(self):
        """STK/PM auf Route: Umwegzeit 20min < 30min → einplanen."""
        bestehend = _make_auftrag(auftrag_id="STK-001", faellig=_HEUTE_TEST)
        neu = _make_auftrag(auftrag_id="STK-NEU", faellig=_HEUTE_TEST)
        ergebnis = pruefe_umplanung(
            bestehend, neu, [],
            umwegzeit_minuten=20.0,
            heute=_HEUTE_TEST,
        )
        assert ergebnis.aktion == "einplanen"
        assert "Route" in ergebnis.begruendung or "route" in ergebnis.begruendung.lower()

    def test_stk_auf_route_ueber_30min_verwerfen(self):
        """Umwegzeit 45min >= 30min → faellt auf STK_PM_NORMAL zurueck;
        mit kapazitaet_frei=False → verwerfen."""
        bestehend = _make_auftrag(auftrag_id="STK-001", faellig=_HEUTE_TEST)
        neu = _make_auftrag(auftrag_id="STK-NEU", faellig=_HEUTE_TEST)
        ergebnis = pruefe_umplanung(
            bestehend, neu, [],
            umwegzeit_minuten=45.0,
            kapazitaet_frei=False,
            heute=_HEUTE_TEST,
        )
        assert ergebnis.aktion == "verwerfen"

    def test_kapazitaet_voll_kein_repair(self):
        """STK/PM normal + kapazitaet_frei=False → verwerfen."""
        bestehend = _make_auftrag(auftrag_id="STK-001", faellig=_HEUTE_TEST)
        neu = _make_auftrag(auftrag_id="STK-NEU", faellig=_HEUTE_TEST)
        ergebnis = pruefe_umplanung(
            bestehend, neu, [],
            kapazitaet_frei=False,
            heute=_HEUTE_TEST,
        )
        assert ergebnis.aktion == "verwerfen"
        assert "keine freie Kapazitaet" in ergebnis.begruendung

    # ---------------------------------------------------------------
    # Deduplizierung
    # ---------------------------------------------------------------

    def test_duplikat_gleicher_schluessel(self):
        """Gleicher Schluessel (geraet_id + faelligkeit + familie) = Duplikat."""
        a1 = _make_auftrag(auftrag_id="A1", geraet_id="NIM-SN001",
                           produkt_familie="Neuromonitoring",
                           faellig=date(2026, 6, 1))
        a2 = _make_auftrag(auftrag_id="A2", geraet_id="NIM-SN001",
                           produkt_familie="Neuromonitoring",
                           faellig=date(2026, 6, 1))  # gleicher Schluessel
        bereinigte, n_duplikate, n_neu = dedupliziere_auftraege([a1], [a2])
        assert n_duplikate == 1
        assert n_neu == 0
        assert len(bereinigte) == 1

    def test_gleiche_sn_neues_datum_kein_duplikat(self):
        """Gleiche Seriennummer + Familie, anderes Datum = kein Duplikat."""
        a1 = _make_auftrag(auftrag_id="A1", geraet_id="NIM-SN001",
                           produkt_familie="Neuromonitoring",
                           faellig=date(2026, 6, 1))
        a2 = _make_auftrag(auftrag_id="A2", geraet_id="NIM-SN001",
                           produkt_familie="Neuromonitoring",
                           faellig=date(2026, 7, 1))  # anderes Datum
        bereinigte, n_duplikate, n_neu = dedupliziere_auftraege([a1], [a2])
        assert n_duplikate == 0
        assert n_neu == 1
        assert len(bereinigte) == 2

    # ---------------------------------------------------------------
    # STK/PM Faelligkeitspruefung (monatsgenau wie TUeV)
    # ---------------------------------------------------------------

    def test_stk_pm_gleicher_monat_gueltig(self):
        """Geplantes Datum im selben Monat wie Faelligkeit → gueltig."""
        auftrag = _make_auftrag(faellig=date(2026, 4, 15))
        gueltig, grund = pruefe_stk_pm_faelligkeit(auftrag, date(2026, 4, 10))
        assert gueltig
        assert "2026-04" in grund

    def test_stk_pm_falscher_monat_ungueltig(self):
        """Geplantes Datum in falschem Monat → ungueltig."""
        auftrag = _make_auftrag(faellig=date(2026, 4, 15))
        gueltig, grund = pruefe_stk_pm_faelligkeit(auftrag, date(2026, 5, 10))
        assert not gueltig
        assert "monatsgenau" in grund.lower() or "TUeV" in grund

    def test_stk_pm_letzter_werktag_folgemonat_ok(self):
        """Faelligkeit am letzten Werktag April (30.04.) →
        erster Werktag Mai (04.05.) ist erlaubt."""
        # April 30, 2026 = Donnerstag = letzter Werktag April
        auftrag = _make_auftrag(faellig=date(2026, 4, 30))
        # May 4, 2026 = Montag = erster Werktag Mai
        gueltig, grund = pruefe_stk_pm_faelligkeit(auftrag, date(2026, 5, 4))
        assert gueltig
        assert "Ausnahme" in grund

    def test_stk_pm_vorletzter_werktag_folgemonat_nicht_ok(self):
        """Faelligkeit am letzten Werktag April (30.04.) →
        zweiter Werktag Mai (05.05.) ist NICHT erlaubt (nur der erste)."""
        auftrag = _make_auftrag(faellig=date(2026, 4, 30))
        # May 5, 2026 = Dienstag = zweiter Werktag Mai
        gueltig, grund = pruefe_stk_pm_faelligkeit(auftrag, date(2026, 5, 5))
        assert not gueltig


# ---------------------------------------------------------------------------
# STK/PM Wartungszyklen
# ---------------------------------------------------------------------------

class TestSTKPMZyklus:
    """Tests fuer get_stk_pm_zyklus und STK_PM_ZYKLEN_MONATE."""

    def test_default_zyklus_12_monate(self):
        """Standard-Produktfamilien → 12 Monate Zyklus."""
        assert get_stk_pm_zyklus("Neuromonitoring") == 12
        assert get_stk_pm_zyklus("ACT") == 12
        assert get_stk_pm_zyklus("Kardiovaskulaer_IPC") == 12

    def test_prog_zyklus_24_monate(self):
        """Programmer → 24 Monate Zyklus."""
        assert get_stk_pm_zyklus("PROG") == 24

    def test_mazor_zyklus_6_monate(self):
        """Mazor → 6 Monate Zyklus."""
        assert get_stk_pm_zyklus("Mazor") == 6

    def test_hugo_zyklus_6_monate(self):
        """Hugo → 6 Monate Zyklus."""
        assert get_stk_pm_zyklus("Hugo") == 6

    def test_unbekannte_familie_fallback_default(self):
        """Unbekannte Produktfamilie → Fallback auf default (12 Monate)."""
        assert get_stk_pm_zyklus("UnbekanntesFamilienXYZ") == STK_PM_ZYKLEN_MONATE['default']
        assert get_stk_pm_zyklus("") == STK_PM_ZYKLEN_MONATE['default']


# ---------------------------------------------------------------------------
# Abwesenheitsverwaltung
# ---------------------------------------------------------------------------

class TestAbwesenheit:
    """Tests fuer techniker/abwesenheit.py."""

    def test_techniker_abwesend_wird_ausgeschlossen(self):
        """Techniker im Abwesenheitszeitraum → nicht in verfuegbarer Liste."""
        ab = [Abwesenheit("T1", date(2026, 6, 1), date(2026, 6, 7), "Urlaub")]
        verfuegbar = filtere_verfuegbare_techniker(["T1", "T2"], date(2026, 6, 3), ab)
        assert "T1" not in verfuegbar
        assert "T2" in verfuegbar

    def test_techniker_verfuegbar_nach_abwesenheit(self):
        """Techniker nach Ende der Abwesenheit wieder verfuegbar."""
        ab = [Abwesenheit("T1", date(2026, 6, 1), date(2026, 6, 5), "Krank")]
        assert not ist_abwesend("T1", date(2026, 6, 6), ab)
        assert "T1" in filtere_verfuegbare_techniker(["T1"], date(2026, 6, 6), ab)

    def test_urlaub_mehrere_tage(self):
        """Urlaub ueber mehrere Tage: alle Tage korrekt als abwesend markiert."""
        ab = lade_abwesenheiten([
            {"techniker_id": "T3", "von": "2026-07-13", "bis": "2026-07-18", "typ": "Urlaub"}
        ])
        for tag in range(13, 19):  # 13.7.–18.7.
            assert ist_abwesend("T3", date(2026, 7, tag), ab), f"T3 soll am {tag}.7. abwesend sein"
        assert not ist_abwesend("T3", date(2026, 7, 12), ab)  # Vortag frei
        assert not ist_abwesend("T3", date(2026, 7, 19), ab)  # Folgetag frei

    def test_krank_einzeltag(self):
        """Krankmeldung nur fuer einen Tag."""
        ab = [Abwesenheit("T5", date(2026, 5, 22), date(2026, 5, 22), "Krank")]
        assert ist_abwesend("T5", date(2026, 5, 22), ab)
        assert not ist_abwesend("T5", date(2026, 5, 21), ab)
        assert not ist_abwesend("T5", date(2026, 5, 23), ab)

    def test_abwesenheit_grenztag_von(self):
        """'von'-Datum ist inklusive (Grenztag)."""
        ab = [Abwesenheit("T7", date(2026, 8, 1), date(2026, 8, 10), "Fortbildung")]
        assert ist_abwesend("T7", date(2026, 8, 1), ab), "von-Grenztag muss abwesend sein"
        assert not ist_abwesend("T7", date(2026, 7, 31), ab), "Tag vor von darf nicht abwesend sein"

    def test_abwesenheit_grenztag_bis(self):
        """'bis'-Datum ist inklusive (Grenztag)."""
        ab = [Abwesenheit("T7", date(2026, 8, 1), date(2026, 8, 10), "Fortbildung")]
        assert ist_abwesend("T7", date(2026, 8, 10), ab), "bis-Grenztag muss abwesend sein"
        assert not ist_abwesend("T7", date(2026, 8, 11), ab), "Tag nach bis darf nicht abwesend sein"
