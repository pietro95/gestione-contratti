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
    sottocluster: "int | tuple[int, ...] | None" = None,
):
    """Rate da stanziare, dalla più vecchia. ``codici_cluster`` e ``sottocluster`` vuoti: tutti."""
    limite = oggi - datetime.timedelta(days=tolleranza(oggi))
    qs = (
        m.Rata.objects.filter(
            data_fattura__lt=limite,
            importo__gt=0,
            fattura__isnull=True,
            stanziamento_ignorato=False,
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
        qs = qs.filter(
            piano__voce__contratto__fabbisogno__sottocluster_id__in=permessi.ids_sottocluster(
                sottocluster
            )
        )
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


def _verifica_ignorabile(rata: m.Rata, utente) -> None:
    contratto = rata.piano.voce.contratto
    permessi.verifica_oggetto(utente, contratto)
    if contratto.data_chiusura is not None:
        raise OperazioneNonAmmessa("Il contratto è chiuso: prima si annulla la chiusura.")


def ignora(
    rata: m.Rata,
    utente,
    oggi: datetime.date | None = None,
    motivo: str = m.Rata.MotivoIgnorata.FATTURATA,
    nota: str = "",
) -> m.Rata:
    """La rata non si propone più allo stanziamento (Rev52). Il budget non cambia."""
    oggi = oggi or datetime.date.today()
    _verifica_ignorabile(rata, utente)
    if motivo not in m.Rata.MotivoIgnorata.values:
        raise OperazioneNonAmmessa("Motivo non valido.")
    nota = (nota or "").strip()
    if motivo == m.Rata.MotivoIgnorata.ALTRO and not nota:
        raise OperazioneNonAmmessa("Con il motivo «Altro» la nota è obbligatoria.")
    if len(nota) > 200:
        raise OperazioneNonAmmessa("La nota è troppo lunga (massimo 200 caratteri).")
    if rata.fattura_id is not None:
        raise OperazioneNonAmmessa("La rata ha già una fattura abbinata: non è da stanziare.")
    if rata.stanziamento_ignorato:
        raise OperazioneNonAmmessa("La rata è già ignorata.")
    if rata.stanziamenti.filter(archiviato=False).exists():
        raise OperazioneNonAmmessa("La rata ha uno stanziamento attivo: prima si annulla.")
    rata.stanziamento_ignorato = True
    rata.ignorata_motivo = motivo
    rata.ignorata_nota = nota
    rata.ignorata_il = oggi
    rata.ignorata_da = getattr(utente, "username", "")[:150]
    _salva(rata, "Rata esclusa dalle proposte di stanziamento")
    return rata


def ignora_fino_al(
    soglia: datetime.date,
    utente,
    oggi: datetime.date | None = None,
    motivo: str = m.Rata.MotivoIgnorata.FATTURATA,
    nota: str = "",
    codici_cluster=(),
    sottocluster=None,
    contratto: m.Contratto | None = None,
) -> int:
    """Ignora le proposte con data fattura fino alla soglia (compresa); restituisce quante.

    Vale solo per le rate che l'utente può modificare. Es. fatture dei contratti storici.
    """
    oggi = oggi or datetime.date.today()
    fatte = 0
    with transaction.atomic():
        for p in proposte(oggi, codici_cluster, contratto=contratto, sottocluster=sottocluster):
            if p.rata.data_fattura > soglia:
                continue
            if not permessi.puo_modificare_oggetto(utente, p.contratto):
                continue
            ignora(p.rata, utente, oggi, motivo, nota)
            fatte += 1
    return fatte


def ripristina(rata: m.Rata, utente) -> m.Rata:
    """La rata torna tra le proposte di stanziamento (se ne ha ancora i requisiti)."""
    _verifica_ignorabile(rata, utente)
    if not rata.stanziamento_ignorato:
        raise OperazioneNonAmmessa("La rata non è ignorata.")
    rata.stanziamento_ignorato = False
    rata.ignorata_motivo = ""
    rata.ignorata_nota = ""
    rata.ignorata_il = None
    rata.ignorata_da = ""
    _salva(rata, "Rata ripristinata tra le proposte di stanziamento")
    return rata


def ignorate(codici_cluster=(), sottocluster=None, contratto: m.Contratto | None = None):
    """Rate escluse dalle proposte, di contratti non archiviati, dalla più vecchia."""
    qs = (
        m.Rata.objects.filter(
            stanziamento_ignorato=True,
            piano__voce__archiviato=False,
            piano__voce__contratto__archiviato=False,
        )
        .select_related("piano__voce__contratto__fabbisogno")
        .order_by("data_fattura", "pk")
    )
    if contratto is not None:
        qs = qs.filter(piano__voce__contratto=contratto)
    if codici_cluster:
        qs = qs.filter(piano__voce__contratto__fabbisogno__cluster__codice__in=codici_cluster)
    if sottocluster:
        qs = qs.filter(
            piano__voce__contratto__fabbisogno__sottocluster_id__in=permessi.ids_sottocluster(
                sottocluster
            )
        )
    return list(qs)


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
