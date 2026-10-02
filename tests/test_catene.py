"""F8: spostare un contratto e accorpare fabbisogni senza rompere la catena dei rinnovi."""

import datetime
from decimal import Decimal

import pytest

from contratti import adapters, servizi
from contratti import models as m

from . import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date


def _catena(fabbisogno, *anni):
    """Contratti annuali consecutivi dal 1° gennaio degli anni dati, collegati in catena."""
    contratti, prima = [], None
    fornitore = f.fornitore(f"Fornitore {fabbisogno.descrizione}")
    for anno in anni:
        c = f.contratto(
            fabbisogno=fabbisogno,
            fornitore=fornitore,
            predecessore=prima,
            data_inizio=D(anno, 1, 1),
            durata_mesi=12,
            numero_contratto=f"58{anno}{fabbisogno.pk:04d}",
        )
        f.voce(c, importo_fisso=Decimal("1000.00"))
        contratti.append(c)
        prima = c
    return contratti


def _ricarica(*oggetti):
    for o in oggetti:
        o.refresh_from_db()


@pytest.fixture
def due():
    a = f.fabbisogno("Assistenza applicativa", decisione="rinnovare")
    b = f.fabbisogno("Assistenza sistemistica", decisione="rinnovare")
    return a, b


def test_spostare_un_contratto_ricuce_la_catena_di_partenza(due):
    a, b = due
    p, c, s = _catena(a, 2023, 2024, 2025)
    (x,) = _catena(b, 2022)
    anteprima = servizi.anteprima_spostamento(c, b, con_successivi=False)
    assert anteprima.proposto == x  # finisce per ultimo prima dell'inizio di c
    servizi.sposta_contratto(c, b, con_successivi=False, predecessore=x)
    _ricarica(p, c, s)
    assert c.fabbisogno == b and c.predecessore == x
    assert s.fabbisogno == a and s.predecessore == p  # P → C → S diventa P → S
    assert c.history.first().history_change_reason.startswith("Spostato da «Assistenza")


def test_spostare_con_i_successivi_porta_tutta_la_coda(due):
    a, b = due
    p, c, s = _catena(a, 2023, 2024, 2025)
    servizi.sposta_contratto(c, b, con_successivi=True)
    _ricarica(p, c, s)
    assert (c.fabbisogno, s.fabbisogno, p.fabbisogno) == (b, b, a)
    assert c.predecessore is None and s.predecessore == c
    assert servizi.successore_di(p) is None
    # Ogni fabbisogno ha di nuovo una sola catena: i previsti partono dall'ultimo.
    assert adapters.contratto_base_previsti(a) == p
    assert adapters.contratto_base_previsti(b) == s


def test_il_predecessore_deve_essere_un_terminale_della_destinazione(due):
    a, b = due
    (c,) = _catena(a, 2025)
    x, y = _catena(b, 2023, 2024)
    with pytest.raises(servizi.OperazioneNonAmmessa):
        servizi.sposta_contratto(c, b, con_successivi=False, predecessore=x)  # ha già y
    with pytest.raises(servizi.OperazioneNonAmmessa):
        servizi.sposta_contratto(c, a, con_successivi=False)
    b.archiviato = True
    b.save()
    with pytest.raises(servizi.OperazioneNonAmmessa):
        servizi.anteprima_spostamento(c, b, con_successivi=False)
    _ricarica(c)
    assert c.fabbisogno == a


def test_il_form_di_modifica_non_cambia_piu_il_fabbisogno():
    from contratti.forms import ContrattoModificaForm

    assert "fabbisogno" not in ContrattoModificaForm.base_fields


def test_accorpare_unisce_le_catene_consecutive(due):
    a, b = due
    vecchi = _catena(a, 2022, 2023)
    nuovi = _catena(b, 2024, 2025)
    anteprima = servizi.anteprima_accorpamento(a, b)
    assert [(p.pk, s.pk) for p, s in anteprima.collegamenti] == [(vecchi[-1].pk, nuovi[0].pk)]
    # Senza collegamento l'ultimo vecchio resterebbe senza successore (alert rosso).
    servizi.accorpa_fabbisogni(a, b, collegamenti=[(vecchi[-1].pk, nuovi[0].pk)])
    _ricarica(a, *vecchi, *nuovi)
    assert a.archiviato
    assert all(c.fabbisogno == b for c in vecchi + nuovi)
    assert nuovi[0].predecessore == vecchi[-1]
    assert adapters.contratto_base_previsti(b) == nuovi[-1]
    assert not adapters.ha_successore(nuovi[-1])
    assert adapters.ha_successore(vecchi[-1])


def test_accorpare_senza_confermare_i_collegamenti(due):
    a, b = due
    vecchi = _catena(a, 2022)
    nuovi = _catena(b, 2024)
    servizi.accorpa_fabbisogni(a, b)
    _ricarica(*vecchi, *nuovi)
    assert nuovi[0].predecessore is None
    assert vecchi[0].fabbisogno == b


def test_collegamento_non_proposto_rifiutato(due):
    a, b = due
    (x,) = _catena(a, 2022)
    (y,) = _catena(b, 2024)
    with pytest.raises(servizi.OperazioneNonAmmessa):
        servizi.accorpa_fabbisogni(a, b, collegamenti=[(y.pk, x.pk)])
    _ricarica(a, x)
    assert not a.archiviato and x.fabbisogno == a


def test_periodi_sovrapposti_nessun_collegamento_e_avviso(due):
    a, b = due
    _catena(a, 2024)
    c = f.contratto(fabbisogno=b, data_inizio=D(2024, 6, 1), durata_mesi=12)
    anteprima = servizi.anteprima_accorpamento(a, b)
    assert anteprima.collegamenti == []
    assert any("sovrapposti" in x for x in anteprima.avvisi)
    assert c.pk


def test_previsto_manuale_e_pratica_scelta_esplicita():
    a = f.fabbisogno(
        "Servizio A",
        previsto_data_avvio=D(2027, 1, 1),
        previsto_durata_mesi=12,
        stima_prossimo_importo=Decimal("100.00"),
    )
    b = f.fabbisogno(
        "Servizio B",
        previsto_data_avvio=D(2027, 7, 1),
        previsto_durata_mesi=24,
        stima_prossimo_importo=Decimal("900.00"),
    )
    servizi.avanza_pratica(a, "offerta_richiesta", D(2026, 5, 1))
    servizi.avanza_pratica(b, "rda_richiesta", D(2026, 6, 1))
    anteprima = servizi.anteprima_accorpamento(a, b)
    assert anteprima.conflitto_previsto and anteprima.conflitto_pratica
    servizi.accorpa_fabbisogni(a, b, previsto_da_origine=True, pratica_da_origine=True)
    _ricarica(a, b)
    assert (b.previsto_data_avvio, b.previsto_durata_mesi) == (D(2027, 1, 1), 12)
    assert b.stima_prossimo_importo == Decimal("100.00")
    assert [p.stato for p in b.stati_pratica.all()] == ["offerta_richiesta"]
    # Nessun passaggio cancellato: l'altra pratica resta sull'archiviato.
    assert [p.stato for p in a.stati_pratica.all()] == ["rda_richiesta"]
    assert m.StatoPratica.objects.count() == 2


def test_senza_conflitto_si_prende_il_previsto_dell_origine():
    a = f.fabbisogno("Servizio A", previsto_data_avvio=D(2027, 1, 1), previsto_durata_mesi=12)
    b = f.fabbisogno("Servizio B")
    servizi.accorpa_fabbisogni(a, b)
    _ricarica(b)
    assert b.previsto_data_avvio == D(2027, 1, 1)
