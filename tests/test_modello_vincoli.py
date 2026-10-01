"""Vincoli di integrità nel database (CheckConstraint/UniqueConstraint), non solo nei form."""

import datetime
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from contratti import models as m

from . import factories as f

pytestmark = pytest.mark.django_db

D = datetime.date


def violates(callable_):
    with pytest.raises(IntegrityError), transaction.atomic():
        callable_()


# --- Importi ≥ 0 -------------------------------------------------------------


@pytest.mark.parametrize("campo", ["importo_fisso", "massimale_variabile"])
def test_voce_importi_negativi_rifiutati(campo):
    violates(lambda: f.voce(**{campo: Decimal("-0.01")}))


def test_voce_importo_zero_ammesso():
    # Righe a valore 0 esistono nei dati reali (SPEC §2.2): sono ammesse.
    assert f.voce(importo_fisso=Decimal("0.00")).pk


def test_rata_importo_negativo_rifiutato():
    violates(lambda: f.rata(importo=Decimal("-1.00")))


def test_stima_fabbisogno_negativa_rifiutata():
    violates(lambda: f.fabbisogno(stima_prossimo_importo=Decimal("-5.00")))


def test_opzione_importo_negativo_rifiutato():
    c = f.contratto()
    violates(
        lambda: m.OpzioneContratto.objects.create(
            contratto=c, tipo="rinnovo", mesi=12, importo=Decimal("-1")
        )
    )


def test_soglia_importo_negativo_rifiutato():
    violates(
        lambda: m.Soglia.objects.create(
            codice="x", descrizione="x", importo=Decimal("-1"), valida_dal=D(2026, 1, 1)
        )
    )


# --- Durata > 0 ---------------------------------------------------------------


def test_durata_zero_rifiutata():
    violates(lambda: f.contratto(durata_mesi=0))


def test_durata_prevista_zero_rifiutata():
    violates(lambda: f.fabbisogno(previsto_data_avvio=D(2027, 1, 1), previsto_durata_mesi=0))


def test_opzione_mesi_zero_rifiutati():
    c = f.contratto()
    violates(lambda: m.OpzioneContratto.objects.create(contratto=c, tipo="proroga", mesi=0))


# --- Stima di consumo tra 0 e 100 (TC-05) -------------------------------------


@pytest.mark.parametrize("pct", ["-0.01", "100.01"])
def test_stima_pct_fuori_intervallo(pct):
    violates(lambda: f.voce(massimale_variabile=Decimal("14000"), stima_consumo_pct=Decimal(pct)))


@pytest.mark.parametrize("pct", ["0", "30", "100"])
def test_stima_pct_estremi_inclusi(pct):
    assert f.voce(massimale_variabile=Decimal("14000"), stima_consumo_pct=Decimal(pct)).pk


def test_stima_importo_oltre_massimale_rifiutata():
    # Il probabile non può superare il massimo (TC-05).
    violates(
        lambda: f.voce(
            massimale_variabile=Decimal("14000.00"), stima_consumo_importo=Decimal("14000.01")
        )
    )


def test_stima_importo_pari_al_massimale_ammessa():
    v = f.voce(massimale_variabile=Decimal("14000.00"), stima_consumo_importo=Decimal("14000.00"))
    assert v.pk


def test_una_sola_stima_di_consumo():
    violates(
        lambda: f.voce(
            massimale_variabile=Decimal("14000"),
            stima_consumo_pct=Decimal("30"),
            stima_consumo_importo=Decimal("4200"),
        )
    )


# --- Coerenza del contratto ---------------------------------------------------


def test_finanziato_richiede_progetto():
    violates(lambda: f.contratto(finanziamento="finanziato"))


def test_ordinario_senza_progetto():
    progetto = m.Progetto.objects.create(codice_wbs="WBS-PROVA-01", descrizione="Progetto prova")
    violates(lambda: f.contratto(finanziamento="ordinario", progetto=progetto))
    assert f.contratto(finanziamento="finanziato", progetto=progetto).pk


def test_tacito_rinnovo_richiede_preavviso():
    violates(lambda: f.contratto(tacito_rinnovo=True))
    assert f.contratto(tacito_rinnovo=True, preavviso_disdetta_giorni=90).pk


def test_fine_override_non_prima_dell_inizio():
    violates(lambda: f.contratto(data_inizio=D(2026, 1, 1), data_fine_override=D(2025, 12, 31)))


def test_data_inizio_mancante_ammessa():
    # TC-08: contratto importato senza data di attivazione, escluso poi dai calcoli.
    assert f.contratto(data_inizio=None).pk


def test_contratto_non_precede_se_stesso():
    c = f.contratto()
    c.predecessore_id = c.pk
    violates(lambda: c.save())


def test_un_solo_successore_per_contratto():
    base = f.contratto()
    f.contratto(fabbisogno=base.fabbisogno, predecessore=base, data_inizio=D(2027, 1, 1))
    violates(
        lambda: f.contratto(
            fabbisogno=base.fabbisogno, predecessore=base, data_inizio=D(2027, 1, 1)
        )
    )


