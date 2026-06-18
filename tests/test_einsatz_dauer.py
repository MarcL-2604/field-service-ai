"""Tests fuer auftraege.einsatz_dauer – Labor-Zeiten + Pufferzeiten."""

import pytest

from auftraege.einsatz_dauer import (
    STANDARD_SERVICE_MIN,
    STANDARD_ADMIN_MIN,
    SYNERGIE_FAKTOR,
    RUESTZEIT_FAMILIE_WECHSEL_MIN,
    MAX_EINSATZ_DAUER_MIN,
    PUFFER_STANDARD_MIN,
    PUFFER_NOTFALL_MIN,
    PUFFER_EINSCHLEUSUNG_MIN,
    PUFFER_GESPRAECH_MIN,
    PUFFER_GROSSGERAET_MIN,
    GESPRAECH_STANDARD,
    GESPRAECH_ERSTBESUCH,
    GESPRAECH_COMPLAINT,
    berechne_einsatz_dauer,
    berechne_puffer,
    _lookup_zeiten,
    _lade_labor_zeiten,
)


# ===================================================================
# Konstanten
# ===================================================================

class TestKonstanten:
    def test_standard_fallback(self):
        assert STANDARD_SERVICE_MIN == 90
        assert STANDARD_ADMIN_MIN == 30

    def test_synergie_faktor(self):
        assert SYNERGIE_FAKTOR == 0.70

    def test_ruestzeit_wechsel(self):
        assert RUESTZEIT_FAMILIE_WECHSEL_MIN == 30

    def test_max_einsatz_dauer(self):
        assert MAX_EINSATZ_DAUER_MIN == 360

    def test_puffer_konstanten(self):
        assert PUFFER_STANDARD_MIN == 30
        assert PUFFER_NOTFALL_MIN == 45
        assert PUFFER_EINSCHLEUSUNG_MIN == 20
        assert PUFFER_GESPRAECH_MIN == 15
        assert PUFFER_GROSSGERAET_MIN == 30


# ===================================================================
# Labor-Zeiten Lookup
# ===================================================================

class TestLookupZeiten:
    def test_labor_zeiten_csv_existiert(self):
        df = _lade_labor_zeiten()
        assert not df.empty

    def test_exakter_techniker_match(self):
        df = _lade_labor_zeiten()
        service, admin, quelle = _lookup_zeiten(df, "Hugo", "HugoRAS", "T10")
        assert service == 240
        assert admin == 45
        assert quelle == "techniker_match"

    def test_familien_durchschnitt_fallback(self):
        df = _lade_labor_zeiten()
        service, admin, quelle = _lookup_zeiten(df, "Hugo", "HugoRAS", "T99")
        assert quelle == "familien_durchschnitt"
        assert service == 231

    def test_standard_fallback_unbekannte_familie(self):
        df = _lade_labor_zeiten()
        service, admin, quelle = _lookup_zeiten(df, "Unbekannt", "XYZ", "T1")
        assert service == STANDARD_SERVICE_MIN
        assert quelle == "standard_fallback"

    def test_kein_techniker_nutzt_durchschnitt(self):
        df = _lade_labor_zeiten()
        _, _, quelle = _lookup_zeiten(df, "NIM", "NIM4CM01", None)
        assert quelle == "familien_durchschnitt"


# ===================================================================
# Einzelgeraet-Berechnung (netto_min = alte gesamt ohne Puffer)
# ===================================================================

