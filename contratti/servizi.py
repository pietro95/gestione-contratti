"""Operazioni che scrivono sul database usando il motore."""

import datetime
from dataclasses import dataclass, field

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
            # Il rinnovo prende la classificazione decisa per i rinnovi, se c'è (F9.2).
            classe = adapters.classificazione_prevista(predecessore.fabbisogno, origine)
            voce.natura = classe.natura
            voce.conto = voce.conto or classe.conto
            voce.wbs = voce.wbs or classe.wbs
            voce.centro_costo = voce.centro_costo or origine.centro_costo
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
        # Se le voci del contratto hanno una sola natura e WBS, la proroga le eredita (F9.2).
        classi = {
            (v.natura, v.wbs_id, v.conto_id)
            for v in contratto.voci.filter(archiviato=False, proroga__isnull=True)
        }
        if len(classi) == 1:
            natura, wbs_id, conto_id = classi.pop()
            voce.setdefault("natura", natura)
            voce.setdefault("wbs_id", wbs_id)
            if not voce.get("conto"):
                voce.setdefault("conto_id", conto_id)
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


# --- Spostamento di contratti e accorpamento di fabbisogni (F8) -------------------------
#
# Il fabbisogno di un contratto si cambia solo da qui: la catena dei rinnovi (predecessore
# → successore) deve restare dentro un solo fabbisogno (SPEC §4).

MOTIVO_MAX = 100  # history_change_reason di simple-history


def _motivo(testo: str) -> str:
    return testo if len(testo) <= MOTIVO_MAX else testo[: MOTIVO_MAX - 1] + "…"


def _salva(oggetto, motivo: str, **kw) -> None:
    oggetto._change_reason = _motivo(motivo)
    oggetto.save(**kw)


def successore_di(contratto: m.Contratto) -> m.Contratto | None:
    return m.Contratto.objects.filter(predecessore=contratto).first()


def contratto_e_successivi(contratto: m.Contratto) -> list[m.Contratto]:
    """Il contratto e i suoi successori, nell'ordine della catena."""
    catena, visti, c = [], set(), contratto
    while c is not None and c.pk not in visti:
        catena.append(c)
        visti.add(c.pk)
        c = successore_di(c)
    return catena


def _ultimo_prima(candidati, inizio):
    """Il candidato che finisce per ultimo prima dell'inizio: il predecessore naturale."""
    if inizio is None:
        return None
    validi = [
        (fine, c)
        for c in candidati
        if (fine := adapters.data_fine_effettiva(c)) is not None and fine < inizio
    ]
    return max(validi, key=lambda x: (x[0], x[1].pk))[1] if validi else None


@dataclass
class AnteprimaSpostamento:
    contratti: list[m.Contratto]  # da spostare, nell'ordine della catena
    predecessore_origine: m.Contratto | None
    successore_origine: m.Contratto | None  # resta nell'origine e si ricollega
    candidati: list[m.Contratto]  # possibili predecessori nella destinazione
    proposto: m.Contratto | None
    avvisi: list[str]


def anteprima_spostamento(
    contratto: m.Contratto, destinazione: m.Fabbisogno, *, con_successivi: bool
) -> AnteprimaSpostamento:
    if destinazione.pk == contratto.fabbisogno_id:
        raise OperazioneNonAmmessa("Il contratto è già in questo fabbisogno.")
    if destinazione.archiviato:
        raise OperazioneNonAmmessa("Il fabbisogno di destinazione è archiviato.")
    spostati = contratto_e_successivi(contratto) if con_successivi else [contratto]
    successore = None if con_successivi else successore_di(contratto)
    candidati = list(
        destinazione.contratti.filter(archiviato=False, successore__isnull=True)
        .select_related("procedura", "fornitore")
        .prefetch_related("proroghe")
        .order_by("data_inizio", "pk")
    )
    avvisi = []
    if destinazione.previsto_data_avvio and not destinazione.contratti.exists():
        avvisi.append(
            "Il fabbisogno di destinazione ha un previsto manuale: con i contratti spostati "
            "i rinnovi previsti partiranno da questi."
        )
    if destinazione.stati_pratica.exists() and not destinazione.contratti.exists():
        avvisi.append(
            "Il fabbisogno di destinazione ha una pratica da fabbisogno nuovo: resta nello "
            "storico, la pratica di rinnovo seguirà i contratti."
        )
    rimasti = contratto.fabbisogno.contratti.exclude(pk__in=[c.pk for c in spostati])
    if not rimasti.filter(archiviato=False).exists():
        avvisi.append(
            f"«{contratto.fabbisogno.descrizione}» resterà senza contratti: archivialo se "
            "non serve più."
        )
    return AnteprimaSpostamento(
        contratti=spostati,
        predecessore_origine=contratto.predecessore,
        successore_origine=successore,
        candidati=candidati,
        proposto=_ultimo_prima(candidati, contratto.data_inizio),
        avvisi=avvisi,
    )


