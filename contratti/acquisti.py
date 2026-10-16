"""Processo d'acquisto (F11): adapter verso il motore e servizi su RDA, fatture, esecuzione.

Il motore puro è ``contratti.engine.acquisti``; qui si leggono i modelli e si scrive il
database. Riferimenti: SPEC §4 (RDA, posizioni, storico, fatture, documenti), §5.7 (fase e
stato della pratica), §5.8 (esecuzione), §5.9 (scheda SAP e proposte dal fabbisogno).
"""

import datetime
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.db.models import Min, Prefetch, Q
from django.utils import timezone

from contratti import adapters
from contratti import models as m
from contratti.engine import acquisti as motore
from contratti.engine import previsioni, scadenze
from contratti.engine.importi import ZERO

Scopo = m.RichiestaAcquisto.Scopo
Chiave = m.Parametro.Chiave


class OperazioneNonAmmessa(Exception):
    pass


# --- Da modelli a motore -------------------------------------------------------------------

_CONTRATTI_GENERATI = m.Contratto.objects.filter(archiviato=False).annotate(
    prima_documento=Min(
        "documenti_esecuzione__data", filter=Q(documenti_esecuzione__archiviato=False)
    ),
    prima_fattura=Min("fatture__data", filter=Q(fatture__archiviato=False)),
)
QS_RDA = m.RichiestaAcquisto.objects.filter(archiviato=False).prefetch_related(
    "eventi", Prefetch("contratti_generati", queryset=_CONTRATTI_GENERATI)
)
# Da passare a prefetch_related su contratti e fabbisogni: stato della pratica senza query.
PREFETCH_PRATICA_CONTRATTO = Prefetch("rda_pratica", queryset=QS_RDA)
PREFETCH_PRATICA_FABBISOGNO = Prefetch("richieste_acquisto", queryset=QS_RDA)


def _contratti_generati(rda: m.RichiestaAcquisto) -> list[m.Contratto]:
    cache = getattr(rda, "_prefetched_objects_cache", {})
    if "contratti_generati" in cache:
        return [c for c in rda.contratti_generati.all() if not c.archiviato]
    return list(_CONTRATTI_GENERATI.filter(rda=rda))


def _contratto_generato(c: m.Contratto) -> motore.ContrattoGenerato:
    prime = [getattr(c, "prima_documento", None), getattr(c, "prima_fattura", None)]
    if not hasattr(c, "prima_documento"):
        prime = [
            c.documenti_esecuzione.filter(archiviato=False).aggregate(d=Min("data"))["d"],
            c.fatture.filter(archiviato=False).aggregate(d=Min("data"))["d"],
        ]
    presenti = [d for d in prime if d is not None]
    return motore.ContrattoGenerato(
        data_emissione=c.data_emissione,
        data_inizio=c.data_inizio,
        data_chiusura=c.data_chiusura,
        prima_esecuzione=min(presenti) if presenti else None,
    )


def dati_rda(rda: m.RichiestaAcquisto) -> motore.DatiRDA:
    eventi = sorted(rda.eventi.all(), key=lambda e: (e.data, e.pk))
    return motore.DatiRDA(
        data_creazione=rda.data_creazione,
        numero=rda.numero_rda or None,
        data_inserimento=rda.data_inserimento,
        data_rilascio=rda.data_rilascio,
        eventi=tuple(motore.EventoRDA(motore.TipoEvento(e.tipo), e.data) for e in eventi),
        contratti=tuple(_contratto_generato(c) for c in _contratti_generati(rda)),
    )


def fase(rda: m.RichiestaAcquisto, oggi: datetime.date | None = None) -> motore.Fase:
    return motore.fase(dati_rda(rda), oggi or timezone.localdate())


def rda_della_pratica(oggetto: m.Contratto | m.Fabbisogno) -> list[m.RichiestaAcquisto]:
    """RDA che contano per la pratica: sul contratto in scadenza, o sul fabbisogno (non
    quelle di acquisto aggiuntivo, che non toccano la pratica)."""
    if isinstance(oggetto, m.Contratto):
        return [r for r in oggetto.rda_pratica.all() if not r.archiviato]
    return [
        r
        for r in oggetto.richieste_acquisto.all()
        if not r.archiviato and r.scopo != Scopo.AGGIUNTIVO
    ]


