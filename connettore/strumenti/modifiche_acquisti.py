"""Tool di scrittura del processo d'acquisto (SPEC_MCP Rev08 §11.3, gruppo E; F12.2).

Ognuno passa dai form e dai servizi della vista corrispondente (``views_rda``,
``views_fatture``): stesse validazioni, stessi messaggi, stessi permessi. Tutto tranne gli
import (D14). Presa in carico, fuori registro e assegnazione ai proposti anche su più fatture,
al massimo 50 (D15). Niente note libere generiche (``note`` di RDA, fatture e documenti):
restano quelle registrate, come per i contratti (SPEC_MCP §8.2).

L'anteprima riporta, oltre alle modifiche, lo stato del processo prima e dopo: fase della RDA
e stato della pratica, passo della fattura e commento per PAC, fatturato e residuo del
contratto, motivo «da chiudere».
"""

from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied

from contratti import acquisti, fatture, permessi
from contratti import forms_fatture as ff
from contratti import forms_rda as fr
from contratti import models as m
from contratti import stanziamenti as servizi_stanziamenti
from contratti.engine import acquisti as motore

from .acquisti import _esecuzione, nome
from .base import SCHEMA_ID, Contesto, ErroreTool, link
from .modifiche import SCHEMA_DATA, SCHEMA_IMPORTO, _dati, _oggetto_link
from .modifiche_contratti import _procedura
from .operazione import ErroreValidazione, Scrittura, errori_form, strumento, trova, valida

Fase = motore.Fase
Tipo = m.DocumentoEsecuzione.Tipo
MASSIMO_FATTURE = 50  # D15
PREFISSO_POSIZIONI = "pos"
PREFISSO_VOCI = "voci"
NON_AUTORIZZATO = "Non autorizzato: l'oggetto appartiene a un cluster che non puoi modificare."


# --- Permessi (SPEC_MCP §11.3) ------------------------------------------------------------


def _verifica_cluster(ctx: Contesto, oggetto) -> None:
    try:
        if isinstance(oggetto, m.RichiestaAcquisto):
            permessi.verifica(ctx.utente, oggetto.cluster_id)
        elif isinstance(oggetto, m.Fabbisogno | m.Contratto | m.Rata | m.Stanziamento):
            permessi.verifica_oggetto(ctx.utente, oggetto)
    except PermissionDenied:
        raise ErroreTool(NON_AUTORIZZATO) from None


def _permesso(controllo_fattura=None):
    """RDA e contratti: chi modifica nel loro cluster. Fatture: ``controllo_fattura`` (di
    default ``fatture.puo_lavorare``); ``False`` lascia il controllo al servizio (operazioni
    su più fatture, che rifiutano fattura per fattura)."""

    def verifica(ctx: Contesto, oggetti: list) -> None:
        for o in oggetti:
            if isinstance(o, m.Fattura):
                if controllo_fattura is False:
                    continue
                if not (controllo_fattura or fatture.puo_lavorare)(ctx.utente, o):
                    raise ErroreTool("Non autorizzato: non puoi modificare questa fattura.")
            else:
                _verifica_cluster(ctx, o)

    return verifica


# --- Stato del processo per l'anteprima ------------------------------------------------------


def _stato_pratica(oggetto, oggi) -> dict:
    valore = acquisti.stato_pratica_con_data(oggetto, oggi)
    if valore is None:
        return {"stato": m.StatoPratica.Stato.NON_AVVIATA.label, "data": None}
    return {"stato": m.StatoPratica.Stato(valore[0]).label, "data": valore[1]}


def _stato_rda(rda: m.RichiestaAcquisto, oggi) -> dict:
    dati = acquisti.dati_rda(rda)
    fase = motore.fase(dati, oggi)
    return {
        "fase": fase,
        "fase_etichetta": motore.ETICHETTE_FASE[fase],
        "data_fase": motore.data_fase(dati, oggi),
        "importo": acquisti.importo_rda(rda),
        "numero_rda": rda.numero_rda,
    }


def _stato_fattura(f: m.Fattura, oggi) -> dict:
    passo = fatture.passo_fattura(f, oggi)
    return {
        "passo": passo or "trasferita",
        "passo_etichetta": motore.ETICHETTE_PASSO[passo] if passo else "Trasferita",
        "in_carico_a": nome(f.referente),
        "contratto_id": f.contratto_id,
        "fuori_registro": f.fuori_registro,
        "esito_convalida": f.get_esito_convalida_display(),
        "anomalie": fatture.anomalie(f),
        "commento_pac": fatture.commento_pac(f),
    }


def _stato_contratto(c: m.Contratto, oggi) -> dict:
    stato = {
        "chiuso_il": c.data_chiusura,
        **_esecuzione(acquisti.riepilogo_esecuzione(c, oggi)),
        "differenza_da_rda": acquisti.differenza_da_rda(c),
    }
    if c.rda_id:
        stato["fase_rda"] = motore.ETICHETTE_FASE[acquisti.fase(c.rda, oggi)]
    return stato


LETTORI = {
    "richiestaacquisto": (acquisti.QS_RDA, _stato_rda, "rda"),
    "fattura": (fatture.QS_FATTURE, _stato_fattura, "fatture"),
    "contratto": (m.Contratto.objects.select_related("rda"), _stato_contratto, "contratti"),
}


def _id(voce: dict):
    return "nuovo" if voce.get("nuovo") else voce["id"]


def stato_processo(ctx: Contesto, argomenti: dict, risultato: dict) -> dict:
    """Stato degli oggetti del processo d'acquisto toccati, ricalcolato con i servizi
    dell'interfaccia. Nella fotografia «prima» gli oggetti nuovi non esistono ancora."""
    stato: dict = {}
    for voce in risultato.get("oggetti", []):
        if voce["tipo"] not in LETTORI:
            continue
        queryset, funzione, chiave = LETTORI[voce["tipo"]]
        oggetto = queryset.filter(pk=voce["id"]).first()
        if oggetto is not None:  # nella fotografia «prima» un oggetto nuovo non c'è
            stato.setdefault(chiave, []).append({"id": _id(voce), **funzione(oggetto, ctx.oggi)})
    for tipo, pk in risultato.get("pratiche", []):
        modello = m.Contratto if tipo == "contratto" else m.Fabbisogno
        if (oggetto := modello.objects.filter(pk=pk).first()) is not None:
            stato.setdefault("pratiche", []).append(
                {"tipo": tipo, "id": pk, **_stato_pratica(oggetto, ctx.oggi)}
            )
    return stato


def _scrittura(nome_tool, oggetti, applica, controllo_fattura=None) -> Scrittura:
    return Scrittura(
        nome_tool,
        oggetti,
        applica,
        permesso=_permesso(controllo_fattura),
        stato=stato_processo,
    )


def _rif(oggetto, nuovo: bool = False) -> dict:
    voce = _oggetto_link(oggetto)
    if isinstance(oggetto, m.RichiestaAcquisto):
        voce["link"] = link("contratti:rda", oggetto.pk)
    elif isinstance(oggetto, m.Fattura):
        voce["link"] = link("contratti:fattura", oggetto.pk)
    if nuovo:
        voce["nuovo"] = True
    return voce


def _pratiche(*rda: m.RichiestaAcquisto) -> list[tuple[str, int]]:
    """Pratiche (contratto in scadenza o fabbisogno) delle RDA, per lo stato della pratica."""
    pratiche = []
    for r in rda:
        if r.contratto_in_scadenza_id:
            pratiche.append(("contratto", r.contratto_in_scadenza_id))
        elif r.fabbisogno_id:
            pratiche.append(("fabbisogno", r.fabbisogno_id))
    return list(dict.fromkeys(pratiche))


