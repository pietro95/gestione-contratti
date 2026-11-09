"""Una fattura che copre più rate dello scadenzario (Rev41): il fornitore emette un'unica
fattura per più periodi."""

import datetime
from decimal import Decimal

import pytest

from contratti import fatture
from contratti import models as m
from contratti.acquisti import OperazioneNonAmmessa
from contratti.engine.tipi import Livello
from contratti.forms_fatture import ImportiForm
from reports.budget import Filtri, calcola_budget

from . import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
OGGI = D(2026, 10, 1)
COMPETENZA = (D(2026, 1, 1), D(2026, 9, 30))


@pytest.fixture
def scenario(db):
    """Quattro rate trimestrali da 1.000,00 (fisso 4.000,00) e una fattura unica da 3.000,00."""
    c = f.contratto(data_inizio=D(2026, 1, 1), durata_mesi=12, numero_contratto="5800000077")
    v = f.voce(c, importo_fisso=Decimal("4000.00"))
    p = f.piano(v, modalita="anticipata", periodicita="trimestrale")
    rate = [
        f.rata(
            p,
            numero=n,
            data_fattura=D(2026, 3 * n - 2, 1),
            data_pagamento_stimata=D(2026, 3 * n - 2, 28),
            importo=Decimal("1000.00"),
            periodo_dal=D(2026, 3 * n - 2, 1),
            periodo_al=D(2026, 3 * n, 28),
        )
        for n in (1, 2, 3, 4)
    ]
    fa = m.Fattura.objects.create(
        fornitore=c.fornitore, contratto=c, voce=v, numero="FA-77", data=D(2026, 1, 15),
        importo_documento=Decimal("3000.00"),
    )  # fmt: skip
    return {"c": c, "v": v, "p": p, "rate": rate, "fa": fa}


def _consuntivo(anno=2026):
    budget = calcola_budget(Filtri(anno=anno, previsionali=False), OGGI)
    return budget.totali()["totale"]["consuntivo"][Livello.FISSO]


def _importi(fa, rate, valore_base="3000.00", voce=None):
    fatture.aggiorna_importi(
        fa, Decimal(valore_base), None, None, voce, rate, iva=Decimal("0.00"),
        competenza=COMPETENZA,
    )  # fmt: skip


def test_tre_rate_con_un_unica_fattura(scenario):
    fa, rate = scenario["fa"], scenario["rate"]
    _importi(fa, rate[:3], voce=scenario["v"])
    for r in m.Rata.objects.filter(pk__in=[r.pk for r in rate[:3]]):
        assert (r.fattura_id, r.consuntivo, r.numero_fattura) == (fa.pk, True, "FA-77")
    quarta = m.Rata.objects.get(pk=rate[3].pk)
    assert (quarta.fattura_id, quarta.consuntivo) == (None, False)
    assert sorted(r.numero for r in fa.rate.all()) == [1, 2, 3]


def test_il_budget_conta_la_fattura_una_volta(scenario):
    _importi(scenario["fa"], scenario["rate"][:3], "2950.00", scenario["v"])
    # 2.950,00 della fattura (competenza 01/01-30/09) + 1.000,00 della quarta rata prevista:
    # le tre rate sostituite non si contano due volte.
    assert _consuntivo(2026) == Decimal("3950.00")


def test_una_rata_sola_come_prima(scenario):
    fa, rate = scenario["fa"], scenario["rate"]
    _importi(fa, rate[:1], "1000.00", scenario["v"])
    assert [r.pk for r in fa.rate.all()] == [rate[0].pk]
    assert _consuntivo(2026) == Decimal("1000.00") + Decimal("3000.00")


def test_rate_tolte_tornano_alla_previsione(scenario):
    fa, rate = scenario["fa"], scenario["rate"]
    _importi(fa, rate[:3], voce=scenario["v"])
    _importi(fa, rate[:2], "2000.00", scenario["v"])
    terza = m.Rata.objects.get(pk=rate[2].pk)
    assert (terza.fattura_id, terza.consuntivo, terza.numero_fattura) == (None, False, "")
    assert sorted(r.numero for r in fa.rate.all()) == [1, 2]
    _importi(fa, [], "2000.00", scenario["v"])
    assert not fa.rate.exists()
    assert not m.Rata.objects.filter(consuntivo=True).exists()