def ultimo_passaggio(oggetto) -> motore.StatoPratica | None:
    passaggi = sorted(oggetto.stati_pratica.all(), key=lambda p: (p.data, p.pk))
    return (passaggi[-1].stato, passaggi[-1].data) if passaggi else None


def stato_pratica_con_data(
    oggetto: m.Contratto | m.Fabbisogno, oggi: datetime.date | None = None
) -> motore.StatoPratica | None:
    """Il più avanzato tra l'ultimo passaggio e lo stato ricavato dalle RDA (TC-15)."""
    oggi = oggi or timezone.localdate()
    rda = [dati_rda(r) for r in rda_della_pratica(oggetto)]
    return motore.stato_pratica(ultimo_passaggio(oggetto), rda, oggi)


def stato_pratica(oggetto, oggi: datetime.date | None = None) -> str | None:
    stato = stato_pratica_con_data(oggetto, oggi)
    return stato[0] if stato else None


def ha_rda(oggetto: m.Contratto | m.Fabbisogno) -> bool:
    return bool(rda_della_pratica(oggetto))


# --- Servizi sulla richiesta ---------------------------------------------------------------


def _evento(rda, tipo, data, utente, nota="") -> m.EventoRDA:
    return m.EventoRDA.objects.create(
        rda=rda, tipo=tipo, data=data or timezone.localdate(), utente=utente, nota=nota
    )


def invia(rda: m.RichiestaAcquisto, utente=None, data=None) -> m.EventoRDA:
    """Il referente invia la richiesta all'addetto (anche dopo un rimando)."""
    if fase(rda, data) not in (motore.Fase.BOZZA, motore.Fase.DA_CORREGGERE):
        raise OperazioneNonAmmessa("Si invia solo una richiesta in bozza o da correggere.")
    if not rda.posizioni.exists():
        raise OperazioneNonAmmessa("La richiesta non ha posizioni.")
    return _evento(rda, m.EventoRDA.Tipo.INVIO, data, utente)


def rimanda(rda: m.RichiestaAcquisto, nota: str, utente=None, data=None) -> m.EventoRDA:
    """L'addetto rimanda la richiesta al referente, con la nota di cosa correggere."""
    if fase(rda, data) != motore.Fase.INVIATA:
        raise OperazioneNonAmmessa("Si rimanda solo una richiesta inviata e non ancora in SAP.")
    if not nota.strip():
        raise OperazioneNonAmmessa("Scrivi cosa correggere.")
    return _evento(rda, m.EventoRDA.Tipo.RIMANDO, data, utente, nota)


def annulla(rda: m.RichiestaAcquisto, motivo: str, utente=None, data=None) -> m.EventoRDA:
    if fase(rda, data) in (motore.Fase.ANNULLATA, motore.Fase.CHIUSA):
        raise OperazioneNonAmmessa("La RDA è già annullata o chiusa.")
    if not motivo.strip():
        raise OperazioneNonAmmessa("Indica il motivo dell'annullamento.")
    return _evento(rda, m.EventoRDA.Tipo.ANNULLAMENTO, data, utente, motivo)


# --- Proposta della richiesta dal fabbisogno (SPEC §4, §5.9) ------------------------------


@dataclass
class PosizioneProposta:
    descrizione_breve: str
    importo_unitario: Decimal | None
    quantita: Decimal = Decimal(1)
    di_cui_variabile: Decimal = ZERO
    natura: str = m.Natura.OPEX
    conto: m.ContoCoge | None = None
    centro_costo: str = ""
    wbs: m.WBS | None = None
    gruppo_merci: m.GruppoMerci | None = None


@dataclass
class PropostaRichiesta:
    fabbisogno: m.Fabbisogno
    scopo: str
    contratto_in_scadenza: m.Contratto | None
    descrizione: str
    intestazione: str
    fornitore_proposto: m.Fornitore | None
    richiedente: m.RichiedenteSAP | None
    gruppo_acquisti: m.GruppoAcquisti | None
    percorso_file_server: str
    rup: str = ""
    cup: str = ""
    posizioni: list[PosizioneProposta] = field(default_factory=list)
    # Altri contratti senza successore (catena interrotta): si possono scegliere al posto.
    alternative: list[m.Contratto] = field(default_factory=list)

    @property
    def importo(self) -> Decimal:
        return sum(
            (
                motore.importo_posizione(p.quantita, p.importo_unitario)
                for p in self.posizioni
                if p.importo_unitario is not None
            ),
            ZERO,
        )


