"""Rev22: periodo salvato sulla rata, stanziamenti proposti dalle rate scadute senza fattura."""

import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.test import Client
from django.urls import reverse

from accounts.roles import EDITOR, READER
from contratti import models as m
from contratti import stanziamenti
from contratti.acquisti import OperazioneNonAmmessa
from contratti.engine.tipi import Livello
from contratti.servizi import genera_scadenzario
from reports.budget import Filtri, calcola_budget

from . import factories as f
from .ui.conftest import PASSWORD

pytestmark = pytest.mark.django_db
D = datetime.date
OGGI = D(2026, 4, 20)  # tolleranza 15 giorni: da stanziare le rate fatturabili prima del 05/04


@pytest.fixture
def mensile():
    """Canone 12.000 €, dal 01/01/2026, fatturato a fine mese (rate da 1.000 €)."""
    c = f.contratto(data_inizio=D(2026, 1, 1), durata_mesi=12, numero_contratto="5800000050")
    v = f.voce(c, importo_fisso=Decimal("12000.00"))
    f.piano(v, modalita="posticipata", periodicita="mensile")
    genera_scadenzario(v)
    return {"contratto": c, "voce": v, "rate": list(m.Rata.objects.filter(piano__voce=v))}


def _numeri(proposte):
    return [p.rata.numero for p in proposte]


def test_il_periodo_si_salva_alla_generazione():
    c = f.contratto(data_inizio=D(2025, 12, 1), durata_mesi=12)
    v = f.voce(c, importo_fisso=Decimal("6000.00"))
    f.piano(v, modalita="posticipata", periodicita="bimestrale")
    genera_scadenzario(v)
    prima = m.Rata.objects.get(piano__voce=v, numero=1)
    # Contratto dall'01/12 con fatturazione bimestrale posticipata: dicembre e gennaio.
    assert (prima.periodo_dal, prima.periodo_al) == (D(2025, 12, 1), D(2026, 1, 31))
    assert prima.data_fattura == D(2026, 1, 31)

    def consuntivo(anno):
        b = calcola_budget(Filtri(anno=anno, previsionali=False), OGGI)
        return b.totali()["totale"]["consuntivo"][Livello.FISSO]

    # 1.000 € ripartiti a giorni (31 + 31): metà nel 2025, metà nel 2026.
    assert consuntivo(2025) == Decimal("500.00")
    assert consuntivo(2026) == Decimal("5500.00")


def test_rate_salvate_prima_senza_periodo_si_ricavano():
    c = f.contratto(data_inizio=D(2025, 12, 1), durata_mesi=12)
    v = f.voce(c, importo_fisso=Decimal("6000.00"))
    f.piano(v, modalita="posticipata", periodicita="bimestrale")
    genera_scadenzario(v)
    m.Rata.objects.filter(piano__voce=v).update(periodo_dal=None, periodo_al=None)
    b = calcola_budget(Filtri(anno=2025, previsionali=False), OGGI)
    assert b.totali()["totale"]["consuntivo"][Livello.FISSO] == Decimal("500.00")
    # Anche la proposta di stanziamento usa il periodo ricavato.
    prima = [p for p in stanziamenti.proposte(D(2026, 4, 20)) if p.rata.numero == 1][0]
    assert (prima.dal, prima.al) == (D(2025, 12, 1), D(2026, 1, 31))


def test_rate_scadute_senza_fattura_sono_proposte(mensile):
    # Il 20/04: gennaio, febbraio e marzo sono scadute da oltre 15 giorni; aprile no.
    assert _numeri(stanziamenti.proposte(OGGI)) == [1, 2, 3]
    assert _numeri(stanziamenti.proposte(D(2026, 4, 5))) == [1, 2]  # 31/03 + 15 gg = 15/04
    p = stanziamenti.proposte(OGGI)[2]
    assert (p.importo, p.dal, p.al, p.giorni_ritardo) == (
        Decimal("1000.00"), D(2026, 3, 1), D(2026, 3, 31), 20,
    )  # fmt: skip


