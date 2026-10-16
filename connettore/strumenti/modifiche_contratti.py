"""Tool di scrittura del gruppo C: contratti, rinnovi, proroghe, voci (SPEC_MCP §8.2).

Stessi form e servizi delle viste (``ContrattoForm``, ``VoceForm``, ``PianoForm``,
``QuoteFormSet``, ``RinnovoForm``, ``servizi.salva_voce``, ``servizi.registra_rinnovo``, …).
Un contratto si crea con le sue voci, i loro piani e le quote in un'operazione sola.
"""

from django.db.models import Model

from contratti import adapters, forms, servizi
from contratti import models as m

from .base import SCHEMA_ID, Contesto, ErroreTool
from .modifiche import SCHEMA_DATA, SCHEMA_IMPORTO, _dati, _oggetto_link
from .operazione import ErroreValidazione, Scrittura, errori_form, strumento, trova, valida

PREFISSO_QUOTE = "quote"


# --- Conversioni degli argomenti ---------------------------------------------------------------


def _procedura(codice: str) -> int:
    procedura = m.Procedura.objects.filter(codice=codice).first()
    if procedura is None:
        raise ErroreTool(f"Procedura sconosciuta: {codice}. Vedi il tool «riferimenti».")
    return procedura.pk


CONVERSIONI_CONTRATTO = {"procedura": _procedura}


# --- Voci ---------------------------------------------------------------------------------------


def _dati_quote(quote: list[dict]) -> dict:
    dati = {
        f"{PREFISSO_QUOTE}-TOTAL_FORMS": str(len(quote)),
        f"{PREFISSO_QUOTE}-INITIAL_FORMS": "0",
        f"{PREFISSO_QUOTE}-MIN_NUM_FORMS": "0",
        f"{PREFISSO_QUOTE}-MAX_NUM_FORMS": "1000",
    }
    for i, q in enumerate(quote):
        for campo in ("dal", "al", "importo"):
            dati[f"{PREFISSO_QUOTE}-{i}-{campo}"] = q.get(campo, "")
    return dati


def _form_voce(contratto: m.Contratto, argomenti: dict, voce: m.VoceContratto | None = None):
    """VoceForm, PianoForm e QuoteFormSet come nella vista della voce."""
    piano = getattr(voce, "piano_fatturazione", None) if voce else None
    dati = _dati(forms.VoceForm, voce, argomenti)
    if voce is None and "centro_costo" not in argomenti:
        dati["centro_costo"] = m.CentroCosto.codice_predefinito()  # come il form vuoto
    form = forms.VoceForm(dati, instance=voce, contratto=contratto)
    piano_form = forms.PianoForm(
        _dati(forms.PianoForm, piano, argomenti.get("piano", {})), instance=piano
    )
    quote = forms.QuoteFormSet(
        _dati_quote(argomenti.get("quote", [])),
        instance=voce or m.VoceContratto(contratto=contratto),
        prefix=PREFISSO_QUOTE,
    )
    return form, piano_form, quote


def _valida_voce(prefisso: str, form, piano_form, quote) -> None:
    validi = [form.is_valid(), piano_form.is_valid(), quote.is_valid()]
    if all(validi):
        return
    errori = {f"{prefisso}{k}": v for k, v in errori_form(form).items()}
    errori |= {f"{prefisso}piano.{k}": v for k, v in errori_form(piano_form).items()}
    for i, e in enumerate(quote.errors):
        for campo, lista in e.items():
            errori[f"{prefisso}quote[{i}].{campo}"] = [str(x) for x in lista]
    if quote.non_form_errors():
        errori[f"{prefisso}quote"] = [str(x) for x in quote.non_form_errors()]
    raise ErroreValidazione(errori)


