"""Fatture (F11.3, SPEC Rev14–Rev15): presa in carico, referente e contratto proposti,
assegnazione, convalida, documenti SAP, trasferimento, commento per PAC.

Adapter verso il motore puro (``contratti.engine.acquisti``) e servizi che scrivono il
database. I valori proposti (contratto, referente) si calcolano e non si salvano.
"""

import datetime
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

from accounts.roles import ADMIN, WRITE_ROLES, role_of
from contratti import adapters, permessi
from contratti import models as m
from contratti.acquisti import OperazioneNonAmmessa, _salva
from contratti.engine import acquisti as motore
from contratti.engine.date import mese_precedente

Esito = m.Fattura.Esito
Passo = motore.PassoFattura
Tipo = m.DocumentoEsecuzione.Tipo

QS_FATTURE = m.Fattura.objects.select_related(
    "fornitore",
    "conto",
    "wbs",
    "contratto__fornitore",
    "contratto__fabbisogno__cluster",
    "voce__conto",
    "voce__wbs",
    "referente",
).prefetch_related(
    Prefetch(
        "documenti",
        queryset=m.DocumentoEsecuzione.objects.filter(archiviato=False).order_by("data", "pk"),
    )
)


# --- Da modello a motore -------------------------------------------------------------------


def documenti_fattura(fattura: m.Fattura) -> list[motore.Documento]:
    return [
        (d.tipo, d.data, d.data_rilascio is not None)
        for d in fattura.documenti.all()
        if not d.archiviato
    ]


def lavorazione(fattura: m.Fattura) -> motore.LavorazioneFattura:
    return motore.LavorazioneFattura(
        in_carico_dal=fattura.data_presa_in_carico if fattura.referente_id else None,
        assegnata=fattura.contratto_id is not None,
        esito=fattura.esito_convalida,
        convalidata_il=fattura.data_convalida,
        bloccata_fino_al=fattura.bloccata_fino_al,
        fuori_registro=fattura.fuori_registro,
    )


def passo_fattura(fattura: m.Fattura, oggi: datetime.date | None = None) -> Passo | None:
    """Il primo passo che manca; ``None`` se trasferita."""
    return motore.passo_fattura(
        documenti_fattura(fattura),
        oggi or timezone.localdate(),
        fattura.data_trasferimento,
        lavorazione(fattura),
    )


def da_lavorare(fattura: m.Fattura, oggi: datetime.date | None = None) -> bool:
    return motore.fattura_da_lavorare(
        documenti_fattura(fattura),
        oggi or timezone.localdate(),
        fattura.data_trasferimento,
        lavorazione(fattura),
    )


def ferma(fattura: m.Fattura, oggi: datetime.date | None = None) -> bool:
    oggi = oggi or timezone.localdate()
    return motore.fattura_ferma(
        fattura.data_registrazione,
        documenti_fattura(fattura),
        oggi,
        int(adapters.parametro(m.Parametro.Chiave.FATTURA_FERMA_GIORNI, oggi)),
        fattura.data_trasferimento,
        lavorazione(fattura),
    )


def documento_proposto(fattura: m.Fattura) -> str:
    """MAP per un contratto di servizi, MIGO per una fornitura (Rev14)."""
    tipo = fattura.contratto.tipo_acquisto if fattura.contratto_id else ""
    return motore.documento_accettazione(tipo)


def anomalie(fattura: m.Fattura) -> list[str]:
    codici = []
    if not motore.importo_quadra(
        fattura.importo_documento,
        fattura.valore_base,
        fattura.oneri,
        fattura.bollo,
        fattura.iva,
        fattura.altri_importi,
    ):
        codici.append("IMPORTO_NON_QUADRA")
    if fattura.contratto_id and fattura.valore_base is None and not fattura.fuori_registro:
        codici.append("VALORE_BASE_MANCANTE")
    if (
        fattura.contratto_id
        and fattura.valore_base is not None
        and fattura.competenza_dal is None
        and not fattura.fuori_registro
    ):
        codici.append("COMPETENZA_MANCANTE")
    return codici


# --- Contratto proposto --------------------------------------------------------------------


def _in_servizio(contratto: m.Contratto, data: datetime.date) -> bool:
    fine = adapters.data_fine_effettiva(contratto)
    return (
        contratto.data_inizio is not None
        and contratto.data_inizio <= data
        and (fine is None or data <= fine)
    )


