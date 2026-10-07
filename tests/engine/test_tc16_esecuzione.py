"""TC-16: esecuzione, residuo e chiusura di un contratto una tantum (parte del motore)."""

from decimal import Decimal

import pytest

from contratti.engine.acquisti import (
    ContrattoGenerato,
    DatiRDA,
    DocumentoEseguito,
    Fase,
    FatturaRegistrata,
    MotivoChiusura,
    anomalie_esecuzione,
    esecuzione,
    fase,
    motivo_da_chiudere,
)
from contratti.engine.scadenze import alert, data_fine_effettiva
from contratti.engine.tipi import Scadenza

from .casi import D

FISSO, MASSIMALE = Decimal("10000.00"), Decimal("2000.00")
F1 = Scadenza(inizio=D(2026, 3, 2), durata_mesi=1, lead_time_mesi=2)
FATTURE = [
    FatturaRegistrata(D(2026, 3, 15), Decimal("4000.00"), "FA-1", 1),
    FatturaRegistrata(D(2026, 4, 20), Decimal("5000.00"), "FA-2", 1),
    FatturaRegistrata(D(2026, 5, 5), Decimal("3500.00"), "FA-3", 1),
]
DOCUMENTI = [
    DocumentoEseguito("DDT", D(2026, 3, 10)),
    DocumentoEseguito("RICEZIONE", D(2026, 4, 28), finale=True),
]
CHIUSURA = D(2026, 5, 10)


def _chiusura(oggi):
    return CHIUSURA if oggi >= CHIUSURA else None


def _rda(oggi):
    prime = [d.data for d in DOCUMENTI] + [f.data for f in FATTURE]
    contratto = ContrattoGenerato(
        data_emissione=D(2026, 3, 2),
        data_inizio=D(2026, 3, 2),
        data_chiusura=CHIUSURA,
        prima_esecuzione=min(prime),
    )
    return DatiRDA(data_creazione=D(2026, 2, 20), numero="5100000016", contratti=(contratto,))


@pytest.mark.parametrize(
    (
        "oggi",
        "fatturato",
        "residuo_fisso",
        "residuo_massimo",
        "pct",
        "motivo",
        "anomalie",
        "fase_r1",
    ),
    [
        (D(2026, 3, 5), "0.00", "10000.00", "12000.00", 0, None, [], Fase.CONTRATTO_EMESSO),
        (
            D(2026, 4, 25),
            "9000.00",
            "1000.00",
            "3000.00",
            90,
            MotivoChiusura.ATTESTAZIONE_MANCANTE,
            [],
            Fase.IN_ESECUZIONE,
        ),
        (
            D(2026, 4, 30),
            "9000.00",
            "1000.00",
            "3000.00",
            90,
            MotivoChiusura.FATTURE_MANCANTI,
            [],
            Fase.IN_ESECUZIONE,
        ),
        (
            D(2026, 5, 6),
            "12500.00",
            "-2500.00",
            "-500.00",
            125,
            MotivoChiusura.PRONTO,
            ["FATTURATO_OLTRE_MASSIMO"],
            Fase.IN_ESECUZIONE,
        ),
        (
            D(2026, 5, 11),
            "12500.00",
            "-2500.00",
            "-500.00",
            125,
            None,
            ["FATTURATO_OLTRE_MASSIMO"],
            Fase.CHIUSA,
        ),
    ],
)
def test_tc16(oggi, fatturato, residuo_fisso, residuo_massimo, pct, motivo, anomalie, fase_r1):
    e = esecuzione(FISSO, MASSIMALE, FATTURE, oggi)
    assert e.fatturato == Decimal(fatturato)
    assert e.residuo_fisso == Decimal(residuo_fisso)
    assert e.residuo_massimo == Decimal(residuo_massimo)
    assert e.avanzamento_pct == pct
    fine = data_fine_effettiva(F1)
    assert fine == D(2026, 4, 1)
    assert motivo_da_chiudere(fine, _chiusura(oggi), DOCUMENTI, e.residuo_fisso, oggi) == motivo
    assert anomalie_esecuzione(FISSO, MASSIMALE, FATTURE, DOCUMENTI, _chiusura(oggi), oggi) == (
        anomalie
    )
    assert fase(_rda(oggi), oggi) == fase_r1


def test_tc16_una_tantum_mai_in_alert():
    for oggi in (D(2026, 3, 5), D(2026, 4, 2), D(2027, 1, 1)):
        assert (
            alert(
                F1,
                oggi,
                decisione="rinnovare",
                stato_pratica=None,
                ha_successore=False,
                finestra_mesi=3,
                una_tantum=True,
            )
            is None
        )


def test_chiuso_senza_attestazione_e_fattura_duplicata():
    fatture = [
        FatturaRegistrata(D(2026, 3, 15), Decimal("100.00"), "FA-1", 1),
        FatturaRegistrata(D(2026, 3, 16), Decimal("100.00"), "fa-1 ", 1),
    ]
    codici = anomalie_esecuzione(
        FISSO, MASSIMALE, fatture, [DocumentoEseguito("DDT", D(2026, 3, 10))], D(2026, 4, 1),
        D(2026, 4, 2),
    )  # fmt: skip
    assert codici == ["CHIUSO_SENZA_ATTESTAZIONE", "FATTURA_DUPLICATA"]


def test_attestazione_parziale_non_basta():
    parziale = [DocumentoEseguito("ATTESTAZIONE", D(2026, 4, 2), finale=False)]
    motivo = motivo_da_chiudere(D(2026, 4, 1), None, parziale, Decimal("0"), D(2026, 4, 5))
    assert motivo == MotivoChiusura.ATTESTAZIONE_MANCANTE


def test_avanzamento_senza_fisso_sul_massimale():
    e = esecuzione(Decimal("0"), Decimal("500.00"), [FATTURE[0]], D(2026, 12, 31))
    assert e.avanzamento_pct == 800
    assert esecuzione(Decimal("0"), Decimal("0"), [], D(2026, 1, 1)).avanzamento_pct is None