def gruppo_merci_proposto(fabbisogno: m.Fabbisogno) -> m.GruppoMerci | None:
    """Il gruppo merci predefinito (la tabella non lega più i gruppi alle categorie)."""
    return m.GruppoMerci.predefinito_attivo()


def _ha_contratti_da_rinnovare(fabbisogno: m.Fabbisogno) -> bool:
    return fabbisogno.contratti.filter(archiviato=False, una_tantum=False).exists()


def _primo_previsto(fabbisogno: m.Fabbisogno, contratto: m.Contratto):
    """Il rinnovo previsto del contratto (SPEC §5.3), anche con la decisione «Dismettere»:
    la richiesta lo chiede esplicitamente."""
    base = adapters.contratto_base(contratto)
    inizio = base.fine_effettiva + datetime.timedelta(days=1)
    return previsioni.prossimo(
        base, adapters.adeguamento_alla_data(inizio), fabbisogno.stima_prossimo_importo
    )


def proposta_richiesta(
    fabbisogno: m.Fabbisogno,
    oggi: datetime.date | None = None,
    *,
    aggiuntivo: bool = False,
    contratto_in_scadenza: m.Contratto | None = None,
) -> PropostaRichiesta:
    """Campi e posizioni proposti per una nuova richiesta di RDA dal fabbisogno (TC-17).

    Rinnovo se il fabbisogno ha contratti (non una tantum): la richiesta si lega al
    contratto in scadenza, quello da cui partono i previsti, o a un altro senza successore
    scelto dall'utente. Primo acquisto se non ne ha. Acquisto aggiuntivo a scelta.
    """
    oggi = oggi or timezone.localdate()
    terminali = sorted(
        adapters.contratti_terminali(fabbisogno),
        key=lambda c: (scadenze.data_fine_effettiva(adapters.scadenza(c)), c.pk),
        reverse=True,
    )
    da_rinnovare = _ha_contratti_da_rinnovare(fabbisogno)
    if aggiuntivo and not da_rinnovare:
        raise OperazioneNonAmmessa("L'acquisto aggiuntivo serve solo se ci sono contratti.")
    scopo = Scopo.PRIMO_ACQUISTO
    if da_rinnovare:
        scopo = Scopo.AGGIUNTIVO if aggiuntivo else Scopo.RINNOVO
    in_scadenza = None
    if da_rinnovare and terminali:
        in_scadenza = terminali[0]
        if contratto_in_scadenza is not None:
            if contratto_in_scadenza.pk not in {c.pk for c in terminali}:
                raise OperazioneNonAmmessa("Il contratto scelto ha già un successore.")
            in_scadenza = contratto_in_scadenza
    if scopo == Scopo.RINNOVO and in_scadenza is None:
        raise OperazioneNonAmmessa("Nessun contratto del fabbisogno da rinnovare.")

    fornitore = in_scadenza.fornitore if scopo == Scopo.RINNOVO else None
    nome_fornitore = fornitore.nome_per_rda if fornitore else None
    descrizione = fabbisogno.descrizione
    # Intestazione e descrizioni brevi proposte entro i 40 caratteri di SAP.
    titolo = motore.taglia_sap(motore.intestazione(nome_fornitore, descrizione))
    gruppo = gruppo_merci_proposto(fabbisogno)
    proposta = PropostaRichiesta(
        fabbisogno=fabbisogno,
        scopo=scopo,
        contratto_in_scadenza=in_scadenza if scopo == Scopo.RINNOVO else None,
        descrizione=descrizione,
        intestazione=titolo,
        fornitore_proposto=fornitore,
        richiedente=m.RichiedenteSAP.predefinito_attivo(),
        gruppo_acquisti=m.GruppoAcquisti.predefinito_attivo(),
        percorso_file_server=motore.percorso_cartella(
            fabbisogno.cluster.cartella_rda, oggi, nome_fornitore, descrizione
        ),
        rup=in_scadenza.rup if scopo == Scopo.RINNOVO else "",
        cup=in_scadenza.cup if scopo == Scopo.RINNOVO else "",
        alternative=[c for c in terminali if in_scadenza is None or c.pk != in_scadenza.pk]
        if scopo == Scopo.RINNOVO
        else [],
    )
    if scopo == Scopo.RINNOVO:
        proposta.posizioni = _posizioni_rinnovo(fabbisogno, in_scadenza, gruppo)
    elif scopo == Scopo.AGGIUNTIVO:
        prima = (
            in_scadenza.voci.filter(archiviato=False).order_by("pk").first()
            if in_scadenza
            else None
        )
        proposta.posizioni = [
            PosizioneProposta(
                descrizione_breve="",
                importo_unitario=None,
                natura=prima.natura if prima else m.Natura.OPEX,
                conto=prima.conto if prima else None,
                centro_costo=prima.centro_costo if prima else "",
                wbs=prima.wbs if prima else None,
                gruppo_merci=gruppo,
            )
        ]
    else:
        classe = adapters.classificazione_prevista(fabbisogno, None)
        proposta.posizioni = [
            PosizioneProposta(
                descrizione_breve=titolo,
                importo_unitario=fabbisogno.stima_prossimo_importo,
                natura=classe.natura,
                conto=classe.conto,
                wbs=classe.wbs,
                gruppo_merci=gruppo,
            )
        ]
    return proposta


