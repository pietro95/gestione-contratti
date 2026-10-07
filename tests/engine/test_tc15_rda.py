"""TC-15: fase della RDA, stato della pratica ricavato, cruscotti, RDA e fatture ferme."""

import pytest

from contratti.engine.acquisti import (
    Azione,
    ContrattoGenerato,
    DatiRDA,
    EventoRDA,
    Fase,
    PassoFattura,
    TipoEvento,
    attende_referente,
    azione_addetto,
    data_fase,
    documento_accettazione,
    fase,
    fattura_da_lavorare,
    fattura_ferma,
    passo_fattura,
    rda_ferma,
    stato_pratica,
)
from contratti.engine.scadenze import alert
from contratti.engine.tipi import Alert, Scadenza

from .casi import D

# Contratto C1 con fine 31/12/2026, affidamento diretto (lead time 4 mesi), finestra 3 mesi.
C1 = Scadenza(inizio=D(2026, 1, 1), durata_mesi=12, lead_time_mesi=4)
FINESTRA = 3
OFFERTA_RICEVUTA = ("offerta_ricevuta", D(2026, 6, 1))

INVIO, RIMANDO, ANNULLAMENTO = TipoEvento.INVIO, TipoEvento.RIMANDO, TipoEvento.ANNULLAMENTO
C2 = ContrattoGenerato(data_emissione=D(2026, 7, 20), data_inizio=D(2027, 1, 1))


def r1(*, contratti=(C2,), eventi_extra=()):
    """R1: bozza 08/06, inviata 10/06, rimandata 11/06, inviata 12/06, inserita 15/06,
    rilasciata 01/07; C2 emesso il 20/07 con inizio 01/01/2027."""
    return DatiRDA(
        data_creazione=D(2026, 6, 8),
        numero="5100000001",
        data_inserimento=D(2026, 6, 15),
        data_rilascio=D(2026, 7, 1),
        eventi=(
            EventoRDA(INVIO, D(2026, 6, 10)),
            EventoRDA(RIMANDO, D(2026, 6, 11)),
            EventoRDA(INVIO, D(2026, 6, 12)),
            *eventi_extra,
        ),
        contratti=contratti,
    )


def _alert(stato, oggi, successore=False):
    return alert(
        C1,
        oggi,
        decisione="rinnovare",
        stato_pratica=stato[0] if stato else None,
        ha_successore=successore,
        finestra_mesi=FINESTRA,
    )


@pytest.mark.parametrize(
    ("oggi", "fase_attesa", "stato_atteso", "alert_atteso", "azione", "referente"),
    [
        (D(2026, 6, 5), None, OFFERTA_RICEVUTA, Alert.GIALLO, None, False),
        (D(2026, 6, 9), Fase.BOZZA, OFFERTA_RICEVUTA, Alert.GIALLO, None, True),
        (
            D(2026, 6, 10),
            Fase.INVIATA,
            ("rda_richiesta", D(2026, 6, 10)),
            Alert.GIALLO,
            Azione.DA_INSERIRE,
            False,
        ),
        (D(2026, 6, 11), Fase.DA_CORREGGERE, OFFERTA_RICEVUTA, Alert.GIALLO, None, True),
        (
            D(2026, 6, 13),
            Fase.INVIATA,
            ("rda_richiesta", D(2026, 6, 12)),
            Alert.GIALLO,
            Azione.DA_INSERIRE,
            False,
        ),
        (
            D(2026, 6, 20),
            Fase.INSERITA,
            ("rda_predisposta", D(2026, 6, 15)),
            Alert.GIALLO,
            Azione.SOLLECITO_RILASCIO,
            False,
        ),
        (
            D(2026, 7, 5),
            Fase.RILASCIATA,
            ("rda_approvata", D(2026, 7, 1)),
            Alert.GIALLO,
            Azione.SOLLECITO_PROCUREMENT,
            False,
        ),
        (
            D(2026, 7, 25),
            Fase.CONTRATTO_EMESSO,
            ("contratto_emesso", D(2026, 7, 20)),
            None,
            None,
            False,
        ),
        (
            D(2027, 1, 5),
            Fase.CONTRATTO_EMESSO,
            ("contratto_attivo", D(2027, 1, 1)),
            None,
            None,
            False,
        ),
    ],
)
def test_tc15_a_percorso_ordinario(
    oggi, fase_attesa, stato_atteso, alert_atteso, azione, referente
):
    rda = [] if fase_attesa is None else [r1()]
    if fase_attesa is not None:
        f = fase(rda[0], oggi)
        assert f == fase_attesa
        assert azione_addetto(f) == azione
        assert attende_referente(f) is referente
    stato = stato_pratica(OFFERTA_RICEVUTA, rda, oggi)
    assert stato == stato_atteso
    successore = oggi >= C2.data_emissione
    assert _alert(stato, oggi, successore) == alert_atteso


