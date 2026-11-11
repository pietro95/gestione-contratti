# ruff: noqa: F401, F811  (le fixture si importano da test_rda e si usano per nome)
"""Rev46: allegati della richiesta di RDA (upload, download, archiviazione, limiti, permessi).
I file sono contenuti fittizi, scritti in una cartella temporanea (tests/conftest.py)."""

import datetime
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from accounts.roles import EDITOR
from contratti import allegati
from contratti import models as m

from .. import factories as f
from .conftest import PASSWORD
from .test_rda import _post_richiesta, rinnovo, sap, una_rda

pytestmark = pytest.mark.django_db
D = datetime.date

PDF = b"%PDF-1.4\n% allegato di prova\n"


def _pdf(nome="preventivo.pdf", contenuto=PDF):
    return SimpleUploadedFile(nome, contenuto, content_type="application/pdf")


def _carica(client, rda, *files):
    return client.post(
        reverse("contratti:rda_allegati_carica", args=[rda.pk]), {"file_allegati": list(files)}
    )


@pytest.fixture
def allegato(una_rda):
    """Un allegato già caricato (dal servizio, così il client dei test resta libero)."""
    rda, _ = una_rda
    (nuovo,) = allegati.aggiungi(rda, [_pdf()], rda.referente_utente)
    return rda, nuovo


# --- Permessi -------------------------------------------------------------------------------


def test_reader_scarica_ma_non_modifica(reader, allegato):
    rda, a = allegato
    assert _carica(reader, rda, _pdf("altro.pdf")).status_code == 403
    assert (
        reader.post(reverse("contratti:rda_allegato_archivia", args=[rda.pk, a.pk])).status_code
        == 403
    )
    assert reader.get(reverse("contratti:rda_allegato", args=[rda.pk, a.pk])).status_code == 200
    assert not m.AllegatoRDA.objects.get(pk=a.pk).archiviato
    pagina = reader.get(reverse("contratti:rda", args=[rda.pk])).content.decode()
    assert "preventivo.pdf" in pagina and "Aggiungi allegati" not in pagina


def test_editor_di_un_altro_cluster_riceve_403(allegato, make_user):
    rda, _ = allegato
    make_user("editor_tlc", role=EDITOR)
    m.AssegnazioneCluster.objects.create(username="editor_tlc", cluster=f.cluster("TLC"))
    client = Client()
    client.login(username="editor_tlc", password=PASSWORD)
    a = rda.file_allegati.get()
    assert _carica(client, rda, _pdf("altro.pdf")).status_code == 403
    assert (
        client.post(reverse("contratti:rda_allegato_archivia", args=[rda.pk, a.pk])).status_code
        == 403
    )
    assert rda.file_allegati.count() == 1


def test_anonimo_non_scarica(allegato):
    rda, a = allegato
    risposta = Client().get(reverse("contratti:rda_allegato", args=[rda.pk, a.pk]))
    assert risposta.status_code == 302 and "login" in risposta.url


# --- Caricamento e download -----------------------------------------------------------------


def test_carica_e_scarica(allegato, editor, settings):
    rda, a = allegato
    assert (a.nome, a.dimensione, a.caricato_da.username) == (
        "preventivo.pdf", len(PDF), "autore_rda",
    )  # fmt: skip
    # Sul disco con nome casuale, nella cartella della RDA e sotto la radice degli allegati.
    percorso = Path(a.file.path)
    assert percorso.is_file() and percorso.parent == Path(settings.MEDIA_ROOT) / "rda" / str(rda.pk)
    assert "preventivo" not in percorso.name
    risposta = editor.get(reverse("contratti:rda_allegato", args=[rda.pk, a.pk]))
    assert b"".join(risposta.streaming_content) == PDF
    assert 'attachment; filename="preventivo.pdf"' in risposta["Content-Disposition"]
    assert risposta["X-Content-Type-Options"] == "nosniff"
    assert "no-store" in risposta["Cache-Control"]
    pagina = editor.get(reverse("contratti:rda", args=[rda.pk])).content.decode()
    assert "preventivo.pdf" in pagina and "Aggiungi allegati" in pagina


def test_nome_originale_senza_percorso(una_rda, editor):
    rda, _ = una_rda
    _carica(editor, rda, _pdf("../../etc/passwd\\..\\contratto.pdf"))
    a = rda.file_allegati.get()
    assert a.nome == "contratto.pdf" and ".." not in a.file.name


def test_allegato_con_rda_sbagliata_da_404(allegato, editor):
    rda, a = allegato
    assert (
        editor.get(reverse("contratti:rda_allegato", args=[rda.pk + 999, a.pk])).status_code == 404
    )


def test_file_mancante_sul_disco_da_404(allegato, editor):
    rda, a = allegato
    Path(a.file.path).unlink()
    assert editor.get(reverse("contratti:rda_allegato", args=[rda.pk, a.pk])).status_code == 404


