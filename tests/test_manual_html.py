"""Tests fuer manual.html (User Manual fuer Koordinatoren und Techniker).

Da manual.html eine statische HTML-Datei ist (kein Python-Template wie
dashboard.py), pruefen diese Tests per Text-/Regex-Analyse: Struktur
(Sprungmarken, Kapitel/Abschnitte), i18n-Vollstaendigkeit (jeder
data-i18n/data-i18n-html-Key muss eine EN-Uebersetzung im _EN-Dict haben --
das ist genau das bekannte Sprachmischungs-Bug-Muster: ein Element wechselt
beim Sprachwechsel nicht mit, weil die Uebersetzung fehlt) und dass der
Handbuch-Link von den anderen Seiten aus erreichbar ist.
"""

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_MANUAL = _ROOT / "manual.html"


@pytest.fixture(scope="module")
def manual_html() -> str:
    return _MANUAL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def en_dict_block(manual_html: str) -> str:
    script = manual_html[manual_html.index("<script>"):manual_html.index("</script>")]
    return script[script.index("var _EN = {"):script.index("function setLang")]


class TestManualExistiertUndLaedt:
    def test_datei_existiert(self):
        assert _MANUAL.exists()

    def test_hat_doctype_und_titel(self, manual_html):
        assert manual_html.startswith("<!DOCTYPE html>")
        assert "<title>Handbuch — Field Service AI</title>" in manual_html

    def test_passwortschutz_konsistent_mit_anderen_seiten(self, manual_html):
        """Gleicher SHA-256-Hash und localStorage-Key wie index.html/
        dashboard.html/coordinator_import.html -- ein Login gilt fuer
        alle Seiten."""
        assert "037453db72fb8a93ebe48d4ff52b1b493cdf56ef6a28240a65c6055b76d8f360" in manual_html
        assert "fsa_auth" in manual_html
        assert 'id="pw-overlay"' in manual_html


class TestManualStruktur:
    def test_zwei_kapitel_vorhanden(self, manual_html):
        assert "Kapitel 1 — Für Koordinatoren" in manual_html
        assert "Kapitel 2 — Für Techniker" in manual_html

    def test_14_abschnitte_mit_id_vorhanden(self, manual_html):
        ids = re.findall(r'<section class="manual-section" id="([^"]+)"', manual_html)
        assert len(ids) == 14
        assert ids == [f"ch1-{i}" for i in range(1, 9)] + [f"ch2-{i}" for i in range(1, 7)]

    def test_toc_sprungmarken_stimmen_mit_abschnitten_ueberein(self, manual_html):
        toc_hrefs = re.findall(r'href="#([^"]+)"', manual_html)
        section_ids = re.findall(r'<section class="manual-section" id="([^"]+)"', manual_html)
        assert toc_hrefs
        assert set(toc_hrefs) == set(section_ids)

    def test_alle_sprungmarken_ziele_existieren_als_anker(self, manual_html):
        """Jeder TOC-Link muss ein tatsaechlich vorhandenes id-Attribut treffen."""
        toc_hrefs = re.findall(r'href="#([^"]+)"', manual_html)
        for href in toc_hrefs:
            assert f'id="{href}"' in manual_html, f"Kein Element mit id=\"{href}\" gefunden"

    def test_gold_hinweisbox_mit_stand_datum_vorhanden(self, manual_html):
        assert "manual-gold-hint" in manual_html
        assert "kontinuierlich aktualisiert" in manual_html
        assert re.search(r"Stand:\s*\d{2}\.\d{2}\.\d{4}", manual_html)

    def test_faq_abschnitte_in_beiden_kapiteln(self, manual_html):
        assert manual_html.count('class="faq-item"') >= 6

    def test_kapitel_2_enthaelt_vier_faktoren_ki_kontrolle(self, manual_html):
        for begriff in ["Vollständigkeit", "Plausibilität Dauer", "Auffälligkeiten", "Dokumente"]:
            assert begriff in manual_html


