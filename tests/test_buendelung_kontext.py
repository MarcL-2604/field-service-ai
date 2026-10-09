"""Buendelung im Echtdaten-Modus: Score-basierte Technikerwahl, Scope-Filter, Tagesgrenze, Anzeige.

Rein synthetische Daten (keine Echtdaten).
"""
from datetime import date

import pytest

import reporting.dashboard as dash
from auftraege.models import Auftrag, AuftragsTyp
from auftraege.tour_optimierung import BuendelKontext, buendle_mit_qualifikation

HH = (53.55, 9.99)      # Norden
MUC = (48.14, 11.58)    # Sueden
T_NORD = "Tom N."
T_SUED = "Sue S."


def _a(aid, kid, name="Testklinik", familie="FAM", faellig=date(2026, 11, 3)):
    return Auftrag(auftrag_id=aid, auftragstyp=AuftragsTyp.STK, klinik_id=kid, klinik_name=name,
                   geraet_id="MC-1", produkt_familie=familie, faelligkeitsdatum=faellig)


def _kontext(klinik_xy, dauer_std=2.0, auftraege=(), unbekannt=()):
    return BuendelKontext(
        techniker_koordinaten={T_NORD: HH, T_SUED: MUC},
        auslastung_pct={T_NORD: 20.0, T_SUED: 20.0},
        klinik_koordinaten=klinik_xy,
        einsatzdauer_std={a.auftrag_id: dauer_std for a in auftraege},
        faelligkeit_unbekannt=set(unbekannt),
    )


MATRIX = {T_NORD: {"FAM": "L3"}, T_SUED: {"FAM": "L3"}}
IDS = {T_NORD, T_SUED}


def _plaene(auftraege, kontext):
    return buendle_mit_qualifikation(auftraege, techniker_ids=IDS, qualifikationsmatrix=MATRIX, kontext=kontext)


def test_kliniken_in_verschiedenen_regionen_bekommen_verschiedene_techniker():
    auf = [_a("1", "K-N"), _a("2", "K-N"), _a("3", "K-S"), _a("4", "K-S")]
    k = _kontext({"K-N": (53.5, 10.0), "K-S": (48.2, 11.5)}, auftraege=auf)
    plaene = {p.klinik_id: p for p in _plaene(auf, k)}
    assert plaene["K-N"].einsaetze[0].techniker_id == T_NORD
    assert plaene["K-S"].einsaetze[0].techniker_id == T_SUED
    # Begruendung zeigt Fahrzeit und Auslastung
    b = plaene["K-N"].einsaetze[0].begruendung
    assert "Fahrzeit" in b and "Auslastung" in b


def test_gruppe_ueber_8h_wird_geteilt_und_kein_einsatz_ueber_8h():
    auf = [_a(str(i), "K-N") for i in range(6)]
    k = _kontext({"K-N": (53.5, 10.0)}, dauer_std=3.0, auftraege=auf)   # 6 x 3 h = 18 h
    (plan,) = _plaene(auf, k)
    assert len(plan.einsaetze) >= 3
    assert all(e.dauer_std <= 8.0 + 1e-9 for e in plan.einsaetze)
    # eingesparte Fahrten = Auftraege minus Einsaetze
    assert plan.eingesparte_fahrten == 6 - len(plan.einsaetze)


def test_einzelauftrag_ueber_tagesgrenze_ist_nicht_zulaessig():
    auf = [_a("1", "K-N"), _a("2", "K-N"), _a("3", "K-N")]
    k = _kontext({"K-N": (53.5, 10.0)}, dauer_std=2.0, auftraege=auf)
    k.einsatzdauer_std["3"] = 12.0
    (plan,) = _plaene(auf, k)
    assert [a.auftrag_id for a in plan.nicht_planbar] == ["3"]
    assert all(e.dauer_std <= 8.0 + 1e-9 for e in plan.einsaetze)
    assert plan.eingesparte_fahrten == 1


