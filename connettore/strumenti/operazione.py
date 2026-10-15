"""Scrittura in due passi: anteprima e conferma (SPEC_MCP §8.1).

Un tool di scrittura non scrive: esegue l'operazione dentro una transazione che poi annulla,
ne ricava le modifiche (dai record della storia) e gli effetti calcolati dal motore (date,
alert, previsti, budget), e registra un'``OperazioneMCP`` da confermare. Solo
``conferma_operazione`` la esegue davvero, con lo stesso codice, se nel frattempo niente è
cambiato. Così l'anteprima mostra le conseguenze vere, calcolate con le stesse regole.
"""

import datetime
import hashlib
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.roles import WRITE_ROLES
from connettore import serializza
from connettore.esecuzione import esecuzione
from connettore.models import OperazioneMCP
from contratti import acquisti, adapters, permessi, selettori, servizi
from contratti import models as m
from contratti.engine.budget import valore
from contratti.engine.tipi import Livello
from reports.budget import VISTE, Filtri, calcola_budget

from .base import Contesto, ErroreTool, Strumento

ZERO = Decimal("0.00")
NOMI_VISTE = {
    "consuntivo": "fatturato_stanziato_competenza",
    "cassa": "fatturato",
    "impegno": "ordinato",
    "competenza": "competenza",
}
ERRORI_DI_DOMINIO = (
    servizi.OperazioneNonAmmessa,
    acquisti.OperazioneNonAmmessa,
    servizi.ScadenzarioBloccato,
    ValidationError,
)
ISTRUZIONI = (
    "Nulla è stato ancora modificato. Mostra all'utente modifiche ed effetti e chiedi se "
    "confermare; solo dopo il suo consenso esplicito chiama «conferma_operazione» con "
    "«id_operazione». Se l'utente cambia qualcosa, chiama di nuovo il tool per una nuova "
    "anteprima. Gli oggetti nuovi non hanno ancora un id: lo assegna la conferma, che lo "
    "restituisce."
)
NUOVO = "nuovo (id assegnato alla conferma)"


class ErroreValidazione(ErroreTool):
    """Dati non validi: gli stessi errori del form dell'interfaccia, campo per campo."""

    def __init__(self, errori: dict[str, list[str]]):
        self.errori = errori
        righe = [f"{campo}: {'; '.join(msg)}" for campo, msg in errori.items()]
        super().__init__("Dati non validi (nessuna modifica). " + " | ".join(righe))


def errori_form(*forms) -> dict[str, list[str]]:
    errori: dict[str, list[str]] = {}
    for form in forms:
        for campo, lista in form.errors.items():
            chiave = "generale" if campo == "__all__" else campo
            errori.setdefault(chiave, []).extend(str(e) for e in lista)
    return errori


def valida(*forms) -> None:
    if not all(f.is_valid() for f in forms):
        raise ErroreValidazione(errori_form(*forms))


@dataclass(frozen=True)
class Scrittura:
    """Un'operazione di scrittura: oggetti toccati e applicazione (form e servizi dell'app)."""

    nome: str
    # Oggetti esistenti toccati: permessi per cluster e versioni (concorrenza).
    oggetti: Callable[[dict], list]
    # Esegue l'operazione con i form e i servizi dell'interfaccia; restituisce gli oggetti.
    applica: Callable[[Contesto, dict], dict]
    # I fornitori sono in comune: nessun controllo di cluster (come l'interfaccia).
    senza_cluster: bool = False
    # Permessi propri (RDA, fatture: SPEC_MCP §11.3) al posto del controllo per cluster.
    permesso: Callable[[Contesto, list], None] | None = None
    # Stato del processo d'acquisto degli oggetti toccati (fase, passo, residuo, commento
    # per PAC), calcolato prima e dopo l'operazione: effetti dell'anteprima (F12.2).
    stato: Callable[[Contesto, dict, dict], dict] | None = None


SCRITTURE: dict[str, Scrittura] = {}


