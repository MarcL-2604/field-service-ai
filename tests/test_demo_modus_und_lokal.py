"""Demo-Modus ignoriert den Cache; Server liefert /dashboard.html aus lokal/ (nur dieses Mapping)."""
import fsa_server
from api import smax_cache


def test_demo_modus_ignoriert_cache(tmp_path, monkeypatch):
    cache = tmp_path / "c.json"
    cache.write_text('{"techniker": [{"x": 1}]}', encoding="utf-8")
    monkeypatch.setattr(smax_cache, "_CACHE", cache)
    monkeypatch.setattr(smax_cache, "_DEMO_MODUS", False)
    assert smax_cache.load_dashboard_data() is not None
    smax_cache.set_demo_modus(True)
    try:
        assert smax_cache.load_dashboard_data() is None
    finally:
        smax_cache.set_demo_modus(False)


def test_server_lokal_mapping(tmp_path, monkeypatch):
    monkeypatch.setattr(fsa_server, "ROOT", tmp_path)
    assert fsa_server.aufgeloester_pfad("dashboard.html") == "dashboard.html"
    (tmp_path / "lokal").mkdir()
    (tmp_path / "lokal" / "dashboard.html").write_text("x", encoding="utf-8")
    assert fsa_server.aufgeloester_pfad("dashboard.html") == "lokal/dashboard.html"
    assert fsa_server.aufgeloester_pfad("index.html") == "index.html"


def test_lokal_nicht_direkt_abrufbar():
    assert not fsa_server.ist_erlaubter_pfad("lokal/dashboard.html")
    assert not fsa_server.ist_erlaubter_pfad("data/smax_dashboard_data.json")