def _posizioni_rinnovo(fabbisogno, contratto, gruppo) -> list[PosizioneProposta]:
    """Una posizione per voce del rinnovo previsto, per l'importo massimo (fisso + massimale)."""
    previsto = _primo_previsto(fabbisogno, contratto)
    modelli = {v.pk: v for v in contratto.voci.all()}
    posizioni = []
    for i, voce in enumerate(previsto.voci):
        modello = modelli.get(voce.riferimento)
        classe = adapters.classificazione_prevista(fabbisogno, modello)
        posizioni.append(
            PosizioneProposta(
                descrizione_breve=modello.descrizione if modello and i else "",
                importo_unitario=voce.importo_fisso + voce.massimale_variabile,
                di_cui_variabile=voce.massimale_variabile,
                natura=classe.natura,
                conto=classe.conto,
                centro_costo=modello.centro_costo if modello else "",
                wbs=classe.wbs,
                gruppo_merci=gruppo,
            )
        )
    if posizioni:
        posizioni[0].descrizione_breve = motore.intestazione(
            contratto.fornitore.nome_per_rda, fabbisogno.descrizione
        )
    for p in posizioni:
        p.descrizione_breve = motore.taglia_sap(p.descrizione_breve)
    return posizioni


@transaction.atomic
def crea_richiesta(proposta: PropostaRichiesta, referente, **campi) -> m.RichiestaAcquisto:
    """Salva la richiesta (in bozza) con le posizioni proposte, eventualmente cambiate."""
    contratto = proposta.contratto_in_scadenza
    rda = m.RichiestaAcquisto(
        origine=m.RichiestaAcquisto.Origine.PORTALE,
        scopo=proposta.scopo,
        cluster=proposta.fabbisogno.cluster,
        fabbisogno=None if contratto else proposta.fabbisogno,
        contratto_in_scadenza=contratto,
        referente_utente=referente,
        descrizione=proposta.descrizione,
        intestazione=proposta.intestazione,
        fornitore_proposto=proposta.fornitore_proposto,
        richiedente=proposta.richiedente,
        gruppo_acquisti=proposta.gruppo_acquisti,
        percorso_file_server=proposta.percorso_file_server,
        rup=proposta.rup,
        cup=proposta.cup,
    )
    for nome, valore in campi.items():
        setattr(rda, nome, valore)
    rda.full_clean()
    rda.save()
    for numero, p in enumerate(proposta.posizioni, start=1):
        posizione = m.PosizioneRDA(
            rda=rda,
            numero=numero,
            descrizione_breve=p.descrizione_breve or proposta.intestazione,
            gruppo_merci=p.gruppo_merci,
            quantita=p.quantita,
            importo_unitario=p.importo_unitario or ZERO,
            di_cui_variabile=p.di_cui_variabile,
            natura=p.natura,
            conto=p.conto,
            centro_costo=p.centro_costo,
            wbs=p.wbs if p.natura == m.Natura.CAPEX else None,
        )
        posizione.full_clean()
        posizione.save()
    return rda