def _salva_voce(contratto, argomenti: dict, prefisso: str = "", voce=None) -> dict:
    form, piano_form, quote = _form_voce(contratto, argomenti, voce)
    _valida_voce(prefisso, form, piano_form, quote)
    salvata = servizi.salva_voce(contratto, form, piano_form, quote)
    esito = {"tipo": "vocecontratto", "id": salvata.voce.pk}
    if salvata.rate is None:
        esito["scadenzario"] = f"rate non rigenerate: {salvata.bloccato}"
    else:
        esito["rate_generate"] = len(salvata.rate)
    return esito


# --- crea_contratto, modifica_contratto ---------------------------------------------------------


def _crea_contratto(ctx: Contesto, argomenti: dict) -> dict:
    dati = _dati(forms.ContrattoNuovoForm, None, argomenti, CONVERSIONI_CONTRATTO)
    if "procedura" not in argomenti:  # come il form vuoto dell'interfaccia
        dati["procedura"] = _procedura("affidamento_diretto")
    form = forms.ContrattoNuovoForm(dati, utente=ctx.utente)
    valida(form)
    contratto = form.save()
    voci = [
        _salva_voce(contratto, v, prefisso=f"voci[{i}].") for i, v in enumerate(argomenti["voci"])
    ]
    return {"oggetti": [_oggetto_link(contratto), *voci]}


def _modifica_contratto(ctx: Contesto, argomenti: dict) -> dict:
    contratto = trova(m.Contratto.objects, argomenti["id"], "contratto")
    dati = _dati(forms.ContrattoModificaForm, contratto, argomenti, CONVERSIONI_CONTRATTO)
    form = forms.ContrattoModificaForm(dati, instance=contratto)
    valida(form)
    return {"oggetti": [_oggetto_link(form.save())]}


# --- registra_rinnovo ---------------------------------------------------------------------------


def _righe_voci(predecessore: m.Contratto, argomenti: dict) -> list[dict]:
    """Voci del rinnovo: quelle proposte dal predecessore, con le modifiche indicate."""
    righe = {v["origine"]: v for v in servizi.voci_iniziali_rinnovo(predecessore)}
    for v in argomenti.get("voci", []):
        if v["origine"] not in righe:
            ammesse = ", ".join(str(pk) for pk in righe) or "nessuna"
            raise ErroreTool(f"Voce d'origine {v['origine']} non riportabile. Ammesse: {ammesse}.")
        righe[v["origine"]] |= v
    validate = []
    for i, riga in enumerate(righe.values()):
        form = forms.VoceRinnovoForm({k: ("" if x is None else x) for k, x in riga.items()})
        if not form.is_valid():
            raise ErroreValidazione({f"voci[{i}].{k}": v for k, v in errori_form(form).items()})
        validate.append(form.cleaned_data)
    return servizi.voci_rinnovo(validate)


def _registra_rinnovo(ctx: Contesto, argomenti: dict) -> dict:
    predecessore = trova(m.Contratto.objects, argomenti["contratto_id"], "contratto")
    senza_contratto = argomenti.get("senza_contratto", False)
    if adapters.ha_successore(predecessore):
        raise ErroreTool("Il contratto ha già un successore registrato.")
    classe = forms.RinnovoSenzaContrattoForm if senza_contratto else forms.RinnovoForm
    iniziali = servizi.iniziali_rinnovo(predecessore, senza_contratto)
    dati = {
        k: (v.pk if isinstance(v, Model) else v)
        for k, v in iniziali.items()
        if k in classe._meta.fields
    }
    dati |= {k: v for k, v in argomenti.items() if k in classe._meta.fields}
    for chiave, funzione in CONVERSIONI_CONTRATTO.items():
        if chiave in argomenti:
            dati[chiave] = funzione(argomenti[chiave])
    form = classe({k: ("" if v is None else v) for k, v in dati.items()})
    valida(form)
    voci = _righe_voci(predecessore, argomenti)
    sostituibili = {c.pk: c for c in servizi.candidati_sostituiti(predecessore)}
    scelti = argomenti.get("sostituisce_ids", [])
    if fuori := [pk for pk in scelti if pk not in sostituibili]:
        ammessi = ", ".join(str(pk) for pk in sostituibili) or "nessuno"
        raise ErroreTool(f"Contratti non sostituibili: {fuori}. Ammessi: {ammessi}.")
    dati_rinnovo = form.cleaned_data | ({"senza_contratto": True} if senza_contratto else {})
    nuovo = servizi.registra_rinnovo(
        predecessore,
        dati_rinnovo,
        voci,
        utente=ctx.utente,
        sostituisce=[sostituibili[pk] for pk in scelti],
    )
    return {"oggetti": [_oggetto_link(nuovo), _oggetto_link(predecessore)]}


