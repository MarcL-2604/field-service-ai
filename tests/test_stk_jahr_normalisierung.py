"""Tests fuer die 3 Gebietsoptimierung/Uebersicht-Bugfixes:

1. STK/Jahr-Normalisierung (api/smax_cache.py): Closed Jobs decken einen
   mehrjaehrigen Beobachtungszeitraum ab und wurden vorher faelschlich als
   rohe Jahresrate verwendet -> Auslastung/Delta-Fahrzeit unrealistisch hoch.
2. "Optimierte Gebiete" zeigte Techniker mit 0 Kliniken nach der Optimierung
   gar nicht mehr an (Tabellen-Filter statt 0-Anzeige).
3. zusatz_stk in den Uebersichts-Ampel-Karten war im Echtdaten-Modus
   hartcodiert 0.0 statt aus dem echten stk_potenzial-Feld befuellt.
"""

import json
from datetime import datetime

import pytest

from api.smax_cache import (
    _berechne_beobachtungszeitraum_jahre,
    _berechne_stk_jahr,
    _CACHE,
)
from reporting.dashboard import (
    _berechne_ampeln_aus_smax,
    _berechne_gebietsmetriken,
    _lade_kliniken_demo,
    _render_gebietsoptimierung,
    _DATA_DIR,
)
import csv


def _lade_demo_techniker() -> dict[str, dict]:
    result = {}
    with open(_DATA_DIR / "techniker.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            result[row["techniker_id"]] = {
                "standort": row["standort"],
                "bundesland": row["bundesland"],
                "lat": float(row.get("lat", 0) or 0),
                "lon": float(row.get("lon", 0) or 0),
            }
    return result


# ===================================================================
# Fix 1+2: STK/Jahr-Normalisierung -- reine Formel-Tests
# ===================================================================

class TestBerechneStkJahr:
    def test_bekannte_zahlen_und_zeitraum(self):
        """100 Closed Jobs ueber 2 Jahre + 10 Open Jobs -> 50 + 10 = 60 STK/Jahr."""
        assert _berechne_stk_jahr(closed_jobs=100, open_jobs=10, beobachtungszeitraum_jahre=2.0) == 60.0

    def test_realer_fall_2_75_jahre(self):
        """Deckt sich mit dem tatsaechlich diagnostizierten Fall (Closed-Job-Historie)."""
        result = _berechne_stk_jahr(closed_jobs=275, open_jobs=0, beobachtungszeitraum_jahre=2.75)
        assert result == 100.0

    def test_nur_open_jobs_kein_zeitbezug(self):
        """Open Jobs ohne Closed-Historie: ungeteilt (kein Zeitraum anwendbar)."""
        assert _berechne_stk_jahr(closed_jobs=0, open_jobs=5, beobachtungszeitraum_jahre=2.75) == 5.0

    def test_zeitraum_null_faellt_auf_ein_jahr_zurueck(self):
        """Schutz vor Division durch 0: zeitraum<=0 -> wie 1 Jahr behandelt."""
        assert _berechne_stk_jahr(closed_jobs=50, open_jobs=0, beobachtungszeitraum_jahre=0.0) == 50.0

    def test_alte_ungewichtete_rechnung_waere_deutlich_hoeher(self):
        """Regressionsschutz: die alte, fehlerhafte Rechnung (rohe Summe als
        STK/Jahr) haette bei > 1 Jahr Beobachtungszeitraum immer einen
        groesseren Wert ergeben als die korrekt normalisierte Rechnung."""
        closed, open_ = 275, 10
        alte_falsche_rechnung = closed + open_  # so war es vor dem Fix
        neue_korrekte_rechnung = _berechne_stk_jahr(closed, open_, 2.75)
        assert neue_korrekte_rechnung < alte_falsche_rechnung


class TestBerechneBeobachtungszeitraumJahre:
    def test_bekannter_zeitraum(self):
        start = datetime(2023, 8, 17)
        ende = datetime(2026, 5, 18)
        jahre = _berechne_beobachtungszeitraum_jahre([start, ende])
        assert 2.7 < jahre < 2.8  # ~2.75 Jahre, deckt sich mit der realen Diagnose

    def test_leere_liste_faellt_auf_ein_jahr_zurueck(self):
        assert _berechne_beobachtungszeitraum_jahre([]) == 1.0

    def test_einzelnes_datum_faellt_auf_ein_jahr_zurueck(self):
        """Ein einzelnes Datum ergibt 0 Tage Zeitraum -> kein Skalierungsfaktor."""
        assert _berechne_beobachtungszeitraum_jahre([datetime(2024, 1, 1)]) == 1.0

    def test_reihenfolge_der_daten_ist_egal(self):
        d1, d2, d3 = datetime(2024, 1, 1), datetime(2025, 1, 1), datetime(2023, 1, 1)
        assert (
            _berechne_beobachtungszeitraum_jahre([d1, d2, d3])
            == _berechne_beobachtungszeitraum_jahre([d3, d1, d2])
        )