# --- Conversioni degli argomenti ---------------------------------------------------------------


def _per_codice(modello, etichetta: str):
    def converti(codice: str):
        oggetto = modello.objects.filter(codice=codice).first()
        if oggetto is None:
            raise ErroreTool(f"{etichetta} sconosciuto: {codice}. Vedi il tool «riferimenti».")
        return oggetto.pk

    return converti


_richiedente = _per_codice(m.RichiedenteSAP, "Richiedente SAP")
_gruppo_acquisti = _per_codice(m.GruppoAcquisti, "Gruppo acquisti")
_gruppo_merci = _per_codice(m.GruppoMerci, "Gruppo merci")
_cluster = _per_codice(m.Cluster, "Cluster")


def _form_valore(valore):
    """Valore iniziale (modello, Decimal, data) come dato di un form inviato."""
    if valore is None:
        return ""
    if hasattr(valore, "pk"):
        return valore.pk
    return valore


def _formset(prefisso: str, righe: list[dict]) -> dict:
    dati = {
        f"{prefisso}-TOTAL_FORMS": str(len(righe)),
        f"{prefisso}-INITIAL_FORMS": "0",
        f"{prefisso}-MIN_NUM_FORMS": "0",
        f"{prefisso}-MAX_NUM_FORMS": "1000",
    }
    for i, riga in enumerate(righe):
        for campo, valore in riga.items():
            dati[f"{prefisso}-{i}-{campo}"] = _form_valore(valore)
    return dati


def _valida_formset(nome_lista: str, formset) -> None:
    if formset.is_valid():
        return
    errori: dict[str, list[str]] = {}
    for i, e in enumerate(formset.errors):
        for campo, lista in e.items():
            errori[f"{nome_lista}[{i}].{campo}"] = [str(x) for x in lista]
    if formset.non_form_errors():
        errori[nome_lista] = [str(x) for x in formset.non_form_errors()]
    raise ErroreValidazione(errori)


# --- RDA ---------------------------------------------------------------------------------


def _rda(argomenti: dict, chiave: str = "id") -> m.RichiestaAcquisto:
    return trova(acquisti.QS_RDA.select_related("cluster"), argomenti[chiave], "RDA")


def _oggetti_rda(argomenti: dict) -> list:
    """La RDA con posizioni ed eventi: una posizione o un passaggio aggiunti dopo
    l'anteprima la rendono superata."""
    r = _rda(argomenti)
    return [r, *r.posizioni.order_by("pk"), *r.eventi.order_by("pk")]


CONVERSIONI_RICHIESTA = {
    "richiedente": _richiedente,
    "gruppo_acquisti": _gruppo_acquisti,
}
CAMPI_POSIZIONE = [
    "descrizione_breve",
    "gruppo_merci",
    "quantita",
    "importo_unitario",
    "di_cui_variabile",
    "natura",
    "conto",
    "centro_costo",
    "wbs",
]


def _riga_posizione(argomenti: dict, base: dict | None = None) -> dict:
    # Una posizione nuova parte dai valori del form vuoto (natura OPEX, centro di costo
    # predefinito), come nel browser.
    riga = dict(
        base or {"natura": m.Natura.OPEX, "centro_costo": m.CentroCosto.codice_predefinito()}
    )
    for campo in CAMPI_POSIZIONE:
        if campo in argomenti:
            riga[campo] = argomenti[campo]
    if "gruppo_merci" in argomenti:
        riga["gruppo_merci"] = _gruppo_merci(argomenti["gruppo_merci"])
    return riga


def _posizioni_crea(argomenti: dict, proposta) -> list[dict]:
    if "posizioni" not in argomenti:
        return fr.iniziali_posizioni(proposta.posizioni)
    return [_riga_posizione(p) for p in argomenti["posizioni"]]


def _posizioni_modifica(rda: m.RichiestaAcquisto, argomenti: dict) -> list[dict]:
    """Le posizioni salvate restano, nell'ordine; quelle indicate per numero cambiano solo nei
    campi passati; quelle senza numero si aggiungono in fondo. Nessuna cancellazione."""
    esistenti = fr.iniziali_posizioni(rda.posizioni.order_by("numero"))
    per_numero = dict(enumerate(esistenti, start=1))  # numerate 1..n da salva_richiesta
    nuove = []
    for p in argomenti.get("posizioni", []):
        if "numero" in p:
            if p["numero"] not in per_numero:
                raise ErroreTool(f"La RDA non ha la posizione {p['numero']}.")
            per_numero[p["numero"]] = _riga_posizione(p, per_numero[p["numero"]])
        else:
            nuove.append(_riga_posizione(p))
    return [*per_numero.values(), *nuove]


def _dati_richiesta(istanza, argomenti: dict, iniziali: dict | None = None) -> dict:
    dati = _dati(fr.RichiestaForm, istanza, argomenti, CONVERSIONI_RICHIESTA)
    for campo, valore in (iniziali or {}).items():
        if campo not in argomenti:
            dati[campo] = _form_valore(valore)
    # Come l'interfaccia: con il richiedente si propone il gruppo acquisti della sua unità.
    if "richiedente" in argomenti and "gruppo_acquisti" not in argomenti:
        richiedente = m.RichiedenteSAP.objects.get(pk=dati["richiedente"])
        if richiedente.gruppo_acquisti_id and richiedente.gruppo_acquisti.attivo:
            dati["gruppo_acquisti"] = richiedente.gruppo_acquisti_id
    return dati


def _salva_rda(ctx, rda, form, posizioni: list[dict], invia: bool) -> m.RichiestaAcquisto:
    formset = fr.PosizioniFormSet(
        _formset(PREFISSO_POSIZIONI, posizioni), prefix=PREFISSO_POSIZIONI, cluster=rda.cluster
    )
    validi = [form.is_valid(), formset.is_valid()]
    if not all(validi):
        errori = errori_form(form)
        try:
            _valida_formset("posizioni", formset)
        except ErroreValidazione as exc:
            errori |= exc.errori
        raise ErroreValidazione(errori)
    salvata = acquisti.salva_richiesta(form.save(commit=False), formset.posizioni())
    if invia:
        acquisti.invia(salvata, ctx.utente)
    return salvata


def _fabbisogno(argomenti: dict) -> m.Fabbisogno:
    return trova(
        m.Fabbisogno.objects.select_related("cluster", "sottocluster"),
        argomenti["fabbisogno_id"],
        "fabbisogno",
    )


def _crea_rda(ctx: Contesto, argomenti: dict) -> dict:
    f = _fabbisogno(argomenti)
    contratto = None
    if "contratto_in_scadenza_id" in argomenti:
        contratto = m.Contratto.objects.filter(
            pk=argomenti["contratto_in_scadenza_id"], fabbisogno=f
        ).first()
        if contratto is None:
            raise ErroreTool("Il contratto in scadenza deve essere del fabbisogno indicato.")
    proposta = acquisti.proposta_richiesta(
        f, ctx.oggi, aggiuntivo=argomenti.get("aggiuntivo", False), contratto_in_scadenza=contratto
    )
    istanza = m.RichiestaAcquisto(
        origine=m.RichiestaAcquisto.Origine.PORTALE,
        scopo=proposta.scopo,
        cluster=f.cluster,
        fabbisogno=None if proposta.contratto_in_scadenza else f,
        contratto_in_scadenza=proposta.contratto_in_scadenza,
        referente_utente=ctx.utente,
        data_creazione=ctx.oggi,
    )
    iniziali = {
        "descrizione": proposta.descrizione,
        "intestazione": proposta.intestazione,
        "fornitore_proposto": proposta.fornitore_proposto,
        "richiedente": proposta.richiedente,
        "gruppo_acquisti": proposta.gruppo_acquisti,
        "percorso_file_server": proposta.percorso_file_server,
        "rup": proposta.rup,
        "cup": proposta.cup,
    }
    form = fr.RichiestaForm(_dati_richiesta(None, argomenti, iniziali), instance=istanza)
    rda = _salva_rda(
        ctx, istanza, form, _posizioni_crea(argomenti, proposta), argomenti.get("invia", False)
    )
    return {
        "oggetti": [_rif(rda, nuovo=True)],
        "pratiche": _pratiche(rda),
        "testo_richiesta": acquisti.testo_della_richiesta(rda),
    }


