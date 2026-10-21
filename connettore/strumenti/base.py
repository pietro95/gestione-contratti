"""Basi comuni dei tool del connettore (SPEC_MCP §5): contesto, descrittore, aiuti."""

import datetime
from collections.abc import Callable
from dataclasses import dataclass, field

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse

from accounts.roles import role_of
from contratti import models as m
from contratti import permessi

LIMITE_DEFAULT = 25
LIMITE_MASSIMO = 100


class ErroreTool(Exception):
    """Errore che il modello deve vedere (oggetto inesistente, filtro incoerente)."""


@dataclass
class Contesto:
    utente: object
    oggi: datetime.date
    # Il collegamento ha lo scope di scrittura (SPEC_MCP §8.1, punto 2).
    scrittura: bool = False
    client_id: str = ""


@dataclass(frozen=True)
class Strumento:
    nome: str
    titolo: str
    descrizione: str
    input_schema: dict
    esegui: Callable[[Contesto, dict], dict]
    annotazioni: dict = field(default_factory=lambda: {"readOnlyHint": True})
    # Ruoli ammessi, come la pagina corrispondente dell'interfaccia; None = tutti.
    ruoli: frozenset | None = None
    # Tool di scrittura: servono anche lo scope e l'interruttore acceso (SPEC_MCP §8.1).
    scrittura: bool = False

    def ammesso(self, ctx: "Contesto") -> bool:
        if self.ruoli is not None and role_of(ctx.utente) not in self.ruoli:
            return False
        return not self.scrittura or (ctx.scrittura and scrittura_attiva(ctx.oggi))

    def descrittore(self) -> dict:
        return {
            "name": self.nome,
            "title": self.titolo,
            "description": self.descrizione,
            "inputSchema": self.input_schema,
            "annotations": {"title": self.titolo, **self.annotazioni},
        }


def scrittura_attiva(oggi: datetime.date) -> bool:
    """Interruttore generale della scrittura (parametro ``mcp_scrittura_attiva``)."""
    from contratti import adapters

    return adapters.parametro(m.Parametro.Chiave.MCP_SCRITTURA_ATTIVA, oggi) == 1


def link(nome_url: str, *args) -> str:
    """Indirizzo della pagina nell'app (host interno), perché l'utente verifichi.

    Dalla URLconf interna: nel container pubblico le pagine dell'interfaccia non esistono.
    """
    return f"{settings.MCP_URL_INTERNO}{reverse(nome_url, args=args, urlconf='config.urls')}"


def versione(oggetto) -> int | None:
    """Ultimo record della storia: serve alla scrittura per riconoscere modifiche nel frattempo."""
    ultimo = oggetto.history.order_by("-history_id").values_list("history_id", flat=True).first()
    return ultimo


def pagina(elementi: list, argomenti: dict) -> tuple[list, dict]:
    limite = argomenti.get("limite", LIMITE_DEFAULT)
    try:
        inizio = int(argomenti.get("cursore") or 0)
    except ValueError:
        raise ErroreTool("«cursore» non valido: usare «cursore_successivo».") from None
    if inizio < 0:
        raise ErroreTool("«cursore» non valido: usare «cursore_successivo».")
    porzione = elementi[inizio : inizio + limite]
    fine = inizio + len(porzione)
    info = {"totale": len(elementi), "troncato": fine < len(elementi)}
    if info["troncato"]:
        info["cursore_successivo"] = str(fine)
    return porzione, info


def cluster_filtro(utente, valori: list[str] | None) -> list[str]:
    """Come la tendina «Cluster»: di default i propri, «tutti» per tutti (F9.2)."""
    codici = permessi.codici_filtro(utente, valori or [])
    noti = set(m.Cluster.objects.values_list("codice", flat=True))
    if ignoti := [c for c in codici if c not in noti]:
        raise ErroreTool(f"Cluster sconosciuti: {', '.join(ignoti)}. Vedi il tool «riferimenti».")
    return codici


def sottocluster_filtro(valore: int | None) -> int | None:
    """Il filtro «sottocluster» degli strumenti di lettura: id esistente, o ``None`` = tutti."""
    if not valore:
        return None
    if not m.Sottocluster.objects.filter(pk=valore).exists():
        raise ErroreTool(f"Sottocluster sconosciuto: {valore}. Vedi il tool «riferimenti».")
    return valore


def oggetto(queryset, pk, nome: str):
    """L'oggetto con quell'id (da un manager o un queryset), o un errore leggibile."""
    try:
        return queryset.get(pk=pk)
    except ObjectDoesNotExist:
        raise ErroreTool(f"Nessun {nome} con id {pk}: cercarlo con il tool «cerca».") from None


SCHEMA_CLUSTER = {
    "type": "array",
    "items": {"type": "string", "minLength": 1, "maxLength": 10},
    "description": (
        "Codici dei cluster (es. IT, TLC). Vuoto o «miei»: i cluster dell'utente; "
        "«tutti»: tutti i cluster."
    ),
}
SCHEMA_SOTTOCLUSTER = {
    **{"type": "integer", "minimum": 1},
    "description": "id del sottocluster («riferimenti»); vuoto: tutti i sottocluster.",
}
SCHEMA_PAGINA = {
    "limite": {"type": "integer", "minimum": 1, "maximum": LIMITE_MASSIMO},
    "cursore": {
        "type": "string",
        "maxLength": 10,
        "description": "Valore di «cursore_successivo» della pagina precedente.",
    },
}
SCHEMA_ID = {"type": "integer", "minimum": 1}