@transaction.atomic
def sposta_contratto(
    contratto: m.Contratto,
    destinazione: m.Fabbisogno,
    *,
    con_successivi: bool,
    predecessore: m.Contratto | None = None,
) -> AnteprimaSpostamento:
    """Sposta il contratto (e, se richiesto, i successori) in un altro fabbisogno.

    Nell'origine la catena si richiude (P → C → S diventa P → S); nella destinazione il
    contratto si collega al predecessore scelto, o a nessuno.
    """
    a = anteprima_spostamento(contratto, destinazione, con_successivi=con_successivi)
    if predecessore is not None and predecessore.pk not in {c.pk for c in a.candidati}:
        raise OperazioneNonAmmessa(
            "Il predecessore deve essere un contratto del fabbisogno di destinazione senza "
            "successore."
        )
    origine = contratto.fabbisogno
    motivo = f"Spostato da «{origine.descrizione}» a «{destinazione.descrizione}»"
    p, s = a.predecessore_origine, a.successore_origine
    # Prima si sciolgono i legami: ogni contratto ha al massimo un successore.
    if s is not None:
        s.predecessore = None
        _salva(s, "Catena ricucita dopo uno spostamento", update_fields=["predecessore"])
    # In ordine di catena: ogni successore si verifica dopo che il suo predecessore è
    # già nella destinazione. clean() controlla solo la regola della catena: i dati
    # importati possono avere altri campi da completare, e non bloccano lo spostamento.
    for c in a.contratti:
        c.fabbisogno = destinazione
        if c.pk == contratto.pk:
            c.predecessore = predecessore
        c.clean()
        _salva(c, motivo, update_fields=["fabbisogno", "predecessore"])
    if s is not None and p is not None:
        s.predecessore = p
        s.clean()
        _salva(s, "Catena ricucita dopo uno spostamento", update_fields=["predecessore"])
    return a


# --- Contratti doppi -------------------------------------------------------------------
#
# Lo stesso contratto registrato due volte (import ripetuto, inserimento a mano e import):
# si tiene quello con più dati e l'altro si archivia, con la sua storia.


def _chiave_doppione(c: m.Contratto) -> tuple | None:
    from contratti.importer.normalizza import chiave_nome

    if c.data_inizio is None:
        return None
    if c.numero_contratto:
        return ("n", c.numero_contratto, c.data_inizio)
    if c.cig:
        return ("c", c.cig, c.data_inizio)
    return (
        "d",
        chiave_nome(c.fornitore.ragione_sociale),
        chiave_nome(c.descrizione),
        c.data_inizio,
        c.durata_mesi,
    )


def _peso(c: m.Contratto) -> tuple:
    """Quanto lavoro c'è su un contratto: si tiene quello con più dati inseriti."""
    voci = [v for v in c.voci.all() if not v.archiviato]
    piani = sum(
        1
        for v in voci
        if getattr(v, "piano_fatturazione", None) is not None
        and v.piano_fatturazione.modalita != m.ModalitaFatturazione.DA_VERIFICARE
    )
    rate = sum(
        v.piano_fatturazione.rate.count()
        for v in voci
        if getattr(v, "piano_fatturazione", None) is not None
    )
    return (piani, rate, c.stati_pratica.count(), bool(c.data_emissione), -c.pk)