def _contratti_vivi(fornitori: Iterable[int]) -> dict[int, list[m.Contratto]]:
    per_fornitore = defaultdict(list)
    qs = (
        m.Contratto.objects.filter(
            fornitore_id__in=set(fornitori), archiviato=False, data_chiusura__isnull=True
        )
        .select_related("fornitore", "fabbisogno__cluster", "procedura")
        .prefetch_related("proroghe")
    )
    for c in qs:
        per_fornitore[c.fornitore_id].append(c)
    return per_fornitore


def contratti_proposti(fatture: list[m.Fattura]) -> dict[int, m.Contratto | None]:
    """Per le fatture senza contratto: l'unico contratto del fornitore non archiviato e non
    chiuso in servizio alla data della fattura (SPEC §7)."""
    senza = [f for f in fatture if not f.contratto_id]
    vivi = _contratti_vivi(f.fornitore_id for f in senza)
    risultato = {}
    for f in senza:
        candidati = [c for c in vivi.get(f.fornitore_id, []) if _in_servizio(c, f.data)]
        risultato[f.pk] = candidati[0] if len(candidati) == 1 else None
    return risultato


def contratto_proposto(fattura: m.Fattura) -> m.Contratto | None:
    if fattura.contratto_id:
        return None
    return contratti_proposti([fattura])[fattura.pk]


def contratto_di_riferimento(fattura: m.Fattura, proposto: m.Contratto | None = None):
    return fattura.contratto if fattura.contratto_id else proposto


# --- Referente proposto (SPEC §4, Rev15) ------------------------------------------------------


def _attivo(utente):
    return utente if utente is not None and utente.is_active else None


def _in_carico(**filtri) -> list[m.Fattura]:
    return list(
        m.Fattura.objects.filter(referente__isnull=False, archiviato=False, **filtri)
        .select_related("referente")
        .order_by("data", "pk")
    )


def _ultimo_per(fatture: list[m.Fattura], chiave) -> dict:
    """Chi ha in carico l'ultima fattura (per data) di ciascuna chiave; solo utenti attivi."""
    risultato = {}
    for f in fatture:
        k = chiave(f)
        if k is not None and f.referente.is_active:
            risultato[k] = f.referente
    return risultato


def referenti_proposti(fatture: list[m.Fattura]) -> dict[int, object]:
    """Referente proposto per ciascuna fattura non in carico: il primo utente attivo tra
    ultima fattura del contratto (assegnato o proposto), referente del fabbisogno, referente
    della RDA d'origine e, senza contratto, ultima fattura del fornitore."""
    da_proporre = [f for f in fatture if not f.referente_id]
    if not da_proporre:
        return {}
    contratti = contratti_proposti(da_proporre)
    riferimento = {f.pk: contratto_di_riferimento(f, contratti.get(f.pk)) for f in da_proporre}
    pk_contratti = {c.pk for c in riferimento.values() if c is not None}
    fornitori = {f.fornitore_id for f in da_proporre}
    in_carico = _in_carico(fornitore_id__in=fornitori)
    # Anche le fatture in carico non ancora abbinate contano per il contratto proposto.
    proposti_altre = contratti_proposti([f for f in in_carico if not f.contratto_id])

    def contratto_effettivo(f):
        c = f.contratto_id or getattr(proposti_altre.get(f.pk), "pk", None)
        return c if c in pk_contratti else None

    per_contratto = _ultimo_per(in_carico, contratto_effettivo)
    per_fornitore = _ultimo_per(in_carico, lambda f: f.fornitore_id)
    dettagli = {
        c.pk: c
        for c in m.Contratto.objects.filter(pk__in=pk_contratti).select_related(
            "fabbisogno__referente_utente", "rda__referente_utente"
        )
    }
    risultato = {}
    for f in da_proporre:
        c = dettagli.get(riferimento[f.pk].pk) if riferimento[f.pk] else None
        if c is not None:
            candidati = [
                per_contratto.get(c.pk),
                _attivo(c.fabbisogno.referente_utente),
                _attivo(c.rda.referente_utente) if c.rda_id else None,
            ]
        else:
            candidati = [per_fornitore.get(f.fornitore_id)]
        risultato[f.pk] = motore.primo_referente(candidati)
    return risultato


def referente_proposto(fattura: m.Fattura):
    return referenti_proposti([fattura]).get(fattura.pk)


# --- Chi può fare cosa (SPEC §4, §8.1) ------------------------------------------------------


