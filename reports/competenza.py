"""Competenza dichiarata dal referente contro quella calcolata dal registro (SPEC §5.2, Rev27).

Il referente dichiara, per un fabbisogno, un anno e una natura, la competenza che si aspetta;
il registro la confronta con quella che ricava da fatture, stanziamenti, rate e previsti. Il
confronto usa la vista di riferimento del budget (``VISTA_ASSEGNATO``, Rev21) e ripete le
altre viste per informazione. OPEX e CAPEX restano distinti.
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal

from contratti import models as m
from contratti.engine.importi import ZERO
from contratti.engine.tipi import Livello
from reports.budget import VISTA_ASSEGNATO, Filtri, calcola_budget


@dataclass(frozen=True)
class RigaCompetenza:
    id: int
    anno: int
    natura: str
    dichiarato: Decimal
    note: str
    calcolato: dict[Livello, Decimal]  # vista di riferimento, per livello
    competenza_contratto: Decimal  # mesi frazionati, livello probabile

    @property
    def probabile(self) -> Decimal:
        return self.calcolato[Livello.PROBABILE]

    @property
    def fisso(self) -> Decimal:
        return self.calcolato[Livello.FISSO]

    @property
    def massimo(self) -> Decimal:
        return self.calcolato[Livello.MASSIMO]

    @property
    def scostamento(self) -> Decimal:
        """Dichiarato meno calcolato al livello probabile; negativo = il calcolo supera."""
        return self.dichiarato - self.calcolato[Livello.PROBABILE]


def confronto(fabbisogno: m.Fabbisogno, oggi: datetime.date) -> list[RigaCompetenza]:
    """Una riga per ogni competenza dichiarata attiva del fabbisogno (anni recenti prima)."""
    righe = []
    dichiarate = fabbisogno.competenze_dichiarate.filter(archiviato=False)
    for d in dichiarate.order_by("-anno", "natura"):
        budget = calcola_budget(
            Filtri(
                anno=d.anno,
                fabbisogno=fabbisogno.pk,
                natura=d.natura,
                progetti="includi",
                extra_budget="includi",
            ),
            oggi,
        )
        totali = budget.totali()["totale"]
        righe.append(
            RigaCompetenza(
                id=d.pk,
                anno=d.anno,
                natura=d.natura,
                dichiarato=d.importo,
                note=d.note,
                calcolato=dict(totali[VISTA_ASSEGNATO]),
                competenza_contratto=totali["competenza"].get(Livello.PROBABILE, ZERO),
            )
        )
    return righe
