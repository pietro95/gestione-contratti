"""Import incrementale: un contratto già registrato si riconosce e la riga si scarta.

Bug segnalato da Pietro (02/10/2026): reimportando un Excel aggiornato comparivano duplicati.
La chiave d'import dipende da foglio e, per le righe senza codici, dal numero di riga.
"""

import datetime

import pytest

from contratti import models as m
from contratti.importer.carica import importa

from .. import factories as f
from .conftest import OGGI, riga

pytestmark = pytest.mark.django_db
DT = datetime.datetime


def _senza_codici(**kw):
    return riga(Contratto=None, Cig=None, **kw)


def test_righe_spostate_o_inserite_non_duplicano(excel):
    prima = [
        riga(),
        _senza_codici(Descrizione="Assistenza sistemistica", Fornitore="Studio Prova"),
    ]
    importa(excel(prima, nome="v1.xlsx"), area="IT", oggi=OGGI)
    assert m.Contratto.objects.count() == 2

    # Versione aggiornata: una riga nuova in testa, le altre spostate di posizione.
    dopo = [
        riga(Contratto="5800000009", Cig="Z000000009", Descrizione="Servizio nuovo"),
        riga(),
        _senza_codici(Descrizione="Assistenza sistemistica", Fornitore="Studio Prova"),
    ]
    report = importa(excel(dopo, nome="v2.xlsx"), area="IT", oggi=OGGI)
    assert m.Contratto.objects.count() == 3
    assert report.conteggi["contratti_creati"] == 1
    assert report.conteggi["contratti_gia_presenti"] == 2
    assert report.codici()["GIA_PRESENTE"] == 1  # la riga senza codici ha cambiato posizione


def test_stesso_file_su_un_altro_cluster_non_duplica(excel):
    percorso = excel([riga()])
    importa(percorso, area="IT", oggi=OGGI)
    report = importa(percorso, area="TLC", oggi=OGGI)
    assert m.Contratto.objects.count() == 1
    assert report.codici()["GIA_PRESENTE"] == 1


def test_contratto_inserito_a_mano_riconosciuto(excel):
    a_mano = f.contratto(numero_contratto="5800000001", data_inizio=datetime.date(2026, 1, 1))
    report = importa(excel([riga()]), area="IT", oggi=OGGI)
    assert m.Contratto.objects.count() == 1
    (anomalia,) = [a for a in report.anomalie if a.codice == "GIA_PRESENTE"]
    assert f"id {a_mano.pk}" in anomalia.messaggio


def test_rinnovo_con_lo_stesso_numero_resta_distinto(excel):
    importa(excel([riga()]), area="IT", oggi=OGGI)
    report = importa(excel([riga(**{"Data di attivazione": DT(2027, 1, 1)})]), area="IT", oggi=OGGI)
    assert m.Contratto.objects.count() == 2
    assert report.conteggi["contratti_creati"] == 1


def test_contratto_archiviato_non_si_reimporta(excel):
    percorso = excel([riga()])
    importa(percorso, area="IT", oggi=OGGI)
    m.Contratto.objects.update(archiviato=True)  # es. archiviato come duplicato
    importa(percorso, area="IT", oggi=OGGI)
    assert m.Contratto.objects.count() == 1