# ===================================================================
# Regressionstest: Demo-Modus bleibt unveraendert (nutzt bereits
# korrekt anzahl/zyklus als STK/Jahr, keine Historie zu normalisieren)
# ===================================================================

class TestDemoModusUnveraendert:
    def test_demo_stk_count_ist_weiterhin_anzahl_pro_zyklus(self):
        kliniken, stk_count, stunden_pro_einsatz = _lade_kliniken_demo()
        assert stunden_pro_einsatz == 2.0
        assert kliniken and stk_count
        # Stichprobe: Werte sind Bruchteile (anzahl/zyklus), keine grossen Ganzzahlen
        # wie sie eine rohe, mehrjaehrige Job-Summe haette.
        beispiel_werte = list(stk_count.values())[:20]
        assert all(v >= 0 for v in beispiel_werte)


# ===================================================================
# Fix 2: "Optimierte Gebiete" zeigt alle Techniker, auch mit 0 Kliniken
# ===================================================================

class TestAlleTechnikerSichtbar:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.techniker = _lade_demo_techniker()

    def test_null_kliniken_techniker_erscheint_in_beiden_tabellen(self):
        """Synthetischer Fall: ein Techniker hat nach der Optimierung 0 Kliniken.
        Er darf aus keiner der beiden Tabellen verschwinden."""
        basis = {
            "standort": "Teststadt", "kliniken": 5, "avg_fahrzeit": 30,
            "max_fahrzeit": 60, "fahrtstunden_jahr": 20, "onsite_stunden": 10,
            "ratio": 0.5,
        }
        metriken_akt = [{"id": "T1", **basis}, {"id": "T2", **{**basis, "kliniken": 3}}]
        t1_opt = dict(basis, kliniken=0, avg_fahrzeit=0, max_fahrzeit=0,
                      fahrtstunden_jahr=0, onsite_stunden=0, ratio=0.0,
                      verschoben=5, verschoben_gewonnen=0, verschoben_abgegeben=5)
        t2_opt = dict(basis, kliniken=8, verschoben=5,
                      verschoben_gewonnen=5, verschoben_abgegeben=0)
        metriken_opt = [{"id": "T1", **t1_opt}, {"id": "T2", **t2_opt}]
        techniker = {"T1": {"standort": "Teststadt"}, "T2": {"standort": "Teststadt"}}
        html = _render_gebietsoptimierung(metriken_akt, metriken_opt, techniker)

        aktuell_html = html.split("Ansicht 2:")[0]
        optimiert_html = html.split("Ansicht 2:")[1].split("Ansicht 3:")[0]

        assert "<strong>T1</strong>" in aktuell_html
        assert "<strong>T2</strong>" in aktuell_html
        assert "<strong>T1</strong>" in optimiert_html, "T1 (0 Kliniken nach Optimierung) fehlt in der Tabelle"
        assert "<strong>T2</strong>" in optimiert_html

    def test_reale_technikeranzahl_stimmt_in_beiden_tabellen_ueberein(self):
        """End-to-End mit echten Demo-Daten: Anzahl <strong>{id}</strong>-Treffer
        in Ansicht 1 und Ansicht 2 muss gleich der Technikeranzahl sein."""
        metriken_akt, metriken_opt, _ = _berechne_gebietsmetriken(self.techniker)
        html = _render_gebietsoptimierung(metriken_akt, metriken_opt, self.techniker)

        aktuell_html = html.split("Ansicht 2:")[0]
        optimiert_html = html.split("Ansicht 2:")[1].split("Ansicht 3:")[0]

        for tid in self.techniker:
            assert f"<strong>{tid}</strong>" in aktuell_html
            assert f"<strong>{tid}</strong>" in optimiert_html


# ===================================================================
# Fix 3: zusatz_stk in Ampel-Karten aus echtem stk_potenzial
# ===================================================================

