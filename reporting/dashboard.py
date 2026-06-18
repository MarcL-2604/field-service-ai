"""Field-Service-Dashboard – Premium Dark Design.

Erzeugt reporting/dashboard.html mit allen Sektionen + Claude-Chat-Panel:
  1. Qualifikations-Ampel pro Techniker  (L3-Abdeckung in der Region)
  2. Naechste 10 faellige STK-Auftraege  (mit Dringlichkeit)
  3. Crosstraining-Luecken Top 5         (hoechstes STK-Potenzial)
  4. NRW-Ueberlastungs-Warnung           (wenn Bedingung erfuellt)
  5. Workflow-Status (7 Schritte)
  6. Business Case (Berechnungslogik)
  +  Eingebetteter Claude-Chat-Assistent (rechtes Panel, 340px)

Design-System: Premium Dark Theme mit Plus Jakarta Sans + Syne.
Keine externen Abhaengigkeiten – reines HTML mit Inline-CSS/JS.
"""

from __future__ import annotations

import csv
import json
import math
import sys
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

# Projektroot auf Suchpfad (falls direkt ausgefuehrt)
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from config import (  # noqa: E402
    HUGO_KA_IDS,
    HUGO_KA_ZIEL_STUNDEN,
    HUGO_KA_RESERVE_PROZENT,
    AUSSENDIENST_STUNDEN,
    PUFFER_BASIS_MIN,
    PUFFER_EINSCHLEUSUNG_MIN,
    PUFFER_GROSSGERAET_MIN,
    PUFFER_GESPRAECH_MIN,
)
from auftraege.dispatcher import naechste_faellige_auftraege  # noqa: E402
from auftraege.workflow import _berechne_dringlichkeit, schlage_termine_vor  # noqa: E402

_DATA_DIR = _ROOT / "daten"
_OUT_PATH = Path(__file__).parent / "dashboard.html"
_HEUTE = date.today()

# ---------------------------------------------------------------------------
# Ampel-Schwellwerte: Anteil qualifizierter L3-Familien an regionalen Familien
# ---------------------------------------------------------------------------
_AMPEL_GRUEN_AB = 0.60   # >= 60 % Abdeckung → Gruen
_AMPEL_GELB_AB  = 0.30   # >= 30 % Abdeckung → Gelb
                          #  < 30 %            → Rot

# NRW-Warnung: ausgeloest wenn mind. 2 NRW-Techniker < 30 % Abdeckung
# UND deren gemeinsames ungenutztes STK-Potenzial > Schwellwert
_NRW_TECHNIKER = {"T5", "T8", "T11", "T13"}
_NRW_STK_WARNUNG_SCHWELLE = 800  # STK/Jahr kombiniert


# ---------------------------------------------------------------------------
# Datenlader
# ---------------------------------------------------------------------------

def _lade_techniker() -> dict[str, dict]:
    """Gibt {techniker_id: {standort, bundesland, region}} zurueck."""
    result = {}
    with open(_DATA_DIR / "techniker.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            result[row["techniker_id"]] = {
                "standort": row["standort"],
                "bundesland": row["bundesland"],
                "region": row["region"],
                "lat": float(row.get("lat", 0) or 0),
                "lon": float(row.get("lon", 0) or 0),
            }
    return result


