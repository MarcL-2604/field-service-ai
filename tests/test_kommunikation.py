"""
tests/test_kommunikation.py
============================
Tests fuer das Kommunikations-Grundgeruest (api/kommunikation.py).

Zentrale Sicherheitsgarantien, die hier abgesichert werden:
  - KOMMUNIKATION_AUTOMATISCH_AKTIV=False -> nie echter Versand, nur Log.
  - Platzhalter-Adressen loesen NIE einen Versandversuch aus, auch nicht bei
    aktiviertem Schalter.
  - Fehlt data/techniker_kontakte.json komplett -> kein Absturz, sauberer
    Fallback (Demo-Modus).
  - SMTP-Fehler fuehren zu einem Log-Fallback statt einem Absturz.
"""

import json

import pytest

import api.kommunikation as komm


@pytest.fixture(autouse=True)
def isolierte_dateien(tmp_path, monkeypatch):
    """Jeder Test bekommt eigene Kontakt-/Log-Dateien -- nie das echte
    (gitignored) data/-Verzeichnis anfassen."""
    monkeypatch.setattr(komm, "_LOG_DATEI", tmp_path / "kommunikation_log.jsonl")
    return tmp_path


def _schreibe_kontakte(tmp_path, inhalt: dict) -> None:
    pfad = tmp_path / "techniker_kontakte.json"
    pfad.write_text(json.dumps(inhalt), encoding="utf-8")


AUFTRAG = {"auftrag_id": "STK-2026-00099", "klinik_name": "Klinikum Test"}


class TestLadeTechnikerKontakte:
    def test_datei_fehlt_komplett_kein_absturz(self, tmp_path):
        result = komm.lade_techniker_kontakte(tmp_path / "existiert_nicht.json")
        assert result == {}

    def test_kaputtes_json_kein_absturz(self, tmp_path):
        pfad = tmp_path / "kaputt.json"
        pfad.write_text("{invalid json", encoding="utf-8")
        assert komm.lade_techniker_kontakte(pfad) == {}

    def test_meta_schluessel_wird_gefiltert(self, tmp_path):
        _schreibe_kontakte(tmp_path, {"_hinweis": "intern", "Marc Liebhardt": "marc@example.com"})
        result = komm.lade_techniker_kontakte(tmp_path / "techniker_kontakte.json")
        assert "_hinweis" not in result
        assert result["Marc Liebhardt"] == "marc@example.com"

    def test_echte_datei_hat_marc_mit_echter_adresse_rest_platzhalter(self):
        """Regressionsschutz fuer die tatsaechliche (gitignored) Kontaktdatei,
        falls sie lokal vorhanden ist -- sonst wird der Test uebersprungen."""
        if not komm._KONTAKTE_DATEI.exists():
            pytest.skip("data/techniker_kontakte.json nicht vorhanden (gitignored)")
        kontakte = komm.lade_techniker_kontakte()
        assert len(kontakte) == 24
        assert kontakte["Marc Liebhardt"] == "marc.liebhardt@medtronic.com"
        assert not komm._ist_platzhalter_adresse(kontakte["Marc Liebhardt"])
        andere = {k: v for k, v in kontakte.items() if k != "Marc Liebhardt"}
        assert len(andere) == 23
        assert all(komm._ist_platzhalter_adresse(v) for v in andere.values())


class TestIstPlatzhalterAdresse:
    def test_none_ist_platzhalter(self):
        assert komm._ist_platzhalter_adresse(None) is True

    def test_platzhalter_marker_erkannt(self):
        assert komm._ist_platzhalter_adresse("PLATZHALTER@medtronic.com") is True

    def test_platzhalter_case_insensitiv(self):
        assert komm._ist_platzhalter_adresse("platzhalter@medtronic.com") is True

    def test_echte_adresse_kein_platzhalter(self):
        assert komm._ist_platzhalter_adresse("marc.liebhardt@medtronic.com") is False


