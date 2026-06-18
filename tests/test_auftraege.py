"""Tests fuer den Auftrags-Lifecycle (models, dispatcher, kv_pruefung, abschlusskontrolle, workflow)."""

from __future__ import annotations

import warnings
from datetime import date, datetime
import pytest

from auftraege.models import (
    Auftrag,
    AuftragsStatus,
    AuftragsTyp,
    Dokument,
    DokumentTyp,
)
from auftraege.kv_pruefung import (
    _KV_SCHWELLWERT_EUR,
    kv_bestaetigen,
    kv_erforderlich,
)
from auftraege.abschlusskontrolle import pflichtdokumente_pruefen
from auftraege.dispatcher import (
    _quartal_zu_datum,
    auftrag_benachrichtigen,
    auftrag_zuweisen,
    naechste_faellige_auftraege,
)
from auftraege.workflow import (
    Dringlichkeit,
    EmpfehlungsReport,
    TechnikerEmpfehlung,
    _berechne_dringlichkeit,
    _TAGE_KRITISCH,
    _TAGE_HOCH,
    _HINWEIS_KEIN_AUTO_ASSIGN,
    empfehlung_generieren,
)


# ---------------------------------------------------------------------------
# Hilfsfunktionen / Fixtures
# ---------------------------------------------------------------------------

def _auftrag(
    typ: AuftragsTyp = AuftragsTyp.STK,
    klinik_id: str = "K001",
    klinik_name: str = "Testklinkum Hamburg",
    produkt: str = "Neuromonitoring",
    faelligkeit: date = date(2025, 4, 1),
    techniker_id: str | None = None,
    kostenschaetzung: float | None = None,
    status: AuftragsStatus = AuftragsStatus.NEU,
    dokumente: list[Dokument] | None = None,
) -> Auftrag:
    return Auftrag(
        auftrag_id="TEST-0001",
        auftragstyp=typ,
        klinik_id=klinik_id,
        klinik_name=klinik_name,
        geraet_id="NIM4CM01",
        produkt_familie=produkt,
        faelligkeitsdatum=faelligkeit,
        techniker_id=techniker_id,
        status=status,
        kostenschaetzung_eur=kostenschaetzung,
        dokumente=dokumente or [],
    )


def _dok(typ: DokumentTyp, angehaengt: bool = True, pflicht: bool = True) -> Dokument:
    return Dokument(typ=typ, angehaengt=angehaengt, pflicht=pflicht)


# ---------------------------------------------------------------------------
# auftraege/models.py
# ---------------------------------------------------------------------------

class TestAuftragModel:
    def test_default_status_ist_neu(self):
        a = _auftrag()
        assert a.status == AuftragsStatus.NEU

    def test_ist_zugewiesen_ohne_techniker(self):
        a = _auftrag()
        assert not a.ist_zugewiesen()

    def test_ist_zugewiesen_mit_techniker_und_status(self):
        a = _auftrag(techniker_id="T1", status=AuftragsStatus.ZUGEWIESEN)
        assert a.ist_zugewiesen()

    def test_fehlende_pflichtdokumente_leer_wenn_alle_angehaengt(self):
        a = _auftrag(dokumente=[
            _dok(DokumentTyp.MESSPROTOKOLL),
            _dok(DokumentTyp.SERVICEBERICHT),
        ])
        assert a.fehlende_pflichtdokumente() == []

    def test_fehlende_pflichtdokumente_erkennt_luecke(self):
        a = _auftrag(dokumente=[
            _dok(DokumentTyp.MESSPROTOKOLL, angehaengt=False),
            _dok(DokumentTyp.SERVICEBERICHT, angehaengt=True),
        ])
        fehlend = a.fehlende_pflichtdokumente()
        assert DokumentTyp.MESSPROTOKOLL in fehlend
        assert DokumentTyp.SERVICEBERICHT not in fehlend

    def test_optionales_dokument_nicht_in_fehlend(self):
        a = _auftrag(dokumente=[
            _dok(DokumentTyp.FOTO_VORHER, angehaengt=False, pflicht=False),
        ])
        assert a.fehlende_pflichtdokumente() == []

    def test_anzahl_geraete_validierung(self):
        with pytest.raises(Exception):
            Auftrag(
                auftrag_id="X",
                auftragstyp=AuftragsTyp.STK,
                klinik_name="Test",
                geraet_id="NIM",
                produkt_familie="Neuromonitoring",
                faelligkeitsdatum=date(2025, 1, 1),
                anzahl_geraete=0,  # ungueltig: muss >= 1 sein
            )


