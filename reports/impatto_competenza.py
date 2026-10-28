"""Impatto della Rev31 (competenza a mesi frazionati): budget di un anno prima e dopo.

«Dopo» è il calcolo attuale. «Prima» è la ripartizione a giorni della Rev30, riprodotta qui solo
per il confronto (sostituisce per la durata del calcolo l'unica funzione di ripartizione, quindi
tutte le viste cambiano insieme). Solo lettura: si usa dal comando ``impatto_competenza`` e si
può togliere dopo il rilascio.
"""

import datetime
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from unittest import mock

from contratti.engine import mesi_frazionati
from contratti.engine.importi import ZERO, ripartisci
from contratti.engine.tipi import Livello
from reports.budget import VISTE, Filtri, calcola_budget

DAY = datetime.date


def _a_giorni(importo: Decimal, inizio: DAY, fine: DAY) -> dict[int, Decimal]:
    """Il calcolo precedente: giorni di ogni anno solare, residuo sull'ultimo anno."""
    if fine < inizio:
        raise ValueError("periodo non valido: la fine precede l'inizio")
    anni = range(inizio.year, fine.year + 1)
    giorni = [(min(fine, DAY(a, 12, 31)) - max(inizio, DAY(a, 1, 1))).days + 1 for a in anni]
    return dict(zip(anni, ripartisci(importo, giorni), strict=True))


@contextmanager
def ripartizione_a_giorni() -> Iterator[None]:
    with mock.patch.object(mesi_frazionati, "competenza_per_anno", _a_giorni):
        yield


@dataclass
class RigaConto:
    codice: str
    conto: str
    prima: dict[str, Decimal]
    dopo: dict[str, Decimal]

    def delta(self, vista: str) -> Decimal:
        return self.dopo[vista] - self.prima[vista]


@dataclass
class RigaVoce:
    cluster: str
    fabbisogno: str
    contratto: str
    descrizione: str
    inizio: DAY
    fine: DAY
    previsionale: bool
    prima: dict[str, Decimal]
    dopo: dict[str, Decimal]

    def delta(self, vista: str) -> Decimal:
        return self.dopo[vista] - self.prima[vista]


@dataclass
class Impatto:
    anno: int
    natura: str
    livello: Livello
    conti: list[RigaConto]
    voci: list[RigaVoce]

    def totale(self, parte: str, vista: str) -> Decimal:
        return sum((getattr(c, parte)[vista] for c in self.conti), ZERO)

    def piu_cambiate(self, vista: str, n: int = 20) -> list[RigaVoce]:
        cambiate = [v for v in self.voci if v.delta(vista)]
        return sorted(cambiate, key=lambda v: abs(v.delta(vista)), reverse=True)[:n]


def _chiave(vb) -> tuple:
    return (
        vb.fabbisogno.pk,
        vb.contratto.pk if vb.contratto else None,
        vb.voce.pk if vb.voce else None,
        vb.previsionale,
        vb.numero_previsto,
        vb.descrizione,
    )


def _somme(importi, livello: Livello) -> dict[str, Decimal]:
    return {vista: importi[vista][livello] for vista in VISTE}


def impatto(anno: int, natura: str, livello: Livello, oggi: datetime.date) -> Impatto:
    filtri = Filtri(anno=anno, natura=natura, progetti="includi", extra_budget="includi")
    dopo = calcola_budget(filtri, oggi)
    with ripartizione_a_giorni():
        prima = calcola_budget(filtri, oggi)

    conti: dict[str, RigaConto] = {}
    for gruppi, parte in ((prima.gruppi("conto"), "prima"), (dopo.gruppi("conto"), "dopo")):
        for g in gruppi:
            riga = conti.setdefault(
                g.chiave,
                RigaConto(
                    g.chiave, g.etichetta, dict.fromkeys(VISTE, ZERO), dict.fromkeys(VISTE, ZERO)
                ),
            )
            setattr(riga, parte, _somme(g.totali["totale"], livello))
    voci: dict[tuple, RigaVoce] = {}
    for budget, parte in ((prima, "prima"), (dopo, "dopo")):
        for vb in budget.voci:
            riga = voci.setdefault(
                _chiave(vb),
                RigaVoce(
                    vb.area,
                    str(vb.fabbisogno),
                    (vb.contratto.numero_contratto or str(vb.fornitore or ""))
                    if vb.contratto
                    else "",
                    vb.descrizione,
                    vb.inizio,
                    vb.fine,
                    vb.previsionale,
                    dict.fromkeys(VISTE, ZERO),
                    dict.fromkeys(VISTE, ZERO),
                ),
            )
            setattr(riga, parte, _somme(vb.importi, livello))
    return Impatto(
        anno, natura, livello, sorted(conti.values(), key=lambda c: c.codice), list(voci.values())
    )


def impatto_xlsx(r: Impatto, oggi: datetime.date):
    from reports import xlsx
    from reports.budget import ETICHETTE_VISTE

    wb = xlsx.nuovo_libro()
    intestazione = [
        f"Impatto della Rev31 (competenza a mesi frazionati): budget {r.anno} {r.natura}",
        f"Livello {r.livello.value}. Prima = ripartizione a giorni; dopo = mesi frazionati. "
        "Cambia solo la ripartizione della competenza: fatturato per data fattura e ordinato "
        "restano uguali.",
        "Importi imponibili (IVA esclusa). Solo lettura: nessun dato è stato modificato.",
        f"Generato il {oggi:%d/%m/%Y}.",
    ]
    colonne = ["Conto", "Descrizione"]
    for vista in VISTE:
        colonne += [f"{vista} prima", f"{vista} dopo", f"{vista} delta"]
    righe = [
        [c.codice, c.conto, *[x for v in VISTE for x in (c.prima[v], c.dopo[v], c.delta(v))]]
        for c in r.conti
    ]
    righe.append(
        ["", "Totale", *[x for v in VISTE
                         for x in (r.totale("prima", v), r.totale("dopo", v),
                                   r.totale("dopo", v) - r.totale("prima", v))]]
    )  # fmt: skip
    xlsx.foglio(wb, "Per conto", intestazione, colonne, righe)
    for vista in ("competenza", "consuntivo"):
        voci = [
            [v.cluster, v.fabbisogno, v.contratto, v.descrizione, v.inizio, v.fine,
             "previsto" if v.previsionale else "registrato",
             v.prima[vista], v.dopo[vista], v.delta(vista)]
            for v in r.piu_cambiate(vista, n=10_000)
        ]  # fmt: skip
        xlsx.foglio(
            wb, f"Voci {vista}", [*intestazione, f"Vista: {ETICHETTE_VISTE[vista]}"],
            ["Cluster", "Fabbisogno", "Contratto", "Voce", "Dal", "Al", "Stato",
             "Prima", "Dopo", "Delta"],
            voci,
        )  # fmt: skip
    return wb
