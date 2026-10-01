"""Export XLSX dei report: riepilogo e dettaglio, con i filtri in intestazione."""

import datetime

from contratti import models as m
from contratti.engine.importi import arrotonda
from contratti.engine.tipi import Livello
from reports import xlsx
from reports.budget import ETICHETTE_VISTE, LIVELLI, PARTI, RAGGRUPPAMENTI, VISTE, Budget
from reports.piano_ordini import PianoOrdini
from reports.quadratura import CAUSE, Quadratura

NOTA_IMPONIBILE = "Importi imponibili (IVA esclusa)."


def _generato(oggi: datetime.date) -> str:
    return f"Generato il {datetime.date.today():%d/%m/%Y}; data di riferimento {oggi:%d/%m/%Y}."


def descrivi_filtri(budget: Budget) -> str:
    f = budget.filtri
    parti = [f"Anno {f.anno}"]
    if f.area:
        parti.append(f"area {f.area}")
    if f.conto:
        parti.append(f"conto {m.ContoCoge.objects.filter(pk=f.conto).first()}")
    if f.fornitore:
        parti.append(f"fornitore {m.Fornitore.objects.filter(pk=f.fornitore).first()}")
    if f.finanziamento:
        parti.append(f"finanziamento {m.Contratto.Finanziamento(f.finanziamento).label}")
    parti.append("previsti inclusi" if f.previsionali else "solo consolidato")
    return "; ".join(parti)


def budget_xlsx(budget: Budget, criterio: str):
    wb = xlsx.nuovo_libro()
    intestazione = [
        f"Budget {budget.filtri.anno}",
        descrivi_filtri(budget),
        NOTA_IMPONIBILE,
        _generato(budget.oggi),
    ]
    totali = budget.totali()
    righe = []
    for vista in VISTE:
        for livello in LIVELLI:
            righe.append(
                [ETICHETTE_VISTE[vista], livello.value]
                + [totali[parte][vista][livello] for parte in PARTI]
            )
    colonne = ["Vista", "Livello", "Consolidato", "Previsionale", "Totale"]
    xlsx.foglio(wb, "Riepilogo", intestazione, colonne, righe)

    colonne = [RAGGRUPPAMENTI[criterio]]
    for vista in VISTE:
        for livello in LIVELLI:
            for parte in PARTI:
                colonne.append(f"{vista} {livello.value} {parte}")
    righe = []
    for g in budget.gruppi(criterio):
        riga = [g.etichetta]
        for vista in VISTE:
            for livello in LIVELLI:
                riga += [g.totali[parte][vista][livello] for parte in PARTI]
        righe.append(riga)
    xlsx.foglio(wb, f"Per {criterio}", intestazione, colonne, righe)

    colonne = [
        "Tipo", "Previsto n.", "Area", "Fabbisogno", "Contratto", "Voce", "Fornitore",
        "Conto", "Finanziamento", "Inizio servizio", "Fine servizio",
    ] + [f"{vista} {livello.value}" for vista in VISTE for livello in LIVELLI]  # fmt: skip
    righe = []
    for v in budget.voci:
        righe.append(
            [
                "Previsionale" if v.previsionale else "Consolidato",
                v.numero_previsto,
                v.area,
                str(v.fabbisogno),
                str(v.contratto) if v.contratto and not v.previsionale else "",
                v.descrizione,
                str(v.fornitore or ""),
                str(v.conto or ""),
                m.Contratto.Finanziamento(v.finanziamento).label,
                v.inizio,
                v.fine,
            ]
            + [v.importi[vista][livello] for vista in VISTE for livello in LIVELLI]
        )
    xlsx.foglio(wb, "Dettaglio voci", intestazione, colonne, righe)

    if budget.rinnovi_mancanti or budget.avvisi or budget.senza_data:
        righe = [
            ["Rinnovo mancante", str(r.fabbisogno),
             f"{r.previsti_esclusi} previsti esclusi, dal {r.dal:%d/%m/%Y} al {r.al:%d/%m/%Y}"]
            for r in budget.rinnovi_mancanti
        ]  # fmt: skip
        righe += [
            ["Avviso di calcolo", voce, msg] for msg, voci in budget.avvisi.items() for voce in voci
        ]
        if budget.senza_data:
            righe.append(["Esclusi", f"{budget.senza_data} contratti", "Senza data di inizio."])
        xlsx.foglio(wb, "Avvisi", intestazione, ["Tipo", "Riferimento", "Dettaglio"], righe)
    return wb


