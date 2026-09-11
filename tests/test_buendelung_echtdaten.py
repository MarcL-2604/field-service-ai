"""
tests/test_buendelung_echtdaten.py
====================================
Tests fuer Schritt 2 der Modul-1-Vervollstaendigung: Auftragsbuendelung
(buendle_mit_qualifikation()) auf echten offenen SMax-Auftraegen statt nur
auf den 14 fiktiven Demo-Technikern/Demo-Klinik-IDs "K001" etc.

Deckt ab:
  - Adapter-Funktionen (echte Job-/Techniker-Daten -> Auftrag-Schema)
  - buendle_mit_qualifikation() mit echten-Daten-foermigen Eingaben
    (nicht nur synthetische K001-Fixtures)
  - Demo-Modus bleibt unveraendert (Regressionsschutz, Default-Parameter)
"""

import json
from datetime import date
from pathlib import Path

import pytest

import reporting.dashboard as dash
from auftraege.models import Auftrag, AuftragsTyp
from auftraege.tour_optimierung import buendle_auftraege, buendle_mit_qualifikation

_ROOT = Path(__file__).parent.parent


def _job(auftragsnummer="SMAX-0001", klinik="Klinikum Test", plz="12345",
         model_code="MC-FT10", produktfamilie="HF_CHIRURGIE", faellig_iso=None,
         repair_kandidat=False):
    return {
        "auftragsnummer": auftragsnummer,
        "klinik": klinik,
        "plz": plz,
        "model_code": model_code,
        "produktfamilie": produktfamilie,
        "faellig_iso": faellig_iso,
        "repair_kandidat": repair_kandidat,
    }


class TestBaueEchteAuftraegeFuerBuendelung:
    def test_klinik_id_aus_klinik_und_plz(self):
        auftraege = dash._baue_echte_auftraege_fuer_buendelung(
            [_job(klinik="Klinikum Test", plz="72072")], heute=date(2026, 9, 10))
        assert auftraege[0].klinik_id == "Klinikum Test::72072"

    def test_auftragstyp_repair_bei_repair_kandidat(self):
        auftraege = dash._baue_echte_auftraege_fuer_buendelung(
            [_job(repair_kandidat=True)], heute=date(2026, 9, 10))
        assert auftraege[0].auftragstyp == AuftragsTyp.REPAIR

    def test_auftragstyp_stk_ohne_repair_kandidat(self):
        auftraege = dash._baue_echte_auftraege_fuer_buendelung(
            [_job(repair_kandidat=False)], heute=date(2026, 9, 10))
        assert auftraege[0].auftragstyp == AuftragsTyp.STK

    def test_faelligkeitsdatum_nutzt_echtes_datum_wenn_bekannt(self):
        auftraege = dash._baue_echte_auftraege_fuer_buendelung(
            [_job(faellig_iso="2026-12-01")], heute=date(2026, 9, 10))
        assert auftraege[0].faelligkeitsdatum == date(2026, 12, 1)

    def test_faelligkeitsdatum_faellt_auf_heute_zurueck_wenn_unbekannt(self):
        auftraege = dash._baue_echte_auftraege_fuer_buendelung(
            [_job(faellig_iso=None)], heute=date(2026, 9, 10))
        assert auftraege[0].faelligkeitsdatum == date(2026, 9, 10)

    def test_zwei_auftraege_ohne_datum_gleiche_klinik_gleicher_monat(self):
        """Der eigentliche Zweck des Heute-Fallbacks: Auftraege derselben
        Klinik ohne bekannte Faelligkeit landen im selben Monats-Bucket und
        koennen so weiterhin gebuendelt werden."""
        auftraege = dash._baue_echte_auftraege_fuer_buendelung(
            [_job("A", klinik="X", faellig_iso=None), _job("B", klinik="X", faellig_iso=None)],
            heute=date(2026, 9, 10),
        )
        assert auftraege[0].faelligkeitsdatum.strftime("%Y-%m") == auftraege[1].faelligkeitsdatum.strftime("%Y-%m")

    def test_produkt_familie_ist_cluster_name(self):
        auftraege = dash._baue_echte_auftraege_fuer_buendelung(
            [_job(produktfamilie="CLUSTER1_OR")], heute=date(2026, 9, 10))
        assert auftraege[0].produkt_familie == "CLUSTER1_OR"

    def test_auftrag_id_faellt_auf_synthetische_id_zurueck(self):
        auftraege = dash._baue_echte_auftraege_fuer_buendelung(
            [_job(auftragsnummer="")], heute=date(2026, 9, 10))
        assert auftraege[0].auftrag_id == "SMAX-0001"

    def test_leere_klinik_wird_uebersprungen(self):
        auftraege = dash._baue_echte_auftraege_fuer_buendelung(
            [_job(klinik="")], heute=date(2026, 9, 10))
        assert auftraege == []

    def test_ergebnis_sind_echte_auftrag_objekte(self):
        auftraege = dash._baue_echte_auftraege_fuer_buendelung([_job()], heute=date(2026, 9, 10))
        assert isinstance(auftraege[0], Auftrag)


