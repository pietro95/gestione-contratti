"""Normalizzazione dei valori grezzi degli Excel (SPEC §7.1–7.2, TC-08). Funzioni pure.

Le anomalie si segnalano, mai si correggono in silenzio: i valori sospetti si conservano.
"""

import datetime
import re
import unicodedata
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Caratteri invisibili trovati nei file: BOM e spazi a larghezza zero.
INVISIBILI = "﻿​‌‍⁠\xa0"
# I cinque modi in cui i file scrivono "nessun valore" (SPEC §2.2).
NULLI = frozenset({"", "n/a", "n/d", "na", "nd", "-"})
# Per i campi codice anche 0 vale "nessun valore"; per gli importi 0 è un valore.
NULLI_CODICE = NULLI | {"0"}

RE_CIG = re.compile(r"^[A-Z0-9]{10}$")
RE_ODA = re.compile(r"^\d{10}$")
RE_RDA_IN_NOTA = re.compile(r"\bRDA\s*(\d{10})\b", re.IGNORECASE)
# Nota composta solo da un numero RDA SAP (10 cifre che iniziano con 51).
RE_RDA_NUMERO = re.compile(r"^51\d{8}$")


@dataclass(frozen=True)
class Anomalia:
    codice: str
    campo: str
    valore: str
    messaggio: str


def testo(valore) -> str | None:
    """Testo pulito: senza caratteri invisibili, spazi compressi; ``None`` se vuoto."""
    if valore is None:
        return None
    if isinstance(valore, float) and valore.is_integer():
        valore = int(valore)
    s = str(valore)
    for c in INVISIBILI:
        s = s.replace(c, " " if c == "\xa0" else "")
    s = " ".join(s.split())
    return s or None


def aveva_invisibili(valore) -> bool:
    return isinstance(valore, str) and any(c in valore for c in INVISIBILI if c != "\xa0")


def codice(valore) -> str | None:
    """Codice (numero contratto, CIG, conto, codice SAP): ``None`` per tutte le forme di nullo."""
    s = testo(valore)
    if s is None or s.lower() in NULLI_CODICE:
        return None
    return s


def cig(valore) -> tuple[str | None, list[Anomalia]]:
    s = codice(valore)
    if s is None:
        return None, []
    s = s.upper()
    if not RE_CIG.match(s):
        return s, [Anomalia("CIG_LUNGHEZZA", "cig", s, "Il CIG ha 10 caratteri alfanumerici.")]
    return s, []


def oda(valore) -> tuple[str | None, list[Anomalia]]:
    s = codice(valore)
    if s is None:
        return None, []
    if not RE_ODA.match(s):
        messaggio = "Il numero di contratto SAP ha 10 cifre."
        return s, [Anomalia("ODA_FORMATO", "numero_contratto", s, messaggio)]
    return s, []


def importo(valore, campo: str) -> tuple[Decimal | None, list[Anomalia]]:
    """Importo in Decimal (dal valore letto, mai calcoli in float); ``None`` se vuoto."""
    if valore is None:
        return None, []
    if isinstance(valore, str):
        s = testo(valore)
        if s is None or s.lower() in NULLI:
            return None, []
        if s.startswith("="):
            return None, [
                Anomalia(
                    "IMPORTO_NON_LEGGIBILE",
                    campo,
                    s[:60],
                    "Formula senza valore calcolato nel file: importo non leggibile.",
                )
            ]
        s = s.replace("€", "").replace(" ", "")
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
    else:
        # repr() del float dà la rappresentazione più corta che lo identifica: niente
        # artefatti binari (4800.0 → "4800.0", 0.1 → "0.1").
        s = repr(valore) if isinstance(valore, float) else str(valore)
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None, [Anomalia("IMPORTO_NON_LEGGIBILE", campo, str(valore), "Non è un numero.")]
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), []


def data(valore) -> datetime.date | None:
    if isinstance(valore, datetime.datetime):
        return valore.date()
    if isinstance(valore, datetime.date):
        return valore
    s = testo(valore)
    if s is None or s.lower() in NULLI:
        return None
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(s, formato).date()
        except ValueError:
            continue
    return None


def intero(valore) -> int | None:
    if valore is None:
        return None
    if isinstance(valore, int | float):
        return int(valore)
    s = testo(valore)
    if s is None or not s.isdigit():
        return None
    return int(s)


def chiave_nome(nome: str | None) -> str:
    """Chiave per riconoscere lo stesso fornitore o la stessa descrizione scritti diversi."""
    if not nome:
        return ""
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().casefold()
    s = re.sub(r"[.,;:'\"()\-]", " ", s)
    s = " ".join(s.split())
    for forma in ("s r l", "srl", "s p a", "spa", "s n c", "snc", "s a s", "sas"):
        s = re.sub(rf"\b{forma}\b$", "", s).strip()
    return s


def rda_da_nota(nota: str | None) -> str | None:
    if not nota:
        return None
    if RE_RDA_NUMERO.match(nota):
        return nota
    trovato = RE_RDA_IN_NOTA.search(nota)
    return trovato.group(1) if trovato else None