def strumento(scrittura: Scrittura, titolo: str, descrizione: str, schema: dict) -> Strumento:
    SCRITTURE[scrittura.nome] = scrittura
    return Strumento(
        nome=scrittura.nome,
        titolo=titolo,
        descrizione=descrizione + " Restituisce un'anteprima da confermare: non modifica nulla.",
        input_schema=schema,
        esegui=lambda ctx, argomenti: anteprima(ctx, scrittura, argomenti),
        annotazioni={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
        ruoli=WRITE_ROLES,
        scrittura=True,
    )


def trova(queryset, pk, nome: str):
    try:
        return queryset.get(pk=pk)
    except ObjectDoesNotExist:
        raise ErroreTool(f"Nessun {nome} con id {pk}.") from None


# --- Permessi e versioni ------------------------------------------------------------------


def _verifica_permessi(ctx: Contesto, scrittura: Scrittura, oggetti: list) -> None:
    if scrittura.senza_cluster:
        return
    if scrittura.permesso is not None:
        scrittura.permesso(ctx, oggetti)
        return
    try:
        for o in oggetti:
            # Il piano di fatturazione appartiene alla sua voce.
            soggetto = o.voce if isinstance(o, m.PianoFatturazione) else o
            permessi.verifica_oggetto(ctx.utente, soggetto)
    except PermissionDenied:
        raise ErroreTool(
            "Non autorizzato: l'oggetto appartiene a un cluster che non puoi modificare."
        ) from None


def _versione(oggetto) -> int | None:
    return oggetto.history.order_by("-history_id").values_list("history_id", flat=True).first()


def _versioni(oggetti: list) -> dict[str, int | None]:
    return {f"{o._meta.label}:{o.pk}": _versione(o) for o in oggetti}


def _impronta(argomenti: dict) -> str:
    return hashlib.sha256(json.dumps(argomenti, sort_keys=True).encode()).hexdigest()


# --- Modifiche ed effetti ------------------------------------------------------------------

CAMPI_ESCLUSI = {"id", "chiave_import"}


def _creati(registrati: list) -> set[tuple[type, int]]:
    """Oggetti creati dall'operazione: nell'anteprima il loro id è provvisorio (la sequenza
    di PostgreSQL non torna indietro con l'annullamento), quindi non si mostra."""
    return {(r.instance_type, r.id) for r in registrati if r.history_type == "+"}


def _valore(campo, valore, creati: set):
    """Un riferimento a un oggetto creato dall'operazione non ha ancora un id."""
    if (campo.many_to_one or campo.one_to_one) and (campo.related_model, valore) in creati:
        return NUOVO
    if isinstance(valore, Decimal) and getattr(campo, "decimal_places", 2) != 2:
        return str(valore.normalize())  # quantità: non sono importi, niente centesimi
    return valore


def _etichetta(record) -> str:
    return f"{record.instance_type._meta.verbose_name}"


def _modifiche(registrati: list, creati: set) -> list[dict]:
    """Dai record della storia creati dall'operazione: cosa si crea, cambia o sostituisce."""
    uscita = []
    for r in registrati:
        modello = r.instance_type
        voce = {"oggetto": _etichetta(r), "id": None if (modello, r.id) in creati else r.id}
        if r.history_type == "+":
            voce["tipo"] = "creato"
            voce["campi"] = {
                f.attname: _valore(f, getattr(r, f.attname), creati)
                for f in modello._meta.fields
                if f.attname not in CAMPI_ESCLUSI and getattr(r, f.attname) not in (None, "")
            }
        elif r.history_type == "~":
            voce["tipo"] = "modificato"
            precedente = r.prev_record
            cambi = r.diff_against(precedente).changes if precedente else []
            voce["campi"] = {
                c.field: {
                    "prima": _valore(modello._meta.get_field(c.field), c.old, set()),
                    "dopo": _valore(modello._meta.get_field(c.field), c.new, creati),
                }
                for c in cambi
                if c.field not in CAMPI_ESCLUSI
            }
        else:
            voce["tipo"] = "sostituito"  # solo rate generate (rigenerazione dello scadenzario)
        uscita.append(voce)
    return uscita


def _fabbisogno_di(record) -> int | None:
    modello = record.instance_type
    try:
        if modello is m.Fabbisogno:
            return record.id
        if modello is m.Contratto:
            return record.fabbisogno_id
        if modello in (m.VoceContratto, m.Proroga, m.OpzioneContratto):
            return m.Contratto.objects.get(pk=record.contratto_id).fabbisogno_id
        if modello is m.PianoFatturazione:
            return m.VoceContratto.objects.get(pk=record.voce_id).contratto.fabbisogno_id
        if modello is m.Rata:
            return m.PianoFatturazione.objects.get(pk=record.piano_id).voce.contratto.fabbisogno_id
        if modello is m.Stanziamento:
            return m.VoceContratto.objects.get(pk=record.voce_id).contratto.fabbisogno_id
        if modello is m.StatoPratica:
            if record.contratto_id:
                return m.Contratto.objects.get(pk=record.contratto_id).fabbisogno_id
            return record.fabbisogno_id
    except ObjectDoesNotExist:
        return None
    return None


def _cluster_toccati(fabbisogni: set[int], registrati: list) -> set[str]:
    """Cluster dei fabbisogni toccati, prima e dopo l'operazione (dentro la transazione).

    Il budget si confronta su questo insieme in tutti e due gli stati: un fabbisogno creato
    dall'operazione non esiste più dopo l'annullamento, e uno spostato di cluster cambia
    cluster tra i due stati.
    """
    cluster = set(
        m.Fabbisogno.objects.filter(pk__in=fabbisogni).values_list("cluster__codice", flat=True)
    )
    for record in registrati:
        if record.instance_type is m.Fabbisogno and record.prev_record is not None:
            cluster.add(record.prev_record.cluster.codice)
    return cluster


def _stato(fabbisogni: set[int], cluster: set[str], oggi: datetime.date) -> dict:
    """Date, alert e previsti dei fabbisogni toccati; budget dei cluster indicati."""
    stato = {"fabbisogni": {}, "budget": {}}
    with adapters.parametri_in_cache():
        for pk in sorted(fabbisogni):
            f = m.Fabbisogno.objects.select_related("cluster").filter(pk=pk).first()
            if f is None:
                continue
            righe = selettori.righe_contratti(
                selettori.contratti_base().filter(fabbisogno=f, archiviato=False), oggi
            )
            previsti = adapters.previsti_fabbisogno(f, adapters.orizzonte_default(oggi))
            stato["fabbisogni"][pk] = {
                "descrizione": f.descrizione,
                "contratti": {
                    r.contratto.pk: {
                        "fine": r.fine,
                        "data_limite": r.data_limite,
                        "alert": r.alert,
                        "pratica": r.stato_pratica_label,
                    }
                    for r in righe
                },
                "previsti": [
                    {
                        "inizio": p.inizio,
                        "fine": p.fine,
                        "probabile": sum(
                            (valore(v, Livello.PROBABILE) for v in p.voci), Decimal("0.00")
                        ),
                    }
                    for p in previsti
                ],
            }
    for codice in sorted(cluster):
        for anno in (oggi.year, oggi.year + 1):
            b = calcola_budget(Filtri(anno=anno, area=(codice,)), oggi)
            for sezione in b.sezioni():
                totali = sezione.totali()["totale"]
                for vista in VISTE:
                    chiave = (codice, anno, sezione.filtri.natura, NOMI_VISTE[vista])
                    stato["budget"][chiave] = totali[vista][Livello.PROBABILE]
    return stato


def _effetti(prima: dict, dopo: dict, creati: set) -> dict:
    fabbisogni = []
    for pk in sorted(set(prima["fabbisogni"]) | set(dopo["fabbisogni"])):
        p, d = prima["fabbisogni"].get(pk), dopo["fabbisogni"].get(pk)
        nuovo = (m.Fabbisogno, pk) in creati
        voce = {"fabbisogno_id": NUOVO if nuovo else pk, "descrizione": (d or p)["descrizione"]}
        if nuovo:
            voce["nuovo"] = True
        contratti = []
        pc, dc = (p or {}).get("contratti", {}), (d or {}).get("contratti", {})
        for c in sorted(set(pc) | set(dc)):
            if pc.get(c) != dc.get(c):
                cid = NUOVO if (m.Contratto, c) in creati else c
                contratti.append({"contratto_id": cid, "prima": pc.get(c), "dopo": dc.get(c)})
        if contratti:
            voce["contratti"] = contratti
        if (p or {}).get("previsti") != (d or {}).get("previsti"):
            voce["previsti"] = {"prima": (p or {}).get("previsti"), "dopo": d.get("previsti")}
        fabbisogni.append(voce)
    budget = [
        {
            "cluster": k[0],
            "anno": k[1],
            "natura": k[2],
            "vista": k[3],
            "prima": prima["budget"].get(k, ZERO),
            "dopo": dopo["budget"].get(k, ZERO),
            "differenza": dopo["budget"].get(k, ZERO) - prima["budget"].get(k, ZERO),
        }
        for k in sorted(set(prima["budget"]) | set(dopo["budget"]))
        if prima["budget"].get(k, ZERO) != dopo["budget"].get(k, ZERO)
    ]
    return {
        "fabbisogni": fabbisogni,
        "budget_livello_probabile": budget,
    }


# --- Anteprima e conferma --------------------------------------------------------------------


def _esiste(oggetto: dict) -> bool:
    modello = apps.get_model("contratti", oggetto["tipo"])
    return modello.objects.filter(pk=oggetto["id"]).exists()


def _minuti(oggi: datetime.date) -> int:
    return int(adapters.parametro(m.Parametro.Chiave.MCP_MINUTI_OPERAZIONE, oggi))


def _messaggio(exc: Exception) -> str:
    return "; ".join(getattr(exc, "messages", None) or [str(exc)])


def anteprima(ctx: Contesto, scrittura: Scrittura, argomenti: dict) -> dict:
    oggetti = scrittura.oggetti(argomenti)
    _verifica_permessi(ctx, scrittura, oggetti)
    try:
        with transaction.atomic():
            with esecuzione(ctx.utente, f"MCP {scrittura.nome} anteprima") as es:
                risultato = scrittura.applica(ctx, argomenti)
            fabbisogni = {f for f in map(_fabbisogno_di, es.registrati) if f}
            cluster = _cluster_toccati(fabbisogni, es.registrati)
            dopo = _stato(fabbisogni, cluster, ctx.oggi)
            creati = _creati(es.registrati)
            modifiche = _modifiche(es.registrati, creati)
            processo_dopo = scrittura.stato(ctx, argomenti, risultato) if scrittura.stato else None
            transaction.set_rollback(True)  # l'anteprima non scrive niente
    except ERRORI_DI_DOMINIO as exc:
        raise ErroreTool(f"Operazione non ammessa (nessuna modifica): {_messaggio(exc)}") from None
    prima = _stato(fabbisogni, cluster, ctx.oggi)
    effetti = _effetti(prima, dopo, creati)
    if scrittura.stato is not None:
        effetti["processo_acquisto"] = {
            "prima": scrittura.stato(ctx, argomenti, risultato),
            "dopo": processo_dopo,
        }
    adesso = timezone.now()
    # Solo gli oggetti già esistenti: quelli creati nell'anteprima non esistono ancora.
    esistenti = [o for o in risultato.get("oggetti", []) if _esiste(o)]
    contenuto = serializza.in_json(
        {
            "tool": scrittura.nome,
            "argomenti": argomenti,
            "modifiche": modifiche,
            "effetti": effetti,
            "oggetti_esistenti": esistenti,
            # Operazioni su più fatture (D15): quelle che passano e quelle rifiutate.
            **{k: risultato[k] for k in ("esito_per_fattura", "avvisi") if risultato.get(k)},
        }
    )
    op = OperazioneMCP.objects.create(
        codice=secrets.token_urlsafe(18),
        utente=ctx.utente,
        client_id=ctx.client_id,
        tool=scrittura.nome,
        argomenti=argomenti,
        versioni=_versioni(oggetti),
        anteprima=contenuto | {"impronta": _impronta(argomenti)},
        scade_il=adesso + datetime.timedelta(minutes=_minuti(ctx.oggi)),
    )
    return {
        "alla_data": ctx.oggi,
        "id_operazione": op.codice,
        "scade_alle": timezone.localtime(op.scade_il),
        **contenuto,
        "istruzioni": ISTRUZIONI,
    }


def _rifiuto(ctx: Contesto, op: OperazioneMCP, scrittura: Scrittura) -> str | None:
    if timezone.now() > op.scade_il:
        return "Anteprima scaduta: chiedere una nuova anteprima."
    if op.anteprima.get("impronta") != _impronta(op.argomenti):
        return "Argomenti alterati: chiedere una nuova anteprima."
    oggetti = scrittura.oggetti(op.argomenti)
    _verifica_permessi(ctx, scrittura, oggetti)
    if _versioni(oggetti) != op.versioni:
        return "Gli oggetti sono stati modificati dopo l'anteprima: chiedere una nuova anteprima."
    return None


def conferma(ctx: Contesto, argomenti: dict) -> dict:
    codice = argomenti["id_operazione"]
    rifiuto = None
    with transaction.atomic():
        op = OperazioneMCP.objects.select_for_update().filter(codice=codice).first()
        if op is None or op.utente_id != ctx.utente.pk:
            raise ErroreTool("Operazione inesistente: chiedere una nuova anteprima.")
        if op.stato == OperazioneMCP.Stato.CONFERMATA:
            return op.esito | {"gia_confermata": True}  # idempotente: niente di rieseguito
        if op.stato == OperazioneMCP.Stato.RIFIUTATA:
            raise ErroreTool(f"Operazione già rifiutata: {op.messaggio}")
        scrittura = SCRITTURE[op.tool]
        try:
            rifiuto = _rifiuto(ctx, op, scrittura)
        except ErroreTool as exc:
            rifiuto = str(exc)
        if rifiuto is None:
            try:
                motivo = f"MCP {op.tool} {op.codice[:8]}"
                with transaction.atomic(), esecuzione(ctx.utente, motivo):
                    risultato = scrittura.applica(ctx, op.argomenti)
            except (ErroreTool, *ERRORI_DI_DOMINIO) as exc:
                rifiuto = f"Operazione non eseguita: {_messaggio(exc)}"
        if rifiuto is None:
            op.stato = OperazioneMCP.Stato.CONFERMATA
            op.confermata_il = timezone.now()
            op.esito = serializza.in_json(
                {"esito": "eseguita", "tool": op.tool, "id_operazione": op.codice} | risultato
            )
        else:
            op.stato = OperazioneMCP.Stato.RIFIUTATA
            op.messaggio = rifiuto[:300]
        op.save()
    if rifiuto:
        raise ErroreTool(rifiuto)
    return op.esito


CONFERMA = Strumento(
    nome="conferma_operazione",
    titolo="Conferma un'operazione",
    descrizione=(
        "Esegue davvero l'operazione di cui un tool di scrittura ha mostrato l'anteprima. Da "
        "chiamare solo dopo che l'utente ha visto l'anteprima e ha confermato esplicitamente. "
        "Rifiutata se l'anteprima è scaduta o se nel frattempo gli oggetti sono cambiati."
    ),
    input_schema={
        "type": "object",
        "properties": {"id_operazione": {"type": "string", "minLength": 10, "maxLength": 40}},
        "required": ["id_operazione"],
        "additionalProperties": False,
    },
    esegui=conferma,
    annotazioni={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True},
    ruoli=WRITE_ROLES,
    scrittura=True,
)
