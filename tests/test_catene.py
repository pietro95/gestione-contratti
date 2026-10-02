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


# --- Contratti doppi (bug: "accorpando i fabbisogni non si accorpano i contratti") ------


def _doppio(fabbisogno, numero="5800000100", **kw):
    kw.setdefault("data_inizio", D(2025, 1, 1))
    c = f.contratto(fabbisogno=fabbisogno, numero_contratto=numero, durata_mesi=12, **kw)
    f.voce(c, importo_fisso=Decimal("1000.00"))
    return c


def test_accorpare_unisce_lo_stesso_contratto_registrato_due_volte(due):
    a, b = due
    copia = _doppio(a)
    buono = _doppio(b)
    f.piano(buono.voci.get(), modalita="anticipata", periodicita="annuale")  # più dati
    anteprima = servizi.anteprima_accorpamento(a, b)
    assert [(t.pk, d.pk) for t, d in anteprima.doppioni] == [(buono.pk, copia.pk)]
    assert not any("sovrapposti" in x for x in anteprima.avvisi)
    servizi.accorpa_fabbisogni(a, b)
    _ricarica(copia, buono)
    assert copia.archiviato and not buono.archiviato
    assert copia.fabbisogno == b  # resta nello storico del fabbisogno accorpato
    attivi = m.Contratto.objects.filter(fabbisogno=b, archiviato=False)
    assert list(attivi) == [buono]


def test_il_doppione_passa_la_catena_al_contratto_tenuto(due):
    a, b = due
    (vecchio,) = _catena(a, 2024)
    copia = _doppio(a, predecessore=vecchio)
    buono = _doppio(b)
    m.StatoPratica.objects.create(contratto=buono, stato="offerta_richiesta", data=D(2025, 6, 1))
    servizi.accorpa_fabbisogni(a, b)
    _ricarica(vecchio, copia, buono)
    assert copia.archiviato and copia.predecessore is None
    assert buono.predecessore == vecchio
    assert adapters.contratto_base_previsti(b) == buono


def test_doppioni_nello_stesso_fabbisogno(due):
    a, _ = due
    primo = _doppio(a)
    secondo = _doppio(a)
    ((tenuto, doppione),) = servizi.doppioni_del_fabbisogno(a)
    assert (tenuto, doppione) == (primo, secondo)  # a parità di dati si tiene il più vecchio
    with pytest.raises(servizi.OperazioneNonAmmessa):
        servizi.unisci_doppioni(a, [(secondo.pk, primo.pk)])
    assert servizi.unisci_doppioni(a, [(primo.pk, secondo.pk)]) == 1
    _ricarica(secondo)
    assert secondo.archiviato
    assert servizi.doppioni_del_fabbisogno(a) == []


def test_rinnovi_con_lo_stesso_numero_non_sono_doppioni(due):
    a, _ = due
    _doppio(a, data_inizio=D(2025, 1, 1))
    _doppio(a, data_inizio=D(2026, 1, 1))
    assert servizi.doppioni_del_fabbisogno(a) == []


# --- Catene interrotte (bug: "accorpando i fabbisogni non si collegano i contratti") ----


def test_accorpare_ricuce_le_catene_che_si_alternano(due):
    """Il contratto che finisce il 31/12/2025 si collega a quello dal 01/01/2026.

    In b c'è anche un contratto 2024 senza rinnovo: le catene ordinate per inizio si
    alternano (x 2023, y 2024, z 2026) e un confronto solo tra catene consecutive non
    proponeva nulla per x.
    """
    a, b = due
    x = f.contratto(fabbisogno=a, data_inizio=D(2023, 1, 1), durata_mesi=36)
    (y,) = _catena(b, 2024)
    (z,) = _catena(b, 2026)
    anteprima = servizi.anteprima_accorpamento(a, b)
    assert [(p.pk, s.pk) for p, s in anteprima.collegamenti] == [(x.pk, z.pk)]
    servizi.accorpa_fabbisogni(a, b, collegamenti=[(x.pk, z.pk)])
    _ricarica(x, y, z)
    assert z.predecessore == x and adapters.ha_successore(x)
    assert adapters.alert_contratto(x, D(2026, 1, 15)) != adapters.Alert.ROSSO


def test_catena_interrotta_si_ricuce_dal_fabbisogno(due):
    """Fabbisogni già accorpati senza collegamento: il vecchio contratto resta in rosso."""
    a, b = due
    (vecchio,) = _catena(a, 2025)
    (nuovo,) = _catena(b, 2026)
    servizi.accorpa_fabbisogni(a, b)  # collegamento non confermato
    _ricarica(vecchio, nuovo)
    assert adapters.alert_contratto(vecchio, D(2026, 1, 15)) == adapters.Alert.ROSSO
    assert servizi.collegamenti_del_fabbisogno(b) == [(vecchio, nuovo)]
    with pytest.raises(servizi.OperazioneNonAmmessa):
        servizi.collega_contratti(b, [(nuovo.pk, vecchio.pk)])
    assert servizi.collega_contratti(b, [(vecchio.pk, nuovo.pk)]) == 1
    _ricarica(vecchio, nuovo)
    assert nuovo.predecessore == vecchio
    assert adapters.alert_contratto(vecchio, D(2026, 1, 15)) != adapters.Alert.ROSSO
    assert nuovo.history.first().history_change_reason == "Catena dei rinnovi ricucita"
    assert servizi.collegamenti_del_fabbisogno(b) == []


def test_ogni_rinnovo_si_propone_una_volta_sola(due):
    a, b = due
    (vecchio,) = _catena(a, 2024)
    (piu_vicino,) = _catena(b, 2025)
    (dopo,) = _catena(b, 2027)
    coppie, _ = servizi.proponi_collegamenti(m.Contratto.objects.all())
    # Prima le coppie più vicine nel tempo: 2024 → 2025, poi 2025 → 2027.
    assert coppie == [(vecchio, piu_vicino), (piu_vicino, dopo)]


def test_rinnovo_che_ha_gia_un_predecessore_avviso(due):
    a, b = due
    (x,) = _catena(a, 2025)
    _, y = _catena(b, 2025, 2026)  # y ha già il suo predecessore
    anteprima = servizi.anteprima_accorpamento(a, b)
    assert anteprima.collegamenti == []
    assert any("già il rinnovo di un altro contratto" in v for v in anteprima.avvisi)
    assert x.pk and y.predecessore_id
