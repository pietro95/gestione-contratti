"""TC-29: costi accessori previsti di una voce (SPEC §5.2, Rev53).

Rimborso INPS e oneri previdenziali in percentuale, spese vive come stima forfettaria: gravano
sulla previsione di budget (cassa, fatturato e stanziato, competenza), non sull'impegno; la
fattura che prende il posto di una rata porta i suoi importi reali.
"""

from dataclasses import replace
from decimal import Decimal

from contratti.engine import accessori
from contratti.engine.budget import calcola, ripartizione_sal
from contratti.engine.previsioni import previsti
from contratti.engine.scadenzario import genera_rate
from contratti.engine.tipi import Consuntivo, ContrattoBase, Livello, Rata, TipoConsuntivo

from .casi import D, euro, piano, voce

INIZIO, FINE = D(2027, 1, 1), D(2027, 12, 31)


def voce_base(**kw):
    return voce(
        "12000.00",
        INIZIO,
        FINE,
        piano=piano("posticipata", "trimestrale"),
        oneri_pct=Decimal(4),
        spese_vive_stimate=euro("400.00"),
        **kw,
    )


def test_a_rata_prevista_con_accessori():
    v = voce_base()
    viste, _ = calcola([v])
    assert viste["impegno"].importo(2027) == euro("12000.00")
    assert viste["cassa"].importo(2027) == euro("12880.00")
    assert viste["consuntivo"].importo(2027) == euro("12880.00")
    assert viste["competenza"].importo(2027) == euro("12880.00")
    assert accessori.per_rate(v, [r.importo for r in genera_rate(v)]) == [euro("220.00")] * 4


def test_b_fattura_sostituisce_rata_e_accessori():
    v = voce_base()
    rate = genera_rate(v)
    fattura = Consuntivo(
        TipoConsuntivo.FATTURA, euro("3177.30"), D(2027, 1, 1), D(2027, 3, 31),
        accessori=euro("177.30"),
    )  # fmt: skip
    v = replace(v, rate=(replace(rate[0], consuntivo=fattura), *rate[1:]))
    viste, _ = calcola([v])
    assert viste["consuntivo"].importo(2027) == euro("12837.30")
    assert viste["impegno"].importo(2027) == euro("12000.00")


def test_c_rimborso_inps_e_oneri_a_cascata():
    v = voce_base(rimborso_inps_pct=Decimal(2))
    assert accessori.maggiorazione(v, euro("3000.00")) == euro("182.40")
    viste, _ = calcola([v])
    assert viste["cassa"].importo(2027) == euro("13129.60")


def test_d_sal_residuo_sul_valore_base():
    v = voce(
        "10000.00", INIZIO, D(2028, 12, 31), piano=piano("sal"),
        oneri_pct=Decimal(4), spese_vive_stimate=euro("500.00"),
        consuntivi=(
            Consuntivo(
                TipoConsuntivo.FATTURA, euro("4160.00"), D(2027, 5, 1), D(2027, 5, 31),
                data=D(2027, 5, 31), accessori=euro("160.00"),
            ),
        ),
        rate=(Rata(1, D(2028, 6, 30), D(2028, 8, 31), euro("6000.00")),),
    )  # fmt: skip
    ripartizione, _ = ripartizione_sal(v, Livello.FISSO, "cassa")
    assert ripartizione.consuntivo_per_anno() == {2027: euro("4160.00")}
    assert ripartizione.previsto == {2028: euro("6540.00")}
    assert ripartizione.non_pianificato == euro("0.00")


def test_e_rinnovo_previsto_eredita_gli_accessori():
    base = ContrattoBase(fine_effettiva=FINE, durata_mesi=12, voci=(voce_base(),))
    (rinnovo,) = previsti(
        base, decisione="rinnovare", orizzonte=D(2028, 6, 30), adeguamento=lambda _: Decimal(0)
    )
    viste, _ = calcola(rinnovo.voci)
    assert viste["impegno"].importo(2028) == euro("12000.00")
    assert viste["cassa"].importo(2028) == euro("12880.00")


def test_f_senza_accessori_nulla_cambia():
    v = voce("12000.00", INIZIO, FINE, piano=piano("posticipata", "trimestrale"))
    viste, _ = calcola([v])
    assert viste["cassa"].importo(2027) == euro("12000.00")