class TestEinzelgeraet:
    def test_nim_fuer_t5_netto(self):
        """T5 + NIM4CM01 → Netto 80min (60 Service + 20 Admin)."""
        result = berechne_einsatz_dauer(
            [{"produkt_familie": "NIM", "geraete_typ": "NIM4CM01"}],
            techniker_id="T5",
        )
        gd = result.geraete_dauern[0]
        assert gd.service_min == 60
        assert gd.admin_min == 20
        assert gd.gesamt_min == 80
        assert result.netto_min == 80

    def test_gesamt_enthaelt_puffer(self):
        """gesamt_min = netto_min + puffer_gesamt_min."""
        result = berechne_einsatz_dauer(
            [{"produkt_familie": "NIM", "geraete_typ": "NIM4CM01"}],
            techniker_id="T5",
        )
        assert result.gesamt_min == result.netto_min + result.puffer_gesamt_min

    def test_gesamt_std_berechnung(self):
        result = berechne_einsatz_dauer(
            [{"produkt_familie": "NIM", "geraete_typ": "NIM4CM01"}],
            techniker_id="T5",
        )
        assert result.gesamt_std == pytest.approx(result.gesamt_min / 60.0, abs=0.01)


# ===================================================================
# Synergieeffekt
# ===================================================================

class TestSynergieeffekt:
    def test_zweites_geraet_gleiche_familie_70_prozent(self):
        result = berechne_einsatz_dauer(
            [{"produkt_familie": "NIM", "geraete_typ": "NIM4CM01", "anzahl": 2}],
            techniker_id="T5",
        )
        assert result.geraete_dauern[0].gesamt_min == 80
        assert result.geraete_dauern[1].synergie_angewendet
        assert result.geraete_dauern[1].gesamt_min == 42 + 14  # 56

    def test_synergie_nur_innerhalb_gleicher_familie(self):
        result = berechne_einsatz_dauer(
            [
                {"produkt_familie": "NIM", "geraete_typ": "NIM4CM01"},
                {"produkt_familie": "Energie", "geraete_typ": "EC300_Legend"},
            ],
            techniker_id="T5",
        )
        assert not result.geraete_dauern[0].synergie_angewendet
        assert not result.geraete_dauern[1].synergie_angewendet


# ===================================================================
# Ruestzeit
# ===================================================================

class TestRuestzeit:
    def test_kein_wechsel_keine_ruestzeit(self):
        result = berechne_einsatz_dauer(
            [{"produkt_familie": "NIM", "geraete_typ": "NIM4CM01", "anzahl": 2}],
            techniker_id="T5",
        )
        assert result.ruestzeiten_min == 0

    def test_ein_familienwechsel_30min(self):
        result = berechne_einsatz_dauer(
            [
                {"produkt_familie": "NIM", "geraete_typ": "NIM4CM01"},
                {"produkt_familie": "Energie", "geraete_typ": "EC300_Legend"},
            ],
            techniker_id="T5",
        )
        assert result.ruestzeiten_min == 30

    def test_ruestzeit_in_netto_enthalten(self):
        result = berechne_einsatz_dauer(
            [
                {"produkt_familie": "NIM", "geraete_typ": "NIM4CM01"},
                {"produkt_familie": "Energie", "geraete_typ": "EC300_Legend"},
            ],
            techniker_id="T5",
        )
        summe_geraete = sum(gd.gesamt_min for gd in result.geraete_dauern)
        assert result.netto_min == summe_geraete + result.ruestzeiten_min


# ===================================================================
# Puffer-Berechnung
# ===================================================================

