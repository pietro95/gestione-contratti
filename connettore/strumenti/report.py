"""Tool di report: budget, piano ordini, spese per WBS, piani da verificare (SPEC_MCP §5).

Calcolati con le stesse funzioni dei report web ed export: per gli stessi filtri e la stessa
data i totali coincidono al centesimo (SPEC_MCP §5, vincolo verificabile). OPEX e CAPEX sono
budget distinti: si restituiscono in sezioni separate, mai sommati.
"""

from decimal import Decimal
from urllib.parse import urlencode

from accounts.roles import WRITE_ROLES
from contratti import models as m
from contratti import selettori
from contratti.engine.tipi import Livello
from reports.budget import ETICHETTE_VISTE, LIVELLI, PARTI, VISTE, Filtri, calcola_budget
from reports.piano_ordini import calcola_piano
from reports.wbs import elenco_wbs, spese_wbs

from .base import (
    SCHEMA_CLUSTER,
    SCHEMA_ID,
    SCHEMA_PAGINA,
    Contesto,
    ErroreTool,
    Strumento,
    cluster_filtro,
    link,
    oggetto,
    pagina,
)

ZERO = Decimal("0.00")

# Nomi delle viste per il modello: quelli dell'interfaccia, non quelli interni (SPEC §5.2).
NOMI_VISTE = {"cassa": "fatturato", "impegno": "ordinato", "competenza": "competenza"}
DA_NOME_VISTA = {v: k for k, v in NOMI_VISTE.items()}
RAGGRUPPAMENTI = {"conto": "conto", "cluster": "area", "fornitore": "fornitore", "wbs": "wbs"}
RAGGRUPPAMENTI["fabbisogno"] = "fabbisogno"
# Valori del filtro «WBS a progetto» del report (reports.budget.PROGETTI).
PROGETTI_TOOL = {"escluse": "", "incluse": "includi", "solo": "solo"}
SCHEMA_ANNO = {"type": "integer", "minimum": 2000, "maximum": 2100}
SCHEMA_LIVELLO = {
    "type": "string",
    "enum": [liv.value for liv in Livello],
    "description": "fisso (solo quota fissa), probabile (con la stima di consumo), massimo.",
}


def _livello(argomenti: dict) -> Livello:
    return Livello(argomenti.get("livello") or Livello.PROBABILE)


def _per_vista(somme, livello: Livello) -> dict:
    """{vista: {parte: importo}} al livello dato."""
    return {
        NOMI_VISTE[vista]: {parte: somme[parte][vista][livello] for parte in PARTI}
        for vista in VISTE
    }


def _tutti_i_livelli(somme) -> dict:
    """{vista: {parte: {livello: importo}}}."""
    return {
        NOMI_VISTE[vista]: {
            parte: {liv.value: somme[parte][vista][liv] for liv in LIVELLI} for parte in PARTI
        }
        for vista in VISTE
    }


def _voce_budget(vb, livello: Livello) -> dict:
    return {
        "previsionale": vb.previsionale,
        "numero_previsto": vb.numero_previsto,
        "fabbisogno": {"id": vb.fabbisogno.pk, "descrizione": vb.fabbisogno.descrizione},
        "contratto_id": vb.contratto.pk if vb.contratto else None,
        "voce": vb.descrizione,
        "fornitore": vb.fornitore.ragione_sociale if vb.fornitore else None,
        "conto": vb.conto.codice if vb.conto else None,
        "wbs": vb.wbs.codice_wbs if vb.wbs else None,
        "inizio": vb.inizio,
        "fine": vb.fine,
        "importi": {NOMI_VISTE[v]: vb.importi[v][livello] for v in VISTE},
    }


