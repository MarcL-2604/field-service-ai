"""Crosstraining-Bedarfsanalyse fuer alle Techniker.

Liest: daten/trainingsmatrix.csv, daten/geraete.csv, daten/techniker.csv, daten/regionen.csv
Schreibt: daten/crosstraining_empfehlungen.csv

Kapazitaetsbasis:
    Freitag = Home Office / Admintag → effektive Außendienst-Tage = Mo-Do = 4 Tage/Woche.
    Jahreskapazitaet je Techniker: 32h/Woche × 46 Arbeitswochen = 1.472 Außendienststunden/Jahr.
    Bei durchschnittlich 4h pro STK-Einsatz: max. ~368 STK-Einsaetze/Jahr pro Techniker.
    Das Feld 'potentielles_zusatz_stk_pa' gibt STK-Einsaetze/Jahr an (nicht Stunden).
    Zur Stunden-Umrechnung: STK-Einsaetze × 4h = Stunden/Jahr.

Kostenmodell Crosstraining:
    INTERN_L2:       0 EUR (Trainer-Zeit bereits einkalkuliert)
    TRAININGSCENTER: ~2.500-3.200 EUR (Kursgebuehr + Reise/Hotel + Ausfall)
    HANDON_FELD:     ~450-900 EUR (5-10 Einsaetze × 2h × 45 EUR/h Begleitzeit)
"""

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from techniker.models import (  # noqa: E402
    TrainingsTyp,
    trainingstyp_fuer_familie,
    produkt_cluster,
)
from config import (  # noqa: E402
    TRAINING_SMALL_CAPITAL_EUR,
    TRAINING_HF_CHIRURGIE_EUR,
    TRAINING_HF_REPAIR_EUR,
    TRAINING_CLUSTER1_OR_EUR,
    TRAINING_CLUSTER2_CARDIAC_EUR,
    TRAINING_CLUSTER3_MONITOR_EUR,
    TRAINING_CLUSTER4_DIGITAL_EUR,
    HANDON_REPAIR_STUNDEN,
    HANDON_PM_STUNDEN,
    HUGO_KA_IDS,
)

BASE = _ROOT / "daten"

# ---------------------------------------------------------------------------
# Mapping: geraete.csv produkt_familie -> trainingsmatrix.csv produktfamilie
# HF_Chirurgie = Hochfrequenzchirurgie = Elektrochirurgie
# NIM          = Nerve Integrity Monitor = Neuromonitoring
# O_arm        = intraoperative Bildgebung / Navigation
# Ablation_HF + Ablation_RF + Cryo = Kardiovaskulaer_Ablation
# IPC + Schrittmacher_Prog + AEX + ACT = Kardiovaskulaer (Programmierung/Monitoring)
# ---------------------------------------------------------------------------
GERAET_ZU_TRAINING = {
    "Hugo":             "Hugo",
    "Beatmung":         "Beatmung",
    "Neurophysiologie": "Neurophysiologie",
    "HF_Chirurgie":     "Elektrochirurgie",
    "NIM":              "Neuromonitoring",
    "O_arm":            "Navigation",
    "Gastro_Manometrie": "Gastroenterologie",
    "Gastro_Endoskopie": "Endoskopie",
    "Ablation_HF":      "Kardiovaskulaer_Ablation",
    "Ablation_RF":      "Kardiovaskulaer_Ablation",
    "Cryo":             "Kardiovaskulaer_Ablation",
    "IPC":              "Kardiovaskulaer",
    "Schrittmacher_Prog": "Kardiovaskulaer",
    "AEX":              "Kardiovaskulaer",
    "ACT":              "Kardiovaskulaer",
}

# ---------------------------------------------------------------------------
# Mapping: kliniken.csv region-Code -> Bundeslaender-Liste
# Einsatzgebiete in regionen.csv sind als Bundeslaender-Namen gespeichert
# ---------------------------------------------------------------------------
REGION_ZU_BL = {
    "Nord":           {"Hamburg", "Schleswig-Holstein", "Mecklenburg-Vorpommern"},
    "Niedersachsen":  {"Niedersachsen", "Bremen"},
    "NRW":            {"Nordrhein-Westfalen"},
    "Hessen":         {"Hessen"},
    "Rheinland-Pfalz": {"Rheinland-Pfalz"},
    "Saarland":       {"Saarland"},
    "BaWü":           {"Baden-Württemberg"},
    "Bayern":         {"Bayern"},
    "Berlin":         {"Berlin"},
    "Brandenburg":    {"Brandenburg"},
    "Sachsen":        {"Sachsen"},
    "Sachsen-Anhalt": {"Sachsen-Anhalt"},
    "Thüringen":      {"Thüringen"},
}

