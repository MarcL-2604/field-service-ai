"""Tests fuer reporting/hugo_zusatzgebiet.py: optionale Hugo-Zusatzgebiet-Regel
(95-Minuten-Radius fuer Small-Capital-Zusatzprodukte, immer PM-only)."""

from config import HUGO_ZUSATZGEBIET_MAX_FAHRZEIT_MIN, HUGO_ZUSATZGEBIET_PRODUKTE
from reporting.hugo_zusatzgebiet import (
    berechne_hugo_zusatzgebiete,
    ist_zusatzprodukt,
    repair_erlaubt_in_zusatzgebiet,
)


TECHNIKER = {
    "T1": {"standort": "Hamburg", "lat": 53.55, "lon": 9.99},
    "T6": {"standort": "Schenefeld", "lat": 53.60, "lon": 9.83},
    "T10": {"standort": "Balingen", "lat": 48.27, "lon": 8.85},
    "T11": {"standort": "Gangelt", "lat": 51.00, "lon": 6.05},
    "T99_ohne_koords": {"standort": "Unbekannt", "lat": 0.0, "lon": 0.0},
}
HUGO_KA_IDS = {"T1", "T6", "T10", "T11"}


class TestIstZusatzprodukt:
    def test_echter_mc_code_matcht(self):
        assert ist_zusatzprodukt("MC-NIM4CM01", HUGO_ZUSATZGEBIET_PRODUKTE)
        assert ist_zusatzprodukt("MC-2090", HUGO_ZUSATZGEBIET_PRODUKTE)

    def test_platzhalter_matcht_kein_echtes_geraet(self):
        assert not ist_zusatzprodukt("MC-NIM3-IRGENDWAS", HUGO_ZUSATZGEBIET_PRODUKTE)
        assert not ist_zusatzprodukt("MC-CVG-9999", HUGO_ZUSATZGEBIET_PRODUKTE)

    def test_fremdes_geraet_matcht_nicht(self):
        assert not ist_zusatzprodukt("MC-HUGO", HUGO_ZUSATZGEBIET_PRODUKTE)


class TestRepairErlaubtInZusatzgebiet:
    def test_zusatzprodukt_ist_immer_pm_only(self):
        for mc in ["MC-NIM4CM01", "MC-NIM4CPB1", "MC-2090", "MC-ACT200", "MC-40-405-1"]:
            assert repair_erlaubt_in_zusatzgebiet(mc, HUGO_ZUSATZGEBIET_PRODUKTE) is False

    def test_andere_geraete_unveraendert_erlaubt(self):
        assert repair_erlaubt_in_zusatzgebiet("MC-HUGO", HUGO_ZUSATZGEBIET_PRODUKTE) is True
        assert repair_erlaubt_in_zusatzgebiet("MC-840", HUGO_ZUSATZGEBIET_PRODUKTE) is True

    def test_platzhalter_ohne_absturz(self):
        # Platzhalter-Eintraege sind Prosa, kein MC-Code -- duerfen nie
        # versehentlich ein echtes Geraet matchen, aber auch nicht crashen.
        for platzhalter in HUGO_ZUSATZGEBIET_PRODUKTE:
            if "Platzhalter" in platzhalter:
                assert repair_erlaubt_in_zusatzgebiet("MC-IRGENDWAS", HUGO_ZUSATZGEBIET_PRODUKTE) is True


class TestBerechneHugoZusatzgebiete:
    def test_nur_techniker_mit_wenig_hugo_systemen(self):
        hugo_systeme = {"T1": 0, "T6": 5, "T10": 1, "T11": 2}
        ergebnis = berechne_hugo_zusatzgebiete(
            TECHNIKER, HUGO_KA_IDS, hugo_systeme,
            HUGO_ZUSATZGEBIET_MAX_FAHRZEIT_MIN, umweg_faktor=1.35,
        )
        ids = {e["id"] for e in ergebnis}
        assert ids == {"T1", "T10", "T11"}  # T6 hat 5 > 2 Hugo-Systeme -> ausgeschlossen

    def test_95_minuten_grenze_wird_angewendet(self):
        hugo_systeme = {"T1": 0}
        ergebnis = berechne_hugo_zusatzgebiete(
            {"T1": TECHNIKER["T1"]}, {"T1"}, hugo_systeme,
            95, umweg_faktor=1.35,
        )
        assert len(ergebnis) == 1
        # 95 min bei effektiver Geschwindigkeit 100/1.35 km/h
        erwarteter_radius = 95 / 60.0 * (100.0 / 1.35)
        assert abs(ergebnis[0]["radius_km"] - round(erwarteter_radius, 1)) < 0.05

    def test_radius_skaliert_mit_max_fahrzeit(self):
        hugo_systeme = {"T1": 0}
        kurz = berechne_hugo_zusatzgebiete(
            {"T1": TECHNIKER["T1"]}, {"T1"}, hugo_systeme, 60, umweg_faktor=1.35,
        )
        lang = berechne_hugo_zusatzgebiete(
            {"T1": TECHNIKER["T1"]}, {"T1"}, hugo_systeme, 95, umweg_faktor=1.35,
        )
        assert lang[0]["radius_km"] > kurz[0]["radius_km"]

    def test_techniker_ohne_koordinaten_wird_uebersprungen(self):
        hugo_systeme = {"T99_ohne_koords": 0}
        ergebnis = berechne_hugo_zusatzgebiete(
            TECHNIKER, {"T99_ohne_koords"}, hugo_systeme, 95, umweg_faktor=1.35,
        )
        assert ergebnis == []

    def test_leere_hugo_systeme_daten_liefert_leere_liste_ohne_absturz(self):
        # z.B. Demo-Modus ohne reale Geraetedichte-Daten
        ergebnis = berechne_hugo_zusatzgebiete(
            TECHNIKER, HUGO_KA_IDS, {}, 95, umweg_faktor=1.35,
        )
        # hugo_systeme_pro_tech.get(tid, 0) -> 0 fuer alle -> alle qualifizieren
        assert len(ergebnis) == len(HUGO_KA_IDS - {"T99_ohne_koords"})

    def test_nicht_hugo_ka_techniker_wird_nicht_beruecksichtigt(self):
        hugo_systeme = {"T1": 0, "T99_ohne_koords": 0}
        ergebnis = berechne_hugo_zusatzgebiete(
            TECHNIKER, {"T1"}, hugo_systeme, 95, umweg_faktor=1.35,
        )
        assert {e["id"] for e in ergebnis} == {"T1"}
