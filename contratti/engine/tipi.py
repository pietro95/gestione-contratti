"""Strutture dati del motore. Nessun riferimento all'ORM: gli adapter le costruiscono."""

import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum


class Modalita(StrEnum):
    ANTICIPATA = "anticipata"
    POSTICIPATA = "posticipata"
    UNA_TANTUM = "una_tantum"
    SAL = "sal"
    CONSUMO = "consumo"
    DA_VERIFICARE = "da_verificare"


# Mesi per periodo; ``intera_durata`` è un solo periodo che copre tutto il servizio.
MESI_PERIODICITA = {
    "mensile": 1,
    "bimestrale": 2,
    "trimestrale": 3,
    "semestrale": 6,
    "annuale": 12,
}
INTERA_DURATA = "intera_durata"


class Livello(StrEnum):
    FISSO = "fisso"
    PROBABILE = "probabile"
    MASSIMO = "massimo"


class Alert(StrEnum):
    ROSSO = "rosso"
    ARANCIONE = "arancione"
    GIALLO = "giallo"
    VERDE = "verde"


@dataclass(frozen=True)
class Piano:
    """Piano di fatturazione con i default già risolti dall'adapter."""

    modalita: Modalita
    periodicita: str = ""
    data_prima_fattura: datetime.date | None = None
    giorni_pagamento: int = 60
    pagamento_fine_mese: bool = True
    # Adeguamento annuo (%) applicato a ogni anniversario dell'inizio; 0 = nessuno.
    adeguamento_pct: Decimal = Decimal("0")


@dataclass(frozen=True)
class Rata:
    numero: int
    data_fattura: datetime.date
    data_pagamento: datetime.date
    importo: Decimal
    # Periodo coperto dalla rata, se noto (le rate inserite a mano possono non averlo).
    periodo_inizio: datetime.date | None = None
    periodo_fine: datetime.date | None = None


@dataclass(frozen=True)
class Voce:
    """Voce economica con il suo periodo di servizio e l'anno di impegno."""

    importo_fisso: Decimal
    inizio: datetime.date
    fine: datetime.date
    anno_impegno: int
    piano: Piano | None = None
    massimale_variabile: Decimal = Decimal("0")
    stima_consumo_pct: Decimal | None = None
    stima_consumo_importo: Decimal | None = None
    # Rate salvate (generate e poi eventualmente modificate a mano). None = da generare.
    rate: tuple[Rata, ...] | None = None
    riferimento: object = None


@dataclass(frozen=True)
class Scadenza:
    """Dati del contratto che servono a scadenze e alert."""

    inizio: datetime.date
    durata_mesi: int
    lead_time_mesi: int
    fine_override: datetime.date | None = None
    nuove_date_fine: tuple[datetime.date, ...] = ()
    tacito_rinnovo: bool = False
    preavviso_disdetta_giorni: int | None = None


@dataclass(frozen=True)
class ContrattoBase:
    """Ultimo contratto della catena: punto di partenza dei rinnovi previsti."""

    fine_effettiva: datetime.date
    durata_mesi: int
    # Voci da replicare (escluse quelle delle proroghe); inizio, fine e anno si ricalcolano.
    voci: tuple[Voce, ...]


@dataclass(frozen=True)
class ContrattoPrevisto:
    inizio: datetime.date
    fine: datetime.date
    voci: tuple[Voce, ...]
    numero: int = 1


@dataclass(frozen=True)
class Esito:
    """Avvisi raccolti durante il calcolo, da mostrare all'utente."""

    codice: str
    messaggio: str


@dataclass
class Totali:
    """Importi per anno, per vista e livello."""

    per_anno: dict[int, dict[Livello, Decimal]] = field(default_factory=dict)

    def aggiungi(self, anno: int, livello: Livello, importo: Decimal) -> None:
        livelli = self.per_anno.setdefault(anno, {})
        livelli[livello] = livelli.get(livello, Decimal("0.00")) + importo

    def importo(self, anno: int, livello: Livello = Livello.FISSO) -> Decimal:
        return self.per_anno.get(anno, {}).get(livello, Decimal("0.00"))

    def totale(self, livello: Livello = Livello.FISSO) -> Decimal:
        return sum(
            (livelli.get(livello, Decimal("0.00")) for livelli in self.per_anno.values()),
            Decimal("0.00"),
        )
