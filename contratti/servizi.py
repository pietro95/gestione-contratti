"""Operazioni che scrivono sul database usando il motore."""

from django.db import transaction
from django.db.models import Q

from contratti import adapters
from contratti import models as m
from contratti.engine.scadenzario import genera_rate


class ScadenzarioBloccato(Exception):
    """Lo scadenzario ha rate modificate a mano o consuntivate: non si rigenera."""


@transaction.atomic
def genera_scadenzario(voce: m.VoceContratto) -> list[m.Rata]:
    """Genera (o rigenera) le rate della voce dal suo piano di fatturazione.

    Le rate esistenti si sostituiscono solo se nessuna è stata modificata a mano o
    consuntivata: in quel caso l'operazione si rifiuta, per non perdere dati inseriti.
    """
    piano = m.PianoFatturazione.objects.select_for_update().get(voce=voce)
    esistenti = piano.rate.all()
    bloccanti = esistenti.filter(Q(modificata_manualmente=True) | Q(consuntivo=True))
    if bloccanti.exists():
        numeri = ", ".join(str(n) for n in bloccanti.values_list("numero", flat=True))
        raise ScadenzarioBloccato(
            f"Rate modificate a mano o consuntivate ({numeri}): rigenerazione non eseguita."
        )

    voci, esiti = adapters.voci_contratto(voce.contratto, con_rate_salvate=False)
    if esiti:
        raise ScadenzarioBloccato(" ".join(e.messaggio for e in esiti))
    (voce_engine,) = [v for v in voci if v.riferimento == voce.pk]

    # Le rate non toccate a mano sono dati generati: si sostituiscono (la storia resta).
    for rata in esistenti:
        rata.delete()
    nuove = [
        m.Rata(
            piano=piano,
            numero=r.numero,
            data_fattura=r.data_fattura,
            data_pagamento_stimata=r.data_pagamento,
            importo=r.importo,
            modificata_manualmente=False,
        )
        for r in genera_rate(voce_engine)
    ]
    for rata in nuove:
        rata.save()
    return nuove
