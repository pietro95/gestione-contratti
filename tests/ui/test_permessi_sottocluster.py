"""Rev25: un'assegnazione può essere limitata a un sottocluster."""

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

from accounts.roles import EDITOR
from contratti import forms, permessi
from contratti import models as m

from .. import factories as f
from .conftest import PASSWORD

pytestmark = pytest.mark.django_db


@pytest.fixture
def ambiente(make_user):
    ict = f.cluster("ICT")
    sc_it, sc_tlc = f.sottocluster("IT", "ICT"), f.sottocluster("Telecomunicazioni", "ICT")
    fab_it = f.fabbisogno("Licenze", cluster=ict, sottocluster=sc_it)
    fab_tlc = f.fabbisogno("Fonia", cluster=ict, sottocluster=sc_tlc)
    fab_senza = f.fabbisogno("Varie", cluster=ict)
    altro = f.fabbisogno("Altro", cluster=f.cluster("OT"))
    contratti = {
        k: f.contratto(fabbisogno=v, numero_contratto=f"5800{i}")
        for i, (k, v) in enumerate(
            {"it": fab_it, "tlc": fab_tlc, "senza": fab_senza, "altro": altro}.items()
        )
    }

    def client(nome, cluster, sottocluster=None):
        make_user(nome, role=EDITOR)
        m.AssegnazioneCluster.objects.create(
            username=nome, cluster=cluster, sottocluster=sottocluster
        )
        c = Client()
        c.login(username=nome, password=PASSWORD)
        return c

    return {
        "ict": ict, "it": sc_it, "tlc": sc_tlc, "contratti": contratti, "client": client,
        "fab": {"it": fab_it, "tlc": fab_tlc, "senza": fab_senza},
    }  # fmt: skip


def _modifica(client, contratto):
    return client.get(reverse("contratti:contratto_modifica", args=[contratto.pk])).status_code


def test_editor_di_sottocluster_modifica_solo_il_proprio(ambiente):
    c = ambiente["contratti"]
    editor = ambiente["client"]("e.it", ambiente["ict"], ambiente["it"])
    assert _modifica(editor, c["it"]) == 200
    assert _modifica(editor, c["tlc"]) == 403
    assert _modifica(editor, c["senza"]) == 403  # senza sottocluster: serve il cluster intero
    assert _modifica(editor, c["altro"]) == 403


def test_editor_di_cluster_intero_modifica_tutti_i_sottocluster(ambiente):
    c = ambiente["contratti"]
    editor = ambiente["client"]("e.ict", ambiente["ict"])
    assert [_modifica(editor, c[k]) for k in ("it", "tlc", "senza")] == [200, 200, 200]
    assert _modifica(editor, c["altro"]) == 403


def test_vede_il_cluster_ma_non_modifica_il_resto(ambiente):
    editor = ambiente["client"]("e.it", ambiente["ict"], ambiente["it"])
    html = editor.get(reverse("contratti:contratto", args=[ambiente["contratti"]["tlc"].pk]))
    assert html.status_code == 200 and not html.context["puo_modificare"]
    html = editor.get(reverse("contratti:contratto", args=[ambiente["contratti"]["it"].pk]))
    assert html.context["puo_modificare"]


def test_tendine_e_validazione_del_fabbisogno(ambiente, django_user_model):
    ambiente["client"]("e.it", ambiente["ict"], ambiente["it"])
    utente = django_user_model.objects.get(username="e.it")
    form = forms.FabbisognoForm(utente=utente)
    assert set(form.fields["sottocluster"].queryset) == {ambiente["it"]}
    dati = {
        "descrizione": "Nuovo",
        "decisione": "rinnovare",
        "cluster": ambiente["ict"].pk,
        "sottocluster": ambiente["tlc"].pk,
    }
    form = forms.FabbisognoForm(dati, utente=utente)
    assert not form.is_valid() and "sottocluster" in form.errors
    form = forms.FabbisognoForm({**dati, "sottocluster": ambiente["it"].pk}, utente=utente)
    assert form.is_valid(), form.errors