class TestManualI18nVollstaendigkeit:
    """Der zentrale Test gegen das bekannte Sprachmischungs-Muster: JEDES
    data-i18n/data-i18n-html-Element muss einen Eintrag im _EN-Dict haben,
    sonst bleibt beim Umschalten auf Englisch deutscher Text stehen."""

    def _html_keys(self, manual_html: str) -> set[str]:
        return set(re.findall(r'data-i18n(?:-html)?="([^"]+)"', manual_html))

    def _en_keys(self, en_dict_block: str) -> set[str]:
        return set(re.findall(r"'([^']+)':", en_dict_block))

    def test_jeder_data_i18n_key_hat_en_uebersetzung(self, manual_html, en_dict_block):
        html_keys = self._html_keys(manual_html)
        en_keys = self._en_keys(en_dict_block)
        fehlend = html_keys - en_keys
        assert not fehlend, f"data-i18n-Keys ohne EN-Uebersetzung: {sorted(fehlend)}"

    def test_kein_verwaister_en_eintrag(self, manual_html, en_dict_block):
        """Regressionsschutz: EN-Eintraege ohne zugehoeriges HTML-Element
        deuten auf ein geloeschtes/umbenanntes Element hin, dessen alte
        Uebersetzung vergessen wurde aufzuraeumen."""
        html_keys = self._html_keys(manual_html)
        en_keys = self._en_keys(en_dict_block)
        verwaist = en_keys - html_keys
        assert not verwaist, f"EN-Eintraege ohne HTML-Element: {sorted(verwaist)}"

    def test_data_i18n_ohne_html_hat_keine_html_entities_im_en_wert(self, manual_html, en_dict_block):
        """Regressionsschutz: data-i18n (nicht -html) setzt .textContent, das
        HTML-Entities NICHT dekodiert -- ein EN-Wert mit '&amp;' wuerde dann
        woertlich als '&amp;' auf der Seite erscheinen statt als '&'.
        Gefundener und behobener Bug: 'toc.ch1.6'/'ch1.6.h' ('Tips &amp; tricks')."""
        plain_keys = set(re.findall(r'data-i18n="([^"]+)"', manual_html))
        for key in plain_keys:
            treffer = re.search(r"'" + re.escape(key) + r"':\s*'([^']*)'", en_dict_block)
            if not treffer:
                continue
            wert = treffer.group(1)
            assert "&amp;" not in wert, f"{key}: EN-Wert enthaelt rohes '&amp;' statt '&' ({wert!r})"
            assert "<" not in wert, f"{key}: EN-Wert enthaelt HTML-Tag, sollte data-i18n-html sein ({wert!r})"

    def test_data_i18n_ohne_html_hat_kein_html_tag_im_de_quelltext(self, manual_html):
        """Spiegelbildlicher Regressionsschutz: enthaelt der DE-Quelltext
        eines data-i18n-Elements ein HTML-Tag (z.B. <span>), geht dieses beim
        Sprachwechsel verloren, weil .textContent nur reinen Text liefert.
        Gefundener und behobener Bug: 'page.title' (<span>Handbuch</span>).
        Nutzt HTMLParser (Stack ueber Tag-Namen) statt Regex, um Start-/
        Endtag korrekt einander zuzuordnen."""
        from html.parser import HTMLParser

        class _Checker(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack = []  # [{tag, key, has_child_tag}]
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
        parser.feed(manual_html)
        assert not parser.violations, (
            f"data-i18n-Elemente mit verschachteltem HTML-Tag (sollten data-i18n-html sein): "
            f"{parser.violations}"
        )

    def test_mindestens_50_uebersetzte_elemente(self, manual_html):
        """Grobe Abdeckungs-Untergrenze -- ein Handbuch mit 13 Abschnitten
        sollte deutlich mehr als eine Handvoll i18n-Keys haben."""
        assert len(self._html_keys(manual_html)) >= 50

    def test_de_cache_wird_aus_dom_gebaut_nicht_hartcodiert_dupliziert(self, manual_html):
        """Die DE-Inhalte werden zur Laufzeit aus dem DOM gecacht statt als
        zweite Text-Kopie im Skript gepflegt -- verhindert, dass DE-Text im
        Body und im (nicht vorhandenen) DE-Dict auseinanderlaufen."""
        script = manual_html[manual_html.index("<script>"):manual_html.index("</script>")]
        assert "_DE_CACHE" in script
        assert "var _DE = {" not in script  # kein separates, dupliziertes DE-Dict

    def test_faq_body_bloecke_sind_uebersetzt(self, manual_html, en_dict_block):
        """Die FAQ-Bloecke (ch1.7.body / ch2.6.body) sind besonders leicht zu
        vergessen (kein <p>, sondern <details>-Struktur) -- explizite
        Regression fuer genau diesen zuvor gefundenen Fehler."""
        assert "'ch1.7.body':" in en_dict_block
        assert "'ch2.6.body':" in en_dict_block


class TestHandbuchLinkVonAnderenSeitenErreichbar:
    @pytest.mark.parametrize("seite", [
        "index.html", "coordinator_import.html", "workflow_demo.html", "demo.html",
    ])
    def test_seite_verlinkt_manual_html(self, seite):
        pfad = _ROOT / seite
        inhalt = pfad.read_text(encoding="utf-8")
        assert "manual.html" in inhalt, f"{seite} verlinkt nicht auf manual.html"

    def test_dashboard_py_verlinkt_manual_html(self):
        inhalt = (_ROOT / "reporting" / "dashboard.py").read_text(encoding="utf-8")
        assert 'href="manual.html"' in inhalt

    def test_manual_html_verlinkt_zurueck_zu_allen_seiten(self, manual_html):
        for ziel in ["index.html", "dashboard.html", "coordinator_import.html", "workflow_demo.html", "demo.html"]:
            assert f'href="{ziel}"' in manual_html, f"manual.html verlinkt nicht auf {ziel}"