# --- Scheda SAP (SPEC §5.9) ----------------------------------------------------------------


def scheda(rda: m.RichiestaAcquisto) -> motore.SchedaRDA:
    posizioni = rda.posizioni.select_related("gruppo_merci", "conto", "wbs").order_by("numero")
    return motore.SchedaRDA(
        intestazione=rda.intestazione or rda.descrizione,
        posizioni=tuple(
            motore.PosizioneScheda(
                descrizione_breve=p.descrizione_breve,
                gruppo_merci=p.gruppo_merci.codice if p.gruppo_merci_id else "",
                quantita=p.quantita,
                importo_unitario=p.importo_unitario,
                wbs=p.wbs.codice_wbs if p.wbs_id else "",
                conto=p.conto.codice if p.conto_id else "",
                centro_costo=p.centro_costo,
                di_cui_variabile=p.di_cui_variabile,
            )
            for p in posizioni
        ),
        richiedente=rda.richiedente.codice if rda.richiedente_id else "",
        gruppo_acquisti=rda.gruppo_acquisti.codice if rda.gruppo_acquisti_id else "",
        note_buyer=rda.note_buyer,
        allegati=rda.allegati,
        percorso=rda.percorso_file_server,
    )


def testo_della_richiesta(rda: m.RichiestaAcquisto) -> str:
    return motore.componi_testo_richiesta(scheda(rda))


def importo_rda(rda: m.RichiestaAcquisto) -> Decimal:
    return sum((p.importo for p in rda.posizioni.all()), ZERO)


def voci_da_rda(rda: m.RichiestaAcquisto) -> list[dict]:
    """Voci proposte per il contratto registrato dalla RDA: una per posizione.

    Fisso = importo della posizione − di cui variabile; massimale = di cui variabile.
    """
    voci = []
    for p in rda.posizioni.select_related("conto", "wbs").order_by("numero"):
        voci.append(
            {
                "descrizione": p.descrizione_breve,
                "importo_fisso": p.importo - p.di_cui_variabile,
                "massimale_variabile": p.di_cui_variabile,
                "natura": p.natura,
                "conto": p.conto,
                "centro_costo": p.centro_costo,
                "wbs": p.wbs,
            }
        )
    return voci


def massimo_contratto(contratto: m.Contratto) -> Decimal:
    voci = contratto.voci.filter(archiviato=False)
    return sum((v.importo_fisso + v.massimale_variabile for v in voci), ZERO)


def differenza_da_rda(contratto: m.Contratto) -> Decimal | None:
    """Massimo del contratto (fisso + massimale) meno l'importo della RDA d'origine."""
    if contratto.rda_id is None:
        return None
    return massimo_contratto(contratto) - importo_rda(contratto.rda)


# --- Esecuzione del contratto (SPEC §5.8) --------------------------------------------------


@dataclass
class RiepilogoEsecuzione:
    esecuzione: motore.Esecuzione
    motivo_da_chiudere: motore.MotivoChiusura | None
    anomalie: list[str]


def riepilogo_esecuzione(
    contratto: m.Contratto, oggi: datetime.date | None = None
) -> RiepilogoEsecuzione:
    oggi = oggi or timezone.localdate()
    voci = [v for v in contratto.voci.all() if not v.archiviato]
    fisso = sum((v.importo_fisso for v in voci), ZERO)
    massimale = sum((v.massimale_variabile for v in voci), ZERO)
    fatture = [
        motore.FatturaRegistrata(f.data, f.valore_base, f.numero, f.fornitore_id)
        for f in contratto.fatture.all()
        if not f.archiviato and not f.fuori_registro
    ]
    documenti = [
        motore.DocumentoEseguito(d.tipo, d.data, d.finale)
        for d in contratto.documenti_esecuzione.all()
        if not d.archiviato
    ]
    pregresso = sum(
        (p.importo for p in contratto.fatturato_pregresso.all() if not p.archiviato), ZERO
    )
    risultato = motore.esecuzione(fisso, massimale, fatture, oggi, pregresso)
    return RiepilogoEsecuzione(
        esecuzione=risultato,
        motivo_da_chiudere=motore.motivo_da_chiudere(
            adapters.data_fine_effettiva(contratto),
            contratto.data_chiusura,
            documenti,
            risultato.residuo_fisso,
            oggi,
        ),
        anomalie=motore.anomalie_esecuzione(
            fisso, massimale, fatture, documenti, contratto.data_chiusura, oggi, pregresso
        ),
    )


