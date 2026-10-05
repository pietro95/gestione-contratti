"""Tool del connettore MCP (SPEC_MCP §5). Sola lettura, sopra selettori e report esistenti.

Ogni tool riceve argomenti già validati con il suo ``input_schema`` e restituisce un
``dict`` che ``serializza.in_json`` porta in JSON. I numeri vengono dal motore, attraverso
gli stessi selettori e report delle viste: il connettore non ha una logica sua.
"""

from . import dettagli, report, ricerca
from .base import Contesto, ErroreTool, Strumento

STRUMENTI: dict[str, Strumento] = {
    s.nome: s for s in [*ricerca.STRUMENTI, *dettagli.STRUMENTI, *report.STRUMENTI]
}


def ammessi(utente) -> list[Strumento]:
    """I tool che l'utente può usare, come le pagine dell'interfaccia."""
    return [s for s in STRUMENTI.values() if s.ammesso(utente)]


__all__ = ["STRUMENTI", "Contesto", "ErroreTool", "Strumento", "ammessi"]
