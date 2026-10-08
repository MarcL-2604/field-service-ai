"""Tests fuer fsa_server.py: Whitelist, Bind-Standard, Import-Endpunkt (mit Mini-Excel)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import fsa_server
from tests.test_e2e_import_dashboard import _mini_excel


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(fsa_server, "XLSX_ZIEL", tmp_path / "KI_gestuetzte_Planung.xlsx")
    monkeypatch.setattr(fsa_server, "fuehre_import_aus", lambda: (True, "import-log"))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), fsa_server.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", tmp_path
    srv.shutdown()
    srv.server_close()


def _get(url):
    try:
        with urllib.request.urlopen(url) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def _post(url, body, headers=None):
    req = urllib.request.Request(url, data=body, method="POST", headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_whitelist_pfade():
    assert fsa_server.ist_erlaubter_pfad("dashboard.html")
    assert fsa_server.ist_erlaubter_pfad("push/manifest.json")
    for verboten in ("data/KI_gestuetzte_Planung.xlsx", "data/techniker_kontakte.json",
                     "fsa_server.py", "api/smax_cache.py", "../x.html", ".git/config",
                     "manifest.json", "venv/Scripts/python.exe"):
        assert not fsa_server.ist_erlaubter_pfad(verboten), verboten


def test_server_liefert_nur_whitelist(server):
    url, _ = server
    assert _get(url + "/dashboard.html") == 200
    assert _get(url + "/data/techniker_kontakte.json") == 404
    assert _get(url + "/fsa_server.py") == 404


def test_import_ablehnung_keine_xlsx(server):
    url, _ = server
    status, body = _post(url + "/api/import", b"kein excel")
    assert status == 400 and not body["ok"]


def test_import_ablehnung_fremder_origin(server):
    url, _ = server
    status, body = _post(url + "/api/import", b"PK\x03\x04", {"Origin": "http://evil.example"})
    assert status == 403


def test_import_formatfehler_ersetzt_nichts(server, tmp_path):
    url, tmp = server
    kaputt = _mini_excel(tmp / "kaputt.xlsx", ohne_sheet="4_Open_Jobs")
    status, body = _post(url + "/api/import", kaputt.read_bytes())
    assert status == 422 and any("4_Open_Jobs" in p for p in body["probleme"])
    assert not (tmp / "KI_gestuetzte_Planung.xlsx").exists()


def test_import_ok_ersetzt_datei_und_sichert_vorherige(server):
    url, tmp = server
    ziel = tmp / "KI_gestuetzte_Planung.xlsx"
    ziel.write_bytes(b"alt")
    gut = _mini_excel(tmp / "gut.xlsx", offene=[("OFF-1", "89073")])
    status, body = _post(url + "/api/import", gut.read_bytes())
    assert status == 200 and body["ok"] and body["log"] == "import-log"
    assert ziel.read_bytes() == gut.read_bytes()
    assert (tmp / "KI_gestuetzte_Planung.vorher.xlsx").read_bytes() == b"alt"
    assert not list(tmp.glob("tmp*.xlsx"))  # keine Temp-Reste
