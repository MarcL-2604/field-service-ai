"""4-stellige PLZ (AT/CH) duerfen nicht zu ostdeutschen 0xxxx-PLZ aufgefuellt werden.

Regel: 4-stellige PLZ nur mit zur City passendem pgeocode-Ortsnamen auffuellen, sonst None.
"""
import reporting.dashboard as dash
from techniker.plz_koordinaten import hole_koordinaten, normalisiere_plz, ort_passt


def test_zuerich_und_wien_ergeben_none():
    assert hole_koordinaten("8001", "Zürich") is None
    assert hole_koordinaten("1010", "Wien") is None
    assert normalisiere_plz("8001", "Zuerich") is None
    assert normalisiere_plz("1140", "Wien") is None


def test_deutsche_plz_ohne_fuehrende_null_mit_passender_city_wird_aufgeloest():
    # Leipzig 04103 kommt aus Excel teils als Zahl 4103
    assert normalisiere_plz("4103", "Leipzig") == "04103"
    xy = hole_koordinaten("4103", "Leipzig")
    assert xy is not None and 50.5 < xy[0] < 52.0 and 11.5 < xy[1] < 13.0


def test_unpassende_city_verwirft():
    assert hole_koordinaten("4103", "Basel") is None
    assert normalisiere_plz("4103", "Hamburg") is None


def test_ohne_city_bleibt_vierstellig_none():
    assert hole_koordinaten("4103") is None
    assert hole_koordinaten("4103", "") is None
    assert hole_koordinaten("4103", None) is None


def test_fuenfstellig_unveraendert_und_ungueltiges_bleibt_none():
    assert normalisiere_plz("20095", None) == "20095"
    assert hole_koordinaten("20095") is not None
    assert hole_koordinaten("123456", "Irgendwo") is None     # mehr als 5 Stellen
    assert hole_koordinaten("12A45", "Irgendwo") is None      # Buchstaben
    assert hole_koordinaten("123", "Irgendwo") is None        # weniger als 4 Stellen


def test_ort_passt_ist_tolerant():
    assert ort_passt("LEIPZIG", "Leipzig, Stadt")
    assert ort_passt("Muenster", "Münster")
    assert ort_passt("Frankfurt am Main", "Frankfurt")
    assert ort_passt("Berlin-Mitte", "Berlin Mitte")
    assert not ort_passt("Basel", "Leipzig")
    assert not ort_passt("", "Leipzig")


def test_buendel_scope_nutzt_dieselbe_regel():
    assert dash._buendel_scope({"klinik": "A", "plz": "8001", "ort": "Zürich"}) == "ausland"
    assert dash._buendel_scope({"klinik": "A", "plz": "4103", "ort": "Leipzig"}) == "ok"
    assert dash._buendel_scope({"klinik": "A", "plz": "4103", "ort": ""}) == "ausland"
    assert dash._buendel_scope({"klinik": "A", "plz": "20095", "ort": "Hamburg"}) == "ok"
    assert dash._buendel_scope({"klinik": "A", "plz": "", "ort": "Hamburg"}) == "ok"   # Standort unbekannt, nicht Ausland
