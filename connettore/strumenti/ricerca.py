"""Tool di ricerca: riferimenti, cerca, scadenze (SPEC_MCP §5).

Ogni tool riceve argomenti già validati con il suo ``input_schema`` e restituisce un
``dict`` che ``serializza.in_json`` porta in JSON. I numeri vengono dal motore, attraverso
gli stessi selettori delle viste: il connettore non ha una logica sua.
"""

import datetime

from django.db.models import Q

from contratti import models as m
from contratti import permessi, selettori
from contratti.engine.tipi import Alert
from reports.piano_ordini import soglie_valide

from .base import (
    SCHEMA_CLUSTER,
    SCHEMA_PAGINA,
    Contesto,
    Strumento,
    cluster_filtro,
    link,
    pagina,
)

# --- riferimenti -------------------------------------------------------------------------


def _conti_e_wbs(ctx: Contesto, argomenti: dict) -> dict:
    includi = argomenti.get("includi") or []
    codici = cluster_filtro(ctx.utente, argomenti.get("cluster"))
    uscita = {}
    if "conti" in includi:
        conti = m.ContoCoge.objects.select_related("cluster").order_by("codice", "-valido_dal")
        conti = conti.filter(valido_dal__lte=ctx.oggi).filter(
            Q(valido_al__isnull=True) | Q(valido_al__gte=ctx.oggi)
        )
        if codici:
            conti = conti.filter(cluster__codice__in=codici)
        uscita["conti"] = [
            {
                "id": c.pk,
                "codice": c.codice,
                "descrizione": c.descrizione,
                "cluster": c.cluster.codice if c.cluster_id else None,
            }
            for c in conti
        ]
    if "wbs" in includi:
        wbs = m.WBS.objects.filter(archiviato=False).select_related("cluster")
        if codici:
            wbs = wbs.filter(Q(tipo=m.WBS.Tipo.PROGETTO) | Q(cluster__codice__in=codici))
        uscita["wbs"] = [
            {
                "id": w.pk,
                "codice": w.codice_wbs,
                "descrizione": w.descrizione,
                "tipo": w.tipo,
                "cluster": w.cluster.codice if w.cluster_id else None,
            }
            for w in wbs.order_by("tipo", "codice_wbs")
        ]
    if uscita:
        uscita["cluster_filtro"] = codici or "tutti"
    return uscita


def riferimenti(ctx: Contesto, argomenti: dict) -> dict:
    propri = {c.codice for c in permessi.cluster_propri(ctx.utente)}
    return {
        **_conti_e_wbs(ctx, argomenti),
        "alla_data": ctx.oggi,
        "cluster": [
            {"codice": c.codice, "nome": c.nome, "proprio": c.codice in propri}
            for c in m.Cluster.objects.filter(archiviato=False)
        ],
        "cluster_propri_definiti": bool(propri),
        "categorie": [
            {"id": c.pk, "nome": c.nome} for c in m.Categoria.objects.filter(attiva=True)
        ],
        "procedure": [
            {"codice": p.codice, "nome": p.nome, "lead_time_mesi": p.lead_time_mesi}
            for p in m.Procedura.objects.filter(attiva=True)
        ],
        # F12.1 (SPEC_MCP §11.2): tabelle del processo d'acquisto.
        "richiedenti_sap": [
            {
                "codice": r.codice,
                "descrizione": r.descrizione,
                "predefinito": r.predefinito,
                # Gruppo acquisti della stessa unità: si propone con il richiedente.
                "gruppo_acquisti": r.gruppo_acquisti.codice if r.gruppo_acquisti_id else None,
            }
            for r in m.RichiedenteSAP.objects.filter(attivo=True).select_related("gruppo_acquisti")
        ],
        "gruppi_acquisti": [
            {"codice": g.codice, "descrizione": g.descrizione, "predefinito": g.predefinito}
            for g in m.GruppoAcquisti.objects.filter(attivo=True)
        ],
        "gruppi_merci": [
            {
                "codice": g.codice,
                "descrizione": g.descrizione,
                "predefinito": g.predefinito,
                "categoria": g.categoria.nome if g.categoria_id else None,
            }
            for g in m.GruppoMerci.objects.filter(attivo=True).select_related("categoria")
        ],  # fmt: skip
        "tipi_acquisto": [{"codice": v, "nome": n} for v, n in m.Contratto.TipoAcquisto.choices],
        "scopi_rda": [{"codice": v, "nome": n} for v, n in m.RichiestaAcquisto.Scopo.choices],
        "soglie": [
            {
                "codice": s.codice,
                "descrizione": s.descrizione,
                "importo": s.importo,
                "valida_dal": s.valida_dal,
                "valida_al": s.valida_al,
            }
            for s in soglie_valide(ctx.oggi)
        ],
    }


