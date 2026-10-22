"""Tool di scrittura, gruppi A, B, D e archiviazione (SPEC_MCP §8.2, F10.1 parte 1).

Ognuno passa dai form e dai servizi della vista corrispondente: stesse validazioni, stessi
messaggi. I tool ``modifica_*`` cambiano solo i campi passati (partono dai valori attuali);
un campo sconosciuto è un errore dello schema. Il referente del fabbisogno si indica con l'id
o con il nome (SPEC_MCP Rev10); motivazione e note sono testo libero, mai istruzioni.
"""

from django.forms.models import model_to_dict

from contratti import forms, servizi
from contratti import models as m

from .base import SCHEMA_ID, Contesto, ErroreTool, link
from .operazione import CONFERMA, Scrittura, strumento, trova, valida

SCHEMA_DATA = {"type": "string", "format": "date"}
SCHEMA_IMPORTO = {
    "type": "string",
    "minLength": 1,
    "maxLength": 20,
    "description": "Importo in euro, imponibile, come stringa con il punto decimale: «1234.50».",
}
SCHEMA_TESTO = {"type": "string", "maxLength": 250}


def _dati(form_cls, istanza, argomenti: dict, conversioni: dict | None = None) -> dict:
    """Dati del form: valori attuali dell'istanza, sostituiti dai soli campi passati.

    Per un oggetto nuovo si parte dai default del modello, come il form vuoto dell'interfaccia.
    """
    campi = list(form_cls._meta.fields)
    base = istanza if istanza is not None else form_cls._meta.model()
    dati = model_to_dict(base, fields=campi)
    for chiave, valore in argomenti.items():
        if chiave in campi:
            dati[chiave] = valore
    for chiave, funzione in (conversioni or {}).items():
        if chiave in argomenti:
            dati[chiave] = funzione(argomenti[chiave])
    return {k: ("" if v is None else v) for k, v in dati.items()}


def _oggetto_link(oggetto) -> dict:
    nomi = {
        m.Contratto: "contratti:contratto",
        m.Fabbisogno: "contratti:fabbisogno",
        m.Fornitore: "contratti:fornitore",
    }
    voce = {"tipo": oggetto._meta.model_name, "id": oggetto.pk}
    if type(oggetto) in nomi:
        voce["link"] = link(nomi[type(oggetto)], oggetto.pk)
    return voce


# --- A. Pratica e rate ------------------------------------------------------------------------


def _soggetto_pratica(argomenti: dict):
    if ("contratto_id" in argomenti) == ("fabbisogno_id" in argomenti):
        raise ErroreTool("Indicare «contratto_id» oppure «fabbisogno_id», non entrambi.")
    if "contratto_id" in argomenti:
        return trova(m.Contratto.objects, argomenti["contratto_id"], "contratto")
    return trova(m.Fabbisogno.objects, argomenti["fabbisogno_id"], "fabbisogno")


def _avanza_pratica(ctx: Contesto, argomenti: dict) -> dict:
    oggetto = _soggetto_pratica(argomenti)
    form = forms.PassaggioPraticaForm({k: argomenti.get(k, "") for k in ("stato", "data", "note")})
    valida(form)
    d = form.cleaned_data
    passaggio = servizi.avanza_pratica(
        oggetto, d["stato"], d["data"], d.get("note", ""), ctx.utente
    )
    return {"oggetti": [_oggetto_link(oggetto), {"tipo": "statopratica", "id": passaggio.pk}]}


def _modifica_rata(ctx: Contesto, argomenti: dict) -> dict:
    rata = trova(m.Rata.objects.select_related("piano__voce__contratto"), argomenti["id"], "rata")
    form = forms.RataForm(_dati(forms.RataForm, rata, argomenti), instance=rata)
    valida(form)
    servizi.salva_rata_manuale(form.save(commit=False))
    return {"oggetti": [{"tipo": "rata", "id": rata.pk}, _oggetto_link(rata.piano.voce.contratto)]}