def _oggetti_rinnovo(argomenti: dict) -> list:
    predecessore = trova(m.Contratto.objects, argomenti["contratto_id"], "contratto")
    sostituiti = [
        trova(m.Contratto.objects, pk, "contratto") for pk in argomenti.get("sostituisce_ids", [])
    ]
    return [predecessore, *sostituiti]


# --- registra_proroga ---------------------------------------------------------------------------

CAMPI_PROROGA = (
    "data_atto",
    "nuova_data_fine",
    "riferimento",
    "importo_fisso",
    "descrizione_voce",
    "modalita",
    "periodicita",
)


def _registra_proroga(ctx: Contesto, argomenti: dict) -> dict:
    contratto = trova(m.Contratto.objects, argomenti["contratto_id"], "contratto")
    dati = {"modalita": "una_tantum", "note": ""} | {
        k: argomenti[k] for k in CAMPI_PROROGA if k in argomenti
    }
    form = forms.ProrogaForm(dati)
    valida(form)
    d = form.cleaned_data
    proroga = servizi.registra_proroga(
        contratto,
        {k: d[k] for k in ("data_atto", "nuova_data_fine", "riferimento", "note")},
        servizi.voce_proroga(d),
    )
    return {"oggetti": [_oggetto_link(contratto), {"tipo": "proroga", "id": proroga.pk}]}


# --- crea_voce, modifica_voce -------------------------------------------------------------------


def _crea_voce(ctx: Contesto, argomenti: dict) -> dict:
    contratto = trova(m.Contratto.objects, argomenti["contratto_id"], "contratto")
    return {"oggetti": [_oggetto_link(contratto), _salva_voce(contratto, argomenti)]}


def _modifica_voce(ctx: Contesto, argomenti: dict) -> dict:
    voce = trova(m.VoceContratto.objects.select_related("contratto"), argomenti["id"], "voce")
    return {
        "oggetti": [
            _oggetto_link(voce.contratto),
            _salva_voce(voce.contratto, argomenti, voce=voce),
        ]
    }


def _oggetti_voce(argomenti: dict) -> list:
    voce = trova(m.VoceContratto.objects, argomenti["id"], "voce")
    piano = getattr(voce, "piano_fatturazione", None)
    return [voce, *([piano] if piano else [])]


# --- Schemi -------------------------------------------------------------------------------------