def test_tc15_a_date_della_fase():
    assert data_fase(r1(), D(2026, 6, 9)) == D(2026, 6, 8)
    assert data_fase(r1(), D(2026, 6, 11)) == D(2026, 6, 11)
    assert data_fase(r1(), D(2026, 7, 25)) == D(2026, 7, 20)


def test_tc15_b_rda_annullata():
    annullata = r1(contratti=(), eventi_extra=(EventoRDA(ANNULLAMENTO, D(2026, 7, 10)),))
    for oggi, colore in ((D(2026, 7, 15), Alert.GIALLO), (D(2026, 9, 15), Alert.GIALLO)):
        assert fase(annullata, oggi) == Fase.ANNULLATA
        stato = stato_pratica(OFFERTA_RICEVUTA, [annullata], oggi)
        assert stato == OFFERTA_RICEVUTA
        assert _alert(stato, oggi) == colore
    r2 = DatiRDA(data_creazione=D(2026, 9, 18), eventi=(EventoRDA(INVIO, D(2026, 9, 20)),))
    stato = stato_pratica(OFFERTA_RICEVUTA, [annullata, r2], D(2026, 9, 25))
    assert stato == ("rda_richiesta", D(2026, 9, 20))


def test_tc15_c_passaggio_successivo_meno_avanzato():
    passaggio = ("offerta_richiesta", D(2026, 7, 6))
    stato = stato_pratica(passaggio, [r1(contratti=())], D(2026, 7, 7))
    assert stato == ("rda_approvata", D(2026, 7, 1))


def test_tc15_d_dati_precedenti():
    passaggio = ("rda_predisposta", D(2026, 10, 1))
    assert stato_pratica(passaggio, [], D(2026, 10, 2)) == passaggio


def test_tc15_e_ferme():
    inserita = r1(contratti=())
    # Senza rilascio: inserita il 15/06.
    inserita = DatiRDA(
        data_creazione=inserita.data_creazione,
        numero=inserita.numero,
        data_inserimento=inserita.data_inserimento,
        eventi=inserita.eventi,
    )
    assert not rda_ferma(inserita, D(2026, 7, 15), 30)
    assert rda_ferma(inserita, D(2026, 7, 16), 30)


FA1_REGISTRATA = D(2026, 3, 1)
RDC = ("ODA_RDC", D(2026, 3, 5))
MAP = ("MAP", D(2026, 3, 18))
TRASFERITA = D(2026, 3, 20)


@pytest.mark.parametrize(
    ("oggi", "passo", "ferma"),
    [
        (D(2026, 3, 2), PassoFattura.RDC, False),
        (D(2026, 3, 6), PassoFattura.MAP_MIGO, False),
        (D(2026, 3, 16), PassoFattura.MAP_MIGO, False),
        (D(2026, 3, 17), PassoFattura.MAP_MIGO, True),
        (D(2026, 3, 19), PassoFattura.TRASFERIMENTO, True),
        (D(2026, 3, 21), None, False),
    ],
)
def test_tc15_e_lavorazione_della_fattura(oggi, passo, ferma):
    documenti = [RDC, MAP]
    assert passo_fattura(documenti, oggi, TRASFERITA) == passo
    assert fattura_da_lavorare(documenti, oggi, TRASFERITA) is (passo is not None)
    assert fattura_ferma(FA1_REGISTRATA, documenti, oggi, 15, TRASFERITA) is ferma


def test_tc15_e_fuori_ordine_e_documento_proposto():
    assert passo_fattura([MAP], D(2026, 3, 19)) == PassoFattura.RDC
    assert documento_accettazione("servizio") == "MAP"
    assert documento_accettazione("fornitura") == "MIGO"


def test_tc15_f_rda_registrata_a_mano():
    r3 = DatiRDA(data_creazione=D(2026, 2, 3), numero="5100000003", data_inserimento=D(2026, 2, 2))
    assert fase(r3, D(2026, 2, 5)) == Fase.INSERITA
    assert azione_addetto(Fase.INSERITA) == Azione.SOLLECITO_RILASCIO
    # Collegata alla pratica di C5 (non avviata, nessun passaggio).
    assert stato_pratica(None, [r3], D(2026, 2, 10)) == ("rda_predisposta", D(2026, 2, 2))


def test_bozza_e_da_correggere_non_contano():
    bozza = DatiRDA(data_creazione=D(2026, 6, 8))
    assert stato_pratica(None, [bozza], D(2026, 6, 9)) is None
    assert stato_pratica(OFFERTA_RICEVUTA, [bozza], D(2026, 6, 9)) == OFFERTA_RICEVUTA
