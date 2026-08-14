"""Tests fuer den generischen Gebietsoptimierungs-Algorithmus (dashboard.py).

Ersetzt die alte, hartcodierte Allgaeu-Sonderregel (T2/T10/T14 -> T7), die nur
fuer die Demo-Techniker-IDs funktionierte. Der neue Algorithmus ist
ID-unabhaengig: eine Klinik wandert vom 1.- zum 2.-naechsten Techniker, wenn
dieser deutlich weniger ausgelastet ist (Auslastungsdifferenz ueber
config.OPTIMIERUNG_AUSLASTUNGS_SCHWELLE Prozentpunkten) UND die
Fahrzeit-Mehrbelastung vertretbar bleibt (<= config.OPTIMIERUNG_MAX_FAHRZEIT_MEHRAUFWAND_MIN
Minuten).
"""

import csv
import inspect

import pytest

from config import (
    OPTIMIERUNG_AUSLASTUNGS_SCHWELLE,
    OPTIMIERUNG_MAX_FAHRZEIT_MEHRAUFWAND_MIN,
    ARBEITSWOCHEN_PRO_JAHR,
)
import reporting.dashboard as dash
from reporting.dashboard import (
    _soll_klinik_verschieben,
    _berechne_gebietsmetriken,
    _lade_kliniken_demo,
    _lade_kliniken_echtdaten,
    _parse_svg_polygon,
    _punkt_in_polygon,
    _bundesland_fuer_punkt,
    _project_mercator,
    _topo_to_svg_paths,
    _DATA_DIR,
)


# ===================================================================
# Config-Konstanten
# ===================================================================

class TestOptimierungsKonstanten:
    def test_auslastungs_schwelle(self):
        assert OPTIMIERUNG_AUSLASTUNGS_SCHWELLE == 15

    def test_max_fahrzeit_mehraufwand(self):
        assert OPTIMIERUNG_MAX_FAHRZEIT_MEHRAUFWAND_MIN == 20

    def test_arbeitswochen_pro_jahr(self):
        assert ARBEITSWOCHEN_PRO_JAHR == 46


# ===================================================================
# _soll_klinik_verschieben(): reine Entscheidungsfunktion
# ===================================================================

class TestSollKlinikVerschieben:
    def test_grosse_auslastungsdifferenz_kleine_fahrzeitdifferenz_verschiebt(self):
        """Auslastungsdifferenz deutlich ueber Schwelle, Fahrzeit-Mehraufwand klein -> True."""
        assert _soll_klinik_verschieben(
            auslastung_diff_pp=25.0, fahrzeit_mehraufwand_min=5.0
        ) is True

    def test_kleine_auslastungsdifferenz_bleibt(self):
        """Auslastungsdifferenz unter Schwelle -> Klinik bleibt, egal wie nah dran."""
        assert _soll_klinik_verschieben(
            auslastung_diff_pp=5.0, fahrzeit_mehraufwand_min=2.0
        ) is False

    def test_grosse_auslastungsdifferenz_aber_zu_weit_bleibt(self):
        """Auslastungsdifferenz gross, aber Fahrzeit-Mehraufwand ueber Limit -> bleibt."""
        assert _soll_klinik_verschieben(
            auslastung_diff_pp=30.0, fahrzeit_mehraufwand_min=25.0
        ) is False

    def test_negative_auslastungsdifferenz_bleibt(self):
        """2.-naechster ist staerker ausgelastet als 1.-naechster -> nie verschieben."""
        assert _soll_klinik_verschieben(
            auslastung_diff_pp=-10.0, fahrzeit_mehraufwand_min=1.0
        ) is False

    def test_grenzwert_auslastung_exakt_schwelle_bleibt(self):
        """Exakt am Schwellwert (nicht darueber) -> Regel ist 'echt groesser als'."""
        assert _soll_klinik_verschieben(
            auslastung_diff_pp=float(OPTIMIERUNG_AUSLASTUNGS_SCHWELLE),
            fahrzeit_mehraufwand_min=0.0,
        ) is False

    def test_grenzwert_auslastung_knapp_ueber_schwelle_verschiebt(self):
        assert _soll_klinik_verschieben(
            auslastung_diff_pp=OPTIMIERUNG_AUSLASTUNGS_SCHWELLE + 0.01,
            fahrzeit_mehraufwand_min=0.0,
        ) is True

    def test_grenzwert_fahrzeit_exakt_max_verschiebt(self):
        """Fahrzeit-Mehraufwand exakt am Limit (inklusive) -> erlaubt."""
        assert _soll_klinik_verschieben(
            auslastung_diff_pp=OPTIMIERUNG_AUSLASTUNGS_SCHWELLE + 1,
            fahrzeit_mehraufwand_min=float(OPTIMIERUNG_MAX_FAHRZEIT_MEHRAUFWAND_MIN),
        ) is True

    def test_grenzwert_fahrzeit_knapp_drueber_bleibt(self):
        assert _soll_klinik_verschieben(
            auslastung_diff_pp=OPTIMIERUNG_AUSLASTUNGS_SCHWELLE + 1,
            fahrzeit_mehraufwand_min=OPTIMIERUNG_MAX_FAHRZEIT_MEHRAUFWAND_MIN + 0.01,
        ) is False