def piano_xlsx(piano: PianoOrdini, oggi: datetime.date, filtri: str = ""):
    wb = xlsx.nuovo_libro()
    intestazione = [
        f"Piano ordini {piano.anno}",
        filtri or "Tutte le aree e categorie",
        NOTA_IMPONIBILE,
        _generato(oggi),
    ]
    colonne = [
        "Fabbisogno", "Area", "Categoria", "Fornitore uscente", "Procedura presunta",
        "Lead time (mesi)", "Data limite di avvio", "Avvio servizio", "Fine servizio",
        "Durata (mesi)", "Stato pratica", "Fisso", "Probabile", "Massimo", "Oltre soglia",
    ]  # fmt: skip
    righe = [
        [
            r.fabbisogno.descrizione,
            r.fabbisogno.area,
            r.categoria.nome,
            str(r.fornitore_uscente or ""),
            str(r.procedura or ""),
            r.lead_time_mesi,
            r.data_limite,
            r.avvio,
            r.fine,
            r.durata_mesi,
            r.stato_pratica_label,
            r.importi[Livello.FISSO],
            r.importi[Livello.PROBABILE],
            r.importi[Livello.MASSIMO],
            "; ".join(r.sopra_soglia),
        ]
        for r in piano.righe
    ]
    totali = piano.totali()
    righe.append(["Totale"] + [None] * 10 + [totali[liv] for liv in LIVELLI] + [None])
    xlsx.foglio(wb, "Piano ordini", intestazione, colonne, righe)

    righe = [
        [a.tipo, a.nome, a.soglia.descrizione, a.soglia.importo, a.totale_massimo,
         "; ".join(r.fabbisogno.descrizione for r in a.righe)]
        for a in piano.avvisi
    ]  # fmt: skip
    xlsx.foglio(
        wb, "Frazionamento", intestazione,
        ["Raggruppamento", "Nome", "Soglia", "Importo soglia", "Totale massimo", "Fabbisogni"],
        righe,
    )  # fmt: skip
    return wb


def quadratura_xlsx(q: Quadratura):
    wb = xlsx.nuovo_libro()
    intestazione = [
        f"Quadratura con il Dashboard Excel — {q.file} ({q.area})",
        "Excel: formula del Dashboard ricalcolata (bug dei mesi compreso). "
        "App: competenza a giorni delle voci importate. Differenza = app − Excel.",
        _generato(datetime.date.today()),
    ]
    colonne = [
        "Anno", "Excel minimo", "App fisso", "Differenza minimo", "Excel massimo",
        "App massimo", "Differenza massimo", "Dashboard minimo (salvato)",
        "Dashboard massimo (salvato)",
    ]  # fmt: skip
    righe = [list(r.values()) for r in q.riepilogo()]
    xlsx.foglio(wb, "Riepilogo", intestazione, colonne, righe)

    colonne = ["Riga", "Descrizione", "Fornitore", "Inizio", "Fine (Excel)", "Mesi", "Cause"]
    for anno in q.anni:
        colonne += [f"{anno} Excel min", f"{anno} app fisso", f"{anno} diff min"]
        colonne += [f"{anno} Excel max", f"{anno} app max", f"{anno} diff max"]
    righe = []
    for r in q.righe:
        riga = [r.numero, r.descrizione, r.fornitore, r.inizio, r.fine, r.mesi, ", ".join(r.cause)]
        for anno in q.anni:
            riga += [arrotonda(r.excel_minimo[anno]), r.app_fisso[anno]]
            riga += [r.differenza(anno, "minimo"), arrotonda(r.excel_massimo[anno])]
            riga += [r.app_massimo[anno], r.differenza(anno, "massimo")]
        righe.append(riga)
    xlsx.foglio(wb, "Dettaglio righe", intestazione, colonne, righe)

    righe = [[c, CAUSE[c], k] for c, k in q.conteggio_cause().items()]
    righe += [[f"Riga {num}", motivo, None] for num, motivo in q.escluse]
    xlsx.foglio(wb, "Cause ed esclusioni", intestazione, ["Codice", "Descrizione", "Righe"], righe)
    return wb
