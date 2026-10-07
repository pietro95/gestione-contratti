"""F11.4: viste del processo d'acquisto (SPEC §5.7, §5.8). I totali delle viste coincidono con
il motore; export XLSX e PDF con i filtri; i casi sono quelli di TC-15 e TC-16."""

import datetime
import io
from decimal import Decimal

import openpyxl
import pytest
from django.urls import reverse

from accounts.roles import EDITOR
from contratti import acquisti as servizi_acquisti
from contratti import fatture, servizi
from contratti import models as m
from contratti.engine import acquisti as motore
from reports import acquisti
from reports.acquisti import FiltriRDA

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
Fase = motore.Fase


def _rda(**kw):
    kw.setdefault("cluster", f.cluster("IT"))
    kw.setdefault("descrizione", "Richiesta di prova")
    kw.setdefault("origine", m.RichiestaAcquisto.Origine.MANUALE)
    posizioni = kw.pop("posizioni", [])
    rda = m.RichiestaAcquisto.objects.create(**kw)
    for i, (importo, wbs) in enumerate(posizioni, start=1):
        m.PosizioneRDA.objects.create(
            rda=rda,
            numero=i,
            descrizione_breve=f"P{i}",
            importo_unitario=importo,
            wbs=wbs,
            natura=m.Natura.CAPEX if wbs else m.Natura.OPEX,
        )
    return rda


@pytest.fixture
def rda_varie(make_user):
    """Quattro RDA in fasi diverse, due cluster (TC-15: R1 inserita il 15/06/2026)."""
    rossi = make_user("rossi", role=EDITOR)
    tlc = f.cluster("TLC")
    wbs = m.WBS.objects.create(codice_wbs="WBS-TEST-01", descrizione="WBS di prova")
    fornitore = f.fornitore("Fornitore Prova A S.r.l.")
    inserita = _rda(
        numero_rda="5100000001", data_inserimento=D(2026, 6, 15), data_creazione=D(2026, 6, 1),
        referente_utente=rossi, fornitore_proposto=fornitore,
        posizioni=[(Decimal("1000.00"), wbs), (Decimal("250.50"), None)],
    )  # fmt: skip
    inviata = _rda(
        data_creazione=D(2026, 7, 1), referente_utente=rossi, origine="portale",
        fabbisogno=f.fabbisogno("Fabbisogno inviato"), scopo="primo_acquisto",
        posizioni=[(Decimal("300.00"), None)],
    )  # fmt: skip
    servizi_acquisti.invia(inviata, rossi, D(2026, 7, 2))
    rilasciata = _rda(
        numero_rda="5100000002", data_inserimento=D(2025, 12, 1), data_rilascio=D(2026, 7, 10),
        data_creazione=D(2025, 11, 20), cluster=tlc, posizioni=[(Decimal("99.99"), None)],
    )  # fmt: skip
    bozza = _rda(
        data_creazione=D(2026, 7, 5), referente_utente=rossi, origine="portale",
        fabbisogno=f.fabbisogno("Fabbisogno in bozza"), scopo="primo_acquisto",
    )  # fmt: skip
    return {
        "rossi": rossi, "inserita": inserita, "inviata": inviata, "rilasciata": rilasciata,
        "bozza": bozza, "wbs": wbs, "fornitore": fornitore,
    }  # fmt: skip


def test_stato_rda_filtri_e_totali(rda_varie):
    oggi = D(2026, 7, 16)
    tutte = acquisti.stato_rda(FiltriRDA(), oggi)
    assert {r.rda.pk: r.fase for r in tutte} == {
        rda_varie["inserita"].pk: Fase.INSERITA,
        rda_varie["inviata"].pk: Fase.INVIATA,
        rda_varie["rilasciata"].pk: Fase.RILASCIATA,
        rda_varie["bozza"].pk: Fase.BOZZA,
    }
    # Importo = somma delle posizioni, come il motore.
    totale = sum(r.importo for r in tutte)
    assert totale == Decimal("1650.49")
    per_fase = {f: (n, importo) for f, _e, n, importo in acquisti.conteggi_per_fase(tutte)}
    assert per_fase[Fase.INSERITA] == (1, Decimal("1250.50"))
    assert sum(n for n, _i in per_fase.values()) == len(tutte)
    # TC-15 (e): R1 inserita il 15/06/2026 è ferma al 16/07/2026, non al 15/07/2026.
    inserita = next(r for r in tutte if r.fase == Fase.INSERITA)
    assert inserita.ferma
    assert not acquisti.stato_rda(FiltriRDA(fasi=("inserita",)), D(2026, 7, 15))[0].ferma

    def pk(filtri):
        return {r.rda.pk for r in acquisti.stato_rda(filtri, oggi)}

    assert pk(FiltriRDA(cluster=("TLC",))) == {rda_varie["rilasciata"].pk}
    assert pk(FiltriRDA(referente=rda_varie["rossi"].pk)) == {
        rda_varie[k].pk for k in ("inserita", "inviata", "bozza")
    }
    assert pk(FiltriRDA(fasi=("inviata", "bozza"))) == {
        rda_varie[k].pk for k in ("inviata", "bozza")
    }
    # Anno: dell'inserimento in SAP, o della creazione se non è inserita.
    assert pk(FiltriRDA(anno=2025)) == {rda_varie["rilasciata"].pk}
    assert pk(FiltriRDA(fornitore=rda_varie["fornitore"].pk)) == {rda_varie["inserita"].pk}
    assert pk(FiltriRDA(wbs="TEST-01")) == {rda_varie["inserita"].pk}
    assert pk(FiltriRDA(testo="5100000002")) == {rda_varie["rilasciata"].pk}