SCHEMA_PIANO = {
    "type": "object",
    "properties": {
        "modalita": {"type": "string", "enum": list(m.ModalitaFatturazione.values)},
        "periodicita": {"type": "string", "enum": list(m.Periodicita.values)},
        "data_prima_fattura": SCHEMA_DATA,
        "giorni_pagamento": {"type": "integer", "minimum": 0, "maximum": 365},
        "pagamento_fine_mese": {"type": "boolean"},
    },
    "additionalProperties": False,
}
SCHEMA_QUOTE = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"dal": SCHEMA_DATA, "al": SCHEMA_DATA, "importo": SCHEMA_IMPORTO},
        "required": ["dal", "al", "importo"],
        "additionalProperties": False,
    },
    "description": "Quote per periodo: contigue, a copertura del servizio, somma = fisso.",
}
CAMPI_VOCE = {
    "descrizione": {"type": "string", "minLength": 1, "maxLength": 250},
    "proroga": {**SCHEMA_ID, "description": "id della proroga, se la voce ne è l'importo."},
    "natura": {"type": "string", "enum": list(m.Natura.values)},
    "conto": {**SCHEMA_ID, "description": "id del conto («riferimenti»)."},
    "centro_costo": {
        "type": "string",
        "maxLength": 20,
        "description": "Codice del centro di costo («riferimenti»); di default il predefinito.",
    },
    "wbs": {**SCHEMA_ID, "description": "id della WBS («riferimenti»); obbligatoria per CAPEX."},
    "autorizzazione_extra_budget": {
        **SCHEMA_ID,
        "description": "id dell'autorizzazione extra budget dell'AD: la voce esce dal budget "
        "(solo contratti una tantum).",
    },
    "importo_fisso": SCHEMA_IMPORTO,
    "massimale_variabile": SCHEMA_IMPORTO,
    "stima_consumo_pct": {"type": "string", "maxLength": 10},
    "stima_consumo_importo": SCHEMA_IMPORTO,
    "natura_rinnovi": {"type": "string", "enum": list(m.Natura.values)},
    "conto_rinnovi": SCHEMA_ID,
    "wbs_rinnovi": SCHEMA_ID,
    "piano": SCHEMA_PIANO,
}
SCHEMA_VOCE_NUOVA = {
    "type": "object",
    "properties": {**CAMPI_VOCE, "quote": SCHEMA_QUOTE},
    "required": ["descrizione", "importo_fisso", "piano"],
    "additionalProperties": False,
}
CAMPI_CONTRATTO = {
    "fornitore": {**SCHEMA_ID, "description": "id del fornitore («cerca»)."},
    "descrizione": {"type": "string", "maxLength": 250},
    "numero_contratto": {"type": "string", "maxLength": 20},
    "data_emissione": SCHEMA_DATA,
    "numero_rda": {"type": "string", "maxLength": 20},
    "cig": {"type": "string", "maxLength": 20},
    "procedura": {"type": "string", "maxLength": 40, "description": "Codice («riferimenti»)."},
    "lead_time_mesi_override": {"type": "integer", "minimum": 0, "maximum": 60},
    "data_stipula": SCHEMA_DATA,
    "data_inizio": SCHEMA_DATA,
    "durata_mesi": {"type": "integer", "minimum": 1, "maximum": 240},
    "data_fine_override": SCHEMA_DATA,
    "tacito_rinnovo": {"type": "boolean"},
    "preavviso_disdetta_giorni": {"type": "integer", "minimum": 0, "maximum": 3650},
    "link_documenti": {"type": "string", "maxLength": 500},
}


def _schema(proprieta: dict, obbligatori: list[str]) -> dict:
    return {
        "type": "object",
        "properties": proprieta,
        "required": obbligatori,
        "additionalProperties": False,
    }


