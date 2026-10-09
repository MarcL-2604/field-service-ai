"""Installiert einen optionalen pre-commit-Hook, der Echtdaten in gestagten Dateien blockiert.

  python scripts/install_pre_commit_hook.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / ".git" / "hooks" / "pre-commit"
INHALT = """#!/bin/sh
# Field Service AI: keine Echtdaten committen (GitHub Pages ist oeffentlich)
PY=python
[ -x venv/Scripts/python.exe ] && PY=venv/Scripts/python.exe
[ -x venv/bin/python ] && PY=venv/bin/python
exec "$PY" scripts/pruefe_keine_echtdaten.py --staged
"""

if __name__ == "__main__":
    HOOK.parent.mkdir(exist_ok=True)
    HOOK.write_text(INHALT, encoding="utf-8", newline="\n")
    try:
        HOOK.chmod(0o755)
    except OSError:
        pass
    print(f"pre-commit-Hook installiert: {HOOK}")
