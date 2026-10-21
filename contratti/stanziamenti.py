"""Stanziamenti proposti dalle rate scadute senza fattura e loro conferma (SPEC Rev22).

Una rata dello scadenzario la cui data fattura è passata da oltre i giorni di tolleranza
(parametro), senza fattura abbinata né stanziamento attivo, si **propone** allo stanziamento
(valore derivato, non si salva). Nel budget a competenza la rata conta già come previsione per
lo stesso importo e periodo: confermare la proposta la rende uno stanziamento registrato.
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from contratti import adapters, permessi
from contratti import models as m
from contratti.acquisti import OperazioneNonAmmessa, _salva
from contratti.engine import stanziamenti as motore

Chiave = m.Parametro.Chiave


@dataclass(frozen=True)
class Proposta:
    rata: m.Rata
    voce: m.VoceContratto
    importo: Decimal
    dal: datetime.date
    al: datetime.date
    giorni_ritardo: int

    @property
    def contratto(self) -> m.Contratto:
        return self.voce.contratto


def tolleranza(oggi: datetime.date) -> int:
    return int(adapters.parametro(Chiave.STANZIAMENTO_GIORNI, oggi))


def _periodi_derivati(contratto: m.Contratto) -> dict[tuple[int, int], tuple]:
    """Periodi delle rate salvate senza periodo, ricavati rigenerando lo scadenzario."""
    voci, _ = adapters.voci_contratto(contratto)
    return {
        (v.riferimento, r.numero): (r.periodo_inizio, r.periodo_fine)
        for v in voci
        for r in (v.rate or ())
    }


def proposte(
    oggi: datetime.date,
    codici_cluster=(),
    contratto: m.Contratto | None = None,
    sottocluster: int | None = None,
):
    """Rate da stanziare, dalla più vecchia. ``codici_cluster`` e ``sottocluster`` vuoti: tutti."""
    limite = oggi - datetime.timedelta(days=tolleranza(oggi))
    qs = (
        m.Rata.objects.filter(
            data_fattura__lt=limite,
            importo__gt=0,
            fattura__isnull=True,
            piano__voce__archiviato=False,
            piano__voce__contratto__archiviato=False,
            piano__voce__contratto__data_chiusura__isnull=True,
        )
        .exclude(Q(stanziamenti__archiviato=False))
        .select_related("piano__voce__contratto__fabbisogno__cluster", "piano__voce__contratto")
        .order_by("data_fattura", "pk")
    )
    if contratto is not None:
        qs = qs.filter(piano__voce__contratto=contratto)
    if codici_cluster:
        qs = qs.filter(piano__voce__contratto__fabbisogno__cluster__codice__in=codici_cluster)
    if sottocluster:
        qs = qs.filter(piano__voce__contratto__fabbisogno__sottocluster_id=sottocluster)
    rate = list(qs)
    derivati: dict[int, dict] = {}
    risultato = []
    for r in rate:
        voce = r.piano.voce
        inizio, fine = r.periodo_dal, r.periodo_al
        if inizio is None:
            if voce.contratto_id not in derivati:
                derivati[voce.contratto_id] = _periodi_derivati(voce.contratto)
            inizio, fine = derivati[voce.contratto_id].get((voce.pk, r.numero), (None, None))
        dal, al = motore.periodo_proposto(r.data_fattura, inizio, fine)
        risultato.append(
            Proposta(r, voce, r.importo, dal, al, motore.giorni_di_ritardo(r.data_fattura, oggi))
        )
    return risultato


def conferma(rata: m.Rata, utente, oggi: datetime.date | None = None) -> m.Stanziamento:
    """Registra lo stanziamento proposto per la rata (importo e periodo della proposta)."""
    oggi = oggi or datetime.date.today()
    voce = rata.piano.voce
    permessi.verifica_oggetto(utente, voce.contratto)
    if voce.contratto.data_chiusura is not None:
        raise OperazioneNonAmmessa("Il contratto è chiuso: prima si annulla la chiusura.")
    trovata = [p for p in proposte(oggi, contratto=voce.contratto) if p.rata.pk == rata.pk]
    if not trovata:
        raise OperazioneNonAmmessa("La rata non è da stanziare (fattura o stanziamento presenti).")
    p = trovata[0]
    with transaction.atomic():
        stanziamento = m.Stanziamento(
            voce=p.voce,
            rata=p.rata,
            importo=p.importo,
            competenza_dal=p.dal,
            competenza_al=p.al,
            data_stanziamento=oggi,
            note="Proposto dalla rata scaduta senza fattura.",
        )
        stanziamento.full_clean()
        _salva(stanziamento, "Stanziamento confermato dalla proposta")
    return stanziamento
