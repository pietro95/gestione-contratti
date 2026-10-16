"""Scrittura dal connettore (SPEC_MCP §8, F10.1): permessi, anteprima, conferma, storia."""

import datetime
from decimal import Decimal

import pytest
from django.apps import apps
from django.utils import timezone

from accounts.roles import ADMIN, EDITOR, READER
from connettore import protocollo
from connettore.models import OperazioneMCP
from connettore.strumenti import STRUMENTI, Contesto
from connettore.strumenti.operazione import NOMI_VISTE
from contratti import models as m
from contratti.engine.tipi import Livello
from reports.budget import VISTE, Filtri, calcola_budget
from tests import factories as f

pytestmark = pytest.mark.django_db

OGGI = datetime.date(2026, 10, 5)
SCRITTURA = {s.nome for s in STRUMENTI.values() if s.scrittura}


def ctx(utente, scrittura=True):
    return Contesto(utente, OGGI, scrittura=scrittura, client_id="prova")


def chiama(c, nome, argomenti):
    messaggio = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": nome, "arguments": argomenti},
    }
    return protocollo.gestisci(messaggio, c)[0]["result"]


def ok(c, nome, argomenti):
    r = chiama(c, nome, argomenti)
    assert not r.get("isError"), r
    return r["structuredContent"]


def errore(c, nome, argomenti) -> str:
    r = chiama(c, nome, argomenti)
    assert r["isError"] is True, r
    return r["content"][0]["text"]


def conteggi() -> dict:
    """Righe di ogni tabella (storia compresa), escluse le operazioni del connettore."""
    return {
        modello._meta.label: modello.objects.count()
        for modello in apps.get_models()
        if modello is not OperazioneMCP
    }


@pytest.fixture
def editor(make_user):
    return make_user("redattore", role=EDITOR)


@pytest.fixture
def contratto_in_alert():
    """Contratto scaduto senza rinnovo: alert rosso al 05/10/2026."""
    f.sottocluster()
    c = f.contratto(data_inizio=datetime.date(2025, 6, 1), durata_mesi=12)
    v = f.voce(c, importo_fisso=Decimal("1200.00"))
    f.piano(v, modalita="anticipata", periodicita="trimestrale")
    return c


# --- Chi vede e chi usa i tool di scrittura -------------------------------------------------


def nomi(c):
    risposta, _ = protocollo.gestisci({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, c)
    return {t["name"] for t in risposta["result"]["tools"]}


def test_tool_di_scrittura_solo_con_ruolo_scope_e_interruttore(make_user, editor):
    lettore = make_user("lettore", role=READER)
    assert nomi(ctx(editor)) >= SCRITTURA
    assert not nomi(ctx(lettore)) & SCRITTURA  # Reader: mai, anche con lo scope
    assert not nomi(ctx(editor, scrittura=False)) & SCRITTURA  # senza scope
    m.Parametro.objects.filter(chiave="mcp_scrittura_attiva").update(valore=Decimal("0"))
    assert not nomi(ctx(editor)) & SCRITTURA  # interruttore spento
    assert "cerca" in nomi(ctx(editor))  # la lettura resta


@pytest.mark.parametrize("nome", sorted(SCRITTURA))
def test_reader_rifiutato_su_ogni_tool_di_scrittura(make_user, nome):
    """Regola 9: il Reader non scrive (qui: errore del tool, mai un'anteprima)."""
    lettore = make_user("lettore", role=READER)
    prima = conteggi()
    assert "riservato ad Admin ed Editor" in errore(ctx(lettore), nome, {})
    assert conteggi() == prima
    assert not OperazioneMCP.objects.exists()


def test_senza_scope_e_con_interruttore_spento(editor, contratto_in_alert):
    argomenti = {"contratto_id": contratto_in_alert.pk, "stato": "offerta_richiesta",
                 "data": "2026-10-05"}  # fmt: skip
    assert "permesso di scrittura" in errore(ctx(editor, False), "avanza_pratica", argomenti)
    m.Parametro.objects.filter(chiave="mcp_scrittura_attiva").update(valore=Decimal("0"))
    assert "spenta" in errore(ctx(editor), "avanza_pratica", argomenti)


def test_editor_fuori_dai_propri_cluster(editor, contratto_in_alert):
    m.AssegnazioneCluster.objects.create(username=editor.username, cluster=f.cluster("TLC"))
    testo = errore(
        ctx(editor),
        "avanza_pratica",
        {"contratto_id": contratto_in_alert.pk, "stato": "offerta_richiesta", "data": "2026-10-05"},
    )
    assert "cluster che non puoi modificare" in testo


# --- Anteprima ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("nome", "argomenti"),
    [
        ("avanza_pratica", lambda c: {"contratto_id": c.pk, "stato": "offerta_richiesta",
                                      "data": "2026-10-05"}),
        ("genera_scadenzario", lambda c: {"voce_id": c.voci.get().pk}),
        ("crea_fabbisogno", lambda c: {"descrizione": "Nuovo servizio", "cluster": "IT",
                                      "sottocluster": f.sottocluster().pk}),
        ("archivia", lambda c: {"tipo": "contratto", "id": c.pk}),
    ],
)  # fmt: skip
def test_l_anteprima_non_scrive_niente(editor, contratto_in_alert, nome, argomenti):
    prima = conteggi()
    dati = ok(ctx(editor), nome, argomenti(contratto_in_alert))
    assert conteggi() == prima  # stesse righe in ogni tabella, storia compresa
    assert dati["id_operazione"] and dati["modifiche"]
    assert "conferma_operazione" in dati["istruzioni"]
    assert OperazioneMCP.objects.get().stato == "in_attesa"


