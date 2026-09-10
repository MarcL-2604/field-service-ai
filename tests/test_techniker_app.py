"""
tests/test_techniker_app.py
=============================
Tests fuer die installierbare Techniker-Demo-App (techniker_app.html) und das
jetzt aktiv genutzte push/-Grundgeruest.

Da techniker_app.html eine statische HTML-Datei ist (kein Python-Template),
pruefen diese Tests per Text-/Regex-Analyse -- analog zu test_manual_html.py:
Struktur, i18n-Vollstaendigkeit, PWA-Verdrahtung (Manifest/Service-Worker) und
die bewussten Sicherheitsgrenzen (keine Verbindung zur echten
Kommunikations-Infrastruktur, keine echten Daten).
"""

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_APP = _ROOT / "techniker_app.html"


@pytest.fixture(scope="module")
def app_html() -> str:
    return _APP.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def app_head(app_html: str) -> str:
    """Markup vor dem <script>-Block (fuer data-i18n-Struktur-Checks)."""
    return app_html[:app_html.index("<script>")]


@pytest.fixture(scope="module")
def app_script(app_html: str) -> str:
    return app_html[app_html.index("<script>"):app_html.index("</script>")]


class TestAppExistiertUndLaedt:
    def test_datei_existiert(self):
        assert _APP.exists()

    def test_hat_doctype_und_titel(self, app_html):
        assert app_html.startswith("<!DOCTYPE html>")
        assert "<title>Techniker-App — Field Service AI</title>" in app_html

    def test_passwortschutz_konsistent_mit_anderen_seiten(self, app_html):
        assert "037453db72fb8a93ebe48d4ff52b1b493cdf56ef6a28240a65c6055b76d8f360" in app_html
        assert "fsa_auth" in app_html
        assert 'id="pw-overlay"' in app_html


class TestPwaVerdrahtung:
    def test_manifest_verlinkt(self, app_html):
        assert '<link rel="manifest" href="push/manifest.json">' in app_html

    def test_icon_verlinkt(self, app_html):
        assert 'href="push/icon.svg"' in app_html

    def test_theme_color_gesetzt(self, app_html):
        assert '<meta name="theme-color" content="#0072CE">' in app_html

    def test_service_worker_wird_auf_dieser_seite_registriert(self, app_html):
        """Im Gegensatz zu allen anderen Seiten (siehe
        test_kommunikation.py::TestPushGrundgeruest) registriert GENAU diese
        eine Seite den Service Worker aktiv."""
        assert "navigator.serviceWorker.register('push/service-worker.js')" in app_html

    def test_andere_seiten_registrieren_weiterhin_keinen_service_worker(self):
        for name in ("dashboard.html", "index.html", "manual.html", "workflow_demo.html", "demo.html"):
            pfad = _ROOT / name
            if pfad.exists():
                assert "serviceWorker.register" not in pfad.read_text(encoding="utf-8"), name

    def test_beforeinstallprompt_wird_behandelt(self, app_html):
        assert "beforeinstallprompt" in app_html

    def test_manifest_json_ist_valide_und_zeigt_auf_die_app(self):
        daten = json.loads((_ROOT / "push" / "manifest.json").read_text(encoding="utf-8"))
        assert daten["start_url"].endswith("techniker_app.html")
        assert len(daten["icons"]) >= 1
        assert all(icon["src"] for icon in daten["icons"])
        assert daten["name"] == "Field Service AI — Techniker"

    def test_icon_svg_ist_valide_xml_und_medtronic_blau(self):
        import xml.dom.minidom as md
        pfad = _ROOT / "push" / "icon.svg"
        md.parse(str(pfad))  # wirft bei ungueltigem XML
        assert "#0072CE" in pfad.read_text(encoding="utf-8")

    def test_service_worker_hat_offline_precaching(self):
        inhalt = (_ROOT / "push" / "service-worker.js").read_text(encoding="utf-8")
        assert "caches.open" in inhalt
        assert "addEventListener('fetch'" in inhalt
        assert "techniker_app.html" in inhalt


class TestFunktionaleBausteine:
    def test_notification_trigger_vorhanden(self, app_html):
        assert "simuliereNeuenAuftrag" in app_html
        assert "showNotification" in app_html or "new Notification" in app_html

    def test_status_store_wiederverwendet_interface_aus_workflow_demo(self, app_html):
        assert "const StatusStore" in app_html
        assert "setBestaetigt" in app_html
        assert "fsa_wf_status_" in app_html

    def test_vier_faktoren_pruefung_vorhanden(self, app_html):
        assert "pruefeAbschluss" in app_html
        for faktor in ("vollstaendigkeit", "dauer", "auffaelligkeiten", "dokumente"):
            assert f"'{faktor}'" in app_html or f'"{faktor}"' in app_html

    def test_demo_auftraege_klar_als_beispiel_gekennzeichnet(self, app_html):
        assert "DEMO_AUFTRAEGE" in app_html
        assert "badge-muster" in app_html

    def test_bottom_navigation_mit_zwei_tabs(self, app_html):
        assert app_html.count('class="bottom-nav-item') >= 2
        assert 'data-tab="auftraege"' in app_html
        assert 'data-tab="info"' in app_html

    def test_permission_erklaerung_vor_anfrage(self, app_html):
        """Erklaerender Text muss vor dem Berechtigungs-Button stehen (nicht
        nur der nackte Browser-Dialog)."""
        idx_text = app_html.index("perm.text")
        idx_btn = app_html.index("benachrichtigungenAnfordern()")
        assert idx_text < idx_btn