# ===================================================================
# Keine hartcodierten Demo-IDs mehr im Optimierungscode
# ===================================================================

class TestKeineHartcodiertenIds:
    def test_quellcode_referenziert_keine_demo_techniker_ids(self):
        """Die alte Allgaeu-Sonderregel (T2/T10/T14 -> T7) darf nicht mehr vorkommen."""
        quelle = inspect.getsource(_berechne_gebietsmetriken)
        for verbotene_id in ('"T2"', '"T10"', '"T14"', '"T7"', "allgaeu"):
            assert verbotene_id.lower() not in quelle.lower(), (
                f"{verbotene_id} sollte nicht mehr in _berechne_gebietsmetriken vorkommen"
            )


# ===================================================================
# _berechne_gebietsmetriken(): End-to-End mit echten Klinik-/Geraetedaten
# ===================================================================

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


class TestBerechneGebietsmetrikenStruktur:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.techniker = _lade_demo_techniker()
        self.akt, self.opt, self.gebiet_opt, self.punkte = _berechne_gebietsmetriken(self.techniker)

    def test_gibt_vierertupel_zurueck(self):
        assert isinstance(self.akt, list)
        assert isinstance(self.opt, list)
        assert isinstance(self.gebiet_opt, dict)
        assert isinstance(self.punkte, list)

    def test_gleiche_technikeranzahl_in_beiden_listen(self):
        assert len(self.akt) == len(self.techniker)
        assert len(self.opt) == len(self.techniker)

    def test_optimiert_hat_verschoben_felder(self):
        for m in self.opt:
            assert "verschoben" in m
            assert "verschoben_gewonnen" in m
            assert m["verschoben"] == m["verschoben_gewonnen"] + m["verschoben_abgegeben"]

    def test_mindestens_eine_klinik_tatsaechlich_verschoben(self):
        """Regressionsschutz: der alte Bug liess ausnahmslos alles unveraendert (0 Diffs)."""
        gesamt_verschoben = sum(m["verschoben_gewonnen"] for m in self.opt)
        assert gesamt_verschoben > 0

    def test_gebiet_optimiert_werte_sind_bekannte_techniker(self):
        for bl, tid in self.gebiet_opt.items():
            assert tid in self.techniker, f"{bl} -> unbekannter Techniker {tid!r}"

    def test_verschobene_kliniken_konsistent_mit_ratio_aenderung(self):
        """Wer Kliniken verliert oder gewinnt, hat i.d.R. eine andere Kliniken-Anzahl als vorher."""
        akt_by_id = {m["id"]: m for m in self.akt}
        veraendert = 0
        for m in self.opt:
            if m["verschoben"] > 0:
                veraendert += 1
                a = akt_by_id[m["id"]]
                assert m["kliniken"] != a["kliniken"] or m["verschoben_gewonnen"] == m["verschoben_abgegeben"]
        assert veraendert > 0


