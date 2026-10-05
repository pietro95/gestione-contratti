"""Tool di dettaglio: contratto, fabbisogno, fornitore, scadenzario (SPEC_MCP §5).

Gli stessi dati delle pagine dell'interfaccia, calcolati con gli stessi adapter. Niente
referenti né note libere (minimizzazione, SPEC_MCP §5).
"""

from decimal import Decimal

from accounts.roles import WRITE_ROLES
from contratti import adapters, selettori
from contratti import models as m
from contratti.engine import scadenze as motore_scadenze
from contratti.engine.budget import valore
from contratti.engine.tipi import Livello

from .base import (
    SCHEMA_ID,
    SCHEMA_PAGINA,
    Contesto,
    ErroreTool,
    Strumento,
    link,
    oggetto,
    pagina,
    versione,
)
from .ricerca import contratto_breve

ZERO = Decimal("0.00")


def _livelli(voci_engine) -> dict[str, Decimal]:
    return {liv.value: sum((valore(v, liv) for v in voci_engine), ZERO) for liv in Livello}


def _previsto(p) -> dict:
    return {
        "numero": p.numero,
        "inizio": p.inizio,
        "fine": p.fine,
        "importi": _livelli(p.voci),
    }


def _riferimento(oggetto_, testo_importato: str = "") -> dict | None:
    if oggetto_ is not None:
        codice = getattr(oggetto_, "codice", None) or getattr(oggetto_, "codice_wbs", "")
        return {"id": oggetto_.pk, "codice": codice, "descrizione": oggetto_.descrizione}
    if testo_importato:
        return {"id": None, "codice": testo_importato, "descrizione": "(come importato)"}
    return None


def _piano(voce: m.VoceContratto) -> dict | None:
    piano = getattr(voce, "piano_fatturazione", None)
    if piano is None:
        return None
    return {
        "modalita": piano.modalita,
        "periodicita": piano.periodicita or None,
        "data_prima_fattura": piano.data_prima_fattura,
        "giorni_pagamento": piano.giorni_pagamento,
        "pagamento_fine_mese": piano.pagamento_fine_mese,
    }


def _voce(voce: m.VoceContratto, valori: dict | None) -> dict:
    return {
        "id": voce.pk,
        "descrizione": voce.descrizione,
        "proroga": {"id": voce.proroga_id, "nuova_data_fine": voce.proroga.nuova_data_fine}
        if voce.proroga_id
        else None,
        "natura": voce.natura,
        "conto": _riferimento(voce.conto, voce.codice_conto_importato),
        "wbs": _riferimento(voce.wbs, voce.codice_wbs_importato),
        "centro_costo": voce.centro_costo or None,
        "rinnovi": {
            "natura": voce.natura_rinnovi or None,
            "conto": _riferimento(voce.conto_rinnovi),
            "wbs": _riferimento(voce.wbs_rinnovi),
        },
        "importo_fisso": voce.importo_fisso,
        "massimale_variabile": voce.massimale_variabile,
        "stima_consumo_pct": voce.stima_consumo_pct,
        "stima_consumo_importo": voce.stima_consumo_importo,
        "quote_per_periodo": [
            {"dal": q.dal, "al": q.al, "importo": q.importo} for q in voce.quote.all()
        ],
        "piano_fatturazione": _piano(voce),
        # Valore della voce ai tre livelli (fisso + variabile), dal motore; None se la voce
        # non è calcolabile (es. contratto senza data di inizio).
        "valori": {liv.value: imp for liv, imp in valori.items()} if valori else None,
        "versione": versione(voce),
    }


# --- contratto ---------------------------------------------------------------------------


