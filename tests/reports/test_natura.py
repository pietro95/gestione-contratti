"""OPEX e CAPEX distinti (F8), natura e WBS per voce (F9.2).

Un contratto può avere quote OPEX e quote CAPEX; i rinnovi possono cambiare natura, conto e
WBS voce per voce; le spese su WBS a progetto stanno fuori dai budget dei cluster.
"""

import datetime
from decimal import Decimal

import pytest

from contratti import adapters, servizi
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


def _wbs(codice, tipo=m.WBS.Tipo.CLUSTER, cluster="IT"):
    return m.WBS.objects.create(
        codice_wbs=codice,
        descrizione=f"WBS {codice}",
        tipo=tipo,
        cluster=f.cluster(cluster) if tipo == m.WBS.Tipo.CLUSTER else None,
    )


@pytest.fixture
def archivio():
    """Un contratto misto (canone OPEX + quota CAPEX su WBS di cluster) e uno su WBS a progetto."""
    misto = f.contratto(
        fabbisogno=f.fabbisogno("Piattaforma", decisione="rinnovare"),
        data_inizio=D(2026, 1, 1),
        durata_mesi=12,
    )
    canone = f.voce(misto, descrizione="Canone", importo_fisso=Decimal("1200.00"))
    f.piano(canone)
    wbs = _wbs("WBS-IT-01")
    quota = f.voce(
        misto,
        descrizione="Licenze perpetue",
        importo_fisso=Decimal("5000.00"),
        natura=m.Natura.CAPEX,
        wbs=wbs,
        conto=_conto("11000001", "Immobilizzazioni di prova"),
    )
    f.piano(quota)
    progetto = f.contratto(
        fabbisogno=f.fabbisogno("Dissalatore di prova", decisione="rinnovare"),
        data_inizio=D(2026, 1, 1),
        durata_mesi=12,
    )
    su_progetto = f.voce(
        progetto,
        importo_fisso=Decimal("900.00"),
        natura=m.Natura.CAPEX,
        wbs=_wbs("WBS-PRJ-01", tipo=m.WBS.Tipo.PROGETTO),
    )
    f.piano(su_progetto)
    return {"misto": misto, "canone": canone, "quota": quota, "wbs": wbs, "progetto": progetto}


def _cassa(filtri, parte="totale"):
    return calcola_budget(filtri, OGGI).totali()[parte]["cassa"][FISSO]


def test_un_contratto_con_quota_opex_e_capex_va_nei_due_budget(archivio):
    c = m.Contratto.objects.prefetch_related("voci__wbs").get(pk=archivio["misto"].pk)
    assert c.natura == m.Contratto.MISTA
    assert c.finanziamento == m.Contratto.Finanziamento.ORDINARIO
    b = calcola_budget(Filtri(anno=2026), OGGI)
    sezioni = {s.filtri.natura: s for s in b.sezioni()}
    assert list(sezioni) == ["OPEX", "CAPEX"]
    assert sezioni["OPEX"].totali()["totale"]["cassa"][FISSO] == Decimal("1200.00")
    assert sezioni["CAPEX"].totali()["totale"]["cassa"][FISSO] == Decimal("5000.00")
    # Il CAPEX si legge per WBS (Controllo di gestione).
    (gruppo,) = sezioni["CAPEX"].gruppi("wbs")
    assert gruppo.chiave == "WBS-IT-01"


def test_le_wbs_a_progetto_restano_fuori_dai_budget_dei_cluster(archivio):
    assert _cassa(Filtri(anno=2026, natura="CAPEX")) == Decimal("5000.00")
    assert _cassa(Filtri(anno=2026, natura="CAPEX", progetti="includi")) == Decimal("5900.00")
    assert _cassa(Filtri(anno=2026, progetti="solo")) == Decimal("900.00")
    c = m.Contratto.objects.prefetch_related("voci__wbs").get(pk=archivio["progetto"].pk)
    assert c.finanziamento == m.Contratto.Finanziamento.FINANZIATO