def scrive(utente) -> bool:
    return role_of(utente) in WRITE_ROLES


def gestisce(utente) -> bool:
    """Admin o addetto (funzione «Amministrazione acquisti»): riassegna e assegna ai proposti."""
    return role_of(utente) == ADMIN or (scrive(utente) and permessi.e_addetto(utente))


def puo_lavorare(utente, fattura: m.Fattura) -> bool:
    """Modifica la fattura: con il contratto, chi modifica nel suo cluster; senza, chi la ha
    in carico, l'addetto e l'Admin."""
    if not scrive(utente):
        return False
    if fattura.contratto_id:
        return permessi.puo_modificare_fabbisogno(utente, fattura.contratto.fabbisogno)
    return fattura.referente_id == utente.pk or gestisce(utente)


def puo_rilasciare(utente) -> bool:
    """Rilascia su SAP RDA, RdC, MAP e MIGO (``permessi.puo_rilasciare``)."""
    return permessi.puo_rilasciare(utente)


def puo_convalidare(utente, fattura: m.Fattura) -> bool:
    return scrive(utente) and (fattura.referente_id == utente.pk or role_of(utente) == ADMIN)


# --- Presa in carico ------------------------------------------------------------------------


@dataclass
class EsitoMultiplo:
    fatte: list[m.Fattura]
    rifiutate: list[tuple[m.Fattura, str]]


def _bloccate(pks: Iterable[int]) -> list[m.Fattura]:
    return list(m.Fattura.objects.select_for_update().filter(pk__in=list(pks)).order_by("pk"))


def _incarica(fattura: m.Fattura, utente, data: datetime.date, motivo: str) -> None:
    fattura.referente = utente
    fattura.data_presa_in_carico = data
    _salva(fattura, motivo, update_fields=["referente", "data_presa_in_carico"])


@transaction.atomic
def prendi_in_carico(pks: Iterable[int], utente, data=None) -> EsitoMultiplo:
    """Una o più fatture prese in carico dall'utente per sé; quelle già in carico a un altro
    (o fuori registro, o archiviate) si rifiutano."""
    if not scrive(utente):
        raise OperazioneNonAmmessa("Solo Admin ed Editor prendono in carico le fatture.")
    data = data or timezone.localdate()
    esito = EsitoMultiplo([], [])
    for f in _bloccate(pks):
        if f.archiviato or f.fuori_registro:
            esito.rifiutate.append((f, "fuori registro o archiviata"))
        elif f.referente_id == utente.pk:
            esito.rifiutate.append((f, "già in carico a te"))
        elif f.referente_id:
            nome = get_user_model().objects.get(pk=f.referente_id)
            esito.rifiutate.append((f, f"già in carico a {nome}"))
        else:
            _incarica(f, utente, data, "Presa in carico")
            esito.fatte.append(f)
    return esito


@transaction.atomic
def assegna_ai_proposti(pks: Iterable[int], utente, data=None) -> EsitoMultiplo:
    """Ogni fattura non in carico al suo referente proposto (Admin e addetto)."""
    if not gestisce(utente):
        raise OperazioneNonAmmessa("Solo l'Admin e l'addetto assegnano le fatture ad altri.")
    data = data or timezone.localdate()
    fatture = _bloccate(pks)
    proposti = referenti_proposti([f for f in fatture if not f.referente_id])
    esito = EsitoMultiplo([], [])
    for f in fatture:
        if f.archiviato or f.fuori_registro or f.referente_id:
            esito.rifiutate.append((f, "già in carico, fuori registro o archiviata"))
        elif (proposto := proposti.get(f.pk)) is None:
            esito.rifiutate.append((f, "senza referente proposto"))
        else:
            _incarica(f, proposto, data, f"Assegnata a {proposto}")
            esito.fatte.append(f)
    return esito


def lascia(fattura: m.Fattura, utente) -> None:
    """La fattura torna tra quelle da prendere in carico."""
    if not fattura.referente_id:
        raise OperazioneNonAmmessa("La fattura non è in carico a nessuno.")
    if fattura.referente_id != utente.pk and not gestisce(utente):
        raise OperazioneNonAmmessa("Può lasciarla solo chi la ha in carico.")
    fattura.referente = None
    fattura.data_presa_in_carico = None
    _salva(fattura, "Lasciata", update_fields=["referente", "data_presa_in_carico"])


