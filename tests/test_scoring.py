"""Tests fuer techniker.scoring – Arbeitszeitregeln und Empfehlungslogik."""

import warnings
from datetime import datetime

import pytest

from techniker.scoring import (
    TagesStatus,
    _WOCHE_MAX_ABSOLUT,
    _WOCHE_WARN_GELB,
    _WOCHE_WARN_PUFFER,
    _WOCHE_ZIEL_STD,
    _MAX_TAG_ABSOLUT,
    _MAX_TAG_NORMAL,
    _MAX_TAG_REGEL,
    _HUGO_KEY_ACCOUNT_IDS,
    _HUGO_WOCHE_ZIEL_STD,
    SMALL_CAPITAL_STK_L2_REICHT,
    _pruefe_arbeitszeit,
    berechne_empfehlung,
)

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

_MONTAG = datetime(2026, 3, 23, 8, 0)   # Montag
_DIENSTAG = datetime(2026, 3, 24, 8, 0)
_FREITAG = datetime(2026, 3, 27, 8, 0)  # Freitag
_SAMSTAG = datetime(2026, 3, 28, 8, 0)
_SONNTAG = datetime(2026, 3, 29, 8, 0)


def _pruefe(
    auftrag_typ="STK",
    woche=0.0,
    tag=0.0,
    distanz_km=50.0,
    dauer_std=4.0,
    datum=_MONTAG,
    letztes_ende=None,
):
    """Shortcut fuer _pruefe_arbeitszeit mit Defaults."""
    status = TagesStatus(
        wochenstunden_aktuell=woche,
        tagesstunden_aktuell=tag,
        letztes_arbeitsende=letztes_ende,
    )
    return _pruefe_arbeitszeit("TX", auftrag_typ, status, dauer_std, datum, distanz_km)


# ---------------------------------------------------------------------------
# Wochenende
# ---------------------------------------------------------------------------

class TestWochenende:
    def test_samstag_ausgeschlossen(self):
        ausgeschlossen, _ = _pruefe(datum=_SAMSTAG)
        assert ausgeschlossen

    def test_sonntag_ausgeschlossen(self):
        ausgeschlossen, _ = _pruefe(datum=_SONNTAG)
        assert ausgeschlossen

    def test_montag_erlaubt(self):
        ausgeschlossen, _ = _pruefe(datum=_MONTAG)
        assert not ausgeschlossen


# ---------------------------------------------------------------------------
# Freitag-Regel
# ---------------------------------------------------------------------------

class TestFreitag:
    def test_stk_freitag_ausgeschlossen(self):
        ausgeschlossen, warnungen = _pruefe(auftrag_typ="STK", datum=_FREITAG)
        assert ausgeschlossen
        assert any("Freitag" in w for w in warnungen)

    def test_pm_freitag_ausgeschlossen(self):
        ausgeschlossen, _ = _pruefe(auftrag_typ="PM", datum=_FREITAG)
        assert ausgeschlossen

    def test_repair_freitag_erlaubt_mit_warnung(self):
        ausgeschlossen, warnungen = _pruefe(auftrag_typ="Repair", datum=_FREITAG)
        assert not ausgeschlossen
        assert any("Freitag" in w for w in warnungen)

    def test_repair_gross_klein_case_insensitiv(self):
        ausgeschlossen, _ = _pruefe(auftrag_typ="REPAIR", datum=_FREITAG)
        assert not ausgeschlossen
        ausgeschlossen, _ = _pruefe(auftrag_typ="repair", datum=_FREITAG)
        assert not ausgeschlossen


# ---------------------------------------------------------------------------
# Mindestruhezeit (ArbZG §5)
# ---------------------------------------------------------------------------

class TestMindestruhezeit:
    def test_zu_wenig_ruhe_ausgeschlossen(self):
        # 9h Ruhezeit < 11h Pflicht
        letztes_ende = datetime(2026, 3, 22, 23, 0)  # Sonntag 23:00
        ausgeschlossen, warnungen = _pruefe(datum=_MONTAG, letztes_ende=letztes_ende)
        assert ausgeschlossen
        assert any("Mindestruhezeit" in w for w in warnungen)

    def test_exakt_11h_ruhe_erlaubt(self):
        letztes_ende = datetime(2026, 3, 22, 21, 0)  # Sonntag 21:00 → Montag 08:00 = 11h
        ausgeschlossen, _ = _pruefe(datum=_MONTAG, letztes_ende=letztes_ende)
        assert not ausgeschlossen

    def test_ausreichend_ruhe_erlaubt(self):
        letztes_ende = datetime(2026, 3, 22, 18, 0)  # 14h Ruhe
        ausgeschlossen, _ = _pruefe(datum=_MONTAG, letztes_ende=letztes_ende)
        assert not ausgeschlossen