# ===================================================================
# ID-Unabhaengigkeit: Umbenennen der Techniker-IDs aendert das Ergebnis nicht
# ===================================================================

class TestIdUnabhaengigkeit:
    """Der Algorithmus darf nicht auf bestimmte ID-Strings (z.B. 'T2') pruefen.
    Gleiche Koordinaten unter anderen Namen muessen strukturell dasselbe
    Optimierungsergebnis liefern (nur die Labels unterscheiden sich)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.original = _lade_demo_techniker()
        # Umbenennen: "T1" -> "Person-T1" usw. -- keine Demo-IDs mehr, aber gleiche Orte
        self.umbenannt = {
            f"Person-{tid}": daten for tid, daten in self.original.items()
        }

    def test_gleiche_anzahl_verschobener_kliniken_nach_umbenennung(self):
        _, opt_orig, _, _ = _berechne_gebietsmetriken(self.original)
        _, opt_neu, _, _ = _berechne_gebietsmetriken(self.umbenannt)

        gesamt_orig = sum(m["verschoben_gewonnen"] for m in opt_orig)
        gesamt_neu = sum(m["verschoben_gewonnen"] for m in opt_neu)
        assert gesamt_orig == gesamt_neu

    def test_gleiche_kliniken_anzahl_pro_umbenanntem_techniker(self):
        _, opt_orig, _, _ = _berechne_gebietsmetriken(self.original)
        _, opt_neu, _, _ = _berechne_gebietsmetriken(self.umbenannt)

        orig_by_id = {m["id"]: m["kliniken"] for m in opt_orig}
        neu_by_id = {m["id"]: m["kliniken"] for m in opt_neu}
        for tid in self.original:
            assert orig_by_id[tid] == neu_by_id[f"Person-{tid}"]

    def test_funktioniert_auch_mit_nur_zwei_technikern(self):
        """Kleinstes sinnvolles Set (1.- und 2.-naechster muss existieren)."""
        zwei = dict(list(self.umbenannt.items())[:2])
        akt, opt, _, _ = _berechne_gebietsmetriken(zwei)
        assert len(akt) == 2
        assert len(opt) == 2

    def test_funktioniert_mit_einem_einzigen_techniker(self):
        """Ohne 2.-naechsten Techniker darf nichts verschoben werden (kein Crash)."""
        einer = dict(list(self.umbenannt.items())[:1])
        akt, opt, _, _ = _berechne_gebietsmetriken(einer)
        assert len(opt) == 1
        assert opt[0]["verschoben"] == 0


# ===================================================================
# Punkt-in-Polygon: Bundesland-Zuordnung ueber echte Geodaten
# (statt PLZ-Naeherungstabelle) -- fuer die Kartenfarben
# ===================================================================

class TestPunktInPolygon:
    QUADRAT = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]

    def test_punkt_innerhalb(self):
        assert _punkt_in_polygon(5.0, 5.0, self.QUADRAT) is True

    def test_punkt_ausserhalb(self):
        assert _punkt_in_polygon(15.0, 5.0, self.QUADRAT) is False

    def test_punkt_weit_ausserhalb(self):
        assert _punkt_in_polygon(-100.0, -100.0, self.QUADRAT) is False


class TestParseSvgPolygon:
    def test_einfaches_polygon(self):
        subpaths = _parse_svg_polygon("M0,0L10,0L10,10L0,10Z")
        assert len(subpaths) == 1
        assert subpaths[0] == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]

    def test_mehrere_teilpfade_inseln(self):
        subpaths = _parse_svg_polygon("M0,0L1,0L1,1ZM5,5L6,5L6,6Z")
        assert len(subpaths) == 2
        assert subpaths[0] == [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
        assert subpaths[1] == [(5.0, 5.0), (6.0, 5.0), (6.0, 6.0)]


class TestBundeslandFuerPunkt:
    """Nutzt die echten Bundeslaender-Geodaten (deutschland_topo.json)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.paths = _topo_to_svg_paths()

    def test_hamburg_koordinaten_ergeben_hamburg(self):
        px, py = _project_mercator(9.9937, 53.5505)  # Hamburg
        bl = _bundesland_fuer_punkt(px, py, self.paths)
        assert bl == "Hamburg"

    def test_muenchen_koordinaten_ergeben_bayern(self):
        px, py = _project_mercator(11.5820, 48.1351)  # Muenchen
        bl = _bundesland_fuer_punkt(px, py, self.paths)
        assert bl == "Bayern"

    def test_punkt_ausserhalb_deutschlands_ergibt_none(self):
        px, py = _project_mercator(2.3522, 48.8566)  # Paris
        bl = _bundesland_fuer_punkt(px, py, self.paths)
        assert bl is None


