"""Fabbisogni via MCP (SPEC_MCP Rev10): campi nuovi, referente per nome, procedura per codice,
una tantum, competenza dichiarata."""

import datetime
from decimal import Decimal

import pytest

from accounts.roles import EDITOR
from connettore.models import OperazioneMCP
from contratti import adapters
from contratti import models as m
from tests import factories as f

from .test_scrittura import conteggi, ctx, errore, ok

pytestmark = pytest.mark.django_db
OGGI = datetime.date(2026, 10, 5)


def conferma(utente, nome, argomenti):
    anteprima = ok(ctx(utente), nome, argomenti)
    return anteprima, ok(
        ctx(utente), "conferma_operazione", {"id_operazione": anteprima["id_operazione"]}
    )


@pytest.fixture
def editor(make_user):
    return make_user("redattore", role=EDITOR)


@pytest.fixture
def base():
    return {"descrizione": "Fornitura switch", "cluster": "IT", "sottocluster": f.sottocluster().pk}


def test_crea_fabbisogno_con_i_campi_nuovi(editor, base):
    _, esito = conferma(
        editor,
        "crea_fabbisogno",
        base
        | {
            "motivazione": "Apparati a fine vita",
            "priorita": "obbligatoria",
            "tipo_acquisto": "fornitura",
            "fonte_stima": "listino",
            "note": "Vedi preventivo",
            "una_tantum": True,
        },
    )
    fab = m.Fabbisogno.objects.get(descrizione="Fornitura switch")
    assert (fab.motivazione, fab.priorita, fab.tipo_acquisto, fab.fonte_stima) == (
        "Apparati a fine vita",
        "obbligatoria",
        "fornitura",
        "listino",
    )
    assert fab.note == "Vedi preventivo" and fab.una_tantum
    dati = ok(ctx(editor), "fabbisogno", {"id": fab.pk})
    assert dati["priorita"] == "obbligatoria" and dati["una_tantum"] is True
    assert dati["testo_libero"] == {
        "motivazione": "Apparati a fine vita",
        "note": "Vedi preventivo",
    }


def test_valori_non_ammessi(editor, base):
    assert "valore non ammesso" in errore(ctx(editor), "crea_fabbisogno", base | {"priorita": "x"})
    assert "valore non ammesso" in errore(
        ctx(editor), "crea_fabbisogno", base | {"fonte_stima": "x"}
    )


def test_modifica_toglie_la_priorita_con_vuoto(editor, base):
    fab = f.fabbisogno(priorita="differibile", sottocluster=f.sottocluster())
    conferma(editor, "modifica_fabbisogno", {"id": fab.pk, "priorita": ""})
    fab.refresh_from_db()
    assert fab.priorita == ""


# --- Referente per nome ------------------------------------------------------------------------


def test_referente_per_nome(editor, base, make_user):
    rossi = make_user("mrossi", first_name="Mario", last_name="Rossi")
    make_user("lverdi", first_name="Luca", last_name="Verdi")
    conferma(editor, "crea_fabbisogno", base | {"referente_nome": "Mario Rossi"})
    fab = m.Fabbisogno.objects.get(descrizione="Fornitura switch")
    assert fab.referente_utente == rossi and fab.referente == "Rossi Mario"
    assert ok(ctx(editor), "fabbisogno", {"id": fab.pk})["referente"] == "Rossi Mario"
    conferma(editor, "modifica_fabbisogno", {"id": fab.pk, "referente_nome": "verdi"})
    fab.refresh_from_db()
    assert fab.referente_utente.username == "lverdi"


def test_referente_per_nome_ambiguo_o_sconosciuto(editor, base, make_user):
    make_user("mrossi", first_name="Mario", last_name="Rossi")
    make_user("grossi", first_name="Giulia", last_name="Rossi")
    testo = errore(ctx(editor), "crea_fabbisogno", base | {"referente_nome": "Rossi"})
    assert "Più utenti" in testo and "Rossi Mario" in testo and "Rossi Giulia" in testo
    assert "Nessun utente" in errore(
        ctx(editor), "crea_fabbisogno", base | {"referente_nome": "Bianchi"}
    )
    assert not OperazioneMCP.objects.exists()


def test_referente_per_nome_e_id_insieme(editor, base, make_user):
    utente = make_user("mrossi", first_name="Mario", last_name="Rossi")
    testo = errore(
        ctx(editor),
        "crea_fabbisogno",
        base | {"referente_nome": "Mario Rossi", "referente_utente": utente.pk},
    )
    assert "non entrambi" in testo


def test_utente_disattivato_non_e_proposto(editor, base, make_user):
    make_user("spento", first_name="Mario", last_name="Rossi", is_active=False)
    assert "Nessun utente" in errore(
        ctx(editor), "crea_fabbisogno", base | {"referente_nome": "Mario Rossi"}
    )


# --- Procedura per codice o id ---------------------------------------------------------------


def test_procedura_per_codice_e_per_id(editor, base):
    procedura = f.procedura("affidamento_diretto")
    riferimenti = ok(ctx(editor), "riferimenti", {})
    assert {"id": procedura.pk, "codice": "affidamento_diretto"}.items() <= next(
        p for p in riferimenti["procedure"] if p["codice"] == "affidamento_diretto"
    ).items()
    for valore in ("affidamento_diretto", procedura.pk):
        dati = base | {
            "descrizione": f"Previsto {valore}",
            "previsto_data_avvio": "2027-03-01",
            "previsto_durata_mesi": 12,
            "previsto_procedura": valore,
        }
        conferma(editor, "crea_fabbisogno", dati)
        assert (
            m.Fabbisogno.objects.get(descrizione=dati["descrizione"]).previsto_procedura
            == procedura
        )