def test_fattura_stanziamento_e_chiusura_escludono_la_proposta(mensile):
    r1, r2, r3 = mensile["rate"][:3]
    m.Fattura.objects.create(
        fornitore=mensile["contratto"].fornitore, contratto=mensile["contratto"],
        numero="F1", data=D(2026, 2, 3), importo_documento=Decimal("1000.00"), rata=r1,
    )  # fmt: skip
    assert _numeri(stanziamenti.proposte(OGGI)) == [2, 3]
    s = m.Stanziamento.objects.create(
        voce=mensile["voce"], rata=r2, importo=Decimal("900.00"),
        competenza_dal=D(2026, 2, 1), competenza_al=D(2026, 2, 28),
    )  # fmt: skip
    assert _numeri(stanziamenti.proposte(OGGI)) == [3]
    s.archiviato = True
    s.save()
    assert _numeri(stanziamenti.proposte(OGGI)) == [2, 3]
    mensile["contratto"].data_chiusura = D(2026, 4, 1)
    mensile["contratto"].save()
    assert stanziamenti.proposte(OGGI) == []


def test_il_filtro_per_cluster(mensile):
    assert _numeri(stanziamenti.proposte(OGGI, ("TLC",))) == []
    assert _numeri(stanziamenti.proposte(OGGI, ("IT",))) == [1, 2, 3]


def test_la_conferma_registra_lo_stanziamento_proposto(mensile, make_user):
    utente = make_user("redattore", role=EDITOR)
    r3 = mensile["rate"][2]
    s = stanziamenti.conferma(r3, utente, OGGI)
    assert (s.voce, s.rata, s.importo) == (mensile["voce"], r3, Decimal("1000.00"))
    assert (s.competenza_dal, s.competenza_al) == (D(2026, 3, 1), D(2026, 3, 31))
    assert s.data_stanziamento == OGGI and s.history.count() == 1
    assert _numeri(stanziamenti.proposte(OGGI)) == [1, 2]
    with pytest.raises(OperazioneNonAmmessa):
        stanziamenti.conferma(r3, utente, OGGI)  # già stanziata
    with pytest.raises(OperazioneNonAmmessa):
        stanziamenti.conferma(mensile["rate"][3], utente, OGGI)  # aprile: non scaduta


def test_conferma_solo_nel_proprio_cluster(mensile, make_user):
    m.AssegnazioneCluster.objects.create(username="altro", cluster=f.cluster("TLC"))
    utente = make_user("altro", role=EDITOR)
    with pytest.raises(PermissionDenied):
        stanziamenti.conferma(mensile["rate"][0], utente, OGGI)


def test_pagina_e_conferma_dall_interfaccia(mensile, make_user, admin_client):
    rate = mensile["rate"]
    url = reverse("reports:stanziamenti") + "?oggi=2026-04-20"
    pagina = admin_client.get(url).content.decode()
    assert "Stanzia le rate selezionate" in pagina and 'name="rata"' in pagina
    contratto = admin_client.get(
        reverse("contratti:contratto", args=[mensile["contratto"].pk]) + "?oggi=2026-04-20"
    ).content.decode()
    assert "sono proposte allo stanziamento" in contratto
    risposta = admin_client.post(
        reverse("contratti:stanziamenti_conferma") + "?oggi=2026-04-20",
        {"rata": [rate[0].pk, rate[1].pk], "next": "/report/stanziamenti/"},
    )
    assert risposta.status_code == 302 and risposta["Location"] == "/report/stanziamenti/"
    assert m.Stanziamento.objects.count() == 2


def test_reader_legge_ma_non_conferma(mensile, make_user):
    make_user("lettore", role=READER)
    reader = Client()
    reader.login(username="lettore", password=PASSWORD)
    pagina = reader.get(reverse("reports:stanziamenti")).content.decode()
    assert "Stanzia le rate selezionate" not in pagina
    risposta = reader.post(
        reverse("contratti:stanziamenti_conferma"), {"rata": [mensile["rate"][0].pk]}
    )
    assert risposta.status_code == 403
    assert not m.Stanziamento.objects.exists()