class TestPufferBerechnung:
    def test_basis_puffer_immer_vorhanden(self):
        """Basis-Puffer 30min ist immer dabei."""
        puffer = berechne_puffer(["NIM"])
        basis = [p for p in puffer if p.bezeichnung == "Basis-Puffer"]
        assert len(basis) == 1
        assert basis[0].minuten == PUFFER_STANDARD_MIN

    def test_uniklinikum_einschleusung_20min(self):
        puffer = berechne_puffer(["NIM"], klinik_groesse="uni")
        einschleusung = [p for p in puffer if "Einschleusung" in p.bezeichnung]
        assert len(einschleusung) == 1
        assert einschleusung[0].minuten == PUFFER_EINSCHLEUSUNG_MIN

    def test_grossklinik_einschleusung_10min(self):
        puffer = berechne_puffer(["NIM"], klinik_groesse="gross")
        einschleusung = [p for p in puffer if "Einschleusung" in p.bezeichnung]
        assert len(einschleusung) == 1
        assert einschleusung[0].minuten == 10

    def test_mittelklinik_einschleusung_10min(self):
        puffer = berechne_puffer(["NIM"], klinik_groesse="mittel")
        einschleusung = [p for p in puffer if "Einschleusung" in p.bezeichnung]
        assert len(einschleusung) == 1
        assert einschleusung[0].minuten == 10

    def test_kein_kliniktyp_keine_einschleusung(self):
        puffer = berechne_puffer(["NIM"])
        einschleusung = [p for p in puffer if "Einschleusung" in p.bezeichnung]
        assert len(einschleusung) == 0

    def test_grossgeraet_hugo_puffer(self):
        puffer = berechne_puffer(["Hugo"], klinik_groesse="uni")
        gross = [p for p in puffer if "Grossgeraet" in p.bezeichnung]
        assert len(gross) == 1
        assert gross[0].minuten == PUFFER_GROSSGERAET_MIN

    def test_energie_kein_grossgeraet_puffer(self):
        """EC300/IPC = Small Capital → kein Grossgeraet-Puffer."""
        puffer = berechne_puffer(["Energie"])
        gross = [p for p in puffer if "Grossgeraet" in p.bezeichnung]
        assert len(gross) == 0

    def test_grossgeraet_navigation_puffer(self):
        puffer = berechne_puffer(["Navigation"])
        gross = [p for p in puffer if "Grossgeraet" in p.bezeichnung]
        assert len(gross) == 1

    def test_kleingeraet_nim_kein_grossgeraet_puffer(self):
        puffer = berechne_puffer(["NIM"])
        gross = [p for p in puffer if "Grossgeraet" in p.bezeichnung]
        assert len(gross) == 0

    def test_grossgeraet_puffer_einmalig(self):
        """Auch bei 2 Grossgeraeten nur 1x Grossgeraet-Puffer."""
        puffer = berechne_puffer(["Hugo", "Navigation"])
        gross = [p for p in puffer if "Grossgeraet" in p.bezeichnung]
        assert len(gross) == 1

    def test_gespraech_standard_15min(self):
        puffer = berechne_puffer(["NIM"], gespraech_typ=GESPRAECH_STANDARD)
        gespraech = [p for p in puffer if "Gespraech" in p.bezeichnung]
        assert len(gespraech) == 1
        assert gespraech[0].minuten == 15

    def test_gespraech_erstbesuch_30min(self):
        puffer = berechne_puffer(["NIM"], gespraech_typ=GESPRAECH_ERSTBESUCH)
        gespraech = [p for p in puffer if "Gespraech" in p.bezeichnung or "Erstbesuch" in p.bezeichnung]
        assert len(gespraech) == 1
        assert gespraech[0].minuten == 30

    def test_gespraech_complaint_45min(self):
        puffer = berechne_puffer(["NIM"], gespraech_typ=GESPRAECH_COMPLAINT)
        gespraech = [p for p in puffer if "Gespraech" in p.bezeichnung or "Beschwerde" in p.bezeichnung]
        assert len(gespraech) == 1
        assert gespraech[0].minuten == 45

    def test_klinik_id_lookup(self):
        """K001 = UKE Hamburg = uni → 20min Einschleusung."""
        puffer = berechne_puffer(["NIM"], klinik_id="K001")
        einschleusung = [p for p in puffer if "Einschleusung" in p.bezeichnung]
        assert len(einschleusung) == 1
        assert einschleusung[0].minuten == PUFFER_EINSCHLEUSUNG_MIN

    def test_klinik_groesse_ueberschreibt_lookup(self):
        """Explizite klinik_groesse hat Vorrang vor klinik_id Lookup."""
        puffer = berechne_puffer(["NIM"], klinik_id="K001", klinik_groesse="mittel")
        einschleusung = [p for p in puffer if "Einschleusung" in p.bezeichnung]
        assert einschleusung[0].minuten == 10  # mittel, nicht uni


# ===================================================================
# Puffer im EinsatzDauer-Ergebnis
# ===================================================================