def test_procedura_sconosciuta_o_non_proponibile(editor, base):
    dati = base | {"previsto_data_avvio": "2027-03-01", "previsto_durata_mesi": 12}
    assert "Procedura sconosciuta" in errore(
        ctx(editor), "crea_fabbisogno", dati | {"previsto_procedura": "boh"}
    )
    assert "previsto_procedura" in errore(
        ctx(editor), "crea_fabbisogno", dati | {"previsto_procedura": "rdo"}
    )


# --- Una tantum: effetti nell'anteprima ----------------------------------------------------


def test_anteprima_una_tantum_un_solo_previsto(editor, base):
    dati = base | {
        "previsto_data_avvio": "2027-03-01",
        "previsto_durata_mesi": 1,
        "previsto_procedura": "affidamento_diretto",
        "previsto_modalita": "posticipata",
        "previsto_periodicita": "intera_durata",
        "stima_prossimo_importo": "3000.00",
        "decisione": "dismettere",
    }
    una = ok(ctx(editor), "crea_fabbisogno", dati | {"una_tantum": True})
    (fab,) = una["effetti"]["fabbisogni"]
    assert len(fab["previsti"]["dopo"]) == 1
    ripetuto = ok(ctx(editor), "crea_fabbisogno", dati | {"decisione": "rinnovare"})
    assert len(ripetuto["effetti"]["fabbisogni"][0]["previsti"]["dopo"]) > 1


# --- Competenza dichiarata -------------------------------------------------------------------


@pytest.fixture
def fab_con_contratto():
    fab = f.fabbisogno("Vigilanza", decisione="rinnovare", sottocluster=f.sottocluster())
    c = f.contratto(fabbisogno=fab, data_inizio=datetime.date(2027, 1, 1), durata_mesi=12)
    v = f.voce(c, importo_fisso=Decimal("11393.00"))
    p = f.piano(v, modalita="anticipata", periodicita="annuale")
    f.rata(
        p,
        data_fattura=datetime.date(2027, 1, 1),
        data_pagamento_stimata=datetime.date(2027, 3, 31),
        importo=Decimal("11393.00"),
    )
    return fab


def test_dichiara_competenza_e_confronto(editor, fab_con_contratto):
    prima = conteggi()
    anteprima = ok(
        ctx(editor),
        "dichiara_competenza",
        {
            "fabbisogno_id": fab_con_contratto.pk,
            "anno": 2027,
            "natura": "OPEX",
            "importo": "10000.00",
        },
    )
    assert conteggi() == prima  # l'anteprima non scrive
    assert anteprima["modifiche"][0]["campi"]["importo"] == "10000.00"
    ok(ctx(editor), "conferma_operazione", {"id_operazione": anteprima["id_operazione"]})
    (riga,) = ok(ctx(editor), "fabbisogno", {"id": fab_con_contratto.pk})["competenza_dichiarata"]
    assert riga["dichiarato"] == "10000.00"
    assert riga["calcolato"]["probabile"] == "11393.00"
    assert riga["scostamento_sul_probabile"] == "-1393.00"


def test_dichiara_competenza_sostituisce_e_si_toglie_con_archivia(editor, fab_con_contratto):
    for importo in ("10000.00", "10500.00"):
        conferma(
            editor,
            "dichiara_competenza",
            {
                "fabbisogno_id": fab_con_contratto.pk,
                "anno": 2027,
                "natura": "OPEX",
                "importo": importo,
            },
        )
    (d,) = m.CompetenzaDichiarata.objects.all()
    assert d.importo == Decimal("10500.00")
    conferma(editor, "archivia", {"tipo": "competenza", "id": d.pk})
    assert (
        ok(ctx(editor), "fabbisogno", {"id": fab_con_contratto.pk})["competenza_dichiarata"] == []
    )


def test_dichiara_competenza_importo_non_valido(editor, fab_con_contratto):
    testo = errore(
        ctx(editor),
        "dichiara_competenza",
        {"fabbisogno_id": fab_con_contratto.pk, "anno": 2027, "natura": "OPEX", "importo": "-1"},
    )
    assert "importo" in testo and not OperazioneMCP.objects.exists()


def test_dichiara_competenza_fuori_dai_propri_cluster(editor, fab_con_contratto):
    m.AssegnazioneCluster.objects.create(username=editor.username, cluster=f.cluster("TLC"))
    testo = errore(
        ctx(editor),
        "dichiara_competenza",
        {"fabbisogno_id": fab_con_contratto.pk, "anno": 2027, "natura": "OPEX", "importo": "1"},
    )
    assert "cluster che non puoi modificare" in testo


def test_adapters_non_usa_la_competenza_dichiarata(fab_con_contratto):
    """La dichiarazione è un dato di confronto: non cambia previsti né budget."""
    prima = adapters.previsti_fabbisogno(fab_con_contratto, datetime.date(2029, 12, 31))
    m.CompetenzaDichiarata.objects.create(
        fabbisogno=fab_con_contratto, anno=2027, natura="OPEX", importo=Decimal("1.00")
    )
    assert adapters.previsti_fabbisogno(fab_con_contratto, datetime.date(2029, 12, 31)) == prima