def _modifica_rda(ctx: Contesto, argomenti: dict) -> dict:
    rda = _rda(argomenti)
    if acquisti.fase(rda) in (Fase.ANNULLATA, Fase.CHIUSA):
        raise ErroreTool("La RDA è annullata o chiusa: non si modifica.")
    correzione = acquisti.correzione_diretta(rda)
    form = fr.RichiestaForm(_dati_richiesta(rda, argomenti), instance=rda)
    _salva_rda(ctx, rda, form, _posizioni_modifica(rda, argomenti), argomenti.get("invia", False))
    risultato = {"oggetti": [_rif(rda)], "pratiche": _pratiche(rda)}
    if correzione:
        risultato["avvisi"] = [
            "La RDA è già inviata: la modifica è una correzione diretta, tracciata nella storia."
        ]
    return risultato


def _azione_rda(esegui):
    def applica(ctx: Contesto, argomenti: dict) -> dict:
        rda = _rda(argomenti)
        esegui(ctx, rda, argomenti)
        return {"oggetti": [_rif(rda)], "pratiche": _pratiche(rda)}

    return applica


def _dati_sap(ctx: Contesto, argomenti: dict) -> dict:
    rda = _rda(argomenti)
    form = fr.DatiSapForm(_dati(fr.DatiSapForm, rda, argomenti), instance=rda)
    valida(form)
    d = form.cleaned_data
    acquisti.aggiorna_dati_sap(rda, d["numero_rda"], d["data_inserimento"], d["data_rilascio"])
    risultato = {"oggetti": [_rif(rda)], "pratiche": _pratiche(rda)}
    if proposti := acquisti.contratti_proposti(rda):
        risultato["avvisi"] = [
            "Contratti con lo stesso n. RDA da collegare (tool «collega_rda»): "
            + ", ".join(f"{c} (id {c.pk})" for c in proposti)
        ]
    return risultato


def _registra_rda(ctx: Contesto, argomenti: dict) -> dict:
    istanza = m.RichiestaAcquisto(origine=m.RichiestaAcquisto.Origine.MANUALE)
    dati = _dati(fr.RdaManualeForm, istanza, argomenti, {"cluster": _cluster})
    dati["referente_utente"] = ""
    form = fr.RdaManualeForm(dati, instance=istanza, utente=ctx.utente)
    valida(form)
    _verifica_cluster(ctx, m.RichiestaAcquisto(cluster=form.cleaned_data["cluster"]))
    return {"oggetti": [_rif(form.save(), nuovo=True)]}


def _oggetti_collega(argomenti: dict) -> list:
    oggetti = _oggetti_rda(argomenti)
    for chiave in ("contratto_id", "fabbisogno_id"):
        if chiave in argomenti:
            modello = m.Contratto if chiave == "contratto_id" else m.Fabbisogno
            oggetti.append(trova(modello.objects, argomenti[chiave], chiave[:-3]))
    return oggetti


def _collega_rda(ctx: Contesto, argomenti: dict) -> dict:
    rda = _rda(argomenti)
    operazione = argomenti["operazione"]
    prima = _pratiche(rda)
    oggetti = [_rif(rda)]
    if operazione == "pratica":
        form = fr.CollegaPraticaForm(
            {
                "contratto": argomenti.get("contratto_id", ""),
                "fabbisogno": argomenti.get("fabbisogno_id", ""),
            },
            rda=rda,
            utente=ctx.utente,
        )
        valida(form)
        d = form.cleaned_data
        acquisti.collega_pratica(rda, contratto=d["contratto"], fabbisogno=d["fabbisogno"])
    else:
        if "contratto_id" not in argomenti:
            raise ErroreTool("Indicare «contratto_id».")
        if operazione == "contratto":
            form = fr.CollegaContrattoForm({"contratto": argomenti["contratto_id"]}, rda=rda)
            valida(form)
            contratto = form.cleaned_data["contratto"]
            acquisti.collega_contratto(rda, contratto)
        else:
            contratto = trova(m.Contratto.objects, argomenti["contratto_id"], "contratto")
            if contratto.rda_id != rda.pk:
                raise ErroreTool("Il contratto non ha questa RDA d'origine.")
            acquisti.scollega_contratto(contratto)
        oggetti.append(_rif(contratto))
    return {"oggetti": oggetti, "pratiche": list(dict.fromkeys([*prima, *_pratiche(rda)]))}


CAMPI_CONTRATTO_DA_RDA = {
    "fabbisogno_id": {
        **SCHEMA_ID,
        "description": "Solo se la RDA non ha una pratica: fabbisogno del contratto.",
    },
    "fornitore": {**SCHEMA_ID, "description": "id del fornitore (tool «cerca»)."},
    "descrizione": {"type": "string", "maxLength": 250},
    "numero_contratto": {"type": "string", "maxLength": 50},
    "data_emissione": SCHEMA_DATA,
    "cig": {"type": "string", "maxLength": 20},
    "procedura": {"type": "string", "maxLength": 50, "description": "Codice («riferimenti»)."},
    "lead_time_mesi_override": {"type": "integer", "minimum": 0, "maximum": 60},
    "data_inizio": SCHEMA_DATA,
    "durata_mesi": {"type": "integer", "minimum": 1, "maximum": 240},
    "una_tantum": {"type": "boolean"},
    "tipo_acquisto": {"type": "string", "enum": list(m.Contratto.TipoAcquisto.values)},
    "senza_contratto": {"type": "boolean"},
    "rup": {"type": "string", "maxLength": 150},
    "cup": {"type": "string", "maxLength": 20},
    "percorso_documenti": {"type": "string", "maxLength": 500},
    "modalita": {"type": "string", "enum": list(m.ModalitaFatturazione.values)},
    "periodicita": {"type": "string", "enum": list(m.Periodicita.values)},
    "voci": {
        "type": "array",
        "minItems": 1,
        "description": "Voci emesse; di default una per posizione della RDA, con i suoi importi.",
        "items": {
            "type": "object",
            "properties": {
                "posizione": {"type": "integer", "minimum": 1,
                              "description": "Numero della posizione d'origine."},
                "descrizione": {"type": "string", "minLength": 1, "maxLength": 250},
                "importo_fisso": SCHEMA_IMPORTO,
                "massimale_variabile": SCHEMA_IMPORTO,
            },
            "required": ["descrizione", "importo_fisso"],
            "additionalProperties": False,
        },
    },
}  # fmt: skip


