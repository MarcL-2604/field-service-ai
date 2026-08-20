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
REPAIR_SLA_STUNDEN = 48          # Kundenkontakt Pflicht (Erstkontakt)
REPAIR_ZIEL_STUNDEN = 24         # intern anstreben
REPAIR_WARNUNG_STUNDEN = 40      # Gelb-Alert
REPAIR_ESKALATION_STUNDEN = 48   # Rot-Alert + Disponent

# Abschluss-Ziele (eigenstaendige Frist, unabhaengig vom 48h-Erstkontakt
# oben): Zeit bis zum tatsaechlichen Auftragsabschluss, exkl. Wartezeit auf
# Ersatzteilbestellung (siehe ERSATZTEIL_*_TAGE).
REPAIR_SLA_VERTRAGSKUNDE_TAGE = 2.5
REPAIR_SLA_NICHT_VERTRAGSKUNDE_TAGE = 3.5

# ─── Auslastungs-Zielkorridor ───────────────────────
# Referenzwert (KEINE harte Regel, keine automatische Zwangs-Umverteilung):
# Anteil echter Vor-Ort-Einsatzstunden/Jahr an der Jahreskapazitaet
# (AUSSENDIENST_STUNDEN bzw. HUGO_KA_ZIEL_STUNDEN x ARBEITSWOCHEN_PRO_JAHR).
# Siehe api/auslastung_analyse.py.
AUSLASTUNG_ZIEL_MIN_PCT = 80
AUSLASTUNG_ZIEL_MAX_PCT = 95

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

# ─── Crosstraining Wirtschaftlichkeit ──────────────
MIN_GERAETE_FUER_CROSSTRAINING = 5      # Mindestanzahl Repair-Geraete der fehlenden Produktfamilie im Gebiet
MIN_STK_POTENZIAL_CROSSTRAINING = 15    # Mindest-STK/Jahr-Potenzial der fehlenden Produktfamilie

# ─── Crosstraining Ausschlussliste ─────────────────
# Produktgruppen, die NIEMALS als Crosstraining-Empfehlung erscheinen sollen --
# Schulung ist zu kostenintensiv/aufwendig, teilweise nur in USA verfuegbar.
# Praefixe matchen gegen die "familie"-Schluessel aus
# api/cluster_mapping.py.finde_repair_familie() (laengster passender MC-Code-
# Praefix, siehe api/smax_cache.py crosstraining_luecken). Werden auch dann
# herausgefiltert, wenn sie wirtschaftlich sinnvoll erscheinen wuerden.
# Platzhalter-Eintraege (noch ohne echten MC-Code) matchen nie ein echtes
# Geraet -- kein Absturz, einfach kein Treffer, bis der echte Code ergaenzt wird.
CROSSTRAINING_AUSGESCHLOSSENE_CLUSTER_PRAEFIXE = [
    "MC-HUGO",                                # Hugo (Robotik)
    "MC-BI70",                                # O-arm (intraoperative Bildgebung/Navigation)
    "CAS-Platzhalter (MC-Code fehlt noch)",   # CAS (Cranial/Spine Navigation)
    "CRYO-Platzhalter (MC-Code fehlt noch)",  # CryoConsole / Arctic Front
]

# ─── Gebietsoptimierung: Algorithmus ───────────────
# Generische Heuristik (ID-unabhaengig): Klinik wandert zum 2.-naechsten
# Techniker, wenn dieser deutlich weniger ausgelastet ist und die
# Fahrzeit-Mehrbelastung vertretbar bleibt.
OPTIMIERUNG_AUSLASTUNGS_SCHWELLE = 15            # Mindest-Auslastungsdifferenz in Prozentpunkten
OPTIMIERUNG_MAX_FAHRZEIT_MEHRAUFWAND_MIN = 20    # max. akzeptierte Fahrzeit-Mehrbelastung (Minuten)
ARBEITSWOCHEN_PRO_JAHR = 46                      # Kapazitaetsbasis fuer Auslastungs-Berechnung

# ─── Gebietsoptimierung: Luecken & Ueberschneidungen (generisch) ───
# Generische Heuristik (ID-unabhaengig, wie oben): pro Bundesland aus den
# echten Klinik-Fahrzeiten abgeleitet statt aus einer festen Techniker-Liste.
LUECKE_FAHRZEIT_SCHWELLE_MIN = 90         # Oe Fahrzeit zum naechsten Techniker > X min = Luecke
UEBERSCHNEIDUNG_FAHRZEIT_DIFF_MIN = 20    # 2.-naechster Techniker <= X min langsamer = kontestiert
UEBERSCHNEIDUNG_ANTEIL_SCHWELLE = 0.30    # Anteil kontestierter Kliniken im Gebiet fuer "Ueberschneidung"