def test_rata_gia_di_un_altra_fattura(scenario):
    c, fa, rate = scenario["c"], scenario["fa"], scenario["rate"]
    _importi(fa, rate[:2], "2000.00", scenario["v"])
    altra = m.Fattura.objects.create(
        fornitore=c.fornitore, contratto=c, numero="FA-78", data=D(2026, 7, 1),
        importo_documento=Decimal("1000.00"),
    )  # fmt: skip
    with pytest.raises(OperazioneNonAmmessa, match="già abbinata a un'altra fattura"):
        _importi(altra, rate[1:3], "1000.00", scenario["v"])
    assert m.Rata.objects.get(pk=rate[1].pk).fattura_id == fa.pk


def test_rate_di_voci_diverse(scenario):
    c, fa, rate = scenario["c"], scenario["fa"], scenario["rate"]
    v2 = f.voce(c, importo_fisso=Decimal("500.00"), descrizione="Altra voce")
    p2 = f.piano(v2, modalita="anticipata", periodicita="annuale")
    r2 = f.rata(p2, importo=Decimal("500.00"))
    with pytest.raises(OperazioneNonAmmessa, match="stessa voce"):
        _importi(fa, [rate[0], r2], voce=scenario["v"])
    assert not fa.rate.exists()


def test_rata_di_un_altro_contratto(scenario):
    altro = f.contratto(numero_contratto="5800000078")
    rata_altrui = f.rata(f.piano(f.voce(altro)))
    with pytest.raises(OperazioneNonAmmessa, match="altro contratto"):
        _importi(scenario["fa"], [rata_altrui], voce=scenario["v"])


def test_stanziamento_su_una_rata_coperta_si_chiude(scenario):
    fa, rate = scenario["fa"], scenario["rate"]
    s = m.Stanziamento.objects.create(
        voce=scenario["v"], rata=rate[1], importo=Decimal("1000.00"),
        competenza_dal=D(2026, 4, 1), competenza_al=D(2026, 6, 30),
    )  # fmt: skip
    assert not s.chiuso
    _importi(fa, rate[:3], voce=scenario["v"])
    s = m.Stanziamento.objects.get(pk=s.pk)
    assert s.chiuso
    assert _consuntivo(2026) == Decimal("3000.00") + Decimal("1000.00")


def test_scollegare_dal_contratto_libera_le_rate(scenario):
    fa, rate = scenario["fa"], scenario["rate"]
    _importi(fa, rate[:3], voce=scenario["v"])
    fatture.assegna_contratto(fa, None)
    assert not m.Rata.objects.filter(fattura__isnull=False).exists()
    assert not m.Rata.objects.filter(consuntivo=True).exists()


def test_form_importi_propone_solo_rate_libere_e_controlla_la_voce(scenario):
    c, fa, rate = scenario["c"], scenario["fa"], scenario["rate"]
    altra = m.Fattura.objects.create(
        fornitore=c.fornitore, contratto=c, numero="FA-79", data=D(2026, 7, 1),
        importo_documento=Decimal("1000.00"),
    )  # fmt: skip
    _importi(altra, rate[:1], "1000.00", scenario["v"])
    form = ImportiForm(fattura=fa)
    assert [r.numero for r in form.fields["rate"].queryset] == [2, 3, 4]
    v2 = f.voce(c, importo_fisso=Decimal("500.00"), descrizione="Altra voce")
    r2 = f.rata(f.piano(v2, modalita="anticipata", periodicita="annuale"))
    dati = {
        "valore_base": "100,00", "competenza_dal": "01/01/2026", "competenza_al": "31/12/2026",
        "rate": [rate[1].pk, r2.pk],
    }  # fmt: skip
    form = ImportiForm(dati, fattura=fa)
    assert not form.is_valid() and "rate" in form.errors


def test_la_storia_della_rata_traccia_la_fattura(scenario):
    _importi(scenario["fa"], scenario["rate"][:2], "2000.00", scenario["v"])
    ultima = scenario["rate"][0].history.first()
    assert ultima.fattura_id == scenario["fa"].pk