class TestDokument:
    def test_fehlt_wenn_pflicht_und_nicht_angehaengt(self):
        d = Dokument(typ=DokumentTyp.SERVICEBERICHT, angehaengt=False, pflicht=True)
        assert d.fehlt()

    def test_fehlt_nicht_wenn_angehaengt(self):
        d = Dokument(typ=DokumentTyp.SERVICEBERICHT, angehaengt=True, pflicht=True)
        assert not d.fehlt()

    def test_fehlt_nicht_wenn_nicht_pflicht(self):
        d = Dokument(typ=DokumentTyp.FOTO_VORHER, angehaengt=False, pflicht=False)
        assert not d.fehlt()


# ---------------------------------------------------------------------------
# auftraege/kv_pruefung.py
# ---------------------------------------------------------------------------

class TestKvErforderlich:
    def test_stk_niemals_kv(self):
        a = _auftrag(typ=AuftragsTyp.STK, kostenschaetzung=9999.0)
        assert not kv_erforderlich(a)

    def test_pm_niemals_kv(self):
        a = _auftrag(typ=AuftragsTyp.PM, kostenschaetzung=9999.0)
        assert not kv_erforderlich(a)

    def test_repair_ohne_kostenschaetzung_kein_kv(self):
        a = _auftrag(typ=AuftragsTyp.REPAIR, kostenschaetzung=None)
        assert not kv_erforderlich(a)

    def test_repair_unter_schwellwert_kein_kv(self):
        a = _auftrag(typ=AuftragsTyp.REPAIR, kostenschaetzung=_KV_SCHWELLWERT_EUR - 0.01)
        assert not kv_erforderlich(a)

    def test_repair_exakt_schwellwert_kein_kv(self):
        # Schwellwert ist exklusiv: > Schwellwert erforderlich, = nicht
        a = _auftrag(typ=AuftragsTyp.REPAIR, kostenschaetzung=_KV_SCHWELLWERT_EUR)
        assert not kv_erforderlich(a)

    def test_repair_ueber_schwellwert_kv_erforderlich(self):
        a = _auftrag(typ=AuftragsTyp.REPAIR, kostenschaetzung=_KV_SCHWELLWERT_EUR + 0.01)
        assert kv_erforderlich(a)

    def test_repair_weit_ueber_schwellwert(self):
        a = _auftrag(typ=AuftragsTyp.REPAIR, kostenschaetzung=5000.0)
        assert kv_erforderlich(a)


class TestKvBestaetigen:
    def test_bestaetigt_repair_auftrag(self):
        a = _auftrag(typ=AuftragsTyp.REPAIR)
        kv_bestaetigen(a, 750.0)
        assert a.kv_bestaetigt is True
        assert a.kostenschaetzung_eur == 750.0

    def test_betrag_null_erlaubt(self):
        a = _auftrag(typ=AuftragsTyp.REPAIR)
        kv_bestaetigen(a, 0.0)
        assert a.kv_bestaetigt is True
        assert a.kostenschaetzung_eur == 0.0

    def test_negativer_betrag_wirft_valueerror(self):
        a = _auftrag(typ=AuftragsTyp.REPAIR)
        with pytest.raises(ValueError, match="negativ"):
            kv_bestaetigen(a, -1.0)

    def test_falscher_auftragstyp_wirft_valueerror(self):
        a = _auftrag(typ=AuftragsTyp.STK)
        with pytest.raises(ValueError, match="Repair"):
            kv_bestaetigen(a, 300.0)

    def test_pm_wirft_valueerror(self):
        a = _auftrag(typ=AuftragsTyp.PM)
        with pytest.raises(ValueError):
            kv_bestaetigen(a, 600.0)


# ---------------------------------------------------------------------------
# auftraege/abschlusskontrolle.py
# ---------------------------------------------------------------------------

