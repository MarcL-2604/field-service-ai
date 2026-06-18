from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Optional
from pydantic import BaseModel, Field, model_validator


class TechnikerTyp(StrEnum):
    """Typ eines Servicetechnikers."""
    STANDARD = "STANDARD"
    KEY_ACCOUNT = "KEY_ACCOUNT"
    HUGO_KEY_ACCOUNT = "HUGO_KEY_ACCOUNT"


class TrainingsTyp(StrEnum):
    """Art der Schulung fuer eine Produktfamilie.

    INTERN:          Small Capital, Schulung im Feld durch L4-Trainer.
                     1-3 Tage, 0 EUR Kursgebuehr.
    TRAININGSCENTER: Big Capital, Medtronic Training Center.
                     3-5 Tage + Reise + Hotel + Handon-Einsaetze danach.
    DIGITAL:         Software-Plattform, Online-Zertifizierung.
                     ~500 EUR.
    """
    INTERN = "INTERN"
    TRAININGSCENTER = "TRAININGSCENTER"
    DIGITAL = "DIGITAL"


# ======================================================================
# Produkt-Cluster (finale Klassifizierung)
# Jede Liste enthaelt trainingsmatrix.csv UND geraete.csv Familiennamen.
# ======================================================================

# Small Capital: STK → L2 vollwertig, kein Repair im Feld
SMALL_CAPITAL: list[str] = [
    "Neuromonitoring",        # NIM
    "Programmer",             # PROG
    "ACT",
    "Kardiovaskulaer_IPC",    # EC300, AEX, alle IPC-Varianten
    "Neurophysiologie",
    "Energie",                # EC300 Legend (= IPC = Small Capital)
    "Kardiovaskulaer",        # Schrittmacher_Prog, AEX, ACT → trainingsmatrix
    # --- Erweiterung 2026 ---
    "CAGEN",                  # CardioGenesis Cardiac Surgery Energy
    "CAGEN_HP",               # CardioGenesis High-Power Variante
    "Endoflip",               # Endoluminal Functional Lumen Imaging
    "OsteoCool",              # RF Ablation Knochentumore
    "Accurian",               # Chirurgisches Versiegelungssystem
]

# Sonderfall: STK/PM → L2 vollwertig, Repair → L3 Pflicht
SMALL_CAPITAL_MIT_REPAIR: list[str] = [
    "HF_Chirurgie",           # geraete.csv Name
    "Elektrochirurgie",       # trainingsmatrix.csv Name
]

# Big Capital Cluster 1 – OR (OP-Saal): L3 Pflicht fuer STK+PM+Repair
BIG_CAPITAL_CLUSTER1_OR: list[str] = [
    "Hugo",                   # HugoRAS
    "Wirbelsaeule",           # Mazor X/Core (trainingsmatrix Name)
    "Mazor",                  # Mazor (geraete.csv Alias)
    "Navigation",             # O-arm, StealthStation (trainingsmatrix Name)
    "StealthStation",         # StealthStation (geraete.csv Alias)
    "OArm",                   # O-arm (geraete.csv Alias)
]

# Big Capital Cluster 2 – Cardiac: L3 Pflicht fuer STK+PM
BIG_CAPITAL_CLUSTER2_CARDIAC: list[str] = [
    "Kardiovaskulaer_Ablation",  # Affera, ArcticFront, Cryo (trainingsmatrix Name)
    "Affera",                 # geraete.csv Alias
    "ArcticFront",            # geraete.csv Alias
    "Nitron",                 # geraete.csv Alias
]

# Cluster 3 – Monitoring: STK L2 fuer Standard, PM+Repair L3
CLUSTER3_MONITORING: list[str] = [
    "Beatmung",               # Ventilation (trainingsmatrix Name)
    "Ventilation",            # geraete.csv Alias
    "Monitoring",             # Patientenmonitoring (zukuenftig)
    "Capnografie",            # CO2-Monitoring (trainingsmatrix Name)
    "Endoskopie",             # trainingsmatrix Name
    "Gastroenterologie",      # trainingsmatrix Name
]

# Cluster 4 – Digital: Software, Online-Zertifizierung
CLUSTER4_DIGITAL: list[str] = [
    "TouchSurgery",           # Digital Surgery Platform
]

# ======================================================================
# Hands-on Modell (Feld-Begleitung nach Schulung)
# ======================================================================
# Hugo/CAS + Big Capital Repair (L3):
#   → 10 Stunden Hands-on im Feld PFLICHT mit zertifiziertem L3-Techniker
#   → Erst danach eigenstaendig einsetzbar
# PM Level (L1→L2):
#   → Hands-on NUR waehrend der Schulung selbst
#   → Kein zusaetzliches Feld-Hands-on noetig
#   → Einige PM-Schulungen: online via Teams moeglich