# Einfache Stadtname-Schluesselbegriffe -> Bundeslaender
# Wird fuer Kliniken genutzt, die nicht in kliniken.csv stehen
STADT_ZU_BL = {
    "hamburg":          "Hamburg",
    "luebeck":          "Schleswig-Holstein",
    "lübeck":           "Schleswig-Holstein",
    "kiel":             "Schleswig-Holstein",
    "schleswig":        "Schleswig-Holstein",
    "schwerin":         "Mecklenburg-Vorpommern",
    "rostock":          "Mecklenburg-Vorpommern",
    "greifswald":       "Mecklenburg-Vorpommern",
    "neubrandenburg":   "Mecklenburg-Vorpommern",
    "hannover":         "Niedersachsen",
    "braunschweig":     "Niedersachsen",
    "oldenburg":        "Niedersachsen",
    "osnabrueck":       "Niedersachsen",
    "osnabrück":        "Niedersachsen",
    "goettingen":       "Niedersachsen",
    "göttingen":        "Niedersachsen",
    "bremen":           "Niedersachsen",
    "dortmund":         "Nordrhein-Westfalen",
    "koeln":            "Nordrhein-Westfalen",
    "köln":             "Nordrhein-Westfalen",
    "duesseldorf":      "Nordrhein-Westfalen",
    "düsseldorf":       "Nordrhein-Westfalen",
    "essen":            "Nordrhein-Westfalen",
    "bochum":           "Nordrhein-Westfalen",
    "muenster":         "Nordrhein-Westfalen",
    "münster":          "Nordrhein-Westfalen",
    "aachen":           "Nordrhein-Westfalen",
    "bonn":             "Nordrhein-Westfalen",
    "wuppertal":        "Nordrhein-Westfalen",
    "bielefeld":        "Nordrhein-Westfalen",
    "duisburg":         "Nordrhein-Westfalen",
    "solingen":         "Nordrhein-Westfalen",
    "velbert":          "Nordrhein-Westfalen",
    "neuss":            "Nordrhein-Westfalen",
    "hamm":             "Nordrhein-Westfalen",
    "guetersloh":       "Nordrhein-Westfalen",
    "meckenheim":       "Nordrhein-Westfalen",
    "hennef":           "Nordrhein-Westfalen",
    "gangelt":          "Nordrhein-Westfalen",
    "frankfurt":        "Hessen",
    "giessen":          "Hessen",
    "gießen":           "Hessen",
    "wiesbaden":        "Hessen",
    "kassel":           "Hessen",
    "fulda":            "Hessen",
    "darmstadt":        "Hessen",
    "obertshausen":     "Hessen",
    "mainz":            "Rheinland-Pfalz",
    "koblenz":          "Rheinland-Pfalz",
    "ludwigshafen":     "Rheinland-Pfalz",
    "kaiserslautern":   "Rheinland-Pfalz",
    "trier":            "Rheinland-Pfalz",
    "worms":            "Rheinland-Pfalz",
    "bad duerkheim":    "Rheinland-Pfalz",
    "saarbruecken":     "Saarland",
    "saarbrücken":      "Saarland",
    "homburg":          "Saarland",
    "heidelberg":       "Baden-Württemberg",
    "freiburg":         "Baden-Württemberg",
    "tuebingen":        "Baden-Württemberg",
    "tübingen":         "Baden-Württemberg",
    "ulm":              "Baden-Württemberg",
    "stuttgart":        "Baden-Württemberg",
    "karlsruhe":        "Baden-Württemberg",
    "heilbronn":        "Baden-Württemberg",
    "konstanz":         "Baden-Württemberg",
    "villingen":        "Baden-Württemberg",
    "schwenningen":     "Baden-Württemberg",
    "friedrichshafen":  "Baden-Württemberg",
    "offenburg":        "Baden-Württemberg",
    "winnenden":        "Baden-Württemberg",
    "balingen":         "Baden-Württemberg",
    "waldachtal":       "Baden-Württemberg",
    "muenchen":         "Bayern",
    "münchen":          "Bayern",
    "nuernberg":        "Bayern",
    "nürnberg":         "Bayern",
    "erlangen":         "Bayern",
    "augsburg":         "Bayern",
    "wuerzburg":        "Bayern",
    "würzburg":         "Bayern",
    "regensburg":       "Bayern",
    "ingolstadt":       "Bayern",
    "bayreuth":         "Bayern",
    "bamberg":          "Bayern",
    "rosenheim":        "Bayern",
    "landshut":         "Bayern",
    "dachau":           "Bayern",
    "kaufbeuren":       "Bayern",
    "deggendorf":       "Bayern",
    "dorfen":           "Bayern",
    "aschaffenburg":    "Bayern",
    "wildenberg":       "Bayern",
    "wehingen":         "Baden-Württemberg",
    "berlin":           "Berlin",
    "potsdam":          "Brandenburg",
    "cottbus":          "Brandenburg",
    "barnim":           "Brandenburg",
    "dresden":          "Sachsen",
    "leipzig":          "Sachsen",
    "chemnitz":         "Sachsen",
    "bautzen":          "Sachsen",
    "halle":            "Sachsen-Anhalt",
    "magdeburg":        "Sachsen-Anhalt",
    "aschersleben":     "Sachsen-Anhalt",
    "nordhausen":       "Thüringen",
    "erfurt":           "Thüringen",
    "jena":             "Thüringen",
    "suhl":             "Thüringen",
    "eisenach":         "Thüringen",
    "weimar":           "Thüringen",
    "wels":             None,   # Oesterreich, ignorieren
}