# --- Fabbisogno, fornitore, pratica ------------------------------------------


def test_previsto_manuale_avvio_e_durata_insieme():
    violates(lambda: f.fabbisogno(previsto_data_avvio=D(2027, 1, 1)))
    violates(lambda: f.fabbisogno(previsto_durata_mesi=12))
    assert f.fabbisogno(previsto_data_avvio=D(2027, 1, 1), previsto_durata_mesi=12).pk


def test_partita_iva_unica_ma_facoltativa():
    f.fornitore("A", partita_iva="00000000001")
    violates(lambda: f.fornitore("B", partita_iva="00000000001"))
    # Più fornitori senza P.IVA (NULL o vuota) sono ammessi.
    f.fornitore("C", partita_iva=None)
    f.fornitore("D", partita_iva=None)
    f.fornitore("E", partita_iva="")
    f.fornitore("F", partita_iva="")


def test_codice_sap_condiviso_ammesso_e_segnalabile():
    a = f.fornitore("A", codice_sap="999001")
    b = f.fornitore("B", codice_sap="999001")
    f.fornitore("C", codice_sap="999002")
    assert list(a.fornitori_stesso_codice_sap()) == [b]
    assert not f.fornitore("D").fornitori_stesso_codice_sap().exists()


def test_pratica_su_contratto_o_fabbisogno_mai_entrambi():
    c = f.contratto()
    stato = m.StatoPratica.Stato.NON_AVVIATA
    violates(lambda: m.StatoPratica.objects.create(stato=stato, data=D(2026, 9, 1)))
    violates(
        lambda: m.StatoPratica.objects.create(
            contratto=c, fabbisogno=c.fabbisogno, stato=stato, data=D(2026, 9, 1)
        )
    )
    assert m.StatoPratica.objects.create(contratto=c, stato=stato, data=D(2026, 9, 1)).pk
    assert m.StatoPratica.objects.create(
        fabbisogno=c.fabbisogno, stato=stato, data=D(2026, 9, 1)
    ).pk


# --- Piano di fatturazione e rate ---------------------------------------------


@pytest.mark.parametrize("modalita", ["anticipata", "posticipata"])
def test_modalita_a_rate_richiede_periodicita(modalita):
    violates(lambda: f.piano(modalita=modalita, periodicita=""))


@pytest.mark.parametrize("modalita", ["una_tantum", "sal", "consumo", "da_verificare"])
def test_altre_modalita_senza_periodicita(modalita):
    assert f.piano(modalita=modalita, periodicita="").pk


def test_adeguamento_percentuale_richiede_pct():
    violates(lambda: f.piano(adeguamento="percentuale"))
    assert f.piano(adeguamento="percentuale", adeguamento_pct=Decimal("2.50")).pk


def test_un_solo_piano_per_voce():
    v = f.voce()
    f.piano(v)
    violates(lambda: f.piano(v))


def test_rata_numero_unico_nel_piano():
    p = f.piano()
    f.rata(p, numero=1)
    violates(lambda: f.rata(p, numero=1))


def test_rata_pagamento_non_prima_della_fattura():
    violates(lambda: f.rata(data_fattura=D(2026, 3, 1), data_pagamento_stimata=D(2026, 2, 28)))


def test_proroga_stessa_fine_non_duplicata():
    c = f.contratto()
    m.Proroga.objects.create(contratto=c, data_atto=D(2026, 11, 1), nuova_data_fine=D(2027, 6, 30))
    violates(
        lambda: m.Proroga.objects.create(
            contratto=c, data_atto=D(2026, 12, 1), nuova_data_fine=D(2027, 6, 30)
        )
    )


# --- Configurazione ---------------------------------------------------------


def test_validita_conto_coerente():
    violates(
        lambda: m.ContoCoge.objects.create(
            codice="6000000001", descrizione="x", valido_dal=D(2026, 1, 1), valido_al=D(2025, 1, 1)
        )
    )


def test_conto_non_sostituisce_se_stesso():
    conto = m.ContoCoge.objects.create(
        codice="6000000001", descrizione="x", valido_dal=D(2020, 1, 1)
    )
    conto.sostituito_da_id = conto.pk
    violates(lambda: conto.save())


def test_parametro_unico_per_chiave_e_data():
    violates(
        lambda: m.Parametro.objects.create(
            chiave="giorni_pagamento", valore=Decimal("30"), valido_dal=D(2000, 1, 1)
        )
    )


def test_importi_decimal_a_due_decimali():
    v = f.voce(importo_fisso=Decimal("4800.00"))
    v.refresh_from_db()
    assert v.importo_fisso == Decimal("4800.00")
    assert isinstance(v.importo_fisso, Decimal)
    field = m.VoceContratto._meta.get_field("importo_fisso")
    assert (field.max_digits, field.decimal_places) == (14, 2)