def test_archivia_non_cancella(allegato, editor):
    rda, a = allegato
    risposta = editor.post(reverse("contratti:rda_allegato_archivia", args=[rda.pk, a.pk]))
    assert risposta.status_code == 302 and risposta.url.endswith("#allegati")
    a.refresh_from_db()
    assert a.archiviato and Path(a.file.path).is_file()
    assert editor.get(reverse("contratti:rda_allegato", args=[rda.pk, a.pk])).status_code == 404
    assert a.history.count() == 2
    pagina = editor.get(reverse("contratti:rda", args=[rda.pk])).content.decode()
    assert reverse("contratti:rda_allegato", args=[rda.pk, a.pk]) not in pagina


def test_con_rda_annullata_non_si_tocca(allegato, editor):
    rda, a = allegato
    editor.post(reverse("contratti:rda_annulla", args=[rda.pk]), {"nota": "non serve più"})
    assert _carica(editor, rda, _pdf("tardivo.pdf")).status_code == 302
    assert rda.file_allegati.count() == 1
    editor.post(reverse("contratti:rda_allegato_archivia", args=[rda.pk, a.pk]))
    a.refresh_from_db()
    assert not a.archiviato


# --- Limiti ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "nome, contenuto",
    [
        ("script.exe", b"MZ\x90\x00"),
        ("pagina.html", b"<script>alert(1)</script>"),
        ("finto.pdf", b"questo non e un pdf"),
        ("vuoto.pdf", b""),
        ("senza_estensione", PDF),
    ],
)
def test_file_non_ammessi(una_rda, editor, nome, contenuto):
    rda, _ = una_rda
    _carica(editor, rda, SimpleUploadedFile(nome, contenuto))
    assert rda.file_allegati.count() == 0


def test_dimensione_massima_da_parametro(una_rda, editor):
    rda, _ = una_rda
    m.Parametro.objects.filter(chiave="allegato_max_mb").update(valore=1)
    _carica(editor, rda, _pdf("grande.pdf", PDF + b"0" * 1024 * 1024))
    assert rda.file_allegati.count() == 0
    _carica(editor, rda, _pdf("piccolo.pdf"))
    assert rda.file_allegati.count() == 1


def test_numero_massimo_da_parametro(una_rda, editor):
    rda, _ = una_rda
    m.Parametro.objects.filter(chiave="allegati_max_per_rda").update(valore=2)
    _carica(editor, rda, _pdf("a.pdf"), _pdf("b.pdf"))
    assert rda.file_allegati.count() == 2
    _carica(editor, rda, _pdf("c.pdf"))
    assert rda.file_allegati.count() == 2
    # Archiviato libera un posto.
    editor.post(
        reverse("contratti:rda_allegato_archivia", args=[rda.pk, rda.file_allegati.first().pk])
    )
    _carica(editor, rda, _pdf("c.pdf"))
    assert rda.file_allegati.filter(archiviato=False).count() == 2


def test_un_file_non_valido_blocca_tutto_il_lotto(una_rda, editor):
    rda, _ = una_rda
    _carica(editor, rda, _pdf("buono.pdf"), SimpleUploadedFile("cattivo.exe", b"MZ"))
    assert rda.file_allegati.count() == 0


# --- Dal form della richiesta ----------------------------------------------------------------


def test_allegati_dal_form_di_nuova_richiesta(editor, rinnovo):
    fab, c1 = rinnovo
    url = reverse("contratti:rda_nuova", args=[fab.pk])
    risposta = _post_richiesta(
        editor,
        url,
        [{"descrizione_breve": "Licenze CAD", "importo_unitario": "1.000,00",
          "gruppo_merci": m.GruppoMerci.objects.get(codice="GM-TEST01").pk,
          "conto": m.ContoCoge.objects.get(codice="600001").pk, "centro_costo": "C0001"}],
        contratto=str(c1.pk),
        file_allegati=[_pdf("offerta.pdf"), _pdf("capitolato.pdf")],
    )  # fmt: skip
    assert risposta.status_code == 302
    rda = m.RichiestaAcquisto.objects.get()
    assert sorted(rda.file_allegati.values_list("nome", flat=True)) == [
        "capitolato.pdf", "offerta.pdf",
    ]  # fmt: skip


def test_file_non_valido_dal_form_non_crea_la_richiesta(editor, rinnovo):
    fab, c1 = rinnovo
    risposta = _post_richiesta(
        editor,
        reverse("contratti:rda_nuova", args=[fab.pk]),
        [{"descrizione_breve": "Licenze CAD", "importo_unitario": "1.000,00",
          "gruppo_merci": m.GruppoMerci.objects.get(codice="GM-TEST01").pk,
          "conto": m.ContoCoge.objects.get(codice="600001").pk, "centro_costo": "C0001"}],
        contratto=str(c1.pk),
        file_allegati=[SimpleUploadedFile("virus.exe", b"MZ")],
    )  # fmt: skip
    assert risposta.status_code == 200
    assert "tipo di file non ammesso" in risposta.content.decode()
    assert not m.RichiestaAcquisto.objects.exists()