def chiudi(contratto: m.Contratto, utente=None, data=None) -> None:
    """Chiusura amministrativa: la registrano l'addetto o il referente (SPEC §4)."""
    if contratto.data_chiusura is not None:
        raise OperazioneNonAmmessa("Il contratto è già chiuso.")
    contratto.data_chiusura = data or timezone.localdate()
    contratto.chiuso_da = utente
    contratto.save(update_fields=["data_chiusura", "chiuso_da"])


def annulla_chiusura(contratto: m.Contratto) -> None:
    if contratto.data_chiusura is None:
        raise OperazioneNonAmmessa("Il contratto non è chiuso.")
    contratto.data_chiusura = None
    contratto.chiuso_da = None
    contratto.save(update_fields=["data_chiusura", "chiuso_da"])


# Lavorazione della fattura: ``contratti.fatture`` (F11.3).


# --- Parametri ------------------------------------------------------------------------------


def giorni_rda_ferma(oggi: datetime.date) -> int:
    return int(adapters.parametro(Chiave.RDA_FERMA_GIORNI, oggi))


def giorni_fattura_ferma(oggi: datetime.date) -> int:
    return int(adapters.parametro(Chiave.FATTURA_FERMA_GIORNI, oggi))


# --- Interfaccia (F11.2): salvataggio, dati SAP, collegamenti, contratto dalla RDA ----------


def _salva(oggetto, motivo: str = "", **kw) -> None:
    if motivo:
        oggetto._change_reason = motivo[:100]
    oggetto.save(**kw)


FASI_MODIFICABILI_DAL_REFERENTE = frozenset({motore.Fase.BOZZA, motore.Fase.DA_CORREGGERE})


def correzione_diretta(rda: m.RichiestaAcquisto, oggi: datetime.date | None = None) -> bool:
    """Modificare ora la richiesta è una correzione diretta (inviata o oltre), tracciata."""
    return fase(rda, oggi) not in FASI_MODIFICABILI_DAL_REFERENTE


@transaction.atomic
def salva_richiesta(rda: m.RichiestaAcquisto, posizioni: list[dict]) -> m.RichiestaAcquisto:
    """Salva la richiesta e le sue posizioni, numerate nell'ordine dato.

    ``posizioni``: dizionari con i campi della posizione e, per quelle già salvate, ``pk``.
    Le posizioni già salvate non si cancellano (regola 8): si modificano.
    """
    motivo = "Correzione diretta dopo l'invio" if rda.pk and correzione_diretta(rda) else ""
    rda.full_clean()
    _salva(rda, motivo)
    esistenti = {p.pk: p for p in rda.posizioni.all()}
    # Numeri provvisori alti: evitano il vincolo (rda, numero) mentre si rinumera.
    for p in esistenti.values():
        p.numero += 1000
        p.save(update_fields=["numero"])
    for numero, dati in enumerate(posizioni, start=1):
        dati = dict(dati)
        posizione = esistenti.pop(dati.pop("pk", None), None) or m.PosizioneRDA(rda=rda)
        for campo, valore in dati.items():
            setattr(posizione, campo, valore)
        if posizione.natura != m.Natura.CAPEX:
            posizione.wbs = None
        posizione.numero = numero
        posizione.full_clean()
        _salva(posizione, motivo)
    for numero, posizione in enumerate(
        sorted(esistenti.values(), key=lambda p: p.numero), start=len(posizioni) + 1
    ):
        posizione.numero = numero  # non toccate dal form: restano, in fondo
        posizione.save(update_fields=["numero"])
    return rda


