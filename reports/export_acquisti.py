"""Export XLSX delle viste del processo d'acquisto (F11.4): filtri in intestazione."""

import datetime

from reports import xlsx
from reports.acquisti import (
    PER_FATTURA,
    RigaEsecuzione,
    RigaRDA,
    conteggi_anomalie,
    conteggi_per_fase,
)
from reports.export import NOTA_IMPONIBILE, _generato

DESCRIZIONE_ANOMALIE = {
    "FATTURATO_OLTRE_MASSIMO": "Fatturato oltre il massimo (fisso + massimale)",
    "CHIUSO_SENZA_ATTESTAZIONE": "Chiuso senza attestazione o modello di ricezione finale",
    "FATTURA_DUPLICATA": "Stesso numero di fattura dello stesso fornitore",
    "VALORE_BASE_MANCANTE": "Fattura senza valore base: non conta nel fatturato",
    "IMPORTO_NON_QUADRA": "Valore base + oneri + bollo + IVA + altri importi "
    "diverso dall'importo del documento",
}


def _contratto(c) -> str:
    return c.numero_contratto or c.cig or f"#{c.pk}"


def stato_rda_xlsx(righe: list[RigaRDA], oggi: datetime.date, filtri: str):
    wb = xlsx.nuovo_libro()
    intestazione = ["Stato delle RDA", filtri, NOTA_IMPONIBILE, _generato(oggi)]
    colonne = [
        "N. RDA", "Intestazione", "Cluster", "Scopo", "Fabbisogno", "Referente", "Fornitore",
        "Fase", "Dal", "Giorni", "Ferma", "Inserita il", "Rilasciata il", "Importo",
        "Contratti generati",
    ]  # fmt: skip
    dati = [
        [
            r.rda.numero_rda or "",
            r.rda.intestazione or r.rda.descrizione,
            r.rda.cluster.codice,
            r.rda.get_scopo_display() if r.rda.scopo else "",
            r.fabbisogno.descrizione if r.fabbisogno else "",
            r.rda.nome_referente,
            str(r.fornitore or ""),
            r.fase_label,
            r.data_fase,
            r.giorni,
            "sì" if r.ferma else "",
            r.rda.data_inserimento,
            r.rda.data_rilascio,
            r.importo,
            "; ".join(_contratto(c) for c in r.contratti),
        ]
        for r in righe
    ]
    if righe:
        dati.append(["Totale"] + [None] * 12 + [sum(r.importo for r in righe), None])
    xlsx.foglio(wb, "Stato delle RDA", intestazione, colonne, dati)
    xlsx.foglio(
        wb, "Per fase", intestazione, ["Fase", "RDA", "Importo"],
        [[etichetta, n, importo] for _f, etichetta, n, importo in conteggi_per_fase(righe)],
    )  # fmt: skip
    return wb


def _riga_esecuzione(r: RigaEsecuzione) -> list:
    e = r.riepilogo.esecuzione
    c = r.contratto
    return [
        _contratto(c),
        c.fabbisogno.descrizione,
        c.fabbisogno.cluster.codice,
        str(c.fornitore),
        r.fine,
        c.data_chiusura,
        e.fatturato,
        e.residuo_fisso,
        e.residuo_massimo,
        e.avanzamento_pct,
    ]


COLONNE_ESECUZIONE = [
    "Contratto", "Fabbisogno", "Cluster", "Fornitore", "Fine effettiva", "Chiuso il",
    "Fatturato", "Residuo sul fisso", "Residuo sul massimo", "Avanzamento %",
]  # fmt: skip


def contratti_da_chiudere_xlsx(righe: list[RigaEsecuzione], oggi: datetime.date, filtri: str):
    wb = xlsx.nuovo_libro()
    intestazione = ["Contratti da chiudere", filtri, NOTA_IMPONIBILE, _generato(oggi)]
    xlsx.foglio(
        wb, "Contratti da chiudere", intestazione, [*COLONNE_ESECUZIONE, "Motivo"],
        [[*_riga_esecuzione(r), r.motivo_label] for r in righe],
    )  # fmt: skip
    return wb


def anomalie_xlsx(righe: list[RigaEsecuzione], oggi: datetime.date, filtri: str):
    wb = xlsx.nuovo_libro()
    intestazione = ["Anomalie dell'esecuzione", filtri, NOTA_IMPONIBILE, _generato(oggi)]
    dati = []
    for r in righe:
        for codice in r.riepilogo.anomalie:
            if codice in PER_FATTURA:
                continue  # una riga per ciascuna fattura, sotto
            dati.append([*_riga_esecuzione(r), codice, DESCRIZIONE_ANOMALIE.get(codice, ""), ""])
        for f, codici in r.anomalie_fatture:
            for codice in codici:
                dati.append(
                    [*_riga_esecuzione(r), codice, DESCRIZIONE_ANOMALIE.get(codice, ""),
                     f"{f.numero} del {f.data:%d/%m/%Y}"]
                )  # fmt: skip
    xlsx.foglio(
        wb, "Anomalie", intestazione, [*COLONNE_ESECUZIONE, "Anomalia", "Descrizione", "Fattura"],
        dati,
    )  # fmt: skip
    xlsx.foglio(
        wb, "Conteggi", intestazione, ["Anomalia", "Descrizione", "Numero"],
        [[k, DESCRIZIONE_ANOMALIE.get(k, ""), n] for k, n in conteggi_anomalie(righe).items()],
    )  # fmt: skip
    return wb
