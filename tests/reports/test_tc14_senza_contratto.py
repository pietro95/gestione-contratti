"""TC-14 (F9.5.5): rinnovo senza contratto, anello della catena come un contratto."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from contratti import adapters, selettori
from contratti import models as m
from contratti.engine.tipi import Alert, Livello
from reports.budget import Filtri, calcola_budget
from reports.piano_ordini import calcola_piano

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
FISSO = Livello.FISSO
PASSWORD = "password-locale-di-prova"


@pytest.fixture
def c1():
    """Contratto 15/03/2024–14/03/2025, 300,00 anticipati (affidamento diretto, 2 mesi)."""
    it = f.cluster("IT")
    conto = m.ContoCoge.objects.create(
        codice="61000009", descrizione="Domini (prova)", valido_dal=D(2020, 1, 1), cluster=it
    )
    fab = f.fabbisogno("Dominio di prova", cluster=it, decisione="rinnovare")
    c = f.contratto(fabbisogno=fab, data_inizio=D(2024, 3, 15), durata_mesi=12)
    f.piano(f.voce(c, descrizione="Dominio", conto=conto, importo_fisso=Decimal("300.00")))
    return c


def _login(client, make_user, ruolo="EDITOR"):
    from accounts import roles

    make_user(f"u_{ruolo.lower()}", role=getattr(roles, ruolo))
    client.login(username=f"u_{ruolo.lower()}", password=PASSWORD)


def _rinnova(client, c1, **kw):
    voce = c1.voci.get()
    dati = {
        "fornitore": c1.fornitore_id,
        "procedura": c1.procedura_id,
        "data_inizio": "15/03/2025",
        "durata_mesi": "12",
        "voci-TOTAL_FORMS": "1",
        "voci-INITIAL_FORMS": "1",
        "voci-0-origine": str(voce.pk),
        "voci-0-riporta": "on",
        "voci-0-descrizione": "Dominio",
        "voci-0-importo_fisso": "25,00",
    }
    dati.update(kw)
    url = reverse("contratti:contratto_rinnovo_senza_contratto", args=[c1.pk])
    return client.post(url, {k: v for k, v in dati.items() if v is not None})


@pytest.fixture
def c2(c1, client, make_user):
    _login(client, make_user)
    assert _rinnova(client, c1).status_code == 302
    return m.Contratto.objects.get(predecessore=c1)


def test_form_precompilato_senza_dati_del_documento(c1, client, make_user):
    _login(client, make_user)
    html = client.get(reverse("contratti:contratto", args=[c1.pk])).content.decode()
    url = reverse("contratti:contratto_rinnovo_senza_contratto", args=[c1.pk])
    assert url in html and "Rinnova senza contratto" in html
    risposta = client.get(url)
    form = risposta.context["form"]
    assert form.initial["data_inizio"] == D(2025, 3, 15)  # il giorno dopo la fine
    assert form.initial["durata_mesi"] == 12
    assert "numero_contratto" not in form.fields and "tacito_rinnovo" not in form.fields
    assert "Scadenza</strong> = inizio + durata − 1 giorno" in risposta.content.decode()
    assert "data_inizio" in _rinnova(client, c1, data_inizio="").context["form"].errors


def test_catena_e_scadenza(c1, c2):
    assert c2.senza_contratto and c2.predecessore == c1 and c2.fabbisogno == c1.fabbisogno
    assert c2.numero_contratto is None
    assert adapters.data_fine_effettiva(c2) == D(2026, 3, 14)  # annuale: un anno esatto
    assert adapters.data_limite_avvio(c2) == D(2026, 1, 14)  # − lead time 2 mesi
    assert adapters.alert_contratto(c1, D(2026, 12, 1)) is None  # ha un successore
    # Pratica del predecessore: «Contratto attivo», come per ogni rinnovo.
    assert c1.stati_pratica.get().stato == m.StatoPratica.Stato.CONTRATTO_ATTIVO


@pytest.mark.parametrize(
    ("oggi", "atteso"),
    [
        (D(2025, 10, 13), Alert.VERDE),
        (D(2025, 10, 14), Alert.GIALLO),  # data limite − 3 mesi
        (D(2026, 1, 14), Alert.GIALLO),
        (D(2026, 1, 15), Alert.ARANCIONE),  # data limite superata, pratica non avviata
        (D(2026, 3, 14), Alert.ARANCIONE),
        (D(2026, 3, 15), Alert.ROSSO),  # scaduto senza rinnovo
    ],
)
def test_alert_come_un_contratto(c2, oggi, atteso):
    assert adapters.alert_contratto(c2, oggi) == atteso


def test_cruscotto(c2):
    gruppi = selettori.cruscotto(D(2026, 3, 15), {})
    assert [r.contratto for r in gruppi[Alert.ROSSO]] == [c2]


def test_budget_consolidato_e_previsionale(c1, c2):
    oggi = D(2025, 6, 1)

    def tot(anno, vista, parte):
        b = calcola_budget(Filtri(anno=anno, natura="OPEX"), oggi)
        return b.totali()[parte][vista][FISSO]

    assert tot(2024, "cassa", "consolidato") == Decimal("300.00")
    assert tot(2025, "cassa", "consolidato") == Decimal("25.00")
    assert tot(2025, "impegno", "consolidato") == Decimal("25.00")
    # 60,00 del contratto (73/365 di 300,00) + 20,00 del rinnovo (292/365 di 25,00).
    assert tot(2025, "competenza", "consolidato") == Decimal("80.00")
    assert tot(2026, "competenza", "consolidato") == Decimal("5.00")
    # Il rinnovo dopo il 14/03/2026 è previsto, come per un contratto.
    assert tot(2026, "cassa", "previsionale") > 0
    voci = calcola_budget(Filtri(anno=2025, natura="OPEX"), oggi).voci
    assert {(v.contratto, v.senza_contratto) for v in voci} == {(c1, False), (c2, True)}


def test_fuori_dal_piano_ordini(c1, c2):
    oggi = D(2025, 6, 1)
    # Né il periodo registrato (che ha competenza 2026) né i suoi previsti.
    assert calcola_piano(2026, oggi).righe == []
    # Controllo: lo stesso rinnovo registrato come contratto entra nel piano, con il suo previsto.
    m.Contratto.objects.filter(pk=c2.pk).update(senza_contratto=False)
    righe = calcola_piano(2026, oggi).righe
    assert [(r.fase, r.avvio) for r in righe] == [
        ("registrato", D(2025, 3, 15)),
        ("da_avviare", D(2026, 3, 15)),
    ]


def test_pagine_ed_etichette(c1, c2, client):
    html = client.get(reverse("contratti:contratto", args=[c2.pk])).content.decode()
    assert "senza contratto" in html
    assert reverse("contratti:contratto_rinnovo_senza_contratto", args=[c2.pk]) in html
    assert reverse("contratti:contratto_rinnovo_senza_contratto", args=[c1.pk]) not in (
        client.get(reverse("contratti:contratto", args=[c1.pk])).content.decode()
    )
    html = client.get(reverse("contratti:fabbisogno", args=[c1.fabbisogno_id])).content.decode()
    assert "senza_contratto=1" in html and "senza contratto" in html
    assert "senza contratto" in client.get(reverse("contratti:contratti")).content.decode()


def test_nuovo_senza_contratto(c1, client, make_user):
    _login(client, make_user)
    url = reverse("contratti:contratto_nuovo") + "?senza_contratto=1"
    risposta = client.get(url)
    assert risposta.context["form"].initial["senza_contratto"] is True
    assert "Nuovo senza contratto" in risposta.content.decode()
    assert "senza_contratto=1" in client.get(reverse("contratti:contratti")).content.decode()


def test_403_per_reader(c1, client, make_user):
    _login(client, make_user, "READER")
    url = reverse("contratti:contratto_rinnovo_senza_contratto", args=[c1.pk])
    assert client.get(url).status_code == 403
    assert client.post(url, {}).status_code == 403
    assert not m.Contratto.objects.filter(predecessore=c1).exists()
