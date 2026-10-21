"""Rev25: il filtro per sottocluster in tutte le viste che filtrano per cluster."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.roles import ADMIN
from contratti import models as m

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
OGGI = "2026-10-21"


@pytest.fixture
def ambiente(come):
    ict = f.cluster("ICT")
    a, b = f.sottocluster("Alfa sotto", "ICT"), f.sottocluster("Beta sotto", "ICT")
    fab_a = f.fabbisogno("Fabbisogno di Alfa", cluster=ict, sottocluster=a)
    fab_b = f.fabbisogno("Fabbisogno di Beta", cluster=ict, sottocluster=b)
    # contratti finiti nel 2024, senza documenti: da chiudere
    con_a = f.contratto(
        fabbisogno=fab_a, data_inizio=D(2024, 1, 1), durata_mesi=12, numero_contratto="5800000001"
    )
    con_b = f.contratto(
        fabbisogno=fab_b, data_inizio=D(2024, 1, 1), durata_mesi=12, numero_contratto="5800000002"
    )
    voce_a = f.voce(con_a, descrizione="Voce di Alfa", importo_fisso=Decimal("1000.00"))
    voce_b = f.voce(con_b, descrizione="Voce di Beta", importo_fisso=Decimal("2000.00"))
    return {
        "ict": ict, "a": a, "b": b, "fab_a": fab_a, "fab_b": fab_b,
        "con_a": con_a, "con_b": con_b, "voce_a": voce_a, "voce_b": voce_b,
        "client": come(ADMIN),
    }  # fmt: skip


def _pagina(ambiente, nome, sotto=None, **extra):
    parametri = {"area": "tutti", "oggi": OGGI, **extra}
    if sotto is not None:
        parametri["sottocluster"] = sotto
    risposta = ambiente["client"].get(reverse(nome), parametri)
    assert risposta.status_code == 200, nome
    return risposta.content.decode()


def _solo_alfa(html, alfa="Alfa", beta="Beta"):
    assert alfa in html and beta not in html


@pytest.mark.parametrize(
    ("nome", "extra"),
    [
        ("contratti:contratti", {}),
        ("contratti:fabbisogni", {}),
        ("contratti:cruscotto", {}),
        ("contratti:piani_da_verificare", {}),
    ],
)
def test_elenchi_del_registro_filtrano(ambiente, nome, extra):
    tutti = _pagina(ambiente, nome, **extra)
    assert "Alfa" in tutti and "Beta" in tutti
    html = _pagina(ambiente, nome, ambiente["a"].pk, **extra)
    _solo_alfa(html, "Fabbisogno di Alfa", "Fabbisogno di Beta")
    # la tendina c'è e ricorda la scelta
    assert 'name="sottocluster"' in html and f'value="{ambiente["a"].pk}" selected' in html


def test_cruscotto_e_contratti_con_sottocluster_non_valido_non_si_rompono(ambiente):
    for nome in ("contratti:contratti", "contratti:fabbisogni", "contratti:cruscotto"):
        html = _pagina(ambiente, nome, "abc")
        assert "Fabbisogno di Alfa" in html and "Fabbisogno di Beta" in html


def test_elenco_rda_anche_per_quelle_senza_sottocluster(ambiente):
    ict = ambiente["ict"]
    m.RichiestaAcquisto.objects.create(
        cluster=ict, sottocluster=ambiente["a"], descrizione="RDA di Alfa",
        origine=m.RichiestaAcquisto.Origine.MANUALE,
    )  # fmt: skip
    vecchia = m.RichiestaAcquisto.objects.create(
        cluster=ict, descrizione="RDA vecchia di Beta", fabbisogno=ambiente["fab_b"],
        origine=m.RichiestaAcquisto.Origine.MANUALE,
    )  # fmt: skip
    m.RichiestaAcquisto.objects.filter(pk=vecchia.pk).update(
        sottocluster=None
    )  # non ancora migrata
    html = _pagina(ambiente, "contratti:rda_elenco", ambiente["a"].pk)
    assert "RDA di Alfa" in html and "RDA vecchia di Beta" not in html
    html = _pagina(ambiente, "contratti:rda_elenco", ambiente["b"].pk)
    assert "RDA vecchia di Beta" in html and "RDA di Alfa" not in html
    # il report «Stato delle RDA» e il cruscotto acquisti filtrano allo stesso modo
    html = _pagina(ambiente, "reports:stato_rda", ambiente["b"].pk)
    assert "RDA vecchia di Beta" in html and "RDA di Alfa" not in html
    assert "Sottocluster" in _pagina(ambiente, "reports:cruscotto_acquisti")


def test_contratti_da_chiudere_e_anomalie(ambiente):
    tutti = _pagina(ambiente, "reports:contratti_da_chiudere")
    assert "Fabbisogno di Alfa" in tutti and "Fabbisogno di Beta" in tutti
    html = _pagina(ambiente, "reports:contratti_da_chiudere", ambiente["a"].pk)
    _solo_alfa(html, "Fabbisogno di Alfa", "Fabbisogno di Beta")
    assert _pagina(ambiente, "reports:anomalie_esecuzione", ambiente["a"].pk)
    assert _pagina(ambiente, "reports:cruscotto_acquisti", ambiente["a"].pk)


def test_stanziamenti(ambiente):
    for voce in (ambiente["voce_a"], ambiente["voce_b"]):
        m.Stanziamento.objects.create(
            voce=voce, importo=Decimal("10.00"),
            competenza_dal=D(2026, 2, 1), competenza_al=D(2026, 2, 28),
        )  # fmt: skip
    html = _pagina(ambiente, "reports:stanziamenti", ambiente["a"].pk)
    assert "Fabbisogno di Alfa" in html and "Fabbisogno di Beta" not in html


def test_export_xlsx_porta_il_sottocluster_nell_intestazione(ambiente):
    risposta = ambiente["client"].get(
        reverse("reports:contratti_da_chiudere"),
        {"area": "tutti", "oggi": OGGI, "sottocluster": ambiente["a"].pk, "formato": "xlsx"},
    )
    assert risposta.status_code == 200
    import io

    import openpyxl

    ws = openpyxl.load_workbook(io.BytesIO(risposta.content)).active
    testo = " ".join(str(c.value) for riga in ws.iter_rows(max_row=6) for c in riga if c.value)
    assert "Alfa sotto" in testo


def test_wbs_e_extra_budget_per_voci_del_sottocluster(ambiente):
    wbs_a = m.WBS.objects.create(
        codice_wbs="W-ALFA",
        descrizione="WBS di Alfa",
        tipo=m.WBS.Tipo.CLUSTER,
        cluster=ambiente["ict"],
    )
    wbs_b = m.WBS.objects.create(
        codice_wbs="W-BETA",
        descrizione="WBS di Beta",
        tipo=m.WBS.Tipo.CLUSTER,
        cluster=ambiente["ict"],
    )
    m.WBS.objects.create(
        codice_wbs="W-VUOTA",
        descrizione="WBS senza voci",
        tipo=m.WBS.Tipo.CLUSTER,
        cluster=ambiente["ict"],
    )
    m.VoceContratto.objects.filter(pk=ambiente["voce_a"].pk).update(wbs=wbs_a, natura="capex")
    m.VoceContratto.objects.filter(pk=ambiente["voce_b"].pk).update(wbs=wbs_b, natura="capex")
    tutte = _pagina(ambiente, "reports:wbs")
    assert all(x in tutte for x in ("W-ALFA", "W-BETA", "W-VUOTA"))
    html = _pagina(ambiente, "reports:wbs", ambiente["a"].pk)
    assert "W-ALFA" in html and "W-BETA" not in html and "W-VUOTA" not in html
    # extra budget
    aut = m.AutorizzazioneExtraBudget.objects.create(
        codice="EB1", descrizione="Spot Alfa e Beta", cluster=ambiente["ict"], protocollo="P1",
        data_autorizzazione=D(2026, 1, 1), importo_autorizzato=Decimal("5000.00"),
    )  # fmt: skip
    vuota = m.AutorizzazioneExtraBudget.objects.create(
        codice="EB2", descrizione="Spot senza voci", cluster=ambiente["ict"], protocollo="P2",
        data_autorizzazione=D(2026, 1, 1), importo_autorizzato=Decimal("100.00"),
    )  # fmt: skip
    assert vuota.pk
    m.VoceContratto.objects.filter(pk=ambiente["voce_a"].pk).update(autorizzazione_extra_budget=aut)
    html = _pagina(ambiente, "reports:extra_budget", ambiente["a"].pk)
    assert "EB1" in html and "EB2" not in html
    assert "EB1" not in _pagina(ambiente, "reports:extra_budget", ambiente["b"].pk)
