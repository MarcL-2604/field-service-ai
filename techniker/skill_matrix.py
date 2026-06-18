"""
Skillmatrix
===========
STK-Level = PM-Level — ein Level-Wert pro Cluster.
Repair ist ein separates Feld (L3 oder None = kein Feldeinsatz).

Cluster-Übersicht:
  CLUSTER1_OR       Hugo, Mazor, StealthStation, O-arm    → L3, Repair: L3
  CLUSTER2_CARDIAC  Affera, Arctic Front, Nitron           → L3, Repair: L3
  CLUSTER3_MONITOR  Ventilation, Monitoring                → L2, Repair: L3
  CLUSTER4_DIGITAL  Touch Surgery                          → L2, Repair: —
  SMALL_CAPITAL     NIM, PROG, ACT, IPC/EC300, Neurophysio → L2, Repair: —
  HF_CHIRURGIE      Sonderfall                             → L2, Repair: L3 (Pflicht)
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ── Typen ─────────────────────────────────────────────────────────────────────

Level = Literal["L2", "L3"] | None
RepairLevel = Literal["L3"] | None       # Nur L3 erlaubt, L2 reicht nicht für Repair


# ── Cluster-Skill (ein Cluster) ───────────────────────────────────────────────

class ClusterSkill(BaseModel):
    """
    Qualifikation eines Technikers für einen Cluster.
    level:  STK = PM = gleiche Anforderung → ein Wert
    repair: L3 oder None (None = kein Feldeinsatz in diesem Cluster)
    """
    level: Level = None
    repair: RepairLevel = None

    @property
    def ist_qualifiziert(self) -> bool:
        """Mindestens STK/PM-fähig."""
        return self.level is not None

    @property
    def ist_vollstaendig(self) -> bool:
        """Level UND Repair vorhanden (für Cluster mit Repair-Anforderung)."""
        return self.level is not None and self.repair is not None

    @property
    def kann_stk(self) -> bool:
        return self.level in ("L2", "L3")

    @property
    def kann_pm(self) -> bool:
        return self.level in ("L2", "L3")

    @property
    def kann_repair(self) -> bool:
        return self.repair == "L3"


# ── Vollständige Skillmatrix eines Technikers ─────────────────────────────────

class TechnikerSkillmatrix(BaseModel):
    """
    Alle Cluster-Skills eines Technikers.
    CLUSTER4_DIGITAL und SMALL_CAPITAL haben kein Repair-Feld (immer None).
    HF_CHIRURGIE Sonderfall: level=L2, repair=L3 (Pflicht wenn qualifiziert).
    """

    tech_id: str = Field(..., pattern=r"^T\d{1,2}$")

    # Cluster 1 — OR
    c1_or: ClusterSkill = Field(default_factory=ClusterSkill)
    # Cluster 2 — Cardiac
    c2_cardiac: ClusterSkill = Field(default_factory=ClusterSkill)
    # Cluster 3 — Monitoring
    c3_monitoring: ClusterSkill = Field(default_factory=ClusterSkill)
    # Cluster 4 — Digital (kein Repair)
    c4_digital: ClusterSkill = Field(default_factory=ClusterSkill)
    # Small Capital (kein Repair im Feld)
    small_capital: ClusterSkill = Field(default_factory=ClusterSkill)
    # HF-Chirurgie (Sonderfall: Repair L3 Pflicht)
    hf_chirurgie: ClusterSkill = Field(default_factory=ClusterSkill)

    hugo_ka: bool = False
    zertifiziert_bis: str | None = None     # ISO-Datum "YYYY-MM-DD"

    @model_validator(mode="after")
    def repair_nicht_fuer_digital_und_smallcap(self) -> "TechnikerSkillmatrix":
        """CLUSTER4_DIGITAL und SMALL_CAPITAL haben kein Feldeinsatz-Repair."""
        if self.c4_digital.repair is not None:
            self.c4_digital = ClusterSkill(level=self.c4_digital.level, repair=None)
        if self.small_capital.repair is not None:
            self.small_capital = ClusterSkill(level=self.small_capital.level, repair=None)
        return self

    # ── Scoring-Methoden ──────────────────────────────────────────────────────

    def kompetenz_score(self, cluster_id: str, auftragstyp: str) -> float:
        """
        Kompetenz-Score 0.0–1.0 für Scoring-Algorithmus.
        Gewichtung: Kompetenz 40% im Gesamtscore.

        Returns:
            1.0  = voll qualifiziert (Level + Repair wenn nötig)
            0.6  = nur Level (kein Repair, aber Repair gefordert)
            0.0  = nicht qualifiziert
        """
        skill = self._get_cluster(cluster_id)
        if skill is None:
            return 0.0

        at = auftragstyp.upper()

        if at in ("STK", "PM"):
            return 1.0 if skill.kann_stk else 0.0

        if at == "REPAIR":
            if skill.kann_repair:
                return 1.0
            if skill.kann_stk:
                return 0.6   # Level vorhanden aber kein Repair → Notfalleinschätzung
            return 0.0

        return 0.0

    def kann_auftrag(self, cluster_id: str, auftragstyp: str) -> bool:
        """Harter Check: Darf der Techniker diesen Auftrag übernehmen?"""
        skill = self._get_cluster(cluster_id)
        if skill is None:
            return False
        at = auftragstyp.upper()
        if at in ("STK", "PM"):
            return skill.kann_stk
        if at == "REPAIR":
            return skill.kann_repair
        return False

    def qualifizierte_cluster(self) -> list[str]:
        """Liste aller Cluster für die Level vorhanden ist."""
        result = []
        mapping = self._cluster_mapping()
        for name, skill in mapping.items():
            if skill.ist_qualifiziert:
                result.append(name)
        return result

    def crosstraining_luecken(self) -> list[dict]:
        """
        Gibt Cluster zurück wo Training empfohlen wird.
        Format: [{"cluster": str, "fehlt": str}, ...]
        """
        luecken = []
        REPAIR_CLUSTER = {"c1_or", "c2_cardiac", "c3_monitoring", "hf_chirurgie"}
        for name, skill in self._cluster_mapping().items():
            if not skill.ist_qualifiziert:
                luecken.append({"cluster": name, "fehlt": "Level (STK/PM)"})
            elif name in REPAIR_CLUSTER and not skill.kann_repair:
                luecken.append({"cluster": name, "fehlt": "Repair-Training (L3)"})
        return luecken

    # ── Interne Helfer ────────────────────────────────────────────────────────

    def _get_cluster(self, cluster_id: str) -> ClusterSkill | None:
        mapping = self._cluster_mapping()
        # Flexible Suche: "CLUSTER1_OR", "c1_or", "c1" alle akzeptiert
        key = cluster_id.lower().replace("-", "_")
        aliases = {
            "cluster1_or": "c1_or", "c1_or": "c1_or", "c1": "c1_or",
            "cluster2_cardiac": "c2_cardiac", "c2_cardiac": "c2_cardiac", "c2": "c2_cardiac",
            "cluster3_monitoring": "c3_monitoring", "c3_monitoring": "c3_monitoring", "c3": "c3_monitoring",
            "cluster4_digital": "c4_digital", "c4_digital": "c4_digital", "c4": "c4_digital",
            "small_capital": "small_capital", "cs": "small_capital",
            "small_capital_mit_repair": "hf_chirurgie",
            "hf_chirurgie": "hf_chirurgie", "ch": "hf_chirurgie",
        }
        resolved = aliases.get(key)
        return mapping.get(resolved) if resolved else None

    def _cluster_mapping(self) -> dict[str, ClusterSkill]:
        return {
            "c1_or": self.c1_or,
            "c2_cardiac": self.c2_cardiac,
            "c3_monitoring": self.c3_monitoring,
            "c4_digital": self.c4_digital,
            "small_capital": self.small_capital,
            "hf_chirurgie": self.hf_chirurgie,
        }


# ── Import-Helper ─────────────────────────────────────────────────────────────

def skillmatrix_aus_csv_zeile(zeile: dict) -> TechnikerSkillmatrix:
    """
    Erstellt TechnikerSkillmatrix aus einer CSV-Zeile (nach Spalten-Mapping).
    Erwartet Spalten wie: tech_id, c1_level, c1_repair, c2_level, ...
    Tolerant gegenüber fehlenden oder leeren Werten.
    """
    def _level(v: str | None) -> Level:
        val = str(v or "").strip().upper()
        return val if val in ("L2", "L3") else None  # type: ignore[return-value]

    def _repair(v: str | None) -> RepairLevel:
        val = str(v or "").strip().upper()
        return "L3" if val == "L3" else None

    def _bool(v: str | None) -> bool:
        return str(v or "").strip().lower() in ("j", "ja", "yes", "true", "1")

    CLUSTER_KEYS = [
        ("c1_or",          "c1_level",  "c1_repair"),
        ("c2_cardiac",     "c2_level",  "c2_repair"),
        ("c3_monitoring",  "c3_level",  "c3_repair"),
        ("c4_digital",     "c4_level",  None),
        ("small_capital",  "cs_level",  None),
        ("hf_chirurgie",   "ch_level",  "ch_repair"),
    ]

    cluster_skills = {}
    for attr, lk, rk in CLUSTER_KEYS:
        lv = _level(zeile.get(lk))
        rp = _repair(zeile.get(rk)) if rk else None
        cluster_skills[attr] = ClusterSkill(level=lv, repair=rp)

    return TechnikerSkillmatrix(
        tech_id=str(zeile.get("tech_id", "")).strip().upper(),
        hugo_ka=_bool(zeile.get("hugo_ka")),
        zertifiziert_bis=zeile.get("cert_bis") or None,
        **cluster_skills,
    )