def contratto(ctx: Contesto, argomenti: dict) -> dict:
    try:
        c = selettori.contratti_base().get(pk=argomenti["id"])
    except m.Contratto.DoesNotExist:
        raise ErroreTool(f"Nessun contratto con id {argomenti['id']}: usare «cerca».") from None
    riga = selettori.riga_contratto(c, ctx.oggi, selettori.finestra_alert(ctx.oggi))
    s = adapters.scadenza(c)
    voci_engine, esiti = adapters.voci_contratto(c)
    valori = {v.riferimento: {liv: valore(v, liv) for liv in Livello} for v in voci_engine}
    voci = (
        c.voci.filter(archiviato=False)
        .select_related("conto", "proroga", "piano_fatturazione", "wbs")
        .select_related("conto_rinnovi", "wbs_rinnovi")
        .prefetch_related("quote")
    )
    successore = m.Contratto.objects.filter(predecessore=c).first() or c.confluito_in
    catena = selettori.catena(c)
    return {
        "alla_data": ctx.oggi,
        **contratto_breve(riga),
        "versione": versione(c),
        "numero_rda": c.numero_rda,
        "data_emissione": c.data_emissione,
        "data_stipula": c.data_stipula,
        "durata_mesi": c.durata_mesi,
        "data_fine_contrattuale": motore_scadenze.data_fine_contrattuale(s) if s else None,
        "data_limite": riga.data_limite,
        "giorni_al_limite": riga.giorni_al_limite,
        "procedura": {"nome": c.procedura.nome, "lead_time_mesi": s.lead_time_mesi if s else None},
        "tacito_rinnovo": c.tacito_rinnovo,
        "data_ultima_disdetta": motore_scadenze.data_ultima_disdetta(s) if s else None,
        "natura": c.natura,
        "finanziamento": c.finanziamento,
        "stato_pratica": riga.stato_pratica_label,
        "storico_pratica": [
            {"stato": p.get_stato_display(), "data": p.data} for p in c.stati_pratica.all()
        ],
        "catena": [
            {
                "id": x.pk,
                "numero_contratto": x.numero_contratto,
                "data_inizio": x.data_inizio,
                "data_fine": adapters.data_fine_effettiva(x),
                "questo": x.pk == c.pk,
            }
            for x in catena
        ],
        "successore": successore.pk if successore else None,
        "confluito_in": c.confluito_in_id,
        "confluiti": [x.pk for x in c.confluiti.order_by("data_inizio")],
        "proroghe": [
            {
                "data_atto": p.data_atto,
                "nuova_data_fine": p.nuova_data_fine,
                "riferimento": p.riferimento,
            }
            for p in c.proroghe.order_by("data_atto")
        ],  # fmt: skip
        "opzioni": [
            {"tipo": o.tipo, "mesi": o.mesi, "importo": o.importo} for o in c.opzioni.all()
        ],
        "voci": [_voce(v, valori.get(v.pk)) for v in voci],
        "totali": {liv.value: sum((x[liv] for x in valori.values()), ZERO) for liv in Livello},
        "previsti": [_previsto(p) for p in selettori.previsti_dopo(c, ctx.oggi)],
        "avvisi": [{"codice": e.codice, "messaggio": e.messaggio} for e in esiti],
    }


# --- fabbisogno --------------------------------------------------------------------------


def fabbisogno(ctx: Contesto, argomenti: dict) -> dict:
    f = oggetto(
        m.Fabbisogno.objects.select_related(
            "cluster", "categoria", "impianto", "previsto_procedura", "conto_previsti"
        ).select_related("wbs_previsti"),
        argomenti["id"],
        "fabbisogno",
    )
    righe = selettori.righe_contratti(
        selettori.contratti_base().filter(fabbisogno=f).order_by("data_inizio"), ctx.oggi
    )
    previsti = adapters.previsti_fabbisogno(f, adapters.orizzonte_default(ctx.oggi))
    base = adapters.contratto_base_previsti(f)
    return {
        "alla_data": ctx.oggi,
        "id": f.pk,
        "versione": versione(f),
        "descrizione": f.descrizione,
        "cluster": f.cluster.codice,
        "categoria": f.categoria.nome,
        "impianto": f.impianto.nome if f.impianto_id else None,
        "decisione": f.decisione,
        "stima_prossimo_importo": f.stima_prossimo_importo,
        "archiviato": f.archiviato,
        "previsto_manuale": {
            "data_avvio": f.previsto_data_avvio,
            "durata_mesi": f.previsto_durata_mesi,
            "procedura": f.previsto_procedura.nome if f.previsto_procedura_id else None,
            "modalita": f.previsto_modalita or None,
            "periodicita": f.previsto_periodicita or None,
            "natura": f.natura_previsti or None,
            "conto": _riferimento(f.conto_previsti),
            "wbs": _riferimento(f.wbs_previsti),
        }
        if f.previsto_data_avvio
        else None,
        "contratti": [
            {
                **contratto_breve(r),
                "data_limite": r.data_limite,
                "stato_pratica": r.stato_pratica_label,
            }
            for r in righe
        ],
        "contratto_base_previsti": base.pk if base else None,
        "natura_previsti": adapters.natura_previsti(f, base),
        "previsti": [_previsto(p) for p in previsti],
        "storico_pratica": [
            {"stato": p.get_stato_display(), "data": p.data}
            for p in f.stati_pratica.order_by("-data", "-id")
        ],
        "link": link("contratti:fabbisogno", f.pk),
    }


# --- fornitore ---------------------------------------------------------------------------


def fornitore(ctx: Contesto, argomenti: dict) -> dict:
    f = oggetto(m.Fornitore.objects, argomenti["id"], "fornitore")
    righe = selettori.righe_contratti(
        selettori.contratti_base().filter(fornitore=f).order_by("-data_inizio"), ctx.oggi
    )
    porzione, info = pagina(righe, argomenti)
    return {
        "alla_data": ctx.oggi,
        "id": f.pk,
        "versione": versione(f),
        "ragione_sociale": f.ragione_sociale,
        "partita_iva": f.partita_iva,
        "codice_sap": f.codice_sap or None,
        "archiviato": f.archiviato,
        "stesso_codice_sap": [
            {"id": x.pk, "ragione_sociale": x.ragione_sociale}
            for x in f.fornitori_stesso_codice_sap()
        ],
        "contratti": [contratto_breve(r) for r in porzione],
        **info,
        "link": link("contratti:fornitore", f.pk),
    }