def _lade_crosstraining() -> list[dict]:
    """Liest crosstraining_empfehlungen.csv und gibt alle Zeilen als Liste zurueck."""
    rows = []
    with open(_DATA_DIR / "crosstraining_empfehlungen.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def _lade_labor_zeiten() -> list[dict]:
    """Liest labor_zeiten.csv und gibt alle Zeilen als Liste zurueck."""
    rows = []
    with open(_DATA_DIR / "labor_zeiten.csv", newline="", encoding="utf-8") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    for row in csv.DictReader(lines):
        rows.append(row)
    return rows


# Cluster-Zuordnung: Produktfamilie → (css_klasse, label_text)
# Kosten: PLATZHALTER – bei T&E anfragen
_CLUSTER_MAP: dict[str, tuple[str, str]] = {
    "Energie":                  ("cluster-small-capital",  "0\u202F\u20ac intern"),
    "Capnografie":              ("cluster-small-capital",  "0\u202F\u20ac intern"),
    "Elektrochirurgie":         ("cluster-hf-chirurgie",   "Kosten: T&E anfragen *"),
    "Hugo":                     ("cluster-1-or",           "10h Handon + T&E anfragen *"),
    "Endoskopie":               ("cluster-1-or",           "10h Handon + T&E anfragen *"),
    "Wirbelsaeule":             ("cluster-1-or",           "10h Handon + T&E anfragen *"),
    "Gastroenterologie":        ("cluster-1-or",           "10h Handon + T&E anfragen *"),
    "Kardiovaskulaer":          ("cluster-2-cardiac",      "10h Handon + T&E anfragen *"),
    "Kardiovaskulaer_Ablation": ("cluster-2-cardiac",      "10h Handon + T&E anfragen *"),
    "Beatmung":                 ("cluster-3-monitoring",   "T&E anfragen *"),
    "Neuromonitoring":          ("cluster-3-monitoring",   "T&E anfragen *"),
    "Neurophysiologie":         ("cluster-3-monitoring",   "T&E anfragen *"),
    "Navigation":               ("cluster-4-digital",      "Online/Teams m\u00f6glich"),
}

# Puffer-Aufschluesselung (Minuten, aus config.py)
_PUFFER = {
    "Basis":         PUFFER_BASIS_MIN,
    "Einschleusung": PUFFER_EINSCHLEUSUNG_MIN,
    "Grossgeraet":   PUFFER_GROSSGERAET_MIN,
    "Gespraech MTech": PUFFER_GESPRAECH_MIN,
}
_PUFFER_GESAMT = sum(_PUFFER.values())  # 95 min


# Hugo Key Account Kapazitaet (aus config.py)
_HUGO_KA_IDS = set(HUGO_KA_IDS)
_HUGO_KA_KAPAZITAET = HUGO_KA_ZIEL_STUNDEN
_HUGO_KA_RESERVE_PCT = int(HUGO_KA_RESERVE_PROZENT * 100)
_HUGO_KA_RESERVE_H = float(AUSSENDIENST_STUNDEN) * HUGO_KA_RESERVE_PROZENT
_HUGO_KA_WARN_H = _HUGO_KA_KAPAZITAET * 0.80


# ---------------------------------------------------------------------------
# Ampel-Berechnung
# ---------------------------------------------------------------------------

def _ampel_farbe(abdeckung: float) -> tuple[str, str]:
    """Gibt (css-klasse, label) zurueck."""
    if abdeckung >= _AMPEL_GRUEN_AB:
        return "ampel-gruen", "GRÜN"
    if abdeckung >= _AMPEL_GELB_AB:
        return "ampel-gelb", "GELB"
    return "ampel-rot", "ROT"


def _berechne_ampeln(ct_rows: list[dict], techniker: dict[str, dict]) -> list[dict]:
    """Berechnet Qualifikations-Abdeckung und Ampel-Status pro Techniker."""
    ergebnisse = []
    for row in ct_rows:
        tid = row["techniker_id"]
        qualifiziert = [f for f in row["qualifizierte_familien_l3plus"].split(";") if f]
        regional = [f for f in row["regionale_produktfamilien"].split(";") if f]
        fehlend = [f for f in row["fehlende_familien"].split(";") if f]

        anzahl_regional = len(regional)
        anzahl_qualifiziert = len(qualifiziert)
        abdeckung = anzahl_qualifiziert / anzahl_regional if anzahl_regional else 0.0

        css, label = _ampel_farbe(abdeckung)
        tech = techniker.get(tid, {})

        ergebnisse.append({
            "techniker_id": tid,
            "standort": tech.get("standort", "–"),
            "region": tech.get("region", "–"),
            "qualifiziert": anzahl_qualifiziert,
            "regional": anzahl_regional,
            "abdeckung_pct": round(abdeckung * 100),
            "fehlend_count": len(fehlend),
            "zusatz_stk": float(row.get("potentielles_zusatz_stk_pa", 0)),
            "partner": row.get("idealer_crosstraining_partner", "–") or "–",
            "ampel_css": css,
            "ampel_label": label,
        })
    return ergebnisse


# ---------------------------------------------------------------------------
# NRW-Warnung
# ---------------------------------------------------------------------------

def _berechne_nrw_warnung(ct_rows: list[dict]) -> dict | None:
    """Prueft ob die NRW-Ueberlastungs-Bedingung erfuellt ist.

    Gibt None zurueck wenn kein Handlungsbedarf, sonst ein Dict mit Details.
    """
    nrw_schwach = []
    nrw_stk_gesamt = 0.0

    for row in ct_rows:
        tid = row["techniker_id"]
        if tid not in _NRW_TECHNIKER:
            continue

        qualifiziert = [f for f in row["qualifizierte_familien_l3plus"].split(";") if f]
        regional = [f for f in row["regionale_produktfamilien"].split(";") if f]
        fehlend = [f for f in row["fehlende_familien"].split(";") if f]
        zusatz = float(row.get("potentielles_zusatz_stk_pa", 0))
        abdeckung = len(qualifiziert) / len(regional) if regional else 0.0

        if abdeckung < _AMPEL_GELB_AB:   # Rot-Techniker
            nrw_schwach.append({
                "id": tid,
                "qualifiziert": len(qualifiziert),
                "familien_l3": ";".join(qualifiziert) if qualifiziert else "–",
                "fehlend": len(fehlend),
                "zusatz_stk": zusatz,
            })
        nrw_stk_gesamt += zusatz

    if len(nrw_schwach) >= 2 and nrw_stk_gesamt >= _NRW_STK_WARNUNG_SCHWELLE:
        return {
            "techniker": nrw_schwach,
            "gesamt_stk": round(nrw_stk_gesamt),
            "anzahl_schwach": len(nrw_schwach),
        }
    return None


# ---------------------------------------------------------------------------
# HTML-Rendering – Premium Dark Design
# ---------------------------------------------------------------------------

_DRINGLICHKEIT_CSS = {
    "\u00dcBERF\u00c4LLIG": "badge-ueberfaellig",
    "KRITISCH": "badge-kritisch",
    "HOCH":     "badge-hoch",
    "NORMAL":   "badge-normal",
}


def _render_ampel_karten(ampeln: list[dict], labor_zeiten: list[dict] | None = None) -> str:
    _AMPEL_ORDER = {"ampel-gruen": 0, "ampel-gelb": 1, "ampel-rot": 2}

    karten = []
    for idx, a in enumerate(ampeln):
        sort_std = _AMPEL_ORDER.get(a["ampel_css"], 1) * 100 + idx
        wochenstunden = 0
        is_hugo = a["techniker_id"] in _HUGO_KA_IDS
        hugo_border = " hugo-border" if is_hugo else ""

        # Hugo KA: reduzierte Kapazitaet 25.6h, sonst 32h
        kapazitaet = _HUGO_KA_KAPAZITAET if is_hugo else float(AUSSENDIENST_STUNDEN)
        ziel_pct = round(kapazitaet / 45 * 100, 1)
        auslastung_pct = round(wochenstunden / kapazitaet * 100, 1) if kapazitaet else 0.0

        hugo_badge = ""
        hugo_reserve = ""
        hugo_warn = ""
        if is_hugo:
            hugo_badge = '<div class="hugo-ka-badge">Hugo Key Account</div>'
            hugo_reserve = (
                '<div class="hugo-reserve">'
                f'20% Reserve = {_HUGO_KA_RESERVE_H}h f&uuml;r Hugo-Calls</div>')
            if wochenstunden > _HUGO_KA_WARN_H:
                hugo_warn = (
                    '<div class="hugo-warnung">'
                    '&#9888; Auslastung &gt;80% von 25.6h!</div>')

        karten.append(f"""
      <div class="ampel-karte {a['ampel_css']}{hugo_border}"
           data-tid="{a['techniker_id']}"
           data-sort-standard="{sort_std}"
           data-sort-crosstraining="{a['fehlend_count']}"
           data-sort-auslastung="{wochenstunden}"
           data-sort-portfolio="{a['qualifiziert']}"
           data-sort-potential="{a['zusatz_stk']:.0f}"
           style="cursor:pointer"
           onclick="showTechDetail('{a['techniker_id']}')">
        <div class="ampel-header">
          <div class="ampel-id">{a['techniker_id']}</div>
          <div class="ampel-badge">{a['ampel_label']}</div>
        </div>
        <div class="ampel-standort">{a['standort']}</div>
        <div class="ampel-region">{a['region']}</div>
        {hugo_badge}

        <div class="metric-box metric-standard">
          <div class="metric-num">{a['abdeckung_pct']}&thinsp;%</div>
          <div class="metric-lbl" data-i18n="card.l3coverage">L3-Abdeckung</div>
          <div class="metric-sub">{a['qualifiziert']}&thinsp;/&thinsp;{a['regional']} <span data-i18n="card.fam">Fam.</span> &middot; {a['fehlend_count']} <span data-i18n="card.gaps">L&uuml;cken</span></div>
          <div class="metric-sub"><span data-i18n="card.capacity">Kapazit&auml;t</span>: {kapazitaet}h/<span data-i18n="card.week">Woche</span></div>
        </div>

        <div class="metric-box metric-crosstraining" style="display:none">
          <div class="metric-num">{a['fehlend_count']}</div>
          <div class="metric-lbl" data-i18n="card.missingFam">fehlende Familien</div>
          <div class="metric-sub">+{a['zusatz_stk']:.0f}&thinsp;STK/a <span data-i18n="card.potential">Potenzial</span></div>
        </div>

        <div class="metric-box metric-auslastung" style="display:none">
          <div class="metric-num">{wochenstunden}&thinsp;h</div>
          <div class="metric-lbl" data-i18n="card.weeklyHours">Wochenstunden</div>
          <div class="metric-sub"><span data-i18n="card.capacity">Kapazit&auml;t</span>: {kapazitaet}h/<span data-i18n="card.week">Woche</span></div>
          <div class="auslastung-bar-wrap">
            <div class="auslastung-bar-fill" style="width:{auslastung_pct:.1f}%"></div>
            <div class="auslastung-bar-ziel" style="left:{ziel_pct:.1f}%"></div>
          </div>
          <div class="metric-sub">{wochenstunden}&thinsp;h &middot; Ziel&thinsp;{kapazitaet}h &middot; Max&thinsp;45&thinsp;h</div>
          {hugo_reserve}
          {hugo_warn}
          <div class="metric-sub metric-italic" data-i18n="card.fridayNote">Freitag = Home Office &middot; keine Echtzeit-Daten</div>
        </div>

        <div class="metric-box metric-portfolio" style="display:none">
          <div class="metric-num">{a['qualifiziert']}</div>
          <div class="metric-lbl" data-i18n="card.l3families">L3-Familien</div>
          <div class="metric-sub"><span data-i18n="card.ofRegional">von</span> {a['regional']} <span data-i18n="card.regional">regionalen</span></div>
        </div>

        <div class="metric-box metric-potential" style="display:none">
          <div class="metric-num">+{a['zusatz_stk']:.0f}</div>
          <div class="metric-lbl" data-i18n="card.stkPotential">STK/a Potenzial</div>
          <div class="metric-sub" data-i18n="card.afterCT">nach Crosstraining</div>
        </div>
      </div>""")
    return "\n".join(karten)


def _render_stk_tabelle(auftraege_rows: list[dict]) -> str:
    zeilen = []
    for row in auftraege_rows:
        css = _DRINGLICHKEIT_CSS.get(row["dringlichkeit"], "badge-normal")
        termine_html = row.get("termine_vorschlag", "&ndash;")
        zeilen.append(
            f"      <tr>"
            f"<td><code>{row['auftrag_id']}</code></td>"
            f"<td>{row['klinik']}</td>"
            f"<td>{row['geraet']}</td>"
            f"<td>{row['produkt']}</td>"
            f"<td>{row['faelligkeit']}</td>"
            f"<td>{termine_html}</td>"
            f"<td><span class='badge {css}'>{row['dringlichkeit']}</span></td>"
            f"<td>{row['tage']}</td>"
            f"</tr>"
        )
    return "\n".join(zeilen)


_REPAIR_SLA_CSS = {
    "Gruen": "badge-normal",
    "Gelb": "badge-hoch",
    "Rot": "badge-ueberfaellig",
    "Kritisch": "badge-kritisch",
    "Blau": "badge-blau",
}


def _render_repair_tabelle(repair_rows: list[dict]) -> str:
    if not repair_rows:
        return "<p style='color:rgba(255,255,255,.5);font-style:italic;'>Keine offenen Repair-Auftr&auml;ge.</p>"
    zeilen = []
    for row in repair_rows:
        css = _REPAIR_SLA_CSS.get(row["sla_status"], "badge-normal")
        puls = " puls-animation" if row["sla_status"] in ("Rot", "Kritisch") else ""
        zeilen.append(
            f"      <tr>"
            f"<td><code>{row['auftrag_id']}</code></td>"
            f"<td>{row['klinik']}</td>"
            f"<td>{row['geraet']}</td>"
            f"<td>{row['eingang']}</td>"
            f"<td><span class='badge {css}{puls}'>{row['sla_text']}</span></td>"
            f"<td>{row['phase']}</td>"
            f"<td>{row.get('ersatzteil', '&ndash;')}</td>"
            f"</tr>"
        )
    return "\n".join(zeilen)


def _render_ct_tabelle(ct_top5: list[dict], techniker: dict[str, dict]) -> str:
    zeilen = []
    for row in ct_top5:
        tid = row["techniker_id"]
        standort = techniker.get(tid, {}).get("standort", "–")
        fehlende_list = [f for f in row["fehlende_familien"].split(";") if f]
        partner = row.get("idealer_crosstraining_partner", "–") or "–"

        # Schulungsdetails
        schulung_typ = row.get("top_schulung_typ", "")
        schulung_kosten = row.get("top_schulung_kosten", "")
        schulung_dauer = row.get("top_schulung_dauer", "")

        # Icon: Haus = intern, Schule = extern
        typ_icon = "&#127968;" if "INTERN" in schulung_typ else "&#127979;"
        kosten_badge = (
            f"<span class='sub'>{typ_icon} {schulung_kosten}</span>"
            if schulung_kosten else ""
        )
        dauer_badge = (
            f"<br><span class='sub'>{schulung_dauer}</span>"
            if schulung_dauer else ""
        )

        # Cluster-Badges pro fehlender Familie
        cluster_badges = []
        for fam in fehlende_list:
            css_cls, label = _CLUSTER_MAP.get(fam, ("cluster-small-capital", "–"))
            cluster_badges.append(
                f"<span class='cluster-badge {css_cls}'>{fam}: {label}</span>"
            )
        badges_html = " ".join(cluster_badges)

        zeilen.append(
            f"      <tr>"
            f"<td><strong>{tid}</strong> <span class='sub'>({standort})</span></td>"
            f"<td>{row['anzahl_luecken']}</td>"
            f"<td><strong>{float(row['potentielles_zusatz_stk_pa']):.0f}</strong></td>"
            f"<td class='fehlend-liste'>{badges_html}{dauer_badge}</td>"
            f"<td>{partner}<br>{kosten_badge}</td>"
            f"</tr>"
        )
    return "\n".join(zeilen)


def _render_nrw_warnung(warnung: dict | None) -> str:
    if warnung is None:
        return ""
    tech_liste = "".join(
        f"<li><strong>{t['id']}</strong>: {t['qualifiziert']} L3-Familie(n) "
        f"(&bdquo;{t['familien_l3']}&ldquo;), "
        f"{t['fehlend']} Luecken, +{t['zusatz_stk']:.0f}&thinsp;STK/a ungenutztes Potenzial</li>"
        for t in warnung["techniker"]
    )
    return f"""
  <section class="warnung-box">
    <h2>&#9888; NRW-&Uuml;berlastungs-Warnung</h2>
    <p class="warnung-stats">
      380 STK/Kopf NRW vs. 72 Nord &middot;
      <strong>{warnung['anzahl_schwach']} von 4 NRW-Technikern</strong> decken weniger als
      {round(_AMPEL_GELB_AB * 100)}&thinsp;% der regionalen Produktfamilien ab (Ampel&thinsp;ROT).
    </p>
    <p class="warnung-stats">
      T8 + T13: <strong>1.025 STK/Jahr nicht abdeckbar</strong> &ndash;
      Kombiniertes ungenutztes Potenzial:
      <strong>{warnung['gesamt_stk']:,}&thinsp;STK/Jahr</strong>
    </p>
    <ul>{tech_liste}</ul>
    <p class="warnung-hinweis">
      Empfehlung: Crosstraining-Ma&szlig;nahmen f&uuml;r T8 und T13 priorisieren.
      Ideale Partner laut Analyse: T10 (f&uuml;r T8) und T10 (f&uuml;r T13).
    </p>
  </section>"""


def _render_puffer_section(labor_zeiten: list[dict]) -> str:
    """Erzeugt aufklappbare Puffer-Visualisierung pro geplantem Einsatz."""
    if not labor_zeiten:
        return ""

    # Gruppiere nach Techniker → Liste von Einsaetzen
    einsaetze_by_tech: dict[str, list[dict]] = {}
    for lz in labor_zeiten:
        tid = lz.get("techniker_id", "")
        if tid:
            einsaetze_by_tech.setdefault(tid, []).append(lz)

    rows = []
    eid = 0
    for tid in sorted(einsaetze_by_tech):
        for lz in einsaetze_by_tech[tid]:
            eid += 1
            netto_min = int(lz.get("service_zeit_min", 0))
            admin_min = int(lz.get("admin_zeit_min", 0))
            netto_total = netto_min + admin_min
            gesamt = netto_total + _PUFFER_GESAMT
            netto_pct = round(netto_total / gesamt * 100) if gesamt else 0
            puffer_pct = 100 - netto_pct

            puffer_detail = "".join(
                f"<div class='puffer-item'>"
                f"<span class='puffer-label'>{k}:</span> "
                f"<span class='puffer-val'>{v} min</span></div>"
                for k, v in _PUFFER.items()
            )

            detail_id = f"puffer-detail-{eid}"
            rows.append(
                f'<div class="puffer-row" onclick="'
                f"var d=document.getElementById('{detail_id}');"
                f"d.style.display=d.style.display==='none'?'block':'none'\">"
                f'<div class="puffer-summary">'
                f'<strong>{tid}</strong> &middot; '
                f'{lz.get("produkt_familie","")} &middot; '
                f'{lz.get("geraete_typ","")} &middot; '
                f'<span class="puffer-gesamt">{gesamt} min gesamt</span>'
                f' <span class="sub">&#9660;</span></div>'
                f'<div class="puffer-bar-wrap">'
                f'<div class="puffer-bar-netto" style="width:{netto_pct}%">'
                f'{netto_total} min</div>'
                f'<div class="puffer-bar-puffer" style="width:{puffer_pct}%">'
                f'{_PUFFER_GESAMT} min</div></div>'
                f'<div id="{detail_id}" class="puffer-detail" style="display:none">'
                f'<div class="puffer-detail-grid">'
                f'<div><strong>Netto-Zeit:</strong> {netto_min} min Service + {admin_min} min Admin = {netto_total} min</div>'
                f'<div class="puffer-aufschluesselung">'
                f'<strong>Puffer-Aufschl&uuml;sselung:</strong>'
                f'{puffer_detail}'
                f'<div class="puffer-item puffer-summe">'
                f'<span class="puffer-label">Gesamt Puffer:</span> '
                f'<span class="puffer-val">{_PUFFER_GESAMT} min</span></div>'
                f'</div>'
                f'<div><strong>Gesamtzeit:</strong> {netto_total} + {_PUFFER_GESAMT} = '
                f'<strong>{gesamt} min</strong> ({gesamt/60:.1f}h)</div>'
                f'</div></div></div>')

    return f"""
  <section>
    <h2>Tourplanung &mdash; Puffer-Visualisierung</h2>
    <p class="section-hint">
      Pro geplantem Einsatz: Netto-Zeit (gr&uuml;n) + Puffer (gelb).
      Klick f&uuml;r Aufschl&uuml;sselung. Quelle: labor_zeiten.csv
    </p>
    <div class="puffer-container">
{"".join(rows)}
    </div>
  </section>"""


def _render_workflow_status() -> str:
    """Erzeugt die Workflow-Status Sektion (7 Schritte)."""
    steps = [
        ("&#128229;", "Einlesen", "auto", "SMax Go API"),
        ("&#129504;", "Scoring", "auto", "KI-Empfehlung"),
        ("&#9989;", "Best&auml;tigung", "mensch", "Disponent pr&uuml;ft"),
        ("&#128241;", "Info", "auto", "Techniker-Push"),
        ("&#128197;", "Due-Date", "auto", "Termin-Check"),
        ("&#128270;", "TD-Pr&uuml;fung", "auto", "Dokumente pr&uuml;fen"),
        ("&#128231;", "Kundenmail", "auto", "Best&auml;tigung"),
    ]
    items = []
    for i, (icon, label, mode, detail) in enumerate(steps):
        badge_cls = "wf-badge-auto" if mode == "auto" else "wf-badge-mensch"
        badge_txt = "Auto" if mode == "auto" else "Mensch"
        arrow = '<span class="wf-arrow">&#8594;</span>' if i < len(steps) - 1 else ""
        items.append(
            f'<div class="wf-step">'
            f'<div class="wf-icon">{icon}</div>'
            f'<div class="wf-label">{label}</div>'
            f'<span class="wf-badge {badge_cls}">{badge_txt}</span>'
            f'<div class="wf-detail">{detail}</div>'
            f'</div>{arrow}'
        )
    return f"""
  <section>
    <h2>6 &mdash; Workflow-Status</h2>
    <p class="section-hint">
      Vollautomatisiert &middot; Copilot &mdash; kein Autopilot
    </p>
    <div class="wf-pipeline">
      {"".join(items)}
    </div>
  </section>"""


def _render_business_case() -> str:
    """Erzeugt die Business-Case Sektion (Berechnungslogik, keine festen Eurobetraege)."""
    return """
  <section>
    <h2>7 &mdash; Business Case</h2>
    <p class="section-hint">
      Berechnungslogik &mdash; keine festen Eurobetr&auml;ge
    </p>
    <div class="bc-grid">
      <div class="bc-card">
        <div class="bc-card-title">Zeitersparnis pro Techniker</div>
        <div class="bc-formula">14 Techniker &times; [&Oslash; Einsparung h/Woche] &times; 52</div>
        <div class="bc-hint">= Jahres-Stunden gespart</div>
      </div>
      <div class="bc-card">
        <div class="bc-card-title">Monet&auml;rer Wert</div>
        <div class="bc-formula">Jahres-Stunden &times; [Stundensatz &euro;]</div>
        <div class="bc-hint">= J&auml;hrliche Einsparung</div>
      </div>
      <div class="bc-card">
        <div class="bc-card-title">Crosstraining-ROI</div>
        <div class="bc-formula">[+STK/a Potenzial] &times; [&Oslash; STK-Dauer h] &times; [Stundensatz &euro;]</div>
        <div class="bc-hint">= Zus&auml;tzlicher Deckungsbeitrag</div>
      </div>
      <div class="bc-card">
        <div class="bc-card-title">Fahrzeit-Optimierung</div>
        <div class="bc-formula">[Eingesparte km/a] &times; [km-Pauschale &euro;] + [h/a] &times; [Stundensatz &euro;]</div>
        <div class="bc-hint">= Mobilit&auml;tskostenreduktion</div>
      </div>
    </div>
    <div class="bc-gold-hint">
      &#9733; Echte Zahlen nach Pilotphase &mdash; Platzhalter f&uuml;r individuelle Parameter
    </div>
  </section>"""


def _generate_demo_history(techniker: dict[str, dict],
                           labor_zeiten: list[dict]) -> dict[str, dict]:
    """Generiert realistische Demo-Einsatzhistorie pro Techniker."""
    import hashlib

    # Kliniken pro Region (Demo)
    _KLINIKEN_DEMO = {
        "Hessen": ["UKF Frankfurt", "Klinikum Kassel", "Uniklinik Giessen"],
        "Bayern": ["Klinikum Erlangen", "LMU Muenchen", "Klinikum Augsburg"],
        "Bayern-Nord": ["Klinikum Erlangen", "Klinikum Bayreuth", "Klinikum Bamberg"],
        "Bayern-Ost": ["Klinikum Regensburg", "Klinikum Passau", "Klinikum Landshut"],
        "Baden-Württemberg": ["Uniklinik Tuebingen", "Klinikum Stuttgart", "Uniklinik Ulm"],
        "BaWü-Süd": ["Uniklinik Tuebingen", "Klinikum Stuttgart", "Uniklinik Freiburg"],
        "NRW-West": ["UKB Bonn", "Uniklinik Koeln", "Klinikum Aachen"],
        "NRW-Süd": ["UKB Bonn", "Uniklinik Koeln", "Klinikum Aachen"],
        "Nord": ["UKE Hamburg", "UKSH Luebeck", "MHH Hannover"],
        "Thüringen": ["Klinikum Weimar", "Uniklinik Jena", "Klinikum Erfurt"],
    }
    _TYPEN = ["STK", "PM", "STK", "Repair", "STK"]

    # Labor-Zeiten nach Techniker gruppieren
    lz_by_tech: dict[str, list[dict]] = {}
    for lz in labor_zeiten:
        lz_by_tech.setdefault(lz["techniker_id"], []).append(lz)

    result: dict[str, dict] = {}
    for tid, td in sorted(techniker.items()):
        region = td.get("region", "Hessen")
        kliniken = _KLINIKEN_DEMO.get(region, ["Klinikum " + td.get("standort", "Unbekannt")])
        tech_lz = lz_by_tech.get(tid, [])

        # Generiere 5 Demo-Work-Orders
        orders = []
        for i in range(5):
            seed = int(hashlib.md5(f"{tid}-{i}".encode()).hexdigest()[:8], 16)
            tage_offset = 7 + (seed % 50)
            datum = _HEUTE - timedelta(days=tage_offset)
            klinik = kliniken[seed % len(kliniken)]
            if tech_lz:
                lz = tech_lz[seed % len(tech_lz)]
                geraet = lz["geraete_typ"]
                familie = lz["produkt_familie"]
                dauer_min = int(lz["service_zeit_min"]) + int(lz["admin_zeit_min"])
            else:
                geraet = "–"
                familie = "–"
                dauer_min = 120 + (seed % 180)
            typ = _TYPEN[seed % len(_TYPEN)]
            orders.append({
                "datum": datum.strftime("%d.%m.%Y"),
                "klinik": klinik,
                "geraet": geraet,
                "typ": typ,
                "dauer_h": f"{dauer_min // 60}h {dauer_min % 60:02d}min",
                "dauer_min": dauer_min,
                "status": "\u2713",
                "familie": familie,
            })
        orders.sort(key=lambda o: o["datum"], reverse=True)

        # Kennzahlen
        avg_dauer = sum(o["dauer_min"] for o in orders) / len(orders) if orders else 0
        from collections import Counter
        klinik_counter = Counter(o["klinik"] for o in orders)
        fam_counter = Counter(o["familie"] for o in orders)
        haeufigste_klinik = klinik_counter.most_common(1)[0][0] if klinik_counter else "–"
        haeufigste_fam = fam_counter.most_common(1)[0][0] if fam_counter else "–"

        result[tid] = {
            "orders": orders[:3],  # Letzte 3 anzeigen
            "einsaetze_monat": 2 + (int(hashlib.md5(tid.encode()).hexdigest()[:4], 16) % 5),
            "einsaetze_jahr": 28 + (int(hashlib.md5(tid.encode()).hexdigest()[:6], 16) % 30),
            "avg_dauer_h": f"{avg_dauer / 60:.1f}",
            "haeufigste_klinik": haeufigste_klinik,
            "haeufigste_familie": haeufigste_fam,
        }
    return result


def _render_techniker_detail_data(
    techniker: dict[str, dict],
    demo_history: dict[str, dict],
) -> str:
    """Erzeugt JSON-Daten fuer Techniker-Detail-Modal (inline im HTML)."""
    detail_data: dict[str, dict] = {}
    for tid, td in sorted(techniker.items()):
        hist = demo_history.get(tid, {})
        detail_data[tid] = {
            "standort": td.get("standort", "–"),
            "orders": hist.get("orders", []),
            "einsaetze_monat": hist.get("einsaetze_monat", 0),
            "einsaetze_jahr": hist.get("einsaetze_jahr", 0),
            "avg_dauer_h": hist.get("avg_dauer_h", "0"),
            "haeufigste_klinik": hist.get("haeufigste_klinik", "–"),
            "haeufigste_familie": hist.get("haeufigste_familie", "–"),
        }
    return json.dumps(detail_data, ensure_ascii=False)


# ---------------------------------------------------------------------------
# System-Prompt fuer Claude-Chat
# ---------------------------------------------------------------------------

def _build_system_prompt(
    ct_rows: list[dict],
    techniker: dict[str, dict],
    ampeln: list[dict],
) -> str:
    """Baut den System-Prompt mit allen Projektdaten."""
    tech_lines = []
    ct_by_tid = {r["techniker_id"]: r for r in ct_rows}
    for a in ampeln:
        tid = a["techniker_id"]
        ct = ct_by_tid.get(tid, {})
        l3_fam = ct.get("qualifizierte_familien_l3plus", "")
        fehlend = ct.get("fehlende_familien", "")
        partner = ct.get("idealer_crosstraining_partner", "–") or "–"
        zusatz = ct.get("potentielles_zusatz_stk_pa", "0")
        tech_lines.append(
            f"- {tid}: Standort={a['standort']}, Region={a['region']}, "
            f"Ampel={a['ampel_label']}, Abdeckung={a['abdeckung_pct']}%, "
            f"L3-Familien=[{l3_fam}], "
            f"Fehlend=[{fehlend}], "
            f"+{float(zusatz):.0f} STK/a Potenzial, "
            f"Crosstraining-Partner={partner}"
        )
    tech_block = "\n".join(tech_lines)

    return (
        "Du bist der KI-Assistent fuer das Medtronic Field Service Dashboard. "
        "Antworte auf Deutsch, praezise und im Kontext der Medtronic-Servicetechniker-Planung. "
        "Beziehe dich auf die konkreten Daten unten.\n\n"
        "## Techniker-Uebersicht (14 Techniker)\n"
        f"{tech_block}\n\n"
        "## Scoring-Formel\n"
        "Score = Kompetenz x 0.40 + Fahrzeit x 0.35 + Auslastung x 0.25\n"
        "- Kompetenz: L3=100, L2=50, L1=0 Punkte\n"
        "- Fahrzeit: Luftlinie x Umwegfaktor 1.35, Geschwindigkeit 90 km/h\n"
        "- Auslastung: Wochenbasis 32h (Mo-Do), Freitag = Home Office / Admin\n\n"
        "## Arbeitszeitmodell (Vertrauensarbeitszeit)\n"
        "- Wochenziel: 32h effektive Aussendienststunden (Mo-Do, je 8h)\n"
        "- Freitag = Home Office / Bueroarbeit (kein Aussendienst ausser Notfaelle)\n"
        "- Warnungen: >=30h Puffer, >=34h Gelb, >45h Ausschluss (ArbZG)\n"
        "- Tageslimits: >8h Warnung, >9h Regel-Max, >10h Ausschluss (ArbZG §3)\n"
        "- Mindestruhezeit: 11h zwischen Arbeitstagen (ArbZG §5)\n\n"
        "## NRW-Ueberlastung\n"
        "- NRW-Techniker: T5 (Oberhausen), T8 (Hennef), T11 (Gangelt), T13 (Meckenheim)\n"
        "- T8 und T13 sind Ampel ROT (<20% Abdeckung)\n"
        "- Kombiniertes ungenutztes Potenzial: ~1.510 STK/Jahr\n"
        "- Durchschnitt NRW: ~380 STK/Kopf – deutliche Ueberlastungsgefahr\n"
        "- Empfehlung: Crosstraining mit T10 (Balingen) als Partner\n\n"
        "## Kalibrierungs-Warnungen (ablaufend <30 Tage ab 27.03.2026)\n"
        "- T10: Hugo-Kalibrierkoffer (MM-HUGO-002) – 14 Tage verbleibend (10.04.2026)\n"
        "- T5: NIM-Tester (MM-NEURO-001) – 19 Tage verbleibend (15.04.2026)\n"
        "- T1: Hugo-Diagnosetool (MM-HUGO-001) – 24 Tage verbleibend (20.04.2026)\n"
        "- T8: EKG-Simulator (MM-KARD-001) – 29 Tage verbleibend (25.04.2026)\n\n"
        "## Crosstraining-Prioritaeten (Top 5 nach STK-Potenzial)\n"
        "1. T2 (Wehingen): 9 Luecken, +664 STK/a – Partner: T10\n"
        "2. T8 (Hennef): 9 Luecken, +527 STK/a – Partner: T10\n"
        "3. T13 (Meckenheim): 9 Luecken, +498 STK/a – Partner: T10\n"
        "4. T1 (Obertshausen): 8 Luecken, +453 STK/a – Partner: T14\n"
        "5. T12 (Frankfurt): 8 Luecken, +449 STK/a – Partner: T10\n\n"
        "## Pflichtdokumente je Auftragstyp\n"
        "- STK: Messprotokoll, Servicebericht\n"
        "- PM: Servicebericht, Checkliste\n"
        "- Repair: Servicebericht, Foto vorher, Foto nachher "
        "(+ KV wenn Kosten > 500 EUR)\n\n"
        "## Hugo-Regel\n"
        "Hugo-Auftraege duerfen NUR von Hugo-zertifizierten Technikern (L3) "
        "durchgefuehrt werden: T1, T6, T10, T11.\n"
        "Hugo-Standorte: UKE Hamburg, UKSH Luebeck, BG Bergmannsheil Bochum, "
        "Uniklinikum Ulm, Uniklinikum Dresden u.a."
    )


# ---------------------------------------------------------------------------
# Gebietsplanung – Fahrzeit-Optimierung
# ---------------------------------------------------------------------------

_TECH_FARBEN = {
    "T1":  "#0072CE", "T2":  "#00A3E0", "T3":  "#7B2D8E",
    "T4":  "#E87000", "T5":  "#00843D", "T6":  "#003087",
    "T7":  "#CC0000", "T8":  "#E8A000", "T9":  "#2E8B57",
    "T10": "#B22222", "T11": "#4169E1", "T12": "#2F4F4F",
    "T13": "#D2691E", "T14": "#008B8B",
}

# Primaere Gebietszuweisung (Bundesland → Techniker) fuer Karteneinfaerbung
_GEBIET_AKTUELL = {
    "Schleswig-Holstein": "T6", "Hamburg": "T9",
    "Mecklenburg-Vorpommern": "T9", "Niedersachsen": "T6",
    "Bremen": "T6", "Nordrhein-Westfalen": "T11",
    "Hessen": "T1", "Thüringen": "T3",
    "Sachsen": "T3", "Sachsen-Anhalt": "T3",
    "Brandenburg": "T3", "Berlin": "T3",
    "Rheinland-Pfalz": "T8", "Saarland": "T13",
    "Baden-Württemberg": "T10", "Bayern": "T7",
}
_GEBIET_OPTIMIERT = dict(_GEBIET_AKTUELL)  # State-level bleibt gleich

# Approximate Mittelpunkte fuer 2-stellige PLZ-Bereiche (lat, lon)
_PLZ2_COORDS: dict[str, tuple[float, float]] = {
    "01": (51.05, 13.74), "02": (51.18, 14.43), "03": (51.76, 14.33),
    "04": (51.34, 12.37), "06": (51.50, 11.97), "07": (50.93, 11.59),
    "08": (50.72, 12.49), "09": (50.83, 12.92), "10": (52.52, 13.41),
    "12": (52.48, 13.44), "13": (52.54, 13.35), "14": (52.39, 13.07),
    "15": (52.35, 14.55), "16": (52.76, 13.28), "17": (54.10, 13.38),
    "18": (54.09, 12.14), "19": (53.63, 11.42), "20": (53.55, 10.00),
    "21": (53.47, 9.97), "22": (53.60, 9.83), "23": (53.87, 10.69),
    "24": (54.32, 10.12), "25": (53.90, 9.48), "26": (53.14, 8.22),
    "27": (53.08, 8.80), "28": (53.08, 8.80), "29": (52.97, 10.23),
    "30": (52.37, 9.73), "31": (52.23, 9.79), "32": (52.02, 8.53),
    "33": (51.93, 8.87), "34": (51.32, 9.50), "35": (50.58, 8.68),
    "36": (50.56, 9.68), "37": (51.54, 9.92), "38": (52.27, 10.53),
    "39": (52.12, 11.63), "40": (51.22, 6.78), "41": (51.21, 6.69),
    "42": (51.26, 7.15), "44": (51.51, 7.47), "45": (51.45, 7.01),
    "46": (51.47, 6.85), "47": (51.44, 6.76), "48": (51.96, 7.63),
    "49": (52.28, 8.05), "50": (50.94, 6.96), "51": (50.94, 7.03),
    "52": (50.78, 6.08), "53": (50.73, 7.10), "54": (49.76, 6.64),
    "55": (49.99, 8.25), "56": (50.36, 7.60), "57": (50.87, 8.02),
    "58": (51.36, 7.47), "59": (51.68, 7.81), "60": (50.11, 8.68),
    "61": (50.18, 8.63), "63": (50.07, 8.86), "64": (49.87, 8.65),
    "65": (50.08, 8.24), "66": (49.24, 7.00), "67": (49.48, 8.44),
    "68": (49.49, 8.47), "69": (49.41, 8.69), "70": (48.78, 9.18),
    "71": (48.73, 9.12), "72": (48.52, 9.06), "73": (48.80, 9.68),
    "74": (49.14, 9.21), "75": (48.89, 8.70), "76": (49.01, 8.40),
    "77": (48.47, 7.94), "78": (48.06, 8.46), "79": (48.00, 7.84),
    "80": (48.14, 11.58), "81": (48.14, 11.60), "82": (48.08, 11.36),
    "83": (47.86, 12.13), "84": (48.54, 12.15), "85": (48.26, 11.44),
    "86": (48.37, 10.90), "87": (47.73, 10.32), "88": (47.66, 9.48),
    "89": (48.40, 10.00), "90": (49.45, 11.08), "91": (49.60, 11.00),
    "92": (49.02, 12.10), "93": (49.01, 12.10), "94": (48.57, 13.45),
    "95": (50.09, 11.78), "96": (50.27, 11.08), "97": (49.79, 9.95),
    "98": (50.61, 10.69), "99": (50.98, 11.03),
}

# Einstellungsempfehlungen fuer unterversorgte Regionen
_EINSTELLUNGS_EMPFEHLUNGEN = [
    {
        "standort": "Berlin",
        "plz": "10117",
        "lat": 52.52, "lon": 13.41,
        "region": "Berlin / Brandenburg / MV",
        "abdeckt_plz": ["10", "12", "13", "14", "15", "16", "17", "18", "19",
                         "01", "02", "03"],
        "kliniken_geschaetzt": 12,
        "begruendung": "Groesste Versorgungsluecke: T3 (Weimar) deckt ganz "
                       "Ostdeutschland allein ab. Berlin-Techniker entlastet "
                       "T3 um ca. 50% und reduziert max. Fahrzeit von 270km auf 80km.",
    },
    {
        "standort": "Hannover",
        "plz": "30625",
        "lat": 52.37, "lon": 9.73,
        "region": "Niedersachsen / Bremen",
        "abdeckt_plz": ["26", "27", "28", "29", "30", "31", "32", "33",
                         "34", "37", "38", "49"],
        "kliniken_geschaetzt": 8,
        "begruendung": "T6 (Schenefeld) und T9 (Hamburg) decken den Norden, "
                       "aber Niedersachsen-Sued/Ost bleibt unterversorgt. "
                       "Hannover schliesst die Luecke zwischen Nord und Mitte.",
    },
    {
        "standort": "München",
        "plz": "80336",
        "lat": 48.14, "lon": 11.58,
        "region": "München / Oberbayern",
        "abdeckt_plz": ["80", "81", "82", "83", "84", "85", "86"],
        "kliniken_geschaetzt": 10,
        "begruendung": "Muenchen ist groesster Klinik-Cluster in Bayern. "
                       "T4 (Erlangen) und T7 (Wildenberg) zu weit entfernt. "
                       "Eigener Muenchen-Techniker fuer 10+ Kliniken optimal.",
    },
    {
        "standort": "Mannheim",
        "plz": "68159",
        "lat": 49.49, "lon": 8.47,
        "region": "Saarland / Pfalz / Rhein-Neckar",
        "abdeckt_plz": ["66", "67", "68", "69", "76"],
        "kliniken_geschaetzt": 6,
        "begruendung": "Luecke zwischen T1 (Obertshausen/Hessen) und "
                       "T10 (Balingen/BaWue). Mannheim deckt Saarland, "
                       "Pfalz und Rhein-Neckar-Raum kompakt ab.",
    },
]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(min(1.0, math.sqrt(a)))


def _strassenfaktor(plz: str) -> float:
    """Geschaetzter Strassenfaktor nach PLZ-Region."""
    p = plz[:2] if len(plz) >= 2 else ""
    if p in ("87", "88"):                                   return 2.0
    if p in ("77", "78", "79"):                             return 2.0
    if p in ("83", "84", "86"):                             return 1.5
    if p in ("40", "41", "42", "44", "45", "46", "47",
             "48", "50", "51", "52", "53"):                 return 1.0
    if p in ("60", "61", "63", "65"):                       return 1.0
    if p in ("10", "12", "13", "14", "20", "21", "22"):     return 1.0
    return 1.3


def _berechne_gebietsmetriken(
    techniker: dict[str, dict],
) -> tuple[list[dict], list[dict]]:
    """Berechnet Fahrzeit-Metriken (aktuell + optimiert) pro Techniker."""
    try:
        from techniker.scoring import _KLINIK_COORDS
    except ImportError:
        return [], []

    kliniken = []
    name_to_id: dict[str, str] = {}
    with open(_DATA_DIR / "kliniken.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            plz = row["plz"]
            kid = row["klinik_id"]
            name_to_id[row["name"].strip().lower()] = kid
            if plz in _KLINIK_COORDS:
                lat, lon = _KLINIK_COORDS[plz]
                kliniken.append({"id": kid, "plz": plz,
                                 "lat": lat, "lon": lon})

    # geraete.csv nutzt klinik_name, nicht klinik_id → ueber Name matchen
    def _norm(s: str) -> str:
        return (s.strip().lower()
                .replace("ä", "ae").replace("ö", "oe")
                .replace("ü", "ue").replace("ß", "ss"))

    name_to_id_norm = {_norm(k): v for k, v in name_to_id.items()}

    stk_count: dict[str, float] = {}
    with open(_DATA_DIR / "geraete.csv", newline="", encoding="utf-8") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    for row in csv.DictReader(lines):
        kname = _norm(row.get("klinik_name", ""))
        kid = name_to_id_norm.get(kname, "")
        if not kid:
            for nk, nid in name_to_id_norm.items():
                if kname in nk or nk in kname:
                    kid = nid
                    break
        if kid:
            try:
                anzahl = int(row.get("anzahl", 1))
                zyklus = max(1, int(row.get("stk_zyklus_jahre", 1)))
                stk_count[kid] = stk_count.get(kid, 0) + anzahl / zyklus
            except ValueError:
                stk_count[kid] = stk_count.get(kid, 0) + 1

    def _calc(allgaeu_shift: bool = False) -> list[dict]:
        zuweisungen: dict[str, list] = {tid: [] for tid in techniker}
        for k in kliniken:
            best_tid, best_dist = "", float("inf")
            for tid, td in techniker.items():
                if not td.get("lat"):
                    continue
                d = _haversine_km(td["lat"], td["lon"], k["lat"], k["lon"])
                if d < best_dist:
                    best_dist, best_tid = d, tid
            # Optimiert: Allgaeu/West-Bayern (PLZ 87/88) von BaWue-Sued-Technikern nach T7
            if (allgaeu_shift
                    and k["plz"][:2] in ("87", "88")
                    and best_tid in ("T2", "T10", "T14")):
                td7 = techniker.get("T7", {})
                if td7.get("lat"):
                    best_tid = "T7"
                    best_dist = _haversine_km(
                        td7["lat"], td7["lon"], k["lat"], k["lon"])
            if best_tid:
                eff_speed = 100.0 / _strassenfaktor(k["plz"])
                zuweisungen[best_tid].append({
                    "fz": best_dist / eff_speed * 60,
                    "stk": stk_count.get(k["id"], 0),
                })

        result = []
        for tid in sorted(techniker):
            kl = zuweisungen.get(tid, [])
            td = techniker[tid]
            if not kl:
                result.append({"id": tid, "standort": td.get("standort", ""),
                               "kliniken": 0, "avg_fahrzeit": 0,
                               "max_fahrzeit": 0,
                               "fahrtstunden_jahr": 0, "onsite_stunden": 0,
                               "ratio": 0.0})
                continue
            avg_fz = sum(x["fz"] for x in kl) / len(kl)
            max_fz = max(x["fz"] for x in kl)
            total_stk = sum(x["stk"] for x in kl)
            drive_h = sum(x["stk"] * 2 * x["fz"] / 60 for x in kl)
            onsite_h = total_stk * 2.0
            result.append({
                "id": tid, "standort": td.get("standort", ""),
                "kliniken": len(kl), "avg_fahrzeit": round(avg_fz),
                "max_fahrzeit": round(max_fz),
                "fahrtstunden_jahr": round(drive_h),
                "onsite_stunden": round(onsite_h),
                "ratio": round(onsite_h / drive_h, 2) if drive_h else 0.0,
            })
        return result

    return _calc(False), _calc(True)


def _berechne_plz_abdeckung(
    techniker: dict[str, dict],
) -> list[dict]:
    """Berechnet Fahrzeit-Abdeckung fuer alle 2-stelligen PLZ-Bereiche."""
    ergebnis = []
    for plz2, (lat, lon) in sorted(_PLZ2_COORDS.items()):
        best_tid, best_km = "", float("inf")
        for tid, td in techniker.items():
            if not td.get("lat"):
                continue
            d = _haversine_km(td["lat"], td["lon"], lat, lon)
            if d < best_km:
                best_km, best_tid = d, tid
        faktor = _strassenfaktor(plz2 + "000")
        fz_min = best_km / (100.0 / faktor) * 60 if best_km < 9999 else 999
        if fz_min < 60:
            status = "gruen"
        elif fz_min < 90:
            status = "gelb"
        else:
            status = "rot"
        ergebnis.append({
            "plz2": plz2, "lat": lat, "lon": lon,
            "naechster_tech": best_tid, "distanz_km": round(best_km),
            "fahrzeit_min": round(fz_min), "status": status,
        })
    return ergebnis


# Optimierungsvorschlaege pro Techniker
_OPTIMIERUNGS_VORSCHLAEGE: dict[str, str] = {
    "T2":  "Gebiet zu gross fuer aktuelle L3-Abdeckung (1 Familie). "
           "Crosstraining priorisieren: Beatmung + Elektrochirurgie. "
           "Allgaeu-Anteil an T7 abgeben.",
    "T3":  "Sachsen/Brandenburg/Thueringen zu gross fuer 1 Techniker. "
           "Crosstraining-Kandidat fuer Ost-Expansion noetig. "
           "Kein geeigneter Partner in der Region vorhanden.",
    "T7":  "Uebernimmt Allgaeu-Kliniken von T2/T10/T14. "
           "+6 Kliniken, kuerzere Wege als BaWue-Sued-Techniker "
           "durch bessere Autobahnanbindung via A7/A96.",
    "T9":  "Nord-Ost (MV) ausbauen. T6 (Schenefeld) konzentriert "
           "sich auf SH/Niedersachsen/Bremen, T9 uebernimmt "
           "Hamburg-Ost + MV fuer kuerzere Wege.",
    "T10": "Allgaeu/West-Bayern (PLZ 87/88) an T7 abgeben. "
           "Reduziert Gebiet auf kompaktes BaWue-Kerngebiet "
           "(Tuebingen, Ulm, Stuttgart).",
    "T13": "Nur 1 L3-Familie (Kardiovaskulaer_Ablation). "
           "Crosstraining mit T10 priorisieren fuer breitere "
           "Einsetzbarkeit in NRW-Sued/Rheinland-Pfalz.",
    "T8":  "Nur 1 L3-Familie (Neurophysiologie). "
           "Crosstraining mit T10 priorisieren. "
           "NRW-Ueberlastung: 527 STK/a ungenutztes Potenzial.",
}


def _render_gebietsplanung(
    metriken_akt: list[dict],
    metriken_opt: list[dict],
    plz_abdeckung: list[dict] | None = None,
) -> str:
    if not metriken_akt:
        return ""

    def _ampel(ratio: float) -> tuple[str, str]:
        if ratio >= 3.0:
            return "gebiets-gruen", "GRÜN"
        if ratio >= 2.0:
            return "gebiets-gelb", "GELB"
        return "gebiets-rot", "ROT"

    def _rows(metriken: list[dict], prefix: str) -> str:
        lines = []
        vis = "table-row" if prefix == "aktuell" else "none"
        for m in metriken:
            css, _ = _ampel(m["ratio"])
            max_warn = " !" if m.get("max_fahrzeit", 0) > 90 else ""
            vorschlag = _OPTIMIERUNGS_VORSCHLAEGE.get(m["id"], "")
            detail_id = f'detail-{prefix}-{m["id"]}'
            lines.append(
                f'      <tr class="gebiets-row gebiets-{prefix} {css}" '
                f'style="display:{vis};cursor:pointer" '
                f'onclick="document.getElementById(\'{detail_id}\').style.display='
                f'document.getElementById(\'{detail_id}\').style.display===\'none\'?'
                f'\'table-row\':\'none\'">'
                f'<td><span class="gebiets-ampel-dot {css}"></span>'
                f'<strong>{m["id"]}</strong> '
                f'<span class="sub">({m["standort"]})</span></td>'
                f'<td>{m["kliniken"]}</td>'
                f'<td>{m["avg_fahrzeit"]} min</td>'
                f'<td>{m.get("max_fahrzeit", 0)} min{max_warn}</td>'
                f'<td>{m["fahrtstunden_jahr"]}</td>'
                f'<td>{m["onsite_stunden"]}</td>'
                f'<td><span class="badge badge-ratio {css}">'
                f'{m["ratio"]}</span></td></tr>')
            if vorschlag:
                lines.append(
                    f'      <tr id="{detail_id}" class="gebiets-{prefix} '
                    f'gebiets-detail" style="display:none">'
                    f'<td colspan="7"><div class="gebiets-detail-box">'
                    f'<strong>Optimierungsvorschlag {m["id"]}:</strong> '
                    f'{vorschlag}</div></td></tr>')
            else:
                lines.append(
                    f'      <tr id="{detail_id}" class="gebiets-{prefix} '
                    f'gebiets-detail" style="display:none">'
                    f'<td colspan="7"><div class="gebiets-detail-box">'
                    f'Keine Optimierung empfohlen &mdash; Gebiet effizient.'
                    f'</div></td></tr>')
        return "\n".join(lines)

    rows_akt = _rows(metriken_akt, "aktuell")
    rows_opt = _rows(metriken_opt, "optimiert")

    # Fahrzeitbilanz: nur Einsparungen zaehlen (Allgaeu-Shift)
    bawue_saving = 0
    for tid in ("T2", "T10", "T14"):
        a = next((m for m in metriken_akt if m["id"] == tid), None)
        o = next((m for m in metriken_opt if m["id"] == tid), None)
        if a and o:
            bawue_saving += max(0, a["fahrtstunden_jahr"] - o["fahrtstunden_jahr"])

    # Ampel-Zusammenfassung Techniker
    gruen = sum(1 for m in metriken_akt if m["ratio"] >= 3.0)
    gelb = sum(1 for m in metriken_akt if 2.0 <= m["ratio"] < 3.0)
    rot = sum(1 for m in metriken_akt if m["ratio"] < 2.0 and m["kliniken"] > 0)
    ueber_90 = sum(1 for m in metriken_akt if m.get("max_fahrzeit", 0) > 90)

    # PLZ-Abdeckung Zusammenfassung
    abd = plz_abdeckung or []
    plz_gruen = sum(1 for p in abd if p["status"] == "gruen")
    plz_gelb = sum(1 for p in abd if p["status"] == "gelb")
    plz_rot = sum(1 for p in abd if p["status"] == "rot")
    plz_total = len(abd)

    # Einstellungsempfehlungen: HTML-Liste (rechts neben Karte)
    _STERN_DETAILS = {
        "Berlin":   "12 Kliniken &middot; T3 Weimar 180 min",
        "Hannover": "8 Kliniken &middot; T9 Hamburg 95 min",
        "München":  "10 Kliniken &middot; T7 Wildenberg 110 min",
        "Mannheim": "6 Kliniken &middot; T12 Frankfurt 85 min",
    }
    einst_items = []
    for emp in _EINSTELLUNGS_EMPFEHLUNGEN:
        detail = _STERN_DETAILS.get(emp["standort"], f'{emp["kliniken_geschaetzt"]} Kliniken')
        einst_items.append(
            f'      <div class="einst-item">'
            f'<div class="einst-dot">\u2605</div>'
            f'<div class="einst-text">'
            f'<div class="einst-name">Grossraum {emp["standort"]}</div>'
            f'<div class="einst-detail">{detail}</div>'
            f'<div class="einst-detail" style="margin-top:4px;color:rgba(255,255,255,.4)">{emp["region"]}</div>'
            f'</div></div>')
    einst_liste_html = "\n".join(einst_items)

    # Einstellungsempfehlungen Tabelle (unterhalb des Flex-Layouts)
    einst_rows = []
    for emp in _EINSTELLUNGS_EMPFEHLUNGEN:
        einst_rows.append(
            f'      <tr><td><strong>{emp["standort"]}</strong></td>'
            f'<td>{emp["region"]}</td>'
            f'<td>{len(emp["abdeckt_plz"])} PLZ-Bereiche</td>'
            f'<td>~{emp["kliniken_geschaetzt"]}</td>'
            f'<td class="fehlend-liste">{emp["begruendung"]}</td></tr>')
    einst_html = "\n".join(einst_rows)

    return f"""
  <section>
    <h2>4 &mdash; Gebietsplanung &mdash; Fahrzeit-Optimierung</h2>
    <p class="section-hint">
      Fahrzeit-basierte Gebietsberechnung &middot;
      Autobahn 1.0x (60&thinsp;min/100km) &middot;
      Bundesstra&szlig;e 1.5x (90&thinsp;min) &middot;
      Landstra&szlig;e 2.0x (120&thinsp;min) &middot;
      Ziel: max 90&thinsp;min zum weitesten Kunden &middot;
      Klick auf Zeile f&uuml;r Details
    </p>
    <div class="gebiets-summary">
      <span><span class="dot dot-gruen"></span> <strong>{gruen}</strong> effizient (Ratio &ge;3.0)</span>
      <span><span class="dot dot-gelb"></span> <strong>{gelb}</strong> optimierbar (2.0&ndash;3.0)</span>
      <span><span class="dot dot-rot"></span> <strong>{rot}</strong> dringend (Ratio &lt;2.0)</span>
      <span style="margin-left:auto"><strong>{ueber_90}</strong> Techniker &gt;90&thinsp;min zum weitesten Kunden</span>
    </div>
    <div class="go-view-buttons" id="go-view-buttons-plan">
      <button class="go-view-btn active" data-view="aktuell" data-target="plan">Aktuelle Gebiete</button>
      <button class="go-view-btn" data-view="optimiert" data-target="plan">Optimierte Gebiete</button>
    </div>
    <div class="gebiets-layout">
      <div class="gebiets-karte">
        <svg id="germany-map" width="480" height="580"><!-- filled by _build_gebiets_svg --></svg>
        <div class="gebiets-legende" id="gebiets-legende"></div>
      </div>
      <div class="gebiets-metriken">
        <table>
          <thead>
            <tr>
              <th>Techniker</th>
              <th>Kliniken</th>
              <th>&Oslash; Fahrzeit</th>
              <th>Max Fahrzeit</th>
              <th>Fahrt h/a</th>
              <th>Onsite h/a</th>
              <th>Ratio</th>
            </tr>
          </thead>
          <tbody id="gebiets-tbody">
{rows_akt}
{rows_opt}
          </tbody>
        </table>
        <div class="gebiets-team-saving">
          <strong>Allg&auml;u-Shift Einsparung:</strong>
          BaW&uuml;-S&uuml;d (T2/T10/T14) spart {bawue_saving}&thinsp;h Fahrzeit/Jahr
          durch Verlagerung PLZ 87/88 an T7
        </div>
      </div>
    </div>
  </section>

  <section>
    <h2>5 &mdash; PLZ-Abdeckung &amp; Einstellungsbedarf</h2>
    <p class="section-hint">
      Analyse aller {plz_total} PLZ-Bereiche (2-stellig) &middot;
      Gr&uuml;n &lt;60&thinsp;min &middot; Gelb 60&ndash;90&thinsp;min &middot;
      Rot &gt;90&thinsp;min vom n&auml;chsten Techniker &middot;
      Sterne = empfohlene Neueinstellungs-Standorte
    </p>
    <div class="gebiets-summary">
      <span><span class="dot dot-gruen"></span> <strong>{plz_gruen}</strong> PLZ gut abgedeckt (&lt;60&thinsp;min)</span>
      <span><span class="dot dot-gelb"></span> <strong>{plz_gelb}</strong> PLZ grenzwertig (60&ndash;90&thinsp;min)</span>
      <span><span class="dot dot-rot"></span> <strong>{plz_rot}</strong> PLZ unterversorgt (&gt;90&thinsp;min)</span>
    </div>

    <div class="einst-layout">
      <div class="einst-karte">
        <svg id="germany-map-plz" viewBox="0 0 480 580" preserveAspectRatio="xMidYMid meet"><!-- filled by _build_gebiets_svg --></svg>
      </div>
      <div class="einst-liste">
        <div class="einst-liste-header">&starf; Einstellungsbedarf</div>
{einst_liste_html}
      </div>
    </div>

    <h3 style="font-size:14px;color:rgba(255,255,255,.87);margin:20px 0 10px;padding-bottom:8px;border-bottom:1px solid rgba(255,255,255,.09)">
      Detaillierte Begr&uuml;ndungen
    </h3>
    <table>
      <thead>
        <tr>
          <th>Standort</th>
          <th>Region</th>
          <th>Abdeckung</th>
          <th>Kliniken</th>
          <th>Begr&uuml;ndung</th>
        </tr>
      </thead>
      <tbody>
{einst_html}
      </tbody>
    </table>
  </section>"""


def _project_mercator(
    lon: float, lat: float,
    cx: float = 10.4, cy: float = 51.1, scale: float = 3200,
    w: float = 480, h: float = 580,
) -> tuple[float, float]:
    """Mercator-Projektion (konsistent mit der bisherigen d3-Projektion)."""
    x = (lon - cx) * math.pi / 180
    y = math.log(math.tan(math.pi / 4 + lat * math.pi / 360))
    cy_r = math.log(math.tan(math.pi / 4 + cy * math.pi / 360))
    return round(w / 2 + x * scale, 1), round(h / 2 - (y - cy_r) * scale, 1)


def _topo_to_svg_paths() -> list[dict]:
    """Wandelt daten/deutschland_topo.json in SVG-Pfade um (server-seitig).

    Returns:
        [{name: str, d: str}, ...] – SVG path 'd' Attribut je Bundesland.
    """
    topo_path = Path(__file__).parent.parent / "daten" / "deutschland_topo.json"
    try:
        topo = json.loads(topo_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        warnings.warn(f"deutschland_topo.json nicht gefunden: {topo_path}", stacklevel=2)
        return []

    arcs_raw = topo["arcs"]
    transform = topo.get("transform")
    obj_key = list(topo["objects"].keys())[0]
    geometries = topo["objects"][obj_key]["geometries"]

    def decode_arc(arc_idx: int) -> list[tuple[float, float]]:
        reverse = arc_idx < 0
        idx = ~arc_idx if reverse else arc_idx
        raw = arcs_raw[idx]
        coords: list[tuple[float, float]] = []
        x, y = 0, 0
        for dx, dy in raw:
            x += dx
            y += dy
            if transform:
                lon = x * transform["scale"][0] + transform["translate"][0]
                lat = y * transform["scale"][1] + transform["translate"][1]
            else:
                lon, lat = float(x), float(y)
            coords.append((lon, lat))
        if reverse:
            coords.reverse()
        return coords

    def geom_to_path_d(geom: dict) -> str:
        if geom["type"] == "Polygon":
            rings_list = [geom["arcs"]]
        elif geom["type"] == "MultiPolygon":
            rings_list = geom["arcs"]
        else:
            return ""
        parts: list[str] = []
        for rings in rings_list:
            for ring in rings:
                coords: list[tuple[float, float]] = []
                for arc_idx in ring:
                    coords.extend(decode_arc(arc_idx))
                # Simplify: keep every Nth point (smooth enough for 480px map)
                n = max(1, len(coords) // 80)
                simplified = coords[::n]
                if len(simplified) < 3:
                    simplified = coords
                for i, (lon, lat) in enumerate(simplified):
                    px, py = _project_mercator(lon, lat)
                    parts.append(f"M{px},{py}" if i == 0 else f"L{px},{py}")
                parts.append("Z")
        return "".join(parts)

    result: list[dict] = []
    for geom in geometries:
        name = geom.get("properties", {}).get("name", "")
        d = geom_to_path_d(geom)
        if d:
            result.append({"name": name, "d": d})
    return result


def _build_gebiets_svg(
    techniker: dict[str, dict],
    plz_abdeckung: list[dict] | None = None,
) -> str:
    """Baut statische SVG-Karte (100% offline, kein CDN, kein JavaScript noetig)."""
    paths = _topo_to_svg_paths()
    if not paths:
        return '<text x="240" y="290" text-anchor="middle" fill="rgba(255,255,255,.5)" font-size="13">Karte nicht verfuegbar</text>'

    svg_parts: list[str] = []

    # 1. Bundesland-Flaechen
    for p in paths:
        name = p["name"]
        tid = _GEBIET_AKTUELL.get(name, "")
        fill = _TECH_FARBEN.get(tid, "#1a2030")
        tid_opt = _GEBIET_OPTIMIERT.get(name, "")
        fill_opt = _TECH_FARBEN.get(tid_opt, "#1a2030")
        tooltip = f"{name} → {tid}" if tid else f"{name} (nicht zugewiesen)"
        # Overlap/Gap Marker fuer Luecken-Ansicht
        _OVERLAP_STATES = {"Nordrhein-Westfalen": "1", "Bayern": "1"}
        _GAP_STATES = {"Mecklenburg-Vorpommern": "gap", "Brandenburg": "gap"}
        overlap = _OVERLAP_STATES.get(name, _GAP_STATES.get(name, ""))
        ov_attr = f' data-overlap="{overlap}"' if overlap else ''
        svg_parts.append(
            f'<path class="st" d="{p["d"]}" fill="{fill}" '
            f'data-name="{name}" data-fill-aktuell="{fill}" data-fill-optimiert="{fill_opt}"{ov_attr} '
            f'stroke="rgba(255,255,255,.15)" stroke-width="1.2">'
            f'<title>{tooltip}</title></path>'
        )

    # 2. PLZ-Abdeckungspunkte
    status_colors = {"gruen": "#5EDD9F", "gelb": "#FFB347", "rot": "#FF8080"}
    for p in (plz_abdeckung or []):
        px, py = _project_mercator(p["lon"], p["lat"])
        fc = status_colors.get(p["status"], "#555")
        svg_parts.append(
            f'<circle class="plz" cx="{px}" cy="{py}" r="3" fill="{fc}" opacity="0.5">'
            f'<title>PLZ {p["plz2"]}xxx: {p["fahrzeit_min"]} min ({p["naechster_tech"]})</title></circle>'
        )

    # 3. Techniker-Standorte
    for tid, td in sorted(techniker.items()):
        if not td.get("lat"):
            continue
        px, py = _project_mercator(td["lon"], td["lat"])
        fc = _TECH_FARBEN.get(tid, "#999")
        standort = td.get("standort", "")
        svg_parts.append(
            f'<circle class="td" cx="{px}" cy="{py}" r="6" fill="{fc}" '
            f'stroke="#fff" stroke-width="2">'
            f'<title>{tid} ({standort})</title></circle>'
        )
        svg_parts.append(
            f'<text class="tl" x="{px + 9}" y="{py + 4}" '
            f'font-family="Plus Jakarta Sans,sans-serif" font-size="10px" font-weight="700" fill="rgba(255,255,255,.87)">'
            f'{tid}</text>'
        )

    # 4. Einstellungsempfehlungen (roter Kreis + weisser Stern)
    for idx, e in enumerate(_EINSTELLUNGS_EMPFEHLUNGEN):
        px, py = _project_mercator(e["lon"], e["lat"])

        svg_parts.append(
            f'<g class="einst-marker" data-idx="{idx}" style="cursor:pointer">'
        )
        svg_parts.append(
            f'<circle cx="{px}" cy="{py}" r="10" fill="#CC0000" '
            f'stroke="#fff" stroke-width="2">'
            f'<title>{e["standort"]}: {e["kliniken_geschaetzt"]} Kliniken</title></circle>'
        )
        svg_parts.append(
            f'<text x="{px}" y="{py + 5}" font-size="13px" fill="#fff" '
            f'text-anchor="middle" style="pointer-events:none">'
            f'\u2605</text>'
        )
        svg_parts.append('</g>')

    return "\n    ".join(svg_parts)


def _build_gebiets_script(
    techniker: dict[str, dict],
    plz_abdeckung: list[dict] | None = None,
) -> str:
    """Baut minimales JS fuer Modus-Umschaltung (aktuell/optimiert)."""
    tc = json.dumps(_TECH_FARBEN, ensure_ascii=False)

    return (
        "/* ── Gebietsplanung (offline, pre-rendered SVG) ── */\n"
        "(function(){\n"
        "  var C=" + tc + ";\n"
        "  /* Gebietsplanung Tab: Button-Umschaltung aktuell/optimiert */\n"
        "  var planBtns=document.querySelectorAll('#go-view-buttons-plan .go-view-btn');\n"
        "  planBtns.forEach(function(btn){\n"
        "    btn.addEventListener('click',function(){\n"
        "      var m=this.getAttribute('data-view');\n"
        "      planBtns.forEach(function(b){b.classList.remove('active');});\n"
        "      this.classList.add('active');\n"
        "      var map=document.getElementById('germany-map');\n"
        "      if(map){map.querySelectorAll('path.st').forEach(function(p){\n"
        "        p.setAttribute('fill',p.getAttribute('data-fill-'+m)||'#1a2030');\n"
        "      });}\n"
        "      document.querySelectorAll('.gebiets-aktuell').forEach(function(r){\n"
        "        r.style.display=m==='aktuell'?'table-row':'none';});\n"
        "      document.querySelectorAll('.gebiets-optimiert').forEach(function(r){\n"
        "        r.style.display=m==='optimiert'?'table-row':'none';});\n"
        "    });\n"
        "  });\n"
        "  ['gebiets-legende','gebiets-legende-opt'].forEach(function(id){\n"
        "    var lg=document.getElementById(id);\n"
        "    if(lg){Object.keys(C).sort().forEach(function(t){\n"
        "      lg.innerHTML+='<span class=\"gebiets-legende-item\">'\n"
        "        +'<span class=\"gebiets-legende-dot\" style=\"background:'+C[t]+'\"></span>'\n"
        "        +t+'</span>';});\n"
        "    }\n"
        "  });\n"
        "})();\n"
        "\n"
        "/* ── Einstellungsempfehlung: Hover-Sync ── */\n"
        "(function(){\n"
        "  function hlStern(idx, on) {\n"
        "    var m = document.querySelector('.einst-marker[data-idx=\"'+idx+'\"]');\n"
        "    if (!m) return;\n"
        "    var c = m.querySelector('circle');\n"
        "    if (c) { c.setAttribute('r', on ? '14' : '10');\n"
        "             c.setAttribute('fill', on ? '#990000' : '#CC0000'); }\n"
        "  }\n"
        "  function hlItem(idx, on) {\n"
        "    var items = document.querySelectorAll('.einst-item');\n"
        "    if (items[idx]) {\n"
        "      items[idx].style.background = on ? 'rgba(204,0,0,.12)' : '';\n"
        "      items[idx].style.boxShadow  = on ? '0 0 0 2px #CC0000' : '';\n"
        "    }\n"
        "  }\n"
        "  document.querySelectorAll('.einst-marker').forEach(function(m) {\n"
        "    var idx = parseInt(m.getAttribute('data-idx'), 10);\n"
        "    m.addEventListener('mouseenter', function() { hlItem(idx, true);  hlStern(idx, true);  });\n"
        "    m.addEventListener('mouseleave', function() { hlItem(idx, false); hlStern(idx, false); });\n"
        "    m.addEventListener('click',      function() {\n"
        "      var items = document.querySelectorAll('.einst-item');\n"
        "      if (items[idx]) items[idx].scrollIntoView({behavior:'smooth', block:'nearest'});\n"
        "    });\n"
        "  });\n"
        "  document.querySelectorAll('.einst-item').forEach(function(item, idx) {\n"
        "    item.addEventListener('mouseenter', function() { hlStern(idx, true);  hlItem(idx, true);  });\n"
        "    item.addEventListener('mouseleave', function() { hlStern(idx, false); hlItem(idx, false); });\n"
        "  });\n"
        "  document.querySelectorAll('.einst-marker').forEach(function(m, idx) {\n"
        "    var c = m.querySelector('circle');\n"
        "    if (!c) return;\n"
        "    var cx = parseFloat(c.getAttribute('cx'));\n"
        "    var cy = parseFloat(c.getAttribute('cy'));\n"
        "    var ns = 'http://www.w3.org/2000/svg';\n"
        "    var t = document.createElementNS(ns, 'text');\n"
        "    t.setAttribute('x', cx + 8);\n"
        "    t.setAttribute('y', cy - 8);\n"
        "    t.setAttribute('font-size', '10px');\n"
        "    t.setAttribute('font-weight', '700');\n"
        "    t.setAttribute('fill', '#FF8080');\n"
        "    t.setAttribute('font-family', 'Plus Jakarta Sans, sans-serif');\n"
        "    t.setAttribute('style', 'pointer-events:none');\n"
        "    t.textContent = (idx + 1).toString();\n"
        "    m.appendChild(t);\n"
        "    var items = document.querySelectorAll('.einst-item');\n"
        "    if (items[idx]) {\n"
        "      var dot = items[idx].querySelector('.einst-dot');\n"
        "      if (dot) dot.setAttribute('data-num', idx + 1);\n"
        "    }\n"
        "  });\n"
        "})();\n"
        "\n"
        "/* ── Gebietsoptimierung: View-Button Umschaltung ── */\n"
        "(function(){\n"
        "  var btns=document.querySelectorAll('.go-view-btn');\n"
        "  var views=document.querySelectorAll('.go-view-content');\n"
        "  var svg=document.getElementById('germany-map-opt');\n"
        "  if(!btns.length) return;\n"
        "  btns.forEach(function(btn){\n"
        "    btn.addEventListener('click',function(){\n"
        "      var mode=this.getAttribute('data-view');\n"
        "      btns.forEach(function(b){b.classList.remove('active');});\n"
        "      this.classList.add('active');\n"
        "      views.forEach(function(v){v.classList.remove('active');});\n"
        "      var target=document.getElementById('go-view-'+mode);\n"
        "      if(target) target.classList.add('active');\n"
        "      /* SVG-Karte aktualisieren */\n"
        "      if(svg){\n"
        "        svg.querySelectorAll('path.st').forEach(function(p){\n"
        "          if(mode==='luecken'){\n"
        "            var ov=p.getAttribute('data-overlap');\n"
        "            if(ov==='1'){\n"
        "              p.setAttribute('fill','rgba(255,139,0,.3)');\n"
        "              p.setAttribute('stroke','#FF8B00');p.setAttribute('stroke-width','3');\n"
        "            }else if(ov==='gap'){\n"
        "              p.setAttribute('fill','rgba(204,0,0,.3)');\n"
        "              p.setAttribute('stroke','#CC0000');p.setAttribute('stroke-width','3');\n"
        "              p.setAttribute('stroke-dasharray','6,3');\n"
        "            }else{\n"
        "              p.setAttribute('fill',p.getAttribute('data-fill-aktuell')||'#1a2030');\n"
        "              p.setAttribute('stroke','rgba(255,255,255,.08)');p.setAttribute('stroke-width','1');\n"
        "              p.removeAttribute('stroke-dasharray');\n"
        "            }\n"
        "          }else{\n"
        "            var fillKey='data-fill-'+(mode==='optimiert'?'optimiert':'aktuell');\n"
        "            p.setAttribute('fill',p.getAttribute(fillKey)||'#1a2030');\n"
        "            p.setAttribute('stroke','rgba(255,255,255,.15)');p.setAttribute('stroke-width','1.2');\n"
        "            p.removeAttribute('stroke-dasharray');\n"
        "          }\n"
        "        });\n"
        "      }\n"
        "    });\n"
        "  });\n"
        "})();\n"
    )


# ---------------------------------------------------------------------------
# Sort-Dropdown Script
# ---------------------------------------------------------------------------

_SORT_SCRIPT = """
  (function () {
    var keyMap = {
      standard:      'sortStandard',
      crosstraining: 'sortCrosstraining',
      auslastung:    'sortAuslastung',
      portfolio:     'sortPortfolio',
      potential:     'sortPotential'
    };

    function sortAmpelGrid(mode) {
      var grid  = document.getElementById('ampel-grid');
      var cards = Array.prototype.slice.call(grid.querySelectorAll('.ampel-karte'));
      var key   = keyMap[mode];

      cards.sort(function (a, b) {
        var va = parseFloat(a.dataset[key]);
        var vb = parseFloat(b.dataset[key]);
        return mode === 'standard' ? va - vb : vb - va;
      });

      grid.querySelectorAll('.metric-box').forEach(function (el) {
        el.style.display = 'none';
      });
      grid.querySelectorAll('.metric-' + mode).forEach(function (el) {
        el.style.display = 'block';
      });

      cards.forEach(function (card) { grid.appendChild(card); });
    }

    document.getElementById('ampel-sort-select')
      .addEventListener('change', function () { sortAmpelGrid(this.value); });
  }());"""


# ---------------------------------------------------------------------------
# Premium Dark Design – CSS
# ---------------------------------------------------------------------------

_CSS = """\
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;0,800;1,400&family=Syne:wght@400;500;600;700;800&display=swap');
    :root {
      --bg:           #000810;
      --card-bg:      rgba(255,255,255,.03);
      --card-border:  rgba(255,255,255,.09);
      --nav-bg:       rgba(0,8,20,.7);
      --primary:      #0072CE;
      --accent:       #00A3E0;
      --success:      #00875A;
      --success-text: #5EDD9F;
      --warning:      #FF8B00;
      --warning-text: #FFB347;
      --critical:     #CC0000;
      --critical-text:#FF8080;
      --demo:         #FFD060;
      --text:         rgba(255,255,255,.87);
      --text-dim:     rgba(255,255,255,.5);
      --text-muted:   rgba(255,255,255,.3);
      --font-body:    'Plus Jakarta Sans', sans-serif;
      --font-heading: 'Syne', sans-serif;
      --grad-accent:  linear-gradient(135deg, #00A3E0, #6EC6FF);
      --grad-primary: linear-gradient(135deg, #0072CE, #00A3E0);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: var(--font-body);
      background: var(--bg);
      color: var(--text);
      font-size: 14px;
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
      scrollbar-width: thin;
      scrollbar-color: rgba(255,255,255,.1) transparent;
    }
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: rgba(255,255,255,.1); border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,.18); }

    /* ── Grain Overlay ── */
    .grain-overlay {
      position: fixed;
      inset: 0;
      pointer-events: none;
      z-index: 9999;
      opacity: 0.025;
      background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='1'/%3E%3C/svg%3E");
      background-repeat: repeat;
      background-size: 180px 180px;
      mix-blend-mode: overlay;
    }

    /* ── App Layout ── */
    .app-layout {
      display: flex;
      min-height: 100vh;
    }
    .dashboard-panel {
      flex: 1;
      min-width: 0;
      display: flex;
      flex-direction: column;
    }

    /* ── Hero Header ── */
    header {
      background: rgba(0,8,20,.85);
      backdrop-filter: blur(28px);
      -webkit-backdrop-filter: blur(28px);
      color: #fff;
      padding: 0 32px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      height: 60px;
      position: sticky;
      top: 0;
      z-index: 100;
      border-bottom: 1px solid rgba(255,255,255,.08);
    }
    .header-brand {
      display: flex;
      align-items: center;
      gap: 16px;
    }
    .header-logo {
      font-family: var(--font-heading);
      font-size: 22px;
      font-weight: 800;
      letter-spacing: .3px;
      background: var(--grad-accent);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }
    .header-logo .brand-ai {
      background: var(--grad-accent);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      font-weight: 800;
    }
    .header-sub {
      font-size: 11px;
      color: var(--text-muted);
      font-weight: 500;
      letter-spacing: .04em;
    }
    .header-right {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .demo-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: rgba(255,208,96,.1);
      color: var(--demo);
      border: 1px solid rgba(255,208,96,.2);
      border-radius: 20px;
      padding: 5px 16px;
      font-size: 11px;
      font-weight: 600;
      letter-spacing: .04em;
    }
    .lang-toggle, .api-key-btn {
      background: rgba(255,255,255,.05);
      color: var(--text-dim);
      border: 1px solid rgba(255,255,255,.1);
      border-radius: 20px;
      padding: 6px 16px;
      font-family: var(--font-body);
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      transition: all .2s ease;
      letter-spacing: .03em;
    }
    .lang-toggle:hover, .api-key-btn:hover {
      background: rgba(255,255,255,.1);
      color: #fff;
      border-color: rgba(255,255,255,.25);
      box-shadow: 0 0 12px rgba(0,163,224,.15);
    }

    /* ── Summary Bar ── */
    .summary-bar {
      background: rgba(255,255,255,.02);
      border-bottom: 1px solid var(--card-border);
      padding: 10px 32px;
      display: flex;
      gap: 28px;
      font-size: 13px;
      align-items: center;
    }
    .summary-bar span { display: flex; align-items: center; gap: 6px; }
    .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
    .dot-gruen { background: var(--success-text); }
    .dot-gelb  { background: var(--warning-text); }
    .dot-rot   { background: var(--critical-text); }

    /* ── Layout ── */
    main { padding: 24px 32px; display: flex; flex-direction: column; gap: 24px; flex: 1; }
    section {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 28px 32px;
      transition: background .2s ease, box-shadow .2s ease;
    }
    section:hover {
      background: rgba(255,255,255,.05);
      box-shadow: 0 4px 24px rgba(0,0,0,.3);
    }
    section h2 {
      font-family: var(--font-heading);
      font-size: 17px;
      font-weight: 700;
      color: var(--text);
      margin-bottom: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid rgba(255,255,255,.06);
      letter-spacing: .02em;
    }
    .section-hint {
      font-size: 11px;
      color: var(--text-dim);
      margin-top: -10px;
      margin-bottom: 16px;
    }
    .tab-content { display: none; }
    .tab-content.active { display: block; }

    /* ── Techniker-Karten (Glassmorphism) ── */
    .ampel-grid {
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
    }
    .ampel-karte {
      border-radius: 16px;
      padding: 16px 18px;
      width: 170px;
      position: relative;
      border: 1px solid var(--card-border);
      border-top: 4px solid var(--text-muted);
      background: var(--card-bg);
      transition: transform .2s ease, box-shadow .2s ease, background .2s ease;
    }
    .ampel-karte:hover {
      transform: translateY(-2px);
      box-shadow: 0 8px 28px rgba(0,0,0,.35);
      background: rgba(255,255,255,.05);
    }
    .ampel-gruen {
      background: rgba(0,135,90,.06);
      border-color: rgba(94,221,159,.12);
      border-top-color: var(--success);
    }
    .ampel-gruen:hover { box-shadow: 0 8px 28px rgba(0,135,90,.15); }
    .ampel-gruen .ampel-id { background: var(--grad-accent); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
    .ampel-gruen .metric-num { color: var(--success-text); }
    .ampel-gelb {
      background: rgba(255,139,0,.06);
      border-color: rgba(255,179,71,.12);
      border-top-color: var(--warning);
    }
    .ampel-gelb:hover { box-shadow: 0 8px 28px rgba(255,139,0,.12); }
    .ampel-gelb .ampel-id { color: var(--warning-text); }
    .ampel-gelb .metric-num { color: var(--warning-text); }
    .ampel-rot {
      background: rgba(204,0,0,.06);
      border-color: rgba(255,128,128,.12);
      border-top-color: var(--critical);
    }
    .ampel-rot:hover { box-shadow: 0 8px 28px rgba(204,0,0,.12); }
    .ampel-rot .ampel-id { color: var(--critical-text); }
    .ampel-rot .metric-num { color: var(--critical-text); }
    .ampel-karte.hugo-border { border: 2px solid var(--primary); }
    .ampel-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 4px;
    }
    .ampel-id      { font-family: var(--font-heading); font-size: 2.2rem; font-weight: 800; line-height: 1; background: var(--grad-accent); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
    .ampel-standort{ font-size: 12px; color: var(--text-dim); }
    .ampel-region  { font-size: 10px; color: var(--text-muted); margin-bottom: 10px; }
    .ampel-badge {
      display: inline-block;
      border-radius: 4px;
      font-size: 10px;
      font-weight: 700;
      padding: 2px 7px;
      letter-spacing: .5px;
    }
    .ampel-gruen .ampel-badge { background: var(--success); color: #fff; }
    .ampel-gelb  .ampel-badge { background: var(--warning); color: #fff; }
    .ampel-rot   .ampel-badge { background: var(--critical); color: #fff; }

    .hugo-ka-badge {
      display: inline-block;
      background: rgba(0,114,206,.15);
      color: var(--accent);
      border: 1px solid rgba(0,163,224,.25);
      border-radius: 4px;
      font-size: 9px;
      font-weight: 700;
      padding: 1px 6px;
      letter-spacing: .3px;
      margin-bottom: 6px;
    }

    /* ── Sort Controls ── */
    .ampel-sort-controls {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 14px;
      flex-wrap: wrap;
    }
    .ampel-sort-controls label {
      font-size: 12px;
      font-weight: 600;
      color: var(--text-dim);
      white-space: nowrap;
    }
    .ampel-sort-controls select {
      font-family: var(--font-body);
      font-size: 12px;
      padding: 8px 14px;
      border: 1px solid var(--card-border);
      border-radius: 10px;
      background: rgba(255,255,255,.04);
      color: var(--text);
      cursor: pointer;
      min-width: 320px;
      outline: none;
      transition: all .2s ease;
    }
    .ampel-sort-controls select:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 2px rgba(0,163,224,.15);
    }
    .ampel-sort-controls select option {
      background: #0a1628;
      color: rgba(255,255,255,.87);
      padding: 8px 12px;
    }
    .ampel-sort-controls .demo-hint {
      font-size: 10px;
      color: var(--demo);
      font-style: italic;
    }

    /* ── Metric Box (stat-cell style) ── */
    .metric-box   { margin: 8px 0 2px; }
    .metric-num   { font-family: var(--font-heading); font-size: 24px; font-weight: 800; line-height: 1.1; background: var(--grad-accent); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
    .metric-lbl   { font-size: 10px; color: rgba(255,255,255,.4); margin-bottom: 3px; text-transform: uppercase; letter-spacing: .08em; }
    .metric-sub   { font-size: 10px; color: var(--text-muted); }
    .metric-italic{ font-style: italic; }

    /* ── Fortschrittsbalken ── */
    .auslastung-bar-wrap {
      position: relative;
      height: 5px;
      background: rgba(255,255,255,.07);
      border-radius: 3px;
      margin: 5px 0 3px;
      overflow: visible;
    }
    .auslastung-bar-fill {
      height: 100%;
      border-radius: 3px;
      min-width: 0;
      background: linear-gradient(90deg, #0072CE, #00A3E0);
    }
    .ampel-gruen .auslastung-bar-fill { background: linear-gradient(90deg, var(--success), #5EDD9F); }
    .ampel-gelb  .auslastung-bar-fill { background: linear-gradient(90deg, #E87000, var(--warning)); }
    .ampel-rot   .auslastung-bar-fill { background: linear-gradient(90deg, #990000, var(--critical)); }
    .auslastung-bar-ziel {
      position: absolute;
      top: -3px;
      width: 2px;
      height: 12px;
      background: var(--text);
      border-radius: 1px;
    }

    /* ── Tabellen ── */
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th {
      background: rgba(255,255,255,.03);
      text-align: left;
      padding: 10px 12px;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .5px;
      color: var(--text-dim);
      border-bottom: 1px solid var(--card-border);
    }
    td {
      padding: 10px 12px;
      border-bottom: 1px solid rgba(255,255,255,.04);
      vertical-align: middle;
      color: var(--text);
    }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: rgba(0,163,224,.04); }
    code { font-family: 'JetBrains Mono', 'Consolas', monospace; font-size: 12px; color: var(--accent); }
    .sub { color: var(--text-dim); font-size: 11px; }
    .fehlend-liste { font-size: 11px; color: var(--text-dim); max-width: 340px; }

    /* ── Dringlichkeit-Badges ── */
    .badge {
      display: inline-block;
      border-radius: 6px;
      padding: 3px 10px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .4px;
    }
    .badge-ueberfaellig { background: rgba(204,0,0,.2); color: var(--critical-text); border: 1px solid rgba(204,0,0,.3); }
    .badge-kritisch { background: rgba(204,0,0,.15); color: var(--critical-text); border: 1px solid rgba(204,0,0,.25); }
    .badge-hoch     { background: rgba(255,139,0,.15); color: var(--warning-text); border: 1px solid rgba(255,139,0,.25); }
    .badge-normal   { background: rgba(0,135,90,.15); color: var(--success-text); border: 1px solid rgba(0,135,90,.25); }
    .badge-blau     { background: rgba(0,163,224,.15); color: var(--accent); border: 1px solid rgba(0,163,224,.25); }
    .puls-animation { animation: puls 1.5s ease-in-out infinite; }
    @keyframes puls { 0%,100% { opacity:1; } 50% { opacity:0.5; } }

    /* ── Hugo Key Account Extras ── */
    .hugo-reserve {
      font-size: 9px;
      color: var(--accent);
      font-weight: 700;
      margin: 3px 0;
      padding: 2px 6px;
      background: rgba(0,114,206,.1);
      border-radius: 3px;
    }
    .hugo-warnung {
      font-size: 9px;
      color: var(--critical-text);
      font-weight: 700;
      margin: 3px 0;
      padding: 2px 6px;
      background: rgba(204,0,0,.12);
      border-radius: 3px;
    }

    /* ── Crosstraining Cluster-Badges ── */
    .cluster-badge {
      display: inline-block;
      border-radius: 4px;
      padding: 2px 8px;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: .3px;
      margin: 1px 2px;
    }
    .cluster-small-capital { background: rgba(0,135,90,.12); color: var(--success-text); }
    .cluster-hf-chirurgie  { background: rgba(232,112,0,.12); color: #E87000; }
    .cluster-1-or          { background: rgba(204,0,0,.12); color: var(--critical-text); }
    .cluster-2-cardiac     { background: rgba(204,0,0,.1); color: var(--critical-text); }
    .cluster-3-monitoring  { background: rgba(255,139,0,.12); color: var(--warning-text); }
    .cluster-4-digital     { background: rgba(0,114,206,.12); color: var(--accent); }

    /* ── Puffer-Visualisierung ── */
    .puffer-container { display: flex; flex-direction: column; gap: 8px; }
    .puffer-row {
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 12px 16px;
      cursor: pointer;
      transition: all .2s ease;
      background: var(--card-bg);
    }
    .puffer-row:hover { background: rgba(255,255,255,.04); box-shadow: 0 2px 12px rgba(0,0,0,.2); }
    .puffer-summary { font-size: 13px; margin-bottom: 6px; color: var(--text); }
    .puffer-gesamt { font-weight: 700; color: var(--accent); }
    .puffer-bar-wrap { display: flex; height: 20px; border-radius: 6px; overflow: hidden; font-size: 10px; }
    .puffer-bar-netto {
      background: linear-gradient(90deg, var(--success), #5EDD9F);
      color: #fff;
      display: flex; align-items: center; justify-content: center;
      font-weight: 700; min-width: 40px;
    }
    .puffer-bar-puffer {
      background: linear-gradient(90deg, #E87000, var(--warning));
      color: #fff;
      display: flex; align-items: center; justify-content: center;
      font-weight: 700; min-width: 40px;
    }
    .puffer-detail {
      margin-top: 10px;
      padding: 10px 14px;
      background: rgba(0,114,206,.05);
      border-left: 3px solid var(--primary);
      border-radius: 0 8px 8px 0;
      font-size: 12px;
      color: var(--text-dim);
    }
    .puffer-detail strong { color: var(--text); }
    .puffer-detail-grid { display: flex; flex-direction: column; gap: 6px; }
    .puffer-aufschluesselung { padding-left: 12px; }
    .puffer-item { display: flex; gap: 8px; font-size: 11px; }
    .puffer-label { color: var(--text-dim); min-width: 120px; }
    .puffer-val { font-weight: 700; color: var(--text); }
    .puffer-summe { border-top: 1px solid var(--card-border); padding-top: 4px; margin-top: 4px; }

    /* ── Workflow-Status ── */
    .wf-pipeline {
      display: flex;
      align-items: flex-start;
      gap: 0;
      flex-wrap: wrap;
      padding: 16px 0;
    }
    .wf-step {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
      padding: 12px 16px;
      min-width: 100px;
      text-align: center;
    }
    .wf-icon {
      font-size: 28px;
      line-height: 1;
    }
    .wf-label {
      font-family: var(--font-heading);
      font-size: 12px;
      font-weight: 600;
      color: var(--text);
    }
    .wf-badge {
      font-size: 9px;
      font-weight: 700;
      padding: 2px 8px;
      border-radius: 10px;
      letter-spacing: .3px;
      text-transform: uppercase;
    }
    .wf-badge-auto {
      background: rgba(0,114,206,.15);
      color: var(--accent);
      border: 1px solid rgba(0,114,206,.25);
    }
    .wf-badge-mensch {
      background: rgba(0,135,90,.15);
      color: var(--success-text);
      border: 1px solid rgba(0,135,90,.25);
    }
    .wf-detail {
      font-size: 10px;
      color: var(--text-muted);
    }
    .wf-arrow {
      color: var(--text-muted);
      font-size: 20px;
      display: flex;
      align-items: center;
      padding-top: 14px;
    }

    /* ── Business Case ── */
    .bc-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 16px;
      margin-bottom: 16px;
    }
    .bc-card {
      background: rgba(255,255,255,.02);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 20px;
      transition: all .2s ease;
    }
    .bc-card:hover { border-color: rgba(0,163,224,.25); background: rgba(255,255,255,.04); box-shadow: 0 4px 20px rgba(0,0,0,.25); }
    .bc-card-title {
      font-family: var(--font-heading);
      font-size: 13px;
      font-weight: 600;
      color: var(--accent);
      margin-bottom: 10px;
    }
    .bc-formula {
      font-family: 'JetBrains Mono', 'Consolas', monospace;
      font-size: 12px;
      color: var(--text);
      padding: 8px 12px;
      background: rgba(0,114,206,.06);
      border-radius: 6px;
      margin-bottom: 6px;
    }
    .bc-hint {
      font-size: 11px;
      color: var(--text-dim);
    }
    .bc-gold-hint {
      padding: 12px 16px;
      background: rgba(255,208,96,.08);
      border: 1px solid rgba(255,208,96,.2);
      border-radius: 8px;
      color: var(--demo);
      font-size: 12px;
      font-weight: 600;
    }

    /* ── Techniker-Detail Modal ── */
    .tech-detail-overlay {
      display: none;
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0,8,16,.85);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      z-index: 1000;
      justify-content: center;
      align-items: center;
    }
    .tech-detail-overlay.active { display: flex; }
    .tech-detail-panel {
      background: rgba(0,8,20,.95);
      border: 1px solid var(--card-border);
      border-radius: 20px;
      box-shadow: 0 24px 64px rgba(0,0,0,.6);
      backdrop-filter: blur(28px);
      -webkit-backdrop-filter: blur(28px);
      max-width: 720px;
      width: 90%;
      max-height: 85vh;
      overflow-y: auto;
      padding: 28px 32px;
      position: relative;
    }
    .tech-detail-close {
      position: absolute;
      top: 12px; right: 16px;
      background: none; border: none;
      font-size: 22px; cursor: pointer;
      color: var(--text-dim);
      line-height: 1;
    }
    .tech-detail-close:hover { color: var(--critical-text); }
    .tech-detail-title {
      font-family: var(--font-heading);
      font-size: 18px;
      font-weight: 700;
      color: var(--text);
      margin-bottom: 16px;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--card-border);
    }
    .tech-detail-kpis {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 16px;
    }
    .tech-detail-kpi {
      flex: 1;
      min-width: 140px;
      background: rgba(255,255,255,.03);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 12px 14px;
    }
    .tech-detail-kpi .kpi-val { font-family: var(--font-heading); font-size: 20px; font-weight: 800; background: var(--grad-accent); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
    .tech-detail-kpi .kpi-lbl { font-size: 11px; color: var(--text-dim); }

    /* ── NRW-Warnung ── */
    .warnung-box {
      background: rgba(255,139,0,.06);
      border: 1px solid rgba(255,139,0,.2);
      border-radius: 12px;
      padding: 20px 24px;
    }
    .warnung-box h2 {
      border-bottom-color: rgba(255,139,0,.2);
      color: var(--warning-text);
    }
    .warnung-box .warnung-stats { margin-bottom: 10px; color: var(--text-dim); font-size: 13px; }
    .warnung-box .warnung-stats strong { color: var(--warning-text); }
    .warnung-box ul { margin: 0 0 12px 20px; }
    .warnung-box li { margin-bottom: 5px; color: var(--text-dim); font-size: 13px; }
    .warnung-box li strong { color: var(--text); }
    .warnung-hinweis {
      margin-top: 10px;
      padding: 10px 14px;
      background: rgba(255,139,0,.08);
      border-radius: 8px;
      font-size: 12px;
      color: var(--warning-text);
    }

    /* ── Footer ── */
    footer {
      background: rgba(0,8,20,.85);
      backdrop-filter: blur(28px);
      -webkit-backdrop-filter: blur(28px);
      text-align: center;
      padding: 20px 32px;
      font-size: 11px;
      color: var(--text-muted);
      border-top: 1px solid var(--card-border);
      letter-spacing: .03em;
    }

    /* ── Gebietsplanung ── */
    .gebiets-layout {
      display: flex;
      gap: 24px;
      align-items: flex-start;
    }
    .gebiets-karte { flex-shrink: 0; }
    .gebiets-karte svg {
      border: 1px solid rgba(255,255,255,.09);
      border-radius: 14px;
      background: #000D2A;
    }
    .gebiets-karte svg path.st { opacity: .7; transition: opacity .2s ease; }
    .gebiets-karte svg path.st:hover { opacity: .9; }
    .gebiets-karte svg circle.td { filter: drop-shadow(0 0 4px rgba(0,163,224,.4)); }
    .gebiets-metriken { flex: 1; min-width: 0; overflow-x: auto; }

    /* Einstellungsbedarf */
    .einst-layout {
      display: flex;
      gap: 24px;
      align-items: flex-start;
    }
    .einst-karte { flex: 0 0 60%; min-width: 0; }
    .einst-karte svg {
      border: 1px solid rgba(255,255,255,.09);
      border-radius: 14px;
      background: #000D2A;
      width: 100%;
      height: auto;
    }
    .einst-liste { flex: 0 0 38%; }
    .einst-liste-header {
      font-family: var(--font-heading);
      font-weight: 700;
      color: var(--critical-text);
      font-size: 15px;
      margin-bottom: 12px;
    }
    .einst-item {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 12px 14px;
      margin-bottom: 8px;
      border: 1px solid var(--card-border);
      border-radius: 14px;
      background: var(--card-bg);
      transition: all .2s ease;
    }
    .einst-item:hover { box-shadow: 0 4px 20px rgba(0,0,0,.35); border-color: rgba(255,255,255,.15); background: rgba(255,255,255,.05); }
    .einst-dot {
      flex-shrink: 0;
      width: 28px;
      height: 28px;
      border-radius: 50%;
      background: var(--critical);
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 15px;
      margin-top: 2px;
      position: relative;
    }
    .einst-dot[data-num]::after {
      content: attr(data-num);
      position: absolute;
      top: -6px; right: -6px;
      background: var(--accent);
      color: #fff;
      font-size: 9px; font-weight: 700;
      width: 14px; height: 14px;
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
    }
    .einst-item { cursor: pointer; }
    .einst-text { flex: 1; }
    .einst-text .einst-name {
      font-weight: 700;
      color: var(--text);
      font-size: 14px;
    }
    .einst-text .einst-detail {
      color: var(--text-dim);
      font-size: 12px;
      margin-top: 2px;
    }
    .einst-marker circle { transition: r .15s; }
    .einst-marker:hover circle { r: 13; }
    .gebiets-summary {
      display: flex;
      gap: 20px;
      align-items: center;
      padding: 10px 0;
      font-size: 13px;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }
    .gebiets-summary span { display: flex; align-items: center; gap: 6px; }
    .gebiets-team-saving {
      margin-top: 16px;
      padding: 12px 16px;
      background: rgba(0,114,206,.06);
      border-left: 3px solid var(--primary);
      border-radius: 0 8px 8px 0;
      font-size: 13px;
      color: var(--text);
    }
    .gebiets-ampel-dot {
      display: inline-block;
      width: 8px; height: 8px;
      border-radius: 50%;
      margin-right: 4px;
    }
    .gebiets-gruen .gebiets-ampel-dot { background: var(--success-text); }
    .gebiets-gelb .gebiets-ampel-dot { background: var(--warning-text); }
    .gebiets-rot .gebiets-ampel-dot { background: var(--critical-text); }
    .badge-ratio { color: #fff; padding: 2px 8px; }
    .badge-ratio.gebiets-gruen { background: var(--success); }
    .badge-ratio.gebiets-gelb  { background: var(--warning); }
    .badge-ratio.gebiets-rot   { background: var(--critical); }
    .gebiets-detail-box {
      padding: 10px 14px;
      background: rgba(0,114,206,.05);
      border-left: 3px solid var(--primary);
      border-radius: 0 8px 8px 0;
      font-size: 12px;
      line-height: 1.6;
      color: var(--text-dim);
    }
    .gebiets-detail-box strong { color: var(--text); }
    tr.gebiets-row { transition: background .15s; }
    tr.gebiets-row:hover td { background: rgba(0,114,206,.06); }
    .gebiets-legende {
      display: flex;
      flex-wrap: wrap;
      gap: 6px 12px;
      margin-top: 10px;
      font-size: 11px;
      color: var(--text-dim);
    }
    .gebiets-legende-item {
      display: flex;
      align-items: center;
      gap: 4px;
    }
    .gebiets-legende-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      border: 1px solid rgba(255,255,255,.15);
    }

    /* ── Chat Panel (Glassmorphism) ── */
    .chat-panel {
      width: 340px;
      min-width: 340px;
      background: rgba(0,8,16,.85);
      backdrop-filter: blur(28px);
      -webkit-backdrop-filter: blur(28px);
      border-left: 1px solid var(--card-border);
      display: flex;
      flex-direction: column;
      height: 100vh;
      position: sticky;
      top: 0;
    }
    .chat-header {
      background: rgba(0,8,20,.85);
      backdrop-filter: blur(28px);
      -webkit-backdrop-filter: blur(28px);
      color: #fff;
      padding: 0 16px;
      height: 60px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-shrink: 0;
      border-bottom: 1px solid var(--card-border);
    }
    .chat-header-title {
      font-family: var(--font-heading);
      font-size: 14px;
      font-weight: 700;
      letter-spacing: .3px;
    }
    .chat-header-sub {
      font-size: 10px;
      color: var(--text-dim);
    }
    .chat-status {
      width: 8px; height: 8px;
      border-radius: 50%;
      background: var(--success-text);
      display: inline-block;
      margin-right: 8px;
    }
    .chat-status.offline { background: var(--text-muted); }

    /* ── Chat Setup ── */
    .chat-setup {
      padding: 24px 16px;
      text-align: center;
    }
    .chat-setup p {
      font-size: 13px;
      color: var(--text-dim);
      margin-bottom: 12px;
    }
    .chat-setup input {
      width: 100%;
      padding: 10px 12px;
      border: 1px solid var(--card-border);
      border-radius: 8px;
      background: rgba(255,255,255,.04);
      color: var(--text);
      font-family: 'JetBrains Mono', 'Consolas', monospace;
      font-size: 12px;
      margin-bottom: 10px;
      outline: none;
    }
    .chat-setup input:focus {
      border-color: var(--primary);
      box-shadow: 0 0 0 2px rgba(0,114,206,.2);
    }
    .chat-setup .chat-key-error {
      color: var(--critical-text);
      font-size: 11px;
      margin-bottom: 8px;
      display: none;
    }
    .chat-btn-primary {
      background: var(--primary);
      color: #fff;
      border: none;
      border-radius: 8px;
      padding: 10px 20px;
      font-family: var(--font-body);
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      transition: all .2s;
    }
    .chat-btn-primary:hover { background: #005ba3; }

    /* ── Chat Messages ── */
    .chat-messages {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .chat-msg {
      max-width: 92%;
      padding: 10px 14px;
      border-radius: 12px;
      font-size: 13px;
      line-height: 1.5;
      word-wrap: break-word;
    }
    .chat-msg-user {
      align-self: flex-end;
      background: linear-gradient(135deg, #0072CE, #00A3E0);
      color: #fff;
      border-bottom-right-radius: 4px;
    }
    .chat-msg-assistant {
      align-self: flex-start;
      background: rgba(0,87,168,.15);
      color: var(--text);
      border: 1px solid rgba(0,87,168,.2);
      border-bottom-left-radius: 4px;
    }
    .chat-msg-assistant strong { color: var(--accent); }
    .chat-msg-assistant code {
      background: rgba(0,163,224,.1);
      padding: 1px 5px;
      border-radius: 3px;
      font-size: 12px;
    }
    .chat-msg-system {
      align-self: center;
      background: transparent;
      color: var(--text-dim);
      font-size: 11px;
      font-style: italic;
      text-align: center;
      padding: 4px;
    }

    /* ── Quick Buttons ── */
    .chat-quick {
      padding: 8px 12px;
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      border-top: 1px solid var(--card-border);
      flex-shrink: 0;
    }
    .chat-quick button {
      background: rgba(255,255,255,.04);
      color: var(--text-dim);
      border: 1px solid rgba(255,255,255,.09);
      border-radius: 16px;
      padding: 6px 14px;
      font-family: var(--font-body);
      font-size: 11px;
      cursor: pointer;
      transition: all .2s ease;
      white-space: nowrap;
    }
    .chat-quick button:hover {
      background: linear-gradient(135deg, #0072CE, #00A3E0);
      color: #fff;
      border-color: transparent;
      box-shadow: 0 2px 8px rgba(0,114,206,.25);
    }

    /* ── Chat Input ── */
    .chat-input-wrap {
      padding: 12px;
      border-top: 1px solid var(--card-border);
      display: flex;
      gap: 8px;
      align-items: flex-end;
      flex-shrink: 0;
    }
    .chat-input-wrap textarea {
      flex: 1;
      resize: none;
      border: 1px solid rgba(255,255,255,.09);
      border-radius: 12px;
      padding: 10px 12px;
      font-family: var(--font-body);
      font-size: 13px;
      line-height: 1.4;
      outline: none;
      background: rgba(255,255,255,.04);
      color: var(--text);
      max-height: 120px;
      min-height: 40px;
      transition: border-color .2s ease;
    }
    .chat-input-wrap textarea:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 2px rgba(0,163,224,.12);
    }
    .chat-send-btn {
      background: linear-gradient(135deg, #0072CE, #00A3E0);
      color: #fff;
      border: none;
      border-radius: 12px;
      width: 40px;
      height: 40px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background .2s;
      flex-shrink: 0;
    }
    .chat-send-btn:hover { background: #005ba3; }
    .chat-send-btn:disabled { background: rgba(255,255,255,.1); cursor: not-allowed; }
    .chat-send-btn svg { width: 18px; height: 18px; fill: #fff; }

    .chat-disconnect {
      padding: 6px 12px;
      text-align: right;
      flex-shrink: 0;
    }
    .chat-disconnect button {
      background: none;
      border: none;
      color: var(--text-muted);
      font-size: 10px;
      cursor: pointer;
      text-decoration: underline;
    }
    .chat-disconnect button:hover { color: var(--critical-text); }

    /* ── Gebietsoptimierung ── */
    .go-empf-grid {
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .go-empf-card {
      display: flex;
      gap: 16px;
      background: rgba(255,255,255,.02);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 20px 22px;
      transition: all .2s ease;
    }
    .go-empf-card:hover { border-color: rgba(0,163,224,.25); background: rgba(255,255,255,.04); box-shadow: 0 4px 20px rgba(0,0,0,.25); }
    .go-empf-num {
      flex-shrink: 0;
      width: 36px; height: 36px;
      border-radius: 50%;
      background: linear-gradient(135deg, #0072CE, #00A3E0);
      color: #fff;
      font-family: var(--font-heading);
      font-size: 16px;
      font-weight: 700;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .go-empf-body { flex: 1; }
    .go-empf-title {
      font-family: var(--font-heading);
      font-size: 14px;
      font-weight: 600;
      color: var(--accent);
      margin-bottom: 4px;
    }
    .go-empf-stats {
      font-size: 11px;
      color: var(--text-dim);
      margin-bottom: 6px;
      padding: 4px 10px;
      background: rgba(0,114,206,.06);
      border-radius: 4px;
      display: inline-block;
    }
    .go-empf-text {
      font-size: 13px;
      color: var(--text);
      line-height: 1.5;
    }
    .go-gruen td { color: var(--success-text); }
    .go-gelb td { color: var(--warning-text); }
    .go-rot td { color: var(--critical-text); }

    /* ── Gebietsoptimierung View Buttons ── */
    .go-view-buttons {
      display: flex;
      gap: 8px;
      margin-bottom: 18px;
    }
    .go-view-btn {
      font-family: var(--font-body);
      font-size: 12px;
      font-weight: 600;
      padding: 9px 20px;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,.09);
      background: rgba(255,255,255,.05);
      color: rgba(255,255,255,.4);
      cursor: pointer;
      transition: all .2s ease;
      letter-spacing: .02em;
    }
    .go-view-btn:hover {
      background: rgba(255,255,255,.1);
      color: rgba(255,255,255,.6);
    }
    .go-view-btn.active {
      background: linear-gradient(135deg, #0072CE, #00A3E0);
      color: #fff;
      border-color: transparent;
      box-shadow: 0 2px 12px rgba(0,114,206,.3);
    }
    .go-view-content { display: none; }
    .go-view-content.active { display: block; }

    .go-delta-pos td:last-child,
    .go-delta-pos { color: var(--success-text) !important; }
    .go-delta-neg td:last-child,
    .go-delta-neg { color: var(--critical-text) !important; }
    .go-delta-neutral { color: var(--text-dim); }

    .go-changes-highlight {
      margin-top: 14px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .go-change-item {
      font-size: 12px;
      color: var(--accent);
      padding: 6px 12px;
      background: rgba(0,163,224,.06);
      border-left: 3px solid var(--accent);
      border-radius: 0 6px 6px 0;
    }

    .go-dot {
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 50%;
      margin-right: 8px;
      vertical-align: middle;
    }
    .go-dot-orange { background: #FF8B00; }
    .go-dot-rot { background: #CC0000; }
    .go-dot-gruen { background: #00875A; }

    .go-overlap td:first-child { color: var(--warning-text); }
    .go-gap td:first-child { color: var(--critical-text); }
    .go-optimal td:first-child { color: var(--success-text); }

    /* ── Nav Tabs (Glassmorphism) ── */
    .nav-tabs {
      background: rgba(0,8,20,.7);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      display: flex;
      gap: 0;
      padding: 0 32px;
      position: sticky;
      top: 60px;
      z-index: 99;
      border-bottom: 1px solid rgba(255,255,255,.08);
      overflow-x: auto;
      -ms-overflow-style: none;
      scrollbar-width: none;
    }
    .nav-tabs::-webkit-scrollbar { display: none; }
    .nav-tab {
      padding: 13px 20px;
      font-family: var(--font-body);
      font-size: 12px;
      font-weight: 600;
      color: rgba(255,255,255,.35);
      cursor: pointer;
      border: none;
      background: none;
      border-bottom: 2px solid transparent;
      transition: color .2s ease, border-color .2s ease;
      letter-spacing: .02em;
      white-space: nowrap;
    }
    .nav-tab:hover { color: rgba(255,255,255,.6); }
    .nav-tab.active {
      color: #00A3E0;
      border-bottom-color: #00A3E0;
    }
    .tab-content { display: none; opacity: 0; transition: opacity .3s ease; }
    .tab-content.active { display: block; opacity: 1; }

    /* ── Animations ── */
    @keyframes fadeInUp {
      from { opacity: 0; transform: translateY(12px); }
      to { opacity: 1; transform: translateY(0); }
    }
    section { animation: fadeInUp .4s ease both; }
    section:nth-child(2) { animation-delay: .05s; }
    section:nth-child(3) { animation-delay: .1s; }
    section:nth-child(4) { animation-delay: .15s; }"""


def _render_gebietsoptimierung(
    metriken_akt: list[dict],
    metriken_opt: list[dict],
    techniker: dict[str, dict],
) -> str:
    """Erzeugt den Gebietsoptimierung-Tab mit 3 klickbaren Ansicht-Buttons."""
    if not metriken_akt:
        return ""

    # ── Ansicht 1: Aktuelle Gebiete – Tabelle ──
    rows_aktuell = ""
    for m in metriken_akt:
        if m["kliniken"] == 0:
            continue
        css = "go-gruen" if m["ratio"] >= 3.0 else ("go-gelb" if m["ratio"] >= 2.0 else "go-rot")
        rows_aktuell += (
            f'<tr class="{css}">'
            f'<td><strong>{m["id"]}</strong></td>'
            f'<td>{m["standort"]}</td>'
            f'<td>{m["kliniken"]}</td>'
            f'<td>{m["avg_fahrzeit"]} min</td>'
            f'<td><span class="badge badge-ratio {css.replace("go-","gebiets-")}">{m["ratio"]}</span></td>'
            f'</tr>')

    # ── Ansicht 2: Optimierte Gebiete – Vorher/Nachher Tabelle ──
    rows_optimiert = ""
    for m_o in metriken_opt:
        if m_o["kliniken"] == 0:
            continue
        m_a = next((x for x in metriken_akt if x["id"] == m_o["id"]), None)
        ratio_vorher = m_a["ratio"] if m_a else 0.0
        ratio_nachher = m_o["ratio"]
        delta_fz = (m_o["fahrtstunden_jahr"] - m_a["fahrtstunden_jahr"]) if m_a else 0
        delta_sign = "+" if delta_fz >= 0 else ""
        if ratio_nachher > ratio_vorher:
            delta_css = "go-delta-pos"
        elif ratio_nachher < ratio_vorher:
            delta_css = "go-delta-neg"
        else:
            delta_css = "go-delta-neutral"
        rows_optimiert += (
            f'<tr>'
            f'<td><strong>{m_o["id"]}</strong></td>'
            f'<td>{m_o["standort"]}</td>'
            f'<td>{ratio_vorher}</td>'
            f'<td>{ratio_nachher}</td>'
            f'<td class="{delta_css}">{delta_sign}{delta_fz} h</td>'
            f'</tr>')

    # ── Ansicht 3: Lücken & Überschneidungen ──
    # Identifiziere Problembereiche aus den Metriken
    _UEBERSCHNEIDUNG_GEBIETE = {
        "Nordrhein-Westfalen": {"techs": ["T5", "T8", "T11", "T13"], "typ": "overlap"},
        "Bayern":              {"techs": ["T4", "T7"],               "typ": "overlap"},
    }
    _LUECKEN_GEBIETE = {
        "Mecklenburg-Vorpommern": {"naechster": "T9", "fahrzeit": "180 min", "typ": "gap"},
        "Brandenburg":            {"naechster": "T3", "fahrzeit": "165 min", "typ": "gap"},
    }

    rows_luecken = ""
    for gebiet, info in _UEBERSCHNEIDUNG_GEBIETE.items():
        techs = ", ".join(info["techs"])
        rows_luecken += (
            f'<tr class="go-overlap">'
            f'<td><span class="go-dot go-dot-orange"></span>{gebiet}</td>'
            f'<td>&Uuml;berschneidung</td>'
            f'<td>{techs}</td>'
            f'<td>Gebiete konsolidieren &mdash; klare Zuordnung definieren</td>'
            f'</tr>')
    for gebiet, info in _LUECKEN_GEBIETE.items():
        rows_luecken += (
            f'<tr class="go-gap">'
            f'<td><span class="go-dot go-dot-rot"></span>{gebiet}</td>'
            f'<td>L&uuml;cke</td>'
            f'<td>{info["naechster"]} ({info["fahrzeit"]})</td>'
            f'<td>Neueinstellung oder Gebiets-Erweiterung empfohlen</td>'
            f'</tr>')
    # Optimal abgedeckte Gebiete
    _OPTIMAL = ["Hessen", "Schleswig-Holstein", "Baden-Württemberg", "Thüringen"]
    for gebiet in _OPTIMAL:
        tid = _GEBIET_AKTUELL.get(gebiet, "–")
        rows_luecken += (
            f'<tr class="go-optimal">'
            f'<td><span class="go-dot go-dot-gruen"></span>{gebiet}</td>'
            f'<td>Optimal</td>'
            f'<td>{tid}</td>'
            f'<td>Keine Anpassung n&ouml;tig</td>'
            f'</tr>')

    # Top-3 Empfehlungen
    top3 = []
    _PRIO = ["T2", "T8", "T13", "T3", "T7", "T10"]
    for tid in _PRIO:
        v = _OPTIMIERUNGS_VORSCHLAEGE.get(tid)
        if v and len(top3) < 3:
            m = next((x for x in metriken_akt if x["id"] == tid), None)
            top3.append({"id": tid, "vorschlag": v, "metriken": m})

    empf_html = ""
    for i, e in enumerate(top3, 1):
        m = e["metriken"]
        fz_info = ""
        if m:
            fz_info = (f'<div class="go-empf-stats">'
                       f'&#216; Fahrzeit: {m["avg_fahrzeit"]} min &middot; '
                       f'Max: {m.get("max_fahrzeit", 0)} min &middot; '
                       f'{m["kliniken"]} Kliniken &middot; '
                       f'Ratio: {m["ratio"]}</div>')
        empf_html += (
            f'<div class="go-empf-card">'
            f'<div class="go-empf-num">{i}</div>'
            f'<div class="go-empf-body">'
            f'<div class="go-empf-title">{e["id"]} &mdash; '
            f'{techniker.get(e["id"], {}).get("standort", "")}</div>'
            f'{fz_info}'
            f'<div class="go-empf-text">{e["vorschlag"]}</div>'
            f'</div></div>')

    return f"""
  <section>
    <h2 data-i18n="h.territory">Gebietsoptimierung</h2>
    <p class="section-hint" data-i18n="hint.territory">
      Analyse der Gebietsabdeckung &middot; &Uuml;berschneidungen &amp; L&uuml;cken &middot;
      Fahrzeit-Optimierungspotenzial je Region
    </p>

    <div class="go-view-buttons" id="go-view-buttons">
      <button class="go-view-btn active" data-view="aktuell">Aktuelle Gebiete</button>
      <button class="go-view-btn" data-view="optimiert">Optimierte Gebiete</button>
      <button class="go-view-btn" data-view="luecken">L&uuml;cken &amp; &Uuml;berschneidungen</button>
    </div>

    <div class="gebiets-layout">
      <div class="gebiets-karte">
        <svg id="germany-map-opt" width="480" height="580"><!-- filled by _build_gebiets_svg --></svg>
        <div class="gebiets-legende" id="gebiets-legende-opt"></div>
      </div>
      <div class="gebiets-metriken">
        <!-- Ansicht 1: Aktuelle Gebiete -->
        <div class="go-view-content active" id="go-view-aktuell">
          <table>
            <thead>
              <tr>
                <th data-i18n="th.technician">Techniker</th>
                <th>Standort</th>
                <th>Kliniken</th>
                <th>&Oslash; Fahrzeit</th>
                <th>Ratio</th>
              </tr>
            </thead>
            <tbody>
{rows_aktuell}
            </tbody>
          </table>
        </div>
        <!-- Ansicht 2: Optimierte Gebiete -->
        <div class="go-view-content" id="go-view-optimiert">
          <div class="bc-gold-hint" style="margin-bottom:14px">
            &#9733; Demo-Optimierung &middot; Basiert auf Fahrzeit-Minimierung und Auslastungsausgleich
          </div>
          <table>
            <thead>
              <tr>
                <th>Techniker</th>
                <th>Standort</th>
                <th>Ratio vorher</th>
                <th>Ratio nachher</th>
                <th>&Delta; Fahrzeit</th>
              </tr>
            </thead>
            <tbody>
{rows_optimiert}
            </tbody>
          </table>
          <div class="go-changes-highlight">
            <div class="go-change-item">T2 Wehingen &rarr; bekommt mehr BaW&uuml;-S&uuml;d Kliniken</div>
            <div class="go-change-item">T3 Weimar &rarr; bekommt Th&uuml;ringen komplett</div>
            <div class="go-change-item">T8 Hennef &rarr; NRW-S&uuml;d konsolidiert</div>
          </div>
        </div>
        <!-- Ansicht 3: Lücken & Überschneidungen -->
        <div class="go-view-content" id="go-view-luecken">
          <table>
            <thead>
              <tr>
                <th>Gebiet</th>
                <th>Status</th>
                <th>Techniker</th>
                <th>Empfehlung</th>
              </tr>
            </thead>
            <tbody>
{rows_luecken}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </section>

  <section>
    <h2 data-i18n="h.top3">Top-3 Empfehlungen f&uuml;r Gebietsanpassung</h2>
    <p class="section-hint" data-i18n="hint.top3">
      Priorisiert nach Fahrzeit-Einsparungspotenzial und Crosstraining-Bedarf
    </p>
    <div class="go-empf-grid">
{empf_html}
    </div>
    <div class="bc-gold-hint" style="margin-top:16px">
      &#9733; Demo-Daten &middot; Regionen konfigurierbar
    </div>
  </section>"""


def render_html(
    ampeln: list[dict],
    stk_rows: list[dict],
    ct_top5: list[dict],
    techniker: dict[str, dict],
    nrw_warnung: dict | None,
    erstellt_am: datetime,
    ct_rows: list[dict] | None = None,
    gebiets_metriken: tuple[list[dict], list[dict]] | None = None,
    labor_zeiten: list[dict] | None = None,
    demo_history: dict[str, dict] | None = None,
    repair_rows: list[dict] | None = None,
) -> str:
    ampel_html    = _render_ampel_karten(ampeln, labor_zeiten)
    stk_html      = _render_stk_tabelle(stk_rows)
    repair_html   = _render_repair_tabelle(repair_rows or [])
    ct_html       = _render_ct_tabelle(ct_top5, techniker)
    warnung_html  = _render_nrw_warnung(nrw_warnung)
    puffer_html   = _render_puffer_section(labor_zeiten or [])
    workflow_html = _render_workflow_status()
    bc_html       = _render_business_case()
    m_akt, m_opt  = gebiets_metriken or ([], [])
    plz_abd       = _berechne_plz_abdeckung(techniker)
    gebiets_html  = _render_gebietsplanung(m_akt, m_opt, plz_abd)
    gebietsopt_html = _render_gebietsoptimierung(m_akt, m_opt, techniker)
    gebiets_svg_content = _build_gebiets_svg(techniker, plz_abd)
    gebiets_script = _build_gebiets_script(techniker, plz_abd)
    tech_detail_json = _render_techniker_detail_data(
        techniker, demo_history or {})
    ts = erstellt_am.strftime("%d.%m.%Y %H:%M")

    gruen_count = sum(1 for a in ampeln if a["ampel_css"] == "ampel-gruen")
    gelb_count  = sum(1 for a in ampeln if a["ampel_css"] == "ampel-gelb")
    rot_count   = sum(1 for a in ampeln if a["ampel_css"] == "ampel-rot")

    # System-Prompt fuer Chat
    system_prompt = _build_system_prompt(ct_rows or [], techniker, ampeln)
    system_prompt_js = json.dumps(system_prompt, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Field Service AI &ndash; Medtronic Deutschland</title>
  <style>
{_CSS}
  </style>
</head>
<body>

<!-- Grain Overlay -->
<div class="grain-overlay"></div>

<div class="app-layout">

<!-- ══════════ Dashboard Panel ══════════ -->
<div class="dashboard-panel">

<header>
  <div class="header-brand">
    <div>
      <div class="header-logo">Field Service <span class="brand-ai">AI</span></div>
      <div class="header-sub">Medtronic GmbH</div>
    </div>
  </div>
  <div class="header-right">
    <span class="demo-badge" data-i18n="header.demo">Demo-Daten &middot; Konfigurierbar</span>
    <button class="lang-toggle" id="lang-toggle-btn" onclick="toggleLang()">EN</button>
    <button class="api-key-btn" onclick="document.getElementById('chat-setup').style.display='block';document.getElementById('api-key-input').focus()">API-Key &#128273;</button>
  </div>
</header>

<nav class="nav-tabs">
  <button class="nav-tab active" data-tab="tab-uebersicht" data-i18n="tab.overview">&Uuml;bersicht</button>
  <button class="nav-tab" data-tab="tab-auftraege" data-i18n="tab.orders">Auftr&auml;ge</button>
  <button class="nav-tab" data-tab="tab-crosstraining" data-i18n="tab.crosstraining">Cross-Training</button>
  <button class="nav-tab" data-tab="tab-workflow" data-i18n="tab.workflow">Workflow</button>
  <button class="nav-tab" data-tab="tab-business" data-i18n="tab.business">Business Case</button>
  <button class="nav-tab" data-tab="tab-gebietsopt" data-i18n="tab.territory">Gebietsoptimierung</button>
  <button class="nav-tab" data-tab="tab-einstellung" data-i18n="tab.hiring">Einstellungsbedarf</button>
</nav>

<div class="summary-bar">
  <span><span class="dot dot-gruen"></span> <span data-i18n="summary.green">Gr&uuml;n</span>: <strong>{gruen_count}</strong> (&ge;60&thinsp;% L3)</span>
  <span><span class="dot dot-gelb"></span> <span data-i18n="summary.yellow">Gelb</span>: <strong>{gelb_count}</strong> (30&ndash;59&thinsp;%)</span>
  <span><span class="dot dot-rot"></span> <span data-i18n="summary.red">Rot</span>: <strong>{rot_count}</strong> (&lt;30&thinsp;%)</span>
  <span style="margin-left:auto;color:var(--text-muted);font-size:11px"><span data-i18n="summary.asOf">Stand</span>: {ts} &middot; 32h/<span data-i18n="card.week">Wo</span> <span data-i18n="summary.monThu">Mo&ndash;Do</span> &middot; Hugo KA: 25,6h</span>
</div>

<main>

  <!-- Tab 1: Uebersicht -->
  <div id="tab-uebersicht" class="tab-content active">
  <section>
    <h2 data-i18n="h.overview">&Uuml;bersicht &mdash; Qualifikations-Ampel</h2>
    <p class="section-hint" data-i18n="hint.overview">
      L3-Abdeckung in der Region &middot; 14 Techniker &middot;
      Gr&uuml;n &ge;60% &middot; Gelb 30-59% &middot; Rot &lt;30%
    </p>
    <div class="ampel-sort-controls">
      <label for="ampel-sort-select" data-i18n="sort.label">Sortierung:</label>
      <select id="ampel-sort-select">
        <option value="standard" data-i18n="sort.standard">Standard (Gr&uuml;n / Gelb / Rot)</option>
        <option value="crosstraining" data-i18n="sort.ct">Crosstraining-Bedarf (meiste L&uuml;cken zuerst)</option>
        <option value="auslastung" data-i18n="sort.util">Auslastung (Stunden)</option>
        <option value="portfolio" data-i18n="sort.portfolio">Ger&auml;te-Portfolio (meiste L3-Familien zuerst)</option>
        <option value="potential" data-i18n="sort.area">Gebietsgr&ouml;&szlig;e</option>
      </select>
      <span class="demo-hint" data-i18n="hint.demo">Demo-Daten &middot; Techniker erweiterbar</span>
    </div>
    <div class="ampel-grid" id="ampel-grid">
{ampel_html}
    </div>
  </section>
  </div>

  <!-- Tab 2: Auftraege (STK + Repair) -->
  <div id="tab-auftraege" class="tab-content">
  <section>
    <h2 data-i18n="h.stk">STK-Auftr&auml;ge (Top 10)</h2>
    <p class="section-hint" data-i18n="hint.stk">Quelle: daten/geraete.csv &middot; Aufsteigend nach F&auml;lligkeitsdatum</p>
    <table>
      <thead>
        <tr>
          <th data-i18n="th.orderId">Auftrag-ID</th>
          <th data-i18n="th.clinic">Klinik</th>
          <th data-i18n="th.device">Ger&auml;t</th>
          <th data-i18n="th.productFamily">Produktfamilie</th>
          <th data-i18n="th.dueDate">F&auml;lligkeit</th>
          <th data-i18n="th.suggestedDates">Vorgeschlagene Termine</th>
          <th data-i18n="th.urgency">Dringlichkeit</th>
          <th data-i18n="th.days">Tage</th>
        </tr>
      </thead>
      <tbody>
{stk_html}
      </tbody>
    </table>
  </section>
  <section>
    <h2 data-i18n="h.repair">Offene Repair-Auftr&auml;ge</h2>
    <p class="section-hint" data-i18n="hint.repair">SLA: Kundenkontakt innerhalb 48h &middot; Internes Ziel: 24h</p>
    <table>
      <thead>
        <tr>
          <th data-i18n="th.orderId">Auftrag-ID</th>
          <th data-i18n="th.clinic">Klinik</th>
          <th data-i18n="th.device">Ger&auml;t</th>
          <th data-i18n="th.received">Eingang</th>
          <th data-i18n="th.slaStatus">SLA-Status</th>
          <th data-i18n="th.phase">Phase</th>
          <th data-i18n="th.sparePart">Ersatzteil</th>
        </tr>
      </thead>
      <tbody>
{repair_html}
      </tbody>
    </table>
  </section>
  </div>

  <!-- Tab 3: Cross-Training + NRW -->
  <div id="tab-crosstraining" class="tab-content">
  <section>
    <h2 data-i18n="h.ct">Crosstraining Top 5</h2>
    <p class="section-hint" data-i18n="hint.ct">
      T2 +664 &middot; T8 +527 &middot; T13 +498 &middot; T12 +449 &middot; T1 +453 STK/a &middot;
      Sortiert nach zus&auml;tzlichem STK-Potenzial pro Jahr
    </p>
    <table>
      <thead>
        <tr>
          <th data-i18n="th.technician">Techniker</th>
          <th data-i18n="th.gaps">L&uuml;cken</th>
          <th data-i18n="th.stkYear">+STK/Jahr</th>
          <th data-i18n="th.missingFamilies">Fehlende Produktfamilien</th>
          <th data-i18n="th.recPartner">Empf. Partner</th>
        </tr>
      </thead>
      <tbody>
{ct_html}
      </tbody>
    </table>
  </section>
{warnung_html}
  </div>

  <!-- Tab 4: Workflow -->
  <div id="tab-workflow" class="tab-content">
{workflow_html}
{puffer_html}
  </div>

  <!-- Tab 5: Business Case -->
  <div id="tab-business" class="tab-content">
{bc_html}
  </div>

  <!-- Tab 6: Gebietsoptimierung -->
  <div id="tab-gebietsopt" class="tab-content">
{gebietsopt_html}
  </div>

  <!-- Tab 7: Einstellungsbedarf -->
  <div id="tab-einstellung" class="tab-content">
{gebiets_html}
  </div>

</main>

<footer>
  Field Service AI &nbsp;|&nbsp;
  Medtronic GmbH Service &amp; Repair &nbsp;|&nbsp;
  <span data-i18n="footer.copilot">Vollautomatisiert &middot; Copilot &mdash; kein Autopilot</span> &nbsp;|&nbsp;
  441 Tests gr&uuml;n
</footer>

</div><!-- /dashboard-panel -->

<!-- ══════════ Chat Panel (340px) ══════════ -->
<aside class="chat-panel" id="chat-panel">

  <div class="chat-header">
    <div>
      <div class="chat-header-title">
        <span class="chat-status offline" id="chat-status"></span>Claude AI
      </div>
      <div class="chat-header-sub" data-i18n="chat.sub">Medtronic Field Service Assistent</div>
    </div>
  </div>

  <!-- API-Key Setup -->
  <div class="chat-setup" id="chat-setup">
    <p data-i18n-html="chat.setup">Claude API-Key eingeben, um den<br>KI-Assistenten zu aktivieren.</p>
    <input type="password" id="api-key-input" placeholder="sk-ant-api03-..." autocomplete="off">
    <div class="chat-key-error" id="chat-key-error">Ung&uuml;ltiger API-Key. Bitte pr&uuml;fen.</div>
    <button class="chat-btn-primary" id="api-key-save" data-i18n="chat.connect">Verbinden</button>
    <p style="margin-top:12px;font-size:10px;color:var(--text-muted)" data-i18n-html="chat.keyNote">
      Key wird lokal im Browser gespeichert.<br>Keine serverseitige Speicherung.
    </p>
  </div>

  <!-- Chat Body (hidden until connected) -->
  <div class="chat-messages" id="chat-messages" style="display:none"></div>

  <div class="chat-quick" id="chat-quick" style="display:none">
    <button data-q="Warum wurde T5 fuer diesen Auftrag empfohlen? Erklaere die Scoring-Berechnung." data-i18n="chat.q1">Warum T5?</button>
    <button data-q="Erklaere das NRW-Ueberlastungsproblem: Welche Techniker sind betroffen, warum ist es kritisch, und was sind die Loesungsoptionen?" data-i18n="chat.q2">NRW Problem</button>
    <button data-q="Wie ist der Kalibrierungsstatus von T10? Welche Messmittel laufen bald ab?" data-i18n="chat.q3">T10 Kalibrierung</button>
    <button data-q="Welches Crosstraining sollte prioritaer durchgefuehrt werden? Begruende anhand der Daten." data-i18n="chat.q4">Crosstraining</button>
    <button data-q="Was sind die wichtigsten naechsten Schritte fuer die Serviceplanung?" data-i18n="chat.q5">N&auml;chste Schritte</button>
  </div>

  <div class="chat-input-wrap" id="chat-input-wrap" style="display:none">
    <textarea id="chat-input" data-i18n-placeholder="chat.placeholder" placeholder="Frage zum Dashboard stellen..." rows="1"></textarea>
    <button class="chat-send-btn" id="chat-send" title="Senden">
      <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
    </button>
  </div>

  <div class="chat-disconnect" id="chat-disconnect" style="display:none">
    <button id="chat-disconnect-btn" data-i18n="chat.removeKey">API-Key entfernen</button>
  </div>

</aside>

</div><!-- /app-layout -->

<!-- Techniker-Detail Modal -->
<div class="tech-detail-overlay" id="tech-detail-overlay"
     onclick="if(event.target===this)closeTechDetail()">
  <div class="tech-detail-panel" id="tech-detail-panel">
    <button class="tech-detail-close" onclick="closeTechDetail()">&times;</button>
    <div id="tech-detail-content"></div>
  </div>
</div>

<script>
/* ── i18n Translation ── */
var _I18N = {{
  DE: {{
    'header.demo': 'Demo-Daten \u00b7 Konfigurierbar',
    'tab.overview': '\u00dcbersicht',
    'tab.orders': 'Auftr\u00e4ge',
    'tab.crosstraining': 'Cross-Training',
    'tab.workflow': 'Workflow',
    'tab.business': 'Business Case',
    'tab.territory': 'Gebietsoptimierung',
    'tab.hiring': 'Einstellungsbedarf',
    'summary.green': 'Gr\u00fcn',
    'summary.yellow': 'Gelb',
    'summary.red': 'Rot',
    'summary.asOf': 'Stand',
    'summary.monThu': 'Mo\u2013Do',
    'h.overview': '\u00dcbersicht \u2014 Qualifikations-Ampel',
    'hint.overview': 'L3-Abdeckung in der Region \u00b7 14 Techniker \u00b7 Gr\u00fcn \u226560% \u00b7 Gelb 30-59% \u00b7 Rot <30%',
    'sort.label': 'Sortierung:',
    'sort.standard': 'Standard (Gr\u00fcn / Gelb / Rot)',
    'sort.ct': 'Crosstraining-Bedarf (meiste L\u00fccken zuerst)',
    'sort.util': 'Auslastung (Stunden)',
    'sort.portfolio': 'Ger\u00e4te-Portfolio (meiste L3-Familien zuerst)',
    'sort.area': 'Gebietsgr\u00f6\u00dfe',
    'hint.demo': 'Demo-Daten \u00b7 Techniker erweiterbar',
    'h.stk': 'STK-Auftr\u00e4ge (Top 10)',
    'hint.stk': 'Quelle: daten/geraete.csv \u00b7 Aufsteigend nach F\u00e4lligkeitsdatum',
    'th.orderId': 'Auftrag-ID',
    'th.clinic': 'Klinik',
    'th.device': 'Ger\u00e4t',
    'th.productFamily': 'Produktfamilie',
    'th.dueDate': 'F\u00e4lligkeit',
    'th.suggestedDates': 'Vorgeschlagene Termine',
    'th.urgency': 'Dringlichkeit',
    'th.days': 'Tage',
    'h.repair': 'Offene Repair-Auftr\u00e4ge',
    'hint.repair': 'SLA: Kundenkontakt innerhalb 48h \u00b7 Internes Ziel: 24h',
    'th.received': 'Eingang',
    'th.slaStatus': 'SLA-Status',
    'th.phase': 'Phase',
    'th.sparePart': 'Ersatzteil',
    'h.ct': 'Crosstraining Top 5',
    'hint.ct': 'T2 +664 \u00b7 T8 +527 \u00b7 T13 +498 \u00b7 T12 +449 \u00b7 T1 +453 STK/a \u00b7 Sortiert nach zus\u00e4tzlichem STK-Potenzial pro Jahr',
    'th.technician': 'Techniker',
    'th.gaps': 'L\u00fccken',
    'th.stkYear': '+STK/Jahr',
    'th.missingFamilies': 'Fehlende Produktfamilien',
    'th.recPartner': 'Empf. Partner',
    'card.l3coverage': 'L3-Abdeckung',
    'card.fam': 'Fam.',
    'card.gaps': 'L\u00fccken',
    'card.capacity': 'Kapazit\u00e4t',
    'card.week': 'Woche',
    'card.missingFam': 'fehlende Familien',
    'card.potential': 'Potenzial',
    'card.weeklyHours': 'Wochenstunden',
    'card.fridayNote': 'Freitag = Home Office \u00b7 keine Echtzeit-Daten',
    'card.l3families': 'L3-Familien',
    'card.ofRegional': 'von',
    'card.regional': 'regionalen',
    'card.stkPotential': 'STK/a Potenzial',
    'card.afterCT': 'nach Crosstraining',
    'footer.copilot': 'Vollautomatisiert \u00b7 Copilot \u2014 kein Autopilot',
    'chat.sub': 'Medtronic Field Service Assistent',
    'chat.setup': 'Claude API-Key eingeben, um den<br>KI-Assistenten zu aktivieren.',
    'chat.connect': 'Verbinden',
    'chat.keyNote': 'Key wird lokal im Browser gespeichert.<br>Keine serverseitige Speicherung.',
    'chat.placeholder': 'Frage zum Dashboard stellen...',
    'chat.removeKey': 'API-Key entfernen',
    'chat.q1': 'Warum T5?',
    'chat.q2': 'NRW Problem',
    'chat.q3': 'T10 Kalibrierung',
    'chat.q4': 'Crosstraining',
    'chat.q5': 'N\u00e4chste Schritte',
    'h.territory': 'Gebietsoptimierung',
    'hint.territory': 'Analyse der Gebietsabdeckung \u00b7 \u00dcberschneidungen & L\u00fccken \u00b7 Fahrzeit-Optimierungspotenzial je Region',
    'h.top3': 'Top-3 Empfehlungen f\u00fcr Gebietsanpassung',
    'hint.top3': 'Priorisiert nach Fahrzeit-Einsparungspotenzial und Crosstraining-Bedarf'
  }},
  EN: {{
    'header.demo': 'Demo Data \u00b7 Configurable',
    'tab.overview': 'Overview',
    'tab.orders': 'Orders',
    'tab.crosstraining': 'Cross-Training',
    'tab.workflow': 'Workflow',
    'tab.business': 'Business Case',
    'tab.territory': 'Territory Optimization',
    'tab.hiring': 'Hiring Needs',
    'summary.green': 'Green',
    'summary.yellow': 'Yellow',
    'summary.red': 'Red',
    'summary.asOf': 'As of',
    'summary.monThu': 'Mon\u2013Thu',
    'h.overview': 'Overview \u2014 Qualification Traffic Light',
    'hint.overview': 'L3 coverage by region \u00b7 14 technicians \u00b7 Green \u226560% \u00b7 Yellow 30-59% \u00b7 Red <30%',
    'sort.label': 'Sort by:',
    'sort.standard': 'Default (Green / Yellow / Red)',
    'sort.ct': 'Cross-training need (most gaps first)',
    'sort.util': 'Utilization (hours)',
    'sort.portfolio': 'Device portfolio (most L3 families first)',
    'sort.area': 'Territory size',
    'hint.demo': 'Demo data \u00b7 Technicians configurable',
    'h.stk': 'Safety Checks (Top 10)',
    'hint.stk': 'Source: daten/geraete.csv \u00b7 Ascending by due date',
    'th.orderId': 'Order ID',
    'th.clinic': 'Hospital',
    'th.device': 'Device',
    'th.productFamily': 'Product Family',
    'th.dueDate': 'Due Date',
    'th.suggestedDates': 'Suggested Dates',
    'th.urgency': 'Urgency',
    'th.days': 'Days',
    'h.repair': 'Open Repair Orders',
    'hint.repair': 'SLA: Customer contact within 48h \u00b7 Internal target: 24h',
    'th.received': 'Received',
    'th.slaStatus': 'SLA Status',
    'th.phase': 'Phase',
    'th.sparePart': 'Spare Part',
    'h.ct': 'Cross-Training Top 5',
    'hint.ct': 'T2 +664 \u00b7 T8 +527 \u00b7 T13 +498 \u00b7 T12 +449 \u00b7 T1 +453 STK/yr \u00b7 Sorted by additional STK potential per year',
    'th.technician': 'Technician',
    'th.gaps': 'Gaps',
    'th.stkYear': '+STK/Year',
    'th.missingFamilies': 'Missing Product Families',
    'th.recPartner': 'Rec. Partner',
    'card.l3coverage': 'L3 Coverage',
    'card.fam': 'fam.',
    'card.gaps': 'gaps',
    'card.capacity': 'Capacity',
    'card.week': 'week',
    'card.missingFam': 'missing families',
    'card.potential': 'potential',
    'card.weeklyHours': 'Weekly hours',
    'card.fridayNote': 'Friday = Home Office \u00b7 no real-time data',
    'card.l3families': 'L3 Families',
    'card.ofRegional': 'of',
    'card.regional': 'regional',
    'card.stkPotential': 'STK/yr potential',
    'card.afterCT': 'after cross-training',
    'footer.copilot': 'Fully automated \u00b7 Copilot \u2014 not autopilot',
    'chat.sub': 'Medtronic Field Service Assistant',
    'chat.setup': 'Enter Claude API key to<br>activate the AI assistant.',
    'chat.connect': 'Connect',
    'chat.keyNote': 'Key is stored locally in your browser.<br>No server-side storage.',
    'chat.placeholder': 'Ask a question about the dashboard...',
    'chat.removeKey': 'Remove API key',
    'chat.q1': 'Why T5?',
    'chat.q2': 'NRW Problem',
    'chat.q3': 'T10 Calibration',
    'chat.q4': 'Cross-training',
    'chat.q5': 'Next Steps',
    'h.territory': 'Territory Optimization',
    'hint.territory': 'Territory coverage analysis \u00b7 Overlaps & gaps \u00b7 Travel time optimization potential per region',
    'h.top3': 'Top 3 Recommendations for Territory Adjustment',
    'hint.top3': 'Prioritized by travel time savings potential and cross-training needs'
  }}
}};
var _currentLang = localStorage.getItem('fsa_lang') || 'DE';

function setLang(lang) {{
  _currentLang = lang;
  localStorage.setItem('fsa_lang', lang);
  var dict = _I18N[lang];
  if (!dict) return;
  document.querySelectorAll('[data-i18n]').forEach(function(el) {{
    var key = el.getAttribute('data-i18n');
    if (dict[key] !== undefined) el.textContent = dict[key];
  }});
  document.querySelectorAll('[data-i18n-html]').forEach(function(el) {{
    var key = el.getAttribute('data-i18n-html');
    if (dict[key] !== undefined) el.innerHTML = dict[key];
  }});
  document.querySelectorAll('[data-i18n-placeholder]').forEach(function(el) {{
    var key = el.getAttribute('data-i18n-placeholder');
    if (dict[key] !== undefined) el.placeholder = dict[key];
  }});
  var btn = document.getElementById('lang-toggle-btn');
  if (btn) btn.textContent = lang === 'DE' ? 'EN' : 'DE';
  document.documentElement.lang = lang.toLowerCase();
}}

function toggleLang() {{
  setLang(_currentLang === 'DE' ? 'EN' : 'DE');
}}

if (_currentLang !== 'DE') setLang(_currentLang);

/* ── Tab Navigation ── */
(function() {{
  var tabs = document.querySelectorAll('.nav-tab');
  tabs.forEach(function(tab) {{
    tab.addEventListener('click', function() {{
      tabs.forEach(function(t) {{ t.classList.remove('active'); }});
      tab.classList.add('active');
      document.querySelectorAll('.tab-content').forEach(function(c) {{
        c.classList.remove('active');
      }});
      var target = document.getElementById(tab.getAttribute('data-tab'));
      if (target) target.classList.add('active');
    }});
  }});
}})();

{_SORT_SCRIPT}

/* ── Techniker-Detail Modal ── */
var TECH_DETAIL_DATA = {tech_detail_json};

function showTechDetail(tid) {{
  var d = TECH_DETAIL_DATA[tid];
  if (!d) return;
  var html = '<div class="tech-detail-title">' + tid + ' &mdash; ' + d.standort + ' &mdash; Einsatzhistorie</div>';
  html += '<table><thead><tr><th>Datum</th><th>Klinik</th><th>Ger&auml;t</th><th>Typ</th><th>Dauer</th><th>Status</th></tr></thead><tbody>';
  d.orders.forEach(function(o) {{
    html += '<tr><td>' + o.datum + '</td><td>' + o.klinik + '</td><td>' + o.geraet + '</td><td>' + o.typ + '</td><td>' + o.dauer_h + '</td><td style="color:var(--success-text)">' + o.status + '</td></tr>';
  }});
  html += '</tbody></table>';
  html += '<div class="tech-detail-kpis">';
  html += '<div class="tech-detail-kpi"><div class="kpi-val">' + d.einsaetze_monat + '</div><div class="kpi-lbl">Eins&auml;tze diesen Monat</div></div>';
  html += '<div class="tech-detail-kpi"><div class="kpi-val">' + d.einsaetze_jahr + '</div><div class="kpi-lbl">Eins&auml;tze dieses Jahr</div></div>';
  html += '<div class="tech-detail-kpi"><div class="kpi-val">' + d.avg_dauer_h + 'h</div><div class="kpi-lbl">&Oslash; Einsatzdauer</div></div>';
  html += '<div class="tech-detail-kpi"><div class="kpi-val">' + d.haeufigste_klinik + '</div><div class="kpi-lbl">H&auml;ufigste Klinik</div></div>';
  html += '<div class="tech-detail-kpi"><div class="kpi-val">' + d.haeufigste_familie + '</div><div class="kpi-lbl">H&auml;ufigste Produktfamilie</div></div>';
  html += '</div>';
  html += '<p style="margin-top:16px;font-size:10px;color:var(--text-muted);font-style:italic">Demo-Daten &middot; Im Produktivbetrieb: echte Daten aus SMax API</p>';
  document.getElementById('tech-detail-content').innerHTML = html;
  document.getElementById('tech-detail-overlay').classList.add('active');
}}

function closeTechDetail() {{
  document.getElementById('tech-detail-overlay').classList.remove('active');
}}

document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape') closeTechDetail();
}});

{gebiets_script}

/* ══════════ Claude Chat ══════════ */
(function() {{
  var SYSTEM_PROMPT = {system_prompt_js};
  var API_URL = 'https://api.anthropic.com/v1/messages';
  var MODEL = 'claude-sonnet-4-20250514';
  var MAX_TOKENS = 1024;

  var apiKey = localStorage.getItem('mdt_claude_key') || '';
  var messages = [];
  var isStreaming = false;

  var setupEl     = document.getElementById('chat-setup');
  var msgsEl      = document.getElementById('chat-messages');
  var quickEl     = document.getElementById('chat-quick');
  var inputWrap   = document.getElementById('chat-input-wrap');
  var inputEl     = document.getElementById('chat-input');
  var sendBtn     = document.getElementById('chat-send');
  var keyInput    = document.getElementById('api-key-input');
  var keySaveBtn  = document.getElementById('api-key-save');
  var keyError    = document.getElementById('chat-key-error');
  var statusDot   = document.getElementById('chat-status');
  var disconnEl   = document.getElementById('chat-disconnect');
  var disconnBtn  = document.getElementById('chat-disconnect-btn');

  function showChat() {{
    setupEl.style.display = 'none';
    msgsEl.style.display = 'flex';
    quickEl.style.display = 'flex';
    inputWrap.style.display = 'flex';
    disconnEl.style.display = 'block';
    statusDot.classList.remove('offline');
    if (messages.length === 0) {{
      addMsg('system', 'Verbunden. Stelle eine Frage zum Dashboard.');
    }}
  }}

  function showSetup() {{
    setupEl.style.display = 'block';
    msgsEl.style.display = 'none';
    quickEl.style.display = 'none';
    inputWrap.style.display = 'none';
    disconnEl.style.display = 'none';
    statusDot.classList.add('offline');
  }}

  function addMsg(role, text) {{
    var div = document.createElement('div');
    div.className = 'chat-msg chat-msg-' + role;
    div.innerHTML = formatMarkdown(text);
    msgsEl.appendChild(div);
    msgsEl.scrollTop = msgsEl.scrollHeight;
    return div;
  }}

  function formatMarkdown(text) {{
    return text
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>')
      .replace(/`(.+?)`/g, '<code>$1</code>')
      .replace(/\\n/g, '<br>');
  }}

  function setLoading(on) {{
    isStreaming = on;
    sendBtn.disabled = on;
    inputEl.disabled = on;
  }}

  async function sendMessage(text) {{
    if (!text.trim() || isStreaming) return;

    addMsg('user', text);
    messages.push({{ role: 'user', content: text }});
    inputEl.value = '';
    autoResize();

    setLoading(true);
    var assistantDiv = addMsg('assistant', '');
    var fullText = '';

    try {{
      var resp = await fetch(API_URL, {{
        method: 'POST',
        headers: {{
          'Content-Type': 'application/json',
          'x-api-key': apiKey,
          'anthropic-version': '2023-06-01',
          'anthropic-dangerous-direct-browser-access': 'true'
        }},
        body: JSON.stringify({{
          model: MODEL,
          max_tokens: MAX_TOKENS,
          system: SYSTEM_PROMPT,
          stream: true,
          messages: messages.slice(-20)
        }})
      }});

      if (!resp.ok) {{
        var errBody = await resp.text();
        throw new Error('API ' + resp.status + ': ' + errBody.slice(0, 200));
      }}

      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var buffer = '';

      while (true) {{
        var chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, {{ stream: true }});

        var lines = buffer.split('\\n');
        buffer = lines.pop() || '';

        for (var i = 0; i < lines.length; i++) {{
          var line = lines[i];
          if (!line.startsWith('data: ')) continue;
          var data = line.slice(6);
          if (data === '[DONE]') continue;
          try {{
            var evt = JSON.parse(data);
            if (evt.type === 'content_block_delta' && evt.delta && evt.delta.text) {{
              fullText += evt.delta.text;
              assistantDiv.innerHTML = formatMarkdown(fullText);
              msgsEl.scrollTop = msgsEl.scrollHeight;
            }}
          }} catch(e) {{}}
        }}
      }}

      if (!fullText) {{
        fullText = '(Keine Antwort erhalten)';
        assistantDiv.innerHTML = formatMarkdown(fullText);
      }}
      messages.push({{ role: 'assistant', content: fullText }});

    }} catch(err) {{
      assistantDiv.innerHTML = '<span style="color:var(--critical-text)">' +
        formatMarkdown('Fehler: ' + err.message) + '</span>';
    }}

    setLoading(false);
  }}

  function autoResize() {{
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
  }}

  keySaveBtn.addEventListener('click', function() {{
    var key = keyInput.value.trim();
    if (!key || !key.startsWith('sk-')) {{
      keyError.style.display = 'block';
      return;
    }}
    keyError.style.display = 'none';
    apiKey = key;
    localStorage.setItem('mdt_claude_key', key);
    showChat();
  }});

  keyInput.addEventListener('keydown', function(e) {{
    if (e.key === 'Enter') keySaveBtn.click();
  }});

  disconnBtn.addEventListener('click', function() {{
    apiKey = '';
    messages = [];
    localStorage.removeItem('mdt_claude_key');
    msgsEl.innerHTML = '';
    keyInput.value = '';
    showSetup();
  }});

  sendBtn.addEventListener('click', function() {{
    sendMessage(inputEl.value);
  }});

  inputEl.addEventListener('keydown', function(e) {{
    if (e.key === 'Enter' && !e.shiftKey) {{
      e.preventDefault();
      sendMessage(inputEl.value);
    }}
  }});

  inputEl.addEventListener('input', autoResize);

  quickEl.addEventListener('click', function(e) {{
    var btn = e.target.closest('button[data-q]');
    if (btn) sendMessage(btn.getAttribute('data-q'));
  }});

  if (apiKey) {{
    showChat();
  }} else {{
    showSetup();
  }}
}})();
</script>

</body>
</html>"""
    return html.replace("<!-- filled by _build_gebiets_svg -->", gebiets_svg_content)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _vollstaendigkeits_pruefung(html: str) -> list[tuple[str, bool]]:
    """Prueft ob alle Pflicht-Sektionen im generierten HTML vorhanden sind."""
    checks = [
        ("Tab-Navigation (7 Tabs, sticky)",
         'nav-tabs' in html and html.count('class="nav-tab') >= 7),
        ("Tab 1: Uebersicht – Qualifikations-Ampel 14 Kacheln",
         'id="tab-uebersicht"' in html and html.count('class="ampel-karte') >= 14),
        ("Tab 2: Auftraege – STK + Repair",
         'id="tab-auftraege"' in html and 'STK-Auftr' in html),
        ("Tab 3: Cross-Training + NRW-Warnung",
         'id="tab-crosstraining"' in html and 'cluster-badge' in html),
        ("Tab 4: Workflow (7 Schritte) + Puffer",
         'id="tab-workflow"' in html and 'wf-pipeline' in html),
        ("Tab 5: Business Case (Formeln)",
         'id="tab-business"' in html and 'bc-formula' in html),
        ("Tab 6: Gebietsoptimierung (NEU) mit Karte + Empfehlungen",
         'id="tab-gebietsopt"' in html and 'go-empf-grid' in html),
        ("Tab 7: Einstellungsbedarf Sterne-Karte",
         'id="tab-einstellung"' in html and 'einst-liste-header' in html),
        ("Techniker-Detail Modal",
         'tech-detail-overlay' in html and 'TECH_DETAIL_DATA' in html),
        ("KI-Chat: rechtes Panel 340px",
         'chat-panel' in html and 'chat-messages' in html),
        ("Premium Dark Design: #000810 Background",
         '#000810' in html),
        ("Google Fonts: Plus Jakarta Sans + Syne",
         'Plus Jakarta Sans' in html and 'Syne' in html),
        ("Grain-Overlay SVG",
         'grain-overlay' in html),
        ("Hugo Key Account Badges (T1, T6, T10, T11)",
         'hugo-ka-badge' in html and html.count('Hugo Key Account') >= 4),
        ("Demo-Badge (gold) im Header",
         'demo-badge' in html),
        ("Footer: 441 Tests gruen",
         '441 Tests' in html),
    ]
    return checks


def main() -> None:
    print("Lade Daten...")
    techniker    = _lade_techniker()
    ct_rows      = _lade_crosstraining()
    labor_zeiten = _lade_labor_zeiten()
    ampeln       = _berechne_ampeln(ct_rows, techniker)
    nrw_warnung  = _berechne_nrw_warnung(ct_rows)

    print("Berechne Dringlichkeiten fuer naechste 10 STK-Auftraege...")
    auftraege = naechste_faellige_auftraege(n=10)

    _DEMO_OFFSETS = [
        -65, -45, -20,
        5, 12, 18, 25,
        35, 48, 58,
    ]
    for i, a in enumerate(auftraege):
        offset = _DEMO_OFFSETS[i] if i < len(_DEMO_OFFSETS) else 30 + i * 5
        a.faelligkeitsdatum = _HEUTE + timedelta(days=offset)

    stk_rows: list[dict] = []
    for a in auftraege:
        d = _berechne_dringlichkeit(a.faelligkeitsdatum, _HEUTE)
        tage = d.tage_bis_faelligkeit
        tage_str = f"{tage}" if tage >= 0 else f"<span style='color:var(--critical-text)'>{tage}</span>"

        vorschlaege = schlage_termine_vor(a, heute=_HEUTE)
        if vorschlaege:
            termine_parts = []
            for v in vorschlaege:
                badge_css = {"optimal": "badge-normal", "moeglich": "badge-hoch", "knapp": "badge-kritisch"}
                css_cls = badge_css.get(v.bewertung, "badge-normal")
                termine_parts.append(
                    f"<span class='badge {css_cls}' title='{v.bewertung}'>"
                    f"{v.wochentag} {v.datum.strftime('%d.%m.')}</span>"
                )
            termine_html = " / ".join(termine_parts)
        else:
            termine_html = "&ndash;"

        stk_rows.append({
            "auftrag_id":   a.auftrag_id,
            "klinik":       a.klinik_name,
            "geraet":       a.geraet_id,
            "produkt":      a.produkt_familie,
            "faelligkeit":  a.faelligkeitsdatum.strftime("%d.%m.%Y"),
            "termine_vorschlag": termine_html,
            "dringlichkeit": d.stufe,
            "tage":         tage_str,
        })

    print("Generiere Demo-Repair-Auftraege...")
    from auftraege.models import RepairPhase as _RP

    _DEMO_REPAIRS = [
        {"aid": "REP-2026-0042", "klinik": "UKE Hamburg", "geraet": "HugoRAS",
         "stunden_offset": -7, "phase": _RP.KONTAKT_AUSSTEHEND, "kontakt": False,
         "ersatzteil": "&ndash;"},
        {"aid": "REP-2026-0041", "klinik": "Uniklinikum Ulm", "geraet": "EC300_Legend",
         "stunden_offset": -31, "phase": _RP.KONTAKT_AUSSTEHEND, "kontakt": False,
         "ersatzteil": "&ndash;"},
        {"aid": "REP-2026-0040", "klinik": "Uni Bonn", "geraet": "NIM4CM01",
         "stunden_offset": -50, "phase": _RP.KONTAKT_AUSSTEHEND, "kontakt": False,
         "ersatzteil": "&ndash;"},
        {"aid": "REP-2026-0039", "klinik": "Klinikum Bochum", "geraet": "HugoRAS",
         "stunden_offset": -20, "phase": _RP.KONTAKT_HERGESTELLT, "kontakt": True,
         "ersatzteil": "Im Fahrzeug"},
        {"aid": "REP-2026-0038", "klinik": "Charit&eacute; Berlin", "geraet": "O-arm",
         "stunden_offset": -36, "phase": _RP.ERSATZTEIL_BESTELLT, "kontakt": True,
         "ersatzteil": "Bestellt (3-5 Tage)"},
    ]
    _JETZT = datetime.now()
    repair_rows: list[dict] = []
    for rd in _DEMO_REPAIRS:
        eingang = _JETZT + timedelta(hours=rd["stunden_offset"])
        stunden = abs(rd["stunden_offset"])
        verbleibend = 48 - stunden
        if rd["kontakt"]:
            if rd["phase"] == _RP.ERSATZTEIL_BESTELLT:
                sla_status = "Blau"
            else:
                sla_status = "Gruen"
            sla_text = "&#10003; Kontakt"
        elif stunden >= 48:
            sla_status = "Kritisch"
            sla_text = "SLA VERLETZT"
        elif stunden >= 40:
            sla_status = "Rot"
            sla_text = f"SLA: noch {round(verbleibend)}h"
        elif stunden >= 24:
            sla_status = "Gelb"
            sla_text = f"SLA: noch {round(verbleibend)}h"
        else:
            sla_status = "Gruen"
            sla_text = f"SLA: noch {round(verbleibend)}h"

        repair_rows.append({
            "auftrag_id": rd["aid"],
            "klinik": rd["klinik"],
            "geraet": rd["geraet"],
            "eingang": eingang.strftime("%d.%m. %H:%M"),
            "sla_status": sla_status,
            "sla_text": sla_text,
            "phase": rd["phase"].value,
            "ersatzteil": rd["ersatzteil"],
        })

    print("Sortiere Crosstraining-Top-5...")
    ct_top5 = sorted(
        ct_rows,
        key=lambda r: float(r.get("potentielles_zusatz_stk_pa", 0)),
        reverse=True,
    )[:5]

    print("Berechne Gebietsmetriken...")
    gebiets_metriken = _berechne_gebietsmetriken(techniker)

    print("Generiere Demo-Einsatzhistorie...")
    demo_history = _generate_demo_history(techniker, labor_zeiten)

    print("Rendere HTML...")
    html = render_html(
        ampeln=ampeln,
        stk_rows=stk_rows,
        ct_top5=ct_top5,
        techniker=techniker,
        nrw_warnung=nrw_warnung,
        erstellt_am=datetime.now(),
        ct_rows=ct_rows,
        gebiets_metriken=gebiets_metriken,
        labor_zeiten=labor_zeiten,
        demo_history=demo_history,
        repair_rows=repair_rows,
    )

    _OUT_PATH.write_text(html, encoding="utf-8")
    print(f"Gespeichert: {_OUT_PATH}")

    # Ampel-Zusammenfassung auf der Konsole
    print("\nAmpel-Uebersicht:")
    for a in ampeln:
        print(f"  {a['techniker_id']} ({a['standort']:12s}) "
              f"{a['ampel_label']:5s}  {a['abdeckung_pct']:3d}%  "
              f"{a['qualifiziert']}/{a['regional']} Familien  "
              f"+{a['zusatz_stk']:.0f} STK/a Potenzial")

    if nrw_warnung:
        print(f"\nNRW-Warnung ausgeloest: {nrw_warnung['anzahl_schwach']} schwache Techniker, "
              f"{nrw_warnung['gesamt_stk']:,} STK/a ungenutztes Potenzial")
    else:
        print("\nKeine NRW-Warnung.")

    # Vollstaendigkeits-Pruefung
    print("\n" + "=" * 60)
    print("VOLLSTAENDIGKEITS-PRUEFUNG")
    print("=" * 60)
    checks = _vollstaendigkeits_pruefung(html)
    alle_ok = True
    for label, ok in checks:
        symbol = "[OK]" if ok else "[X]"
        print(f"  {symbol} {label}")
        if not ok:
            alle_ok = False
    print("-" * 60)
    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    if alle_ok:
        print(f"  ERGEBNIS: {passed}/{total} Pruefpunkte bestanden!")
    else:
        print(f"  ERGEBNIS: {passed}/{total} -- fehlende Sektionen pruefen!")


if __name__ == "__main__":
    main()