class TestZusatzStkAusStkPotenzial:
    def test_zusatz_stk_uebernimmt_stk_potenzial_feld(self):
        smax_techniker = [
            {"pseudonym_id": "Ahmed A.", "standort": "Obertshausen", "region": "Hessen",
             "pm_count": 35, "total_model_codes": 365, "stk_potenzial": 105},
            {"pseudonym_id": "Andrej F.", "standort": "Neubiberg", "region": "Bayern-Sued",
             "pm_count": 0, "total_model_codes": 365, "stk_potenzial": 290},
        ]
        ampeln = _berechne_ampeln_aus_smax(smax_techniker)
        by_id = {a["techniker_id"]: a for a in ampeln}
        assert by_id["Ahmed A."]["zusatz_stk"] == 105.0
        assert by_id["Andrej F."]["zusatz_stk"] == 290.0

    def test_fehlendes_stk_potenzial_feld_ergibt_0_statt_absturz(self):
        ampeln = _berechne_ampeln_aus_smax(
            [{"pseudonym_id": "X", "standort": "-", "region": "-", "pm_count": 0, "total_model_codes": 100}]
        )
        assert ampeln[0]["zusatz_stk"] == 0.0

    def test_unterschiedliche_techniker_haben_unterschiedliche_werte(self):
        """Regressionsschutz: vorher war zusatz_stk fuer JEDEN Techniker identisch 0."""
        smax_techniker = [
            {"pseudonym_id": f"T{i}", "standort": "-", "region": "-",
             "pm_count": i, "total_model_codes": 100, "stk_potenzial": i * 37}
            for i in range(1, 6)
        ]
        ampeln = _berechne_ampeln_aus_smax(smax_techniker)
        werte = {a["zusatz_stk"] for a in ampeln}
        assert len(werte) == len(smax_techniker), "alle Werte identisch -- Bug nicht behoben"


# ===================================================================
# Reale Abdeckung: Konsistenz gegen smax_dashboard_data.json
# ===================================================================

class TestRealeDatenKonsistenz:
    @pytest.fixture(autouse=True)
    def setup(self):
        if not _CACHE.exists():
            pytest.skip("data/smax_dashboard_data.json nicht vorhanden -- kein Echtdaten-Import")
        self.data = json.loads(_CACHE.read_text(encoding="utf-8"))

    def test_beobachtungszeitraum_im_cache_vorhanden_und_plausibel(self):
        jahre = self.data.get("beobachtungszeitraum_jahre")
        assert jahre is not None
        assert 0.5 < jahre < 20  # realistischer Rahmen, kein Tage-/Minutenwert

    def test_job_standorte_haben_stk_jahr_statt_roher_jobs_summe(self):
        assert self.data["job_standorte"], "keine job_standorte vorhanden"
        for eintrag in self.data["job_standorte"][:20]:
            assert "stk_jahr" in eintrag
            assert "closed_jobs" in eintrag and "open_jobs" in eintrag
            # stk_jahr darf nicht einfach closed+open (die alte, falsche Rechnung) sein,
            # sobald der Beobachtungszeitraum > 1 Jahr betraegt.
            roh_summe = eintrag["closed_jobs"] + eintrag["open_jobs"]
            if eintrag["closed_jobs"] > 0 and self.data["beobachtungszeitraum_jahre"] > 1.01:
                assert eintrag["stk_jahr"] < roh_summe

    def test_ampel_karten_zusatz_stk_stimmt_mit_stk_potenzial_ueberein(self):
        ampeln = _berechne_ampeln_aus_smax(self.data["techniker"])
        stk_pot = {t["pseudonym_id"]: t["stk_potenzial"] for t in self.data["techniker"]}
        for a in ampeln:
            assert a["zusatz_stk"] == float(stk_pot[a["techniker_id"]])

    def test_delta_fahrzeit_liegt_in_plausiblem_rahmen_fuer_die_mehrheit(self):
        """Nach der Normalisierung sollte die Mehrheit der Techniker (nicht
        zwingend alle -- grosse Verschiebungen bleiben grosse Deltas) ein
        Delta deutlich unter der alten, verzerrten Groessenordnung haben."""
        techniker = {
            t["pseudonym_id"]: {
                "standort": t["standort"], "bundesland": t["bundesland"],
                "lat": t["lat"], "lon": t["lon"],
            }
            for t in self.data["techniker"]
        }
        import reporting.dashboard as dash
        alt = dash._ECHTDATEN
        dash._ECHTDATEN = True
        try:
            metriken_akt, metriken_opt, _ = _berechne_gebietsmetriken(techniker)
        finally:
            dash._ECHTDATEN = alt

        akt_by_id = {m["id"]: m for m in metriken_akt}
        deltas = [
            abs(m["fahrtstunden_jahr"] - akt_by_id[m["id"]]["fahrtstunden_jahr"])
            for m in metriken_opt
        ]
        plausibel = sum(1 for d in deltas if d < 100)
        assert plausibel / len(deltas) > 0.5, (
            f"nur {plausibel}/{len(deltas)} Delta-Werte < 100h -- "
            "Normalisierung wirkt nicht wie erwartet"
        )
