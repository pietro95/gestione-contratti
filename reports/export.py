"""Export XLSX dei report: riepilogo e dettaglio, con i filtri in intestazione."""

import datetime

from contratti import models as m
from contratti import permessi
from contratti.engine.importi import ZERO, arrotonda
from contratti.engine.tipi import Livello
from contratti.selettori import codici_cluster
from reports import xlsx
from reports.budget import (
    ETICHETTE_VISTE,
    LIVELLI,
    PARTI,
    RAGGRUPPAMENTI,
    SIGLE_VISTE,
    VISTE,
    Budget,
)
from reports.piano_ordini import PianoOrdini
from reports.quadratura import CAUSE, Quadratura

NOTA_IMPONIBILE = "Importi imponibili (IVA esclusa)."


def _generato(oggi: datetime.date) -> str:
    return f"Generato il {datetime.date.today():%d/%m/%Y}; data di riferimento {oggi:%d/%m/%Y}."


def voci_filtri(budget: Budget) -> list[str]:
    """I filtri del budget, uno per voce: il cluster sempre, anche quando sono tutti."""
    f = budget.filtri
    parti = [
        f"Anno {f.anno}",
        permessi.descrivi_filtro(codici_cluster(f.area)),
        f"natura {f.natura}" if f.natura else "OPEX e CAPEX separati",
    ]
    if f.conto:
        parti.append(f"conto {m.ContoCoge.objects.filter(pk=f.conto).first()}")
    if f.fornitore:
        parti.append(f"fornitore {m.Fornitore.objects.filter(pk=f.fornitore).first()}")
    if f.progetti == "includi":
        parti.append("WBS a progetto incluse")
    elif f.progetti == "solo":
        parti.append("solo WBS a progetto")
    else:
        parti.append("WBS a progetto escluse")
    if f.extra_budget == "includi":
        parti.append("extra budget incluso")
    elif f.extra_budget == "solo":
        parti.append("solo extra budget")
    else:
        parti.append("extra budget escluso")
    if f.wbs:
        parti.append(f"WBS {m.WBS.objects.filter(pk=f.wbs).first()}")
    parti.append("previsti inclusi" if f.previsionali else "solo consolidato")
    return parti


def descrivi_filtri(budget: Budget) -> str:
    return "; ".join(voci_filtri(budget))


def suffisso_cluster(codici) -> str:
    """Per il nome del file: ``_IT-TLC`` con il filtro sui cluster, niente se sono tutti."""
    return "_" + "-".join(codici) if codici else ""