def test_anteprima_con_effetti_calcolati(editor, contratto_in_alert):
    c = contratto_in_alert
    dati = ok(
        ctx(editor),
        "avanza_pratica",
        {"contratto_id": c.pk, "stato": "offerta_richiesta", "data": "2026-10-05"},
    )
    (modifica,) = dati["modifiche"]
    assert modifica["tipo"] == "creato" and modifica["campi"]["stato"] == "offerta_richiesta"
    (fab,) = dati["effetti"]["fabbisogni"]
    (contratto,) = fab["contratti"]
    assert contratto["prima"]["pratica"] == "Non avviata"
    assert contratto["dopo"]["pratica"] == "Offerta richiesta"


def budget_probabile(cluster: str, anno: int) -> dict:
    """Budget del cluster al livello probabile, calcolato come la vista web."""
    b = calcola_budget(Filtri(anno=anno, area=(cluster,)), OGGI)
    return {
        (s.filtri.natura, vista): s.totali()["totale"][vista][Livello.PROBABILE]
        for s in b.sezioni()
        for vista in VISTE
    }


def test_nuovo_fabbisogno_vuoto_non_sposta_il_budget(editor, contratto_in_alert):
    """Il «prima» è il budget attuale del cluster, non zero: un fabbisogno senza contratti
    né previsti non cambia nulla (errore visto in produzione il 07/10/2026)."""
    cluster = contratto_in_alert.fabbisogno.cluster.codice
    assert any(budget_probabile(cluster, 2026).values())  # il cluster ha già un budget
    dati = ok(
        ctx(editor),
        "crea_fabbisogno",
        {"descrizione": "Nuovo servizio", "cluster": cluster, "sottocluster": f.sottocluster().pk},
    )
    assert dati["effetti"]["budget_livello_probabile"] == []
    (fab,) = dati["effetti"]["fabbisogni"]
    assert fab["nuovo"] is True


def test_budget_prima_e_dopo_sono_quelli_del_cluster(editor, contratto_in_alert):
    c = contratto_in_alert
    cluster = c.fabbisogno.cluster.codice
    attuale = budget_probabile(cluster, 2026)
    dati = ok(ctx(editor), "archivia", {"tipo": "contratto", "id": c.pk})
    righe = [r for r in dati["effetti"]["budget_livello_probabile"] if r["anno"] == 2026]
    assert righe
    for r in righe:
        assert r["cluster"] == cluster
        assert Decimal(r["prima"]) != 0
        chiave = next(k for k in attuale if k[0] == r["natura"] and NOMI_VISTE[k[1]] == r["vista"])
        assert Decimal(r["prima"]) == attuale[chiave]
        assert Decimal(r["dopo"]) == Decimal(r["prima"]) + Decimal(r["differenza"])


def test_fabbisogno_spostato_di_cluster(editor, contratto_in_alert):
    """Il budget esce da un cluster ed entra nell'altro: tutti e due con il loro «prima»."""
    fab = contratto_in_alert.fabbisogno
    f.cluster("TLC")
    origine = budget_probabile("IT", 2026)
    dati = ok(ctx(editor), "modifica_fabbisogno", {"id": fab.pk, "cluster": "TLC"})
    righe = [r for r in dati["effetti"]["budget_livello_probabile"] if r["anno"] == 2026]
    assert {r["cluster"] for r in righe} == {"IT", "TLC"}
    for r in righe:
        if r["cluster"] == "IT":
            chiave = next(
                k for k in origine if k[0] == r["natura"] and NOMI_VISTE[k[1]] == r["vista"]
            )
            assert Decimal(r["prima"]) == origine[chiave] != 0
            assert Decimal(r["dopo"]) == 0
        else:
            assert Decimal(r["prima"]) == 0 and Decimal(r["dopo"]) != 0