def budget(ctx: Contesto, argomenti: dict) -> dict:
    codici = cluster_filtro(ctx.utente, argomenti.get("cluster"))
    livello = _livello(argomenti)
    filtri = Filtri(
        anno=argomenti.get("anno", ctx.oggi.year),
        area=tuple(codici),
        conto=argomenti.get("conto"),
        fornitore=argomenti.get("fornitore"),
        wbs=argomenti.get("wbs"),
        progetti=PROGETTI_TOOL[argomenti.get("wbs_a_progetto", "escluse")],
        previsionali=argomenti.get("previsti", True),
        natura=argomenti.get("natura", ""),
    )
    b = calcola_budget(filtri, ctx.oggi)
    per = argomenti.get("raggruppa_per")
    sezioni = []
    for s in b.sezioni():
        natura = s.filtri.natura
        criterio = RAGGRUPPAMENTI[per] if per else ("wbs" if natura == m.Natura.CAPEX else "conto")
        sezione = {
            "natura": natura,
            "totale": _tutti_i_livelli(s.totali()),
            "raggruppato_per": criterio if criterio != "area" else "cluster",
            "gruppi": [
                {
                    "chiave": g.chiave,
                    "etichetta": g.etichetta,
                    "importi": _per_vista(g.totali, livello),
                    "n_voci": len(g.voci),
                    **(
                        {"voci": [_voce_budget(v, livello) for v in g.voci]}
                        if argomenti.get("dettaglio_voci")
                        else {}
                    ),
                }
                for g in s.gruppi(criterio)
            ],
            "rinnovi_mancanti": [
                {
                    "fabbisogno": {"id": r.fabbisogno.pk, "descrizione": r.fabbisogno.descrizione},
                    "previsti_esclusi": r.previsti_esclusi,
                    "dal": r.dal,
                    "al": r.al,
                }
                for r in s.rinnovi_mancanti
            ],
            "avvisi": [
                {"messaggio": messaggio, "voci": voci[:10], "n_voci": len(voci)}
                for messaggio, voci in s.avvisi.items()
            ],
        }
        sezioni.append(sezione)
    query = [("anno", filtri.anno), ("natura", filtri.natura or "separate")]
    query += [("area", c) for c in codici] or [("area", "tutti")]
    return {
        "alla_data": ctx.oggi,
        "anno": filtri.anno,
        "filtri": {
            "cluster": codici or "tutti",
            "natura": filtri.natura or "OPEX e CAPEX, separati",
            "conto": filtri.conto,
            "fornitore": filtri.fornitore,
            "wbs": filtri.wbs,
            "wbs_a_progetto": argomenti.get("wbs_a_progetto", "escluse"),
            "previsti": filtri.previsionali,
            "livello_dei_gruppi": livello.value,
        },
        "viste": {NOMI_VISTE[v]: ETICHETTE_VISTE[v] for v in VISTE},
        "avvertenza": (
            "OPEX e CAPEX sono budget distinti: non sommarli. Il fatturato (data fattura) è il "
            "budget di riferimento. «previsionale» sono i rinnovi previsti, non ancora "
            "contrattualizzati."
        ),
        "sezioni": sezioni,
        "contratti_senza_data_inizio": b.senza_data,
        "link": link("reports:budget") + "?" + urlencode(query),
    }


# --- piano ordini ------------------------------------------------------------------------


def _riga_piano(r) -> dict:
    uscente = r.contratto_uscente
    return {
        "fabbisogno": {"id": r.fabbisogno.pk, "descrizione": r.fabbisogno.descrizione},
        "cluster": r.fabbisogno.cluster.codice,
        "categoria": r.categoria.nome,
        "contratto_uscente_id": uscente.pk if uscente else None,
        "fornitore_uscente": r.fornitore_uscente.ragione_sociale if r.fornitore_uscente else None,
        "numero_previsto": r.numero_previsto,
        "procedura": r.procedura.nome if r.procedura else None,
        "lead_time_mesi": r.lead_time_mesi,
        "data_limite_avvio": r.data_limite,
        "avvio_servizio": r.avvio,
        "fine": r.fine,
        "durata_mesi": r.durata_mesi,
        "stato_pratica": r.stato_pratica_label,
        "natura": r.natura,
        "importi": {liv.value: r.importi[liv] for liv in LIVELLI},
        "importi_per_natura": {
            natura: {liv.value: imp[liv] for liv in LIVELLI} for natura, imp in r.per_natura.items()
        },
        "su_wbs_a_progetto": r.a_progetto,
        "sopra_soglia": r.sopra_soglia,
    }


def piano_ordini(ctx: Contesto, argomenti: dict) -> dict:
    codici = cluster_filtro(ctx.utente, argomenti.get("cluster"))
    anno = argomenti.get("anno", ctx.oggi.year)
    natura = argomenti.get("natura", "")
    p = calcola_piano(
        anno, ctx.oggi, area=tuple(codici), categoria=argomenti.get("categoria"), natura=natura
    )
    righe = sorted(p.righe, key=lambda r: (r.data_limite, r.fabbisogno.descrizione))
    porzione, info = pagina(righe, argomenti)
    totali = {natura: p.totali(natura)} if natura else p.totali_per_natura()
    query = [("anno", anno), *([("area", c) for c in codici] or [("area", "tutti")])]
    return {
        "alla_data": ctx.oggi,
        "anno": anno,
        "filtri": {
            "cluster": codici or "tutti",
            "categoria": argomenti.get("categoria"),
            "natura": natura or "OPEX e CAPEX",
        },
        "nota": (
            "Una riga per ogni contratto previsto con avvio del servizio nell'anno. Importi "
            "sull'intera durata, imponibile IVA esclusa. I rinnovi senza contratto non ci sono "
            "(non passano dal Procurement). OPEX e CAPEX si totalizzano separati."
        ),
        "totali_per_natura": {
            n: {liv.value: imp[liv] for liv in LIVELLI} for n, imp in totali.items()
        },
        "avvisi_frazionamento": [
            {
                "tipo": a.tipo,
                "nome": a.nome,
                "soglia": {"descrizione": a.soglia.descrizione, "importo": a.soglia.importo},
                "totale_massimo": a.totale_massimo,
                "fabbisogni": [r.fabbisogno.pk for r in a.righe],
            }
            for a in p.avvisi
        ],
        "righe": [_riga_piano(r) for r in porzione],
        **info,
        "link": link("reports:piano_ordini") + "?" + urlencode(query),
    }


