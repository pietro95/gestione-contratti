"""Conversione dei risultati in JSON per il connettore (SPEC_MCP §5).

Importi come stringhe con due decimali, date ISO. Un ``float`` è un errore: per il client un
numero JSON è un float, e i soldi non lo sono mai (CLAUDE.md, regola 3).
"""

import datetime
import enum
from decimal import ROUND_HALF_UP, Decimal

CENTESIMO = Decimal("0.01")


def importo(valore: Decimal | None) -> str | None:
    if valore is None:
        return None
    return str(Decimal(valore).quantize(CENTESIMO, rounding=ROUND_HALF_UP))


def in_json(valore):
    """Valore pronto per ``json.dumps``. Solleva ``TypeError`` per ``float`` e tipi ignoti."""
    if valore is None or isinstance(valore, bool | int | str):
        return valore
    if isinstance(valore, float):
        raise TypeError("float nel risultato di un tool: usare Decimal")
    if isinstance(valore, Decimal):
        return importo(valore)
    if isinstance(valore, datetime.datetime):
        return valore.isoformat()
    if isinstance(valore, datetime.date):
        return valore.isoformat()
    if isinstance(valore, enum.Enum):
        return in_json(valore.value)
    if isinstance(valore, dict):
        return {str(k): in_json(v) for k, v in valore.items()}
    if isinstance(valore, list | tuple):
        return [in_json(v) for v in valore]
    raise TypeError(f"tipo non serializzabile nel risultato di un tool: {type(valore).__name__}")
