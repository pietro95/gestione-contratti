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


class OperazioneNonAmmessa(Exception):
    pass


def _copia_piano(da: m.PianoFatturazione | None, voce: m.VoceContratto) -> None:
    if da is None:
        m.PianoFatturazione.objects.create(voce=voce, modalita="da_verificare", periodicita="")
        return
    m.PianoFatturazione.objects.create(
        voce=voce,
        modalita=da.modalita,
        periodicita=da.periodicita,
        giorni_pagamento=da.giorni_pagamento,
        pagamento_fine_mese=da.pagamento_fine_mese,
        note=da.note,
    )


@transaction.atomic
def registra_rinnovo(
    predecessore: m.Contratto, dati: dict, voci: list[dict], utente=None
) -> m.Contratto:
    """Nuovo contratto successore sullo stesso fabbisogno (SPEC §5.3, F4).

    ``dati``: campi del contratto; ``voci``: per ogni voce da riportare, il pk della voce
    del predecessore (``origine``) con descrizione e importi aggiornati. Le voci copiano il
    piano di fatturazione (senza data della prima fattura). I previsti del periodo spariscono
    perché il contratto reale prende il loro posto; la pratica del predecessore passa a
    "Contratto attivo".
    """
    if m.Contratto.objects.filter(predecessore=predecessore, archiviato=False).exists():
        raise OperazioneNonAmmessa("Il contratto ha già un successore registrato.")
    contratto = m.Contratto(fabbisogno=predecessore.fabbisogno, predecessore=predecessore, **dati)
    contratto.full_clean()
    contratto.save()
    origini = {
        v.pk: v
        for v in predecessore.voci.select_related("piano_fatturazione").filter(archiviato=False)
    }
    for dati_voce in voci:
        origine = origini.get(dati_voce.pop("origine", None))
        voce = m.VoceContratto(contratto=contratto, **dati_voce)
        if origine is not None:
            voce.conto = voce.conto or origine.conto
            voce.centro_costo = voce.centro_costo or origine.centro_costo
            voce.wbs = voce.wbs or origine.wbs
        voce.full_clean()
        voce.save()
        _copia_piano(getattr(origine, "piano_fatturazione", None), voce)
    m.StatoPratica.objects.create(
        contratto=predecessore,
        stato=m.StatoPratica.Stato.CONTRATTO_ATTIVO,
        data=contratto.data_inizio or contratto.data_stipula or predecessore.data_inizio,
        note="Rinnovo registrato.",
        utente=utente,
    )
    return contratto


@transaction.atomic
def registra_proroga(contratto: m.Contratto, dati: dict, voce: dict | None = None) -> m.Proroga:
    """Proroga esercitata, con l'eventuale importo come voce collegata (SPEC §4)."""
    fine_attuale = adapters.data_fine_effettiva(contratto)
    if fine_attuale and dati["nuova_data_fine"] <= fine_attuale:
        raise OperazioneNonAmmessa(
            f"La nuova data di fine deve essere successiva al {fine_attuale:%d/%m/%Y}."
        )
    proroga = m.Proroga(contratto=contratto, **dati)
    proroga.full_clean()
    proroga.save()
    if voce:
        piano = {k: voce.pop(k) for k in ("modalita", "periodicita") if k in voce}
        nuova = m.VoceContratto(contratto=contratto, proroga=proroga, **voce)
        nuova.full_clean()
        nuova.save()
        m.PianoFatturazione.objects.create(
            voce=nuova,
            modalita=piano.get("modalita") or "da_verificare",
            periodicita=piano.get("periodicita") or "",
        )
    return proroga


def avanza_pratica(oggetto, stato: str, data, note: str = "", utente=None) -> m.StatoPratica:
    """Nuovo passaggio della pratica su un contratto o su un fabbisogno nuovo."""
    campo = "contratto" if isinstance(oggetto, m.Contratto) else "fabbisogno"
    passaggio = m.StatoPratica(**{campo: oggetto}, stato=stato, data=data, note=note, utente=utente)
    passaggio.full_clean()
    passaggio.save()
    return passaggio


def archivia(oggetto, archiviato: bool = True) -> None:
    """Archiviazione al posto della cancellazione; passa da save() per la storia."""
    oggetto.archiviato = archiviato
    oggetto.save(update_fields=["archiviato"])


def salva_rata_manuale(rata: m.Rata) -> m.Rata:
    """Rata cambiata a mano dall'interfaccia: resta marcata come tale (CLAUDE.md, regola 6)."""
    rata.modificata_manualmente = True
    rata.full_clean()
    rata.save()
    return rata