# --- scadenzario -------------------------------------------------------------------------


def scadenzario(ctx: Contesto, argomenti: dict) -> dict:
    if ("contratto_id" in argomenti) == ("voce_id" in argomenti):
        raise ErroreTool("Indicare «contratto_id» oppure «voce_id», non entrambi.")
    if "voce_id" in argomenti:
        voce = oggetto(m.VoceContratto.objects, argomenti["voce_id"], "voce")
        c = voce.contratto
        voci = [voce]
    else:
        c = oggetto(m.Contratto.objects, argomenti["contratto_id"], "contratto")
        voci = list(c.voci.filter(archiviato=False).order_by("pk"))
    uscita = []
    for v in voci:
        piano = getattr(v, "piano_fatturazione", None)
        rate = list(piano.rate.order_by("numero")) if piano else []
        totale = sum((r.importo for r in rate), ZERO)
        uscita.append(
            {
                "voce": {"id": v.pk, "descrizione": v.descrizione},
                "piano_fatturazione": _piano(v),
                "importo_fisso": v.importo_fisso,
                "rate": [
                    {
                        "numero": r.numero,
                        "data_fattura": r.data_fattura,
                        "data_pagamento_stimata": r.data_pagamento_stimata,
                        "importo": r.importo,
                        "consuntivo": r.consuntivo,
                        "numero_fattura": r.numero_fattura or None,
                        "modificata_a_mano": r.modificata_manualmente,
                    }
                    for r in rate
                ],
                "totale_rate": totale,
                # Le rate contengono solo la quota fissa (SPEC §4): devono sommare al fisso.
                "quadra_con_il_fisso": totale == v.importo_fisso if rate else None,
            }
        )
    return {
        "alla_data": ctx.oggi,
        "contratto": {"id": c.pk, "descrizione": c.descrizione or c.fabbisogno.descrizione},
        "voci": uscita,
        "nota": (
            "Pagamento stimato solo informativo; il budget usa la data della fattura. "
            "Piani A SAL o Da verificare non hanno rate generate."
        ),
        "link": link("contratti:contratto", c.pk),
    }


STRUMENTI = [
    Strumento(
        nome="contratto",
        titolo="Dettaglio di un contratto",
        descrizione=(
            "Tutto il contratto: riferimenti (numero, CIG, RDA), date (inizio, fine effettiva e "
            "contrattuale, data limite di avvio del rinnovo, ultima disdetta), procedura e lead "
            "time, alert e stato della pratica, catena dei rinnovi, proroghe, opzioni, voci con "
            "classificazione (natura, conto, WBS), piano di fatturazione e valori ai livelli "
            "fisso, probabile, massimo; rinnovi previsti se è il contratto da cui partono."
        ),
        input_schema={
            "type": "object",
            "properties": {"id": SCHEMA_ID},
            "required": ["id"],
            "additionalProperties": False,
        },
        esegui=contratto,
    ),
    Strumento(
        nome="fabbisogno",
        titolo="Dettaglio di un fabbisogno",
        descrizione=(
            "Il servizio ricorrente: cluster, categoria, decisione di continuità, stima del "
            "prossimo importo, previsto manuale, catena dei contratti con date e alert, "
            "rinnovi previsti calcolati (date e importi ai tre livelli) e storico della "
            "pratica. Un fabbisogno senza previsti con decisione «Rinnovare» va segnalato."
        ),
        input_schema={
            "type": "object",
            "properties": {"id": SCHEMA_ID},
            "required": ["id"],
            "additionalProperties": False,
        },
        esegui=fabbisogno,
    ),
    Strumento(
        nome="fornitore",
        titolo="Dettaglio di un fornitore",
        descrizione=(
            "Anagrafica del fornitore (partita IVA, codice SAP, altri fornitori con lo stesso "
            "codice SAP) e i suoi contratti, dal più recente. Per gli importi per anno usare "
            "«budget» con il filtro «fornitore». Riservato ad Admin ed Editor."
        ),
        input_schema={
            "type": "object",
            "properties": {"id": SCHEMA_ID, **SCHEMA_PAGINA},
            "required": ["id"],
            "additionalProperties": False,
        },
        esegui=fornitore,
        ruoli=WRITE_ROLES,
    ),
    Strumento(
        nome="scadenzario",
        titolo="Scadenzario delle rate",
        descrizione=(
            "Rate di un contratto (tutte le voci) o di una voce: data fattura, pagamento "
            "stimato, importo della quota fissa, consuntivo, rate modificate a mano."
        ),
        input_schema={
            "type": "object",
            "properties": {"contratto_id": SCHEMA_ID, "voce_id": SCHEMA_ID},
            "additionalProperties": False,
        },
        esegui=scadenzario,
    ),
]
