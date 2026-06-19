"""Zentrale Konfiguration fuer FieldServiceAI.

Alle geschaeftsrelevanten Schwellwerte und Gewichtungen an einer Stelle.
Module importieren aus config.py statt eigene Konstanten zu definieren.
"""

# ─── Scoring ───────────────────────────────────────
SCORING_KOMPETENZ = 0.40
SCORING_FAHRZEIT = 0.35
SCORING_AUSLASTUNG = 0.25
HAVERSINE_UMWEG_FAKTOR = 1.35  # Luftlinie → Fahrtstrecke

# ─── Arbeitszeit ───────────────────────────────────
ARBZG_MAX_STUNDEN = 45          # gesetzliches Maximum
AUSSENDIENST_STUNDEN = 32       # Mo-Do Ziel
FREITAG_NUR_HOME_OFFICE = True
WARNUNG_STUNDEN = 34            # Gelb-Schwelle
AUSSCHLUSS_STUNDEN = 36         # Ausschluss Aussendienst

# ─── Hugo Key Account ──────────────────────────────
HUGO_KA_FAKTOR = 0.80           # 80% = 25.6h/Woche
HUGO_KA_ZIEL_STUNDEN = 25.6
HUGO_KA_RESERVE_PROZENT = 0.20  # 20% fuer Hugo-Calls
HUGO_EINSATZ_STUNDEN = 8.0      # Ganztag
HUGO_KA_IDS = ["T1", "T6", "T10", "T11"]
HUGO_EINSATZDAUER_TAGE = 2.5        # typischer Hugo-Mehrtages-Einsatz (2 Naechte)

# ─── Planung STK/PM ────────────────────────────────
PLANUNGSHORIZONT_TAGE = 7
PLANUNGSHORIZONT_MIN = 3         # Mindestvorlauf Werktage
VORLAUF_STANDARD_TAGE = 5        # Optimal
TERMINVORSCHLAEGE_ANZAHL = 3
OP_KLINIK_MAX_WOCHENTAG = 3      # letzter erlaubter Wochentag (Do=3)
OP_KLINIK_TAGE = [0, 1, 2, 3]   # Mo=0 bis Do=3 (Fr gesperrt)

# ─── Repair SLA ────────────────────────────────────
REPAIR_SLA_STUNDEN = 48          # Kundenkontakt Pflicht
REPAIR_ZIEL_STUNDEN = 24         # intern anstreben
REPAIR_WARNUNG_STUNDEN = 40      # Gelb-Alert
REPAIR_ESKALATION_STUNDEN = 48   # Rot-Alert + Disponent

# ─── Ersatzteile ───────────────────────────────────
ERSATZTEIL_SOFORT_TAGE = 2       # Im Fahrzeug vorhanden
ERSATZTEIL_LAGER_TAGE = 3        # Zentrallager
ERSATZTEIL_BESTELL_TAGE = 10     # Externe Bestellung

# ─── Tour-Optimierung ──────────────────────────────
MAX_EINSATZ_STUNDEN = 6.0
SYNERGIEEFFEKT_FAKTOR = 0.70     # 2. Geraet gleiche Familie
RUESTZEIT_MINUTEN = 30           # Zwischen Familien
MAX_UEBERNACHTUNGEN_WOCHE = 1               # Standard / Prioritaet 1
MAX_UEBERNACHTUNGEN_WOCHE_AUSNAHME = 2      # Wirtschaftliche Ausnahme
MAX_UEBERNACHTUNGEN_HUGO = 3                # Hugo/Big Capital Mehrtages-Einsatz
UEBERNACHTUNG_KOSTEN_EUR = 150
UEBERNACHTUNG_TRIGGER_H = 3.0
LETZTER_AUSSENEINSATZ_WOCHENTAG = 3         # Donnerstag (Mo=0)
KEIN_WOCHENENDEINSATZ = True

# ─── Planungshorizont (Wochen) ─────────────────────
PLANUNGSHORIZONT_WOCHEN = 6
PLANUNGSHORIZONT_MIN_WOCHEN = 4
PLANUNGSHORIZONT_MAX_WOCHEN = 8

# ─── Umplanungs-Prioritaeten ───────────────────────
UMPLANUNGS_PRIORITAETEN = {
    'REPAIR_OHNE_ET':      1,
    'REPAIR_MIT_ET':       2,
    'STK_PM_UEBERFAELLIG': 3,
    'STK_PM_AUF_ROUTE':    4,
    'STK_PM_NORMAL':       5,
}

# ─── STK/PM Fälligkeit monatsgenau (wie TÜV) ──────
STK_PM_FAELLIGKEIT_MONATSGENAU = True
STK_PM_TOLERANZ_TAGE_VOR = 0
STK_PM_TOLERANZ_TAGE_NACH = 0
STK_PM_AUSNAHME_LETZTER_WERKTAG = True    # > 3h einfache Strecke

# ─── STK/PM Wartungszyklen (Monate) ────────────────
STK_PM_ZYKLEN_MONATE = {
    'default':  12,   # alle Produktfamilien
    'PROG':     24,   # Programmer
    'Mazor':     6,   # Mazor
    'Hugo':      6,   # Hugo
}

# ─── Puffer ────────────────────────────────────────
PUFFER_BASIS_MIN = 30
PUFFER_EINSCHLEUSUNG_MIN = 20    # Uniklinikum
PUFFER_GROSSGERAET_MIN = 30      # Hugo, EC300
PUFFER_GESPRAECH_MIN = 15        # Medizintechnik-Gespraech
PUFFER_MESSMITTEL_LADEN = 30     # Vortag (nicht in Einsatz)

# ─── Trainingskosten (Platzhalter) ─────────────────
TRAINING_SMALL_CAPITAL_EUR = 0        # intern
TRAINING_HF_CHIRURGIE_EUR = 0         # STK/PM intern
TRAINING_HF_REPAIR_EUR = None         # T&E anfragen
TRAINING_CLUSTER1_OR_EUR = None       # T&E anfragen
TRAINING_CLUSTER2_CARDIAC_EUR = None  # T&E anfragen
TRAINING_CLUSTER3_MONITOR_EUR = None  # T&E anfragen
TRAINING_CLUSTER4_DIGITAL_EUR = None  # Online/Teams
HANDON_REPAIR_STUNDEN = 10            # Hugo/Big Capital
HANDON_PM_STUNDEN = 0                 # nur waehrend Schulung

# ─── Klinik-Buendelung ─────────────────────────────
BUENDELUNG_RADIUS_KM = 50        # Kliniken in Naehe
BUENDELUNG_GLEICHE_KLINIK = True  # gleiche Klinik = immer

# ─── Kalender (Produktivbetrieb) ───────────────────
SMAX_API_URL = None               # wird konfiguriert
OUTLOOK_GRAPH_API_URL = None      # wird konfiguriert
KALENDER_INTEGRIERT = False       # Prototyp-Flag