def _genera_scadenzario(ctx: Contesto, argomenti: dict) -> dict:
    voce = trova(m.VoceContratto.objects, argomenti["voce_id"], "voce")
    rate = servizi.genera_scadenzario(voce)
    return {
        "oggetti": [_oggetto_link(voce.contratto), {"tipo": "vocecontratto", "id": voce.pk}],
        "rate_generate": len(rate),
    }


# --- B. Anagrafiche ---------------------------------------------------------------------------

CAMPI_FORNITORE = {
    "ragione_sociale": {"type": "string", "minLength": 1, "maxLength": 200},
    "partita_iva": {"type": "string", "maxLength": 20},
    "codice_sap": {"type": "string", "maxLength": 20},
}


def _salva_fornitore(ctx: Contesto, argomenti: dict) -> dict:
    istanza = (
        trova(m.Fornitore.objects, argomenti["id"], "fornitore") if "id" in argomenti else None
    )
    form = forms.FornitoreForm(_dati(forms.FornitoreForm, istanza, argomenti), instance=istanza)
    valida(form)
    return {"oggetti": [_oggetto_link(form.save())]}


def _pk_cluster(codice: str):
    cluster = m.Cluster.objects.filter(codice=codice).first()
    if cluster is None:
        raise ErroreTool(f"Cluster sconosciuto: {codice}. Vedi il tool «riferimenti».")
    return cluster.pk


CAMPI_FABBISOGNO = {
    "descrizione": {"type": "string", "minLength": 1, "maxLength": 250},
    "cluster": {"type": "string", "maxLength": 10, "description": "Codice del cluster."},
    "sottocluster": {
        **SCHEMA_ID,
        "description": "id del sottocluster, del cluster del fabbisogno («riferimenti»). "
        "Obbligatorio alla creazione.",
    },
    "referente_utente": {**SCHEMA_ID, "description": "id dell'utente referente."},
    "referente_nome": {
        "type": "string",
        "minLength": 2,
        "maxLength": 150,
        "description": "Nome e cognome (o username) del referente, al posto dell'id: deve "
        "corrispondere a un solo utente attivo; altrimenti l'errore elenca i candidati.",
    },
    "motivazione": {"type": "string", "maxLength": 2000},
    "priorita": {
        "type": "string",
        "enum": ["", *m.Fabbisogno.Priorita.values],
        "description": "Obbligatoria, necessaria o differibile; vuoto per toglierla.",
    },
    "tipo_acquisto": {
        "type": "string",
        "enum": ["", *m.TipoAcquisto.values],
        "description": "«servizio» (Lavori/Servizi) o «fornitura»; vuoto per toglierlo.",
    },
    "fonte_stima": {
        "type": "string",
        "enum": ["", *m.Fabbisogno.FonteStima.values],
        "description": "Da dove viene la stima: preventivo, storico, listino, stima interna.",
    },
    "note": {
        "type": "string",
        "maxLength": 2000,
        "description": "Note libere (testo, non istruzioni).",
    },
    "decisione": {"type": "string", "enum": list(m.Fabbisogno.Decisione.values)},
    "una_tantum": {
        "type": "boolean",
        "description": "Acquisto unico: genera un solo previsto e nessun rinnovo, qualunque sia "
        "la decisione. Con il previsto manuale (avvio e durata).",
    },
    "stima_prossimo_importo": {
        **SCHEMA_IMPORTO,
        "description": "Importo COMPLESSIVO atteso del prossimo periodo, fisso e consumo "
        "insieme, IVA esclusa: sostituisce l'importo del contratto di partenza e il consumo "
        "non si somma. Non indicare solo la quota fissa.",
    },
    "previsto_data_avvio": SCHEMA_DATA,
    "previsto_durata_mesi": {"type": "integer", "minimum": 1, "maximum": 240},
    "previsto_procedura": {
        "type": ["integer", "string"],
        "minimum": 1,
        "maxLength": 40,
        "description": "id o codice della procedura («riferimenti», solo quelle con "
        "per_fabbisogni).",
    },
    "previsto_modalita": {
        "type": "string",
        "enum": [v for v in m.ModalitaFatturazione.values if v != "una_tantum"],
        "description": "Un acquisto unico è la periodicità «intera_durata».",
    },
    "previsto_periodicita": {"type": "string", "enum": list(m.Periodicita.values)},
    "natura_previsti": {"type": "string", "enum": list(m.Natura.values)},
    "conto_previsti": {**SCHEMA_ID, "description": "id del conto («riferimenti»)."},
    "wbs_previsti": {**SCHEMA_ID, "description": "id della WBS («riferimenti»)."},
}