def riassegna(fattura: m.Fattura, nuovo, utente, data=None) -> None:
    if not gestisce(utente):
        raise OperazioneNonAmmessa("Solo l'Admin e l'addetto riassegnano le fatture.")
    if role_of(nuovo) not in WRITE_ROLES:
        raise OperazioneNonAmmessa("Si assegna solo a un Admin o a un Editor.")
    _incarica(fattura, nuovo, data or timezone.localdate(), f"Riassegnata a {nuovo}")


@transaction.atomic
def segna_fuori_registro(pks: Iterable[int], utente, valore: bool = True) -> EsitoMultiplo:
    esito = EsitoMultiplo([], [])
    for f in _bloccate(pks):
        if f.contratto_id and not puo_lavorare(utente, f):
            esito.rifiutate.append((f, "contratto di un cluster che non ti è assegnato"))
            continue
        if not scrive(utente):
            raise OperazioneNonAmmessa("Solo Admin ed Editor.")
        f.fuori_registro = valore
        _salva(
            f, "Fuori registro" if valore else "Di nuovo nel registro",
            update_fields=["fuori_registro"],
        )  # fmt: skip
        esito.fatte.append(f)
    return esito


# --- Assegnazione al contratto, convalida, importi -----------------------------------------


def assegna_contratto(
    fattura: m.Fattura, contratto: m.Contratto | None, voce: m.VoceContratto | None = None
) -> None:
    """Abbina la fattura al contratto (o la scollega, senza documenti SAP collegati)."""
    if contratto is None:
        if fattura.documenti.filter(archiviato=False).exists():
            raise OperazioneNonAmmessa("La fattura ha documenti SAP: non si scollega.")
        fattura.contratto = fattura.voce = fattura.rata = None
        _salva(fattura, "Scollegata dal contratto", update_fields=["contratto", "voce", "rata"])
        return
    if contratto.fornitore_id != fattura.fornitore_id:
        raise OperazioneNonAmmessa("Il contratto è di un altro fornitore.")
    if contratto.data_chiusura is not None:
        raise OperazioneNonAmmessa("Il contratto è chiuso: prima si annulla la chiusura.")
    if contratto.archiviato:
        raise OperazioneNonAmmessa("Il contratto è archiviato.")
    if (
        fattura.contratto_id
        and fattura.contratto_id != contratto.pk
        and fattura.documenti.filter(archiviato=False).exists()
    ):
        raise OperazioneNonAmmessa("La fattura ha documenti SAP di un altro contratto.")
    if voce is not None and voce.contratto_id != contratto.pk:
        raise OperazioneNonAmmessa("La voce è di un altro contratto.")
    if voce is None:
        voci = [v for v in contratto.voci.all() if not v.archiviato]
        voce = voci[0] if len(voci) == 1 else None
    cambia = fattura.contratto_id != contratto.pk
    fattura.contratto = contratto
    fattura.voce = voce
    if cambia:
        fattura.rata = None
    _salva(fattura, f"Assegnata al contratto {contratto}", update_fields=["contratto", "voce",
                                                                         "rata"])  # fmt: skip


def convalida(
    fattura: m.Fattura,
    esito: str,
    nota: str = "",
    bloccata_fino_al: datetime.date | None = None,
    data=None,
) -> None:
    if esito not in Esito.values:
        raise OperazioneNonAmmessa("Esito non valido.")
    if esito in (Esito.NON_CONVALIDABILE, Esito.IN_ATTESA) and not nota.strip():
        raise OperazioneNonAmmessa(
            "Indica nella nota perché non è convalidabile o cosa si attende."
        )
    fattura.esito_convalida = esito
    fattura.nota_convalida = nota.strip()
    fattura.bloccata_fino_al = bloccata_fino_al
    fattura.data_convalida = data or timezone.localdate()
    _salva(
        fattura,
        f"Convalida: {Esito(esito).label}",
        update_fields=["esito_convalida", "nota_convalida", "bloccata_fino_al", "data_convalida"],
    )


def aliquote_iva() -> list[Decimal]:
    """Aliquote IVA attive (tabella di configurazione)."""
    return list(m.AliquotaIVA.objects.filter(attiva=True).values_list("aliquota", flat=True))