# --- spese per WBS -----------------------------------------------------------------------


def _wbs(argomenti: dict) -> m.WBS:
    if "wbs_id" in argomenti:
        return oggetto(m.WBS.objects.select_related("cluster"), argomenti["wbs_id"], "WBS")
    try:
        return m.WBS.objects.select_related("cluster").get(codice_wbs=argomenti["codice_wbs"])
    except m.WBS.DoesNotExist:
        raise ErroreTool(
            f"Nessuna WBS con codice {argomenti['codice_wbs']}: senza argomenti il tool elenca "
            "le WBS."
        ) from None


def spese_per_wbs(ctx: Contesto, argomenti: dict) -> dict:
    if "wbs_id" not in argomenti and "codice_wbs" not in argomenti:
        codici = cluster_filtro(ctx.utente, argomenti.get("cluster"))
        elenco = list(elenco_wbs(codici, argomenti.get("tipo", "")))
        porzione, info = pagina(elenco, argomenti)
        return {
            "alla_data": ctx.oggi,
            "filtri": {"cluster": codici or "tutti", "tipo": argomenti.get("tipo") or "tutti"},
            "nota": "Di default le WBS dei cluster dell'utente e tutte le WBS a progetto.",
            "wbs": [
                {
                    "id": w.pk,
                    "codice": w.codice_wbs,
                    "descrizione": w.descrizione,
                    "tipo": w.tipo,
                    "cluster": w.cluster.codice if w.cluster_id else None,
                    "n_voci": w.n_voci,
                }
                for w in porzione
            ],
            **info,
            "link": link("reports:wbs"),
        }
    wbs = _wbs(argomenti)
    vista = DA_NOME_VISTA[argomenti.get("vista", "fatturato")]
    livello = _livello(argomenti)
    s = spese_wbs(wbs, vista, livello)
    return {
        "alla_data": ctx.oggi,
        "wbs": {
            "id": wbs.pk,
            "codice": wbs.codice_wbs,
            "descrizione": wbs.descrizione,
            "tipo": wbs.tipo,
            "cluster": wbs.cluster.codice if wbs.cluster_id else None,
        },
        "vista": NOMI_VISTE[vista],
        "livello": livello.value,
        "nota": "Solo contratti registrati, niente previsti: spesa sostenuta o impegnata.",
        "righe": [
            {
                "contratto": {
                    "id": r.contratto.pk,
                    "descrizione": r.contratto.descrizione or r.contratto.fabbisogno.descrizione,
                    "fornitore": r.contratto.fornitore.ragione_sociale,
                },
                "voce": {"id": r.voce.pk, "descrizione": r.voce.descrizione},
                "inizio": r.inizio,
                "fine": r.fine,
                "per_anno": {str(a): imp for a, imp in r.per_anno.items()},
            }
            for r in s.righe
        ],
        "totali_per_anno": {str(a): imp for a, imp in s.totali().items()},
        "totale": s.totale,
        "contratti_esclusi_senza_data": s.esclusi,
        "link": link("reports:wbs_spese", wbs.pk) + "?" + urlencode({"vista": vista}),
    }


# --- piani da verificare -----------------------------------------------------------------


def piani_da_verificare(ctx: Contesto, argomenti: dict) -> dict:
    codici = cluster_filtro(ctx.utente, argomenti.get("cluster"))
    voci = list(selettori.voci_piano_da_verificare(codici))
    porzione, info = pagina(voci, argomenti)
    return {
        "alla_data": ctx.oggi,
        "filtri": {"cluster": codici or "tutti"},
        "nota": (
            "Voci senza piano di fatturazione reale: il loro fatturato nel budget è un pro-rata "
            "a giorni. Le più pesanti (fisso + massimale) prima."
        ),
        "totale_peso": sum((v.peso for v in voci), ZERO),
        "voci": [
            {
                "id": v.pk,
                "descrizione": v.descrizione,
                "contratto_id": v.contratto_id,
                "fabbisogno": v.contratto.fabbisogno.descrizione,
                "fornitore": v.contratto.fornitore.ragione_sociale,
                "importo_fisso": v.importo_fisso,
                "massimale_variabile": v.massimale_variabile,
                "peso": v.peso,
                "link": link("contratti:contratto", v.contratto_id),
            }
            for v in porzione
        ],
        **info,
        "link": link("contratti:piani_da_verificare"),
    }