def _pk_procedura(valore) -> int:
    """La procedura si indica con l'id o con il codice di «riferimenti»."""
    if isinstance(valore, int):
        return valore
    procedura = m.Procedura.objects.filter(codice=valore).first()
    if procedura is None:
        raise ErroreTool(f"Procedura sconosciuta: {valore}. Vedi il tool «riferimenti».")
    return procedura.pk


def _utente_per_nome(testo: str):
    """L'utente attivo che corrisponde al nome; errore se nessuno o più d'uno."""
    parole = testo.lower().split()
    candidati = [
        u
        for u in forms.utenti_attivi()
        if all(p in f"{u.first_name} {u.last_name} {u.get_username()}".lower() for p in parole)
    ]
    esatti = [u for u in candidati if forms.nome_utente(u).lower() == testo.lower()]
    candidati = esatti or candidati
    if not candidati:
        raise ErroreTool(f"Nessun utente attivo corrisponde a «{testo}».")
    if len(candidati) > 1:
        elenco = "; ".join(f"{forms.nome_utente(u)} (id {u.pk})" for u in candidati[:10])
        raise ErroreTool(
            f"Più utenti corrispondono a «{testo}»: {elenco}. Indica il nome completo o "
            "«referente_utente» con l'id."
        )
    return candidati[0]


def _salva_fabbisogno(ctx: Contesto, argomenti: dict) -> dict:
    istanza = None
    if "id" in argomenti:
        istanza = trova(m.Fabbisogno.objects, argomenti["id"], "fabbisogno")
    if "referente_nome" in argomenti and "referente_utente" in argomenti:
        raise ErroreTool("Indicare «referente_utente» oppure «referente_nome», non entrambi.")
    dati = _dati(
        forms.FabbisognoForm,
        istanza,
        argomenti,
        {"cluster": _pk_cluster, "previsto_procedura": _pk_procedura},
    )
    if "referente_nome" in argomenti:
        dati["referente_utente"] = _utente_per_nome(argomenti["referente_nome"]).pk
    form = forms.FabbisognoForm(dati, instance=istanza, utente=ctx.utente)
    valida(form)
    return {"oggetti": [_oggetto_link(form.save())]}


# --- Competenza dichiarata -----------------------------------------------------------------


def _dichiara_competenza(ctx: Contesto, argomenti: dict) -> dict:
    f = trova(m.Fabbisogno.objects, argomenti["fabbisogno_id"], "fabbisogno")
    form = forms.CompetenzaDichiarataForm(
        {k: argomenti.get(k, "") for k in ("anno", "natura", "importo", "note")}
    )
    valida(form)
    d = form.cleaned_data
    dichiarata = servizi.dichiara_competenza(f, d["anno"], d["natura"], d["importo"], d["note"])
    return {
        "oggetti": [_oggetto_link(f), {"tipo": "competenzadichiarata", "id": dichiarata.pk}],
    }


# --- Archiviazione ----------------------------------------------------------------------------

ARCHIVIABILI = {
    "contratto": m.Contratto,
    "fabbisogno": m.Fabbisogno,
    "fornitore": m.Fornitore,
    "voce": m.VoceContratto,
    "competenza": m.CompetenzaDichiarata,
}