HANDON_STUNDEN = {
    "REPAIR_L3":  10,    # Hugo/CAS/Big Capital Repair – 10h Pflicht
    "PM_L1_L2":    0,    # Hands-on nur waehrend Schulung
    "PM_ONLINE":   0,    # Teams-Schulung moeglich
}


# Aggregierte Listen fuer schnelles Lookup
TRAININGSCENTER_PFLICHT: list[str] = (
    BIG_CAPITAL_CLUSTER1_OR
    + BIG_CAPITAL_CLUSTER2_CARDIAC
    + CLUSTER3_MONITORING
)

INTERN_MOEGLICH: list[str] = (
    SMALL_CAPITAL
    + SMALL_CAPITAL_MIT_REPAIR
    + CLUSTER4_DIGITAL
)

# Alle Familien die bei STK L2 erlauben (fuer scoring.py)
STK_L2_ERLAUBT: list[str] = (
    SMALL_CAPITAL
    + SMALL_CAPITAL_MIT_REPAIR  # HF_Chirurgie: STK+PM = L2
    + CLUSTER3_MONITORING       # Monitoring: STK = L2
)

# Hugo Key Account Familien
HUGO_KEY_ACCOUNT_FAMILIEN: list[str] = ["Hugo"]


def produkt_cluster(produktfamilie: str) -> str:
    """Gibt den Cluster-Namen fuer eine Produktfamilie zurueck."""
    if produktfamilie in BIG_CAPITAL_CLUSTER1_OR:
        return "CLUSTER1_OR"
    if produktfamilie in BIG_CAPITAL_CLUSTER2_CARDIAC:
        return "CLUSTER2_CARDIAC"
    if produktfamilie in CLUSTER3_MONITORING:
        return "CLUSTER3_MONITORING"
    if produktfamilie in CLUSTER4_DIGITAL:
        return "CLUSTER4_DIGITAL"
    if produktfamilie in SMALL_CAPITAL_MIT_REPAIR:
        return "SMALL_CAPITAL_MIT_REPAIR"
    return "SMALL_CAPITAL"


def trainingstyp_fuer_familie(produktfamilie: str) -> TrainingsTyp:
    """Gibt den primaeren Trainingstyp fuer eine Produktfamilie zurueck."""
    if produktfamilie in CLUSTER4_DIGITAL:
        return TrainingsTyp.DIGITAL
    if produktfamilie in TRAININGSCENTER_PFLICHT:
        return TrainingsTyp.TRAININGSCENTER
    return TrainingsTyp.INTERN


def mindest_level_fuer(produktfamilie: str, auftragstyp: str) -> int:
    """Gibt das Mindest-Qualifikationslevel (2 oder 3) zurueck.

    Beruecksichtigt Sonderfall HF_Chirurgie:
        STK/PM → L2 reicht, Repair → L3 Pflicht.
    """
    typ = auftragstyp.upper()

    # Small Capital: STK = L2, PM/Repair = L3
    if produktfamilie in SMALL_CAPITAL:
        return 2 if typ == "STK" else 3

    # HF_Chirurgie Sonderfall: STK+PM = L2, Repair = L3
    if produktfamilie in SMALL_CAPITAL_MIT_REPAIR:
        return 2 if typ in ("STK", "PM") else 3

    # Cluster 3 Monitoring: STK = L2, PM+Repair = L3
    if produktfamilie in CLUSTER3_MONITORING:
        return 2 if typ == "STK" else 3

    # Cluster 4 Digital: immer L2
    if produktfamilie in CLUSTER4_DIGITAL:
        return 2

    # Big Capital (Cluster 1+2): immer L3
    return 3


class Qualifikationslevel(IntEnum):
    """Qualifikationslevel eines Technikers fuer eine Geraeteklasse.

    0 – Keine Qualifikation
    1 – In Ausbildung (Crosstraining laeuft)
    2 – Assistenz (nur mit qualifiziertem Kollegen einsetzbar)
    3 – Selbststaendig (vollqualifiziert, allein einsetzbar)
    4 – Trainer (kann andere Techniker schulen)
    """

    KEINE = 0
    IN_AUSBILDUNG = 1
    ASSISTENZ = 2
    SELBSTSTAENDIG = 3
    TRAINER = 4

    def einsetzbar(self) -> bool:
        """True wenn der Techniker den Auftrag selbststaendig ausfuehren kann."""
        return self >= Qualifikationslevel.SELBSTSTAENDIG