# --- cerca -------------------------------------------------------------------------------


def contratto_breve(riga: selettori.RigaContratto) -> dict:
    c = riga.contratto
    return {
        "id": c.pk,
        "descrizione": c.descrizione or c.fabbisogno.descrizione,
        "fabbisogno": {"id": c.fabbisogno_id, "descrizione": c.fabbisogno.descrizione},
        "cluster": c.fabbisogno.cluster.codice,
        "fornitore": c.fornitore.ragione_sociale,
        "numero_contratto": c.numero_contratto,
        "cig": c.cig,
        "senza_contratto": c.senza_contratto,
        "data_inizio": c.data_inizio,
        "data_fine": riga.fine,
        "stato": riga.stato,
        "alert": riga.alert,
        "archiviato": c.archiviato,
        "link": link("contratti:contratto", c.pk),
    }


def cerca(ctx: Contesto, argomenti: dict) -> dict:
    risultati = selettori.cerca(argomenti["testo"], ctx.oggi)
    tipo = argomenti.get("tipo")
    uscita = {"alla_data": ctx.oggi, "testo": argomenti["testo"]}
    if tipo in (None, "contratti"):
        uscita["contratti"] = [contratto_breve(r) for r in risultati["contratti"]]
    if tipo in (None, "fabbisogni"):
        uscita["fabbisogni"] = [
            {
                "id": f.pk,
                "descrizione": f.descrizione,
                "cluster": f.cluster.codice,
                "categoria": f.categoria.nome,
                "decisione": f.decisione,
                "archiviato": f.archiviato,
                "link": link("contratti:fabbisogno", f.pk),
            }
            for f in risultati["fabbisogni"]
        ]
    if tipo in (None, "fornitori"):
        uscita["fornitori"] = [
            {
                "id": f.pk,
                "ragione_sociale": f.ragione_sociale,
                "partita_iva": f.partita_iva,
                "codice_sap": f.codice_sap,
                "archiviato": f.archiviato,
                "link": link("contratti:fornitore", f.pk),
            }
            for f in risultati["fornitori"]
        ]
    # F12.1 (SPEC_MCP §11.2): RDA e fatture, come la ricerca globale.
    if tipo in (None, "rda"):
        uscita["rda"] = [
            {
                "id": r.pk,
                "numero_rda": r.numero_rda,
                "descrizione": r.intestazione or r.descrizione,
                "cluster": r.cluster.codice,
                "archiviata": r.archiviato,
                "link": link("contratti:rda", r.pk),
            }
            for r in risultati["rda"]
        ]
    if tipo in (None, "fatture"):
        uscita["fatture"] = [
            {
                "id": f.pk,
                "numero": f.numero,
                "data": f.data,
                "fornitore": f.fornitore.ragione_sociale,
                "contratto": f.contratto_id,
                "archiviata": f.archiviato,
                "link": link("contratti:fattura", f.pk),
            }
            for f in risultati["fatture"]
        ]
    uscita["limiti"] = selettori.LIMITE_CERCA
    return uscita


# --- scadenze ----------------------------------------------------------------------------


def _riga_scadenza(riga: selettori.RigaContratto) -> dict:
    if riga.previsto_manuale is not None:
        f = riga.previsto_manuale
        procedura = f.previsto_procedura
        return {
            "tipo": "previsto_manuale",
            "alert": riga.alert,
            "fabbisogno": {"id": f.pk, "descrizione": f.descrizione},
            "cluster": f.cluster.codice if f.cluster_id else None,
            "data_avvio_prevista": riga.fine,
            "data_limite": riga.data_limite,
            "giorni_al_limite": riga.giorni_al_limite,
            "procedura": procedura.nome if procedura else None,
            "stato_pratica": riga.stato_pratica_label,
            "link": link("contratti:fabbisogno", f.pk),
        }
    c = riga.contratto
    return {
        "tipo": "contratto",
        "alert": riga.alert,
        **contratto_breve(riga),
        "data_limite": riga.data_limite,
        "giorni_al_limite": riga.giorni_al_limite,
        "procedura": c.procedura.nome,
        "stato_pratica": riga.stato_pratica_label,
    }