def aggiorna_importi(
    fattura: m.Fattura,
    valore_base: Decimal | None,
    oneri: Decimal | None,
    bollo: Decimal | None,
    voce: m.VoceContratto | None = None,
    rata: m.Rata | None = None,
    *,
    iva: Decimal | None = None,
    altri_importi: Decimal | None = None,
    competenza: tuple[datetime.date | None, datetime.date | None] | None = None,
) -> None:
    """Valore base, oneri, bollo, IVA e altri importi (e, se indicata, la competenza: dal, al);
    con il contratto anche voce e rata abbinata (la rata diventa consuntivo e riceve il numero
    di fattura; il suo importo non cambia).

    Senza IVA indicata: se la differenza dall'importo del documento è l'IVA di un'aliquota
    della tabella (SAP riporta spesso l'importo con l'IVA), l'IVA si registra da sola."""
    if iva is None:
        riconosciuta = motore.iva_riconosciuta(
            fattura.importo_documento, valore_base, oneri, bollo, aliquote_iva(), altri_importi
        )
        iva = riconosciuta[1] if riconosciuta else None
    if voce is not None and voce.contratto_id != fattura.contratto_id:
        raise OperazioneNonAmmessa("La voce è di un altro contratto.")
    if rata is not None and rata.piano.voce.contratto_id != fattura.contratto_id:
        raise OperazioneNonAmmessa("La rata è di un altro contratto.")
    if rata is not None and m.Fattura.objects.filter(rata=rata).exclude(pk=fattura.pk).exists():
        raise OperazioneNonAmmessa("La rata è già abbinata a un'altra fattura.")
    fattura.valore_base, fattura.oneri, fattura.bollo = valore_base, oneri, bollo
    fattura.iva = iva
    fattura.altri_importi = altri_importi
    campi = ["valore_base", "oneri", "bollo", "iva", "altri_importi"]
    if competenza is not None:
        fattura.competenza_dal, fattura.competenza_al = competenza
        campi += ["competenza_dal", "competenza_al"]
    if fattura.contratto_id:
        precedente = fattura.rata if fattura.rata_id and fattura.rata_id != getattr(
            rata, "pk", None
        ) else None  # fmt: skip
        fattura.voce, fattura.rata = voce, rata
        campi += ["voce", "rata"]
        with transaction.atomic():
            if precedente is not None and precedente.numero_fattura == fattura.numero:
                precedente.consuntivo, precedente.numero_fattura = False, ""
                _salva(precedente, f"Tolta la fattura {fattura.numero}",
                       update_fields=["consuntivo", "numero_fattura"])  # fmt: skip
            _salva(fattura, "Importi", update_fields=campi)
            if rata is not None and (not rata.consuntivo or rata.numero_fattura != fattura.numero):
                rata.consuntivo, rata.numero_fattura = True, fattura.numero[:40]
                _salva(rata, f"Fattura {fattura.numero}",
                       update_fields=["consuntivo", "numero_fattura"])  # fmt: skip
        return
    _salva(fattura, "Importi", update_fields=campi)


def imputa(
    fattura: m.Fattura,
    conto: m.ContoCoge | None,
    centro_costo: str,
    wbs: m.WBS | None,
) -> None:
    """Imputazione propria della fattura (conto, centro di costo, WBS), se diversa da quella
    della voce; vuota = quella della voce."""
    nuova = (getattr(conto, "pk", None), centro_costo or "", getattr(wbs, "pk", None))
    if (fattura.conto_id, fattura.centro_costo, fattura.wbs_id) == nuova:
        return
    fattura.conto, fattura.centro_costo, fattura.wbs = conto, centro_costo or "", wbs
    _salva(fattura, "Imputazione della fattura", update_fields=["conto", "centro_costo", "wbs"])


def scorpora_iva(
    fattura: m.Fattura,
    aliquota: Decimal,
    oneri: Decimal | None,
    bollo: Decimal | None,
    voce: m.VoceContratto | None = None,
    rata: m.Rata | None = None,
    altri_importi: Decimal | None = None,
    competenza: tuple[datetime.date | None, datetime.date | None] | None = None,
) -> None:
    """Importo del documento con l'IVA: valore base e IVA dallo scorporo dell'aliquota, tolti
    oneri, bollo e altri importi."""
    if aliquota not in aliquote_iva():
        raise OperazioneNonAmmessa("Aliquota IVA non prevista dalla tabella.")
    valore_base, iva = motore.scorporo_iva(
        fattura.importo_documento, oneri, bollo, aliquota, altri_importi
    )
    if valore_base < 0:
        raise OperazioneNonAmmessa("Oneri, bollo e altri importi superano l'importo senza IVA.")
    aggiorna_importi(
        fattura, valore_base, oneri, bollo, voce, rata, iva=iva, altri_importi=altri_importi,
        competenza=competenza,
    )  # fmt: skip