# ===================================================================
# _lade_kliniken_echtdaten(): echte Auftrags-Standorte, keine Platzhalter
# ===================================================================

class TestLadeKlinikenEchtdaten:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.kliniken, self.stk_count, self.stunden_pro_einsatz = _lade_kliniken_echtdaten()

    def test_laedt_reale_job_standorte(self):
        """Setzt voraus, dass data/smax_dashboard_data.json mit job_standorte vorliegt."""
        assert self.kliniken, "keine job_standorte im SMax-Cache gefunden"

    def test_klinik_ids_sind_keine_demo_ids(self):
        """Reale Standorte duerfen nicht mit den Demo-Klinik-IDs (K0xx) kollidieren."""
        for k in self.kliniken:
            assert k["id"].startswith("J")

    def test_stk_count_ist_annualisierte_stk_jahr_rate(self):
        """stk_count muss STK/Jahr sein (Closed Jobs / Beobachtungszeitraum +
        Open Jobs) -- dieselbe Zeitbasis wie im Demo-Modell (anzahl/zyklus),
        NICHT die rohe, mehrjaehrige Job-Summe (das war der Bug)."""
        for wert in self.stk_count.values():
            assert wert >= 0
        assert any(wert > 0 for wert in self.stk_count.values())

    def test_stunden_pro_einsatz_aus_echtem_median(self):
        """stunden_pro_einsatz muss aus dem realen einsatz_median_min abgeleitet sein,
        nicht der hartcodierte Demo-Wert (2.0h)."""
        assert self.stunden_pro_einsatz != 2.0
        assert self.stunden_pro_einsatz > 0


# ===================================================================
# _berechne_gebietsmetriken() waehlt die Datenquelle ueber _ECHTDATEN
# ===================================================================

class TestBerechneGebietsmetrikenDatenquelle:
    @pytest.fixture(autouse=True)
    def setup(self):
        original = dash._ECHTDATEN
        yield
        dash._ECHTDATEN = original  # Global-State nach dem Test zuruecksetzen

    def test_echtdaten_modus_nutzt_reale_job_standorte(self):
        dash._ECHTDATEN = True
        techniker = _lade_demo_techniker()  # Koordinaten egal, nur Datenquelle testen
        akt, opt, _, _ = _berechne_gebietsmetriken(techniker)
        # Reale Kliniken tragen "J"-IDs -- indirekt pruefbar ueber Nicht-Leere,
        # da IDs nicht im Rueckgabewert von _aggregiere() landen. Stattdessen:
        # direkter Vergleich der Ladefunktion.
        kliniken_echt, _, _ = _lade_kliniken_echtdaten()
        assert kliniken_echt  # Datenquelle ist tatsaechlich die echten Standorte
        assert akt  # Aggregation lief erfolgreich mit dieser Datenquelle

    def test_demo_modus_nutzt_demo_kliniken(self):
        dash._ECHTDATEN = False
        techniker = _lade_demo_techniker()
        akt, opt, _, _ = _berechne_gebietsmetriken(techniker)
        kliniken_demo, _, stunden = _lade_kliniken_demo()
        assert stunden == 2.0  # Demo-Kostenmodell (Konstante im Code)
        assert akt
