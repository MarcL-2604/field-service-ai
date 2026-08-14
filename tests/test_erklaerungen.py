"""Tests fuer reporting/erklaerungen.py: template-basierte KI-Erklaerungen
ohne externen API-Aufruf. Prueft, dass die generierten Texte echte Zahlen
aus den Berechnungsdaten enthalten statt Platzhaltern.
"""

from reporting.erklaerungen import FRAGE_TYPEN, generiere_erklaerung


TECHNIKER = {
    "T1": {"standort": "Hamburg", "lat": 53.55, "lon": 9.99, "pm_count": 40, "total_mc": 365, "pm_ratio_pct": 11.0},
    "T2": {"standort": "München", "lat": 48.14, "lon": 11.58},
}

METRIKEN_AKT = [
    {"id": "T1", "standort": "Hamburg", "kliniken": 12, "avg_fahrzeit": 45,
     "max_fahrzeit": 90, "fahrtstunden_jahr": 200, "onsite_stunden": 400, "ratio": 2.0},
    {"id": "T2", "standort": "München", "kliniken": 0, "avg_fahrzeit": 0,
     "max_fahrzeit": 0, "fahrtstunden_jahr": 0, "onsite_stunden": 0, "ratio": 0.0},
]

METRIKEN_OPT = [
    {"id": "T1", "standort": "Hamburg", "kliniken": 15, "avg_fahrzeit": 50,
     "max_fahrzeit": 95, "fahrtstunden_jahr": 230, "onsite_stunden": 420, "ratio": 1.83,
     "verschoben": 4, "verschoben_gewonnen": 3, "verschoben_abgegeben": 1},
    {"id": "T2", "standort": "München", "kliniken": 0, "avg_fahrzeit": 0,
     "max_fahrzeit": 0, "fahrtstunden_jahr": 0, "onsite_stunden": 0, "ratio": 0.0,
     "verschoben": 0, "verschoben_gewonnen": 0, "verschoben_abgegeben": 0},
]

AMPELN = [
    {"techniker_id": "T1", "standort": "Hamburg", "qualifiziert": 30, "regional": 40,
     "abdeckung_pct": 75, "fehlend_count": 10, "zusatz_stk": 55.0, "ampel_css": "ampel-gelb"},
]


class TestGeneriereErklaerung:
    def test_warum_gebiet_enthaelt_echte_zahlen(self):
        text = generiere_erklaerung(
            "warum_gebiet", "T1",
            techniker=TECHNIKER, metriken_akt=METRIKEN_AKT, metriken_opt=METRIKEN_OPT,
            ampeln=AMPELN, umweg_faktor=1.35,
        )
        assert "12 Kliniken" in text
        assert "45 min" in text
        assert "2.0" in text
        assert "40%" in text and "35%" in text and "25%" in text
        assert "T2" in text  # naechstgelegener Alternativtechniker

    def test_warum_gebiet_ohne_kliniken(self):
        text = generiere_erklaerung(
            "warum_gebiet", "T2",
            techniker=TECHNIKER, metriken_akt=METRIKEN_AKT, metriken_opt=METRIKEN_OPT,
            ampeln=AMPELN,
        )
        assert "keine zugewiesenen Kliniken" in text

    def test_warum_auslastung_enthaelt_echte_zahlen(self):
        text = generiere_erklaerung(
            "warum_auslastung", "T1",
            techniker=TECHNIKER, metriken_akt=METRIKEN_AKT, metriken_opt=METRIKEN_OPT,
            ampeln=AMPELN,
        )
        assert "12 Kliniken" in text
        assert "200 Fahrtstunden" in text
        assert "75%" in text
        assert "+55 STK/Jahr" in text
        assert "40 PM-Qualifikationen" in text

    def test_warum_verschoben_mit_verschiebung(self):
        text = generiere_erklaerung(
            "warum_verschoben", "T1",
            techniker=TECHNIKER, metriken_akt=METRIKEN_AKT, metriken_opt=METRIKEN_OPT,
            ampeln=AMPELN,
        )
        assert "3 Klinik(en) neu hinzugekommen" in text
        assert "1 Klinik(en) abgegeben" in text
        assert "2.0" in text and "1.83" in text

    def test_warum_verschoben_ohne_verschiebung(self):
        text = generiere_erklaerung(
            "warum_verschoben", "T2",
            techniker=TECHNIKER, metriken_akt=METRIKEN_AKT, metriken_opt=METRIKEN_OPT,
            ampeln=AMPELN,
        )
        assert "keine Kliniken verschoben" in text

    def test_unbekannter_fragetyp(self):
        text = generiere_erklaerung(
            "quatsch", "T1", techniker=TECHNIKER, metriken_akt=METRIKEN_AKT,
        )
        assert "Unbekannter Fragetyp" in text

    def test_unbekannter_techniker(self):
        text = generiere_erklaerung(
            "warum_gebiet", "T99", techniker=TECHNIKER, metriken_akt=METRIKEN_AKT,
        )
        assert "T99" in text and "Kein Techniker" in text

    def test_alle_fragetypen_fuer_alle_techniker_liefern_text(self):
        for tid in TECHNIKER:
            for frage_typ in FRAGE_TYPEN:
                text = generiere_erklaerung(
                    frage_typ, tid,
                    techniker=TECHNIKER, metriken_akt=METRIKEN_AKT,
                    metriken_opt=METRIKEN_OPT, ampeln=AMPELN,
                )
                assert isinstance(text, str) and len(text) > 10
                assert "Platzhalter" not in text