STRUMENTI = [
    strumento(
        Scrittura(
            "crea_contratto",
            lambda a: [trova(m.Fabbisogno.objects, a["fabbisogno"], "fabbisogno")],
            _crea_contratto,
        ),
        "Nuovo contratto",
        "Registra un contratto nuovo nel fabbisogno, con le sue voci (classificazione, importi, "
        "piano di fatturazione, quote per periodo): le rate si generano dal piano. "
        "«senza_contratto» per un acquisto senza documento contrattuale. Per il rinnovo di un "
        "contratto esistente usare «registra_rinnovo».",
        _schema(
            {
                "fabbisogno": {**SCHEMA_ID, "description": "id del fabbisogno."},
                "senza_contratto": {"type": "boolean"},
                **CAMPI_CONTRATTO,
                "voci": {"type": "array", "items": SCHEMA_VOCE_NUOVA},
            },
            ["fabbisogno", "fornitore", "data_inizio", "durata_mesi", "voci"],
        ),
    ),
    strumento(
        Scrittura(
            "modifica_contratto",
            lambda a: [trova(m.Contratto.objects, a["id"], "contratto")],
            _modifica_contratto,
        ),
        "Modifica un contratto",
        "Cambia solo i campi indicati del contratto (riferimenti, date, durata, procedura, tacito "
        "rinnovo). Il fabbisogno non si cambia da qui (si sposta dall'interfaccia).",
        _schema(
            {"id": SCHEMA_ID, "senza_contratto": {"type": "boolean"}, **CAMPI_CONTRATTO}, ["id"]
        ),
    ),
    strumento(
        Scrittura("registra_rinnovo", _oggetti_rinnovo, _registra_rinnovo),
        "Registra il rinnovo",
        "Nuovo contratto successore di contratto_id, proposto dal predecessore: stesso "
        "fornitore, procedura e durata, inizio il giorno dopo la fine, voci riportate. Si "
        "indicano solo le differenze (es. data, numero, importi delle voci per «origine»; "
        "riporta=false per non riportarne una). «senza_contratto» per il rinnovo senza "
        "documento contrattuale. «sostituisce_ids»: altri contratti dello stesso fabbisogno "
        "che confluiscono nel nuovo. La pratica del predecessore passa a «Contratto attivo».",
        _schema(
            {
                "contratto_id": SCHEMA_ID,
                "senza_contratto": {"type": "boolean"},
                **CAMPI_CONTRATTO,
                "voci": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "origine": {**SCHEMA_ID, "description": "id della voce riportata."},
                            "riporta": {"type": "boolean"},
                            "descrizione": {"type": "string", "minLength": 1, "maxLength": 250},
                            "importo_fisso": SCHEMA_IMPORTO,
                            "massimale_variabile": SCHEMA_IMPORTO,
                        },
                        "required": ["origine"],
                        "additionalProperties": False,
                    },
                },
                "sostituisce_ids": {"type": "array", "items": SCHEMA_ID},
            },
            ["contratto_id"],
        ),
    ),
    strumento(
        Scrittura(
            "registra_proroga",
            lambda a: [trova(m.Contratto.objects, a["contratto_id"], "contratto")],
            _registra_proroga,
        ),
        "Registra una proroga",
        "Proroga esercitata: data dell'atto, nuova data di fine (dopo quella attuale), "
        "riferimento; con «importo_fisso» anche la voce dell'importo, con il suo piano.",
        _schema(
            {
                "contratto_id": SCHEMA_ID,
                "data_atto": SCHEMA_DATA,
                "nuova_data_fine": SCHEMA_DATA,
                "riferimento": {"type": "string", "maxLength": 200},
                "importo_fisso": SCHEMA_IMPORTO,
                "descrizione_voce": {"type": "string", "maxLength": 250},
                "modalita": {"type": "string", "enum": list(m.ModalitaFatturazione.values)},
                "periodicita": {"type": "string", "enum": list(m.Periodicita.values)},
            },
            ["contratto_id", "data_atto", "nuova_data_fine"],
        ),
    ),
    strumento(
        Scrittura(
            "crea_voce",
            lambda a: [trova(m.Contratto.objects, a["contratto_id"], "contratto")],
            _crea_voce,
        ),
        "Nuova voce",
        "Aggiunge una voce al contratto, con piano di fatturazione e quote per periodo; le rate "
        "si generano dal piano.",
        _schema(
            {"contratto_id": SCHEMA_ID, **SCHEMA_VOCE_NUOVA["properties"]},
            ["contratto_id", "descrizione", "importo_fisso", "piano"],
        ),
    ),
    strumento(
        Scrittura("modifica_voce", _oggetti_voce, _modifica_voce),
        "Modifica una voce",
        "Cambia solo i campi indicati della voce e del suo piano («piano»); le rate si "
        "rigenerano, salvo quelle modificate a mano o consuntivate. Le quote per periodo "
        "esistenti si cambiano dall'interfaccia.",
        _schema({"id": SCHEMA_ID, **CAMPI_VOCE}, ["id"]),
    ),
]