def doppioni(contratti) -> list[tuple[m.Contratto, m.Contratto]]:
    """Coppie (da tenere, doppione) tra i contratti attivi dati."""
    gruppi: dict[tuple, list[m.Contratto]] = {}
    for c in contratti:
        if c.archiviato:
            continue
        chiave = _chiave_doppione(c)
        if chiave is not None:
            gruppi.setdefault(chiave, []).append(c)
    coppie = []
    for gruppo in gruppi.values():
        if len(gruppo) < 2:
            continue
        gruppo.sort(key=_peso, reverse=True)
        coppie += [(gruppo[0], altro) for altro in gruppo[1:]]
    return coppie


def _qs_doppioni(fabbisogni):
    return (
        m.Contratto.objects.filter(fabbisogno__in=fabbisogni, archiviato=False)
        .select_related("fornitore", "procedura", "fabbisogno")
        .prefetch_related("voci__piano_fatturazione__rate", "stati_pratica", "proroghe")
        .order_by("pk")
    )


def doppioni_del_fabbisogno(f: m.Fabbisogno) -> list[tuple[m.Contratto, m.Contratto]]:
    return doppioni(_qs_doppioni([f]))


def _archivia_doppione(tenuto: m.Contratto, doppione: m.Contratto, motivo: str) -> None:
    """Archivia il doppione; la catena dei rinnovi passa al contratto tenuto."""
    tenuto.refresh_from_db()
    doppione.refresh_from_db()
    successore = successore_di(doppione)
    if successore is not None and successore_di(tenuto) is None and successore != tenuto:
        successore.predecessore = None
        _salva(successore, motivo, update_fields=["predecessore"])
    predecessore = doppione.predecessore
    doppione.predecessore = None
    doppione.archiviato = True
    _salva(doppione, motivo, update_fields=["predecessore", "archiviato"])
    if predecessore is not None and tenuto.predecessore_id is None and predecessore != tenuto:
        tenuto.predecessore = predecessore
        tenuto.clean()
        _salva(tenuto, motivo, update_fields=["predecessore"])
    if successore is not None and successore.predecessore_id is None and successore != tenuto:
        successore.predecessore = tenuto
        successore.clean()
        _salva(successore, motivo, update_fields=["predecessore"])


@transaction.atomic
def unisci_doppioni(f: m.Fabbisogno, coppie: list[tuple[int, int]]) -> int:
    """Archivia i doppioni confermati (tra quelli rilevati) del fabbisogno."""
    rilevate = {(t.pk, d.pk): (t, d) for t, d in doppioni_del_fabbisogno(f)}
    if any(tuple(c) not in rilevate for c in coppie):
        raise OperazioneNonAmmessa("Coppia non tra i doppioni rilevati.")
    for coppia in coppie:
        tenuto, doppione = rilevate[tuple(coppia)]
        _archivia_doppione(tenuto, doppione, f"Doppione di #{tenuto.pk}, archiviato")
    return len(coppie)


@dataclass
class AnteprimaAccorpamento:
    origine: m.Fabbisogno
    destinazione: m.Fabbisogno
    contratti: list[m.Contratto]  # dell'origine, che passano alla destinazione
    collegamenti: list[tuple[m.Contratto, m.Contratto]]  # (predecessore, successore) proposti
    conflitto_previsto: bool
    conflitto_pratica: bool
    avvisi: list[str]
    # Stesso contratto registrato due volte: (da tenere, doppione da archiviare).
    doppioni: list[tuple[m.Contratto, m.Contratto]] = field(default_factory=list)


def _ha_previsto(f: m.Fabbisogno) -> bool:
    return bool(f.previsto_data_avvio or f.stima_prossimo_importo is not None)


UN_GIORNO = datetime.timedelta(days=1)