# ---------------------------------------------------------------------------
# Kostenmodell Crosstraining
# ---------------------------------------------------------------------------

# =========================================================================
# Trainingskosten – PLATZHALTER
# Genaue Kosten bitte bei Medtronic Training & Education (T&E) anfragen.
# Die Euro-Betraege unten sind NICHT VALIDIERT und dienen nur als
# Strukturvorlage fuer die Kostenberechnung.
# =========================================================================

# Kosten pro Schulungstyp (EUR) – aus config.py
KOSTEN_INTERN = TRAINING_SMALL_CAPITAL_EUR
KOSTEN_HF_CHIRURGIE_STK_PM = TRAINING_HF_CHIRURGIE_EUR

# PLATZHALTER – bei T&E anfragen (None in config.py → "PLATZHALTER" hier)
KOSTEN_TC_OR = "PLATZHALTER" if TRAINING_CLUSTER1_OR_EUR is None else TRAINING_CLUSTER1_OR_EUR
KOSTEN_TC_CARDIAC = "PLATZHALTER" if TRAINING_CLUSTER2_CARDIAC_EUR is None else TRAINING_CLUSTER2_CARDIAC_EUR
KOSTEN_TC_MONITORING = "PLATZHALTER" if TRAINING_CLUSTER3_MONITOR_EUR is None else TRAINING_CLUSTER3_MONITOR_EUR
KOSTEN_TC_REPAIR_HF = "PLATZHALTER" if TRAINING_HF_REPAIR_EUR is None else TRAINING_HF_REPAIR_EUR
KOSTEN_DIGITAL = "PLATZHALTER" if TRAINING_CLUSTER4_DIGITAL_EUR is None else TRAINING_CLUSTER4_DIGITAL_EUR

# Hands-on Modell (validiert)
# Repair L3 (Hugo/CAS/Big Capital): 10h Feld-Hands-on mit L3-Techniker PFLICHT
# PM L1→L2: Hands-on NUR waehrend Schulung, kein zusaetzliches Feld-Hands-on
# PM online: einige PM-Schulungen via Teams moeglich
HANDON_STUNDEN_REPAIR_L3 = HANDON_REPAIR_STUNDEN
HANDON_STUNDEN_PM = HANDON_PM_STUNDEN

# Legacy: Handon-Einsaetze (PLATZHALTER fuer Kostenrechnung)
KOSTEN_HANDON_PRO_EINSATZ = 90        # 2h × 45 EUR/h (PLATZHALTER)
HANDON_EINSAETZE_OR = 10              # Cluster 1 – validiert: 10h Pflicht
HANDON_EINSAETZE_CARDIAC = 8          # Cluster 2 – PLATZHALTER
HANDON_EINSAETZE_MONITORING = 6       # Cluster 3 – PLATZHALTER
HANDON_EINSAETZE_HF_REPAIR = 5       # HF_Chirurgie Repair – PLATZHALTER