def _registra_contratto_da_rda(ctx: Contesto, argomenti: dict) -> dict:
    rda = trova(acquisti.QS_RDA.select_related("cluster"), argomenti["id"], "RDA")
    if acquisti.fase(rda) == Fase.ANNULLATA:
        raise ErroreTool("La RDA è annullata.")
    iniziali = acquisti.iniziali_contratto(rda, ctx.oggi)
    dati = {campo: _form_valore(valore) for campo, valore in iniziali.items()}
    for campo in CAMPI_CONTRATTO_DA_RDA:
        if campo in argomenti and campo not in ("voci", "fabbisogno_id"):
            dati[campo] = argomenti[campo]
    if "procedura" in argomenti:
        dati["procedura"] = _procedura(argomenti["procedura"])
    if "fabbisogno_id" in argomenti:
        dati["fabbisogno"] = argomenti["fabbisogno_id"]
    form = fr.ContrattoDaRdaForm(dati, rda=rda, utente=ctx.utente)
    righe = argomenti.get("voci") or [
        {
            "posizione": p.numero,
            "descrizione": p.descrizione_breve,
            "importo_fisso": p.importo - p.di_cui_variabile,
            "massimale_variabile": p.di_cui_variabile,
        }
        for p in rda.posizioni.order_by("numero")
    ]
    formset = fr.VociDaRdaFormSet(_formset(PREFISSO_VOCI, righe), prefix=PREFISSO_VOCI)
    if not all([form.is_valid(), formset.is_valid()]):
        errori = errori_form(form)
        try:
            _valida_formset("voci", formset)
        except ErroreValidazione as exc:
            errori |= exc.errori
        raise ErroreValidazione(errori)
    fabbisogno = form.cleaned_data.get("fabbisogno")
    if fabbisogno is not None:
        _verifica_cluster(ctx, fabbisogno)
    voci = [
        {
            "posizione": d.get("posizione"),
            "descrizione": d["descrizione"],
            "importo_fisso": d["importo_fisso"],
            "massimale_variabile": d.get("massimale_variabile") or 0,
        }
        for d in formset.cleaned_data
        if d
    ]
    contratto = acquisti.registra_contratto_da_rda(
        rda,
        form.dati_contratto(),
        voci,
        modalita=form.cleaned_data["modalita"],
        periodicita=form.cleaned_data.get("periodicita") or "",
        fabbisogno=fabbisogno,
    )
    risultato = {
        "oggetti": [_rif(rda), _rif(contratto, nuovo=True)],
        "pratiche": _pratiche(rda),
    }
    if differenza := acquisti.differenza_da_rda(contratto):
        risultato["avvisi"] = [
            f"Il massimo del contratto differisce dalla RDA di {motore.formato_euro(differenza)}:"
            " la RDA resta com'è."
        ]
    return risultato


# --- Fatture ------------------------------------------------------------------------------


def _fattura(argomenti: dict, chiave: str = "id") -> m.Fattura:
    return trova(fatture.QS_FATTURE, argomenti[chiave], "fattura")


def _oggetti_fattura(argomenti: dict) -> list:
    f = _fattura(argomenti)
    oggetti = [f, *f.documenti.order_by("pk")]
    if argomenti.get("contratto_id"):
        oggetti.append(trova(m.Contratto.objects, argomenti["contratto_id"], "contratto"))
    return oggetti


def _contratti_della_fattura(f: m.Fattura, *altri) -> list[dict]:
    pks = dict.fromkeys(pk for pk in (f.contratto_id, *altri) if pk)
    return [{"tipo": "contratto", "id": pk} for pk in pks]


def _registra_fattura(ctx: Contesto, argomenti: dict) -> dict:
    if ("contratto_id" in argomenti) == ("fornitore_id" in argomenti):
        raise ErroreTool("Indicare «contratto_id» oppure «fornitore_id», non entrambi.")
    contratto = None
    if "contratto_id" in argomenti:
        contratto = trova(m.Contratto.objects, argomenti["contratto_id"], "contratto")
    dati = {
        "fornitore": argomenti.get("fornitore_id", ""),
        "numero": argomenti["numero"],
        "data": argomenti["data"],
        "importo_documento": argomenti["importo_documento"],
        "note": "",
    }
    form = ff.FatturaForm(dati, contratto=contratto)
    valida(form)
    d = form.cleaned_data
    fattura = fatture.registra(
        numero=d["numero"],
        data=d["data"],
        importo_documento=d["importo_documento"],
        fornitore=d.get("fornitore"),
        contratto=contratto,
    )
    return {
        "oggetti": [_rif(fattura, nuovo=True), *_contratti_della_fattura(fattura)],
    }


def _oggetti_multipli(argomenti: dict) -> list:
    pks = list(dict.fromkeys(argomenti["fatture_ids"]))
    trovate = {f.pk: f for f in m.Fattura.objects.filter(pk__in=pks)}
    if mancanti := [pk for pk in pks if pk not in trovate]:
        raise ErroreTool(f"Fatture inesistenti: {mancanti}. Cercarle con «elenco_fatture».")
    return [trovate[pk] for pk in pks]


def _multipla(esegui):
    """Operazione su più fatture (D15): esito fattura per fattura; la conferma applica solo
    quelle che passano (le altre sono rifiutate di nuovo, per lo stesso motivo)."""

    def applica(ctx: Contesto, argomenti: dict) -> dict:
        pks = list(dict.fromkeys(argomenti["fatture_ids"]))
        esito = esegui(ctx, pks, argomenti)
        righe = [{"id": f.pk, "numero": f.numero, "esito": "applicata"} for f in esito.fatte] + [
            {"id": f.pk, "numero": f.numero, "esito": "rifiutata", "motivo": motivo}
            for f, motivo in esito.rifiutate
        ]
        if not esito.fatte:
            motivi = "; ".join(f"{r['numero']}: {r['motivo']}" for r in righe)
            raise ErroreTool(f"Nessuna fattura da modificare (nessuna modifica). {motivi}")
        ordine = {pk: i for i, pk in enumerate(pks)}
        return {
            "oggetti": [{"tipo": "fattura", "id": f.pk} for f in esito.fatte],
            "esito_per_fattura": sorted(righe, key=lambda r: ordine[r["id"]]),
        }

    return applica


def _azione_fattura(esegui):
    def applica(ctx: Contesto, argomenti: dict) -> dict:
        f = _fattura(argomenti)
        prima = f.contratto_id
        esegui(ctx, f, argomenti)
        return {"oggetti": [_rif(f), *_contratti_della_fattura(f, prima)]}

    return applica


def _riassegna(ctx: Contesto, f: m.Fattura, argomenti: dict) -> None:
    username = argomenti["username"].strip()
    utente = get_user_model().objects.filter(username__iexact=username, is_active=True).first()
    if utente is None:
        raise ErroreTool(f"Utente sconosciuto o non attivo: {username}.")
    form = ff.RiassegnaForm({"utente": utente.pk})
    valida(form)
    fatture.riassegna(f, form.cleaned_data["utente"], ctx.utente)


def _assegna_contratto(ctx: Contesto, f: m.Fattura, argomenti: dict) -> None:
    if argomenti.get("scollega"):
        if "contratto_id" in argomenti:
            raise ErroreTool("Con «scollega» non si indica il contratto.")
        fatture.assegna_contratto(f, None)
        return
    if "contratto_id" not in argomenti:
        raise ErroreTool("Indicare «contratto_id» oppure «scollega».")
    form = ff.ContrattoFatturaForm(
        {"contratto": argomenti["contratto_id"], "voce": argomenti.get("voce_id", "")},
        fattura=f,
    )
    valida(form)
    fatture.assegna_contratto(f, form.cleaned_data["contratto"], form.cleaned_data["voce"])


def _convalida(ctx: Contesto, f: m.Fattura, argomenti: dict) -> None:
    istanza = m.Fattura.objects.get(pk=f.pk)
    form = ff.ConvalidaForm(_dati(ff.ConvalidaForm, istanza, argomenti), instance=istanza)
    valida(form)
    d = form.cleaned_data
    fatture.convalida(f, d["esito_convalida"], d["nota_convalida"], d["bloccata_fino_al"])