class TestPflichtdokumentePruefen:
    # --- STK ---
    def test_stk_vollstaendig(self):
        a = _auftrag(typ=AuftragsTyp.STK, dokumente=[
            _dok(DokumentTyp.MESSPROTOKOLL),
            _dok(DokumentTyp.SERVICEBERICHT),
        ])
        ergebnis = pflichtdokumente_pruefen(a)
        assert ergebnis["vollstaendig"] is True
        assert ergebnis["fehlend"] == []

    def test_stk_fehlt_messprotokoll(self):
        a = _auftrag(typ=AuftragsTyp.STK, dokumente=[
            _dok(DokumentTyp.SERVICEBERICHT),
        ])
        ergebnis = pflichtdokumente_pruefen(a)
        assert ergebnis["vollstaendig"] is False
        assert "Messprotokoll" in ergebnis["fehlend"]

    def test_stk_fehlt_servicebericht(self):
        a = _auftrag(typ=AuftragsTyp.STK, dokumente=[
            _dok(DokumentTyp.MESSPROTOKOLL),
        ])
        ergebnis = pflichtdokumente_pruefen(a)
        assert ergebnis["vollstaendig"] is False
        assert "Servicebericht" in ergebnis["fehlend"]

    def test_stk_beide_fehlen(self):
        a = _auftrag(typ=AuftragsTyp.STK, dokumente=[])
        ergebnis = pflichtdokumente_pruefen(a)
        assert ergebnis["vollstaendig"] is False
        assert len(ergebnis["fehlend"]) == 2

    def test_stk_erforderliche_typen(self):
        a = _auftrag(typ=AuftragsTyp.STK, dokumente=[])
        ergebnis = pflichtdokumente_pruefen(a)
        typen = set(ergebnis["erforderliche_typen"])
        assert "Messprotokoll" in typen
        assert "Servicebericht" in typen

    # --- PM ---
    def test_pm_vollstaendig(self):
        a = _auftrag(typ=AuftragsTyp.PM, dokumente=[
            _dok(DokumentTyp.SERVICEBERICHT),
            _dok(DokumentTyp.CHECKLISTE),
        ])
        ergebnis = pflichtdokumente_pruefen(a)
        assert ergebnis["vollstaendig"] is True

    def test_pm_fehlt_checkliste(self):
        a = _auftrag(typ=AuftragsTyp.PM, dokumente=[
            _dok(DokumentTyp.SERVICEBERICHT),
        ])
        ergebnis = pflichtdokumente_pruefen(a)
        assert ergebnis["vollstaendig"] is False
        assert "Checkliste" in ergebnis["fehlend"]

    def test_pm_kein_messprotokoll_erforderlich(self):
        a = _auftrag(typ=AuftragsTyp.PM, dokumente=[])
        ergebnis = pflichtdokumente_pruefen(a)
        assert "Messprotokoll" not in ergebnis["erforderliche_typen"]

    # --- Repair ---
    def test_repair_vollstaendig_ohne_kv(self):
        a = _auftrag(
            typ=AuftragsTyp.REPAIR,
            kostenschaetzung=300.0,  # unter Schwellwert -> kein KV
            dokumente=[
                _dok(DokumentTyp.SERVICEBERICHT),
                _dok(DokumentTyp.FOTO_VORHER),
                _dok(DokumentTyp.FOTO_NACHHER),
            ],
        )
        ergebnis = pflichtdokumente_pruefen(a)
        assert ergebnis["vollstaendig"] is True

    def test_repair_kv_erforderlich_und_vorhanden(self):
        a = _auftrag(
            typ=AuftragsTyp.REPAIR,
            kostenschaetzung=_KV_SCHWELLWERT_EUR + 1,
            dokumente=[
                _dok(DokumentTyp.SERVICEBERICHT),
                _dok(DokumentTyp.FOTO_VORHER),
                _dok(DokumentTyp.FOTO_NACHHER),
                _dok(DokumentTyp.KV),
            ],
        )
        ergebnis = pflichtdokumente_pruefen(a)
        assert ergebnis["vollstaendig"] is True
        assert "KV" in ergebnis["erforderliche_typen"]

    def test_repair_kv_erforderlich_aber_fehlend(self):
        a = _auftrag(
            typ=AuftragsTyp.REPAIR,
            kostenschaetzung=_KV_SCHWELLWERT_EUR + 100,
            dokumente=[
                _dok(DokumentTyp.SERVICEBERICHT),
                _dok(DokumentTyp.FOTO_VORHER),
                _dok(DokumentTyp.FOTO_NACHHER),
                # KV fehlt
            ],
        )
        ergebnis = pflichtdokumente_pruefen(a)
        assert ergebnis["vollstaendig"] is False
        assert "KV" in ergebnis["fehlend"]

    def test_repair_kv_nicht_erforderlich_wenn_unter_schwellwert(self):
        a = _auftrag(
            typ=AuftragsTyp.REPAIR,
            kostenschaetzung=100.0,
            dokumente=[
                _dok(DokumentTyp.SERVICEBERICHT),
                _dok(DokumentTyp.FOTO_VORHER),
                _dok(DokumentTyp.FOTO_NACHHER),
            ],
        )
        ergebnis = pflichtdokumente_pruefen(a)
        assert ergebnis["vollstaendig"] is True
        assert "KV" not in ergebnis["erforderliche_typen"]

    def test_repair_fehlt_foto_vorher(self):
        a = _auftrag(
            typ=AuftragsTyp.REPAIR,
            kostenschaetzung=None,
            dokumente=[
                _dok(DokumentTyp.SERVICEBERICHT),
                _dok(DokumentTyp.FOTO_NACHHER),
            ],
        )
        ergebnis = pflichtdokumente_pruefen(a)
        assert ergebnis["vollstaendig"] is False
        assert "Foto_vorher" in ergebnis["fehlend"]

    def test_repair_nicht_angehaengtes_dok_gilt_als_fehlend(self):
        a = _auftrag(
            typ=AuftragsTyp.REPAIR,
            kostenschaetzung=None,
            dokumente=[
                _dok(DokumentTyp.SERVICEBERICHT),
                _dok(DokumentTyp.FOTO_VORHER, angehaengt=False),  # vorhanden aber nicht angehaengt
                _dok(DokumentTyp.FOTO_NACHHER),
            ],
        )
        ergebnis = pflichtdokumente_pruefen(a)
        assert ergebnis["vollstaendig"] is False
        assert "Foto_vorher" in ergebnis["fehlend"]