@transaction.atomic
def aggiorna_dati_sap(rda, numero_rda, data_inserimento, data_rilascio) -> None:
    """Dati che SAP restituisce: li riporta l'addetto (o il referente)."""
    if fase(rda) == motore.Fase.ANNULLATA:
        raise OperazioneNonAmmessa("La RDA è annullata.")
    rda.numero_rda = (numero_rda or "").strip() or None
    rda.data_inserimento = data_inserimento
    rda.data_rilascio = data_rilascio
    if rda.numero_rda and rda.data_inserimento is None:
        rda.data_inserimento = timezone.localdate()
    if rda.data_rilascio and not rda.numero_rda:
        raise OperazioneNonAmmessa("Prima del rilascio serve il numero della RDA.")
    rda.full_clean()
    _salva(rda, "Dati da SAP")


@transaction.atomic
def collega_pratica(
    rda: m.RichiestaAcquisto,
    *,
    fabbisogno: m.Fabbisogno | None = None,
    contratto: m.Contratto | None = None,
) -> None:
    """Lega la RDA alla pratica: contratto in scadenza o fabbisogno; nessuno dei due la scollega."""
    if fabbisogno is not None and contratto is not None:
        raise OperazioneNonAmmessa("Scegli il contratto in scadenza oppure il fabbisogno.")
    if rda.origine == m.RichiestaAcquisto.Origine.PORTALE and not (fabbisogno or contratto):
        raise OperazioneNonAmmessa("Una richiesta nata sul portale resta legata al fabbisogno.")
    if contratto is not None and adapters.ha_successore(contratto):
        raise OperazioneNonAmmessa("Il contratto ha già un successore: non è in scadenza.")
    rda.fabbisogno, rda.contratto_in_scadenza = fabbisogno, contratto
    if contratto is not None:
        rda.scopo = Scopo.RINNOVO
    elif fabbisogno is not None:
        rda.scopo = (
            Scopo.AGGIUNTIVO if _ha_contratti_da_rinnovare(fabbisogno) else Scopo.PRIMO_ACQUISTO
        )
    else:
        rda.scopo = ""
    legato = rda.fabbisogno_della_pratica()
    if legato is not None:
        rda.cluster_id = legato.cluster_id
    rda.full_clean()
    _salva(rda, "Collegamento della pratica")


@transaction.atomic
def collega_contratto(rda: m.RichiestaAcquisto, contratto: m.Contratto) -> None:
    """Il contratto è nato da questa RDA (RDA d'origine)."""
    if contratto.rda_id and contratto.rda_id != rda.pk:
        raise OperazioneNonAmmessa(f"Il contratto ha già la RDA d'origine {contratto.rda}.")
    if contratto.fabbisogno.cluster_id != rda.cluster_id:
        raise OperazioneNonAmmessa("Il contratto è di un altro cluster.")
    contratto.rda = rda
    _salva(contratto, f"Collegato a {rda}", update_fields=["rda"])


@transaction.atomic
def scollega_contratto(contratto: m.Contratto) -> None:
    if contratto.rda_id is None:
        raise OperazioneNonAmmessa("Il contratto non ha una RDA d'origine.")
    rda = contratto.rda
    contratto.rda = None
    _salva(contratto, f"Scollegato da {rda}", update_fields=["rda"])


def contratti_proposti(rda: m.RichiestaAcquisto) -> list[m.Contratto]:
    """Contratti senza RDA d'origine con lo stesso n. RDA scritto (proposte di collegamento)."""
    if not rda.numero_rda:
        return []
    return list(
        m.Contratto.objects.filter(
            archiviato=False, rda__isnull=True, numero_rda=rda.numero_rda
        ).select_related("fornitore", "fabbisogno")
    )


def rda_proposta(contratto: m.Contratto) -> m.RichiestaAcquisto | None:
    """La RDA registrata con il n. RDA scritto sul contratto, se il contratto non ne ha una."""
    if contratto.rda_id or not contratto.numero_rda:
        return None
    return m.RichiestaAcquisto.objects.filter(
        archiviato=False, numero_rda=contratto.numero_rda.strip()
    ).first()


def contratto_in_scadenza_libero(rda: m.RichiestaAcquisto) -> m.Contratto | None:
    """Il predecessore del contratto che nasce dalla RDA: il contratto in scadenza, se è
    ancora senza successore."""
    c = rda.contratto_in_scadenza
    if c is None or adapters.ha_successore(c):
        return None
    return c