def budget_xlsx(budget: Budget, criteri: dict[str, str] | str):
    """``criteri``: raggruppamento per natura (es. OPEX per conto, CAPEX per WBS)."""
    if isinstance(criteri, str):
        criteri = dict.fromkeys(m.Natura.values, criteri)
    wb = xlsx.nuovo_libro()
    intestazione = [
        f"Budget {budget.filtri.anno}",
        descrivi_filtri(budget),
        NOTA_IMPONIBILE,
        _generato(budget.oggi),
    ]
    # OPEX e CAPEX in righe distinte: nessun totale le somma.
    sezioni = budget.sezioni()
    righe = []
    for s in sezioni:
        totali = s.totali()
        for vista in VISTE:
            for livello in LIVELLI:
                righe.append(
                    [s.filtri.natura, ETICHETTE_VISTE[vista], livello.value]
                    + [totali[parte][vista][livello] for parte in PARTI]
                )
    colonne = ["Natura", "Vista", "Livello", "Consolidato", "Previsionale", "Totale"]
    xlsx.foglio(wb, "Riepilogo", intestazione, colonne, righe)

    usati = list(dict.fromkeys(criteri[s.filtri.natura] for s in sezioni))
    criterio = usati[0] if len(usati) == 1 else ""
    colonne = ["Natura", RAGGRUPPAMENTI[criterio] if criterio else "Gruppo"]
    for vista in VISTE:
        for livello in LIVELLI:
            for parte in PARTI:
                colonne.append(f"{SIGLE_VISTE[vista]} {livello.value} {parte}")
    righe = []
    for s in sezioni:
        for g in s.gruppi(criteri[s.filtri.natura]):
            riga = [s.filtri.natura, g.etichetta]
            for vista in VISTE:
                for livello in LIVELLI:
                    riga += [g.totali[parte][vista][livello] for parte in PARTI]
            righe.append(riga)
    xlsx.foglio(wb, f"Per {criterio}" if criterio else "Per gruppo", intestazione, colonne, righe)

    # CAPEX per WBS e, dentro ogni WBS, per conto: la lettura del Controllo di gestione.
    capex = [s for s in sezioni if s.filtri.natura == m.Natura.CAPEX]
    if capex and criteri[m.Natura.CAPEX] == "wbs":
        colonne_wbs = ["WBS", "Conto", *colonne[2:]]
        righe = []
        for g in capex[0].gruppi("wbs"):
            for sg in g.sotto("conto"):
                riga = [g.etichetta, sg.etichetta]
                for vista in VISTE:
                    for livello in LIVELLI:
                        riga += [sg.totali[parte][vista][livello] for parte in PARTI]
                righe.append(riga)
        xlsx.foglio(wb, "CAPEX per WBS e conto", intestazione, colonne_wbs, righe)

    colonne = [
        "Tipo", "Natura", "Previsto n.", "Cluster", "Fabbisogno", "Contratto", "Voce",
        "Fornitore", "Conto", "WBS", "Finanziamento", "Inizio servizio", "Fine servizio",
    ]  # fmt: skip
    colonne += [f"{SIGLE_VISTE[vista]} {liv.value}" for vista in VISTE for liv in LIVELLI]
    righe = []
    for v in sorted(budget.voci, key=lambda v: v.natura != "OPEX"):
        righe.append(
            [
                "Previsionale" if v.previsionale else "Consolidato",
                v.natura,
                v.numero_previsto,
                v.area,
                str(v.fabbisogno),
                (str(v.contratto) + (" (senza contratto)" if v.senza_contratto else ""))
                if v.contratto and not v.previsionale
                else "",
                v.descrizione,
                str(v.fornitore or ""),
                str(v.conto or ""),
                str(v.wbs or ""),
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


def piano_xlsx(
    piano: PianoOrdini,
    oggi: datetime.date,
    filtri: str = "",
    natura: str = "",
    semplificata: bool = False,
):
    """Export del piano ordini. Semplificato (per il Procurement): senza categoria, procedura,
    lead time, data limite, fase, ritardo e senza il fisso e il probabile (solo il massimo)."""
    wb = xlsx.nuovo_libro()
    intestazione = [
        f"Piano ordini {piano.anno}" + (" (semplificato)" if semplificata else ""),
        filtri or "Tutti i cluster e le categorie",
        NOTA_IMPONIBILE,
        _generato(oggi),
    ]
    livelli = [Livello.MASSIMO] if semplificata else LIVELLI
    colonne = ["Fabbisogno", "Cluster", "Sottocluster"]
    if not semplificata:
        colonne.append("Categoria")
    colonne += ["Stato", "Fornitore"]
    if not semplificata:
        colonne += ["Procedura presunta", "Lead time (mesi)", "Data limite di avvio"]
    colonne += ["Avvio servizio", "Fine servizio", "Durata (mesi)", "Stato pratica"]
    if not semplificata:
        colonne += ["Fase", "In ritardo"]
    colonne.append("Fonte di finanziamento")
    colonne += [f"Contrattuale {liv.value}" for liv in livelli]
    colonne += [f"Normalizzato {piano.anno} {liv.value}" for liv in livelli]
    colonne.append("Oltre soglia")
    fasi = {
        "da_avviare": "da avviare",
        "da_concludere": "da concludere (fuori dai totali)",
        "registrato": "registrato (fuori dai totali contrattuali)",
    }
    # Dopo il testo e prima dei valori: «Totale» e il riepilogo degli stipulati usano questi indici.
    inizio_valori = len(colonne) - 2 * len(livelli) - 1
    sezioni = piano.sezioni(natura)
    if any(gs.stipulati for sz in sezioni for gc in sz.cluster for gs in gc.sottocluster):
        intestazione[2] += (
            " Contratti stipulati raggruppati (righe comprimibili): la riga di riepilogo "
            "somma i dettagli, non sommare entrambe."
        )

    def riga_xlsx(rn, gc, gs):
        r = rn.riga
        riga = [r.fabbisogno.descrizione, gc.cluster.codice, gs.nome]
        if not semplificata:
            riga.append(r.categoria.nome)
        riga += [r.stato, str(r.fornitore or "")]
        if not semplificata:
            riga += [str(r.procedura or ""), r.lead_time_mesi, r.data_limite]
        riga += [r.avvio, r.fine, r.durata_mesi, r.stato_pratica_label]
        if not semplificata:
            riga += [fasi[r.fase], "sì" if r.in_ritardo else ""]
        riga.append(rn.fonte)
        riga += [rn.importi[liv] for liv in livelli]
        riga += [rn.normalizzato[liv] for liv in livelli]
        riga.append("; ".join(r.sopra_soglia))
        return riga

    def riga_riepilogo(gc, gs):
        riep = gs.riepilogo_stipulati
        riga = [None] * len(colonne)
        riga[0] = f"{len(gs.stipulati)} contratti già stipulati"
        riga[1], riga[2] = gc.cluster.codice, gs.nome
        riga[colonne.index("Stato")] = "Stipulato"
        valori = [riep.contrattuale[liv] for liv in livelli]
        valori += [riep.normalizzato[liv] for liv in livelli]
        riga[inizio_valori : inizio_valori + len(valori)] = valori
        return riga

    # Un foglio per natura: OPEX e CAPEX sono budget distinti, mai sommati.
    for sezione in sezioni:
        righe = []
        livelli_riga = []  # 1 = dettaglio di un gruppo (comprimibile), 0 = riga normale
        for gc in sezione.cluster:
            for gs in gc.sottocluster:
                for rn in gs.altre:
                    righe.append(riga_xlsx(rn, gc, gs))
                    livelli_riga.append(0)
                if gs.stipulati:  # riepilogo sopra, dettagli raggruppati sotto
                    righe.append(riga_riepilogo(gc, gs))
                    livelli_riga.append(0)
                    for rn in gs.stipulati:
                        righe.append(riga_xlsx(rn, gc, gs))
                        livelli_riga.append(1)
        t = sezione.totali
        righe.append(
            [f"Totale {sezione.natura}"]
            + [None] * (inizio_valori - 1)
            + [t.contrattuale[liv] for liv in livelli]
            + [t.normalizzato[liv] for liv in livelli]
            + [None]
        )
        livelli_riga.append(0)
        ws = xlsx.foglio(wb, sezione.natura, intestazione, colonne, righe)
        xlsx.raggruppa_righe(ws, len(intestazione) + 3, livelli_riga)
    if not sezioni:
        xlsx.foglio(wb, "Piano ordini", intestazione, colonne, [])

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


def wbs_xlsx(spese, oggi: datetime.date):
    """Spese per WBS: una riga per voce, una colonna per anno, poi il totale."""
    wb = xlsx.nuovo_libro()
    w = spese.wbs
    intestazione = [
        f"Spese per WBS {w.codice_wbs} — {w.descrizione}",
        f"{w.get_tipo_display()}{f', cluster {w.cluster.codice}' if w.cluster else ''}; "
        f"{ETICHETTE_VISTE[spese.vista]}, livello {spese.livello.value}; solo contratti registrati",
        NOTA_IMPONIBILE,
        _generato(oggi),
    ]
    anni = spese.anni
    colonne = ["Cluster", "Fabbisogno", "Contratto", "Fornitore", "Voce", "Conto",
               "Inizio servizio", "Fine servizio", *[str(a) for a in anni], "Totale"]  # fmt: skip
    righe = []
    for r in spese.righe:
        importi = [r.per_anno.get(a, ZERO) for a in anni]
        righe.append(
            [
                r.contratto.fabbisogno.cluster.codice,
                r.contratto.fabbisogno.descrizione,
                r.contratto.numero_contratto or "",
                str(r.contratto.fornitore),
                r.voce.descrizione,
                r.voce.conto.codice if r.voce.conto else "",
                r.inizio,
                r.fine,
                *importi,
                sum(importi, ZERO),
            ]
        )
    totali = spese.totali()
    righe.append(["Totale", "", "", "", "", "", None, None, *[totali[a] for a in anni],
                  spese.totale])  # fmt: skip
    xlsx.foglio(wb, "Spese per anno", intestazione, colonne, righe)
    return wb