def _distanza(fine: datetime.date, inizio: datetime.date) -> int:
    """Giorni tra il giorno dopo la fine e l'inizio del rinnovo (0 = rinnovo a ridosso)."""
    return abs((inizio - (fine + UN_GIORNO)).days)


def proponi_collegamenti(contratti) -> tuple[list[tuple[m.Contratto, m.Contratto]], list[str]]:
    """Catene dei rinnovi interrotte da ricucire: coppie (predecessore, successore) e avvisi.

    Per ogni contratto senza successore si propone il contratto senza predecessore che
    inizia dopo di lui e finisce dopo di lui, con l'inizio più vicino al giorno dopo la sua
    fine: il rinnovo può anche partire prima della scadenza (periodi sovrapposti). Ogni
    contratto si usa una volta sola, prima le coppie più vicine.
    """
    attivi = [c for c in contratti if not c.archiviato and c.data_inizio is not None]
    ultimi = [c for c in attivi if not hasattr(c, "successore")]
    primi = [c for c in attivi if c.predecessore_id is None]
    fini = {c.pk: adapters.data_fine_effettiva(c) for c in attivi}
    candidate = [
        (_distanza(fini[u.pk], p.data_inizio), u.pk, p.pk, u, p)
        for u in ultimi
        for p in primi
        if p.pk != u.pk
        and fini[u.pk] is not None
        and u.data_inizio < p.data_inizio
        and (fini[p.pk] is None or fini[p.pk] > fini[u.pk])
    ]
    coppie, usati_u, usati_p = [], set(), set()
    for *_, u, p in sorted(candidate, key=lambda x: x[:3]):
        if u.pk in usati_u or p.pk in usati_p:
            continue
        coppie.append((u, p))
        usati_u.add(u.pk)
        usati_p.add(p.pk)
    avvisi = []
    for u, p in coppie:
        if p.data_inizio <= fini[u.pk]:
            avvisi.append(
                f"{p} inizia il {p.data_inizio:%d/%m/%Y}, prima della fine di {u} "
                f"({fini[u.pk]:%d/%m/%Y}): periodi sovrapposti. Verifica che sia il rinnovo."
            )
    # Contratto finito senza successore mentre il rinnovo ha già un altro predecessore.
    for u in ultimi:
        fine = fini[u.pk]
        if u.pk in usati_u or fine is None:
            continue
        for c in attivi:
            if (
                c.pk != u.pk
                and c.predecessore_id is not None
                and u.data_inizio < c.data_inizio <= fine + UN_GIORNO
            ):
                avvisi.append(
                    f"{u} finisce il {fine:%d/%m/%Y} senza successore; {c}, che inizia il "
                    f"{c.data_inizio:%d/%m/%Y}, è già il rinnovo di un altro contratto. "
                    "Nessun collegamento proposto: verifica."
                )
                break
    return sorted(coppie, key=lambda x: (x[1].data_inizio, x[1].pk)), avvisi


def candidati_rinnovo(contratto: m.Contratto) -> list[m.Contratto]:
    """Contratti del fabbisogno che si possono collegare a mano come rinnovo del contratto.

    Senza predecessore, non archiviati, con inizio successivo a quello del contratto; per
    primi quelli che iniziano più vicino al giorno dopo la sua fine.
    """
    if contratto.data_inizio is None or hasattr(contratto, "successore"):
        return []
    catena = {c.pk for c in contratto_e_predecessori(contratto)}
    candidati = [
        c
        for c in _qs_collegamenti([contratto.fabbisogno_id]).filter(
            predecessore__isnull=True, data_inizio__gt=contratto.data_inizio
        )
        if c.pk not in catena
    ]
    fine = adapters.data_fine_effettiva(contratto)
    return sorted(candidati, key=lambda c: (_distanza(fine, c.data_inizio), c.pk))


def contratto_e_predecessori(contratto: m.Contratto) -> list[m.Contratto]:
    catena, visti, c = [], set(), contratto
    while c is not None and c.pk not in visti:
        catena.append(c)
        visti.add(c.pk)
        c = c.predecessore
    return catena