ALERT_SCADENZE = [Alert.ROSSO.value, Alert.ARANCIONE.value, Alert.GIALLO.value]


def scadenze(ctx: Contesto, argomenti: dict) -> dict:
    codici = cluster_filtro(ctx.utente, argomenti.get("cluster"))
    filtri = {"area": codici, "categoria": argomenti.get("categoria") or ""}
    gruppi = selettori.cruscotto(ctx.oggi, filtri)
    colori = argomenti.get("alert") or ALERT_SCADENZE
    entro = argomenti.get("entro")
    entro = datetime.date.fromisoformat(entro) if entro else None
    righe = [
        r
        for colore in ALERT_SCADENZE
        if colore in colori
        for r in gruppi[Alert(colore)]
        if entro is None or (r.data_limite is not None and r.data_limite <= entro)
    ]
    porzione, info = pagina(righe, argomenti)
    return {
        "alla_data": ctx.oggi,
        "filtri": {
            "cluster": codici or "tutti",
            "alert": colori,
            "entro": entro,
            "categoria": argomenti.get("categoria"),
        },
        "legenda_alert": {
            "rosso": "scaduto senza rinnovo",
            "arancione": "data limite superata, pratica non avviata",
            "giallo": "in avvicinamento o pratica in corso",
        },
        "righe": [_riga_scadenza(r) for r in porzione],
        **info,
        "link": link("contratti:cruscotto"),
    }


STRUMENTI = [
    Strumento(
        nome="riferimenti",
        titolo="Tabelle di riferimento",
        descrizione=(
            "Cluster (con quelli dell'utente), categorie dei fabbisogni, procedure di "
            "affidamento con il lead time in mesi, soglie d'importo valide oggi; per le RDA "
            "richiedenti SAP, gruppi acquisti e gruppi merci (con il predefinito), tipi "
            "d'acquisto e scopi. Con "
            "«includi» anche i conti COGE validi oggi e le WBS (di default dei cluster "
            "dell'utente; le WBS a progetto sempre). Da chiamare per conoscere codici e id "
            "da usare nei filtri degli altri tool."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "includi": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["conti", "wbs"]},
                },
                "cluster": SCHEMA_CLUSTER,
            },
            "additionalProperties": False,
        },
        esegui=riferimenti,
    ),
    Strumento(
        nome="cerca",
        titolo="Cerca nel registro",
        descrizione=(
            "Ricerca testuale su contratti (descrizione, fabbisogno, numero di contratto, "
            "CIG, RDA, fornitore), fabbisogni e fornitori (ragione sociale, partita IVA, "
            "codice SAP), richieste di RDA (numero, descrizione) e fatture (numero, numeri di "
            "RdC, MAP e MIGO). Tutti i cluster. Al massimo 25 contratti e 15 per gli altri "
            "tipi: se servono di più, restringere il testo. Gli importi sono imponibili, IVA "
            "esclusa."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "testo": {"type": "string", "minLength": 2, "maxLength": 100},
                "tipo": {
                    "type": "string",
                    "enum": ["contratti", "fabbisogni", "fornitori", "rda", "fatture"],
                },
            },
            "required": ["testo"],
            "additionalProperties": False,
        },
        esegui=cerca,
    ),
    Strumento(
        nome="scadenze",
        titolo="Scadenze e alert",
        descrizione=(
            "Contratti e fabbisogni nuovi in alert, come nel cruscotto: rosso (scaduto "
            "senza rinnovo), arancione (data limite superata, pratica non avviata), "
            "giallo (in avvicinamento o pratica in corso). La data limite è la data di "
            "fine meno il lead time della procedura. Ordinati per gravità e data limite. "
            "«entro» tiene solo le righe con data limite fino a quella data."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "cluster": SCHEMA_CLUSTER,
                "alert": {
                    "type": "array",
                    "items": {"type": "string", "enum": ALERT_SCADENZE},
                },
                "entro": {"type": "string", "format": "date"},
                "categoria": {"type": "integer", "minimum": 1},
                **SCHEMA_PAGINA,
            },
            "additionalProperties": False,
        },
        esegui=scadenze,
    ),
]