def test_fabbisogni_modificabili(ambiente, django_user_model):
    ambiente["client"]("e.it", ambiente["ict"], ambiente["it"])
    utente = django_user_model.objects.get(username="e.it")
    assert set(permessi.fabbisogni_modificabili(utente)) == {ambiente["fab"]["it"]}


def test_assegnazione_con_sottocluster_di_un_altro_cluster_non_valida(ambiente):
    a = m.AssegnazioneCluster(username="x", cluster=f.cluster("OT"), sottocluster=ambiente["it"])
    with pytest.raises(ValidationError):
        a.full_clean()


def test_assegnazione_unica_anche_con_sottocluster_vuoto(ambiente):
    from django.db import IntegrityError, transaction

    m.AssegnazioneCluster.objects.create(username="u", cluster=ambiente["ict"])
    with pytest.raises(IntegrityError), transaction.atomic():
        m.AssegnazioneCluster.objects.create(username="u", cluster=ambiente["ict"])
    m.AssegnazioneCluster.objects.create(
        username="u", cluster=ambiente["ict"], sottocluster=ambiente["it"]
    )
    m.AssegnazioneCluster.objects.create(username="t", cluster=None)
    with pytest.raises(IntegrityError), transaction.atomic():
        m.AssegnazioneCluster.objects.create(username="t", cluster=None)


def _rda(cluster, sottocluster=None, **kw):
    return m.RichiestaAcquisto.objects.create(
        cluster=cluster,
        sottocluster=sottocluster,
        descrizione="r",
        origine=m.RichiestaAcquisto.Origine.MANUALE,
        **kw,
    )


def test_rda_eredita_il_sottocluster_dalla_pratica(ambiente):
    rda = _rda(ambiente["ict"], fabbisogno=ambiente["fab"]["tlc"])
    assert rda.sottocluster == ambiente["tlc"]
    senza = _rda(ambiente["ict"], fabbisogno=ambiente["fab"]["senza"])
    assert senza.sottocluster is None
    esplicita = _rda(ambiente["ict"], ambiente["it"], fabbisogno=ambiente["fab"]["tlc"])
    assert esplicita.sottocluster == ambiente["it"]  # la scelta esplicita non si sovrascrive


def test_rda_sottocluster_di_un_altro_cluster_non_valida(ambiente):
    rda = m.RichiestaAcquisto(cluster=f.cluster("OT"), sottocluster=ambiente["it"], descrizione="r")
    with pytest.raises(ValidationError) as exc:
        rda.clean()
    assert "sottocluster" in exc.value.message_dict


def test_editor_di_sottocluster_modifica_solo_le_rda_del_proprio(ambiente):
    editor = ambiente["client"]("e.it", ambiente["ict"], ambiente["it"])
    mia = _rda(ambiente["ict"], ambiente["it"])
    altra = _rda(ambiente["ict"], ambiente["tlc"])
    cluster_intero = _rda(ambiente["ict"])  # senza sottocluster: serve il cluster intero
    for rda, atteso in ((mia, 200), (altra, 403), (cluster_intero, 403)):
        url = reverse("contratti:rda_modifica", args=[rda.pk])
        assert editor.get(url).status_code == atteso, rda
    dettaglio = editor.get(reverse("contratti:rda", args=[altra.pk]))
    assert dettaglio.status_code == 200 and not dettaglio.context["puo_modificare"]


def test_registra_rda_a_mano_rispetta_il_sottocluster(ambiente):
    editor = ambiente["client"]("e.it", ambiente["ict"], ambiente["it"])
    url = reverse("contratti:rda_registra")
    dati = {
        "cluster": ambiente["ict"].pk,
        "descrizione": "RDA a mano",
        "numero_rda": "1000000001",
        "sottocluster": ambiente["tlc"].pk,
    }
    assert editor.post(url, dati).status_code == 200  # il sottocluster non è tra le scelte
    assert not m.RichiestaAcquisto.objects.exists()
    risposta = editor.post(url, {**dati, "sottocluster": ambiente["it"].pk})
    assert risposta.status_code == 302
    assert m.RichiestaAcquisto.objects.get().sottocluster == ambiente["it"]
    # senza sottocluster: serve il cluster intero
    assert (
        editor.post(url, {**dati, "numero_rda": "1000000002", "sottocluster": ""}).status_code
        == 403
    )
