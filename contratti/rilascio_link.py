"""Link «Rilascia ora» delle email di rilascio (SPEC §5.10, Rev43).

Il link porta un token firmato (``django.core.signing``, chiave ``SECRET_KEY``) che dice quale RDA
o quale documento (RdC, MAP) rilasciare, con scadenza (``RILASCIO_LINK_GIORNI``). Il token non dà
alcun potere da solo: la vista pretende il login e la funzione «Addetto al rilascio», quindi un
link inoltrato a chi non può rilasciare non fa niente. Il rilascio passa dagli stessi servizi
della maschera dei rilasci (``acquisti.rilascia_rda``, ``fatture.rilascia_documenti``).
"""

from django.conf import settings
from django.core import signing

SALT = "contratti.rilascio_da_email"
RDA = "rda"
DOCUMENTO = "documento"


class LinkNonValido(Exception):
    """Token alterato o non riconosciuto."""


class LinkScaduto(Exception):
    """Token valido ma oltre la scadenza."""


def crea(tipo: str, pk: int) -> str:
    if tipo not in (RDA, DOCUMENTO):
        raise ValueError(tipo)
    return signing.dumps({"t": tipo, "pk": int(pk)}, salt=SALT, compress=True)


def leggi(token: str) -> tuple[str, int]:
    """Restituisce ``(tipo, pk)`` o solleva ``LinkScaduto`` / ``LinkNonValido``."""
    try:
        dati = signing.loads(token, salt=SALT, max_age=settings.RILASCIO_LINK_GIORNI * 86400)
    except signing.SignatureExpired as exc:
        raise LinkScaduto from exc
    except signing.BadSignature as exc:
        raise LinkNonValido from exc
    if not isinstance(dati, dict):
        raise LinkNonValido
    tipo, pk = dati.get("t"), dati.get("pk")
    if tipo not in (RDA, DOCUMENTO) or not isinstance(pk, int):
        raise LinkNonValido
    return tipo, pk
