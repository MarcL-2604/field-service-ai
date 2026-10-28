"""Tests: Gebietsoptimierung rechnet die Auslastung nach JEDER Verschiebung neu (F06).

Vorher wurde die Ausgangsauslastung einmal berechnet und blieb fix -- ein
Techniker konnte dadurch fast alle Kliniken an einen Nachbarn abgeben.
"""

from config import OPTIMIERUNG_AUSLASTUNGS_SCHWELLE, OPTIMIERUNG_MAX_ABGABE_ANTEIL
from reporting.dashboard import _berechne_gebietsmetriken, _verschiebe_kliniken
from tests.test_plz_uebersicht import _lade_demo_techniker

KAP = 1000.0   # Jahreskapazitaet in Stunden -> 1 h = 0,1 Prozentpunkte


def _kandidaten(anzahl: int, last: float, mehrfahrt=lambda i: 5.0, last2: float | None = None):
    return [
        {"id": f"K{i:03d}", "tid1": "A", "tid2": "B", "mehrfahrt": mehrfahrt(i),
         "last1": last, "last2": last if last2 is None else last2}
        for i in range(anzahl)
    ]


def _auslastung(last_h: dict, verschoben: list[dict]) -> tuple[float, float]:
    a = last_h["A"] - sum(v["last1"] for v in verschoben)
    b = last_h["B"] + sum(v["last2"] for v in verschoben)
    return a / KAP * 100, b / KAP * 100


class TestLiveAuslastung:
    def test_40_prozentpunkte_gleichen_sich_an_ohne_ueberholen(self):
        # A 70 %, B 30 %: 20 Kliniken je 35 h
        kand = _kandidaten(20, 35.0)
        last = {"A": 700.0, "B": 300.0}
        v = _verschiebe_kliniken(kand, last, {"A": 20, "B": 0}, KAP, max_abgabe_anteil=1.0)
        a, b = _auslastung(last, v)
        assert v, "bei 40 Prozentpunkten Unterschied muss verschoben werden"
        assert a - b < 40                    # naeher beieinander als vorher
        assert b <= a                        # Empfaenger ueberholt den Abgeber nicht
        # die Regel stoppt, sobald der Unterschied unter die Schwelle faellt
        assert a - b < OPTIMIERUNG_AUSLASTUNGS_SCHWELLE

    def test_grosse_kliniken_ueberholen_nicht(self):
        # Eine Klinik verschiebt 25 Prozentpunkte: 70/30 -> 45/55 wuerde ueberholen
        kand = _kandidaten(4, 250.0)
        last = {"A": 700.0, "B": 300.0}
        v = _verschiebe_kliniken(kand, last, {"A": 4, "B": 0}, KAP, max_abgabe_anteil=1.0)
        assert v == []

    def test_abgabe_ueber_30_prozent_wird_gekappt(self):
        # A 90 %, B 10 %: ohne Kappung wuerden ~11 von 30 Kliniken wechseln
        kand = _kandidaten(30, 30.0)
        last = {"A": 900.0, "B": 100.0}
        v = _verschiebe_kliniken(kand, last, {"A": 30, "B": 0}, KAP)
        assert OPTIMIERUNG_MAX_ABGABE_ANTEIL == 0.3
        assert len(v) == int(30 * OPTIMIERUNG_MAX_ABGABE_ANTEIL) == 9
        ungekappt = _verschiebe_kliniken(kand, last, {"A": 30, "B": 0}, KAP, max_abgabe_anteil=1.0)
        assert len(ungekappt) > len(v)

    def test_keine_verschiebung_unter_schwelle(self):
        for diff_h in (0.0, 100.0, 149.0):       # 0 / 10 / 14,9 Prozentpunkte
            last = {"A": 500.0 + diff_h, "B": 500.0}
            assert _verschiebe_kliniken(_kandidaten(10, 10.0), last, {"A": 10, "B": 0}, KAP,
                                        max_abgabe_anteil=1.0) == []

    def test_genau_schwelle_verschiebt(self):
        last = {"A": 650.0, "B": 500.0}           # exakt 15 Prozentpunkte
        v = _verschiebe_kliniken(_kandidaten(10, 10.0), last, {"A": 10, "B": 0}, KAP,
                                 max_abgabe_anteil=1.0)
        assert len(v) >= 1

    def test_geringste_mehrfahrt_zuerst(self):
        kand = _kandidaten(10, 10.0, mehrfahrt=lambda i: float(10 - i))   # K009 hat 1 Min.
        last = {"A": 900.0, "B": 100.0}
        v = _verschiebe_kliniken(kand, last, {"A": 10, "B": 0}, KAP)
        assert [x["id"] for x in v] == ["K009", "K008", "K007"]

    def test_mehrfahrt_ueber_grenze_wird_nicht_verschoben(self):
        kand = _kandidaten(10, 10.0, mehrfahrt=lambda i: 25.0)
        assert _verschiebe_kliniken(kand, {"A": 900.0, "B": 100.0}, {"A": 10, "B": 0}, KAP) == []

    def test_keine_ketten_empfaenger_gibt_nicht_ab(self):
        kand = _kandidaten(10, 10.0) + [
            {"id": "X1", "tid1": "B", "tid2": "C", "mehrfahrt": 1.0, "last1": 10.0, "last2": 10.0}]
        last = {"A": 900.0, "B": 600.0, "C": 100.0}
        v = _verschiebe_kliniken(kand, last, {"A": 10, "B": 10, "C": 0}, KAP, max_abgabe_anteil=1.0)
        gaben = {x["tid1"] for x in v}
        empf = {x["tid2"] for x in v}
        assert not (gaben & empf)


class TestEndToEndDemo:
    def setup_method(self):
        techniker = _lade_demo_techniker()
        self.akt, self.opt, _, _, _ = _berechne_gebietsmetriken(techniker)

    def test_demo_modus_funktioniert_und_verschiebt(self):
        assert sum(m["verschoben_gewonnen"] for m in self.opt) > 0

    def test_kein_techniker_gibt_mehr_als_obergrenze_ab(self):
        for a, o in zip(self.akt, self.opt):
            assert o["verschoben_abgegeben"] <= int(a["kliniken"] * OPTIMIERUNG_MAX_ABGABE_ANTEIL + 1e-9)

    def test_techniker_wird_nicht_entleert(self):
        for a, o in zip(self.akt, self.opt):
            if a["kliniken"]:
                assert o["kliniken"] >= 0.7 * a["kliniken"] - 1e-9 or o["verschoben_gewonnen"] > 0

    def test_abgaben_summieren_zu_gewonnenen(self):
        paare = [v for m in self.opt for v in m["abgaben"]]
        assert sum(v["anzahl"] for v in paare) == sum(m["verschoben_gewonnen"] for m in self.opt)
        assert sum(v["anzahl"] for v in paare) == sum(m["verschoben_abgegeben"] for m in self.opt)
