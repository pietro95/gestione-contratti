"""TC-13 (F9.4): quota OPEX e quota CAPEX nello stesso contratto."""

import datetime
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from accounts.roles import READER
from contratti import models as m
from contratti.engine.tipi import Livello
from reports.budget import Filtri, calcola_budget
from reports.piano_ordini import calcola_piano

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
OGGI = D(2026, 6, 1)
FISSO = Livello.FISSO


def _conto(codice, cluster):
    return m.ContoCoge.objects.create(
        codice=codice, descrizione=f"Conto {codice}", valido_dal=D(2020, 1, 1), cluster=cluster
    )


@pytest.fixture
def tc13():
    m.Parametro.objects.create(
        chiave="adeguamento_pct", valore=Decimal("3"), valido_dal=D(2026, 1, 1)
    )
    it = f.cluster("IT")
    conti = {
        k: _conto(c, it) for k, c in (("O", "61000001"), ("K", "11000001"), ("O2", "61000002"))
    }
    w = m.WBS.objects.create(
        codice_wbs="X.0001.00.000", descrizione="Investimenti IT", tipo="cluster", cluster=it
    )
    fab = f.fabbisogno("Piattaforma di virtualizzazione", cluster=it, decisione="rinnovare")
    c = f.contratto(fabbisogno=fab, data_inizio=D(2026, 1, 1), durata_mesi=12)
    v1 = f.voce(c, descrizione="Supporto annuale", conto=conti["O"],
                importo_fisso=Decimal("6000.00"))  # fmt: skip
    f.piano(v1)  # anticipata annuale
    v2 = f.voce(c, descrizione="Licenze perpetue", natura="CAPEX", wbs=w, conto=conti["K"],
                importo_fisso=Decimal("10000.00"))  # fmt: skip
    f.piano(v2, modalita=m.ModalitaFatturazione.UNA_TANTUM, periodicita="")
    return {"c": c, "v2": v2, "conti": conti, "w": w}


def _sezione(anno, natura):
    return calcola_budget(Filtri(anno=anno, natura=natura), OGGI)


def test_natura_del_contratto_si_ricava_dalle_voci(tc13):
    assert tc13["c"].natura == m.Contratto.MISTA == "OPEX e CAPEX"


def test_budget_2026_sezioni_distinte(tc13):
    opex, capex = _sezione(2026, "OPEX"), _sezione(2026, "CAPEX")
    for vista in ("cassa", "impegno", "competenza"):
        assert opex.totali()["consolidato"][vista][FISSO] == Decimal("6000.00"), vista
        assert capex.totali()["consolidato"][vista][FISSO] == Decimal("10000.00"), vista
    (g_opex,) = opex.gruppi("conto")
    assert g_opex.chiave == "61000001"
    (g_wbs,) = capex.gruppi("wbs")
    assert g_wbs.chiave == "X.0001.00.000"
    assert [s.chiave for s in g_wbs.sotto("conto")] == ["11000001"]
    # OPEX e CAPEX separati: due sezioni, nessun totale comune.
    sezioni = calcola_budget(Filtri(anno=2026), OGGI).sezioni()
    assert [s.filtri.natura for s in sezioni] == ["OPEX", "CAPEX"]


def _previsionale(natura):
    return _sezione(2027, natura).totali()["previsionale"]["cassa"][FISSO]


def test_previsto_misto_variante_a(tc13):
    assert _previsionale("OPEX") == Decimal("6180.00")
    assert _previsionale("CAPEX") == Decimal("10300.00")
    (riga,) = calcola_piano(2026, OGGI).da_avviare
    assert riga.natura == m.Contratto.MISTA
    assert riga.per_natura["OPEX"][FISSO] == Decimal("6180.00")
    assert riga.per_natura["CAPEX"][FISSO] == Decimal("10300.00")
    piano = calcola_piano(2026, OGGI)
    assert {n: t[FISSO] for n, t in piano.totali_per_natura().items()} == {
        "OPEX": Decimal("6180.00"),
        "CAPEX": Decimal("10300.00"),
    }
    solo_capex = calcola_piano(2026, OGGI, natura="CAPEX")
    assert len(solo_capex.da_avviare) == 1  # un unico ordine
    assert solo_capex.totali("CAPEX")[FISSO] == Decimal("10300.00")
    (voce_capex,) = [v for v in _sezione(2027, "CAPEX").voci if v.previsionale]
    assert voce_capex.wbs == tc13["w"] and voce_capex.conto == tc13["conti"]["K"]


def test_previsto_variante_b_licenze_rinnovate_in_opex(tc13):
    v2 = tc13["v2"]
    v2.natura_rinnovi = m.Natura.OPEX
    v2.conto_rinnovi = tc13["conti"]["O2"]
    v2.save()
    assert _previsionale("OPEX") == Decimal("16480.00")
    assert _previsionale("CAPEX") == Decimal("0.00")
    gruppi = {
        g.chiave: g.totali["previsionale"]["cassa"][FISSO]
        for g in _sezione(2027, "OPEX").gruppi("conto")
    }
    assert gruppi == {"61000001": Decimal("6180.00"), "61000002": Decimal("10300.00")}
    (riga,) = calcola_piano(2026, OGGI).da_avviare
    assert riga.natura == "OPEX" and riga.importi[FISSO] == Decimal("16480.00")
    # Il contratto reale non cambia.
    assert tc13["c"].natura == m.Contratto.MISTA
    assert _sezione(2026, "CAPEX").totali()["consolidato"]["cassa"][FISSO] == Decimal("10000.00")


def test_piano_ordini_filtrato_mostra_solo_i_totali_della_natura(tc13, make_user):
    make_user("u_reader", role=READER)
    client = Client()
    client.login(username="u_reader", password="password-locale-di-prova")
    risposta = client.get(reverse("reports:piano_ordini") + "?anno=2026&natura=CAPEX")
    assert list(risposta.context["per_natura"]) == ["CAPEX"]
    assert risposta.context["per_natura"]["CAPEX"][FISSO] == Decimal("10300.00")