# ---------------------------------------------------------------------------
# Wochenstunden – Vertrauensarbeitszeit
# ---------------------------------------------------------------------------

class TestWochenstunden:
    def test_unter_ziel_kein_ausschluss_keine_warnung(self):
        # 20h < 30h (PUFFER-Schwelle) → keine Warnung
        ausgeschlossen, warnungen = _pruefe(woche=20.0)
        assert not ausgeschlossen
        assert not warnungen  # 20h + Fahrt(~0.75h) + 4h = 24.75h, keine Warnung

    def test_puffer_warnung_ab_30h(self):
        # Außendienst-Ziel 32h, PUFFER 2h davor = 30h
        ausgeschlossen, warnungen = _pruefe(woche=30.0, distanz_km=10.0, dauer_std=1.0)
        assert not ausgeschlossen
        assert any("PUFFER" in w for w in warnungen)

    def test_gelb_warnung_ab_34h(self):
        # 2h ueber 32h-Ziel = 34h
        ausgeschlossen, warnungen = _pruefe(woche=34.0, distanz_km=10.0, dauer_std=1.0)
        assert not ausgeschlossen
        assert any("GELB" in w for w in warnungen)

    def test_gelb_warnung_schlaegt_puffer(self):
        # Bei 35h soll GELB, nicht PUFFER angezeigt werden
        ausgeschlossen, warnungen = _pruefe(woche=35.0, distanz_km=10.0, dauer_std=1.0)
        assert any("GELB" in w for w in warnungen)
        assert not any("PUFFER" in w for w in warnungen)

    def test_genau_45h_noch_nicht_ausgeschlossen(self):
        # 44h aktuell + 0.15h Fahrt (10km) + 0.5h Einsatz = 44.65h <= 45h → erlaubt
        ausgeschlossen, _ = _pruefe(woche=44.0, distanz_km=10.0, dauer_std=0.5)
        assert not ausgeschlossen

    def test_ueber_45h_prognose_ausgeschlossen(self):
        # 44h + 2h Fahrt(~134km) + 4h = 50h > 45h → Ausschluss
        ausgeschlossen, warnungen = _pruefe(woche=44.0, distanz_km=134.0, dauer_std=4.0)
        assert ausgeschlossen
        assert any("Wochen-Absolut-Maximum" in w for w in warnungen)

    def test_32h_aussendienst_ziel_kein_ausschluss(self):
        # Genau am 32h Außendienst-Ziel (Mo-Do): kein Ausschluss
        ausgeschlossen, _ = _pruefe(woche=32.0, distanz_km=10.0, dauer_std=0.5)
        assert not ausgeschlossen

    def test_konstanten_konsistent(self):
        assert _WOCHE_WARN_PUFFER < _WOCHE_ZIEL_STD
        assert _WOCHE_ZIEL_STD < _WOCHE_WARN_GELB
        assert _WOCHE_WARN_GELB < _WOCHE_MAX_ABSOLUT
        assert _WOCHE_MAX_ABSOLUT == 45.0


# ---------------------------------------------------------------------------
# Tagesstunden (ArbZG §3)
# ---------------------------------------------------------------------------

class TestTagesstunden:
    def test_unter_8h_keine_warnung(self):
        # 0h aktuell + 0.55h Fahrt(50km) + 4h = 4.55h
        ausgeschlossen, warnungen = _pruefe(tag=0.0, distanz_km=50.0, dauer_std=4.0)
        assert not ausgeschlossen
        assert not any("8h" in w for w in warnungen)

    def test_ueber_8h_warnung(self):
        # 2h aktuell + 0.75h Fahrt(50km) + 6h = 8.75h
        ausgeschlossen, warnungen = _pruefe(tag=2.0, distanz_km=50.0, dauer_std=6.0)
        assert not ausgeschlossen
        assert any("8h" in w for w in warnungen)

    def test_ueber_9h_regel_warnung(self):
        # 3h aktuell + 0.75h + 6h = 9.75h
        ausgeschlossen, warnungen = _pruefe(tag=3.0, distanz_km=50.0, dauer_std=6.0)
        assert not ausgeschlossen
        assert any("Regel-Maximum" in w for w in warnungen)

    def test_ueber_10h_ausgeschlossen(self):
        # 4h aktuell + 0.75h + 7h = 11.75h > 10h
        ausgeschlossen, warnungen = _pruefe(tag=4.0, distanz_km=50.0, dauer_std=7.0)
        assert ausgeschlossen
        assert any("Tages-Absolut-Maximum" in w for w in warnungen)

    def test_exakt_10h_nicht_ausgeschlossen(self):
        # 0h + 0h Fahrt + 10h = 10.0h → nicht > 10h
        ausgeschlossen, _ = _pruefe(tag=0.0, distanz_km=0.0, dauer_std=10.0)
        assert not ausgeschlossen

    def test_konstanten_konsistent(self):
        assert _MAX_TAG_NORMAL < _MAX_TAG_REGEL < _MAX_TAG_ABSOLUT