def _archiviabile(argomenti: dict):
    return trova(ARCHIVIABILI[argomenti["tipo"]].objects, argomenti["id"], argomenti["tipo"])


def _archivia(archiviato: bool):
    def applica(ctx: Contesto, argomenti: dict) -> dict:
        oggetto = _archiviabile(argomenti)
        servizi.archivia(oggetto, archiviato)
        return {"oggetti": [_oggetto_link(oggetto)], "archiviato": archiviato}

    return applica


def _oggetti_archiviazione(argomenti: dict) -> list:
    oggetto = _archiviabile(argomenti)
    # I fornitori sono in comune: nessun controllo di cluster (come l'interfaccia).
    return [] if isinstance(oggetto, m.Fornitore) else [oggetto]


# --- D. Catena dei rinnovi --------------------------------------------------------------------


def _contratto(argomenti: dict, chiave: str = "contratto_id") -> m.Contratto:
    return trova(m.Contratto.objects.select_related("fabbisogno"), argomenti[chiave], "contratto")


def _collega_rinnovo(ctx: Contesto, argomenti: dict) -> dict:
    predecessore = _contratto(argomenti)
    candidati = servizi.candidati_rinnovo(predecessore)
    scelto = next((c for c in candidati if c.pk == argomenti["successore_id"]), None)
    if scelto is None:
        ammessi = ", ".join(str(c.pk) for c in candidati) or "nessuno"
        raise ErroreTool(
            "Il successore deve essere un contratto dello stesso fabbisogno che inizia dopo, "
            f"senza predecessore. Candidati: {ammessi}."
        )
    servizi.collega_rinnovo(predecessore, scelto)
    return {"oggetti": [_oggetto_link(predecessore), _oggetto_link(scelto)]}


def _scollega(ctx: Contesto, argomenti: dict) -> dict:
    contratto = _contratto(argomenti)
    predecessore = servizi.scollega_predecessore(contratto)
    return {"oggetti": [_oggetto_link(contratto), _oggetto_link(predecessore)]}


def _confluisci(ctx: Contesto, argomenti: dict) -> dict:
    nuovo = _contratto(argomenti)
    candidati = {c.pk: c for c in servizi.candidati_confluenza(nuovo)}
    scelti = argomenti["confluiti_ids"]
    if fuori := [pk for pk in scelti if pk not in candidati]:
        ammessi = ", ".join(str(pk) for pk in candidati) or "nessuno"
        raise ErroreTool(f"Contratti non ammessi: {fuori}. Candidati: {ammessi}.")
    for pk in scelti:
        servizi.confluisci(candidati[pk], nuovo)
    return {"oggetti": [_oggetto_link(nuovo), *(_oggetto_link(candidati[pk]) for pk in scelti)]}


def _togli_confluenza(ctx: Contesto, argomenti: dict) -> dict:
    contratto = _contratto(argomenti)
    nuovo = servizi.togli_confluenza(contratto)
    return {"oggetti": [_oggetto_link(contratto), _oggetto_link(nuovo)]}


def _schema(proprieta: dict, obbligatori: list[str] | None = None) -> dict:
    schema = {"type": "object", "properties": proprieta, "additionalProperties": False}
    if obbligatori:
        schema["required"] = obbligatori
    return schema