def _importi(ctx: Contesto, f: m.Fattura, argomenti: dict) -> None:
    # Come il form dell'interfaccia: valori attuali, valore base proposto se manca.
    dati = {
        "valore_base": f.valore_base
        if f.valore_base is not None
        else motore.valore_base_proposto(f.importo_documento, f.oneri, f.bollo, f.altri_importi),
        "oneri": f.oneri,
        "bollo": f.bollo,
        "iva": f.iva,
        "altri_importi": f.altri_importi,
        "competenza_dal": f.competenza_dal,
        "competenza_al": f.competenza_al,
        "voce": f.voce_id,
        "rata": f.rata_id,
        "conto": f.conto_id,
        "centro_costo": f.centro_costo,
        "wbs": f.wbs_id,
    }
    for campo, chiave in (("valore_base",) * 2, ("oneri",) * 2, ("bollo",) * 2, ("iva",) * 2,
                          ("altri_importi",) * 2, ("competenza_dal",) * 2, ("competenza_al",) * 2,
                          ("voce", "voce_id"), ("rata", "rata_id"), ("conto", "conto_id"),
                          ("centro_costo",) * 2, ("wbs", "wbs_id")):  # fmt: skip
        if chiave in argomenti:
            dati[campo] = argomenti[chiave]
    form = ff.ImportiForm({k: _form_valore(v) for k, v in dati.items()}, fattura=f)
    valida(form)
    aliquota = None
    if "scorpora_iva" in argomenti:  # come il pulsante «Scorpora IVA» dell'interfaccia
        try:
            aliquota = Decimal(argomenti["scorpora_iva"])
        except InvalidOperation:
            raise ErroreTool("«scorpora_iva»: aliquota non valida, es. «22».") from None
    fatture.salva_importi(f, form.cleaned_data, aliquota)


def _documento(ctx: Contesto, f: m.Fattura, argomenti: dict) -> None:
    form = ff.DocumentoFatturaForm(
        {
            "tipo": argomenti["tipo"],
            "numero": argomenti["numero"],
            "data": argomenti.get("data", ctx.oggi),
        }
    )
    valida(form)
    d = form.cleaned_data
    fatture.registra_documento(f, d["tipo"], d["numero"], d["data"])


def _trasferisci(ctx: Contesto, f: m.Fattura, argomenti: dict) -> None:
    if argomenti.get("annulla"):
        fatture.annulla_trasferimento(f)
        return
    form = ff.TrasferimentoForm({"data": argomenti.get("data", ctx.oggi)})
    valida(form)
    fatture.trasferisci(f, ctx.utente, form.cleaned_data["data"])


# --- Esecuzione del contratto ------------------------------------------------------------------


def _contratto(argomenti: dict) -> m.Contratto:
    return trova(
        m.Contratto.objects.select_related("fabbisogno"), argomenti["contratto_id"], "contratto"
    )


def _documento_esecuzione(ctx: Contesto, argomenti: dict) -> dict:
    contratto = _contratto(argomenti)
    if contratto.data_chiusura is not None:
        raise ErroreTool("Il contratto è chiuso: prima si annulla la chiusura.")
    dati = {
        "tipo": argomenti["tipo"],
        "numero": argomenti.get("numero", ""),
        "data": argomenti["data"],
        "importo": argomenti.get("importo", ""),
        "voce": argomenti.get("voce_id", ""),
        "finale": argomenti.get("finale", False),
        "note": "",
    }
    form = ff.DocumentoEsecuzioneForm(dati, contratto=contratto)
    valida(form)
    doc = form.save(commit=False)
    doc.contratto = contratto
    doc._change_reason = "Registrato dal contratto"
    doc.save()
    return {"oggetti": [_rif(contratto)]}


# --- Stanziamenti (SPEC Rev22) ----------------------------------------------------------------


def _registra_stanziamento(ctx: Contesto, argomenti: dict) -> dict:
    contratto = _contratto(argomenti)
    if contratto.data_chiusura is not None:
        raise ErroreTool("Il contratto è chiuso: prima si annulla la chiusura.")
    dati = {
        "voce": argomenti["voce_id"],
        "rata": argomenti.get("rata_id", ""),
        "importo": argomenti["importo"],
        "competenza_dal": argomenti["competenza_dal"],
        "competenza_al": argomenti["competenza_al"],
        "note": "",
    }
    form = ff.StanziamentoForm({k: _form_valore(v) for k, v in dati.items()}, contratto=contratto)
    valida(form)
    stanziamento = form.save(commit=False)
    stanziamento._change_reason = "Stanziamento registrato dal contratto"
    stanziamento.save()
    return {"oggetti": [_rif(contratto)]}


def _oggetti_rate(argomenti: dict) -> list:
    pks = list(dict.fromkeys(argomenti["rate_ids"]))
    if len(pks) > MASSIMO_FATTURE:
        raise ErroreTool(f"Al massimo {MASSIMO_FATTURE} rate per volta.")
    trovate = {
        r.pk: r for r in m.Rata.objects.filter(pk__in=pks).select_related("piano__voce__contratto")
    }
    if mancanti := [pk for pk in pks if pk not in trovate]:
        raise ErroreTool(f"Rate inesistenti: {mancanti}. Cercarle con «stanziamenti».")
    return [trovate[pk] for pk in pks]


def _stanzia_rate(ctx: Contesto, argomenti: dict) -> dict:
    contratti = {}
    for rata in _oggetti_rate(argomenti):
        servizi_stanziamenti.conferma(rata, ctx.utente, ctx.oggi)
        contratto = rata.piano.voce.contratto
        contratti[contratto.pk] = contratto
    return {"oggetti": [_rif(c) for c in contratti.values()]}


def _stanziamento(argomenti: dict) -> m.Stanziamento:
    return trova(
        m.Stanziamento.objects.select_related("voce__contratto__fabbisogno"),
        argomenti["id"],
        "stanziamento",
    )


def _chiudi_stanziamento(ctx: Contesto, argomenti: dict) -> dict:
    s = _stanziamento(argomenti)
    contratto = s.voce.contratto
    form = ff.ChiudiStanziamentoForm({"fattura": argomenti["fattura_id"]}, contratto=contratto)
    valida(form)
    s.fattura = form.cleaned_data["fattura"]
    s._change_reason = "Chiuso dalla fattura"
    s.save(update_fields=["fattura"])
    return {"oggetti": [_rif(contratto)]}


def _annulla_stanziamento(ctx: Contesto, argomenti: dict) -> dict:
    s = _stanziamento(argomenti)
    s.archiviato = True
    s._change_reason = "Stanziamento annullato"
    s.save(update_fields=["archiviato"])
    return {"oggetti": [_rif(s.voce.contratto)]}


def _chiusura(chiudi: bool):
    def applica(ctx: Contesto, argomenti: dict) -> dict:
        contratto = _contratto(argomenti)
        if chiudi:
            acquisti.chiudi(contratto, ctx.utente)
        else:
            acquisti.annulla_chiusura(contratto)
        oggetti = [_rif(contratto)]
        if contratto.rda_id:
            oggetti.append({"tipo": "richiestaacquisto", "id": contratto.rda_id})
        return {"oggetti": oggetti}

    return applica


# --- Schemi -------------------------------------------------------------------------------


def _schema(proprieta: dict, obbligatori: list[str] | None = None) -> dict:
    schema = {"type": "object", "properties": proprieta, "additionalProperties": False}
    if obbligatori:
        schema["required"] = obbligatori
    return schema


