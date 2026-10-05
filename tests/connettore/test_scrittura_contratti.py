"""Scrittura del gruppo C (SPEC_MCP §8.2, §8.4): contratti, rinnovi, proroghe, voci.

Equivalenza con l'interfaccia per ogni tool; TC-12 e TC-14 ricostruiti via MCP.
"""

import datetime
from decimal import Decimal

import pytest

from connettore.models import OperazioneMCP
from contratti import adapters, servizi
from contratti import models as m
from contratti.engine import scadenze
from contratti.engine.tipi import Alert
from tests import factories as f
from tests.connettore.test_scrittura_equivalenza import equivalente, mcp, stato

pytestmark = pytest.mark.django_db
D = datetime.date


@pytest.fixture
def contratto():
    c = f.contratto(
        data_inizio=D(2025, 6, 1),
        durata_mesi=12,
        descrizione="Canone di prova",
        numero_contratto="4600000001",
    )
    v = f.voce(c, importo_fisso=Decimal("1200.00"))
    f.piano(v, modalita="anticipata", periodicita="trimestrale")
    return c


def _voce_web(prefisso_voce="voce", **kw):
    dati = {
        f"{prefisso_voce}-descrizione": "Canone annuo",
        f"{prefisso_voce}-natura": "OPEX",
        f"{prefisso_voce}-importo_fisso": "2.400,00",
        f"{prefisso_voce}-massimale_variabile": "0,00",
        "piano-modalita": "anticipata",
        "piano-periodicita": "semestrale",
        "piano-pagamento_fine_mese": "unknown",
        "quote-TOTAL_FORMS": "0",
        "quote-INITIAL_FORMS": "0",
        "quote-MIN_NUM_FORMS": "0",
        "quote-MAX_NUM_FORMS": "1000",
    }
    return dati | kw


VOCE_MCP = {
    "descrizione": "Canone annuo",
    "natura": "OPEX",
    "importo_fisso": "2400.00",
    "massimale_variabile": "0.00",
    "piano": {"modalita": "anticipata", "periodicita": "semestrale"},
}


# --- Equivalenza ---------------------------------------------------------------------------------


def test_crea_contratto(client, editor):
    fab = f.fabbisogno("Servizio da contrattualizzare")
    fornitore = f.fornitore("Fornitore Nuovo S.r.l.")

    def web(cl):
        r = cl.post(
            "/contratti/nuovo/",
            {
                "fabbisogno": fab.pk,
                "fornitore": fornitore.pk,
                "descrizione": "Servizio 2027",
                "numero_contratto": "4600000777",
                "procedura": m.Procedura.objects.get(codice="affidamento_diretto").pk,
                "data_inizio": "01/01/2027",
                "durata_mesi": "12",
            },
        )
        assert r.status_code == 302, r.context["form"].errors
        nuovo = m.Contratto.objects.get(numero_contratto="4600000777")
        return cl.post(f"/contratti/{nuovo.pk}/voci/nuova/?guidata=1", _voce_web())

    equivalente(
        client,
        editor,
        web,
        "crea_contratto",
        {
            "fabbisogno": fab.pk,
            "fornitore": fornitore.pk,
            "descrizione": "Servizio 2027",
            "numero_contratto": "4600000777",
            "data_inizio": "2027-01-01",
            "durata_mesi": 12,
            "voci": [VOCE_MCP],
        },
    )
    nuovo = m.Contratto.objects.get(numero_contratto="4600000777")
    assert nuovo.voci.get().piano_fatturazione.rate.count() == 2  # semestrale su 12 mesi


def test_modifica_contratto(client, editor, contratto):
    c = contratto
    equivalente(
        client,
        editor,
        lambda cl: cl.post(
            f"/contratti/{c.pk}/modifica/",
            {
                "fornitore": c.fornitore_id,
                "descrizione": "Canone di prova",
                "numero_contratto": "4600000001",
                "cig": "Z1234567AB",
                "procedura": c.procedura_id,
                "data_inizio": "01/06/2025",
                "durata_mesi": "24",
            },
        ),
        "modifica_contratto",
        {"id": c.pk, "cig": "Z1234567AB", "durata_mesi": 24},
    )


