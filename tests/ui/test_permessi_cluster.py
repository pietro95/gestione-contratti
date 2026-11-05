"""F9.2: l'Editor modifica solo i propri cluster; ognuno vede di default i propri."""

import datetime
import re

import pytest
from django.http import QueryDict
from django.test import Client
from django.urls import reverse

from accounts.roles import ADMIN, EDITOR, READER
from contratti import models as m
from contratti import permessi
from reports.forms import FiltriBudgetForm, FiltriPianoForm

from .. import factories as f
from .conftest import PASSWORD

pytestmark = pytest.mark.django_db
D = datetime.date


@pytest.fixture
def struttura():
    it, tlc, ot = f.cluster("IT"), f.cluster("TLC"), f.cluster("OT")
    fab_it = f.fabbisogno("Licenze IT", cluster=it)
    fab_tlc = f.fabbisogno("Telefonia", cluster=tlc)
    fab_ot = f.fabbisogno("Telecontrollo", cluster=ot)
    return {
        "cluster": {"IT": it, "TLC": tlc, "OT": ot},
        "fab": {"IT": fab_it, "TLC": fab_tlc, "OT": fab_ot},
        "contratto": {
            k: f.contratto(fabbisogno=v, numero_contratto=f"58000{i}")
            for i, (k, v) in enumerate({"IT": fab_it, "TLC": fab_tlc, "OT": fab_ot}.items())
        },
    }


@pytest.fixture
def utente(make_user):
    """Client autenticato: ruolo e cluster assegnati (codici, o «TUTTI»)."""

    def _crea(nome, ruolo, *cluster):
        u = make_user(nome, role=ruolo, is_superuser=ruolo == ADMIN, is_staff=ruolo == ADMIN)
        for codice in cluster:
            m.AssegnazioneCluster.objects.create(
                username=nome.upper(),  # il nome si normalizza in minuscolo
                cluster=None if codice == "TUTTI" else m.Cluster.objects.get(codice=codice),
            )
        c = Client()
        c.login(username=nome, password=PASSWORD)
        c.utente = u
        return c

    return _crea


def _modifica(client, contratto):
    return client.get(reverse("contratti:contratto_modifica", args=[contratto.pk]))


def test_editor_modifica_solo_i_propri_cluster(struttura, utente):
    c = struttura["contratto"]
    editor = utente("e.it", EDITOR, "IT", "TLC")
    assert _modifica(editor, c["IT"]).status_code == 200
    assert _modifica(editor, c["TLC"]).status_code == 200
    assert _modifica(editor, c["OT"]).status_code == 403
    risposta = editor.post(
        reverse("contratti:archivia", args=["contratto", c["OT"].pk]), {"ripristina": ""}
    )
    assert risposta.status_code == 403
    c["OT"].refresh_from_db()
    assert not c["OT"].archiviato
    # Nella pagina del contratto di un altro cluster: niente pulsanti di modifica.
    html = editor.get(reverse("contratti:contratto", args=[c["OT"].pk])).content.decode()
    assert "Registra rinnovo" not in html
    html = editor.get(reverse("contratti:contratto", args=[c["IT"].pk])).content.decode()
    assert "Registra rinnovo" in html


def test_tendine_solo_con_i_propri_cluster(struttura, utente):
    editor = utente("e.it", EDITOR, "IT")
    form = editor.get(reverse("contratti:contratto_nuovo")).context["form"]
    scelti = set(form.fields["fabbisogno"].queryset)
    assert struttura["fab"]["IT"] in scelti and {x.cluster.codice for x in scelti} == {"IT"}
    form = editor.get(reverse("contratti:fabbisogno_nuovo")).context["form"]
    assert {s.cluster.codice for s in form.fields["sottocluster"].queryset} == {"IT"}
    # Accorpare o spostare verso un altro cluster richiede il permesso anche lì.
    altro_it = f.fabbisogno("Altro IT", cluster=struttura["cluster"]["IT"])
    url = reverse("contratti:fabbisogno_accorpa", args=[struttura["fab"]["IT"].pk])
    form = editor.get(url).context["form"]
    destinazioni = set(form.fields["destinazione"].queryset)
    assert altro_it in destinazioni and {x.cluster.codice for x in destinazioni} == {"IT"}
    risposta = editor.post(url, {"destinazione": struttura["fab"]["OT"].pk, "passo": "anteprima"})
    assert risposta.status_code == 200 and risposta.context["form"].errors