@transaction.atomic
def collega_rinnovo(predecessore: m.Contratto, successore: m.Contratto) -> None:
    """Collega a mano il successore come rinnovo del predecessore (stesso fabbisogno)."""
    if successore.pk not in {c.pk for c in candidati_rinnovo(predecessore)}:
        raise OperazioneNonAmmessa(
            "Il rinnovo deve essere un contratto dello stesso fabbisogno, senza predecessore, "
            "che inizia dopo questo; e questo non deve avere già un successore."
        )
    _collega(predecessore, successore, f"Collegato a mano come rinnovo di #{predecessore.pk}")


@transaction.atomic
def scollega_predecessore(contratto: m.Contratto) -> m.Contratto:
    """Toglie il collegamento al predecessore (es. collegamento sbagliato)."""
    contratto.refresh_from_db()
    predecessore = contratto.predecessore
    if predecessore is None:
        raise OperazioneNonAmmessa("Il contratto non ha un predecessore.")
    contratto.predecessore = None
    _salva(
        contratto, f"Scollegato dal predecessore #{predecessore.pk}", update_fields=["predecessore"]
    )
    return predecessore


def collegamenti_del_fabbisogno(f: m.Fabbisogno) -> list[tuple[m.Contratto, m.Contratto]]:
    """Catene interrotte nel fabbisogno, escluse quelle già segnalate come doppioni."""
    da_archiviare = {d.pk for _, d in doppioni_del_fabbisogno(f)}
    coppie, _ = proponi_collegamenti(_qs_collegamenti([f]).exclude(pk__in=da_archiviare))
    return coppie


def _qs_collegamenti(fabbisogni):
    return (
        m.Contratto.objects.filter(fabbisogno__in=fabbisogni, archiviato=False)
        .exclude(data_inizio__isnull=True)
        .select_related("procedura", "fornitore", "fabbisogno", "successore")
        .prefetch_related("proroghe")
        .order_by("data_inizio", "pk")
    )


def _collega(predecessore: m.Contratto, successore: m.Contratto, motivo: str) -> None:
    # Ricaricati: in memoria possono avere il fabbisogno di prima di un accorpamento.
    predecessore.refresh_from_db()
    successore.refresh_from_db()
    successore.predecessore = predecessore
    successore.clean()
    _salva(successore, motivo, update_fields=["predecessore"])


@transaction.atomic
def collega_contratti(f: m.Fabbisogno, coppie: list[tuple[int, int]]) -> int:
    """Ricuce le catene interrotte confermate (tra quelle proposte) del fabbisogno."""
    proposte = {(p.pk, s.pk): (p, s) for p, s in collegamenti_del_fabbisogno(f)}
    if not coppie or any(tuple(c) not in proposte for c in coppie):
        raise OperazioneNonAmmessa("Collegamento non tra quelli proposti.")
    for coppia in coppie:
        predecessore, successore = proposte[tuple(coppia)]
        _collega(predecessore, successore, "Catena dei rinnovi ricucita")
    return len(coppie)


def anteprima_accorpamento(
    origine: m.Fabbisogno, destinazione: m.Fabbisogno
) -> AnteprimaAccorpamento:
    if origine.pk == destinazione.pk:
        raise OperazioneNonAmmessa("Scegli un fabbisogno diverso.")
    if destinazione.archiviato or origine.archiviato:
        raise OperazioneNonAmmessa("Non si accorpa un fabbisogno archiviato.")
    coppie = doppioni(_qs_doppioni([origine, destinazione]))
    da_archiviare = {d.pk for _, d in coppie}
    collegamenti, avvisi = proponi_collegamenti(
        _qs_collegamenti([origine, destinazione]).exclude(pk__in=da_archiviare)
    )
    for campo, etichetta in (
        ("cluster_id", "Cluster diverso"),
        ("categoria_id", "Categoria diversa"),
        ("decisione", "Decisione diversa"),
        ("natura_previsti", "Natura dei rinnovi diversa"),
        ("conto_previsti_id", "Conto dei rinnovi diverso"),
    ):
        if getattr(origine, campo) != getattr(destinazione, campo):
            avvisi.append(f"{etichetta}: resta il valore di «{destinazione.descrizione}».")
    return AnteprimaAccorpamento(
        origine=origine,
        destinazione=destinazione,
        contratti=list(origine.contratti.order_by("data_inizio", "pk")),
        collegamenti=collegamenti,
        conflitto_previsto=_ha_previsto(origine) and _ha_previsto(destinazione),
        conflitto_pratica=origine.stati_pratica.exists() and destinazione.stati_pratica.exists(),
        avvisi=avvisi,
        doppioni=coppie,
    )