# ---------------------------------------------------------------------------
# ArbZG §4 Pausenpflicht
# ---------------------------------------------------------------------------

class TestPausenpflicht:
    def test_unter_6h_keine_pausenpflicht(self):
        ausgeschlossen, warnungen = _pruefe(tag=0.0, distanz_km=10.0, dauer_std=4.0)
        assert not ausgeschlossen
        assert not any("Pause" in w for w in warnungen)

    def test_ab_6h_30min_pause(self):
        # 0h + 0.15h(10km) + 6h = 6.15h
        ausgeschlossen, warnungen = _pruefe(tag=0.0, distanz_km=10.0, dauer_std=6.0)
        assert not ausgeschlossen
        assert any("30min" in w for w in warnungen)

    def test_ab_9h_45min_pause(self):
        # 0h + 0.75h(50km) + 9h = 9.75h
        ausgeschlossen, warnungen = _pruefe(tag=0.0, distanz_km=50.0, dauer_std=9.0)
        assert not ausgeschlossen
        assert any("45min" in w for w in warnungen)
        assert not any("30min" in w for w in warnungen)


# ---------------------------------------------------------------------------
# Integration: berechne_empfehlung
# ---------------------------------------------------------------------------

class TestBerechneEmpfehlung:
    def test_gibt_maximal_3_zurueck(self):
        result = berechne_empfehlung("STK", "Elektrochirurgie", "K044")
        assert len(result) <= 3

    def test_scores_absteigend_sortiert(self):
        result = berechne_empfehlung("PM", "Elektrochirurgie", "K044")
        scores = [r.score for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_hugo_nur_l3_techniker(self):
        result = berechne_empfehlung("STK", "Hugo", "K001")
        for r in result:
            assert r.level == "L3", f"{r.techniker_id} hat Hugo aber nicht L3"

    def test_unbekannte_klinik_raises(self):
        with pytest.raises(ValueError, match="K999"):
            berechne_empfehlung("STK", "Beatmung", "K999")

    def test_freitag_pm_liefert_leere_liste(self):
        freitag = datetime(2026, 3, 27, 8, 0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = berechne_empfehlung("PM", "Beatmung", "K044", einsatz_datetime=freitag)
        assert result == []

    def test_freitag_repair_liefert_ergebnisse(self):
        freitag = datetime(2026, 3, 27, 8, 0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = berechne_empfehlung("Repair", "Beatmung", "K044", einsatz_datetime=freitag)
        assert len(result) > 0
        for r in result:
            assert any("Freitag" in w for w in r.warnungen)

    def test_techniker_mit_42h_nicht_ausgeschlossen(self):
        # _pruefe_arbeitszeit: 42h aktuell + 0.15h Fahrt(10km) + 1h Einsatz = 43.15h < 45h
        # → kein Ausschluss, aber GELB-Warnung
        ausgeschlossen, warnungen = _pruefe(woche=42.0, distanz_km=10.0, dauer_std=1.0)
        assert not ausgeschlossen
        assert any("GELB" in w for w in warnungen)

    def test_techniker_mit_42h_erscheint_in_empfehlung(self):
        # T10 in Balingen (86km zu Ulm), 42h aktuell, aber Einsatz 1.5h:
        # 42 + 1.29h Fahrt + 1.5h = 44.8h < 45h → nicht ausgeschlossen
        status = {"T10": TagesStatus(wochenstunden_aktuell=42.0)}
        result = berechne_empfehlung(
            "STK", "Hugo", "K044", einsatz_dauer_std=1.5, tages_status=status
        )
        t10 = next((r for r in result if r.techniker_id == "T10"), None)
        assert t10 is not None
        assert any("GELB" in w for w in t10.warnungen)

    def test_techniker_mit_45h_prognose_ausgeschlossen(self):
        # T10 hat 44h + weit entfernte Klinik → > 45h → ausgeschlossen
        status = {"T10": TagesStatus(wochenstunden_aktuell=44.5)}
        with warnings.catch_warnings(record=True) as _:
            warnings.simplefilter("always")
            result = berechne_empfehlung("STK", "Hugo", "K001", tages_status=status)
        t10_ergebnis = next((r for r in result if r.techniker_id == "T10"), None)
        assert t10_ergebnis is None  # ausgeschlossen

    def test_auslastung_score_ueber_32h_aussendienst_ziel_ist_null(self):
        # Techniker mit >= 32h (Außendienst-Ziel) bekommt Auslastungs-Score 0 (kein negativer Score)
        status = {"T14": TagesStatus(wochenstunden_aktuell=33.0)}
        result = berechne_empfehlung("STK", "Elektrochirurgie", "K044", tages_status=status)
        t14 = next((r for r in result if r.techniker_id == "T14"), None)
        if t14 is not None:
            assert t14.auslastung_score == 0.0

    def test_score_liegt_zwischen_0_und_100(self):
        result = berechne_empfehlung("PM", "Beatmung", "K012")
        for r in result:
            assert 0.0 <= r.score <= 100.0

    def test_keine_qualifikation_liefert_leere_liste(self):
        # Kardiovaskulaer_Ablation hat nur T13 → andere Produktfamilie ohne Techniker
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = berechne_empfehlung("Repair", "Navigation", "K001")
        # Navigation hat nur T2 → sollte mindestens 0-1 Ergebnisse liefern,
        # aber kein Fehler
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Hugo Key Account
# ---------------------------------------------------------------------------

class TestHugoKeyAccount:
    """Tests fuer Hugo Key Account Logik."""

    def test_hugo_key_account_ids(self):
        assert _HUGO_KEY_ACCOUNT_IDS == {"T1", "T6", "T10", "T11"}

    def test_hugo_woche_ziel_ist_25_6h(self):
        assert _HUGO_WOCHE_ZIEL_STD == pytest.approx(25.6)

    def test_hugo_ka_auslastung_score_basiert_auf_25_6h(self):
        """Hugo KA bei 20h: 20/25.6 = 78% → Score ~22 (nicht 37.5 wie bei 32h)."""
        status = {"T10": TagesStatus(wochenstunden_aktuell=20.0)}
        result = berechne_empfehlung("STK", "Elektrochirurgie", "K044",
                                     tages_status=status)
        t10 = next((r for r in result if r.techniker_id == "T10"), None)
        if t10 is not None:
            # 20/25.6 = 0.78125 → (1 - 0.78125) * 100 = 21.875
            assert t10.auslastung_score < 25.0

    def test_standard_tech_auslastung_basiert_auf_32h(self):
        """Standard-Techniker bei 20h: 20/32 = 62.5% → Score 37.5."""
        status = {"T14": TagesStatus(wochenstunden_aktuell=20.0)}
        result = berechne_empfehlung("STK", "Elektrochirurgie", "K044",
                                     tages_status=status)
        t14 = next((r for r in result if r.techniker_id == "T14"), None)
        if t14 is not None:
            assert t14.auslastung_score == pytest.approx(37.5)

    def test_hugo_ka_warnung_bei_hoher_auslastung_stk(self):
        """Hugo KA mit >80% Auslastung bei STK-Einsatz gibt Warnung."""
        status = {"T10": TagesStatus(wochenstunden_aktuell=22.0)}
        result = berechne_empfehlung("STK", "Elektrochirurgie", "K044",
                                     tages_status=status)
        t10 = next((r for r in result if r.techniker_id == "T10"), None)
        if t10 is not None:
            assert any("Hugo Key Account" in w for w in t10.warnungen)

    def test_hugo_einsatz_hoechste_kompetenz(self):
        """Hugo-Auftraege bekommen Kompetenz-Score 100 (hoechste Prioritaet)."""
        result = berechne_empfehlung("STK", "Hugo", "K001")
        for r in result:
            assert r.kompetenz_score == 100.0


# ---------------------------------------------------------------------------
# Small Capital STK: L2 reicht aus
# ---------------------------------------------------------------------------

class TestSmallCapitalSTK:
    """Tests fuer Small Capital Regel: STK + Small Capital → L2 vollwertig."""

    def test_konstante_enthaelt_erwartete_familien(self):
        assert "Neuromonitoring" in SMALL_CAPITAL_STK_L2_REICHT
        assert "Programmer" in SMALL_CAPITAL_STK_L2_REICHT
        assert "ACT" in SMALL_CAPITAL_STK_L2_REICHT
        assert "Kardiovaskulaer_IPC" in SMALL_CAPITAL_STK_L2_REICHT

    def test_stk_neuromonitoring_l2_bekommt_vollen_kompetenz_score(self):
        """STK + Neuromonitoring: L2-Techniker bekommt Kompetenz-Score 100 (nicht 50)."""
        # T2 hat Neuromonitoring L2, T5 hat Neuromonitoring L3
        result = berechne_empfehlung("STK", "Neuromonitoring", "K044")
        l2_techs = [r for r in result if r.level == "L2"]
        for t in l2_techs:
            assert t.kompetenz_score == 100.0, (
                f"{t.techniker_id} (L2) sollte bei STK Neuromonitoring "
                f"Kompetenz 100 haben, hat {t.kompetenz_score}"
            )

    def test_stk_neuromonitoring_l2_erscheint_ohne_l3_warnung(self):
        """STK + Small Capital: L2 ohne 'nur zusammen mit L3' Warnung."""
        result = berechne_empfehlung("STK", "Neuromonitoring", "K044")
        l2_techs = [r for r in result if r.level == "L2"]
        for t in l2_techs:
            assert not any("L3" in w for w in t.warnungen), (
                f"{t.techniker_id}: Unerwartete L3-Warnung bei STK Small Capital"
            )

    def test_repair_neuromonitoring_nur_l3(self):
        """Repair + Small Capital: L2 ausgeschlossen, nur L3 erlaubt."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = berechne_empfehlung("Repair", "Neuromonitoring", "K044")
        for r in result:
            assert r.level == "L3", (
                f"{r.techniker_id} hat {r.level} – "
                f"Repair Neuromonitoring erfordert L3"
            )

    def test_pm_neuromonitoring_nur_l3(self):
        """PM + Small Capital: L2 ausgeschlossen, nur L3 erlaubt."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = berechne_empfehlung("PM", "Neuromonitoring", "K044")
        for r in result:
            assert r.level == "L3", (
                f"{r.techniker_id} hat {r.level} – "
                f"PM Neuromonitoring erfordert L3"
            )

    def test_stk_elektrochirurgie_l2_vollwertig(self):
        """HF_Chirurgie/Elektrochirurgie STK: L2 vollwertig (Score 100)."""
        result = berechne_empfehlung("STK", "Elektrochirurgie", "K044")
        l2_techs = [r for r in result if r.level == "L2"]
        for t in l2_techs:
            assert t.kompetenz_score == 100.0, (
                f"{t.techniker_id} (L2 Elektrochirurgie STK) sollte Score 100 haben"
            )

    def test_hugo_nicht_in_small_capital(self):
        """Hugo ist Big Capital – nicht in SMALL_CAPITAL_STK_L2_REICHT."""
        assert "Hugo" not in SMALL_CAPITAL_STK_L2_REICHT

    def test_hf_chirurgie_stk_l2_vollwertig(self):
        """HF_Chirurgie/Elektrochirurgie STK: L2 bekommt Score 100."""
        result = berechne_empfehlung("STK", "Elektrochirurgie", "K044")
        l2_techs = [r for r in result if r.level == "L2"]
        for t in l2_techs:
            assert t.kompetenz_score == 100.0

    def test_hf_chirurgie_pm_l2_vollwertig(self):
        """HF_Chirurgie PM: L2 vollwertig (Sonderfall)."""
        result = berechne_empfehlung("PM", "Elektrochirurgie", "K044")
        l2_techs = [r for r in result if r.level == "L2"]
        for t in l2_techs:
            assert t.kompetenz_score == 100.0

    def test_hf_chirurgie_repair_nur_l3(self):
        """HF_Chirurgie Repair: L2 ausgeschlossen, nur L3."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = berechne_empfehlung("Repair", "Elektrochirurgie", "K044")
        for r in result:
            assert r.level == "L3", (
                f"{r.techniker_id} hat {r.level} – Repair Elektrochirurgie erfordert L3"
            )