class TestGeneriereErklaerungEnglisch:
    """Sprache=en liefert englische Formulierungen, identische Zahlen/Fakten (i18n-Fix)."""

    def test_warum_gebiet_englisch_enthaelt_gleiche_zahlen(self):
        text = generiere_erklaerung(
            "warum_gebiet", "T1",
            techniker=TECHNIKER, metriken_akt=METRIKEN_AKT, metriken_opt=METRIKEN_OPT,
            ampeln=AMPELN, umweg_faktor=1.35, sprache="en",
        )
        assert "12 clinics" in text
        assert "45 min" in text
        assert "2.0" in text
        assert "40%" in text and "35%" in text and "25%" in text
        assert "T2" in text
        # keine deutschen Woerter aus der DE-Formulierung
        assert "Kliniken" not in text and "Fahrzeit" not in text

    def test_warum_auslastung_englisch(self):
        text = generiere_erklaerung(
            "warum_auslastung", "T1",
            techniker=TECHNIKER, metriken_akt=METRIKEN_AKT, metriken_opt=METRIKEN_OPT,
            ampeln=AMPELN, sprache="en",
        )
        assert "12 clinics" in text
        assert "200 travel hours" in text
        assert "75%" in text
        assert "+55 STK/year" in text
        assert "40 PM qualifications" in text

    def test_warum_verschoben_englisch(self):
        text = generiere_erklaerung(
            "warum_verschoben", "T1",
            techniker=TECHNIKER, metriken_akt=METRIKEN_AKT, metriken_opt=METRIKEN_OPT,
            ampeln=AMPELN, sprache="en",
        )
        assert "3 clinic(s) newly added" in text
        assert "1 clinic(s) given up" in text
        assert "2.0" in text and "1.83" in text

    def test_warum_verschoben_ohne_verschiebung_englisch(self):
        text = generiere_erklaerung(
            "warum_verschoben", "T2",
            techniker=TECHNIKER, metriken_akt=METRIKEN_AKT, metriken_opt=METRIKEN_OPT,
            ampeln=AMPELN, sprache="en",
        )
        assert "no clinics were moved" in text

    def test_unbekannter_techniker_englisch(self):
        text = generiere_erklaerung(
            "warum_gebiet", "T99", techniker=TECHNIKER, metriken_akt=METRIKEN_AKT,
            sprache="en",
        )
        assert "T99" in text and "No technician found" in text

    def test_unbekannter_fragetyp_englisch(self):
        text = generiere_erklaerung(
            "quatsch", "T1", techniker=TECHNIKER, metriken_akt=METRIKEN_AKT, sprache="en",
        )
        assert "Unknown question type" in text

    def test_default_bleibt_deutsch(self):
        """Ohne sprache-Argument bleibt das Verhalten unveraendert (DE)."""
        text = generiere_erklaerung(
            "warum_gebiet", "T1",
            techniker=TECHNIKER, metriken_akt=METRIKEN_AKT, metriken_opt=METRIKEN_OPT,
            ampeln=AMPELN,
        )
        assert "12 Kliniken" in text

    def test_alle_fragetypen_alle_techniker_englisch_liefern_text(self):
        for tid in TECHNIKER:
            for frage_typ in FRAGE_TYPEN:
                text = generiere_erklaerung(
                    frage_typ, tid,
                    techniker=TECHNIKER, metriken_akt=METRIKEN_AKT,
                    metriken_opt=METRIKEN_OPT, ampeln=AMPELN, sprache="en",
                )
                assert isinstance(text, str) and len(text) > 10
                assert "Platzhalter" not in text