def test_rda_da_processare_e_mie_rda(rda_varie):
    oggi = D(2026, 7, 16)
    gruppi = {azione: righe for azione, _e, righe in acquisti.rda_da_processare((), oggi)}
    assert [r.rda for r in gruppi[motore.Azione.DA_INSERIRE]] == [rda_varie["inviata"]]
    assert [r.rda for r in gruppi[motore.Azione.SOLLECITO_RILASCIO]] == [rda_varie["inserita"]]
    assert [r.rda for r in gruppi[motore.Azione.SOLLECITO_PROCUREMENT]] == [rda_varie["rilasciata"]]
    mie = acquisti.mie_rda(rda_varie["rossi"], oggi)
    # Prima quelle che aspettano il referente (bozza).
    assert mie[0].rda == rda_varie["bozza"] and len(mie) == 3


def test_vista_stato_rda_ed_export(rda_varie, client):
    client.force_login(rda_varie["rossi"])
    url = reverse("reports:stato_rda") + "?area=tutti&oggi=2026-07-16"
    pagina = client.get(url).content.decode()
    assert "5100000001" in pagina and "1.650,49" in pagina
    risposta = client.get(url + "&formato=xlsx")
    wb = openpyxl.load_workbook(io.BytesIO(risposta.content))
    ws = wb["Stato delle RDA"]
    valori = [c.value for riga in ws.iter_rows() for c in riga]
    assert "Cluster: tutti" in valori and Decimal("1650.49") == Decimal(str(valori[-2]))
    risposta = client.get(url + "&fase=inserita&formato=pdf")
    assert risposta["Content-Type"] == "application/pdf"


@pytest.fixture
def f1():
    """TC-16: contratto una tantum F1 dal 02/03/2026, 1 mese; fisso 10.000, massimale 2.000."""
    fab = f.fabbisogno("Forniture di prova", decisione="rinnovare")
    c = f.contratto(
        fabbisogno=fab, una_tantum=True, data_inizio=D(2026, 3, 2), durata_mesi=1,
        numero_contratto="5800000016",
    )  # fmt: skip
    voce = f.voce(c, importo_fisso=Decimal("10000.00"), massimale_variabile=Decimal("2000.00"))
    f.piano(voce, modalita="una_tantum", periodicita="")
    servizi.genera_scadenzario(voce)
    return c


def _fattura(c, numero, data, valore):
    return m.Fattura.objects.create(
        contratto=c, numero=numero, data=data, importo_documento=valore, valore_base=valore
    )


def test_tc16_contratti_da_chiudere(f1):
    m.DocumentoEsecuzione.objects.create(contratto=f1, tipo="DDT", data=D(2026, 3, 10))
    _fattura(f1, "FA-1", D(2026, 3, 15), Decimal("4000.00"))
    _fattura(f1, "FA-2", D(2026, 4, 20), Decimal("5000.00"))

    def motivo(oggi):
        righe = acquisti.contratti_da_chiudere((), oggi)
        return [(r.contratto, r.motivo_label) for r in righe]

    assert motivo(D(2026, 3, 5)) == []  # non finito
    assert motivo(D(2026, 4, 25)) == [(f1, "Attestazione mancante")]
    m.DocumentoEsecuzione.objects.create(
        contratto=f1, tipo="RICEZIONE", data=D(2026, 4, 28), finale=True
    )
    assert motivo(D(2026, 4, 30)) == [(f1, "Fatture mancanti")]
    riga = acquisti.contratti_da_chiudere((), D(2026, 4, 30))[0]
    # Stessi numeri del motore (TC-16): fatturato 9.000, residuo sul fisso 1.000.
    assert (
        riga.riepilogo.esecuzione
        == servizi_acquisti.riepilogo_esecuzione(f1, D(2026, 4, 30)).esecuzione
    )
    assert riga.riepilogo.esecuzione.residuo_fisso == Decimal("1000.00")
    _fattura(f1, "FA-3", D(2026, 5, 5), Decimal("3500.00"))
    assert motivo(D(2026, 5, 6)) == [(f1, "Pronto da chiudere")]
    servizi_acquisti.chiudi(f1, None, D(2026, 5, 10))
    assert motivo(D(2026, 5, 11)) == []
    assert acquisti.contratti_da_chiudere(("TLC",), D(2026, 4, 30)) == []