class Geraeteklasse(BaseModel):
    """Repraesentiert eine Geraeteklasse im Medtronic-Portfolio."""

    id: str = Field(description="Eindeutiger Bezeichner, z.B. 'CRM_ICD', 'NEUROSTIM_DBS'")
    bezeichnung: str = Field(description="Lesbarer Name, z.B. 'ICD / CRT-D'")
    division: str = Field(description="Medtronic Division, z.B. 'CRM', 'Neuromodulation', 'Diabetes'")

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Geraeteklasse) and self.id == other.id


class Trainingsmatrix(BaseModel):
    """Portfolio-Trainingsmatrix eines Technikers.

    Bildet Geraeteklassen-IDs auf Qualifikationslevel ab.
    Nicht vorhandene Eintraege entsprechen Qualifikationslevel.KEINE.
    """

    qualifikationen: dict[str, Qualifikationslevel] = Field(
        default_factory=dict,
        description="Mapping: Geraeteklasse.id -> Qualifikationslevel",
    )

    def level(self, geraeteklasse_id: str) -> Qualifikationslevel:
        """Gibt den Qualifikationslevel fuer eine Geraeteklasse zurueck."""
        return self.qualifikationen.get(geraeteklasse_id, Qualifikationslevel.KEINE)

    def ist_einsetzbar(self, geraeteklasse_id: str) -> bool:
        """True wenn der Techniker fuer diese Geraeteklasse selbststaendig einsetzbar ist."""
        return self.level(geraeteklasse_id).einsetzbar()

    def qualifizierte_klassen(self) -> list[str]:
        """Gibt alle Geraeteklassen-IDs zurueck, fuer die der Techniker einsetzbar ist."""
        return [gk_id for gk_id, level in self.qualifikationen.items() if level.einsetzbar()]


class Auslastung(BaseModel):
    """Aktuelle Kapazitaetssituation eines Technikers."""

    kapazitaet_stunden: float = Field(gt=0, description="Verfuegbare Arbeitsstunden im Planungszeitraum")
    geplante_stunden: float = Field(ge=0, description="Bereits verplante Stunden")

    @model_validator(mode="after")
    def geplante_nicht_groesser_als_kapazitaet(self) -> Auslastung:
        if self.geplante_stunden > self.kapazitaet_stunden:
            raise ValueError(
                f"Geplante Stunden ({self.geplante_stunden}) "
                f"uebersteigen Kapazitaet ({self.kapazitaet_stunden})"
            )
        return self

    @property
    def auslastungsgrad(self) -> float:
        """Auslastungsgrad als Wert zwischen 0.0 und 1.0."""
        return self.geplante_stunden / self.kapazitaet_stunden

    @property
    def freie_stunden(self) -> float:
        return self.kapazitaet_stunden - self.geplante_stunden


class Techniker(BaseModel):
    """Repraesentiert einen Aussendienst-Servicetechniker."""

    smax_id: str = Field(description="ServiceMax-ID des Technikers")
    name: str
    email: Optional[str] = None

    # Einsatzgebiet: Liste von PLZ-Praefixen (z.B. ["80", "81", "82"] fuer Muenchen-Bereich)
    # oder vollstaendige PLZ. Leerlist = bundesweit einsetzbar.
    einsatzgebiet_plz: list[str] = Field(
        default_factory=list,
        description="PLZ-Praefixe oder vollstaendige PLZ des Einsatzgebiets",
    )
    heimatort_plz: Optional[str] = Field(
        default=None,
        description="PLZ des Heimatorts / Startpunkts fuer Fahrzeitberechnung",
    )

    techniker_typ: TechnikerTyp = Field(default=TechnikerTyp.STANDARD)
    trainingsmatrix: Trainingsmatrix = Field(default_factory=Trainingsmatrix)
    auslastung: Optional[Auslastung] = None

    @property
    def ist_hugo_key_account(self) -> bool:
        return self.techniker_typ == TechnikerTyp.HUGO_KEY_ACCOUNT

    def ist_einsetzbar_fuer(self, geraeteklasse_id: str) -> bool:
        return self.trainingsmatrix.ist_einsetzbar(geraeteklasse_id)

    def ist_im_einsatzgebiet(self, auftrag_plz: str) -> bool:
        """Prueft ob eine Auftrags-PLZ im Einsatzgebiet liegt.

        Einsatzgebiet ist definiert durch PLZ-Praefixe:
        '80' matcht '80331', '80333', '80335' usw.
        Leeres Einsatzgebiet bedeutet bundesweit einsetzbar.
        """
        if not self.einsatzgebiet_plz:
            return True
        return any(auftrag_plz.startswith(praefix) for praefix in self.einsatzgebiet_plz)
