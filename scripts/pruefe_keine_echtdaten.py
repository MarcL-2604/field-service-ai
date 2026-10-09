"""
Waechter: Keine Echtdaten in git-getrackten Dateien (GitHub Pages ist oeffentlich).

Liest zur LAUFZEIT die lokalen Echtdaten (data/techniker_kontakte.json: Klarnamen,
data/smax_dashboard_data.json: Klinik-/Account-Namen) und sucht diese Strings in
ALLEN von git getrackten Dateien. Ausgabe: nur Anzahl und Dateipfad, nie Namen.

  python scripts/pruefe_keine_echtdaten.py        # Exit 0 = sauber, 1 = Treffer
  python scripts/pruefe_keine_echtdaten.py --staged   # nur Index (fuer pre-commit)

Fehlt data/ (z.B. frischer Clone), gibt es nichts zu pruefen -> Exit 0.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KONTAKTE = ROOT / "data" / "techniker_kontakte.json"
CACHE = ROOT / "data" / "smax_dashboard_data.json"
PSEUDONYM = re.compile(r"^\S+ [A-Z]\.$")          # "Vorname N." ist bewusst pseudonym
# Der Projekteigner ist als Autor bewusst oeffentlich und wird nicht als Treffer gewertet.
EIGNER = {"Marc Liebhardt"}
MIN_KLINIKNAME = 8


def _varianten(name: str) -> set[str]:
    ae = name.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return {name, ae}


def lade_suchbegriffe() -> dict:
    """Gibt {'namen', 'kliniken', 'muster'} zurueck (leer, wenn data/ fehlt)."""
    namen: set[str] = set()
    kliniken: set[str] = set()
    muster: list[re.Pattern] = []
    if KONTAKTE.is_file():
        for k in json.loads(KONTAKTE.read_text(encoding="utf-8")):
            if k.startswith("_") or k in EIGNER or PSEUDONYM.match(k) or " " not in k:
                continue
            namen |= _varianten(k)
    if CACHE.is_file():
        d = json.loads(CACHE.read_text(encoding="utf-8"))
        # Pseudonym "Vorname N." -> jeder ausgeschriebene Nachname "Vorname N..." ist ein Klarname
        for t in d.get("techniker", []):
            v, _, l = str(t.get("pseudonym_id", "")).partition(" ")
            if v and l.endswith("."):
                muster.append(re.compile(re.escape(v) + " " + re.escape(l[0]) + "[a-zäöüß]{2,}"))
        for j in d.get("job_standorte", []):
            kliniken.add(str(j.get("account") or ""))
        for a in d.get("offene_auftraege", []):
            kliniken.add(str(a.get("klinik") or ""))
    kliniken = {k for k in kliniken if len(k) >= MIN_KLINIKNAME and "medtronic" not in k.lower()}
    return {"namen": namen, "kliniken": kliniken, "muster": muster}


def getrackte_dateien(nur_index: bool = False) -> list[str]:
    cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM", "-z"] if nur_index \
        else ["git", "ls-files", "-z"]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def finde_treffer(nur_index: bool = False) -> dict[str, dict[str, int]]:
    """{pfad: {'namen': n, 'kliniken': n}} nur fuer Dateien mit Treffern."""
    begriffe = lade_suchbegriffe()
    treffer: dict[str, dict[str, int]] = {}
    for rel in getrackte_dateien(nur_index):
        pfad = ROOT / rel
        if not pfad.is_file() or pfad.stat().st_size > 20_000_000:
            continue
        try:
            text = pfad.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        z = {
            "namen": sum(text.count(b) for b in begriffe["namen"])
            + sum(1 for p in begriffe["muster"] for m in p.findall(text) if m not in EIGNER),
            "kliniken": sum(text.count(b) for b in begriffe["kliniken"]),
        }
        if any(z.values()):
            treffer[rel] = z
    return treffer


def main(argv: list[str] | None = None) -> int:
    nur_index = "--staged" in (argv if argv is not None else sys.argv[1:])
    b = lade_suchbegriffe()
    if not b["namen"] and not b["kliniken"] and not b["muster"]:
        print("Keine lokalen Echtdaten vorhanden -> nichts zu pruefen.")
        return 0
    treffer = finde_treffer(nur_index)
    if not treffer:
        print(f"OK: keine Echtdaten in getrackten Dateien ({len(b['namen'])} Namensvarianten, "
              f"{len(b['kliniken'])} Klinikbegriffe geprueft).")
        return 0
    print(f"FEHLER: Echtdaten in {len(treffer)} getrackten Datei(en):")
    for rel, z in sorted(treffer.items()):
        print(f"  {rel}: Namen={z['namen']} Kliniken={z['kliniken']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
