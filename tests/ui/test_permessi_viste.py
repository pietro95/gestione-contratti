"""Ogni vista che modifica dati: 403 per il Reader, login per l'anonimo (CLAUDE.md regola 9)."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def viste_di_modifica(d):
    c, v, f = d["contratto"], d["voce"], d["fabbisogno"]
    return [
        ("get", reverse("contratti:contratto_nuovo")),
        ("post", reverse("contratti:contratto_nuovo")),
        ("get", reverse("contratti:contratto_modifica", args=[c.pk])),
        ("post", reverse("contratti:contratto_modifica", args=[c.pk])),
        ("get", reverse("contratti:contratto_rinnovo", args=[c.pk])),
        ("post", reverse("contratti:contratto_rinnovo", args=[c.pk])),
        ("get", reverse("contratti:proroga_nuova", args=[c.pk])),
        ("post", reverse("contratti:proroga_nuova", args=[c.pk])),
        ("get", reverse("contratti:voce_nuova", args=[c.pk])),
        ("post", reverse("contratti:voce_modifica", args=[c.pk, v.pk])),
        ("post", reverse("contratti:voce_anteprima", args=[c.pk])),
        ("post", reverse("contratti:scadenzario_genera", args=[v.pk])),
        ("get", reverse("contratti:rata_modifica", args=[d["rata"].pk])),
        ("post", reverse("contratti:rata_modifica", args=[d["rata"].pk])),
        ("post", reverse("contratti:pratica_avanza", args=["contratto", c.pk])),
        ("post", reverse("contratti:pratica_avanza", args=["fabbisogno", d["nuovo"].pk])),
        ("get", reverse("contratti:archivia", args=["contratto", c.pk])),
        ("post", reverse("contratti:archivia", args=["contratto", c.pk])),
        ("post", reverse("contratti:archivia", args=["voce", v.pk])),
        ("get", reverse("contratti:contratto_sposta", args=[c.pk])),
        ("post", reverse("contratti:contratto_sposta", args=[c.pk])),
        ("get", reverse("contratti:fabbisogno_accorpa", args=[f.pk])),
        ("post", reverse("contratti:fabbisogno_doppioni", args=[f.pk])),
        ("post", reverse("contratti:fabbisogno_accorpa", args=[f.pk])),
        ("get", reverse("contratti:importazioni")),
        ("post", reverse("contratti:importazione_carica", args=["date_emissione"])),
        ("post", reverse("contratti:importazione_carica", args=["contratti"])),
        ("get", reverse("contratti:importazione", args=[d["importazione"].pk])),
        ("post", reverse("contratti:importazione_conferma", args=[d["importazione"].pk])),
        ("post", reverse("contratti:importazione_annulla", args=[d["importazione"].pk])),
        ("get", reverse("contratti:fabbisogno_nuovo")),
        ("post", reverse("contratti:fabbisogno_modifica", args=[f.pk])),
        ("get", reverse("contratti:fornitore_nuovo")),
        ("post", reverse("contratti:fornitore_modifica", args=[d["fornitore"].pk])),
        (
            "post",
            reverse(
                "contratti:proposta_azione",
                args=["raggruppamento", d["raggruppamento"].pk, "conferma"],
            ),
        ),
        (
            "post",
            reverse(
                "contratti:proposta_azione", args=["predecessore", d["predecessore"].pk, "scarta"]
            ),
        ),
    ]


def test_reader_riceve_403_su_ogni_modifica(reader, dati):
    for metodo, url in viste_di_modifica(dati):
        risposta = getattr(reader, metodo)(url)
        assert risposta.status_code == 403, (metodo, url)
    # Nulla è cambiato.
    dati["contratto"].refresh_from_db()
    assert not dati["contratto"].archiviato
    dati["raggruppamento"].refresh_from_db()
    assert dati["raggruppamento"].stato == "proposta"


def test_anonimo_rimandato_al_login(client, dati):
    for metodo, url in viste_di_modifica(dati):
        risposta = getattr(client, metodo)(url)
        assert risposta.status_code == 302, (metodo, url)
        assert reverse("accounts:login") in risposta.url


def test_editor_accede_ai_form(editor, dati):
    for metodo, url in viste_di_modifica(dati):
        if metodo == "get":
            assert editor.get(url).status_code == 200, url