def test_admin_tutti_e_transizione_senza_assegnazioni(struttura, utente, make_user):
    ot = struttura["contratto"]["OT"]
    # Nessuna assegnazione nel registro: gli Editor modificano tutto, come prima.
    libero = utente("e.libero", EDITOR)
    assert _modifica(libero, ot).status_code == 200
    utente("e.it", EDITOR, "IT")  # da qui le assegnazioni valgono
    assert _modifica(libero, ot).status_code == 403
    assert _modifica(utente("amministrativo", EDITOR, "TUTTI"), ot).status_code == 200
    assert _modifica(utente("capo", ADMIN), ot).status_code == 200
    assert _modifica(utente("lettore", READER, "OT"), ot).status_code == 403


def _sotto(struttura, codice) -> int:
    """Il sottocluster del fabbisogno del cluster (Rev35: «Non classificato» nei test)."""
    return struttura["fab"][codice].sottocluster_id


def test_di_default_si_vedono_i_propri_sottocluster(struttura, utente):
    editor = utente("e.it", EDITOR, "IT", "TLC")
    elenco = reverse("contratti:contratti")
    html = editor.get(elenco).content.decode()
    assert "580000" in html and "580001" in html and "580002" not in html
    assert "2 sottocluster su 3" in html  # la tendina mostra la selezione di default
    html = editor.get(elenco + "?sottocluster=tutti").content.decode()
    assert "580002" in html
    ot = _sotto(struttura, "OT")
    html = editor.get(elenco + f"?sottocluster={ot}").content.decode()  # gli altri a richiesta
    assert "580002" in html and "580000" not in html
    html = editor.get(reverse("contratti:fabbisogni")).content.decode()
    assert "Licenze IT" in html and "Telecontrollo" not in html
    # Chi non ha assegnazioni vede tutto.
    html = utente("lettore", READER).get(elenco).content.decode()
    assert "580002" in html and "3 sottocluster su 3" not in html and "Tutti i sottocluster" in html


def test_budget_e_piano_ordini_di_default_sui_propri_sottocluster(struttura, utente):
    editor = utente("e.it", EDITOR, "IT", "TLC")
    propri = tuple(sorted((_sotto(struttura, "IT"), _sotto(struttura, "TLC"))))
    form = FiltriBudgetForm({}, anno_default=2026, utente=editor.utente)
    assert form.is_valid() and form.filtri().sottocluster == propri
    form = FiltriBudgetForm({"sottocluster": "tutti"}, anno_default=2026, utente=editor.utente)
    assert form.is_valid() and form.filtri().sottocluster == ()
    form = FiltriPianoForm({}, anno_default=2027, utente=editor.utente)
    assert form.is_valid() and form.sottocluster_ids() == propri
    assert form.descrizione().startswith("Anno 2027; sottocluster IT (tutti), TLC (tutti);")
    risposta = editor.get(reverse("reports:piano_ordini"))
    assert risposta.status_code == 200
    assert {r.fabbisogno.cluster.codice for r in risposta.context["piano"].righe} <= {"IT", "TLC"}


def test_voce_con_conto_di_un_altro_cluster_bloccata(struttura, utente):
    conto_ot = f.conto(
        codice="60000001",
        descrizione="Conto di prova",
        valido_dal=D(2020, 1, 1),
        cluster=struttura["cluster"]["OT"],
    )
    editor = utente("e.it", EDITOR, "IT")
    c = struttura["contratto"]["IT"]
    risposta = editor.post(
        reverse("contratti:voce_nuova", args=[c.pk]),
        {
            "voce-descrizione": "Canone",
            "voce-natura": "OPEX",
            "voce-conto": conto_ot.pk,
            "voce-importo_fisso": "1.000,00",
            "voce-massimale_variabile": "0",
            "piano-modalita": "anticipata",
            "piano-periodicita": "annuale",
            "quote-TOTAL_FORMS": "0",
            "quote-INITIAL_FORMS": "0",
        },
    )
    assert risposta.status_code == 200
    assert "è del cluster OT" in risposta.content.decode()
    assert not c.voci.exists()