SCHEMA_TESTO_LIBERO = {"type": "string", "maxLength": 2000}
SCHEMA_POSIZIONE = {
    "type": "object",
    "properties": {
        "numero": {
            "type": "integer",
            "minimum": 1,
            "description": "Solo in «modifica_rda»: posizione salvata da cambiare. Senza "
            "numero la posizione si aggiunge in fondo.",
        },
        "descrizione_breve": {"type": "string", "maxLength": 40,
                              "description": "Al massimo 40 caratteri (limite di SAP)."},
        "gruppo_merci": {"type": "string", "maxLength": 20,
                         "description": "Codice del gruppo merci («riferimenti»)."},
        "quantita": {"type": "string", "maxLength": 20,
                     "description": "Quantità, stringa decimale con il punto: «2.5»."},
        "importo_unitario": SCHEMA_IMPORTO,
        "di_cui_variabile": SCHEMA_IMPORTO,
        "natura": {"type": "string", "enum": list(m.Natura.values)},
        "conto": {**SCHEMA_ID, "description": "id del conto («riferimenti»)."},
        "centro_costo": {"type": "string", "maxLength": 20,
                         "description": "Codice del centro di costo («riferimenti»)."},
        "wbs": {**SCHEMA_ID, "description": "id della WBS, solo CAPEX («riferimenti»)."},
    },
    "additionalProperties": False,
}  # fmt: skip
CAMPI_RICHIESTA = {
    "descrizione": {"type": "string", "minLength": 1, "maxLength": 250},
    "intestazione": {"type": "string", "maxLength": 40,
                     "description": "Al massimo 40 caratteri (limite di SAP)."},
    "fornitore_proposto": {**SCHEMA_ID, "description": "id del fornitore (tool «cerca»)."},
    "richiedente": {"type": "string", "maxLength": 20,
                    "description": "Codice del richiedente SAP («riferimenti»); senza "
                    "«gruppo_acquisti» si usa quello della sua unità."},
    "gruppo_acquisti": {"type": "string", "maxLength": 20,
                        "description": "Codice del gruppo acquisti («riferimenti»)."},
    "note_buyer": SCHEMA_TESTO_LIBERO,
    "allegati": SCHEMA_TESTO_LIBERO,
    "percorso_file_server": {"type": "string", "maxLength": 500},
    "rup": {"type": "string", "maxLength": 150},
    "cup": {"type": "string", "maxLength": 20},
    "posizioni": {"type": "array", "items": SCHEMA_POSIZIONE, "maxItems": 100},
    "invia": {"type": "boolean", "description": "Invia subito la richiesta all'addetto."},
}  # fmt: skip
SCHEMA_FATTURE = {
    "type": "array",
    "items": SCHEMA_ID,
    "minItems": 1,
    "maxItems": MASSIMO_FATTURE,
    "description": f"id delle fatture, al massimo {MASSIMO_FATTURE} per operazione.",
}
SOLO_ID = _schema({"id": SCHEMA_ID}, ["id"])
SOLO_CONTRATTO = _schema({"contratto_id": SCHEMA_ID}, ["contratto_id"])
MULTIPLA = (
    " Su più fatture (al massimo 50): l'anteprima elenca per ognuna se passa o è rifiutata e "
    "perché; la conferma applica solo quelle che passano. Se una fattura cambia dopo "
    "l'anteprima, la conferma è rifiutata per intero."
)


def _gestisce(utente, _f) -> bool:
    return fatture.gestisce(utente)


def _lascia_ammesso(utente, f) -> bool:
    return f.referente_id == utente.pk or fatture.gestisce(utente)