# Rueckwaertskompatible Aliase (PLATZHALTER)
KOSTEN_INTERN_L2 = KOSTEN_INTERN
KOSTEN_TRAININGSCENTER_MIN = "PLATZHALTER"
KOSTEN_TRAININGSCENTER_MAX = "PLATZHALTER"
KOSTEN_TRAININGSCENTER_MITTEL = "PLATZHALTER"
KOSTEN_HANDON_MIN = KOSTEN_HANDON_PRO_EINSATZ * HANDON_EINSAETZE_MONITORING
KOSTEN_HANDON_MAX = KOSTEN_HANDON_PRO_EINSATZ * HANDON_EINSAETZE_OR
KOSTEN_HANDON_MITTEL = KOSTEN_HANDON_PRO_EINSATZ * HANDON_EINSAETZE_CARDIAC

# Dauer bis eigenstaendig einsetzbar
DAUER_INTERN_TAGE = 2
DAUER_INTERN_BEGLEIT_EINSAETZE = 4
DAUER_TRAININGSCENTER_TAGE = 5
DAUER_HANDON_EINSAETZE_MIN = HANDON_EINSAETZE_MONITORING
DAUER_HANDON_EINSAETZE_MAX = HANDON_EINSAETZE_OR
DAUER_HANDON_EINSAETZE_MITTEL = HANDON_EINSAETZE_CARDIAC


def _cluster_kosten(produktfamilie: str) -> tuple[str | int, int, str | int]:
    """Gibt (kurskosten, handon_einsaetze, handon_kosten) fuer eine Produktfamilie.

    Kurskosten: int (0) fuer intern, "PLATZHALTER" fuer T&E-pflichtige Cluster.
    """
    cluster = produkt_cluster(produktfamilie)
    if cluster == "CLUSTER1_OR":
        return "PLATZHALTER", HANDON_EINSAETZE_OR, "PLATZHALTER"
    if cluster == "CLUSTER2_CARDIAC":
        return "PLATZHALTER", HANDON_EINSAETZE_CARDIAC, "PLATZHALTER"
    if cluster == "CLUSTER3_MONITORING":
        return "PLATZHALTER", HANDON_EINSAETZE_MONITORING, "PLATZHALTER"
    if cluster == "SMALL_CAPITAL_MIT_REPAIR":
        # HF_Chirurgie: STK/PM = intern 0 EUR, Repair = T&E anfragen
        return "PLATZHALTER", HANDON_EINSAETZE_HF_REPAIR, "PLATZHALTER"
    if cluster == "CLUSTER4_DIGITAL":
        return "PLATZHALTER", 0, 0
    # SMALL_CAPITAL
    return KOSTEN_INTERN, 0, 0


def berechne_schulungsdetails(
    produktfamilie: str,
    techniker_id: str,
    alle_qualifikationen: dict[str, dict[str, str]],
    alle_regionen: dict[str, set[str]],
    techniker_bls: set[str],
) -> dict:
    """Berechnet Trainingstyp, Kosten, Dauer und Trainer fuer eine Schulungsempfehlung.

    Beruecksichtigt Cluster-spezifische Kosten und Handon-Einsaetze.
    """
    typ = trainingstyp_fuer_familie(produktfamilie)
    cluster = produkt_cluster(produktfamilie)
    kurskosten, handon_n, handon_kosten = _cluster_kosten(produktfamilie)

    # Finde L3+ oder L4 Trainer fuer diese Familie
    trainer_id = ""
    for other_id, qualis in alle_qualifikationen.items():
        if other_id == techniker_id:
            continue
        level_str = qualis.get(produktfamilie, "L0")
        level_num = int(level_str[1]) if re.match(r"L\d", level_str) else 0
        if level_num < 3:
            continue
        other_bls = bundeslaender_fuer_techniker(other_id, alle_regionen)
        if other_bls & techniker_bls:
            trainer_id = other_id
            if level_num >= 4:
                break  # Bevorzuge L4 Trainer

    if typ == TrainingsTyp.INTERN:
        return {
            "trainingstyp": "INTERN",
            "trainingstyp_label": "Intern (Feld-Schulung)",
            "cluster": cluster,
            "kosten_eur": 0,
            "kosten_text": "intern, 0 EUR",
            "dauer_text": (
                f"{DAUER_INTERN_TAGE} Tage + "
                f"{DAUER_INTERN_BEGLEIT_EINSAETZE} begleitete Einsaetze"
            ),
            "trainer_id": trainer_id,
            "handon_begleiter": trainer_id,
            "eigenstaendig_ab": "~2-3 Monate",
        }
    elif typ == TrainingsTyp.DIGITAL:
        return {
            "trainingstyp": "DIGITAL",
            "trainingstyp_label": "Online/Teams moeglich",
            "cluster": cluster,
            "kosten_eur": "PLATZHALTER",
            "kosten_text": "Online/Teams moeglich (Kosten: T&E anfragen)",
            "dauer_text": "Online-Kurs, selbstbestimmt",
            "trainer_id": "",
            "handon_begleiter": "",
            "eigenstaendig_ab": "~1-2 Wochen",
        }
    else:
        # Trainingscenter + Handon – Kosten sind PLATZHALTER
        handon_info = f"{handon_n}h Handon Pflicht" if handon_n else ""
        return {
            "trainingstyp": "TRAININGSCENTER + HANDON",
            "trainingstyp_label": f"Trainingscenter ({cluster})",
            "cluster": cluster,
            "kosten_eur": "PLATZHALTER",
            "kosten_text": (
                f"{handon_info} + Kosten: T&E anfragen"
                if handon_info
                else "Kosten: T&E anfragen"
            ),
            "dauer_text": (
                f"{DAUER_TRAININGSCENTER_TAGE} Tage Kurs + "
                f"{handon_n} begleitete Einsaetze"
            ),
            "trainer_id": trainer_id,
            "handon_begleiter": trainer_id,
            "eigenstaendig_ab": "~6-9 Monate",
        }