class TestBaueEchteQualifikationsmatrix:
    def _techniker(self, pseudonym_id, cluster):
        return {"pseudonym_id": pseudonym_id, "qualifizierte_cluster": cluster}

    def test_techniker_ids_enthalten_alle_pseudonyme(self):
        ids, _ = dash._baue_echte_qualifikationsmatrix([
            self._techniker("Marc L.", ["HF_CHIRURGIE"]),
            self._techniker("Ahmed A.", []),
        ])
        assert ids == {"Marc L.", "Ahmed A."}

    def test_matrix_setzt_level_l3_fuer_qualifizierte_cluster(self):
        _, matrix = dash._baue_echte_qualifikationsmatrix([
            self._techniker("Marc L.", ["HF_CHIRURGIE", "SMALL_CAPITAL"]),
        ])
        assert matrix["Marc L."] == {"HF_CHIRURGIE": "L3", "SMALL_CAPITAL": "L3"}

    def test_techniker_ohne_qualifikation_hat_leeres_dict(self):
        _, matrix = dash._baue_echte_qualifikationsmatrix([self._techniker("Ahmed A.", [])])
        assert matrix["Ahmed A."] == {}


class TestBuendleMitQualifikationEchteDatenFoermig:
    """Bundling mit ECHTEN-Daten-foermigen Eingaben (reale Klinik-Keys,
    reale Pseudonym-IDs, Cluster-Produktfamilien) statt der bisherigen
    synthetischen K001-Fixtures -- ueber die neuen optionalen Parameter."""

    def _auftrag(self, aid, klinik_id, familie, faellig):
        return Auftrag(
            auftrag_id=aid, auftragstyp=AuftragsTyp.STK, klinik_id=klinik_id,
            klinik_name="Klinikum Test", geraet_id="MC-XYZ", produkt_familie=familie,
            faelligkeitsdatum=faellig,
        )

    def test_ein_techniker_deckt_alles_ab_fall_a(self):
        gruppe = [
            self._auftrag("A", "Klinikum Test::12345", "HF_CHIRURGIE", date(2026, 9, 10)),
            self._auftrag("B", "Klinikum Test::12345", "SMALL_CAPITAL", date(2026, 9, 10)),
        ]
        plaene = buendle_mit_qualifikation(
            gruppe,
            techniker_ids={"Marc L.", "Ahmed A."},
            qualifikationsmatrix={
                "Marc L.": {"HF_CHIRURGIE": "L3", "SMALL_CAPITAL": "L3"},
                "Ahmed A.": {"HF_CHIRURGIE": "L3"},
            },
        )
        assert len(plaene) == 1
        assert plaene[0].fall == "A"
        assert plaene[0].einsaetze[0].techniker_id == "Marc L."

    def test_kein_techniker_deckt_alles_ab_fall_b(self):
        gruppe = [
            self._auftrag("A", "Klinikum Test::12345", "HF_CHIRURGIE", date(2026, 9, 10)),
            self._auftrag("B", "Klinikum Test::12345", "CLUSTER1_OR", date(2026, 9, 10)),
        ]
        plaene = buendle_mit_qualifikation(
            gruppe,
            techniker_ids={"Marc L.", "Ahmed A."},
            qualifikationsmatrix={
                "Marc L.": {"HF_CHIRURGIE": "L3"},
                "Ahmed A.": {"CLUSTER1_OR": "L3"},
            },
        )
        assert len(plaene) == 1
        assert plaene[0].fall == "B"
        assert len(plaene[0].einsaetze) == 2

    def test_funktioniert_mit_pseudonym_ids_die_nicht_in_demo_csv_stehen(self):
        """Reale Pseudonym-IDs wie 'Marc L.' existieren nicht in
        daten/techniker.csv -- die Funktion darf trotzdem nicht auf die
        Demo-CSV zurueckfallen, wenn Override-Parameter gesetzt sind."""
        gruppe = [
            self._auftrag("A", "K::1", "SMALL_CAPITAL", date(2026, 9, 10)),
            self._auftrag("B", "K::1", "SMALL_CAPITAL", date(2026, 9, 10)),
        ]
        plaene = buendle_mit_qualifikation(
            gruppe, techniker_ids={"Marc L."},
            qualifikationsmatrix={"Marc L.": {"SMALL_CAPITAL": "L3"}},
        )
        assert len(plaene) == 1
        assert plaene[0].einsaetze[0].techniker_id == "Marc L."

    def test_ohne_qualifizierten_techniker_kein_plan(self):
        gruppe = [
            self._auftrag("A", "K::1", "CLUSTER1_OR", date(2026, 9, 10)),
            self._auftrag("B", "K::1", "CLUSTER1_OR", date(2026, 9, 10)),
        ]
        plaene = buendle_mit_qualifikation(
            gruppe, techniker_ids={"Marc L."},
            qualifikationsmatrix={"Marc L.": {"SMALL_CAPITAL": "L3"}},
        )
        assert plaene == []