class TestSendeAuftragsBenachrichtigungSchalterAus:
    """KOMMUNIKATION_AUTOMATISCH_AKTIV=False -- fuer ALLE Testfaelle, inkl. Marc."""

    def test_marc_mit_echter_adresse_trotzdem_nur_log(self, tmp_path, monkeypatch):
        _schreibe_kontakte(tmp_path, {"Marc Liebhardt": "marc.liebhardt@medtronic.com"})
        monkeypatch.setattr(komm, "_KONTAKTE_DATEI", tmp_path / "techniker_kontakte.json")
        monkeypatch.setattr(komm, "KOMMUNIKATION_AUTOMATISCH_AKTIV", False)

        result = komm.sende_auftrags_benachrichtigung("Marc Liebhardt", AUFTRAG, testkontext=True)

        assert result["versendet"] is False
        assert result["modus"] == "log"
        assert result["empfaenger"] == "marc.liebhardt@medtronic.com"

    def test_platzhalter_techniker_nur_log(self, tmp_path, monkeypatch):
        _schreibe_kontakte(tmp_path, {"Ahmed Awadallah": "PLATZHALTER@medtronic.com"})
        monkeypatch.setattr(komm, "_KONTAKTE_DATEI", tmp_path / "techniker_kontakte.json")
        monkeypatch.setattr(komm, "KOMMUNIKATION_AUTOMATISCH_AKTIV", False)

        result = komm.sende_auftrags_benachrichtigung("Ahmed Awadallah", AUFTRAG)

        assert result["versendet"] is False
        assert result["modus"] == "log"

    def test_schreibt_log_eintrag(self, isolierte_dateien, tmp_path, monkeypatch):
        _schreibe_kontakte(tmp_path, {"Marc Liebhardt": "marc.liebhardt@medtronic.com"})
        monkeypatch.setattr(komm, "_KONTAKTE_DATEI", tmp_path / "techniker_kontakte.json")
        monkeypatch.setattr(komm, "KOMMUNIKATION_AUTOMATISCH_AKTIV", False)

        komm.sende_auftrags_benachrichtigung("Marc Liebhardt", AUFTRAG)

        zeilen = komm._LOG_DATEI.read_text(encoding="utf-8").strip().splitlines()
        assert len(zeilen) == 1
        eintrag = json.loads(zeilen[0])
        assert eintrag["techniker"] == "Marc Liebhardt"
        assert eintrag["modus"] == "log"

    def test_kein_absturz_ohne_kontaktdatei(self, tmp_path, monkeypatch):
        monkeypatch.setattr(komm, "_KONTAKTE_DATEI", tmp_path / "existiert_nicht.json")
        monkeypatch.setattr(komm, "KOMMUNIKATION_AUTOMATISCH_AKTIV", False)

        result = komm.sende_auftrags_benachrichtigung("Irgendein Techniker", AUFTRAG)

        assert result["versendet"] is False
        assert result["empfaenger"] is None


class TestSendeAuftragsBenachrichtigungSchalterAn:
    """KOMMUNIKATION_AUTOMATISCH_AKTIV=True -- Platzhalter bleiben trotzdem gesperrt."""

    def test_platzhalter_niemals_versandversuch_trotz_aktivem_schalter(self, tmp_path, monkeypatch):
        _schreibe_kontakte(tmp_path, {"Ahmed Awadallah": "PLATZHALTER@medtronic.com"})
        monkeypatch.setattr(komm, "_KONTAKTE_DATEI", tmp_path / "techniker_kontakte.json")
        monkeypatch.setattr(komm, "KOMMUNIKATION_AUTOMATISCH_AKTIV", True)

        def _sollte_nie_aufgerufen_werden(*args, **kwargs):
            raise AssertionError("SMTP-Versand haette fuer eine Platzhalter-Adresse nie versucht werden duerfen")

        monkeypatch.setattr(komm, "_sende_echte_mail", _sollte_nie_aufgerufen_werden)

        result = komm.sende_auftrags_benachrichtigung("Ahmed Awadallah", AUFTRAG, testkontext=True)

        assert result["versendet"] is False
        assert result["modus"] == "log"

    def test_marc_ohne_testkontext_bleibt_log_only(self, tmp_path, monkeypatch):
        _schreibe_kontakte(tmp_path, {"Marc Liebhardt": "marc.liebhardt@medtronic.com"})
        monkeypatch.setattr(komm, "_KONTAKTE_DATEI", tmp_path / "techniker_kontakte.json")
        monkeypatch.setattr(komm, "KOMMUNIKATION_AUTOMATISCH_AKTIV", True)

        def _sollte_nie_aufgerufen_werden(*args, **kwargs):
            raise AssertionError("Ohne expliziten Testkontext darf kein SMTP-Versand ausgeloest werden")

        monkeypatch.setattr(komm, "_sende_echte_mail", _sollte_nie_aufgerufen_werden)

        result = komm.sende_auftrags_benachrichtigung("Marc Liebhardt", AUFTRAG, testkontext=False)

        assert result["versendet"] is False
        assert result["modus"] == "log"

    def test_marc_testkontext_erfolgreicher_smtp_versand(self, tmp_path, monkeypatch):
        _schreibe_kontakte(tmp_path, {"Marc Liebhardt": "marc.liebhardt@medtronic.com"})
        monkeypatch.setattr(komm, "_KONTAKTE_DATEI", tmp_path / "techniker_kontakte.json")
        monkeypatch.setattr(komm, "KOMMUNIKATION_AUTOMATISCH_AKTIV", True)

        aufrufe = []
        monkeypatch.setattr(
            komm, "_sende_echte_mail",
            lambda empfaenger, betreff, text: aufrufe.append((empfaenger, betreff, text)),
        )

        result = komm.sende_auftrags_benachrichtigung("Marc Liebhardt", AUFTRAG, testkontext=True)

        assert result == {"versendet": True, "modus": "smtp", "empfaenger": "marc.liebhardt@medtronic.com"}
        assert len(aufrufe) == 1
        assert aufrufe[0][0] == "marc.liebhardt@medtronic.com"

    def test_marc_testkontext_smtp_fehler_faellt_auf_log_zurueck(self, tmp_path, monkeypatch):
        _schreibe_kontakte(tmp_path, {"Marc Liebhardt": "marc.liebhardt@medtronic.com"})
        monkeypatch.setattr(komm, "_KONTAKTE_DATEI", tmp_path / "techniker_kontakte.json")
        monkeypatch.setattr(komm, "KOMMUNIKATION_AUTOMATISCH_AKTIV", True)

        def _wirft_fehler(*args, **kwargs):
            raise RuntimeError("SMTP nicht konfiguriert")

        monkeypatch.setattr(komm, "_sende_echte_mail", _wirft_fehler)

        result = komm.sende_auftrags_benachrichtigung("Marc Liebhardt", AUFTRAG, testkontext=True)

        assert result["versendet"] is False
        assert result["modus"] == "log_fallback"


