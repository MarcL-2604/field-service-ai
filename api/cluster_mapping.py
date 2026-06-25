"""
api/cluster_mapping.py
=======================
Präfix-basiertes Cluster-Mapping für Medtronic Model Codes.

Matching-Reihenfolge:
  1. Exakter Match (case-insensitive, ohne Leerzeichen)
  2. Längster Präfix-Match
  3. None → Code wird in Ampel/Crosstraining ignoriert

Datenquelle: data/model_code_cluster_mapping.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

_MAPPING_FILE = Path(__file__).resolve().parent.parent / "data" / "model_code_cluster_mapping.json"


@dataclass(frozen=True)
class ClusterInfo:
    cluster: str
    repair: bool


@lru_cache(maxsize=1)
def _lade_mapping() -> tuple[dict[str, ClusterInfo], list[tuple[str, ClusterInfo]]]:
    """Lädt Mapping einmalig und gibt (exact_dict, prefix_list_absteigend) zurück."""
    raw = json.loads(_MAPPING_FILE.read_text(encoding="utf-8"))

    exact: dict[str, ClusterInfo] = {
        code.strip().upper(): ClusterInfo(cluster=v["cluster"], repair=v["repair"])
        for code, v in raw.get("exact", {}).items()
    }

    prefixes: list[tuple[str, ClusterInfo]] = sorted(
        [
            (entry["prefix"].strip().upper(), ClusterInfo(cluster=entry["cluster"], repair=entry["repair"]))
            for entry in raw.get("prefixes", [])
        ],
        key=lambda t: len(t[0]),
        reverse=True,
    )

    return exact, prefixes


def finde_cluster(model_code: str) -> Optional[ClusterInfo]:
    """Gibt ClusterInfo für einen Model Code zurück, oder None wenn kein Match."""
    code = model_code.strip().upper().replace(" ", "")
    exact, prefixes = _lade_mapping()

    if code in exact:
        return exact[code]

    for prefix, info in prefixes:
        if code.startswith(prefix):
            return info

    return None


def finde_repair_familie(model_code: str) -> Optional[str]:
    """Gibt den kanonischen Familie-Schlüssel für repair=True Geräte zurück.

    Familie = längster passender Präfix, oder exakter Code bei reinem Exact-Match.
    Gibt None zurück wenn das Gerät repair=False ist oder unbekannt ist.

    Beispiele:
        MC-HUGO-3DDOF  → "MC-HUGO"
        MC-840-A       → "MC-840"
        MC-NITRON      → "MC-NITRON"  (Exact-Match)
        MC-FT10        → "MC-FT10"   (Exact-Match)
        MC-VISTA       → None        (repair=False)
        MC-UNBEKANNT   → None
    """
    code = model_code.strip().upper().replace(" ", "")
    exact, prefixes = _lade_mapping()
    if code in exact:
        return code if exact[code].repair else None
    for prefix, info in prefixes:
        if code.startswith(prefix):
            return prefix if info.repair else None
    return None


def mapping_neu_laden() -> None:
    """Leert den LRU-Cache — nötig nach Änderungen an der JSON-Datei."""
    _lade_mapping.cache_clear()
