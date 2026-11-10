"""Rev42: spese vive e rimborso INPS in fattura (gravano sul budget, non sul contratto),
regime forfettario, righe nuove del commento per PAC. Dati di fantasia."""

import datetime
from dataclasses import replace
from decimal import Decimal

import pytest

from contratti import acquisti, adapters, fatture
from contratti import models as m
from contratti.engine.acquisti import DatiPAC, commento_pac, importo_quadra, valore_base_proposto

from . import factories as f

D = Decimal
COMPETENZA = (datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))

# Esempio del responsabile: base 1.666,67 + rimborso INPS 367,83 + oneri 4% su 2.034,50
# (81,38) + spese vive 82,34 = 2.197,22, senza IVA.
PAC_FORFETTARIO = """Contratto: 5800000013
ODA : RDC-0001
MAP: MAP-0001
CDC: C0001
COGE: 600010
WBS: WBS-TEST-01

Valore base prelevato da contratto: € 1.666,67
Rimborso riconosciuto da contratto per costi INPS: € 367,83
Oneri previdenziali (ribaltamento 4% INPS): € 81,38
Spese vive: € 82,34
Senza IVA (regime forfettario)"""

DATI = DatiPAC(
    numero_contratto="5800000013",
    numero_rdc="RDC-0001",
    accettazione="MAP",
    numero_accettazione="MAP-0001",
    centro_costo="C0001",
    conto="600010",
    wbs="WBS-TEST-01",
    valore_base=D("1666.67"),
    oneri=D("81.38"),
    rimborso_inps=D("367.83"),
    spese_vive=D("82.34"),
    regime_forfettario=True,
)


def test_commento_pac_forfettario_con_spese_vive():
    assert commento_pac(DATI) == PAC_FORFETTARIO


def test_commento_pac_senza_i_dati_nuovi_e_invariato():
    base = replace(
        DATI, rimborso_inps=None, spese_vive=None, regime_forfettario=False, oneri=D("173.66"),
        valore_base=D("1504.17"), bollo=D("2.00"),
    )  # fmt: skip
    testo = commento_pac(base)
    assert "Rimborso" not in testo and "Spese vive" not in testo and "forfettario" not in testo
    assert "Oneri previdenziali: € 173,66" in testo  # senza rimborso INPS, niente percentuale


def test_quadratura_e_proposta_con_gli_extra():
    extra = D("367.83") + D("82.34")
    assert importo_quadra(D("2197.22"), D("1666.67"), D("81.38"), None, None, None, extra)
    assert not importo_quadra(D("2197.22"), D("1666.67"), D("81.38"), None)
    assert valore_base_proposto(D("2197.22"), D("81.38"), None, None, extra) == D("1666.67")


@pytest.fixture
def fattura(db):
    c = f.contratto()
    return m.Fattura.objects.create(
        fornitore=c.fornitore, contratto=c, numero="FA-1", data=datetime.date(2026, 2, 3),
        importo_documento=D("2197.22"),
    )  # fmt: skip


def _salva(fattura, **extra):
    fatture.aggiorna_importi(
        fattura, D("1666.67"), D("81.38"), None, competenza=COMPETENZA,
        rimborso_inps=D("367.83"), spese_vive=D("82.34"), **extra,
    )  # fmt: skip
    return fatture.QS_FATTURE.get(pk=fattura.pk)


def test_forfettario_nessuna_iva_e_quadra(fattura):
    x = _salva(fattura, regime_forfettario=True)
    assert x.iva is None and x.regime_forfettario
    assert fatture.anomalie(x) == []
    assert fatture.commento_pac(x).endswith("Senza IVA (regime forfettario)")


def test_forfettario_con_iva_rifiutato(fattura):
    with pytest.raises(fatture.OperazioneNonAmmessa, match="forfettario"):
        _salva(fattura, regime_forfettario=True, iva=D("10"))


def test_budget_conta_gli_extra_il_contratto_no(fattura):
    x = _salva(fattura, regime_forfettario=True)
    # Budget: valore base + oneri + rimborso INPS + spese vive, sulla competenza della fattura.
    assert adapters._consuntivo_fattura(x).importo == D("2197.22")
    # Contratto: fatturato e residuo sul solo valore base.
    assert acquisti.riepilogo_esecuzione(x.contratto).esecuzione.fatturato == D("1666.67")