class TestDemoModusRegressionsschutz:
    """Default-Parameter (None) muessen exakt das bisherige Verhalten
    beibehalten -- Demo-CSV-Pfad bleibt unangetastet."""

    def test_buendle_auftraege_unveraendert(self):
        gruppe = [
            Auftrag(auftrag_id="A", auftragstyp=AuftragsTyp.STK, klinik_id="K044",
                    klinik_name="Uniklinikum Ulm", geraet_id="NIM4CM01",
                    produkt_familie="Neuromonitoring", faelligkeitsdatum=date(2026, 4, 1)),
            Auftrag(auftrag_id="B", auftragstyp=AuftragsTyp.STK, klinik_id="K044",
                    klinik_name="Uniklinikum Ulm", geraet_id="NIM4CM02",
                    produkt_familie="Neuromonitoring", faelligkeitsdatum=date(2026, 4, 2)),
        ]
        ergebnis = buendle_auftraege(gruppe)
        assert len(ergebnis) == 1
        assert ergebnis[0].klinik_id == "K044"

    def test_buendle_mit_qualifikation_ohne_override_laedt_demo_csv(self):
        gruppe = [
            Auftrag(auftrag_id="A", auftragstyp=AuftragsTyp.STK, klinik_id="K044",
                    klinik_name="Uniklinikum Ulm", geraet_id="NIM4CM01",
                    produkt_familie="Neuromonitoring", faelligkeitsdatum=date(2026, 4, 1)),
            Auftrag(auftrag_id="B", auftragstyp=AuftragsTyp.STK, klinik_id="K044",
                    klinik_name="Uniklinikum Ulm", geraet_id="NIM4CM02",
                    produkt_familie="Neuromonitoring", faelligkeitsdatum=date(2026, 4, 2)),
        ]
        # Kein techniker_ids/qualifikationsmatrix-Override -> muss wie vorher
        # funktionieren (Demo-Techniker T1-T14 aus daten/techniker.csv).
        ergebnis = buendle_mit_qualifikation(gruppe)
        assert isinstance(ergebnis, list)


