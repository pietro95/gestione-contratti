"""F8: OPEX e CAPEX sono budget distinti; i rinnovi possono cambiare natura e conto."""

import datetime
from decimal import Decimal

import pytest

from contratti import adapters
from contratti import models as m
from contratti.engine.tipi import Livello
from reports.budget import Filtri, calcola_budget
from reports.piano_ordini import calcola_piano

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
OGGI = D(2026, 6, 1)
FISSO = Livello.FISSO


def _conto(codice, descrizione="Conto di prova"):
    return m.ContoCoge.objects.create(
        codice=codice, descrizione=descrizione, valido_dal=D(2020, 1, 1)
    )


@pytest.fixture
def archivio():
    """Un contratto OPEX annuale e uno CAPEX finanziato, entrambi da rinnovare."""
    opex = f.contratto(
        fabbisogno=f.fabbisogno("Assistenza", decisione="rinnovare"),
        data_inizio=D(2026, 1, 1),
        durata_mesi=12,
    )
    f.piano(f.voce(opex, importo_fisso=Decimal("1200.00"), conto=_conto("61000001")))
    progetto = m.Progetto.objects.create(codice_wbs="WBS-PROVA-01", descrizione="Progetto di prova")
    conto_capex = _conto("11000001", "Immobilizzazioni di prova")
    capex = f.contratto(
        fabbisogno=f.fabbisogno("Piattaforma", decisione="rinnovare"),
        data_inizio=D(2026, 1, 1),
        durata_mesi=12,
        natura=m.Natura.CAPEX,
        finanziamento=m.Contratto.Finanziamento.FINANZIATO,
        progetto=progetto,
    )
    f.piano(f.voce(capex, importo_fisso=Decimal("5000.00"), conto=conto_capex))
    return {"opex": opex, "capex": capex}


def _cassa(filtri, parte="totale"):
    return calcola_budget(filtri, OGGI).totali()[parte]["cassa"][FISSO]


def test_le_nature_partizionano_il_budget_senza_sommarsi(archivio):
    b = calcola_budget(Filtri(anno=2026), OGGI)
    sezioni = {s.filtri.natura: s for s in b.sezioni()}
    assert list(sezioni) == ["OPEX", "CAPEX"]
    assert sezioni["OPEX"].totali()["totale"]["cassa"][FISSO] == Decimal("1200.00")
    assert sezioni["CAPEX"].totali()["totale"]["cassa"][FISSO] == Decimal("5000.00")
    assert _cassa(Filtri(anno=2026, natura="OPEX")) == Decimal("1200.00")
    assert _cassa(Filtri(anno=2026, natura="CAPEX")) == Decimal("5000.00")


def test_il_rinnovo_di_un_capex_puo_andare_in_opex_su_un_altro_conto(archivio):
    fab = archivio["capex"].fabbisogno
    conto_opex = _conto("61000002", "Canoni di prova")
    fab.natura_previsti = m.Natura.OPEX
    fab.conto_previsti = conto_opex
    fab.save()

    # 2027: il rinnovo previsto pesa sull'OPEX, sul conto deciso, ed è ordinario.
    assert _cassa(Filtri(anno=2027, natura="CAPEX"), "previsionale") == Decimal("0.00")
    opex = calcola_budget(Filtri(anno=2027, natura="OPEX"), OGGI)
    (previsto,) = [v for v in opex.voci if v.fabbisogno == fab]
    assert previsto.previsionale and previsto.natura == "OPEX"
    assert previsto.conto == conto_opex
    assert previsto.finanziamento == m.Contratto.Finanziamento.ORDINARIO
    assert previsto.importi["cassa"][FISSO] == Decimal("5000.00")
    # Il filtro per conto usa il conto deciso, non quello della voce d'origine.
    assert _cassa(Filtri(anno=2027, conto=conto_opex.pk), "previsionale") == Decimal("5000.00")
    # Il contratto reale resta CAPEX e finanziato.
    assert _cassa(Filtri(anno=2026, natura="CAPEX", finanziamento="finanziato")) == Decimal(
        "5000.00"
    )


def test_senza_decisione_il_previsto_eredita_natura_e_finanziamento(archivio):
    fab = archivio["capex"].fabbisogno
    base = adapters.contratto_base_previsti(fab)
    assert adapters.natura_previsti(fab, base) == "CAPEX"
    assert adapters.finanziamento_previsti(fab, base) == "finanziato"
    assert _cassa(Filtri(anno=2027, natura="CAPEX"), "previsionale") == Decimal("5000.00")


def test_fabbisogno_nuovo_senza_decisione_e_opex():
    nuovo = f.fabbisogno(
        "Servizio nuovo",
        decisione="rinnovare",
        previsto_data_avvio=D(2027, 1, 1),
        previsto_durata_mesi=12,
        stima_prossimo_importo=Decimal("800.00"),
    )
    assert adapters.natura_previsti(nuovo, None) == "OPEX"
    nuovo.natura_previsti = m.Natura.CAPEX
    nuovo.save()
    assert calcola_budget(Filtri(anno=2027, natura="CAPEX"), OGGI).totali()["previsionale"][
        "impegno"
    ][FISSO] == Decimal("800.00")


def test_piano_ordini_con_natura_e_totali_distinti(archivio):
    fab = archivio["capex"].fabbisogno
    fab.natura_previsti = m.Natura.OPEX
    fab.save()
    piano = calcola_piano(2027, OGGI)
    assert {r.fabbisogno.descrizione: r.natura for r in piano.righe} == {
        "Assistenza": "OPEX",
        "Piattaforma": "OPEX",
    }
    assert list(piano.totali_per_natura()) == ["OPEX"]
    fab.natura_previsti = ""
    fab.save()
    piano = calcola_piano(2027, OGGI)
    totali = piano.totali_per_natura()
    assert totali["OPEX"][FISSO] == Decimal("1200.00")
    assert totali["CAPEX"][FISSO] == Decimal("5000.00")
    assert [r.natura for r in calcola_piano(2027, OGGI, natura="CAPEX").righe] == ["CAPEX"]