def iniziali_contratto(rda: m.RichiestaAcquisto, oggi: datetime.date | None = None) -> dict:
    """Dati proposti per il contratto che nasce dalla RDA (F11.2)."""
    oggi = oggi or timezone.localdate()
    predecessore = contratto_in_scadenza_libero(rda)
    una_tantum = rda.scopo == Scopo.AGGIUNTIVO
    iniziali = {
        "fornitore": rda.fornitore_proposto or (predecessore.fornitore if predecessore else None),
        "descrizione": rda.descrizione,
        "data_emissione": oggi,
        "procedura": predecessore.procedura
        if predecessore
        else m.Procedura.objects.filter(codice="affidamento_diretto").first(),
        "durata_mesi": predecessore.durata_mesi if predecessore else (1 if una_tantum else 12),
        "una_tantum": una_tantum,
        "tipo_acquisto": predecessore.tipo_acquisto
        if predecessore
        else m.Contratto.TipoAcquisto.SERVIZIO,
        "rup": rda.rup,
        "cup": rda.cup,
        "percorso_documenti": rda.percorso_file_server,
        "modalita": m.ModalitaFatturazione.UNA_TANTUM
        if una_tantum
        else m.ModalitaFatturazione.DA_VERIFICARE,
        "periodicita": "",
    }
    if predecessore is not None:
        iniziali["data_inizio"] = adapters.data_fine_effettiva(predecessore) + datetime.timedelta(
            days=1
        )
        prima = predecessore.voci.filter(archiviato=False, proroga__isnull=True).order_by("pk")
        piano = getattr(prima.first(), "piano_fatturazione", None) if prima.exists() else None
        if piano is not None:
            iniziali["modalita"], iniziali["periodicita"] = piano.modalita, piano.periodicita
    elif una_tantum:
        iniziali["data_inizio"] = oggi
    return iniziali


MODALITA_CON_RATE = frozenset({"anticipata", "posticipata", "una_tantum", "consumo"})


@transaction.atomic
def registra_contratto_da_rda(
    rda: m.RichiestaAcquisto,
    dati: dict,
    voci: list[dict],
    *,
    modalita: str,
    periodicita: str = "",
    fabbisogno: m.Fabbisogno | None = None,
) -> m.Contratto:
    """Contratto emesso dal Procurement, registrato dalla RDA (rinnovo o una tantum).

    ``voci``: descrizione, importo fisso, massimale e numero della posizione d'origine, da
    cui prendono natura, conto, centro di costo e WBS. Gli importi sono quelli emessi.
    """
    if fase(rda) == motore.Fase.ANNULLATA:
        raise OperazioneNonAmmessa("La RDA è annullata.")
    fabbisogno = rda.fabbisogno_della_pratica() or fabbisogno
    if fabbisogno is None:
        raise OperazioneNonAmmessa("Indica il fabbisogno del contratto.")
    if not voci:
        raise OperazioneNonAmmessa("Il contratto deve avere almeno una voce.")
    if modalita in ("anticipata", "posticipata") and not periodicita:
        raise OperazioneNonAmmessa("Indica la periodicità della fatturazione.")
    una_tantum = dati.get("una_tantum", False)
    predecessore = None if una_tantum else contratto_in_scadenza_libero(rda)
    contratto = m.Contratto(fabbisogno=fabbisogno, predecessore=predecessore, rda=rda, **dati)
    contratto.full_clean()
    _salva(contratto, f"Registrato da {rda}")
    posizioni = {p.numero: p for p in rda.posizioni.all()}
    for d in voci:
        d = dict(d)
        origine = posizioni.get(d.pop("posizione", None))
        voce = m.VoceContratto(contratto=contratto, **d)
        if origine is not None:
            voce.natura, voce.conto, voce.centro_costo = (
                origine.natura,
                origine.conto,
                origine.centro_costo,
            )
            voce.wbs = origine.wbs if origine.natura == m.Natura.CAPEX else None
        voce.full_clean()
        voce.save()
        m.PianoFatturazione.objects.create(voce=voce, modalita=modalita, periodicita=periodicita)
        if modalita in MODALITA_CON_RATE and contratto.data_inizio:
            from contratti import servizi

            servizi.genera_scadenzario(voce)
    return contratto
