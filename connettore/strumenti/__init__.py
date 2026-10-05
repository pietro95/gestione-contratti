"""Tool del connettore MCP (SPEC_MCP §5, §8): lettura e, con lo scope, scrittura in due passi.

Ogni tool riceve argomenti già validati con il suo ``input_schema`` e restituisce un
``dict`` che ``serializza.in_json`` porta in JSON. I numeri vengono dal motore, attraverso
gli stessi selettori e report delle viste: il connettore non ha una logica sua.
"""

from . import dettagli, modifiche, modifiche_contratti, report, ricerca
from .base import Contesto, ErroreTool, Strumento

STRUMENTI: dict[str, Strumento] = {
    s.nome: s
    for s in [
        *ricerca.STRUMENTI,
        *dettagli.STRUMENTI,
        *report.STRUMENTI,
        *modifiche.STRUMENTI,
        *modifiche_contratti.STRUMENTI,
    ]
}


def ammessi(ctx: Contesto) -> list[Strumento]:
    """I tool che l'utente può usare: come le pagine dell'interfaccia; la scrittura solo con
    lo scope e l'interruttore acceso."""
    return [s for s in STRUMENTI.values() if s.ammesso(ctx)]


__all__ = ["STRUMENTI", "Contesto", "ErroreTool", "Strumento", "ammessi"]