def test_anteprima_di_dati_non_validi(editor):
    testo = errore(
        ctx(editor),
        "crea_fabbisogno",
        {
            "descrizione": "X",
            "cluster": "IT",
            "sottocluster": f.sottocluster().pk,
            "previsto_data_avvio": "2027-01-01",
        },
    )
    assert "servono insieme avvio e durata" in testo
    assert not OperazioneMCP.objects.exists()


# --- Conferma ----------------------------------------------------------------------------------


def anteprima_pratica(editor, c):
    return ok(
        ctx(editor),
        "avanza_pratica",
        {"contratto_id": c.pk, "stato": "offerta_richiesta", "data": "2026-10-05"},
    )["id_operazione"]


def test_conferma_esegue_con_storia_e_utente(editor, contratto_in_alert):
    codice = anteprima_pratica(editor, contratto_in_alert)
    esito = ok(ctx(editor), "conferma_operazione", {"id_operazione": codice})
    assert esito["esito"] == "eseguita"
    passaggio = m.StatoPratica.objects.get(contratto=contratto_in_alert)
    assert passaggio.utente == editor
    storia = passaggio.history.get()
    assert storia.history_user == editor
    assert storia.history_change_reason.startswith(f"MCP avanza_pratica {codice[:8]}")
    op = OperazioneMCP.objects.get()
    assert op.stato == "confermata" and op.confermata_il is not None


def test_seconda_conferma_non_riesegue(editor, contratto_in_alert):
    codice = anteprima_pratica(editor, contratto_in_alert)
    ok(ctx(editor), "conferma_operazione", {"id_operazione": codice})
    prima = conteggi()
    di_nuovo = ok(ctx(editor), "conferma_operazione", {"id_operazione": codice})
    assert di_nuovo["gia_confermata"] is True
    assert conteggi() == prima


def test_conferma_di_un_altro_utente(make_user, editor, contratto_in_alert):
    codice = anteprima_pratica(editor, contratto_in_alert)
    altro = make_user("altro", role=ADMIN)
    assert "inesistente" in errore(ctx(altro), "conferma_operazione", {"id_operazione": codice})
    assert not m.StatoPratica.objects.exists()


def test_conferma_scaduta(editor, contratto_in_alert):
    codice = anteprima_pratica(editor, contratto_in_alert)
    OperazioneMCP.objects.update(scade_il=timezone.now() - datetime.timedelta(seconds=1))
    assert "scaduta" in errore(ctx(editor), "conferma_operazione", {"id_operazione": codice})
    assert OperazioneMCP.objects.get().stato == "rifiutata"
    assert not m.StatoPratica.objects.exists()


def test_conferma_dopo_una_modifica_dell_oggetto(editor, contratto_in_alert):
    codice = anteprima_pratica(editor, contratto_in_alert)
    contratto_in_alert.descrizione = "Cambiato da un altro utente"
    contratto_in_alert.save()
    testo = errore(ctx(editor), "conferma_operazione", {"id_operazione": codice})
    assert "modificati dopo l'anteprima" in testo
    assert not m.StatoPratica.objects.exists()


def test_conferma_con_argomenti_alterati(editor, contratto_in_alert):
    codice = anteprima_pratica(editor, contratto_in_alert)
    op = OperazioneMCP.objects.get()
    op.argomenti["stato"] = "contratto_attivo"
    op.save()
    assert "alterati" in errore(ctx(editor), "conferma_operazione", {"id_operazione": codice})


def test_conferma_con_interruttore_spento(editor, contratto_in_alert):
    codice = anteprima_pratica(editor, contratto_in_alert)
    m.Parametro.objects.filter(chiave="mcp_scrittura_attiva").update(valore=Decimal("0"))
    assert "spenta" in errore(ctx(editor), "conferma_operazione", {"id_operazione": codice})
    assert not m.StatoPratica.objects.exists()


def test_errore_alla_conferma_non_lascia_scritture(editor, contratto_in_alert):
    """Lo scadenzario diventa bloccato tra anteprima e conferma: niente di scritto."""
    voce = contratto_in_alert.voci.get()
    codice = ok(ctx(editor), "genera_scadenzario", {"voce_id": voce.pk})["id_operazione"]
    rata = f.rata(voce.piano_fatturazione, modificata_manualmente=True)
    prima = m.Rata.objects.count()
    testo = errore(ctx(editor), "conferma_operazione", {"id_operazione": codice})
    assert "modificate a mano" in testo
    assert m.Rata.objects.count() == prima and m.Rata.objects.filter(pk=rata.pk).exists()