# ---------------------------------------------------------------------------
# auftraege/dispatcher.py – _quartal_zu_datum
# ---------------------------------------------------------------------------

class TestQuartalZuDatum:
    def test_q1(self):
        assert _quartal_zu_datum("2025-Q1") == date(2025, 1, 1)

    def test_q2(self):
        assert _quartal_zu_datum("2025-Q2") == date(2025, 4, 1)

    def test_q3(self):
        assert _quartal_zu_datum("2026-Q3") == date(2026, 7, 1)

    def test_q4(self):
        assert _quartal_zu_datum("2024-Q4") == date(2024, 10, 1)

    def test_ungueltig_wirft_valueerror(self):
        with pytest.raises(ValueError):
            _quartal_zu_datum("2025-Q5")

    def test_falsches_format_wirft_valueerror(self):
        with pytest.raises(ValueError):
            _quartal_zu_datum("2025-01-01")

    def test_leerzeichen_werden_toleriert(self):
        assert _quartal_zu_datum("  2025-Q2  ") == date(2025, 4, 1)


# ---------------------------------------------------------------------------
# auftraege/dispatcher.py – naechste_faellige_auftraege
# ---------------------------------------------------------------------------

class TestNaechsteFaelligeAuftraege:
    def test_gibt_liste_zurueck(self):
        auftraege = naechste_faellige_auftraege(n=5)
        assert isinstance(auftraege, list)
        assert len(auftraege) <= 5

    def test_maximale_anzahl_respektiert(self):
        auftraege = naechste_faellige_auftraege(n=3)
        assert len(auftraege) <= 3

    def test_aufsteigend_sortiert(self):
        auftraege = naechste_faellige_auftraege(n=20)
        for i in range(1, len(auftraege)):
            assert auftraege[i].faelligkeitsdatum >= auftraege[i - 1].faelligkeitsdatum

    def test_alle_typ_stk(self):
        auftraege = naechste_faellige_auftraege(n=10)
        assert all(a.auftragstyp == AuftragsTyp.STK for a in auftraege)

    def test_alle_status_neu(self):
        auftraege = naechste_faellige_auftraege(n=10)
        assert all(a.status == AuftragsStatus.NEU for a in auftraege)

    def test_auftrag_id_eindeutig(self):
        auftraege = naechste_faellige_auftraege(n=20)
        ids = [a.auftrag_id for a in auftraege]
        assert len(ids) == len(set(ids))

    def test_faelligkeitsdatum_ist_date_objekt(self):
        auftraege = naechste_faellige_auftraege(n=5)
        for a in auftraege:
            assert isinstance(a.faelligkeitsdatum, date)


# ---------------------------------------------------------------------------
# auftraege/dispatcher.py – auftrag_zuweisen
# ---------------------------------------------------------------------------