class TestRenderBuendelungEchtdaten:
    def test_leere_liste_zeigt_hinweistext(self):
        html = dash._render_buendelung_echtdaten([])
        assert "Keine B" in html

    def test_rendert_klinik_und_fall(self):
        gruppe = [
            Auftrag(auftrag_id="A", auftragstyp=AuftragsTyp.STK, klinik_id="Testklinik::1",
                    klinik_name="Testklinik", geraet_id="MC-X", produkt_familie="SMALL_CAPITAL",
                    faelligkeitsdatum=date(2026, 9, 10)),
            Auftrag(auftrag_id="B", auftragstyp=AuftragsTyp.STK, klinik_id="Testklinik::1",
                    klinik_name="Testklinik", geraet_id="MC-Y", produkt_familie="SMALL_CAPITAL",
                    faelligkeitsdatum=date(2026, 9, 10)),
        ]
        plaene = buendle_mit_qualifikation(
            gruppe, techniker_ids={"Marc L."},
            qualifikationsmatrix={"Marc L.": {"SMALL_CAPITAL": "L3"}},
        )
        html = dash._render_buendelung_echtdaten(plaene)
        assert "Testklinik" in html
        assert "go-empf-card" in html
        assert "Fall A" in html

    def test_begrenzt_auf_10_karten(self):
        plaene = []
        for i in range(15):
            gruppe = [
                Auftrag(auftrag_id=f"A{i}", auftragstyp=AuftragsTyp.STK, klinik_id=f"K{i}::1",
                        klinik_name=f"Klinik{i}", geraet_id="MC-X", produkt_familie="SMALL_CAPITAL",
                        faelligkeitsdatum=date(2026, 9, 10)),
                Auftrag(auftrag_id=f"B{i}", auftragstyp=AuftragsTyp.STK, klinik_id=f"K{i}::1",
                        klinik_name=f"Klinik{i}", geraet_id="MC-Y", produkt_familie="SMALL_CAPITAL",
                        faelligkeitsdatum=date(2026, 9, 10)),
            ]
            plaene += buendle_mit_qualifikation(
                gruppe, techniker_ids={"Marc L."},
                qualifikationsmatrix={"Marc L.": {"SMALL_CAPITAL": "L3"}},
            )
        html = dash._render_buendelung_echtdaten(plaene)
        assert html.count("go-empf-card") == 10


class TestRenderAuftraegeAbschnitt3:
    def test_leer_im_demo_modus(self):
        assert dash._render_auftraege_abschnitt3(False, "<div>x</div>") == ""

    def test_nicht_leer_im_echtdaten_modus(self):
        html = dash._render_auftraege_abschnitt3(True, "<div>x</div>")
        assert "h.buendelung" in html
        assert "<div>x</div>" in html


class TestRealDatensatzRegression:
    """Buendelung auf dem tatsaechlichen (committeten) SMax-Datensatz --
    stellt sicher, dass der komplette Pfad auch mit echten, nicht
    handgeschriebenen Daten funktioniert."""

    def test_echter_datensatz_liefert_plausible_buendelungsergebnisse(self):
        cache = _ROOT / "data" / "smax_dashboard_data.json"
        if not cache.exists():
            pytest.skip("data/smax_dashboard_data.json nicht vorhanden")
        d = json.loads(cache.read_text(encoding="utf-8"))
        if "offene_auftraege" not in d or "qualifizierte_cluster" not in (d.get("techniker") or [{}])[0]:
            pytest.skip("Cache-Datei noch ohne die fuer Schritt 2 benoetigten Felder")

        auftraege = dash._baue_echte_auftraege_fuer_buendelung(
            d["offene_auftraege"], heute=date(2026, 9, 10))
        techniker_ids, matrix = dash._baue_echte_qualifikationsmatrix(d["techniker"])

        assert len(auftraege) > 700
        assert len(techniker_ids) == 24

        plaene = buendle_mit_qualifikation(auftraege, techniker_ids=techniker_ids, qualifikationsmatrix=matrix)
        assert len(plaene) > 0
        for plan in plaene:
            assert plan.fall in ("A", "B", "C")
            assert len(plan.alle_auftraege) >= 2
            for einsatz in plan.einsaetze:
                assert einsatz.techniker_id in techniker_ids