class TestPufferInEinsatzDauer:
    def test_puffer_details_vorhanden(self):
        result = berechne_einsatz_dauer(
            [{"produkt_familie": "NIM", "geraete_typ": "NIM4CM01"}],
            techniker_id="T5",
        )
        assert len(result.puffer_details) >= 2  # mindestens Basis + Gespraech

    def test_puffer_gesamt_ist_summe(self):
        result = berechne_einsatz_dauer(
            [{"produkt_familie": "Hugo", "geraete_typ": "HugoRAS"}],
            techniker_id="T10",
            klinik_groesse="uni",
        )
        assert result.puffer_gesamt_min == sum(p.minuten for p in result.puffer_details)

    def test_gesamt_gleich_netto_plus_puffer(self):
        result = berechne_einsatz_dauer(
            [{"produkt_familie": "NIM", "geraete_typ": "NIM4CM01"}],
            techniker_id="T5",
            klinik_groesse="uni",
        )
        assert result.gesamt_min == result.netto_min + result.puffer_gesamt_min

    def test_nim_kleingeraet_standard_puffer(self):
        """NIM (kein Grossgeraet), keine Klinik → Basis(30) + Gespraech(15) = 45min."""
        result = berechne_einsatz_dauer(
            [{"produkt_familie": "NIM", "geraete_typ": "NIM4CM01"}],
            techniker_id="T5",
        )
        assert result.puffer_gesamt_min == PUFFER_STANDARD_MIN + PUFFER_GESPRAECH_MIN

    def test_hugo_uni_voller_puffer(self):
        """Hugo + Uniklinikum → Basis(30) + Einschleusung(20) + Grossgeraet(30) + Gespraech(15) = 95min."""
        result = berechne_einsatz_dauer(
            [{"produkt_familie": "Hugo", "geraete_typ": "HugoRAS"}],
            techniker_id="T10",
            klinik_groesse="uni",
        )
        assert result.puffer_gesamt_min == 30 + 20 + 30 + 15  # 95

    def test_erstbesuch_puffer(self):
        """Erstbesuch: Gespraech 30min statt 15min."""
        result = berechne_einsatz_dauer(
            [{"produkt_familie": "NIM", "geraete_typ": "NIM4CM01"}],
            techniker_id="T5",
            gespraech_typ=GESPRAECH_ERSTBESUCH,
        )
        assert result.puffer_gesamt_min == PUFFER_STANDARD_MIN + 30

    def test_complaint_puffer(self):
        """Nach Beschwerde: Gespraech 45min."""
        result = berechne_einsatz_dauer(
            [{"produkt_familie": "NIM", "geraete_typ": "NIM4CM01"}],
            techniker_id="T5",
            gespraech_typ=GESPRAECH_COMPLAINT,
        )
        assert result.puffer_gesamt_min == PUFFER_STANDARD_MIN + PUFFER_NOTFALL_MIN


# ===================================================================
# Kombiniertes Beispiel (User Story mit Puffer)
# ===================================================================

class TestKombiBeispielMitPuffer:
    def test_t5_nim_ec300_ukb_bonn(self):
        """T5 · UKB Bonn · EC300 + NIM:
        Netto:
          NIM: 60+20 = 80min
          EC300: 90+30 = 120min
          Ruestzeit: +30min
          = 230min
        Puffer (EC300 = Small Capital, kein Grossgeraet-Puffer):
          Basis: 30min
          Einschleusung UKL: 20min (K017 = uni)
          Gespraech: 15min
          = 65min
        Gesamt: 295min = 4h 55min
        """
        result = berechne_einsatz_dauer(
            [
                {"produkt_familie": "NIM", "geraete_typ": "NIM4CM01"},
                {"produkt_familie": "Energie", "geraete_typ": "EC300_Legend"},
            ],
            techniker_id="T5",
            klinik_id="K017",  # Uni Bonn = uni
        )
        assert result.netto_min == 230
        assert result.puffer_gesamt_min == 65  # kein Grossgeraet fuer EC300
        assert result.gesamt_min == 295
        assert not result.ueberschreitet_max

    def test_t5_nim_ec300_ohne_klinik(self):
        """Ohne Klinik-Info: kein Einschleusungs-Puffer, kein Grossgeraet."""
        result = berechne_einsatz_dauer(
            [
                {"produkt_familie": "NIM", "geraete_typ": "NIM4CM01"},
                {"produkt_familie": "Energie", "geraete_typ": "EC300_Legend"},
            ],
            techniker_id="T5",
        )
        assert result.netto_min == 230
        # Basis(30) + Gespraech(15) = 45 (kein Grossgeraet fuer EC300)
        assert result.puffer_gesamt_min == 45
        assert result.gesamt_min == 275