def test_standort_unbekannt_keine_zuweisung():
    auf = [_a("1", "K-X"), _a("2", "K-X")]
    k = _kontext({"K-X": None}, auftraege=auf)
    (plan,) = _plaene(auf, k)
    assert plan.fall == "U" and not plan.standort_bekannt
    assert plan.einsaetze == [] and plan.eingesparte_fahrten == 0
    assert "Standort unbekannt" in plan.hinweis


def test_unbekannte_faelligkeit_ohne_monat():
    auf = [_a("1", "K-N"), _a("2", "K-N")]
    k = _kontext({"K-N": (53.5, 10.0)}, auftraege=auf, unbekannt={"1", "2"})
    (plan,) = _plaene(auf, k)
    assert not plan.faelligkeit_bekannt
    assert "Fälligkeit unbekannt, Potenzial" in plan.hinweis
    assert "2026-" not in plan.hinweis and "fällig im" not in plan.hinweis


def test_klinik_klinik_wird_nicht_doppelt_angezeigt():
    auf = [_a("1", "K-N", name="Klinikum Beispiel"), _a("2", "K-N", name="Klinikum Beispiel")]
    k = _kontext({"K-N": (53.5, 10.0)}, auftraege=auf)
    (plan,) = _plaene(auf, k)
    assert "Klinik Klinikum" not in plan.hinweis
    assert plan.hinweis.startswith("Klinikum Beispiel")


# -- Adapter: Scope-Filter und Schluessel-Zusammenfuehrung ---------------------------------

def _job(nr, klinik, plz, ort="Teststadt", faellig=None):
    return {"auftragsnummer": nr, "klinik": klinik, "plz": plz, "ort": ort, "model_code": "MC-1",
            "produktfamilie": "FAM", "faellig_iso": faellig, "repair_kandidat": False,
            "einsatzdauer_min": 120}


TECHS = [{"pseudonym_id": T_NORD, "lat": HH[0], "lon": HH[1], "auslastung_pct_real": 10.0},
         {"pseudonym_id": T_SUED, "lat": MUC[0], "lon": MUC[1], "auslastung_pct_real": 10.0}]


def test_schweizer_und_interne_accounts_fehlen_in_der_buendelung():
    jobs = [_job("1", "Kantonsspital Test", "8001", ort="Zuerich"),
            _job("2", "Kantonsspital Test", "8001", ort="Zuerich"),
            _job("3", "Medtronic GmbH", "40210", ort="Duesseldorf"),
            _job("4", "Medtronic GmbH", "40210", ort="Duesseldorf"),
            _job("5", "Klinikum Inland", "20095", ort="Hamburg"),
            _job("6", "Klinikum Inland", "20095", ort="Hamburg")]
    e = dash._baue_buendel_eingabe(jobs, TECHS, heute=date(2026, 10, 1))
    namen = {a.klinik_name for a in e["auftraege"]}
    assert namen == {"Klinikum Inland"}
    assert e["scope"]["ausland"] == 2 and e["scope"]["intern"] == 2 and e["scope"]["betrachtet"] == 2
    assert "Nicht gebündelt" in dash._buendel_scope_hinweis(e["scope"])


def test_doppelter_klinik_schluessel_wird_zusammengefuehrt():
    jobs = [_job("1", "Klinikum Doppel", "20095", ort="Hamburg"),
            _job("2", "KLINIKUM  Doppel", "20097", ort="hamburg"),
            _job("3", "Klinikum Doppel", "20095", ort="Hamburg")]
    e = dash._baue_buendel_eingabe(jobs, TECHS, heute=date(2026, 10, 1))
    assert len({a.klinik_id for a in e["auftraege"]}) == 1
    plaene = buendle_mit_qualifikation(
        e["auftraege"], techniker_ids=IDS, qualifikationsmatrix=MATRIX, kontext=e["kontext"])
    assert len(plaene) == 1 and len(plaene[0].alle_auftraege) == 3