# ─── Hugo-Kerngebiet ────────────────────────────────
# Hugo-Systeme stehen an wenigen, teils weit vom Wohnort des zustaendigen
# Techniker entfernten Standorten (z.B. Ulm/Mannheim ~2,5h von Balingen) --
# diese Entfernung zum Hugo-SYSTEM ist normal und wird nicht begrenzt (siehe
# config_hugo_standorte.HUGO_STANDORTE, manuell gepflegte Zuordnung).
# Begrenzt wird stattdessen das Alltags-Kerngebiet (Small Capital, PM-only)
# um den WOHNORT des Hugo-Technikers: eine Verfuegbarkeits-Garantie, damit er
# taeglich nach Hause zurueckkehrt und bei einer Hugo-Stoerung sein Equipment
# bereits zuhause hat -- keine Entfernungsbegrenzung zum Hugo-System selbst.
# Siehe reporting/hugo_kerngebiet.py.
HUGO_KERNGEBIET_MAX_FAHRZEIT_MIN = 90

# ─── Stundensaetze (Startwerte, anpassbar) ─────────
# Ersetzen die bisherigen "T&E anfragen"-Platzhalter im Business-Case-Tab
# durch konkrete Euro-Betraege. AUSDRUECKLICH SCHAETZWERTE, keine von
# Medtronic T&E bestaetigten Ist-Zahlen -- im Dashboard entsprechend als
# "Startwert, anpassbar" gekennzeichnet (siehe reporting/dashboard.py
# _render_business_case). Bei Bedarf hier zentral anpassen.
TECHNIKER_KOSTENSATZ_EUR_STUNDE = 45.0
# Herleitung (Schaetzung): Marktdurchschnitt Bruttolohn Servicetechniker
# Medizintechnik Deutschland ~24 EUR/h, x Lohnnebenkosten-Faktor ~1,9
# (Arbeitgeberanteile Sozialversicherung, Urlaubs-/Krankheitsruecklage,
# anteilige Fahrzeug-/Ausruestungskosten) = interner Vollkostensatz.
KUNDEN_VERRECHNUNGSSATZ_EUR_STUNDE = 150.0
# Herleitung (Schaetzung): typischer Repair-Erloessatz bei Nicht-
# Vertragskunden (Time-&-Material-Abrechnung) im Medizintechnik-Field-
# Service-Markt Deutschland.

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

# ─── Datenschutz ───────────────────────────────────
PSEUDONYMISIERUNG_AKTIV = False   # False = echte Namen, True = SHA256-Pseudonym

# ─── Kalender (Produktivbetrieb) ───────────────────
SMAX_API_URL = None               # wird konfiguriert
OUTLOOK_GRAPH_API_URL = None      # wird konfiguriert
KALENDER_INTEGRIERT = False       # Prototyp-Flag

# ─── Test-Suite (Dashboard-Footer) ─────────────────
# Manuell bei jedem pytest-Lauf/Release aktualisieren (`pytest --collect-only -q`).
# Einzige Stelle im Code -- dashboard.py liest von hier, nicht hardcodiert.
TESTS_ANZAHL = 1131

# ─── Projekt-Kennzahlen (Landingpage index.html) ───
# Einzige Quelle fuer die auf index.html beworbenen Kennzahlen. Bei neuem
# SMax-Import oder Codeaenderung hier aktualisieren, dann
# `python scripts/sync_landing_page_stats.py` ausfuehren -- NICHT einzeln in
# index.html editieren (dort mehrfach dupliziert: Hero-Stats, Prototyp-Karten,
# Config-Panel, DE/EN-Uebersetzungen).
PROJEKT_TECHNIKER_ANZAHL = 24          # smax_dashboard_data.json: len(techniker)
PROJEKT_GERAETE_ANZAHL = 6569          # distinct Seriennummern (Closed+Open Jobs)
PROJEKT_KLINIKEN_ANZAHL = 1444         # distinct Klinik-Accounts (Closed+Open Jobs)
PROJEKT_DASHBOARD_CHECKS = 17          # reporting/dashboard.py: _vollstaendigkeits_pruefung()
PROJEKT_CLUSTER_ANZAHL = 6             # techniker/models.py: produkt_cluster()-Kategorien
PROJEKT_PRODUKTFAMILIEN_ANZAHL = 31    # techniker/models.py: distinct Produktfamilien