STRUMENTI = [
    # --- RDA ---
    strumento(
        _scrittura("crea_rda", lambda a: [_fabbisogno(a)], _crea_rda),
        "Nuova richiesta di RDA",
        "Prepara la richiesta di RDA dal fabbisogno, come la pagina «Nuova richiesta»: scopo, "
        "contratto in scadenza, intestazione, campi SAP e posizioni proposti dal fabbisogno se "
        "non indicati (le posizioni indicate sostituiscono quelle proposte). Referente: "
        "l'utente. Resta in bozza, o con «invia» va all'addetto. L'anteprima riporta fase, "
        "stato della pratica e testo della richiesta.",
        _schema(
            {
                "fabbisogno_id": SCHEMA_ID,
                "aggiuntivo": {
                    "type": "boolean",
                    "description": "Acquisto aggiuntivo (una tantum).",
                },
                "contratto_in_scadenza_id": {**SCHEMA_ID, "description": "Contratto da rinnovare."},
                **CAMPI_RICHIESTA,
            },
            ["fabbisogno_id"],
        ),  # fmt: skip
    ),
    strumento(
        _scrittura("modifica_rda", _oggetti_rda, _modifica_rda),
        "Modifica una richiesta di RDA",
        "Cambia solo i campi indicati della richiesta. Posizioni: con «numero» si modifica "
        "quella posizione nei soli campi passati, senza numero se ne aggiunge una; nessuna si "
        "cancella. Dopo l'invio è una correzione diretta, tracciata. Non per RDA annullate o "
        "chiuse.",
        _schema({"id": SCHEMA_ID, **CAMPI_RICHIESTA}, ["id"]),
    ),
    strumento(
        _scrittura(
            "invia_rda",
            _oggetti_rda,
            _azione_rda(lambda ctx, r, a: acquisti.invia(r, ctx.utente)),
        ),
        "Invia la richiesta di RDA",
        "Invia all'addetto una richiesta in bozza o da correggere.",
        SOLO_ID,
    ),
    strumento(
        _scrittura(
            "rimanda_rda",
            _oggetti_rda,
            _azione_rda(lambda ctx, r, a: acquisti.rimanda(r, a["nota"], ctx.utente)),
        ),
        "Rimanda la richiesta al referente",
        "L'addetto rimanda una richiesta inviata (non ancora in SAP), con la nota di cosa "
        "correggere.",
        _schema(
            {"id": SCHEMA_ID, "nota": {**SCHEMA_TESTO_LIBERO, "minLength": 1}}, ["id", "nota"]
        ),  # fmt: skip
    ),
    strumento(
        _scrittura(
            "annulla_rda",
            _oggetti_rda,
            _azione_rda(lambda ctx, r, a: acquisti.annulla(r, a["motivo"], ctx.utente)),
        ),
        "Annulla una RDA",
        "Annulla la RDA (non già annullata o chiusa) con il motivo. La pratica torna allo "
        "stato precedente.",
        _schema(
            {"id": SCHEMA_ID, "motivo": {**SCHEMA_TESTO_LIBERO, "minLength": 1}}, ["id", "motivo"]
        ),  # fmt: skip
    ),
    strumento(
        _scrittura("dati_sap_rda", _oggetti_rda, _dati_sap),
        "Dati SAP della RDA",
        "Registra numero della RDA (10 cifre), data di inserimento (vuota: oggi, se c'è il "
        "numero) e data dell'ultimo rilascio. Cambia solo i campi indicati. L'anteprima "
        "riporta fase, stato della pratica e i contratti con lo stesso n. RDA da collegare.",
        _schema(
            {
                "id": SCHEMA_ID,
                "numero_rda": {"type": "string", "maxLength": 20},
                "data_inserimento": SCHEMA_DATA,
                "data_rilascio": SCHEMA_DATA,
            },
            ["id"],
        ),
    ),
    strumento(
        _scrittura("registra_rda", lambda a: [], _registra_rda),
        "Registra una RDA già in SAP",
        "Registra a mano una RDA già inserita in SAP (migrazione), anche senza legami: poi si "
        "collega con «collega_rda». Numero della RDA obbligatorio.",
        _schema(
            {
                "cluster": {"type": "string", "maxLength": 10, "description": "Codice."},
                "descrizione": {"type": "string", "minLength": 1, "maxLength": 250},
                "fornitore_proposto": {**SCHEMA_ID, "description": "id del fornitore."},
                "referente": {
                    "type": "string",
                    "maxLength": 150,
                    "description": "Nome del referente (testo).",
                },
                "numero_rda": {"type": "string", "minLength": 1, "maxLength": 20},
                "data_inserimento": SCHEMA_DATA,
                "data_rilascio": SCHEMA_DATA,
                "percorso_file_server": {"type": "string", "maxLength": 500},
                "rup": {"type": "string", "maxLength": 150},
                "cup": {"type": "string", "maxLength": 20},
            },
            ["cluster", "descrizione", "numero_rda"],
        ),  # fmt: skip
    ),
    strumento(
        _scrittura("collega_rda", _oggetti_collega, _collega_rda),
        "Collega una RDA",
        "Operazione «pratica»: lega la RDA al contratto in scadenza (contratto_id) oppure al "
        "fabbisogno (fabbisogno_id); senza nessuno dei due la scollega (solo RDA registrate a "
        "mano). «contratto»: il contratto (contratto_id) è nato da questa RDA. "
        "«scollega_contratto»: toglie al contratto la RDA d'origine.",
        _schema(
            {
                "id": SCHEMA_ID,
                "operazione": {
                    "type": "string",
                    "enum": ["pratica", "contratto", "scollega_contratto"],
                },
                "contratto_id": SCHEMA_ID,
                "fabbisogno_id": SCHEMA_ID,
            },
            ["id", "operazione"],
        ),  # fmt: skip
    ),
    strumento(
        _scrittura(
            "registra_contratto_da_rda",
            lambda a: [*_oggetti_rda(a), *([_fabbisogno(a)] if "fabbisogno_id" in a else [])],
            _registra_contratto_da_rda,
        ),
        "Contratto emesso dalla RDA",
        "Registra il contratto emesso dal Procurement, precompilato dalla RDA come la pagina "
        "dell'interfaccia: fornitore, durata, procedura e fatturazione proposti (dal contratto "
        "in scadenza, se c'è, che ne diventa il predecessore); voci una per posizione. Cambia "
        "solo i campi indicati. Le rate si generano se la fatturazione lo consente. "
        "L'anteprima riporta date, alert, budget, previsti e la differenza dalla RDA.",
        _schema({"id": SCHEMA_ID, **CAMPI_CONTRATTO_DA_RDA}, ["id"]),
    ),
    # --- Fatture ---
    strumento(
        _scrittura(
            "registra_fattura",
            lambda a: [_contratto(a)] if "contratto_id" in a else [],
            _registra_fattura,
        ),
        "Registra una fattura",
        "Registra a mano una fattura (di norma arrivano dall'import settimanale): per "
        "fornitore, da prendere in carico, oppure dal contratto, già abbinata.",
        _schema(
            {
                "fornitore_id": SCHEMA_ID,
                "contratto_id": SCHEMA_ID,
                "numero": {"type": "string", "minLength": 1, "maxLength": 60},
                "data": SCHEMA_DATA,
                "importo_documento": SCHEMA_IMPORTO,
            },
            ["numero", "data", "importo_documento"],
        ),
    ),
    strumento(
        _scrittura(
            "prendi_in_carico",
            _oggetti_multipli,
            _multipla(lambda ctx, pks, a: fatture.prendi_in_carico(pks, ctx.utente)),
            controllo_fattura=False,
        ),
        "Prendi in carico fatture",
        "Prende in carico per l'utente una o più fatture; rifiutate quelle già in carico a "
        "qualcuno, fuori registro o archiviate." + MULTIPLA,
        _schema({"fatture_ids": SCHEMA_FATTURE}, ["fatture_ids"]),
    ),
    strumento(
        _scrittura(
            "segna_fuori_registro",
            _oggetti_multipli,
            _multipla(
                lambda ctx, pks, a: fatture.segna_fuori_registro(
                    pks, ctx.utente, a.get("fuori_registro", True)
                )
            ),
            controllo_fattura=False,
        ),
        "Fatture fuori registro",
        "Segna una o più fatture come non pertinenti al registro (o, con fuori_registro "
        "false, le rimette nel registro); rifiutate quelle di contratti di cluster non "
        "propri." + MULTIPLA,
        _schema(
            {"fatture_ids": SCHEMA_FATTURE, "fuori_registro": {"type": "boolean"}}, ["fatture_ids"]
        ),  # fmt: skip
    ),
    strumento(
        _scrittura(
            "assegna_ai_referenti_proposti",
            _oggetti_multipli,
            _multipla(lambda ctx, pks, a: fatture.assegna_ai_proposti(pks, ctx.utente)),
            controllo_fattura=False,
        ),
        "Assegna le fatture ai referenti proposti",
        "Solo Admin e addetto: assegna ogni fattura non in carico al suo referente proposto "
        "(ultima fattura dello stesso contratto, referente del contratto o della RDA); "
        "rifiutate quelle senza proposta." + MULTIPLA,
        _schema({"fatture_ids": SCHEMA_FATTURE}, ["fatture_ids"]),
    ),
    strumento(
        _scrittura(
            "lascia_fattura",
            _oggetti_fattura,
            _azione_fattura(lambda ctx, f, a: fatture.lascia(f, ctx.utente)),
            controllo_fattura=_lascia_ammesso,
        ),
        "Lascia una fattura",
        "La fattura torna tra quelle da prendere in carico (chi la ha in carico, Admin, addetto).",
        SOLO_ID,
    ),
    strumento(
        _scrittura(
            "riassegna_fattura",
            _oggetti_fattura,
            _azione_fattura(_riassegna),
            controllo_fattura=_gestisce,
        ),  # fmt: skip
        "Riassegna una fattura",
        "Solo Admin e addetto: assegna la fattura a un Admin o un Editor, indicato con lo "
        "username.",
        _schema(
            {"id": SCHEMA_ID, "username": {"type": "string", "minLength": 1, "maxLength": 150}},
            ["id", "username"],
        ),  # fmt: skip
    ),
    strumento(
        _scrittura(
            "assegna_contratto_fattura", _oggetti_fattura, _azione_fattura(_assegna_contratto)
        ),  # fmt: skip
        "Assegna la fattura al contratto",
        "Abbina la fattura a un contratto dello stesso fornitore, non chiuso (e alla voce; "
        "vuota: l'unica voce, se ce n'è una), oppure con «scollega» toglie il contratto. "
        "L'anteprima riporta passo, fatturato e residuo del contratto.",
        _schema(
            {
                "id": SCHEMA_ID,
                "contratto_id": SCHEMA_ID,
                "voce_id": SCHEMA_ID,
                "scollega": {"type": "boolean"},
            },
            ["id"],
        ),
    ),
    strumento(
        _scrittura(
            "convalida_fattura",
            _oggetti_fattura,
            _azione_fattura(_convalida),
            controllo_fattura=fatture.puo_convalidare,
        ),  # fmt: skip
        "Convalida una fattura",
        "Registra l'esito della convalida (chi ha la fattura in carico, o l'Admin). Nota "
        "obbligatoria per «non convalidabile» e «in attesa»; «bloccata_fino_al»: stanziata e "
        "bloccata fino a quella data. Cambia solo i campi indicati.",
        _schema(
            {
                "id": SCHEMA_ID,
                "esito_convalida": {"type": "string", "enum": list(m.Fattura.Esito.values)},
                "nota_convalida": SCHEMA_TESTO_LIBERO,
                "bloccata_fino_al": {
                    "type": ["string", "null"],
                    "format": "date",
                    "description": "null per togliere il blocco.",
                },
            },
            ["id"],
        ),
    ),
    strumento(
        _scrittura("importi_fattura", _oggetti_fattura, _azione_fattura(_importi)),
        "Importi della fattura",
        "Valore base prelevato dal contratto (di default quello proposto), oneri, bollo, IVA, "
        "altri importi (more, danni: non imputabili all'ufficio, tolti dal valore base); "
        "imputazione propria della fattura (conto, centro di costo, WBS) se diversa dalla voce; "
        "con il contratto anche voce e rata dello scadenzario, che diventa consuntivo con il "
        "numero di fattura. L'anteprima riporta anomalie (importo che non quadra), fatturato, "
        "residuo e il commento per PAC risultante.",
        _schema(
            {
                "id": SCHEMA_ID,
                "valore_base": SCHEMA_IMPORTO,
                "oneri": SCHEMA_IMPORTO,
                "bollo": SCHEMA_IMPORTO,
                "iva": {
                    **SCHEMA_IMPORTO,
                    "description": "IVA nell'importo del "
                    "documento; omessa: riconosciuta se è l'IVA di un'aliquota.",
                },
                "altri_importi": {
                    **SCHEMA_IMPORTO,
                    "description": "Altri importi (es. more/danni) in fattura e non "
                    "imputabili all'ufficio: si tolgono dal valore base.",
                },
                "scorpora_iva": {
                    "type": "string",
                    "maxLength": 6,
                    "description": "Aliquota da scorporare dall'importo del documento (es. "
                    "«22»): valore base e IVA calcolati; ignora «valore_base» e "
                    "«iva».",
                },
                "competenza_dal": {
                    **SCHEMA_DATA,
                    "description": "Inizio del periodo di competenza della fattura: decide "
                    "l'anno di budget. Obbligatorio, con «competenza_al», se la fattura ha "
                    "un valore base.",
                },
                "competenza_al": {**SCHEMA_DATA, "description": "Fine della competenza."},
                "voce_id": SCHEMA_ID,
                "rata_id": SCHEMA_ID,
                "conto_id": {
                    **SCHEMA_ID,
                    "description": "Imputazione propria della fattura, "
                    "se diversa dalla voce: id del conto («riferimenti»).",
                },
                "centro_costo": {
                    "type": "string",
                    "maxLength": 20,
                    "description": "Centro di costo della fattura, se diverso dalla voce; "
                    "stringa vuota per tornare a quello della voce.",
                },
                "wbs_id": {
                    **SCHEMA_ID,
                    "description": "WBS della fattura, se diversa dalla voce («riferimenti»).",
                },
            },
            ["id"],
        ),
    ),
    strumento(
        _scrittura("documento_fattura", _oggetti_fattura, _azione_fattura(_documento)),
        "Documento SAP della fattura",
        "Registra RdC (una per fattura), MAP o MIGO della fattura, sul suo contratto. "
        "L'anteprima riporta il passo e il commento per PAC risultante.",
        _schema(
            {
                "id": SCHEMA_ID,
                "tipo": {"type": "string", "enum": [Tipo.ODA, Tipo.MAP, Tipo.MIGO]},
                "numero": {"type": "string", "minLength": 1, "maxLength": 40},
                "data": SCHEMA_DATA,
            },
            ["id", "tipo", "numero"],
        ),
    ),
    strumento(
        _scrittura("trasferisci_fattura", _oggetti_fattura, _azione_fattura(_trasferisci)),
        "Trasferisci la fattura",
        "Ultimo passo: fattura trasferita per il pagamento (data, di default oggi); con "
        "«annulla» toglie il trasferimento.",
        _schema({"id": SCHEMA_ID, "data": SCHEMA_DATA, "annulla": {"type": "boolean"}}, ["id"]),
    ),
    # --- Esecuzione ---
    strumento(
        _scrittura("documento_esecuzione", lambda a: [_contratto(a)], _documento_esecuzione),
        "Documento di esecuzione del contratto",
        "Registra DDT, attestazione di regolare esecuzione, modello di ricezione (anche "
        "finale) o altro documento del contratto non chiuso. L'anteprima riporta il motivo "
        "«da chiudere».",
        _schema(
            {
                "contratto_id": SCHEMA_ID,
                "tipo": {"type": "string", "enum": list(Tipo.values)},
                "numero": {"type": "string", "maxLength": 40},
                "data": SCHEMA_DATA,
                "importo": SCHEMA_IMPORTO,
                "voce_id": SCHEMA_ID,
                "finale": {"type": "boolean"},
            },
            ["contratto_id", "tipo", "data"],
        ),
    ),
    strumento(
        _scrittura("registra_stanziamento", lambda a: [_contratto(a)], _registra_stanziamento),
        "Registra uno stanziamento",
        "Costo di competenza non ancora fatturato: voce, importo (imponibile), periodo di "
        "competenza e, se c'è, la rata dello scadenzario che sostituisce. Conta nel budget a "
        "competenza finché non arriva la fattura. Contratto non chiuso.",
        _schema(
            {
                "contratto_id": SCHEMA_ID,
                "voce_id": SCHEMA_ID,
                "importo": SCHEMA_IMPORTO,
                "competenza_dal": SCHEMA_DATA,
                "competenza_al": SCHEMA_DATA,
                "rata_id": SCHEMA_ID,
            },
            ["contratto_id", "voce_id", "importo", "competenza_dal", "competenza_al"],
        ),
    ),
    strumento(
        _scrittura("stanzia_rate", _oggetti_rate, _stanzia_rate),
        "Stanzia le rate scadute",
        "Conferma la proposta di stanziamento di una o più rate scadute senza fattura "
        "(«stanziamenti»): importo e competenza sono quelli proposti. Al massimo 50 rate; se "
        "una non è più da stanziare l'operazione è rifiutata.",
        _schema(
            {"rate_ids": {"type": "array", "items": SCHEMA_ID, "minItems": 1, "maxItems": 50}},
            ["rate_ids"],
        ),
    ),
    strumento(
        _scrittura("chiudi_stanziamento", lambda a: [_stanziamento(a)], _chiudi_stanziamento),
        "Chiudi lo stanziamento con la fattura",
        "Indica la fattura arrivata (dello stesso contratto): sostituisce lo stanziamento nel "
        "budget a competenza.",
        _schema({"id": SCHEMA_ID, "fattura_id": SCHEMA_ID}, ["id", "fattura_id"]),
    ),
    strumento(
        _scrittura("annulla_stanziamento", lambda a: [_stanziamento(a)], _annulla_stanziamento),
        "Annulla lo stanziamento",
        "Archivia lo stanziamento: esce dal budget (la rata torna alla previsione).",
        _schema({"id": SCHEMA_ID}, ["id"]),
    ),
    strumento(
        _scrittura("chiudi_contratto", lambda a: [_contratto(a)], _chiusura(True)),
        "Chiudi il contratto",
        "Chiusura amministrativa del contratto (oggi). L'anteprima riporta la fase della RDA "
        "d'origine e le anomalie (es. chiuso senza attestazione).",
        SOLO_CONTRATTO,
    ),
    strumento(
        _scrittura("annulla_chiusura", lambda a: [_contratto(a)], _chiusura(False)),
        "Annulla la chiusura del contratto",
        "Riapre un contratto chiuso.",
        SOLO_CONTRATTO,
    ),
]
