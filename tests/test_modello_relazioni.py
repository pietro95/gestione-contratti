"""Relazioni del modello, validazioni applicative, storia delle modifiche."""

import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError

from contratti import models as m

from . import factories as f

pytestmark = pytest.mark.django_db

D = datetime.date


def test_catena_dei_rinnovi_sul_fabbisogno():
    fab = f.fabbisogno()
    c2024 = f.contratto(fabbisogno=fab, data_inizio=D(2024, 1, 1))
    c2025 = f.contratto(fabbisogno=fab, predecessore=c2024, data_inizio=D(2025, 1, 1))
    c2026 = f.contratto(fabbisogno=fab, predecessore=c2025, data_inizio=D(2026, 1, 1))

    assert c2024.successore == c2025
    assert c2025.successore == c2026
    assert set(fab.contratti.all()) == {c2024, c2025, c2026}


def test_predecessore_di_altro_fabbisogno_rifiutato():
    altro = f.contratto(fabbisogno=f.fabbisogno("Altro"))
    c = m.Contratto(
        fabbisogno=f.fabbisogno(),
        predecessore=altro,
        fornitore=altro.fornitore,
        procedura=altro.procedura,
        durata_mesi=12,
    )
    with pytest.raises(ValidationError, match="stesso fabbisogno"):
        c.full_clean()


def test_contratto_con_piu_voci():
    # Un OdA con più voci (SPEC §2.1): un contratto, n voci.
    c = f.contratto(numero_contratto="7300000001", cig="Z000000001")
    for i in range(4):
        f.voce(c, descrizione=f"Voce {i}", importo_fisso=Decimal("100.00"))
    assert c.voci.count() == 4


def test_proroghe_multiple_con_importo_nelle_voci():
    c = f.contratto(data_inizio=D(2025, 1, 1), durata_mesi=12)
    f.voce(c, importo_fisso=Decimal("12000.00"))
    p1 = m.Proroga.objects.create(
        contratto=c, data_atto=D(2025, 11, 1), nuova_data_fine=D(2026, 6, 30)
    )
    p2 = m.Proroga.objects.create(
        contratto=c, data_atto=D(2026, 5, 1), nuova_data_fine=D(2026, 12, 31)
    )
    f.voce(c, proroga=p1, descrizione="Proroga 1", importo_fisso=Decimal("6000.00"))
    f.voce(c, proroga=p2, descrizione="Proroga 2", importo_fisso=Decimal("6300.00"))

    assert list(c.proroghe.values_list("nuova_data_fine", flat=True)) == [
        D(2026, 6, 30),
        D(2026, 12, 31),
    ]
    assert c.voci.count() == 3
    assert p2.voci.get().importo_fisso == Decimal("6300.00")


def test_proroga_senza_importo_ammessa():
    c = f.contratto()
    p = m.Proroga.objects.create(
        contratto=c, data_atto=D(2026, 11, 1), nuova_data_fine=D(2027, 3, 31)
    )
    assert not p.voci.exists()


def test_voce_di_proroga_di_altro_contratto_rifiutata():
    c1, c2 = f.contratto(), f.contratto()
    p = m.Proroga.objects.create(
        contratto=c1, data_atto=D(2026, 11, 1), nuova_data_fine=D(2027, 3, 31)
    )
    voce = m.VoceContratto(contratto=c2, proroga=p, descrizione="x")
    with pytest.raises(ValidationError, match="stesso contratto"):
        voce.full_clean()


def test_piano_e_rate_della_voce():
    p = f.piano()
    f.rata(p, numero=1)
    f.rata(p, numero=2, data_fattura=D(2027, 1, 1), data_pagamento_stimata=D(2027, 3, 1))
    assert p.voce.piano_fatturazione == p
    assert list(p.rate.values_list("numero", flat=True)) == [1, 2]


def test_stato_pratica_corrente_e_ultimo_passaggio():
    c = f.contratto()
    S = m.StatoPratica.Stato
    m.StatoPratica.objects.create(contratto=c, stato=S.NON_AVVIATA, data=D(2026, 6, 1))
    m.StatoPratica.objects.create(contratto=c, stato=S.OFFERTA_RICHIESTA, data=D(2026, 7, 1))
    m.StatoPratica.objects.create(contratto=c, stato=S.RDA_PREDISPOSTA, data=D(2026, 9, 1))
    assert c.stati_pratica.first().stato == S.RDA_PREDISPOSTA
    assert c.stati_pratica.count() == 3


def test_cancellazione_protetta():
    # Nessuna cancellazione fisica a cascata: i riferimenti proteggono i dati.
    c = f.contratto()
    f.voce(c)
    with pytest.raises(ProtectedError):
        c.fabbisogno.delete()
    with pytest.raises(ProtectedError):
        c.fornitore.delete()
    with pytest.raises(ProtectedError):
        c.delete()


def test_storia_delle_modifiche():
    c = f.contratto(numero_contratto="5800000001")
    c.numero_contratto = "5800000002"
    c.save()
    c.archiviato = True
    c.save()

    storia = list(c.history.order_by("history_date"))
    assert [h.history_type for h in storia] == ["+", "~", "~"]
    assert [h.numero_contratto for h in storia] == ["5800000001", "5800000002", "5800000002"]
    delta = storia[1].diff_against(storia[0])
    assert [(ch.field, ch.old, ch.new) for ch in delta.changes] == [
        ("numero_contratto", "5800000001", "5800000002")
    ]


@pytest.mark.parametrize(
    "model",
    [
        m.Procedura,
        m.Soglia,
        m.Parametro,
        m.Categoria,
        m.Impianto,
        m.Progetto,
        m.ContoCoge,
        m.Fornitore,
        m.Fabbisogno,
        m.Contratto,
        m.OpzioneContratto,
        m.Proroga,
        m.VoceContratto,
        m.PianoFatturazione,
        m.Rata,
        m.StatoPratica,
        m.QuotaPeriodo,
    ],
)
def test_ogni_entita_ha_la_storia(model):
    assert hasattr(model, "history")


def test_valori_derivati_non_salvati():
    # CLAUDE.md regola 6: data di fine, data limite, alert non sono colonne.
    campi = {f.name for f in m.Contratto._meta.get_fields()}
    for derivato in ("data_fine", "data_limite", "data_limite_avvio", "alert"):
        assert derivato not in campi