CAMPI_PREVISTO = (
    "stima_prossimo_importo",
    "previsto_data_avvio",
    "previsto_durata_mesi",
    "previsto_procedura",
    "previsto_modalita",
    "previsto_periodicita",
)


@transaction.atomic
def accorpa_fabbisogni(
    origine: m.Fabbisogno,
    destinazione: m.Fabbisogno,
    *,
    collegamenti: list[tuple[int, int]] = (),
    doppioni_confermati: list[tuple[int, int]] | None = None,
    previsto_da_origine: bool = False,
    pratica_da_origine: bool = False,
) -> AnteprimaAccorpamento:
    """Tutti i contratti dell'origine passano alla destinazione; l'origine si archivia.

    ``collegamenti``: coppie (predecessore, successore) confermate tra quelle proposte.
    ``doppioni_confermati``: coppie (da tenere, doppione) da unire; ``None`` = tutte quelle
    rilevate. Il doppione si archivia e la sua catena passa al contratto tenuto.
    Previsto manuale e pratica da fabbisogno nuovo: vale quello della destinazione, salvo
    scelta contraria; se la destinazione non li ha, si prendono dall'origine.
    """
    a = anteprima_accorpamento(origine, destinazione)
    proposti = {(p.pk, s.pk): (p, s) for p, s in a.collegamenti}
    if any(tuple(c) not in proposti for c in collegamenti):
        raise OperazioneNonAmmessa("Collegamento non tra quelli proposti.")
    rilevati = {(t.pk, d.pk): (t, d) for t, d in a.doppioni}
    if doppioni_confermati is None:
        doppioni_confermati = list(rilevati)
    if any(tuple(c) not in rilevati for c in doppioni_confermati):
        raise OperazioneNonAmmessa("Coppia non tra i doppioni rilevati.")
    motivo = f"Accorpato «{origine.descrizione}» in «{destinazione.descrizione}»"
    for c in a.contratti:
        c.fabbisogno = destinazione
        _salva(c, motivo, update_fields=["fabbisogno"])
    for coppia in doppioni_confermati:
        tenuto, doppione = rilevati[tuple(coppia)]
        _archivia_doppione(tenuto, doppione, f"Doppione di #{tenuto.pk}, archiviato ({motivo})")
    for coppia in collegamenti:
        _collega(*proposti[tuple(coppia)], motivo)

    if _ha_previsto(origine) and (previsto_da_origine or not _ha_previsto(destinazione)):
        for campo in CAMPI_PREVISTO:
            setattr(destinazione, campo, getattr(origine, campo))
        _salva(destinazione, motivo)
    pratica_origine = list(origine.stati_pratica.all())
    pratica_destinazione = list(destinazione.stati_pratica.all())
    if pratica_origine and (pratica_da_origine or not pratica_destinazione):
        # Si scambiano: la pratica scelta passa alla destinazione, l'altra resta nello
        # storico del fabbisogno archiviato. Nessun passaggio si cancella.
        for passaggio in pratica_destinazione:
            passaggio.fabbisogno = origine
            _salva(passaggio, motivo, update_fields=["fabbisogno"])
        for passaggio in pratica_origine:
            passaggio.fabbisogno = destinazione
            _salva(passaggio, motivo, update_fields=["fabbisogno"])
    origine.archiviato = True
    _salva(origine, motivo, update_fields=["archiviato"])
    return a