def test_registra_rinnovo(client, editor, contratto):
    c = contratto
    voce = c.voci.get()
    equivalente(
        client,
        editor,
        lambda cl: cl.post(
            f"/contratti/{c.pk}/rinnovo/",
            {
                "fornitore": c.fornitore_id,
                "descrizione": "Canone di prova",
                "procedura": c.procedura_id,
                "numero_contratto": "4600000002",
                "data_inizio": "01/06/2026",
                "durata_mesi": "12",
                "voci-TOTAL_FORMS": "1",
                "voci-INITIAL_FORMS": "1",
                "voci-0-origine": str(voce.pk),
                "voci-0-riporta": "on",
                "voci-0-descrizione": voce.descrizione,
                "voci-0-importo_fisso": "1.300,00",
                "voci-0-massimale_variabile": "0,00",
            },
        ),
        "registra_rinnovo",
        {
            "contratto_id": c.pk,
            "numero_contratto": "4600000002",
            "voci": [{"origine": voce.pk, "importo_fisso": "1300.00"}],
        },
    )


def test_registra_proroga(client, editor, contratto):
    c = contratto
    equivalente(
        client,
        editor,
        lambda cl: cl.post(
            f"/contratti/{c.pk}/proroga/",
            {
                "data_atto": "15/05/2026",
                "nuova_data_fine": "30/11/2026",
                "riferimento": "Atto aggiuntivo 1",
                "importo_fisso": "600,00",
                "modalita": "una_tantum",
            },
        ),
        "registra_proroga",
        {
            "contratto_id": c.pk,
            "data_atto": "2026-05-15",
            "nuova_data_fine": "2026-11-30",
            "riferimento": "Atto aggiuntivo 1",
            "importo_fisso": "600.00",
        },
    )


def test_crea_voce(client, editor, contratto):
    equivalente(
        client,
        editor,
        lambda cl: cl.post(f"/contratti/{contratto.pk}/voci/nuova/", _voce_web()),
        "crea_voce",
        {"contratto_id": contratto.pk, **VOCE_MCP},
    )


def test_modifica_voce(client, editor, contratto):
    voce = contratto.voci.get()
    equivalente(
        client,
        editor,
        lambda cl: cl.post(
            f"/contratti/{contratto.pk}/voci/{voce.pk}/",
            _voce_web(
                **{
                    "voce-descrizione": voce.descrizione,
                    "voce-importo_fisso": "1.500,00",
                    "piano-periodicita": "trimestrale",
                }
            ),
        ),
        "modifica_voce",
        {"id": voce.pk, "importo_fisso": "1500.00", "massimale_variabile": "0.00"},
    )


def test_voce_capex_senza_wbs_stesso_errore_del_form(editor, contratto):
    from tests.connettore.test_scrittura import chiama, ctx

    r = chiama(
        ctx(editor), "crea_voce", {"contratto_id": contratto.pk, **VOCE_MCP, "natura": "CAPEX"}
    )
    assert r["isError"] and "Una spesa CAPEX sta sempre su una WBS." in r["content"][0]["text"]
    assert not OperazioneMCP.objects.exists()


# --- Anteprima del rinnovo --------------------------------------------------------------------


def test_anteprima_del_rinnovo(editor, contratto):
    from tests.connettore.test_scrittura import ctx, ok

    prima = stato()
    dati = ok(ctx(editor), "registra_rinnovo", {"contratto_id": contratto.pk})
    assert stato() == prima  # niente di scritto
    (fab,) = dati["effetti"]["fabbisogni"]
    per_contratto = {c["contratto_id"]: c for c in fab["contratti"]}
    vecchio = per_contratto[contratto.pk]
    assert vecchio["prima"]["alert"] == "rosso" and vecchio["dopo"]["alert"] is None
    assert vecchio["dopo"]["pratica"] == "Contratto attivo"
    (nuovo,) = [c for k, c in per_contratto.items() if k != contratto.pk]
    assert nuovo["prima"] is None and nuovo["dopo"]["fine"] == "2027-05-31"
    assert {mod["oggetto"] for mod in dati["modifiche"]} >= {"contratto", "voce di contratto"}


# --- TC-12 e TC-14 via MCP ------------------------------------------------------------------------