def test_il_rinnovo_di_una_quota_capex_puo_andare_in_opex_su_un_altro_conto(archivio):
    quota = archivio["quota"]
    conto_opex = _conto("61000002", "Canoni di prova")
    quota.natura_rinnovi = m.Natura.OPEX
    quota.conto_rinnovi = conto_opex
    quota.save()

    # 2027: il rinnovo previsto della quota pesa sull'OPEX, sul conto deciso, senza WBS.
    assert _cassa(Filtri(anno=2027, natura="CAPEX"), "previsionale") == Decimal("0.00")
    opex = calcola_budget(Filtri(anno=2027, natura="OPEX"), OGGI)
    previsti = {v.descrizione: v for v in opex.voci if v.previsionale}
    assert set(previsti) == {"Canone", "Licenze perpetue"}
    rinnovo = previsti["Licenze perpetue"]
    assert (rinnovo.natura, rinnovo.conto, rinnovo.wbs) == ("OPEX", conto_opex, None)
    assert rinnovo.importi["cassa"][FISSO] == Decimal("5000.00")
    # Il filtro per conto usa il conto deciso per i rinnovi.
    assert _cassa(Filtri(anno=2027, conto=conto_opex.pk), "previsionale") == Decimal("5000.00")
    # Il contratto reale resta misto.
    assert _cassa(Filtri(anno=2026, natura="CAPEX")) == Decimal("5000.00")


def test_senza_decisione_il_rinnovo_conserva_natura_e_wbs(archivio):
    fab = archivio["misto"].fabbisogno
    classe = adapters.classificazione_prevista(fab, archivio["quota"])
    assert (classe.natura, classe.wbs) == ("CAPEX", archivio["wbs"])
    assert adapters.natura_previsti(fab, adapters.contratto_base_previsti(fab)) == "OPEX e CAPEX"
    assert _cassa(Filtri(anno=2027, natura="CAPEX"), "previsionale") == Decimal("5000.00")


def test_previsto_manuale_capex_sulla_sua_wbs():
    wbs = _wbs("WBS-IT-09")
    nuovo = f.fabbisogno(
        "Servizio nuovo",
        decisione="rinnovare",
        previsto_data_avvio=D(2027, 1, 1),
        previsto_durata_mesi=12,
        stima_prossimo_importo=Decimal("800.00"),
    )
    assert adapters.natura_previsti(nuovo, None) == "OPEX"
    nuovo.natura_previsti = m.Natura.CAPEX
    nuovo.wbs_previsti = wbs
    nuovo.save()
    b = calcola_budget(Filtri(anno=2027, natura="CAPEX"), OGGI)
    assert b.totali()["previsionale"]["impegno"][FISSO] == Decimal("800.00")
    assert [v.wbs for v in b.voci] == [wbs]


def test_piano_ordini_divide_le_quote_per_natura(archivio):
    piano = calcola_piano(2027, OGGI)
    (riga,) = [r for r in piano.da_avviare if r.fabbisogno == archivio["misto"].fabbisogno]
    assert riga.natura == "OPEX e CAPEX"
    assert riga.per_natura["OPEX"][FISSO] == Decimal("1200.00")
    assert riga.per_natura["CAPEX"][FISSO] == Decimal("5000.00")
    totali = piano.totali_per_natura()
    assert totali["OPEX"][FISSO] == Decimal("1200.00")
    assert totali["CAPEX"][FISSO] == Decimal("5900.00")  # il piano ordini contiene tutto
    (progetto,) = [r for r in piano.da_avviare if r.fabbisogno == archivio["progetto"].fabbisogno]
    assert progetto.a_progetto
    assert {r.fabbisogno.descrizione for r in calcola_piano(2027, OGGI, natura="OPEX").righe} == {
        "Piattaforma"
    }


def test_registrando_il_rinnovo_le_voci_prendono_la_classificazione_dei_rinnovi(archivio):
    quota = archivio["quota"]
    conto_opex = _conto("61000003", "Canoni")
    quota.natura_rinnovi = m.Natura.OPEX
    quota.conto_rinnovi = conto_opex
    quota.save()
    c = archivio["misto"]
    nuovo = servizi.registra_rinnovo(
        c,
        {
            "fornitore": c.fornitore,
            "procedura": c.procedura,
            "data_inizio": D(2027, 1, 1),
            "durata_mesi": 12,
        },
        [
            {"origine": v.pk, "descrizione": v.descrizione, "importo_fisso": v.importo_fisso}
            for v in (archivio["canone"], quota)
        ],
    )
    voci = {v.descrizione: v for v in nuovo.voci.all()}
    assert voci["Canone"].natura == "OPEX" and voci["Canone"].wbs is None
    assert (voci["Licenze perpetue"].natura, voci["Licenze perpetue"].conto) == (
        "OPEX",
        conto_opex,
    )
    assert voci["Licenze perpetue"].wbs is None