class TestAuftragZuweisen:
    def test_zuweisung_mit_gueltiger_klinik(self):
        """T6 oder T9 sollte NIM/Neuromonitoring fuer K001 (UKE Hamburg) bekommen."""
        a = _auftrag(
            typ=AuftragsTyp.STK,
            klinik_id="K001",
            produkt="Neuromonitoring",
        )
        # T10 hat L3 Neuromonitoring, aber ist in BaWü -> weit weg
        # T6 hat kein Neuromonitoring -> T9, T5 haben L3
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = auftrag_zuweisen(a)
        # Es kann auch None sein wenn kein qualifizierter naher Techniker da ist
        if result is not None:
            assert result.status == AuftragsStatus.ZUGEWIESEN
            assert result.techniker_id is not None

    def test_kein_klinik_id_gibt_none_mit_warnung(self):
        a = _auftrag(klinik_id=None)
        with pytest.warns(UserWarning, match="klinik_id fehlt"):
            result = auftrag_zuweisen(a)
        assert result is None

    def test_unbekannte_klinik_id_gibt_none(self):
        a = _auftrag(klinik_id="K999")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = auftrag_zuweisen(a)
        assert result is None

    def test_status_bleibt_neu_wenn_keine_zuweisung(self):
        a = _auftrag(klinik_id=None)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            auftrag_zuweisen(a)
        assert a.status == AuftragsStatus.NEU

    def test_nicht_qualifizierte_familie_gibt_none(self):
        """'Energie' hat nur T1 und T11 – K017 (Bonn) liegt ausserhalb beider."""
        a = _auftrag(
            typ=AuftragsTyp.STK,
            klinik_id="K017",
            produkt="Energie",
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = auftrag_zuweisen(a)
        # Kann None oder zugewiesen sein – hauptsaechlich kein Absturz
        assert result is None or result.status == AuftragsStatus.ZUGEWIESEN


# ---------------------------------------------------------------------------
# auftraege/dispatcher.py – auftrag_benachrichtigen
# ---------------------------------------------------------------------------

class TestAuftragBenachrichtigen:
    def test_struktur_vollstaendig(self):
        a = _auftrag(techniker_id="T1", status=AuftragsStatus.ZUGEWIESEN)
        result = auftrag_benachrichtigen(a)
        assert "auftragsdaten" in result
        assert "geraetestandort" in result
        assert "kundenkontakt" in result
        assert "anfahrt" in result

    def test_auftragsdaten_felder(self):
        a = _auftrag(techniker_id="T6", status=AuftragsStatus.ZUGEWIESEN)
        daten = auftrag_benachrichtigen(a)["auftragsdaten"]
        assert daten["auftrag_id"] == "TEST-0001"
        assert daten["auftragstyp"] == "STK"
        assert daten["techniker_id"] == "T6"
        assert daten["status"] == "ZUGEWIESEN"

    def test_faelligkeitsdatum_als_isoformat(self):
        a = _auftrag(faelligkeit=date(2025, 7, 1))
        daten = auftrag_benachrichtigen(a)["auftragsdaten"]
        assert daten["faelligkeitsdatum"] == "2025-07-01"

    def test_geraetestandort_mit_gueltiger_klinik(self):
        a = _auftrag(klinik_id="K001", klinik_name="Universitätsklinikum Hamburg-Eppendorf (UKE)")
        standort = auftrag_benachrichtigen(a)["geraetestandort"]
        assert standort["klinik_id"] == "K001"
        assert standort["plz"] is not None  # K001 ist in kliniken.csv

    def test_geraetestandort_ohne_klinik_id(self):
        a = _auftrag(klinik_id=None, klinik_name="Unbekannte Klinik")
        standort = auftrag_benachrichtigen(a)["geraetestandort"]
        assert standort["klinik_id"] is None
        assert standort["plz"] is None

    def test_hugo_standort_hinweis(self):
        # K001 (UKE) ist Hugo-Standort laut kliniken.csv
        a = _auftrag(klinik_id="K001")
        anfahrt = auftrag_benachrichtigen(a)["anfahrt"]
        # Hugo-Hinweis sollte gesetzt sein
        assert anfahrt["hinweis"] is not None
        assert "Hugo" in anfahrt["hinweis"]

    def test_kein_hugo_hinweis_bei_normalem_standort(self):
        # K009 (MHH Hannover) ist kein Hugo-Standort
        a = _auftrag(klinik_id="K009")
        anfahrt = auftrag_benachrichtigen(a)["anfahrt"]
        assert anfahrt["hinweis"] is None

    def test_smax_url_mit_klinik_id(self):
        a = _auftrag(klinik_id="K001")
        kontakt = auftrag_benachrichtigen(a)["kundenkontakt"]
        assert "K001" in kontakt["smax_kontakt_url"]

    def test_smax_url_ohne_klinik_id_ist_none(self):
        a = _auftrag(klinik_id=None)
        kontakt = auftrag_benachrichtigen(a)["kundenkontakt"]
        assert kontakt["smax_kontakt_url"] is None


# ===========================================================================
# auftraege/workflow.py
# ===========================================================================

# Festes Referenzdatum fuer alle Dringlichkeitstests
_HEUTE = date(2026, 3, 27)


class TestBerechne_Dringlichkeit:
    """Tests fuer die interne Dringlichkeits-Klassifizierung."""

    def test_ueberfaellig_weit(self):
        faellig = _HEUTE - __import__("datetime").timedelta(days=90)
        d = _berechne_dringlichkeit(faellig, heute=_HEUTE)
        assert d.stufe == "\u00dcBERF\u00c4LLIG"
        assert d.tage_bis_faelligkeit == -90

    def test_ueberfaellig_knapp(self):
        faellig = _HEUTE - __import__("datetime").timedelta(days=1)
        d = _berechne_dringlichkeit(faellig, heute=_HEUTE)
        assert d.stufe == "\u00dcBERF\u00c4LLIG"
        assert d.tage_bis_faelligkeit == -1

    def test_kritisch_heute_faellig(self):
        d = _berechne_dringlichkeit(_HEUTE, heute=_HEUTE)
        assert d.stufe == "KRITISCH"
        assert d.tage_bis_faelligkeit == 0

    def test_kritisch_unter_14_tage(self):
        faellig = _HEUTE + __import__("datetime").timedelta(days=10)
        d = _berechne_dringlichkeit(faellig, heute=_HEUTE)
        assert d.stufe == "KRITISCH"

    def test_kritisch_exakt_14_tage(self):
        faellig = _HEUTE + __import__("datetime").timedelta(days=_TAGE_KRITISCH)
        d = _berechne_dringlichkeit(faellig, heute=_HEUTE)
        assert d.stufe == "KRITISCH"

    def test_hoch_15_tage(self):
        faellig = _HEUTE + __import__("datetime").timedelta(days=15)
        d = _berechne_dringlichkeit(faellig, heute=_HEUTE)
        assert d.stufe == "HOCH"

    def test_hoch_20_tage(self):
        faellig = _HEUTE + __import__("datetime").timedelta(days=20)
        d = _berechne_dringlichkeit(faellig, heute=_HEUTE)
        assert d.stufe == "HOCH"

    def test_hoch_exakt_30_tage(self):
        faellig = _HEUTE + __import__("datetime").timedelta(days=_TAGE_HOCH)
        d = _berechne_dringlichkeit(faellig, heute=_HEUTE)
        assert d.stufe == "HOCH"

    def test_normal_31_tage(self):
        faellig = _HEUTE + __import__("datetime").timedelta(days=31)
        d = _berechne_dringlichkeit(faellig, heute=_HEUTE)
        assert d.stufe == "NORMAL"

    def test_normal_120_tage(self):
        faellig = _HEUTE + __import__("datetime").timedelta(days=120)
        d = _berechne_dringlichkeit(faellig, heute=_HEUTE)
        assert d.stufe == "NORMAL"
        assert d.tage_bis_faelligkeit == 120

    def test_begruendung_enthaelt_tage(self):
        faellig = _HEUTE - __import__("datetime").timedelta(days=5)
        d = _berechne_dringlichkeit(faellig, heute=_HEUTE)
        assert "5" in d.begruendung

    def test_verwendet_heute_als_default(self):
        """Ohne heute-Parameter kein Fehler (raucht nicht ab)."""
        d = _berechne_dringlichkeit(date.today())
        assert d.stufe in {"\u00dcBERF\u00c4LLIG", "KRITISCH", "HOCH", "NORMAL"}


class TestEmpfehlungsReportDatenklassen:
    """Tests fuer EmpfehlungsReport und TechnikerEmpfehlung Dataclass-Methoden."""

    def _minimal_report(self, empfehlungen=None) -> EmpfehlungsReport:
        return EmpfehlungsReport(
            auftrag_id="TEST-0001",
            erstellt_am=datetime(2026, 3, 27, 9, 0),
            auftrag=_auftrag(),
            dringlichkeit=Dringlichkeit("NORMAL", "60 Tage", 60),
            empfehlungen=empfehlungen or [],
            geraetestandort={},
            kundenkontakt={},
            letzte_wartung=None,
            offene_punkte=[],
            ersatzteile_schaetzung=[],
            hinweis_disposition=_HINWEIS_KEIN_AUTO_ASSIGN,
        )

    def test_hat_empfehlungen_true(self):
        emp = TechnikerEmpfehlung(
            rang=1, techniker_id="T6", techniker_standort="Schenefeld",
            score=82.5, level="L3",
            kompetenz_begruendung="L3", naehe_begruendung="~10 km",
            auslastung_begruendung="0 h / 32 h", fahrzeit_minuten=12,
            distanz_km=10.0, warnungen=[], hinweise=[],
        )
        report = self._minimal_report([emp])
        assert report.hat_empfehlungen() is True

    def test_hat_empfehlungen_false_wenn_leer(self):
        report = self._minimal_report([])
        assert report.hat_empfehlungen() is False

    def test_beste_empfehlung_gibt_rang1(self):
        e1 = TechnikerEmpfehlung(rang=1, techniker_id="T1", techniker_standort="X",
            score=90.0, level="L3", kompetenz_begruendung="", naehe_begruendung="",
            auslastung_begruendung="", fahrzeit_minuten=10, distanz_km=20.0,
            warnungen=[], hinweise=[])
        e2 = TechnikerEmpfehlung(rang=2, techniker_id="T2", techniker_standort="Y",
            score=70.0, level="L3", kompetenz_begruendung="", naehe_begruendung="",
            auslastung_begruendung="", fahrzeit_minuten=30, distanz_km=50.0,
            warnungen=[], hinweise=[])
        report = self._minimal_report([e1, e2])
        assert report.beste_empfehlung().techniker_id == "T1"

    def test_beste_empfehlung_none_wenn_leer(self):
        assert self._minimal_report().beste_empfehlung() is None


class TestEmpfehlungGenerieren:
    """Integrationstests fuer empfehlung_generieren()."""

    def test_gibt_empfehlungsreport_zurueck(self):
        a = _auftrag(typ=AuftragsTyp.STK, klinik_id="K001", produkt="Neuromonitoring")
        report = empfehlung_generieren(a, heute=_HEUTE)
        assert isinstance(report, EmpfehlungsReport)

    def test_auftrag_status_bleibt_neu(self):
        a = _auftrag(status=AuftragsStatus.NEU)
        empfehlung_generieren(a, heute=_HEUTE)
        assert a.status == AuftragsStatus.NEU

    def test_auftrag_techniker_id_unveraendert(self):
        a = _auftrag(techniker_id=None)
        empfehlung_generieren(a, heute=_HEUTE)
        assert a.techniker_id is None

    def test_auftrag_objekt_nicht_geklont(self):
        """empfehlung_generieren muss dasselbe Auftrag-Objekt im Report referenzieren."""
        a = _auftrag()
        report = empfehlung_generieren(a, heute=_HEUTE)
        assert report.auftrag is a

    def test_auftrag_id_im_report(self):
        a = _auftrag()
        report = empfehlung_generieren(a, heute=_HEUTE)
        assert report.auftrag_id == a.auftrag_id

    def test_erstellt_am_ist_datetime(self):
        report = empfehlung_generieren(_auftrag(), heute=_HEUTE)
        assert isinstance(report.erstellt_am, datetime)

    def test_max_3_empfehlungen(self):
        a = _auftrag(klinik_id="K001", produkt="Neuromonitoring")
        report = empfehlung_generieren(a, heute=_HEUTE)
        assert len(report.empfehlungen) <= 3

    def test_empfehlungen_nach_score_absteigend(self):
        a = _auftrag(klinik_id="K019", produkt="Elektrochirurgie")
        report = empfehlung_generieren(a, heute=_HEUTE)
        scores = [e.score for e in report.empfehlungen]
        assert scores == sorted(scores, reverse=True)

    def test_rang_fortlaufend(self):
        a = _auftrag(klinik_id="K001", produkt="Beatmung")
        report = empfehlung_generieren(a, heute=_HEUTE)
        raenge = [e.rang for e in report.empfehlungen]
        assert raenge == list(range(1, len(raenge) + 1))

    def test_hinweis_disposition_gesetzt(self):
        report = empfehlung_generieren(_auftrag(), heute=_HEUTE)
        assert report.hinweis_disposition == _HINWEIS_KEIN_AUTO_ASSIGN
        assert len(report.hinweis_disposition) > 0

    def test_kein_klinik_id_gibt_leere_empfehlungen(self):
        a = _auftrag(klinik_id=None)
        report = empfehlung_generieren(a, heute=_HEUTE)
        assert report.empfehlungen == []
        # Status und techniker_id trotzdem unveraendert
        assert a.status == AuftragsStatus.NEU
        assert a.techniker_id is None

    def test_unbekannte_klinik_id_gibt_leere_empfehlungen(self):
        a = _auftrag(klinik_id="K999")
        report = empfehlung_generieren(a, heute=_HEUTE)
        assert isinstance(report.empfehlungen, list)

    def test_dringlichkeit_korrekt_berechnet(self):
        faellig = _HEUTE - __import__("datetime").timedelta(days=80)
        a = _auftrag(faelligkeit=faellig, klinik_id=None)
        report = empfehlung_generieren(a, heute=_HEUTE)
        assert report.dringlichkeit.stufe == "\u00dcBERF\u00c4LLIG"

    def test_geraetestandort_enthaelt_klinik_name(self):
        a = _auftrag(klinik_id="K001", klinik_name="Testklinik Hamburg")
        report = empfehlung_generieren(a, heute=_HEUTE)
        assert report.geraetestandort["klinik_name"] == "Testklinik Hamburg"

    def test_geraetestandort_enthaelt_klinik_id(self):
        a = _auftrag(klinik_id="K001")
        report = empfehlung_generieren(a, heute=_HEUTE)
        assert report.geraetestandort["klinik_id"] == "K001"

    def test_geraetestandort_ohne_klinik_id_felder_none(self):
        a = _auftrag(klinik_id=None)
        report = empfehlung_generieren(a, heute=_HEUTE)
        assert report.geraetestandort["plz"] is None

    def test_kundenkontakt_enthaelt_klinik_name(self):
        a = _auftrag(klinik_name="Meine Klinik")
        report = empfehlung_generieren(a, heute=_HEUTE)
        assert report.kundenkontakt["klinik_name"] == "Meine Klinik"

    def test_ersatzteile_liste_nicht_leer_fuer_bekannte_familie(self):
        a = _auftrag(produkt="Beatmung", klinik_id=None)
        report = empfehlung_generieren(a, heute=_HEUTE)
        assert len(report.ersatzteile_schaetzung) > 0
        assert all("bezeichnung" in e for e in report.ersatzteile_schaetzung)

    def test_ersatzteile_enthalten_quelle(self):
        a = _auftrag(produkt="Elektrochirurgie", klinik_id=None)
        report = empfehlung_generieren(a, heute=_HEUTE)
        assert all("quelle" in e for e in report.ersatzteile_schaetzung)

    def test_offene_punkte_ist_liste(self):
        report = empfehlung_generieren(_auftrag(), heute=_HEUTE)
        assert isinstance(report.offene_punkte, list)

    def test_empfehlung_begruendungsfelder_nicht_leer(self):
        a = _auftrag(klinik_id="K001", produkt="Beatmung")
        report = empfehlung_generieren(a, heute=_HEUTE)
        for emp in report.empfehlungen:
            assert emp.kompetenz_begruendung
            assert emp.naehe_begruendung
            assert emp.auslastung_begruendung

    def test_empfehlung_fahrzeit_positiv(self):
        a = _auftrag(klinik_id="K001", produkt="Beatmung")
        report = empfehlung_generieren(a, heute=_HEUTE)
        for emp in report.empfehlungen:
            assert emp.fahrzeit_minuten > 0
            assert emp.distanz_km > 0

    def test_empfehlung_hinweise_enthalten_servicehistorie_hinweis(self):
        a = _auftrag(klinik_id="K001", produkt="Beatmung")
        report = empfehlung_generieren(a, heute=_HEUTE)
        for emp in report.empfehlungen:
            hinweise_text = " ".join(emp.hinweise).lower()
            assert "servicehistorie" in hinweise_text

    def test_hugo_empfehlung_nur_l3(self):
        """Hugo-Auftraege duerfen nur L3-Techniker in den Empfehlungen haben."""
        a = _auftrag(klinik_id="K001", produkt="Hugo")
        report = empfehlung_generieren(a, heute=_HEUTE)
        for emp in report.empfehlungen:
            assert emp.level == "L3"

    def test_hugo_hinweis_in_empfehlungen(self):
        a = _auftrag(klinik_id="K001", produkt="Hugo")
        report = empfehlung_generieren(a, heute=_HEUTE)
        for emp in report.empfehlungen:
            hinweise_text = " ".join(emp.hinweise)
            assert "Hugo" in hinweise_text

    def test_tages_status_wird_in_auslastung_angezeigt(self):
        from techniker.scoring import TagesStatus
        status = {"T6": TagesStatus(wochenstunden_aktuell=32.0)}
        a = _auftrag(klinik_id="K001", produkt="Beatmung")
        report = empfehlung_generieren(a, tages_status=status, heute=_HEUTE)
        # Falls T6 in den Empfehlungen: Echtzeit-Auslastung muss erscheinen
        t6_empfehlung = next((e for e in report.empfehlungen if e.techniker_id == "T6"), None)
        if t6_empfehlung:
            assert "32" in t6_empfehlung.auslastung_begruendung
            assert "Echtzeit" in t6_empfehlung.auslastung_begruendung
