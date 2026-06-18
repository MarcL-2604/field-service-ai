"""
Techniker-Stammdaten
====================
Wohnort, PLZ, Koordinaten, Kontakt, Kapazität.
Gebietsplanung wird ABGELEITET aus techniker.plz + gerät.klinik_plz (Haversine).

Neu in v3: dieses Modul ersetzt manuelle Gebietsmatrix.
"""

from __future__ import annotations

import math
from pydantic import BaseModel, Field, field_validator, model_validator


# ── Konstanten ────────────────────────────────────────────────────────────────

HUGO_KA_IDS = {"T1", "T6", "T10", "T11"}
KAPAZITAET_STANDARD_H = 32.0
HUGO_AUSLASTUNG_FAKTOR = 0.80          # 80% von 32h = 25.6h
HUGO_RESERVE_FAKTOR = 0.20             # 20% Reserve für ungeplante Hugo-Calls
HAVERSINE_STRASSENFAKTOR = 1.35        # Luftlinie → Fahrzeit-Korrekturfaktor
DURCHSCHNITT_KMH = 80.0                # Angenommene Durchschnittsgeschwindigkeit


# ── Modell ────────────────────────────────────────────────────────────────────

class TechnikerStammdaten(BaseModel):
    """Stammdaten eines Servicetechnikers inkl. Wohnort für Gebietsplanung."""

    tech_id: str = Field(..., pattern=r"^T\d{1,2}$", description="z.B. T1, T10")
    nachname: str = Field(..., min_length=1)
    vorname: str = Field(..., min_length=1)
    strasse: str | None = None
    plz: str = Field(..., pattern=r"^\d{5}$", description="5-stellige PLZ des Wohnorts")
    ort: str = Field(..., min_length=1)
    bundesland: str | None = None
    lat: float | None = Field(None, ge=-90.0, le=90.0, description="Latitude Wohnort")
    lon: float | None = Field(None, ge=-180.0, le=180.0, description="Longitude Wohnort")
    telefon: str | None = None
    email: str | None = None
    kapazitaet_h: float = Field(
        default=KAPAZITAET_STANDARD_H,
        ge=0.0,
        le=45.0,
        description="Wochensollkapazität in Stunden (ArbZG-Maximum: 45h)",
    )
    hugo_ka: bool = Field(default=False, description="Hugo Key Account Techniker")

    @field_validator("tech_id")
    @classmethod
    def tech_id_uppercase(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def hugo_ka_auto(self) -> "TechnikerStammdaten":
        """Hugo-KA-Flag automatisch setzen wenn ID bekannt."""
        if self.tech_id in HUGO_KA_IDS:
            self.hugo_ka = True
        return self

    # ── Berechnete Properties ─────────────────────────────────────────────────

    @property
    def name_voll(self) -> str:
        return f"{self.vorname} {self.nachname}"

    @property
    def effektive_kapazitaet_h(self) -> float:
        """Nutzbare Kapazität nach Hugo-Reserve."""
        if self.hugo_ka:
            return self.kapazitaet_h * HUGO_AUSLASTUNG_FAKTOR
        return self.kapazitaet_h

    @property
    def hugo_reserve_h(self) -> float:
        """Reservierte Stunden für ungeplante Hugo-Calls."""
        if self.hugo_ka:
            return self.kapazitaet_h * HUGO_RESERVE_FAKTOR
        return 0.0

    @property
    def hat_koordinaten(self) -> bool:
        return self.lat is not None and self.lon is not None

    # ── Gebietsplanung: Distanzberechnung ─────────────────────────────────────

    def distanz_km(self, ziel_lat: float, ziel_lon: float) -> float | None:
        """
        Haversine-Distanz vom Wohnort zum Zielort in km.
        Gibt None zurück wenn Koordinaten fehlen.
        """
        if not self.hat_koordinaten:
            return None
        return _haversine(self.lat, self.lon, ziel_lat, ziel_lon)

    def fahrzeit_min(self, ziel_lat: float, ziel_lon: float) -> float | None:
        """
        Geschätzte Fahrzeit in Minuten.
        Haversine × Straßenfaktor / Durchschnittsgeschwindigkeit.
        """
        d = self.distanz_km(ziel_lat, ziel_lon)
        if d is None:
            return None
        strecke = d * HAVERSINE_STRASSENFAKTOR
        return (strecke / DURCHSCHNITT_KMH) * 60.0

    def plz_naehe(self, klinik_plz: str, radius: int = 2) -> bool:
        """
        PLZ-Näherung: gleiche oder benachbarte PLZ-Region (erste 2 Stellen).
        Fallback wenn keine Koordinaten vorhanden.
        """
        if len(self.plz) < 2 or len(klinik_plz) < 2:
            return False
        return abs(int(self.plz[:2]) - int(klinik_plz[:2])) <= radius


# ── Haversine ─────────────────────────────────────────────────────────────────

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Luftlinien-Distanz in km zwischen zwei Koordinaten."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Import-Helper ─────────────────────────────────────────────────────────────

def techniker_aus_csv_zeile(zeile: dict) -> TechnikerStammdaten:
    """
    Erstellt TechnikerStammdaten aus einer CSV-Zeile (nach Spalten-Mapping).
    Tolerant gegenüber fehlenden optionalen Feldern.
    """
    def _float_or_none(v: str | None) -> float | None:
        if not v:
            return None
        try:
            return float(v.replace(",", "."))
        except (ValueError, AttributeError):
            return None

    def _bool_from_str(v: str | None) -> bool:
        return str(v or "").strip().lower() in ("j", "ja", "yes", "true", "1")

    return TechnikerStammdaten(
        tech_id=str(zeile.get("tech_id", "")).strip(),
        nachname=str(zeile.get("nachname", "")).strip(),
        vorname=str(zeile.get("vorname", "")).strip(),
        strasse=zeile.get("strasse") or None,
        plz=str(zeile.get("plz", "")).strip(),
        ort=str(zeile.get("ort", "")).strip(),
        bundesland=zeile.get("bundesland") or None,
        lat=_float_or_none(zeile.get("lat")),
        lon=_float_or_none(zeile.get("lon")),
        telefon=zeile.get("telefon") or None,
        email=zeile.get("email") or None,
        kapazitaet_h=_float_or_none(zeile.get("kapazitaet_h")) or KAPAZITAET_STANDARD_H,
        hugo_ka=_bool_from_str(zeile.get("hugo_ka")),
    )