@transaction.atomic
def salva_importi(fattura: m.Fattura, dati: dict, aliquota_scorporo: Decimal | None = None):
    """Il pannello «Importi» (dati del form): importi o scorporo dell'IVA, voce e rata,
    imputazione propria della fattura."""
    competenza = (dati.get("competenza_dal"), dati.get("competenza_al"))
    if (aliquota_scorporo is not None or dati.get("valore_base") is not None) and not all(
        competenza
    ):
        raise OperazioneNonAmmessa(
            "Indica il periodo di competenza della fattura (dal e al): decide l'anno di budget."
        )
    if aliquota_scorporo is not None:
        scorpora_iva(fattura, aliquota_scorporo, dati.get("oneri"), dati.get("bollo"),
                     dati.get("voce"), dati.get("rata"), dati.get("altri_importi"),
                     competenza)  # fmt: skip
    else:
        aggiorna_importi(
            fattura, dati.get("valore_base"), dati.get("oneri"), dati.get("bollo"),
            dati.get("voce"), dati.get("rata"), iva=dati.get("iva"),
            altri_importi=dati.get("altri_importi"), competenza=competenza,
        )  # fmt: skip
    imputa(fattura, dati.get("conto"), dati.get("centro_costo") or "", dati.get("wbs"))


def registra(
    *,
    numero: str,
    data: datetime.date,
    importo_documento: Decimal,
    fornitore: m.Fornitore | None = None,
    contratto: m.Contratto | None = None,
    note: str = "",
) -> m.Fattura:
    """Fattura registrata a mano: come dall'import, da prendere in carico; dal contratto
    entra già abbinata."""
    if contratto is not None and contratto.data_chiusura is not None:
        raise OperazioneNonAmmessa("Il contratto è chiuso: prima si annulla la chiusura.")
    fattura = m.Fattura(
        fornitore=contratto.fornitore if contratto else fornitore,
        contratto=contratto,
        numero=numero.strip(),
        data=data,
        importo_documento=importo_documento,
        note=note,
    )
    # Rev22: competenza di default, il mese prima della data; la corregge il referente.
    fattura.competenza_dal, fattura.competenza_al = mese_precedente(data)
    if contratto is not None:
        voci = [v for v in contratto.voci.all() if not v.archiviato]
        fattura.voce = voci[0] if len(voci) == 1 else None
    fattura.full_clean()
    fattura._change_reason = "Registrata a mano"
    fattura.save()
    return fattura


# --- Documenti SAP e trasferimento (Rev14) ---------------------------------------------------


def registra_documento(
    fattura: m.Fattura, tipo: str, numero: str, data: datetime.date, importo=None
) -> m.DocumentoEsecuzione:
    """RdC, MAP o MIGO della fattura: il documento è del contratto della fattura."""
    if tipo not in (Tipo.ODA, Tipo.MAP, Tipo.MIGO):
        raise OperazioneNonAmmessa("Documento non previsto per la fattura.")
    if not fattura.contratto_id:
        raise OperazioneNonAmmessa("Prima si assegna la fattura al contratto.")
    if fattura.contratto.data_chiusura is not None:
        raise OperazioneNonAmmessa("Il contratto è chiuso: prima si annulla la chiusura.")
    if not numero.strip():
        raise OperazioneNonAmmessa("Indica il numero del documento.")
    if tipo == Tipo.ODA and fattura.documenti.filter(tipo=Tipo.ODA, archiviato=False).exists():
        raise OperazioneNonAmmessa("La fattura ha già la sua RdC (una per fattura).")
    doc = m.DocumentoEsecuzione(
        contratto=fattura.contratto,
        fattura=fattura,
        tipo=tipo,
        numero=numero.strip(),
        data=data,
        importo=importo,
        voce=fattura.voce,
    )
    doc.full_clean()
    doc._change_reason = f"Registrato dalla fattura {fattura.numero}"[:100]
    doc.save()
    return doc