def test_anomalie_esecuzione(f1):
    _fattura(f1, "FA-1", D(2026, 3, 15), Decimal("12500.00"))  # oltre fisso + massimale
    fa = m.Fattura.objects.create(
        contratto=f1, numero="FA-2", data=D(2026, 3, 20), importo_documento=Decimal("100.00")
    )  # senza valore base
    m.Fattura.objects.create(
        contratto=f1,
        numero="FA-3",
        data=D(2026, 3, 21),
        importo_documento=Decimal("100.00"),
        valore_base=Decimal("90.00"),
        bollo=Decimal("2.00"),
    )  # fmt: skip non quadra
    righe = acquisti.anomalie_esecuzione((), D(2026, 4, 1))
    assert len(righe) == 1
    assert righe[0].riepilogo.anomalie == ["FATTURATO_OLTRE_MASSIMO", "VALORE_BASE_MANCANTE"]
    per_fattura = {x.numero: codici for x, codici in righe[0].anomalie_fatture}
    assert per_fattura == {"FA-2": ["VALORE_BASE_MANCANTE"], "FA-3": ["IMPORTO_NON_QUADRA"]}
    # VALORE_BASE_MANCANTE si conta per fattura, non due volte.
    assert acquisti.conteggi_anomalie(righe) == {
        "FATTURATO_OLTRE_MASSIMO": 1, "IMPORTO_NON_QUADRA": 1, "VALORE_BASE_MANCANTE": 1,
    }  # fmt: skip
    fatture.aggiorna_importi(fa, Decimal("100.00"), None, None)
    assert acquisti.conteggi_anomalie(acquisti.anomalie_esecuzione((), D(2026, 4, 1))) == {
        "FATTURATO_OLTRE_MASSIMO": 1, "IMPORTO_NON_QUADRA": 1,
    }  # fmt: skip


def test_fatture_da_lavorare_e_mie(make_user):
    rossi = make_user("rossi", role=EDITOR)
    fornitore = f.fornitore("Studio Prova")
    c = f.contratto(fornitore=fornitore, fabbisogno=f.fabbisogno("S", referente_utente=rossi))
    f.voce(c)
    oggi = D(2026, 10, 7)
    libera = m.Fattura.objects.create(
        fornitore=fornitore, numero="1", data=oggi, importo_documento=1,
        data_registrazione=D(2026, 9, 1),
    )  # fmt: skip
    mia = m.Fattura.objects.create(
        fornitore=fornitore, numero="2", data=oggi, importo_documento=1, contratto=c,
        referente=rossi, data_presa_in_carico=oggi, data_registrazione=oggi,
    )  # fmt: skip
    gruppi = acquisti.fatture_da_lavorare(oggi)
    assert [r.fattura for r in gruppi[motore.PassoFattura.PRESA_IN_CARICO]] == [libera]
    assert gruppi[motore.PassoFattura.PRESA_IN_CARICO][0].ferma  # 36 giorni > 15
    assert [r.fattura for r in gruppi[motore.PassoFattura.CONVALIDA]] == [mia]
    assert [r.fattura for r in acquisti.mie_fatture(rossi, oggi)] == [mia]
    assert [r.fattura for r in acquisti.fatture_proposte_a(rossi, oggi)] == [libera]
    # Il totale dei gruppi è il numero delle fatture da lavorare.
    assert sum(len(g) for g in gruppi.values()) == 2


@pytest.fixture
def reader_client(client, make_user):
    from accounts.roles import READER

    client.force_login(make_user("lettore", role=READER))
    return client


def test_viste_per_tutti_i_ruoli(reader_client, f1):
    for nome in ("cruscotto_acquisti", "stato_rda", "contratti_da_chiudere",
                 "anomalie_esecuzione"):  # fmt: skip
        assert reader_client.get(reverse(f"reports:{nome}")).status_code == 200, nome
    for nome in ("stato_rda", "contratti_da_chiudere", "anomalie_esecuzione"):
        for formato, tipo in (("xlsx", "spreadsheetml"), ("pdf", "application/pdf")):
            risposta = reader_client.get(reverse(f"reports:{nome}") + f"?formato={formato}")
            assert tipo in risposta["Content-Type"], (nome, formato)


def test_home_con_i_miei_acquisti(rda_varie, client):
    client.force_login(rda_varie["rossi"])
    pagina = client.get(reverse("home") + "?oggi=2026-07-16").content.decode()
    assert 'id="miei-acquisti"' in pagina