def test_nome_utente_normalizzato():
    a = m.AssegnazioneCluster.objects.create(username="  M.Rossi ", cluster=f.cluster("IT"))
    assert a.username == "m.rossi"
    assert str(a) == "m.rossi → IT"
    assert permessi.codici_filtro(type("U", (), {"username": "M.ROSSI"})(), []) == ["IT"]


def test_assegnazione_archiviata_non_vale(struttura, utente):
    editor = utente("e.it", EDITOR, "IT")
    utente("e.tlc", EDITOR, "TLC")
    m.AssegnazioneCluster.objects.filter(username="e.it").update(archiviato=True)
    editor = utente("e.altro", EDITOR)  # nuova sessione: senza assegnazioni attive
    assert _modifica(editor, struttura["contratto"]["IT"]).status_code == 403


def test_transizione_finita_anche_con_assegnazioni_tutte_archiviate(struttura, utente):
    """Dalla prima assegnazione valgono le regole per cluster, per sempre (SPEC §8.1)."""
    editor = utente("e.libero", EDITOR)
    assert _modifica(editor, struttura["contratto"]["OT"]).status_code == 200
    utente("e.it", EDITOR, "IT")
    m.AssegnazioneCluster.objects.update(archiviato=True)  # nessuna assegnazione attiva
    editor = utente("e.altro", EDITOR)
    assert _modifica(editor, struttura["contratto"]["OT"]).status_code == 403


def _voce(conto):
    return {
        "voce-descrizione": "Canone",
        "voce-natura": "OPEX",
        "voce-conto": conto.pk,
        "voce-importo_fisso": "1.000,00",
        "voce-massimale_variabile": "0",
        "piano-modalita": "anticipata",
        "piano-periodicita": "annuale",
        "quote-TOTAL_FORMS": "0",
        "quote-INITIAL_FORMS": "0",
    }


def test_conto_senza_cluster_bloccato_dopo_la_struttura(struttura, utente):
    editor = utente("e.it", EDITOR, "IT")
    c = struttura["contratto"]["IT"]
    url = reverse("contratti:voce_nuova", args=[c.pk])
    senza = m.ContoCoge.objects.create(
        codice="60000002", descrizione="Senza cluster", valido_dal=D(2020, 1, 1)
    )
    # Struttura non ancora caricata (nessun conto con cluster): ammesso.
    assert editor.post(url, _voce(senza)).status_code == 302
    f.conto(
        codice="60000003", descrizione="Con cluster", valido_dal=D(2020, 1, 1),
        cluster=struttura["cluster"]["IT"],
    )  # fmt: skip
    risposta = editor.post(url, _voce(senza))
    assert risposta.status_code == 200
    assert "non ha un cluster" in risposta.content.decode()
    assert c.voci.count() == 1


def test_piu_sottocluster_nel_filtro(struttura, utente):
    """Rev36: il filtro accetta più sottocluster (``?sottocluster=3&sottocluster=7``)."""
    editor = utente("e.it", EDITOR, "IT", "TLC")
    it, tlc, ot = (_sotto(struttura, c) for c in ("IT", "TLC", "OT"))
    assert permessi.selezione_sottocluster(editor.utente, []) == [it, tlc]
    assert sorted(permessi.selezione_sottocluster(editor.utente, [str(it), "tutti"])) == sorted(
        (it, tlc, ot)
    )
    assert permessi.selezione_sottocluster(editor.utente, [str(it), str(ot), str(it)]) == [it, ot]
    assert permessi.selezione_sottocluster(editor.utente, ["abc"]) == [it, tlc]  # non valido
    html = editor.get(
        reverse("contratti:contratti") + f"?sottocluster={it}&sottocluster={ot}"
    ).content.decode()
    assert "580000" in html and "580002" in html and "580001" not in html
    assert re.search(rf'value="{ot}"[^>]*checked', html)
    assert not re.search(rf'value="{tlc}"[^>]*checked', html)
    form = FiltriBudgetForm(
        QueryDict(f"sottocluster={it}&sottocluster={ot}"),
        anno_default=2026,
        utente=editor.utente,
    )
    assert form.is_valid() and form.filtri().sottocluster == tuple(sorted((it, ot)))
    assert permessi.descrivi_sottocluster_scelti([]) == "Sottocluster: tutti"
    assert permessi.descrivi_sottocluster_scelti([it, ot]) == "Sottocluster: IT (tutti), OT (tutti)"