def _documento_modificabile(fattura: m.Fattura, doc: m.DocumentoEsecuzione) -> None:
    if doc.fattura_id != fattura.pk or doc.archiviato:
        raise OperazioneNonAmmessa("Il documento non è di questa fattura.")
    if doc.data_rilascio is not None:
        raise OperazioneNonAmmessa(
            "Il documento è rilasciato su SAP: prima si annulla il rilascio."
        )
    if doc.tipo not in (Tipo.ODA, Tipo.MAP, Tipo.MIGO):
        raise OperazioneNonAmmessa("Documento non previsto per la fattura.")
    if fattura.contratto_id and fattura.contratto.data_chiusura is not None:
        raise OperazioneNonAmmessa("Il contratto è chiuso: prima si annulla la chiusura.")
    if fattura.data_trasferimento is not None:
        raise OperazioneNonAmmessa("La fattura è trasferita: prima si annulla il trasferimento.")


def modifica_documento(
    fattura: m.Fattura, doc: m.DocumentoEsecuzione, tipo: str, numero: str, data: datetime.date
) -> m.DocumentoEsecuzione:
    """Corregge tipo, numero e data di una RdC, MAP o MIGO già registrata."""
    _documento_modificabile(fattura, doc)
    if tipo not in (Tipo.ODA, Tipo.MAP, Tipo.MIGO):
        raise OperazioneNonAmmessa("Documento non previsto per la fattura.")
    if not numero.strip():
        raise OperazioneNonAmmessa("Indica il numero del documento.")
    altra_rdc = (
        fattura.documenti.filter(tipo=Tipo.ODA, archiviato=False).exclude(pk=doc.pk).exists()
    )
    if tipo == Tipo.ODA and altra_rdc:
        raise OperazioneNonAmmessa("La fattura ha già la sua RdC (una per fattura).")
    doc.tipo, doc.numero, doc.data = tipo, numero.strip(), data
    doc.full_clean()
    doc._change_reason = f"Corretto dalla fattura {fattura.numero}"[:100]
    doc.save()
    return doc


def rimuovi_documento(fattura: m.Fattura, doc: m.DocumentoEsecuzione) -> None:
    """Toglie una RdC, MAP o MIGO dalla fattura: si archivia, non si cancella (regola 8)."""
    _documento_modificabile(fattura, doc)
    doc.archiviato = True
    doc._change_reason = f"Rimosso dalla fattura {fattura.numero}"[:100]
    doc.save(update_fields=["archiviato"])


# --- Rilascio su SAP di RdC, MAP e MIGO ------------------------------------------------------

TIPI_DA_RILASCIARE = (Tipo.ODA, Tipo.MAP, Tipo.MIGO)


def documenti_da_rilasciare(tipo: str = "") -> list[m.DocumentoEsecuzione]:
    """RdC, MAP e MIGO registrati e non ancora rilasciati, di fatture da lavorare (non
    trasferite, non fuori registro): la coda dell'addetto al rilascio."""
    qs = m.DocumentoEsecuzione.objects.filter(
        archiviato=False,
        data_rilascio__isnull=True,
        tipo__in=[tipo] if tipo in TIPI_DA_RILASCIARE else TIPI_DA_RILASCIARE,
        fattura__isnull=False,
        fattura__archiviato=False,
        fattura__fuori_registro=False,
        fattura__data_trasferimento__isnull=True,
    ).select_related("fattura__fornitore", "contratto__fornitore", "contratto__fabbisogno__cluster")
    return list(qs.order_by("data", "pk"))


def rilascia_documenti(pks: Iterable[int], utente, data: datetime.date | None = None):
    """Rilascia su SAP i documenti indicati (data e utente). I documenti non rilasciabili
    sono rifiutati con il motivo, gli altri vanno avanti."""
    if not puo_rilasciare(utente):
        raise PermissionDenied("Non sei addetto al rilascio.")
    data = data or timezone.localdate()
    fatte, rifiutate = [], []
    with transaction.atomic():
        documenti = (
            m.DocumentoEsecuzione.objects.select_for_update(of=("self",))
            .select_related("fattura", "contratto")
            .filter(pk__in=list(pks))
            .order_by("pk")
        )
        for d in documenti:
            motivo = _non_rilasciabile(d)
            if motivo:
                rifiutate.append((d, motivo))
                continue
            d.data_rilascio, d.rilasciato_da = data, utente
            d._change_reason = f"Rilasciato su SAP ({d.fattura.numero})"[:100]
            d.save(update_fields=["data_rilascio", "rilasciato_da"])
            fatte.append(d)
    return EsitoDocumenti(fatte, rifiutate)