# ===================================================================
# Tagesmaximum mit Puffer
# ===================================================================

class TestTagesMaxMitPuffer:
    def test_hugo_mit_puffer_ueberschreitet(self):
        """2x Hugo + uni-Puffer → weit ueber 360min."""
        result = berechne_einsatz_dauer(
            [{"produkt_familie": "Hugo", "geraete_typ": "HugoRAS", "anzahl": 2}],
            techniker_id="T10",
            klinik_groesse="uni",
        )
        assert result.ueberschreitet_max

    def test_kleiner_einsatz_mit_puffer_unter_max(self):
        """1x NIM + Puffer → netto 80 + puffer 45 = 125min → unter 360min."""
        result = berechne_einsatz_dauer(
            [{"produkt_familie": "NIM", "geraete_typ": "NIM4CM01"}],
            techniker_id="T5",
        )
        assert not result.ueberschreitet_max


# ===================================================================
# Dashboard-Text
# ===================================================================

class TestDashboardText:
    def test_dashboard_enthaelt_techniker(self):
        result = berechne_einsatz_dauer(
            [{"produkt_familie": "NIM", "geraete_typ": "NIM4CM01"}],
            techniker_id="T5",
        )
        assert "T5" in result.dashboard_text

    def test_dashboard_enthaelt_netto_und_puffer(self):
        result = berechne_einsatz_dauer(
            [{"produkt_familie": "NIM", "geraete_typ": "NIM4CM01"}],
            techniker_id="T5",
        )
        assert "Netto" in result.dashboard_text
        assert "Puffer" in result.dashboard_text
        assert "Geplant" in result.dashboard_text

    def test_dashboard_zeigt_puffer_posten(self):
        result = berechne_einsatz_dauer(
            [{"produkt_familie": "Hugo", "geraete_typ": "HugoRAS"}],
            techniker_id="T10",
            klinik_groesse="uni",
        )
        assert "Basis-Puffer" in result.dashboard_text
        assert "Einschleusung" in result.dashboard_text
        assert "Grossgeraet" in result.dashboard_text

    def test_dashboard_zeigt_synergie(self):
        result = berechne_einsatz_dauer(
            [{"produkt_familie": "NIM", "geraete_typ": "NIM4CM01", "anzahl": 2}],
            techniker_id="T5",
        )
        assert "Synergie" in result.dashboard_text


# ===================================================================
# Integration: tour_optimierung nutzt echte Zeiten
# ===================================================================

class TestTourIntegration:
    def test_standard_einsatzdauer_nutzt_labor_zeiten(self):
        from auftraege.models import Auftrag, AuftragsTyp
        from auftraege.tour_optimierung import _standard_einsatzdauer
        from datetime import date

        auftrag = Auftrag(
            auftrag_id="TEST",
            auftragstyp=AuftragsTyp.STK,
            klinik_id="K001",
            klinik_name="Test",
            geraet_id="NIM4CM01",
            produkt_familie="NIM",
            faelligkeitsdatum=date(2026, 4, 1),
        )
        dauer = _standard_einsatzdauer(auftrag)
        # Sollte aus labor_zeiten.csv kommen (inkl. Puffer), nicht 4.0h Pauschal
        assert dauer < 3.0, f"Dauer {dauer}h scheint Pauschalwert, nicht labor_zeiten"
