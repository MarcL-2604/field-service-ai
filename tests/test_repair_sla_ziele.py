"""Tests fuer die neuen Repair-SLA-Abschluss-Ziele (AUFGABE 4).

REPAIR_SLA_VERTRAGSKUNDE_TAGE / REPAIR_SLA_NICHT_VERTRAGSKUNDE_TAGE sind eine
eigenstaendige Frist (tatsaechlicher Auftragsabschluss), getrennt von der
bestehenden 48h-Kundenkontakt-Pflicht (REPAIR_SLA_STUNDEN). Beide muessen im
SLA-Status-Tooltip klar unterschieden dargestellt werden.
"""

from config import (
    REPAIR_SLA_STUNDEN,
    REPAIR_SLA_VERTRAGSKUNDE_TAGE,
    REPAIR_SLA_NICHT_VERTRAGSKUNDE_TAGE,
)
from reporting.dashboard import _repair_sla_tooltip_text


class TestRepairSlaKonstanten:
    def test_vertragskunde_2_5_tage(self):
        assert REPAIR_SLA_VERTRAGSKUNDE_TAGE == 2.5

    def test_nicht_vertragskunde_3_5_tage(self):
        assert REPAIR_SLA_NICHT_VERTRAGSKUNDE_TAGE == 3.5

    def test_bestehende_48h_kontaktfrist_unveraendert(self):
        assert REPAIR_SLA_STUNDEN == 48


class TestRepairSlaTooltipText:
    def setup_method(self):
        self.text = _repair_sla_tooltip_text()

    def test_enthaelt_48h_erstkontakt(self):
        assert "48h" in self.text and "Erstkontakt" in self.text

    def test_enthaelt_abschluss_ziele_mit_deutschem_dezimalkomma(self):
        assert "2,5 Tage" in self.text
        assert "3,5 Tage" in self.text

    def test_unterscheidet_vertragskunde_und_nicht_vertragskunde(self):
        assert "Vertragskunden" in self.text
        assert "Nicht-Vertragskunden" in self.text

    def test_erstkontakt_und_abschluss_als_getrennte_fristen_erkennbar(self):
        assert "Erstkontakt" in self.text
        assert "Abschluss" in self.text
        assert self.text.index("Erstkontakt") < self.text.index("Abschluss")