def _non_rilasciabile(d: m.DocumentoEsecuzione) -> str:
    if d.archiviato or d.tipo not in TIPI_DA_RILASCIARE or d.fattura_id is None:
        return "non è un documento da rilasciare"
    if d.data_rilascio is not None:
        return "è già rilasciato"
    if d.fattura.data_trasferimento is not None:
        return "la fattura è già trasferita"
    if d.contratto.data_chiusura is not None:
        return "il contratto è chiuso"
    return ""


def annulla_rilascio(doc: m.DocumentoEsecuzione, utente) -> None:
    if not puo_rilasciare(utente):
        raise PermissionDenied("Non sei addetto al rilascio.")
    if doc.data_rilascio is None:
        raise OperazioneNonAmmessa("Il documento non è rilasciato.")
    if doc.fattura_id and doc.fattura.data_trasferimento is not None:
        raise OperazioneNonAmmessa("La fattura è trasferita: prima si annulla il trasferimento.")
    doc.data_rilascio = None
    doc.rilasciato_da = None
    doc._change_reason = "Rilascio annullato"
    doc.save(update_fields=["data_rilascio", "rilasciato_da"])


@dataclass
class EsitoDocumenti:
    fatte: list[m.DocumentoEsecuzione]
    rifiutate: list[tuple[m.DocumentoEsecuzione, str]]


def trasferisci(fattura: m.Fattura, utente=None, data=None) -> None:
    """Ultimo passo: la fattura è trasferita per il pagamento (solo data)."""
    if fattura.data_trasferimento is not None:
        raise OperazioneNonAmmessa("La fattura è già trasferita.")
    fattura.data_trasferimento = data or timezone.localdate()
    fattura.trasferita_da = utente
    _salva(fattura, "Trasferita per il pagamento", update_fields=["data_trasferimento",
                                                                    "trasferita_da"])  # fmt: skip


def annulla_trasferimento(fattura: m.Fattura) -> None:
    if fattura.data_trasferimento is None:
        raise OperazioneNonAmmessa("La fattura non è trasferita.")
    fattura.data_trasferimento = None
    fattura.trasferita_da = None
    _salva(fattura, "Trasferimento annullato", update_fields=["data_trasferimento",
                                                               "trasferita_da"])  # fmt: skip


# --- Indicazioni per la validazione e commento per PAC (SPEC §5.9) -------------------------


def _voce_di_riferimento(fattura: m.Fattura) -> m.VoceContratto | None:
    if fattura.voce_id:
        return fattura.voce
    if not fattura.contratto_id:
        return None
    voci = [v for v in fattura.contratto.voci.all() if not v.archiviato]
    return voci[0] if len(voci) == 1 else None


def dati_pac(fattura: m.Fattura) -> motore.DatiPAC:
    documenti = [d for d in fattura.documenti.all() if not d.archiviato]
    rdc = next((d for d in documenti if d.tipo == Tipo.ODA), None)
    accettazione = next((d for d in documenti if d.tipo in (Tipo.MAP, Tipo.MIGO)), None)
    voce = _voce_di_riferimento(fattura)
    wbs = conto = centro_costo = None
    if voce is not None:
        wbs = voce.wbs.codice_wbs if voce.wbs_id else (voce.codice_wbs_importato or None)
        conto = voce.conto.codice if voce.conto_id else None
        centro_costo = voce.centro_costo or None
    # L'imputazione propria della fattura, campo per campo, prevale su quella della voce.
    if fattura.conto_id:
        conto = fattura.conto.codice
    if fattura.centro_costo:
        centro_costo = fattura.centro_costo
    if fattura.wbs_id:
        wbs = fattura.wbs.codice_wbs
    return motore.DatiPAC(
        numero_rdc=rdc.numero if rdc else None,
        accettazione=accettazione.tipo if accettazione else documento_proposto(fattura),
        numero_accettazione=accettazione.numero if accettazione else None,
        centro_costo=centro_costo,
        conto=conto,
        wbs=wbs,
        valore_base=fattura.valore_base,
        oneri=fattura.oneri,
        bollo=fattura.bollo,
    )


def commento_pac(fattura: m.Fattura) -> str:
    return motore.commento_pac(dati_pac(fattura))


def indicazioni_validazione(fattura: m.Fattura) -> str:
    return motore.indicazioni_validazione(dati_pac(fattura))