STRUMENTI = [
    strumento(
        Scrittura("avanza_pratica", lambda a: [_soggetto_pratica(a)], _avanza_pratica),
        "Avanza la pratica di rinnovo",
        "Registra un passaggio della pratica sul contratto in scadenza (o sul fabbisogno nuovo, "
        "senza contratti): stato, data, nota facoltativa. A mano solo «offerta richiesta» e "
        "«offerta ricevuta»: da «RDA richiesta» in poi lo stato si ricava dalle RDA collegate.",
        _schema(
            {
                "contratto_id": SCHEMA_ID,
                "fabbisogno_id": SCHEMA_ID,
                "stato": {"type": "string", "enum": [v for v, _ in forms.STATI_PRATICA_MANUALI]},
                "data": SCHEMA_DATA,
                "note": {"type": "string", "maxLength": 500},
            },
            ["stato", "data"],
        ),
    ),
    strumento(
        Scrittura(
            "modifica_rata",
            lambda a: [trova(m.Rata.objects, a["id"], "rata")],
            _modifica_rata,
        ),
        "Modifica una rata",
        "Cambia data fattura, pagamento stimato, importo, consuntivo o numero fattura di una "
        "rata; la rata resta marcata «modificata a mano» e non si rigenera più.",
        _schema(
            {
                "id": SCHEMA_ID,
                "data_fattura": SCHEMA_DATA,
                "data_pagamento_stimata": SCHEMA_DATA,
                "importo": SCHEMA_IMPORTO,
                "consuntivo": {"type": "boolean"},
                "numero_fattura": {"type": "string", "maxLength": 40},
            },
            ["id"],
        ),
    ),
    strumento(
        Scrittura(
            "genera_scadenzario",
            lambda a: [trova(m.VoceContratto.objects, a["voce_id"], "voce")],
            _genera_scadenzario,
        ),
        "Genera lo scadenzario di una voce",
        "Genera (o rigenera) le rate della voce dal suo piano di fatturazione. Rifiutato se ci "
        "sono rate modificate a mano o consuntivate.",
        _schema({"voce_id": SCHEMA_ID}, ["voce_id"]),
    ),
    strumento(
        Scrittura("crea_fornitore", lambda a: [], _salva_fornitore, senza_cluster=True),
        "Nuovo fornitore",
        "Crea un fornitore (in comune a tutti i cluster). La partita IVA, se indicata, è unica.",
        _schema(CAMPI_FORNITORE, ["ragione_sociale"]),
    ),
    strumento(
        Scrittura(
            "modifica_fornitore",
            lambda a: [trova(m.Fornitore.objects, a["id"], "fornitore")],
            _salva_fornitore,
            senza_cluster=True,
        ),
        "Modifica un fornitore",
        "Cambia solo i campi indicati del fornitore.",
        _schema({"id": SCHEMA_ID, **CAMPI_FORNITORE}, ["id"]),
    ),
    strumento(
        Scrittura("crea_fabbisogno", lambda a: [], _salva_fabbisogno),
        "Nuovo fabbisogno",
        "Crea un fabbisogno (servizio ricorrente) in un cluster che puoi modificare, con il "
        "sottocluster (obbligatorio), la motivazione, la priorità, il tipo d'acquisto, la "
        "fonte della stima e il referente (id o nome). «una_tantum» per un acquisto unico. "
        "Per un fabbisogno nuovo, senza contratti, si può dare il previsto manuale: avvio e "
        "durata insieme, CAPEX solo con una WBS. «stima_prossimo_importo» è l'importo "
        "complessivo atteso (fisso e consumo): non si somma il consumo del contratto.",
        _schema(CAMPI_FABBISOGNO, ["descrizione", "cluster", "sottocluster"]),
    ),
    strumento(
        Scrittura(
            "modifica_fabbisogno",
            lambda a: [trova(m.Fabbisogno.objects, a["id"], "fabbisogno")],
            _salva_fabbisogno,
        ),
        "Modifica un fabbisogno",
        "Cambia solo i campi indicati: decisione di continuità, acquisto unico, stima del "
        "prossimo importo (importo complessivo atteso, consumo compreso), motivazione, "
        "priorità, tipo d'acquisto, fonte della stima, note, referente (id o nome), previsto "
        "manuale, classificazione. Lo spostamento in un altro cluster richiede il permesso su "
        "entrambi.",
        _schema({"id": SCHEMA_ID, **CAMPI_FABBISOGNO}, ["id"]),
    ),
    strumento(
        Scrittura(
            "dichiara_competenza",
            lambda a: [trova(m.Fabbisogno.objects, a["fabbisogno_id"], "fabbisogno")],
            _dichiara_competenza,
        ),
        "Dichiara la competenza di un fabbisogno",
        "Registra la competenza che il referente dichiara per un anno e una natura (OPEX o "
        "CAPEX): una sola per fabbisogno, anno e natura, una nuova sostituisce la precedente. "
        "Il tool «fabbisogno» la mostra accanto al calcolo del registro, con lo scostamento. "
        "Si toglie con «archivia» (tipo «competenza»).",
        _schema(
            {
                "fabbisogno_id": SCHEMA_ID,
                "anno": {"type": "integer", "minimum": 2000, "maximum": 2100},
                "natura": {"type": "string", "enum": list(m.Natura.values)},
                "importo": SCHEMA_IMPORTO,
                "note": {"type": "string", "maxLength": 500},
            },
            ["fabbisogno_id", "anno", "natura", "importo"],
        ),
    ),
    strumento(
        Scrittura("archivia", _oggetti_archiviazione, _archivia(True)),
        "Archivia",
        "Archivia un contratto, un fabbisogno, un fornitore, una voce o una competenza "
        "dichiarata (nessuna cancellazione: "
        "si ripristina con «ripristina»). Un contratto archiviato esce da alert, budget e "
        "previsti.",
        _schema(
            {"tipo": {"type": "string", "enum": list(ARCHIVIABILI)}, "id": SCHEMA_ID},
            ["tipo", "id"],
        ),
    ),
    strumento(
        Scrittura("ripristina", _oggetti_archiviazione, _archivia(False)),
        "Ripristina",
        "Riporta attivo un oggetto archiviato.",
        _schema(
            {"tipo": {"type": "string", "enum": list(ARCHIVIABILI)}, "id": SCHEMA_ID},
            ["tipo", "id"],
        ),
    ),
    strumento(
        Scrittura(
            "collega_rinnovo",
            lambda a: [_contratto(a), _contratto(a, "successore_id")],
            _collega_rinnovo,
        ),
        "Collega un rinnovo",
        "Indica che un contratto già registrato (successore_id) è il rinnovo di questo "
        "(contratto_id): stesso fabbisogno, inizio dopo, senza altro predecessore.",
        _schema(
            {"contratto_id": SCHEMA_ID, "successore_id": SCHEMA_ID},
            ["contratto_id", "successore_id"],
        ),
    ),
    strumento(
        Scrittura("scollega_predecessore", lambda a: [_contratto(a)], _scollega),
        "Scollega dal predecessore",
        "Toglie il collegamento del contratto al suo predecessore: torna inizio di una catena.",
        _schema({"contratto_id": SCHEMA_ID}, ["contratto_id"]),
    ),
    strumento(
        Scrittura(
            "confluisci",
            lambda a: [
                _contratto(a),
                *(trova(m.Contratto.objects, pk, "contratto") for pk in a["confluiti_ids"]),
            ],
            _confluisci,
        ),
        "Contratti che confluiscono",
        "Il contratto (contratto_id) sostituisce anche altri contratti dello stesso fabbisogno "
        "che finiscono prima (confluiti_ids): escono da alert e previsti.",
        _schema(
            {
                "contratto_id": SCHEMA_ID,
                "confluiti_ids": {"type": "array", "items": SCHEMA_ID},
            },
            ["contratto_id", "confluiti_ids"],
        ),
    ),
    strumento(
        Scrittura("togli_confluenza", lambda a: [_contratto(a)], _togli_confluenza),
        "Togli la confluenza",
        "Il contratto non è più sostituito dal contratto in cui era confluito.",
        _schema({"contratto_id": SCHEMA_ID}, ["contratto_id"]),
    ),
    CONFERMA,
]
