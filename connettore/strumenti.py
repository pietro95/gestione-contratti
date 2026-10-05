"""Tool del connettore MCP (SPEC_MCP §5). Sola lettura, sopra selettori e report esistenti.

Ogni tool riceve argomenti già validati con il suo ``input_schema`` e restituisce un
``dict`` che ``serializza.in_json`` porta in JSON. I numeri vengono dal motore, attraverso
gli stessi selettori delle viste: il connettore non ha una logica sua.
"""

import datetime
from collections.abc import Callable
from dataclasses import dataclass, field

from django.conf import settings
from django.urls import reverse

from contratti import models as m
from contratti import permessi, selettori
from contratti.engine.tipi import Alert
from reports.piano_ordini import soglie_valide

LIMITE_DEFAULT = 25
LIMITE_MASSIMO = 100


class ErroreTool(Exception):
    """Errore che il modello deve vedere (oggetto inesistente, filtro incoerente)."""


@dataclass
class Contesto:
    utente: object
    oggi: datetime.date


@dataclass(frozen=True)
class Strumento:
    nome: str
    titolo: str
    descrizione: str
    input_schema: dict
    esegui: Callable[[Contesto, dict], dict]
    annotazioni: dict = field(default_factory=lambda: {"readOnlyHint": True})

    def descrittore(self) -> dict:
        return {
            "name": self.nome,
            "title": self.titolo,
            "description": self.descrizione,
            "inputSchema": self.input_schema,
            "annotations": {"title": self.titolo, **self.annotazioni},
        }


def link(nome_url: str, *args) -> str:
    """Indirizzo della pagina nell'app (host interno), perché l'utente verifichi.

    Dalla URLconf interna: nel container pubblico le pagine dell'interfaccia non esistono.
    """
    return f"{settings.MCP_URL_INTERNO}{reverse(nome_url, args=args, urlconf='config.urls')}"


def _pagina(elementi: list, argomenti: dict) -> tuple[list, dict]:
    limite = argomenti.get("limite", LIMITE_DEFAULT)
    try:
        inizio = int(argomenti.get("cursore") or 0)
    except ValueError:
        raise ErroreTool("«cursore» non valido: usare «cursore_successivo».") from None
    if inizio < 0:
        raise ErroreTool("«cursore» non valido: usare «cursore_successivo».")
    pagina = elementi[inizio : inizio + limite]
    fine = inizio + len(pagina)
    info = {"totale": len(elementi), "troncato": fine < len(elementi)}
    if info["troncato"]:
        info["cursore_successivo"] = str(fine)
    return pagina, info


def _cluster_filtro(utente, valori: list[str] | None) -> list[str]:
    """Come la tendina «Cluster»: di default i propri, «tutti» per tutti (F9.2)."""
    codici = permessi.codici_filtro(utente, valori or [])
    noti = set(m.Cluster.objects.values_list("codice", flat=True))
    if ignoti := [c for c in codici if c not in noti]:
        raise ErroreTool(f"Cluster sconosciuti: {', '.join(ignoti)}. Vedi il tool «riferimenti».")
    return codici


SCHEMA_CLUSTER = {
    "type": "array",
    "items": {"type": "string", "minLength": 1, "maxLength": 10},
    "description": (
        "Codici dei cluster (es. IT, TLC). Vuoto o «miei»: i cluster dell'utente; "
        "«tutti»: tutti i cluster."
    ),
}
SCHEMA_PAGINA = {
    "limite": {"type": "integer", "minimum": 1, "maximum": LIMITE_MASSIMO},
    "cursore": {
        "type": "string",
        "maxLength": 10,
        "description": "Valore di «cursore_successivo» della pagina precedente.",
    },
}


# --- riferimenti -------------------------------------------------------------------------


def riferimenti(ctx: Contesto, argomenti: dict) -> dict:
    propri = {c.codice for c in permessi.cluster_propri(ctx.utente)}
    return {
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


def _contratto_breve(riga: selettori.RigaContratto) -> dict:
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
        uscita["contratti"] = [_contratto_breve(r) for r in risultati["contratti"]]
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
        **_contratto_breve(riga),
        "data_limite": riga.data_limite,
        "giorni_al_limite": riga.giorni_al_limite,
        "procedura": c.procedura.nome,
        "stato_pratica": riga.stato_pratica_label,
    }


ALERT_SCADENZE = [Alert.ROSSO.value, Alert.ARANCIONE.value, Alert.GIALLO.value]


def scadenze(ctx: Contesto, argomenti: dict) -> dict:
    codici = _cluster_filtro(ctx.utente, argomenti.get("cluster"))
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
    pagina, info = _pagina(righe, argomenti)
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
        "righe": [_riga_scadenza(r) for r in pagina],
        **info,
        "link": link("contratti:cruscotto"),
    }


STRUMENTI = {
    s.nome: s
    for s in [
        Strumento(
            nome="riferimenti",
            titolo="Tabelle di riferimento",
            descrizione=(
                "Cluster (con quelli dell'utente), categorie dei fabbisogni, procedure di "
                "affidamento con il lead time in mesi e soglie d'importo valide oggi. Da "
                "chiamare per conoscere i codici da usare nei filtri degli altri tool."
            ),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            esegui=riferimenti,
        ),
        Strumento(
            nome="cerca",
            titolo="Cerca nel registro",
            descrizione=(
                "Ricerca testuale su contratti (descrizione, fabbisogno, numero di contratto, "
                "CIG, RDA, fornitore), fabbisogni e fornitori (ragione sociale, partita IVA, "
                "codice SAP). Tutti i cluster. Al massimo 25 contratti, 15 fabbisogni e 15 "
                "fornitori: se servono di più, restringere il testo. Gli importi sono "
                "imponibili, IVA esclusa."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "testo": {"type": "string", "minLength": 2, "maxLength": 100},
                    "tipo": {"type": "string", "enum": ["contratti", "fabbisogni", "fornitori"]},
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
}
