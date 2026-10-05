"""Validazione degli argomenti dei tool con il sottoinsieme di JSON Schema che usiamo.

Tipi ``object`` (con ``properties``, ``required``, ``additionalProperties: false``),
``string`` (``enum``, ``minLength``, ``maxLength``, ``format: date``), ``integer``
(``minimum``, ``maximum``), ``boolean`` e ``array`` di stringhe. Gli errori sono in
italiano, perché il modello li legge e corregge la chiamata.
"""

import datetime


class ArgomentiNonValidi(ValueError):
    pass


def _tipo(valore, tipo: str) -> bool:
    if tipo == "string":
        return isinstance(valore, str)
    if tipo == "integer":
        return isinstance(valore, int) and not isinstance(valore, bool)
    if tipo == "boolean":
        return isinstance(valore, bool)
    if tipo == "array":
        return isinstance(valore, list)
    if tipo == "object":
        return isinstance(valore, dict)
    raise ValueError(f"tipo di schema non gestito: {tipo}")


def _valida(valore, schema: dict, nome: str) -> None:
    tipo = schema["type"]
    if not _tipo(valore, tipo):
        raise ArgomentiNonValidi(f"«{nome}»: atteso {tipo}.")
    if "enum" in schema and valore not in schema["enum"]:
        ammessi = ", ".join(str(v) for v in schema["enum"])
        raise ArgomentiNonValidi(f"«{nome}»: valore non ammesso (ammessi: {ammessi}).")
    if tipo == "string":
        if len(valore) < schema.get("minLength", 0):
            raise ArgomentiNonValidi(f"«{nome}»: almeno {schema['minLength']} caratteri.")
        if "maxLength" in schema and len(valore) > schema["maxLength"]:
            raise ArgomentiNonValidi(f"«{nome}»: al massimo {schema['maxLength']} caratteri.")
        if schema.get("format") == "date":
            try:
                datetime.date.fromisoformat(valore)
            except ValueError:
                raise ArgomentiNonValidi(f"«{nome}»: data attesa nel formato AAAA-MM-GG.") from None
    if tipo == "integer":
        if "minimum" in schema and valore < schema["minimum"]:
            raise ArgomentiNonValidi(f"«{nome}»: almeno {schema['minimum']}.")
        if "maximum" in schema and valore > schema["maximum"]:
            raise ArgomentiNonValidi(f"«{nome}»: al massimo {schema['maximum']}.")
    if tipo == "array":
        for i, elemento in enumerate(valore):
            _valida(elemento, schema["items"], f"{nome}[{i}]")
    if tipo == "object":
        proprieta = schema.get("properties", {})
        for chiave in schema.get("required", []):
            if chiave not in valore:
                raise ArgomentiNonValidi(f"manca l'argomento obbligatorio «{chiave}».")
        for chiave, v in valore.items():
            if chiave not in proprieta:
                if schema.get("additionalProperties", True) is False:
                    raise ArgomentiNonValidi(f"argomento sconosciuto «{chiave}».")
                continue
            _valida(v, proprieta[chiave], chiave)


def valida(argomenti, schema: dict) -> dict:
    """Argomenti validati (un ``dict``), oppure ``ArgomentiNonValidi``."""
    if argomenti is None:
        argomenti = {}
    _valida(argomenti, schema, "arguments")
    return argomenti