STRUMENTI = [
    Strumento(
        nome="budget",
        titolo="Budget dell'anno",
        descrizione=(
            "Budget di un anno nelle tre viste: fatturato (per data fattura, riferimento del "
            "Controllo di gestione), ordinato (contratti emessi nell'anno), competenza "
            "(pro-rata a giorni). Per ogni vista consolidato (contratti registrati), "
            "previsionale (rinnovi previsti) e totale; livelli fisso, probabile, massimo. OPEX "
            "e CAPEX in sezioni separate, mai sommate. Gruppi di default: conto per l'OPEX, WBS "
            "per il CAPEX. Le voci su WBS a progetto (es. dissalatori) sono escluse se non "
            "richieste. Segnala i rinnovi mancanti."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "anno": SCHEMA_ANNO,
                "natura": {"type": "string", "enum": list(m.Natura.values)},
                "cluster": SCHEMA_CLUSTER,
                "conto": {**SCHEMA_ID, "description": "id del conto (tool «riferimenti»)."},
                "fornitore": {**SCHEMA_ID, "description": "id del fornitore (tool «cerca»)."},
                "wbs": {**SCHEMA_ID, "description": "id della WBS (tool «riferimenti»)."},
                "wbs_a_progetto": {"type": "string", "enum": list(PROGETTI_TOOL)},
                "previsti": {"type": "boolean"},
                "raggruppa_per": {"type": "string", "enum": list(RAGGRUPPAMENTI)},
                "livello": SCHEMA_LIVELLO,
                "dettaglio_voci": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        esegui=budget,
    ),
    Strumento(
        nome="piano_ordini",
        titolo="Piano ordini dell'anno",
        descrizione=(
            "Il piano per il Procurement: una riga per ogni contratto da rinnovare o nuovo con "
            "avvio del servizio nell'anno, con procedura presunta, lead time, data limite di "
            "avvio della procedura, stato della pratica, natura e importo stimato sull'intera "
            "durata. Avvisi di possibile frazionamento quando più fabbisogni della stessa "
            "categoria o dello stesso fornitore superano una soglia. Ordinato per data limite."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "anno": SCHEMA_ANNO,
                "cluster": SCHEMA_CLUSTER,
                "categoria": {**SCHEMA_ID, "description": "id della categoria («riferimenti»)."},
                "natura": {"type": "string", "enum": list(m.Natura.values)},
                **SCHEMA_PAGINA,
            },
            "additionalProperties": False,
        },
        esegui=piano_ordini,
    ),
    Strumento(
        nome="spese_wbs",
        titolo="Spese per WBS",
        descrizione=(
            "Senza «wbs_id» né «codice_wbs»: elenco delle WBS (di cluster e a progetto) con il "
            "numero di voci. Con una WBS: i contratti con voci su quella WBS e gli importi anno "
            "per anno nella vista e al livello scelti (default fatturato, probabile). Solo "
            "contratti registrati."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "wbs_id": SCHEMA_ID,
                "codice_wbs": {"type": "string", "minLength": 1, "maxLength": 40},
                "vista": {"type": "string", "enum": list(DA_NOME_VISTA)},
                "livello": SCHEMA_LIVELLO,
                "cluster": SCHEMA_CLUSTER,
                "tipo": {"type": "string", "enum": list(m.WBS.Tipo.values)},
                **SCHEMA_PAGINA,
            },
            "additionalProperties": False,
        },
        esegui=spese_per_wbs,
    ),
    Strumento(
        nome="piani_da_verificare",
        titolo="Piani di fatturazione da verificare",
        descrizione=(
            "Voci con piano di fatturazione «Da verificare» o assente: nel budget il loro "
            "fatturato è stimato a pro-rata. Le più pesanti prima. Riservato ad Admin ed Editor."
        ),
        input_schema={
            "type": "object",
            "properties": {"cluster": SCHEMA_CLUSTER, **SCHEMA_PAGINA},
            "additionalProperties": False,
        },
        esegui=piani_da_verificare,
        ruoli=WRITE_ROLES,
    ),
]
