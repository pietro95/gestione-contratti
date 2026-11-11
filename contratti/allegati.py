"""Allegati delle richieste di RDA (SPEC §4, Rev46): controlli, salvataggio, archiviazione.

I file stanno in ``settings.ALLEGATI_ROOT``, con nome casuale; il nome originale è nel database.
Limiti di dimensione e di numero sono parametri (tabella ``Parametro``); i tipi ammessi sono una
lista chiusa di estensioni, confermata dall'intestazione del file quando il formato ne ha una.
"""

import os
import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from contratti import acquisti, adapters
from contratti import models as m
from contratti.engine.acquisti import Fase

Chiave = m.Parametro.Chiave
# Valori usati solo se manca il parametro (la data migration lo crea sempre).
MAX_MB_DEFAULT = 10
MAX_PER_RDA_DEFAULT = 20

_ZIP = (b"PK\x03\x04",)
_OLE = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",)
# estensione -> intestazioni ammesse (None: nessun controllo, formato testuale).
TIPI_AMMESSI: dict[str, tuple[bytes, ...] | None] = {
    "pdf": (b"%PDF",),
    "docx": _ZIP,
    "xlsx": _ZIP,
    "zip": _ZIP,
    "doc": _OLE,
    "xls": _OLE,
    "msg": _OLE,
    "eml": None,
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
}
_CONTROLLO = re.compile(r"[\x00-\x1f\x7f]")


def elenco_tipi() -> str:
    return ", ".join(sorted(TIPI_AMMESSI))


def _parametro(chiave: str, default: int) -> int:
    try:
        return int(adapters.parametro(chiave, timezone.localdate()))
    except adapters.ParametroMancante:
        return default


def max_byte() -> int:
    return _parametro(Chiave.ALLEGATO_MAX_MB, MAX_MB_DEFAULT) * 1024 * 1024


def max_per_rda() -> int:
    return _parametro(Chiave.ALLEGATI_MAX_PER_RDA, MAX_PER_RDA_DEFAULT)


def nome_pulito(nome: str) -> str:
    """Solo il nome del file (niente cartelle, di nessun sistema), senza caratteri di controllo."""
    nome = _CONTROLLO.sub("", re.split(r"[\\/]", nome or "")[-1]).strip().strip(".")
    radice, estensione = os.path.splitext(nome)
    return radice[: 250 - len(estensione)] + estensione


def attivi(rda: m.RichiestaAcquisto):
    return rda.file_allegati.filter(archiviato=False)


def controlla_file(file) -> None:
    """ValidationError se il file non è ammesso (nome, tipo, dimensione, intestazione)."""
    nome = nome_pulito(file.name)
    estensione = os.path.splitext(nome)[1].lower().lstrip(".")
    if not nome or estensione not in TIPI_AMMESSI:
        raise ValidationError(
            f"«{nome or file.name}»: tipo di file non ammesso. Ammessi: {elenco_tipi()}."
        )
    if file.size == 0:
        raise ValidationError(f"«{nome}»: il file è vuoto.")
    massimo = max_byte()
    if file.size > massimo:
        raise ValidationError(
            f"«{nome}»: supera la dimensione massima di {massimo // (1024 * 1024)} MB."
        )
    intestazioni = TIPI_AMMESSI[estensione]
    if intestazioni is not None:
        file.seek(0)
        testa = file.read(8)
        file.seek(0)
        if not testa.startswith(intestazioni):
            raise ValidationError(f"«{nome}»: il contenuto non corrisponde al tipo «{estensione}».")


def controlla(rda: m.RichiestaAcquisto | None, files) -> None:
    """Controlla i file nuovi e il loro numero rispetto a quelli già caricati."""
    errori = []
    for file in files:
        try:
            controlla_file(file)
        except ValidationError as exc:
            errori.extend(exc.messages)
    gia = attivi(rda).count() if rda is not None and rda.pk else 0
    massimo = max_per_rda()
    if gia + len(files) > massimo:
        errori.append(
            f"Troppi allegati: ne sono ammessi {massimo} per richiesta (già caricati {gia})."
        )
    if errori:
        raise ValidationError(errori)


def modificabile(rda: m.RichiestaAcquisto) -> bool:
    """Con la RDA annullata o chiusa gli allegati non si toccano più."""
    return acquisti.fase(rda) not in (Fase.ANNULLATA, Fase.CHIUSA)


def aggiungi(rda: m.RichiestaAcquisto, files, utente) -> list[m.AllegatoRDA]:
    """Salva i file come allegati della RDA. Tutto o niente: se qualcosa fallisce, i file già
    scritti sul disco vengono rimossi."""
    files = list(files)
    if not files:
        return []
    if not modificabile(rda):
        raise acquisti.OperazioneNonAmmessa("La RDA è annullata o chiusa: niente nuovi allegati.")
    controlla(rda, files)
    scritti: list[m.AllegatoRDA] = []
    try:
        with transaction.atomic():
            for file in files:
                allegato = m.AllegatoRDA(
                    rda=rda,
                    nome=nome_pulito(file.name),
                    dimensione=file.size,
                    caricato_da=utente if getattr(utente, "pk", None) else None,
                )
                allegato.file.save(file.name, file, save=False)
                scritti.append(allegato)
                allegato.save()
    except Exception:
        for allegato in scritti:
            allegato.file.storage.delete(allegato.file.name)
        raise
    return scritti


def archivia(allegato: m.AllegatoRDA) -> None:
    """L'allegato esce dall'elenco; il file resta sul disco e nella storia (SPEC §8, nessuna
    cancellazione fisica)."""
    if not modificabile(allegato.rda):
        raise acquisti.OperazioneNonAmmessa(
            "La RDA è annullata o chiusa: gli allegati non si toccano."
        )
    allegato.archiviato = True
    allegato.save(update_fields=["archiviato"])
