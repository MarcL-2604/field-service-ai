"""Waechter: keine Echtdaten (Technikernamen, Kliniknamen) in git-getrackten Dateien.

GitHub Pages ist oeffentlich -- alles Getrackte ist damit oeffentlich. Der Test liest die
lokalen Echtdaten zur Laufzeit (data/ ist gitignored) und ueberspringt sich ohne data/.
Ausgabe nennt nur Anzahl und Dateipfad.
"""
import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("pruefe_keine_echtdaten", ROOT / "scripts" / "pruefe_keine_echtdaten.py")
waechter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(waechter)

pytestmark = pytest.mark.skipif(
    not (ROOT / "data" / "smax_dashboard_data.json").is_file()
    and not (ROOT / "data" / "techniker_kontakte.json").is_file(),
    reason="data/ fehlt (kein lokaler Echtdatenbestand) -- nichts zu pruefen",
)


def _git_ok() -> bool:
    try:
        subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


@pytest.mark.skipif(not _git_ok(), reason="kein git-Repository")
def test_keine_echtdaten_in_getrackten_dateien():
    treffer = waechter.finde_treffer()
    assert not treffer, f"Echtdaten in {len(treffer)} getrackten Datei(en): {sorted(treffer)}"


@pytest.mark.skipif(not _git_ok(), reason="kein git-Repository")
def test_cache_und_lokal_sind_nicht_getrackt():
    tracked = set(waechter.getrackte_dateien())
    assert "data/smax_dashboard_data.json" not in tracked
    assert not any(p.startswith("lokal/") for p in tracked)