class TestSicherheitsgrenzen:
    """Die Demo-App muss vollstaendig isoliert von der echten (deaktivierten)
    Kommunikationsinfrastruktur bleiben."""

    def test_keine_code_verbindung_zu_kommunikation_py(self, app_html):
        """Ein erklaerender Hinweistext, dass die App NICHT an
        api/kommunikation.py angebunden ist, ist erlaubt (Transparenz) --
        eine tatsaechliche Code-Verbindung (Script-Include) ist es nicht."""
        assert '<script src="api' not in app_html
        assert 'src="api/kommunikation.py"' not in app_html

    def test_kein_bezug_zu_echter_kontaktdatei(self, app_html):
        assert "techniker_kontakte.json" not in app_html

    def test_kein_fetch_oder_xhr_zu_einem_server(self, app_html):
        script_only = app_html[app_html.index("<script>"):]
        assert "fetch(" not in script_only
        assert "XMLHttpRequest" not in script_only

    def test_demo_hinweis_klar_sichtbar(self, app_html):
        assert "Demo-Modus" in app_html or "app.demoHint" in app_html
        assert "keine echten Daten" in app_html or "lokal simuliert" in app_html


class TestI18nVollstaendigkeit:
    def _html_keys(self, app_head: str) -> set[str]:
        return set(re.findall(r'data-i18n="([^"]+)"', app_head))

    def _en_keys(self, app_script: str) -> set[str]:
        block = app_script[app_script.index("const _EN = {"):app_script.index("function anwendenSprache")]
        return set(re.findall(r"'([a-zA-Z0-9_.]+)':", block))

    def test_jeder_data_i18n_key_hat_en_uebersetzung(self, app_head, app_script):
        fehlend = self._html_keys(app_head) - self._en_keys(app_script)
        assert not fehlend, f"data-i18n-Keys ohne EN-Uebersetzung: {sorted(fehlend)}"

    def test_kein_verwaister_en_eintrag(self, app_head, app_script):
        verwaist = self._en_keys(app_script) - self._html_keys(app_head)
        assert not verwaist, f"EN-Eintraege ohne HTML-Element: {sorted(verwaist)}"

    def test_mindestens_20_uebersetzte_elemente(self, app_head):
        assert len(self._html_keys(app_head)) >= 20

    def test_data_i18n_ohne_html_hat_keine_html_entities_im_en_wert(self, app_script):
        """Regressionsschutz (bekanntes Muster aus manual.html): data-i18n
        setzt .textContent, das HTML-Entities NICHT dekodiert -- ein
        EN-Wert mit '&amp;' wuerde woertlich erscheinen statt als '&'."""
        block = app_script[app_script.index("const _EN = {"):app_script.index("function anwendenSprache")]
        for key, wert in re.findall(r"'([a-zA-Z0-9_.]+)':\s*'([^']*)'", block):
            assert "&amp;" not in wert, f"{key}: EN-Wert enthaelt rohes '&amp;' statt '&' ({wert!r})"

    def test_data_i18n_ohne_html_hat_kein_html_tag_im_de_quelltext(self, app_head):
        """Spiegelbildlicher Regressionsschutz: data-i18n-Elemente duerfen im
        DE-Quelltext kein verschachteltes HTML-Tag enthalten, sonst geht es
        beim Sprachwechsel verloren (.textContent liefert nur reinen Text)."""

        class _Checker(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack = []
                self.violations = []

            def handle_starttag(self, tag, attrs):
                if self.stack:
                    self.stack[-1]["has_child_tag"] = True
                self.stack.append({
                    "tag": tag, "key": dict(attrs).get("data-i18n"), "has_child_tag": False,
                })

            def handle_startendtag(self, tag, attrs):
                if self.stack:
                    self.stack[-1]["has_child_tag"] = True

            def handle_endtag(self, tag):
                for i in range(len(self.stack) - 1, -1, -1):
                    if self.stack[i]["tag"] == tag:
                        entry = self.stack.pop()
                        if entry["key"] and entry["has_child_tag"]:
                            self.violations.append(entry["key"])
                        del self.stack[i:]
                        break

        parser = _Checker()
        parser.feed(app_head)
        assert not parser.violations, (
            f"data-i18n-Elemente mit verschachteltem HTML-Tag: {parser.violations}"
        )


class TestVerlinkung:
    def test_workflow_demo_verlinkt_auf_die_app(self):
        inhalt = (_ROOT / "workflow_demo.html").read_text(encoding="utf-8")
        assert 'href="techniker_app.html"' in inhalt

    def test_manual_verlinkt_auf_die_app(self):
        inhalt = (_ROOT / "manual.html").read_text(encoding="utf-8")
        assert 'href="techniker_app.html"' in inhalt

    def test_app_verlinkt_zurueck_zu_manual_und_workflow_demo(self, app_html):
        assert "manual.html" in app_html
        assert "workflow_demo.html" in app_html