def test_tc12_via_mcp(editor):
    oggi = D(2026, 11, 15)
    m.Procedura.objects.filter(codice="affidamento_diretto").update(lead_time_mesi=4)
    m.Parametro.objects.create(
        chiave="adeguamento_pct", valore=Decimal("3"), valido_dal=D(2025, 1, 1)
    )
    a = f.fabbisogno("SIM voce", decisione="rinnovare")
    b = f.fabbisogno("SIM M2M", decisione="rinnovare")
    v = f.contratto(fabbisogno=a, numero_contratto="V", data_inizio=D(2025, 1, 1), durata_mesi=24)
    f.piano(f.voce(v, importo_fisso=Decimal("4800.00")))
    mm = f.contratto(fabbisogno=b, numero_contratto="M", data_inizio=D(2025, 11, 1), durata_mesi=12)
    f.piano(f.voce(mm, importo_fisso=Decimal("1200.00")))
    servizi.accorpa_fabbisogni(b, a)  # solo dall'interfaccia (D11)
    esito = mcp(
        editor,
        "registra_rinnovo",
        {
            "contratto_id": v.pk,
            "descrizione": "SIM voce e M2M",
            "numero_contratto": "N",
            "data_inizio": "2027-01-01",
            "durata_mesi": 24,
            "voci": [
                {"origine": v.voci.get().pk, "descrizione": "Canone", "importo_fisso": "9600.00"}
            ],
            "sostituisce_ids": [mm.pk],
        },
    )
    n = m.Contratto.objects.get(numero_contratto="N")
    assert esito["oggetti"][0]["id"] == n.pk
    mcp(editor, "genera_scadenzario", {"voce_id": n.voci.get().pk})
    v.refresh_from_db()
    mm.refresh_from_db()
    assert n.predecessore == v and list(n.confluiti.all()) == [mm]
    assert adapters.alert_contratto(v, oggi) is None
    assert adapters.alert_contratto(mm, oggi) is None
    assert adapters.alert_contratto(n, oggi) == Alert.VERDE
    assert scadenze.data_riferimento_alert(adapters.scadenza(n)) == D(2028, 8, 31)
    previsti = adapters.previsti_fabbisogno(a, D(2029, 12, 31))
    assert [(p.inizio, p.fine, sum(x.importo_fisso for x in p.voci)) for p in previsti] == [
        (D(2029, 1, 1), D(2030, 12, 31), Decimal("9888.00"))
    ]
    rate = n.voci.get().piano_fatturazione.rate.order_by("numero")
    assert [(r.data_fattura, r.importo) for r in rate] == [
        (D(2027, 1, 1), Decimal("4800.00")),
        (D(2028, 1, 1), Decimal("4800.00")),
    ]


def test_tc14_via_mcp(editor):
    it = f.cluster("IT")
    fab = f.fabbisogno("Dominio di prova", cluster=it, decisione="rinnovare")
    c1 = f.contratto(fabbisogno=fab, data_inizio=D(2024, 3, 15), durata_mesi=12)
    f.piano(f.voce(c1, descrizione="Dominio", importo_fisso=Decimal("300.00")))
    mcp(
        editor,
        "registra_rinnovo",
        {
            "contratto_id": c1.pk,
            "senza_contratto": True,
            "voci": [{"origine": c1.voci.get().pk, "importo_fisso": "25.00"}],
        },
    )
    c2 = m.Contratto.objects.get(predecessore=c1)
    assert c2.senza_contratto and c2.numero_contratto is None
    assert c2.data_inizio == D(2025, 3, 15) and c2.durata_mesi == 12
    assert adapters.data_fine_effettiva(c2) == D(2026, 3, 14)
    assert adapters.data_limite_avvio(c2) == D(2026, 1, 14)
    assert c1.stati_pratica.get().stato == m.StatoPratica.Stato.CONTRATTO_ATTIVO
    for oggi, atteso in [
        (D(2025, 10, 13), Alert.VERDE),
        (D(2025, 10, 14), Alert.GIALLO),
        (D(2026, 1, 15), Alert.ARANCIONE),
        (D(2026, 3, 15), Alert.ROSSO),
    ]:
        assert adapters.alert_contratto(c2, oggi) == atteso, oggi
    assert c2.voci.get().importo_fisso == Decimal("25.00")
