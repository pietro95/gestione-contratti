"""TC-14 (F9.5): spesa ricorrente senza contratto (dominio DNS) nel registro."""

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


@pytest.fixture
def dns():
    it = f.cluster("IT")
    conto = m.ContoCoge.objects.create(
        codice="61000009", descrizione="Domini (prova)", valido_dal=D(2020, 1, 1), cluster=it
    )
    return f.fabbisogno(
        "Dominio DNS",
        cluster=it,
        decisione="rinnovare",
        senza_contratto=True,
        spesa_fornitore=f.fornitore("Registrar di prova"),
        spesa_importo=Decimal("25.00"),
        spesa_periodicita="annuale",
        spesa_dal=D(2025, 3, 15),
        natura_previsti="OPEX",
        conto_previsti=conto,
    )


OGGI = D(2026, 12, 1)


def _consolidato(anno, vista, oggi=OGGI, **kw):
    b = calcola_budget(Filtri(anno=anno, natura="OPEX", **kw), oggi)
    return b.totali()["consolidato"][vista][FISSO], b


def test_budget_2026(dns):
    for vista in ("cassa", "impegno", "competenza"):
        importo, b = _consolidato(2026, vista)
        assert importo == Decimal("25.00"), vista
    (g,) = b.gruppi("conto")
    assert g.chiave == "61000009"
    # Due voci: la spesa del 15/03/2025 ha ancora 5,00 di competenza nel 2026.
    assert [v.inizio for v in b.voci] == [D(2025, 3, 15), D(2026, 3, 15)]
    assert {v.fornitore.ragione_sociale for v in b.voci} == {"Registrar di prova"}
    assert b.totali()["previsionale"]["cassa"][FISSO] == Decimal("0.00")
    # Filtro per fornitore.
    assert _consolidato(2026, "cassa", fornitore=dns.spesa_fornitore.pk)[0] == Decimal("25.00")
    altro = f.fornitore("Altro fornitore")
    assert _consolidato(2026, "cassa", fornitore=altro.pk)[0] == Decimal("0.00")


def test_nessun_previsto_e_fuori_dal_piano_ordini(dns):
    assert adapters.previsti_fabbisogno(dns, D(2029, 12, 31)) == []
    assert [r.fabbisogno for r in calcola_piano(2027, D(2026, 12, 1)).righe] == []


def _cruscotto(oggi):
    gruppi = selettori.cruscotto(oggi, {})
    return {colore: [r.previsto_manuale for r in righe] for colore, righe in gruppi.items()}


def test_solo_promemoria_giallo(dns):
    assert _cruscotto(D(2026, 12, 1)) == {Alert.ROSSO: [], Alert.ARANCIONE: [], Alert.GIALLO: []}
    gialli = selettori.cruscotto(D(2026, 12, 20), {})[Alert.GIALLO]
    assert [(r.previsto_manuale, r.fine, r.spesa_ricorrente) for r in gialli] == [
        (dns, D(2027, 3, 15), True)
    ]
    # Mai rosso, anche dopo la data: la spesa successiva è nel 2028.
    assert _cruscotto(D(2027, 3, 16))[Alert.ROSSO] == []
    dns.decisione = "dismettere"
    dns.save()
    assert _cruscotto(D(2026, 12, 20))[Alert.GIALLO] == []


def test_spesa_terminata(dns):
    dns.spesa_al = D(2026, 12, 31)
    dns.save()
    assert _consolidato(2026, "cassa")[0] == Decimal("25.00")
    assert _consolidato(2027, "cassa", oggi=D(2027, 1, 1))[0] == Decimal("0.00")
    assert adapters.promemoria_spesa(dns, D(2027, 1, 1)) == (None, None)


def test_dismessa_si_ferma_restano_le_spese_passate(dns):
    dns.decisione = "dismettere"
    dns.save()
    # Al 01/12/2026 la spesa del 15/03/2026 è già sostenuta e resta; quelle future no.
    assert _consolidato(2026, "cassa")[0] == Decimal("25.00")
    assert _consolidato(2027, "cassa")[0] == Decimal("0.00")
    assert _consolidato(2026, "cassa", oggi=D(2026, 3, 1))[0] == Decimal("0.00")
    assert adapters.promemoria_spesa(dns, OGGI) == (None, None)


def _dati_form(dns, **kw):
    dati = {
        "descrizione": dns.descrizione,
        "cluster": dns.cluster_id,
        "categoria": dns.categoria_id,
        "decisione": "rinnovare",
        "senza_contratto": "on",
        "spesa_fornitore": dns.spesa_fornitore_id,
        "spesa_importo": "25,00",
        "spesa_periodicita": "annuale",
        "spesa_dal": "2025-03-15",
        "natura_previsti": "OPEX",
    }
    dati.update(kw)
    return {k: v for k, v in dati.items() if v is not None}


def test_form_e_pagina(dns, client, make_user):
    from accounts.roles import EDITOR

    make_user("u_editor", role=EDITOR)
    client.login(username="u_editor", password="password-locale-di-prova")
    url = reverse("contratti:fabbisogno_modifica", args=[dns.pk])
    risposta = client.post(url, _dati_form(dns, spesa_importo="", spesa_dal=""))
    assert risposta.status_code == 200
    assert "Obbligatorio per una spesa senza contratto" in risposta.content.decode()
    risposta = client.post(url, _dati_form(dns, previsto_data_avvio="2027-01-01",
                                           previsto_durata_mesi="12"))  # fmt: skip
    assert "non ha previsto manuale" in risposta.content.decode()
    f.contratto(fabbisogno=dns)
    risposta = client.post(url, _dati_form(dns))
    assert "ha contratti attivi" in risposta.content.decode()
    m.Contratto.objects.filter(fabbisogno=dns).update(archiviato=True)
    assert client.post(url, _dati_form(dns, spesa_importo="30,00")).status_code == 302
    dns.refresh_from_db()
    assert dns.spesa_importo == Decimal("30.00")
    html = client.get(reverse("contratti:fabbisogno", args=[dns.pk])).content.decode()
    assert "Spesa ricorrente senza contratto" in html and "Prossima spesa" in html
    html = client.get(reverse("contratti:fabbisogni") + "?area=tutti").content.decode()
    assert "spesa senza contratto" in html