def normalize(text: str) -> str:
    """Lowercase und Umlaute umwandeln fuer einfachen Vergleich."""
    return (text.lower()
            .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
            .replace("ß", "ss"))


def klinik_zu_bundesland(klinikname: str, klinik_bl_map: dict[str, str]) -> str | None:
    """Versucht Bundesland ueber direktes Mapping, dann Stadtname-Heuristik."""
    n = normalize(klinikname)

    # 1) Direktes Mapping aus kliniken.csv
    if n in klinik_bl_map:
        return klinik_bl_map[n]

    # 2) Teilstring-Match gegen klinik_bl_map
    for kn, bl in klinik_bl_map.items():
        if kn in n or n in kn:
            return bl

    # 3) Stadtname-Heuristik
    for stadt, bl in STADT_ZU_BL.items():
        if stadt in n:
            return bl

    return None


def stk_pro_jahr(anzahl: int, zyklus_jahre: int) -> float:
    """Jaehrliches STK-Volumen fuer ein Geraet."""
    return anzahl / max(zyklus_jahre, 1)


def load_trainingsmatrix() -> dict[str, dict[str, str]]:
    """Gibt {techniker_id: {produktfamilie: level}} zurueck."""
    matrix: dict[str, dict[str, str]] = defaultdict(dict)
    with open(BASE / "trainingsmatrix.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            matrix[row["techniker_id"]][row["produktfamilie"]] = row["level"]
    return dict(matrix)


def load_regionen() -> dict[str, set[str]]:
    """Gibt {techniker_id: {bundesland, ...}} zurueck."""
    regionen: dict[str, set[str]] = {}
    with open(BASE / "regionen.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            bls = {bl.strip() for bl in row["einsatzgebiet"].split(";") if bl.strip()}
            regionen[row["techniker_id"]] = bls
    return regionen


def load_klinik_bl_map() -> dict[str, str]:
    """Normalized klinik_name -> Bundesland aus kliniken.csv."""
    region_zu_bl_flat = {}
    for region, bls in REGION_ZU_BL.items():
        for bl in bls:
            region_zu_bl_flat[region] = bl  # nimm ersten BL als Repraesentant
    # Besser: direktes Mapping Region-Code -> Bundesland (erster Eintrag genuegt
    # da NRW,Bayern usw. nur ein Bundesland haben; Nord wird Hamburg als Primary)
    region_primary = {
        "Nord": "Hamburg",
        "Niedersachsen": "Niedersachsen",
        "NRW": "Nordrhein-Westfalen",
        "Hessen": "Hessen",
        "Rheinland-Pfalz": "Rheinland-Pfalz",
        "Saarland": "Saarland",
        "BaWü": "Baden-Württemberg",
        "Bayern": "Bayern",
        "Berlin": "Berlin",
        "Brandenburg": "Brandenburg",
        "Sachsen": "Sachsen",
        "Sachsen-Anhalt": "Sachsen-Anhalt",
        "Thüringen": "Thüringen",
    }

    result: dict[str, str] = {}
    with open(BASE / "kliniken.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            bl = region_primary.get(row["region"])
            if bl:
                result[normalize(row["name"])] = bl
    return result


def load_geraete(klinik_bl_map: dict[str, str]) -> dict[str, dict[str, float]]:
    """
    Gibt {bundesland: {training_produktfamilie: stk_pa}} zurueck.
    Linien mit '#' werden uebersprungen.
    """
    bl_volumen: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    with open(BASE / "geraete.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(
            (line for line in f if not line.strip().startswith("#"))
        )
        for row in reader:
            klinik = row["klinik_name"].strip()
            produkt = row["produkt_familie"].strip()
            try:
                anzahl = int(row["anzahl"])
                zyklus = int(row["stk_zyklus_jahre"])
            except ValueError:
                continue

            training_produkt = GERAET_ZU_TRAINING.get(produkt)
            if training_produkt is None:
                continue  # unbekannte Familie -> ignorieren

            bl = klinik_zu_bundesland(klinik, klinik_bl_map)
            if bl is None:
                continue  # kein Bundesland bestimmbar

            bl_volumen[bl][training_produkt] += stk_pro_jahr(anzahl, zyklus)

    return {bl: dict(pf) for bl, pf in bl_volumen.items()}


def bundeslaender_fuer_techniker(
    tid: str,
    regionen: dict[str, set[str]],
) -> set[str]:
    """Gibt alle Bundeslaender zurueck, die im Einsatzgebiet des Technikers liegen."""
    einsatz_bls = regionen.get(tid, set())
    result: set[str] = set()
    for ebl in einsatz_bls:
        # Einsatzgebiete koennen direkte BL-Namen oder Regionen sein
        if ebl in REGION_ZU_BL:
            result |= REGION_ZU_BL[ebl]
        else:
            result.add(ebl)
    return result


def regionales_volumen(
    techniker_bls: set[str],
    bl_volumen: dict[str, dict[str, float]],
) -> dict[str, float]:
    """Summiert STK-Volumen ueber alle Bundeslaender im Einsatzgebiet."""
    gesamt: dict[str, float] = defaultdict(float)
    for bl in techniker_bls:
        for pf, vol in bl_volumen.get(bl, {}).items():
            gesamt[pf] += vol
    return dict(gesamt)


def fehlende_familien(
    qualifikationen: dict[str, str],
    reg_volumen: dict[str, float],
    min_level: int = 3,
) -> list[str]:
    """
    Produktfamilien, die in der Region vorhanden sind,
    aber der Techniker (noch) nicht auf Level >= min_level qualifiziert ist.
    """
    fehlend = []
    for pf in sorted(reg_volumen):
        level_str = qualifikationen.get(pf, "L0")
        level_num = int(level_str[1]) if re.match(r"L\d", level_str) else 0
        if level_num < min_level:
            fehlend.append(pf)
    return fehlend


def bester_crosstraining_partner(
    tid: str,
    fehlende_pf: list[str],
    alle_qualifikationen: dict[str, dict[str, str]],
    alle_regionen: dict[str, set[str]],
    techniker_bls: set[str],
) -> str:
    """
    Findet den Techniker mit den meisten L3+-Qualifikationen fuer die fehlenden
    Produktfamilien UND einem ueberlappenden Einsatzgebiet.
    Gibt techniker_id zurueck oder '' falls keiner gefunden.
    """
    scores: dict[str, int] = defaultdict(int)
    for other_id, qualis in alle_qualifikationen.items():
        if other_id == tid:
            continue
        other_bls = bundeslaender_fuer_techniker(other_id, alle_regionen)
        overlap = techniker_bls & other_bls
        if not overlap:
            continue
        for pf in fehlende_pf:
            level_str = qualis.get(pf, "L0")
            level_num = int(level_str[1]) if re.match(r"L\d", level_str) else 0
            if level_num >= 3:
                scores[other_id] += 1

    if not scores:
        return ""
    return max(scores, key=lambda x: scores[x])


def main() -> None:
    print("Lade Daten...")
    qualifikationen = load_trainingsmatrix()
    regionen_map = load_regionen()
    klinik_bl_map = load_klinik_bl_map()
    bl_volumen = load_geraete(klinik_bl_map)

    # Alle Techniker-IDs aus trainingsmatrix (T1..T14)
    alle_ids = sorted(qualifikationen.keys(), key=lambda x: int(x[1:]))

    ergebnisse = []

    for tid in alle_ids:
        qualis = qualifikationen[tid]
        tech_bls = bundeslaender_fuer_techniker(tid, regionen_map)
        reg_vol = regionales_volumen(tech_bls, bl_volumen)

        # Fehlende Familien (nicht L3+)
        fehlend = fehlende_familien(qualis, reg_vol)

        # Potentielles Zusatz-STK-Volumen durch Crosstraining
        zusatz_stk = sum(reg_vol[pf] for pf in fehlend)

        # Crosstraining-Partner
        partner = bester_crosstraining_partner(
            tid, fehlend, qualifikationen, regionen_map, tech_bls
        )

        # Aktuelle qualifizierte Familien (L3+)
        qualifiziert = [
            pf for pf, lv in qualis.items()
            if re.match(r"L\d", lv) and int(lv[1]) >= 3
        ]

        # Schulungsdetails fuer die Top-Luecke (groesstes STK-Volumen)
        top_schulung = {}
        if fehlend:
            top_pf = max(fehlend, key=lambda pf: reg_vol.get(pf, 0))
            top_schulung = berechne_schulungsdetails(
                top_pf, tid, qualifikationen, regionen_map, tech_bls,
            )

        # Gesamtkosten: PLATZHALTER wenn mind. 1 Cluster T&E-pflichtig
        gesamt_kosten: int | str = 0
        for pf in fehlend:
            kk, _, hk = _cluster_kosten(pf)
            if kk == "PLATZHALTER" or hk == "PLATZHALTER":
                gesamt_kosten = "PLATZHALTER"
                break
            gesamt_kosten += kk + hk

        ergebnisse.append({
            "techniker_id": tid,
            "einsatzgebiet_bundeslaender": ";".join(sorted(tech_bls)),
            "qualifizierte_familien_l3plus": ";".join(sorted(qualifiziert)),
            "regionale_produktfamilien": ";".join(sorted(reg_vol.keys())),
            "fehlende_familien": ";".join(fehlend),
            "anzahl_luecken": len(fehlend),
            "potentielles_zusatz_stk_pa": round(zusatz_stk, 1),
            "idealer_crosstraining_partner": partner,
            "top_schulung_typ": top_schulung.get("trainingstyp", ""),
            "top_schulung_kosten": top_schulung.get("kosten_text", ""),
            "top_schulung_dauer": top_schulung.get("dauer_text", ""),
            "top_schulung_trainer": top_schulung.get("trainer_id", ""),
            "geschaetzte_gesamtkosten_eur": gesamt_kosten,
        })

        print(
            f"  {tid}: {len(fehlend)} Luecken, "
            f"+{round(zusatz_stk,1)} STK/a -> Partner: {partner or '–'}"
        )

    out_path = BASE / "crosstraining_empfehlungen.csv"
    fieldnames = [
        "techniker_id",
        "einsatzgebiet_bundeslaender",
        "qualifizierte_familien_l3plus",
        "regionale_produktfamilien",
        "fehlende_familien",
        "anzahl_luecken",
        "potentielles_zusatz_stk_pa",
        "idealer_crosstraining_partner",
        "top_schulung_typ",
        "top_schulung_kosten",
        "top_schulung_dauer",
        "top_schulung_trainer",
        "geschaetzte_gesamtkosten_eur",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(ergebnisse)

    print(f"\nGespeichert: {out_path}")

    # --- Hugo-Crosstraining-Empfehlung ---
    print("\nBerechne Hugo-Crosstraining-Empfehlungen...")
    hugo_empfehlungen = berechne_hugo_crosstraining(
        qualifikationen, regionen_map, bl_volumen,
    )
    hugo_path = BASE / "crosstraining_hugo_empfehlung.csv"
    hugo_fields = [
        "hugo_techniker_id", "standort_region", "hugo_standort",
        "l3_familien", "kapazitaets_warnung",
        "empfohlener_kandidat", "kandidat_l3_familien",
        "kandidat_auslastung_info", "begruendung",
    ]
    with open(hugo_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=hugo_fields)
        writer.writeheader()
        writer.writerows(hugo_empfehlungen)
    print(f"Hugo-Crosstraining gespeichert: {hugo_path}")


# ---------------------------------------------------------------------------
# Hugo-Crosstraining-Bedarfsanalyse
# ---------------------------------------------------------------------------

_HUGO_KEY_ACCOUNTS = {
    tid: info for tid, info in {
        "T1":  {"region": "Hessen", "hugo_standort": "TBD Hessen"},
        "T6":  {"region": "Nord", "hugo_standort": "UKE Hamburg (4 Systeme)"},
        "T10": {"region": "BaWü-Süd", "hugo_standort": "Uniklinikum Ulm (1 System)"},
        "T11": {"region": "NRW-West", "hugo_standort": "Klinikum Bochum (1 System)"},
    }.items() if tid in HUGO_KA_IDS
}

_HUGO_STANDORT_COORDS = {
    "T1":  (50.07, 8.86),   # Obertshausen
    "T6":  (53.60, 9.83),   # Schenefeld / UKE
    "T10": (48.27, 8.85),   # Balingen / Ulm
    "T11": (51.01, 6.00),   # Gangelt / Bochum
}


def _haversine_approx(lat1, lon1, lat2, lon2):
    """Einfache Distanzschaetzung in km."""
    import math
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(min(1.0, math.sqrt(a)))


def berechne_hugo_crosstraining(
    qualifikationen: dict[str, dict[str, str]],
    regionen_map: dict[str, set[str]],
    bl_volumen: dict[str, dict[str, float]],
) -> list[dict]:
    """Berechnet Hugo-Crosstraining-Empfehlungen.

    Kriterien fuer Kandidaten:
    - Bereits L3 in 3+ Familien
    - Geografisch nah an Hugo-Standort
    - Kein bestehender Hugo Key Account
    """
    # Techniker-GPS aus CSV laden
    tech_coords = {}
    with open(BASE / "techniker.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                tech_coords[row["techniker_id"]] = (
                    float(row["lat"]), float(row["lon"]),
                )
            except (ValueError, KeyError):
                pass

    ergebnisse = []
    for hugo_tid, info in sorted(_HUGO_KEY_ACCOUNTS.items()):
        hugo_qualis = qualifikationen.get(hugo_tid, {})
        l3_fam = [pf for pf, lv in hugo_qualis.items()
                   if re.match(r"L\d", lv) and int(lv[1]) >= 3]

        hugo_coord = _HUGO_STANDORT_COORDS.get(hugo_tid)

        # Kandidaten bewerten
        best_tid, best_score, best_reason = "", -1, ""
        for cand_tid, cand_qualis in qualifikationen.items():
            if cand_tid in _HUGO_KEY_ACCOUNTS:
                continue
            cand_l3 = [pf for pf, lv in cand_qualis.items()
                        if re.match(r"L\d", lv) and int(lv[1]) >= 3]
            if len(cand_l3) < 3:
                continue

            # Geografie-Score (naeher = besser)
            geo_score = 0
            cand_coord = tech_coords.get(cand_tid)
            dist_km = 999
            if hugo_coord and cand_coord:
                dist_km = _haversine_approx(
                    hugo_coord[0], hugo_coord[1],
                    cand_coord[0], cand_coord[1],
                )
                geo_score = max(0, 100 - dist_km / 5)

            # Kompetenz-Score
            komp_score = len(cand_l3) * 10

            total = geo_score + komp_score
            if total > best_score:
                best_score = total
                best_tid = cand_tid
                best_reason = (
                    f"{len(cand_l3)} L3-Familien, "
                    f"{dist_km:.0f} km Entfernung"
                )

        cand_l3_str = ""
        if best_tid:
            cand_qualis = qualifikationen.get(best_tid, {})
            cand_l3_str = ";".join(sorted(
                pf for pf, lv in cand_qualis.items()
                if re.match(r"L\d", lv) and int(lv[1]) >= 3
            ))

        ergebnisse.append({
            "hugo_techniker_id": hugo_tid,
            "standort_region": info["region"],
            "hugo_standort": info["hugo_standort"],
            "l3_familien": ";".join(sorted(l3_fam)),
            "kapazitaets_warnung": "Ja" if len(l3_fam) >= 4 else "Nein",
            "empfohlener_kandidat": best_tid,
            "kandidat_l3_familien": cand_l3_str,
            "kandidat_auslastung_info": "Keine Echtzeit-Daten",
            "begruendung": best_reason,
        })

    return ergebnisse


if __name__ == "__main__":
    main()