class TestSendeEchteMailOhneSmtpKonfiguration:
    def test_fehlende_env_vars_werfen_runtime_error(self, monkeypatch):
        monkeypatch.delenv("FSA_SMTP_HOST", raising=False)
        monkeypatch.delenv("FSA_SMTP_PORT", raising=False)
        monkeypatch.delenv("FSA_SMTP_ABSENDER", raising=False)

        with pytest.raises(RuntimeError):
            komm._sende_echte_mail("test@example.com", "Betreff", "Text")


class TestAuftragKurzbeschreibung:
    def test_funktioniert_mit_dict(self):
        out = komm._auftrag_kurzbeschreibung({"auftrag_id": "STK-1", "klinik_name": "Klinikum X"})
        assert out == "STK-1 · Klinikum X"

    def test_funktioniert_mit_objekt(self):
        class _Auftrag:
            auftrag_id = "STK-2"
            klinik_name = "Klinikum Y"

        assert komm._auftrag_kurzbeschreibung(_Auftrag()) == "STK-2 · Klinikum Y"

    def test_fehlende_felder_kein_absturz(self):
        assert komm._auftrag_kurzbeschreibung({}) == "? · ?"


class TestPushGrundgeruest:
    """Push-Grundgeruest: Dateien vorhanden, aber keine aktive
    Server-Verbindung im Code (rein strukturell/deaktiviert)."""

    def _root(self):
        from pathlib import Path
        return Path(__file__).resolve().parent.parent

    def test_service_worker_datei_vorhanden(self):
        pfad = self._root() / "push" / "service-worker.js"
        assert pfad.exists()
        inhalt = pfad.read_text(encoding="utf-8")
        assert "STATUS: Grundgeruest, nicht aktiv" in inhalt

    def test_manifest_datei_vorhanden(self):
        pfad = self._root() / "push" / "manifest.json"
        assert pfad.exists()
        daten = json.loads(pfad.read_text(encoding="utf-8"))
        assert "Grundgeruest" in daten["_status"]

    def test_kein_aktiver_serviceworker_register_aufruf_im_projekt(self):
        """Grundgeruest darf im Pilotbetrieb nicht verdrahtet sein -- kein
        navigator.serviceWorker.register() in den HTML-Seiten."""
        root = self._root()
        for name in ("dashboard.html", "index.html", "manual.html", "workflow_demo.html", "demo.html"):
            pfad = root / name
            if pfad.exists():
                assert "serviceWorker.register" not in pfad.read_text(encoding="utf-8"), name
