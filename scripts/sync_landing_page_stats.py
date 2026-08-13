"""Synchronisiert die auf den statischen Marketing-/Demo-Seiten beworbenen
Projekt-Kennzahlen mit config.py.

Hintergrund: index.html, demo.html und animation.html sind handgepflegte,
statische Seiten (kein Python-Templating wie dashboard.py). Die Kennzahlen
(Techniker, Geraete, Kliniken, Tests, Dashboard-Checks, Cluster,
Produktfamilien) wurden bei frueheren Updates mehrfach dupliziert (Hero-Stats,
Prototyp-Karten, Config-Panel-Defaults, Chat-Begruessung, Footer,
DE/EN-Uebersetzungen, JS-Konfigurationsobjekt DEFS) und liefen dadurch
auseinander -- z.B. zeigten die Seiten noch "516 Tests" / "14 Techniker" /
"1.985 Geraete", waehrend das Dashboard laengst 897 Tests / 24 Techniker /
6.569 Geraete hatte.

Einzige Quelle: config.py (PROJEKT_*-Konstanten + TESTS_ANZAHL). Bei jedem
SMax-Import oder Testlauf dort aktualisieren, dann dieses Skript ausfuehren --
NICHT direkt in den HTML-Dateien editieren.

Aktualisiert in index.html:
  - JS-Objekt `const DEFS={...}` (steuert zur Laufzeit ALLE abgeleiteten
    Anzeigen: Hero-Stats, Prototyp-Karten, Cluster-Heading, Config-Panel --
    siehe applyStats() in index.html)
  - Statische HTML-Platzhalter (Anzeige vor dem ersten JS-Durchlauf) und die
    <input value="..."> Defaults im Config-Panel
Aktualisiert in demo.html / animation.html:
  - Stat-Kacheln, Chat-Begruessung/Info-Boxen, Footer -- DE + EN, jeweils
    ueber den Label-Kontext erkannt (nicht ueber den alten Zahlenwert).

Nutzung: python scripts/sync_landing_page_stats.py [--check]
  --check: nur pruefen, ob alle Seiten bereits synchron sind (Exit-Code 1
           wenn nicht) -- aendert nichts. Fuer CI/Pre-Commit-Hooks geeignet.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from config import (  # noqa: E402
    PROJEKT_TECHNIKER_ANZAHL,
    PROJEKT_GERAETE_ANZAHL,
    PROJEKT_KLINIKEN_ANZAHL,
    PROJEKT_DASHBOARD_CHECKS,
    PROJEKT_CLUSTER_ANZAHL,
    PROJEKT_PRODUKTFAMILIEN_ANZAHL,
    TESTS_ANZAHL,
)

_INDEX_HTML = _ROOT / "index.html"


def _de_zahl(n: int) -> str:
    """Formatiert eine Zahl mit deutschem Tausenderpunkt, z.B. 6569 -> '6.569'."""
    return f"{n:,}".replace(",", ".")


def _werte() -> dict:
    return {
        "tech": PROJEKT_TECHNIKER_ANZAHL,
        "dev": PROJEKT_GERAETE_ANZAHL,
        "cli": PROJEKT_KLINIKEN_ANZAHL,
        "tests": TESTS_ANZAHL,
        "dash": f"{PROJEKT_DASHBOARD_CHECKS}/{PROJEKT_DASHBOARD_CHECKS}",
        "clust": PROJEKT_CLUSTER_ANZAHL,
        "pfam": PROJEKT_PRODUKTFAMILIEN_ANZAHL,
    }


def _ersetzungen(w: dict) -> list[tuple[str, str]]:
    """Liste von (regex, replacement) -- angewandt der Reihe nach auf index.html."""
    dev_fmt = _de_zahl(w["dev"])
    cli_fmt = _de_zahl(w["cli"])
    return [
        # JS-Konfigurationsobjekt -- die eigentliche Laufzeit-Quelle
        (
            r"const DEFS=\{tech:\d+,dev:\d+,cli:\d+,tests:\d+,dash:'[^']*',clust:\d+,pfam:\d+\};",
            f"const DEFS={{tech:{w['tech']},dev:{w['dev']},cli:{w['cli']},"
            f"tests:{w['tests']},dash:'{w['dash']}',clust:{w['clust']},pfam:{w['pfam']}}};",
        ),
        # Hero-Stat-Zeile (4 Kacheln)
        (r'(id="sn-tests">)\d+(</div>)', rf"\g<1>{w['tests']}\g<2>"),
        (r'(id="sn-dev">)[\d.]+(</div>)', rf"\g<1>{dev_fmt}\g<2>"),
        (r'(id="sn-tech">)\d+(</div>)', rf"\g<1>{w['tech']}\g<2>"),
        (r'(id="sn-dash">)\S+(</div>)', rf"\g<1>{w['dash']}\g<2>"),
        # Hero-Subtitle ("Entwickelt fuer X Techniker, Y Geraete, Z Kliniken")
        (r'(id="cfg-tech-hero">)\d+(</strong>)', rf"\g<1>{w['tech']}\g<2>"),
        (r'(id="cfg-dev-hero">)[\d.]+(</strong>)', rf"\g<1>{dev_fmt}\g<2>"),
        (r'(id="cfg-cli-hero">)[\d.]+(</strong>)', rf"\g<1>{cli_fmt}\g<2>"),
        # Prototyp-Karten
        (r'(id="pc1-n">)\d+(</div>)', rf"\g<1>{w['tests']}\g<2>"),
        (r'(id="pc2-n">)\S+(</div>)', rf"\g<1>{w['dash']}\g<2>"),
        (r'(id="pc3-n">)\d+(</div>)', rf"\g<1>{w['clust']}\g<2>"),
        (
            r'(id="pc3-t">)\d+( Produktfamilien · L2/L3-Regeln · HF-Sonderfall · vollständig klassifiziert</div>)',
            rf"\g<1>{w['pfam']}\g<2>",
        ),
        # Cluster/Produktfamilien-Ueberschrift
        (
            r'(id="cl-heading">)\d+( Cluster\.<br>)\d+( Produktfamilien\.</h2>)',
            rf"\g<1>{w['clust']}\g<2>{w['pfam']}\g<3>",
        ),
        # Prototyp-Fliesstext (statischer Platzhalter vor JS-Ausfuehrung)
        (
            r'(id="pr-body">Kein Mock, keine Simulation\. )\d+( Tests bestanden, Dashboard )\S+(\.</p>)',
            rf"\g<1>{w['tests']}\g<2>{w['dash']}\g<3>",
        ),
        # Roadmap-Zeile
        (
            r'(id="tl1-dt">)\d+( Tests · Dashboard )\S+( · Autodidaktisch vor formaler Ausbildung</div>)',
            rf"\g<1>{w['tests']}\g<2>{w['dash']}\g<3>",
        ),
        # Config-Panel <input>-Defaults
        (r'(id="ci-tech" type="number" value=")\d+(")', rf"\g<1>{w['tech']}\g<2>"),
        (r'(id="ci-dev" type="number" value=")\d+(")', rf"\g<1>{w['dev']}\g<2>"),
        (r'(id="ci-cli" type="number" value=")\d+(")', rf"\g<1>{w['cli']}\g<2>"),
        (r'(id="ci-tests" type="number" value=")\d+(")', rf"\g<1>{w['tests']}\g<2>"),
        (r'(id="ci-dash" type="text" value=")\S+(")', rf"\g<1>{w['dash']}\g<2>"),
        (r'(id="ci-clust" type="number" value=")\d+(")', rf"\g<1>{w['clust']}\g<2>"),
        (r'(id="ci-pfam" type="number" value=")\d+(")', rf"\g<1>{w['pfam']}\g<2>"),
        # TX-Uebersetzungsobjekte (DE + EN) -- werden zur Laufzeit von applyStats()
        # sofort ueberschrieben, hier trotzdem synchron gehalten (Quelltext-Hygiene,
        # Fallback falls JS deaktiviert ist).
        (
            r"('cl-heading':')\d+( Cluster\.<br>)\d+( Produktfamilien\.')",
            rf"\g<1>{w['clust']}\g<2>{w['pfam']}\g<3>",
        ),
        (
            r"('cl-heading':')\d+( Clusters\.<br>)\d+( Product Families\.')",
            rf"\g<1>{w['clust']}\g<2>{w['pfam']}\g<3>",
        ),
        (
            r"('pr-body':'Kein Mock, keine Simulation\. )\d+( Tests, Dashboard )\S+(\.')",
            rf"\g<1>{w['tests']}\g<2>{w['dash']}\g<3>",
        ),
        (
            r"('pr-body':'No mock, no simulation\. )\d+( tests, dashboard )\S+(\.')",
            rf"\g<1>{w['tests']}\g<2>{w['dash']}\g<3>",
        ),
        (r"('pc3-t':')\d+( Familien · L2/L3-Regeln · HF-Sonderfall abgebildet')", rf"\g<1>{w['pfam']}\g<2>"),
        (r"('pc3-t':')\d+( families · L2/L3 rules · HF special case mapped')", rf"\g<1>{w['pfam']}\g<2>"),
        (
            r"('tl1-dt':')\d+( Tests · Dashboard )\S+?( · Autodidaktisch')",
            rf"\g<1>{w['tests']}\g<2>{w['dash']}\g<3>",
        ),
        (
            r"('tl1-dt':')\d+( tests · Dashboard )\S+?( · Self-taught')",
            rf"\g<1>{w['tests']}\g<2>{w['dash']}\g<3>",
        ),
    ]


def _ersetzungen_demo(w: dict) -> list[tuple[str, str]]:
    """demo.html: Stat-Kacheln, Chat-Begruessung, Footer (DE + EN)."""
    dev_fmt_de = _de_zahl(w["dev"])
    dev_fmt_en = f"{w['dev']:,}"
    return [
        (r'(<div class="stat-v" style="color:#5EDD9F">)\d+(</div><div class="stat-l">Tests grün</div>)',
         rf"\g<1>{w['tests']}\g<2>"),
        (r'(<div class="stat-v" style="color:var\(--sky\)">)[\d.]+(</div><div class="stat-l">Vertragsgeräte</div>)',
         rf"\g<1>{dev_fmt_de}\g<2>"),
        (r'(Hallo! Ich kenne alle )\d+( Techniker, )[\d.]+( Geräte, Tour-Optimierung)',
         rf"\g<1>{w['tech']}\g<2>{dev_fmt_de}\g<3>"),
        (r'(Hello! I know all )\d+( technicians, )[\d,]+( devices, tour optimization)',
         rf"\g<1>{w['tech']}\g<2>{dev_fmt_en}\g<3>"),
        (r'(Demo v2 · )\d+( Tests grün)', rf"\g<1>{w['tests']}\g<2>"),
        (r'(Demo v2 · )\d+( Tests passed)', rf"\g<1>{w['tests']}\g<2>"),
    ]


def _ersetzungen_animation(w: dict) -> list[tuple[str, str]]:
    """animation.html: Info-Boxen, Footer (DE + EN)."""
    dev_fmt_de = _de_zahl(w["dev"])
    dev_fmt_en = f"{w['dev']:,}"
    return [
        (r'([\d.]+) Vertragsgeräte · täglich geprüft · kein manuelles Nachschauen',
         rf"{dev_fmt_de} Vertragsgeräte · täglich geprüft · kein manuelles Nachschauen"),
        (r'[\d,]+ contract devices · checked daily · no manual lookup',
         rf"{dev_fmt_en} contract devices · checked daily · no manual lookup"),
        (r'(Kompetenz 40% \+ Fahrzeit 35% \+ Auslastung 25% · )\d+( Tests grün)',
         rf"\g<1>{w['tests']}\g<2>"),
        (r'(Competency 40% \+ Travel 35% \+ Utilization 25% · )\d+( tests passed)',
         rf"\g<1>{w['tests']}\g<2>"),
        (r'(Medtronic GmbH Service (?:&amp;|&) Repair · )\d+( Tests grün)', rf"\g<1>{w['tests']}\g<2>"),
        (r'(Medtronic GmbH Service (?:&amp;|&) Repair · )\d+( Tests passed)', rf"\g<1>{w['tests']}\g<2>"),
    ]


_DATEIEN = [
    (_INDEX_HTML, _ersetzungen),
    (_ROOT / "demo.html", _ersetzungen_demo),
    (_ROOT / "animation.html", _ersetzungen_animation),
]


def sync(check_only: bool = False) -> bool:
    """Fuehrt alle Ersetzungen in allen Zieldateien aus.

    Gibt True zurueck wenn ALLE Dateien bereits synchron waren.
    """
    alle_synchron = True
    werte = _werte()
    for pfad, ersetzungen_fn in _DATEIEN:
        original = pfad.read_text(encoding="utf-8")
        updated = original
        for pattern, replacement in ersetzungen_fn(werte):
            updated = re.sub(pattern, replacement, updated)

        if updated == original:
            print(f"{pfad.name} ist bereits synchron mit config.py.")
            continue

        alle_synchron = False
        if check_only:
            print(f"{pfad.name} ist NICHT synchron mit config.py -- "
                  "python scripts/sync_landing_page_stats.py ausfuehren.")
            continue

        pfad.write_text(updated, encoding="utf-8")
        print(f"{pfad.name} aktualisiert.")

    return alle_synchron


if __name__ == "__main__":
    check_only = "--check" in sys.argv
    war_synchron = sync(check_only)
    if check_only and not war_synchron:
        sys.exit(1)
