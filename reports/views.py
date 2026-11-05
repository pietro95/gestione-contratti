"""Report (F5): budget dell'anno e piano ordini. Sola lettura, visibili a tutti i ruoli."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from contratti import models as m
from contratti import permessi
from contratti.engine.tipi import Livello
from contratti.views import oggi_richiesta
from reports import pdf, xlsx
from reports.budget import (
    ETICHETTE_VISTE,
    FONTI_VISTE,
    LIVELLI,
    NATURE,
    PARTI,
    RAGGRUPPAMENTI,
    VISTA_ASSEGNATO,
    VISTE,
    assegnati_del_criterio,
    budget_assegnato,
    calcola_budget,
    confronto_conto,
    soglia_avvicinamento,
)
from reports.export import (
    budget_xlsx,
    descrivi_filtri,
    piano_xlsx,
    suffisso_sottocluster,
    voci_filtri,
)
from reports.extra_budget import avviso_sforamento, elenco_autorizzazioni, spese_extra_budget
from reports.forms import FiltriBudgetForm, FiltriPianoForm
from reports.piano_ordini import calcola_piano
from reports.wbs import elenco_wbs, spese_wbs

VISTA_SEMPLIFICATA = "semplificata"


def _celle(totali, livello, viste) -> list:
    """Per ogni vista scelta: consolidato, previsionale e totale al livello scelto."""
    return [[totali[parte][vista][livello] for parte in PARTI] for vista in viste]


def _assegnato(b, livello) -> dict | None:
    """Box del budget assegnato ai sottocluster filtrati (natura della sezione).

    Il residuo è l'assegnato meno il totale della vista di riferimento (Fatturato e stanziato)
    al livello scelto. Con più sottocluster è la somma degli assegnati. Il box compare solo
    quando la selezione è ristretta (non con tutti i sottocluster).
    """
    f = b.filtri
    if not f.sottocluster:
        return None
    sc = permessi.descrivi_sottocluster_scelti(f.sottocluster).removeprefix("Sottocluster: ")
    assegnato = budget_assegnato(f).get(f.natura)
    totale = b.totali()["totale"][VISTA_ASSEGNATO][livello]
    return {
        "sottocluster": sc,
        "importo": assegnato,
        "speso": totale,
        "vista": ETICHETTE_VISTE[VISTA_ASSEGNATO],
        "residuo": None if assegnato is None else assegnato - totale,
    }


def _sezione(b, criterio, livello, viste, soglia) -> dict:
    """Una natura del budget (OPEX o CAPEX): riepilogo, gruppi e totali, mai sommati tra loro."""
    totali = b.totali()
    # Rev34: assegnato e stato sulle righe dei gruppi: OPEX per conto, CAPEX per WBS. Le spese
    # CAPEX gravano sulla WBS, non sul conto: i conti sotto la WBS non hanno confronto.
    assegnati = assegnati_del_criterio(b.filtri, criterio)

    def confronto(g):
        return confronto_conto(assegnati, g.chiave, g.totali, livello, soglia)

    gruppi = []
    for g in b.gruppi(criterio):
        # Solo le voci con importi nelle viste scelte: le altre viste non sporcano l'elenco.
        voci = [v for v in g.voci if any(v.importi[x][liv] for x in viste for liv in LIVELLI)]
        if voci:
            gruppi.append((g, voci))
    return {
        "natura": b.filtri.natura,
        "con_confronto": assegnati is not None,
        "assegnato": _assegnato(b, livello),
        "budget": b,
        "criterio": RAGGRUPPAMENTI[criterio],
        "riepilogo": [
            (ETICHETTE_VISTE[vista], [[totali[p][vista][liv] for p in PARTI] for liv in LIVELLI])
            for vista in viste
        ],
        "gruppi": [
            {
                "etichetta": g.etichetta,
                "celle": _celle(g.totali, livello, viste),
                "confronto": confronto(g) if assegnati is not None else None,
                # CAPEX per WBS: il dettaglio per conto, come lo legge il Controllo di gestione.
                "sotto": [
                    (sg.etichetta, _celle(sg.totali, livello, viste)) for sg in g.sotto("conto")
                ]
                if criterio == "wbs"
                else [],
                "voci": [(v, [v.importi[vista][livello] for vista in viste]) for v in voci],
            }
            for g, voci in gruppi
        ],
        "totale_celle": _celle(totali, livello, viste),
        "kpi": [(ETICHETTE_VISTE[v], *[totali[p][v][livello] for p in PARTI]) for v in viste],
    }


@login_required
def budget(request):
    oggi = oggi_richiesta(request)
    form = FiltriBudgetForm(request.GET, anno_default=oggi.year, utente=request.user)
    contesto = {"form": form, "oggi": oggi, "viste": [ETICHETTE_VISTE[v] for v in VISTE]}
    if not form.is_valid():
        return render(request, "reports/budget.html", contesto)
    b = calcola_budget(form.filtri(), oggi)
    livello = form.livello_scelto
    viste = form.viste_scelte
    soglia = soglia_avvicinamento(oggi)
    criteri = {n: form.criterio(n) for n in NATURE}
    if request.GET.get("formato") == "xlsx":
        natura = b.filtri.natura or "OPEX_CAPEX"
        nome = f"{oggi:%Y.%m.%d}_Budget_{b.filtri.anno}_{natura}.xlsx"
        return xlsx.risposta(budget_xlsx(b, criteri, viste, livello, soglia), nome)
    contesto |= {
        "budget": b,
        "sezioni": [
            _sezione(s, criteri[s.filtri.natura], livello, viste, soglia) for s in b.sezioni()
        ],
        "livelli": LIVELLI,
        "viste": [ETICHETTE_VISTE[v] for v in viste],
        "n_colonne": 1 + 3 * len(viste) + 2,
        "soglia": soglia,
        "n_avvisi": len(b.rinnovi_mancanti) + len(b.avvisi) + (1 if b.senza_data else 0),
        "livello": livello,
    }
    if request.GET.get("formato") == "pdf":
        natura = b.filtri.natura or "OPEX_CAPEX"
        titolo = f"Budget {b.filtri.anno}" + (f" · {b.filtri.natura}" if b.filtri.natura else "")
        contesto |= {
            "titolo": titolo,
            "filtri": descrivi_filtri(b),
            "voci_filtri": voci_filtri(b),
            "cluster": permessi.descrivi_sottocluster_scelti(b.filtri.sottocluster),
            "dettaglio": bool(request.GET.get("dettaglio")),
        }
        suffisso = suffisso_sottocluster(b.filtri.sottocluster)
        nome = f"{oggi:%Y.%m.%d}_Budget_{b.filtri.anno}_{natura}{suffisso}.pdf"
        return pdf.risposta("reports/pdf/budget.html", contesto, nome, request)
    return render(request, "reports/budget.html", contesto)


@login_required
def piano_ordini(request):
    oggi = oggi_richiesta(request)
    form = FiltriPianoForm(request.GET, anno_default=oggi.year, utente=request.user)
    contesto = {"form": form, "oggi": oggi}
    if not form.is_valid():
        return render(request, "reports/piano_ordini.html", contesto)
    d = form.cleaned_data
    piano = calcola_piano(
        d["anno"],
        oggi,
        sottocluster=form.sottocluster_ids(),
        natura=d.get("natura") or "",
    )
    semplificata = request.GET.get("vista") == VISTA_SEMPLIFICATA
    if request.GET.get("formato") == "xlsx":
        suffisso = "_semplificato" if semplificata else ""
        nome = f"{oggi:%Y.%m.%d}_Piano_ordini_{piano.anno}{suffisso}.xlsx"
        natura = d.get("natura") or ""
        wb = piano_xlsx(piano, oggi, form.descrizione(), natura, semplificata=semplificata)
        return xlsx.risposta(wb, nome)
    # Vista semplificata per il Procurement: solo il valore massimo, senza gli elementi di lavoro
    # interni (procedura, lead time, data limite, fase, ritardo, fisso e probabile).
    livelli_mostrati = [Livello.MASSIMO] if semplificata else LIVELLI
    query = request.GET.copy()
    query.pop("formato", None)
    query.pop("dettaglio", None)
    query.pop("vista", None)
    contesto |= {
        "semplificata": semplificata,
        "semplificata_param": VISTA_SEMPLIFICATA if semplificata else "",
        "query_completa": query.urlencode(),
        "query_semplificata": query.urlencode()
        + ("&" if query else "")
        + "vista="
        + VISTA_SEMPLIFICATA,
        "livelli_mostrati": livelli_mostrati,
        "n_testo": 6 if semplificata else 8,
        "n_colonne": 6 + 2 * len(livelli_mostrati) if semplificata else 14,
        "piano": piano,
        # Con il filtro di natura, solo i totali di quella natura (un previsto misto resta
        # in elenco con l'importo intero, ma la sua quota dell'altra natura non si conta).
        "per_natura": {d["natura"]: piano.totali(d["natura"])}
        if d.get("natura")
        else piano.totali_per_natura(),
        "sezioni": piano.sezioni(d.get("natura") or ""),
        "livelli": LIVELLI,
    }
    if request.GET.get("formato") == "pdf":
        ids = form.sottocluster_ids()
        contesto |= {
            "titolo": f"Piano ordini {piano.anno}",
            # Gli avvisi di frazionamento sono una verifica interna: nel PDF solo a richiesta.
            "con_avvisi": bool(request.GET.get("dettaglio")),
            "filtri": form.descrizione(),
            "voci_filtri": form.voci(),
            "cluster": form.descrizione_sottocluster(),
        }
        raggruppa = bool(request.GET.get("raggruppa"))
        contesto["raggruppa_stipulati"] = raggruppa
        suffisso = "_stipulati_raggruppati" if raggruppa else ""
        nome = (
            f"{oggi:%Y.%m.%d}_Piano_ordini_{piano.anno}{suffisso_sottocluster(ids)}{suffisso}.pdf"
        )
        return pdf.risposta("reports/pdf/piano_ordini.html", contesto, nome, request)
    return render(request, "reports/piano_ordini.html", contesto)


@login_required
def wbs_elenco(request):
    """WBS di cluster (di default dei propri cluster) e WBS a progetto, con il numero di voci."""
    g = request.GET
    scelti = g.getlist("sottocluster")
    sottocluster = permessi.filtro_sottocluster(request.user, scelti)
    tipo = g.get("tipo", "") if g.get("tipo") in m.WBS.Tipo.values else ""
    return render(
        request,
        "reports/wbs_elenco.html",
        {
            "elenco": elenco_wbs(
                [],
                tipo,
                archiviate=bool(g.get("archiviate")),
                sottocluster=sottocluster,
                tutte_a_progetto=not scelti,
            ),
            "filtro_sottocluster": permessi.contesto_filtro_sottocluster(request.user, scelti),
            "tipi": m.WBS.Tipo.choices,
            "filtri": g,
        },
    )


@login_required
def wbs_spese(request, pk):
    """Spese per WBS: i contratti sulla WBS e gli importi anno per anno."""
    wbs = get_object_or_404(m.WBS.objects.select_related("cluster"), pk=pk)
    vista = request.GET.get("vista") if request.GET.get("vista") in VISTE else "cassa"
    try:
        livello = Livello(request.GET.get("livello") or Livello.PROBABILE)
    except ValueError:
        livello = Livello.PROBABILE
    spese = spese_wbs(wbs, vista, livello)
    if request.GET.get("formato") == "xlsx":
        from reports.export import wbs_xlsx

        nome = f"{oggi_richiesta(request):%Y.%m.%d}_Spese_WBS_{wbs.codice_wbs}.xlsx"
        return xlsx.risposta(wbs_xlsx(spese, oggi_richiesta(request)), nome)
    contesto = {
        "s": spese,
        "anni": spese.anni,
        "righe": [
            (
                r,
                [r.per_anno.get(a) for a in spese.anni],
                [r.consuntivo.get(a) for a in spese.anni],
                [r.previsto.get(a) for a in spese.anni],
            )
            for r in spese.righe
        ],
        "totali": [spese.totali()[a] for a in spese.anni],
        "totali_consuntivo": [spese.totali_consuntivo()[a] for a in spese.anni],
        "totali_previsto": [spese.totali_previsto()[a] for a in spese.anni],
        "fonte_vista": FONTI_VISTE[vista],
        "viste": [(v, ETICHETTE_VISTE[v]) for v in VISTE],
        "livelli": LIVELLI,
    }
    if request.GET.get("formato") == "pdf":
        contesto |= {
            "titolo": f"Spese WBS {wbs.codice_wbs}",
            "filtri": f"{ETICHETTE_VISTE[vista]} · livello {livello.value}",
        }
        nome = f"{oggi_richiesta(request):%Y.%m.%d}_Spese_WBS_{wbs.codice_wbs}.pdf"
        return pdf.risposta("reports/pdf/wbs_spese.html", contesto, nome, request)
    return render(request, "reports/wbs_spese.html", contesto)


@login_required
def extra_budget_elenco(request):
    """Autorizzazioni extra budget dell'AD (Rev18) con voci collegate, consumato e residuo."""
    g = request.GET
    scelti = g.getlist("sottocluster")
    sottocluster = permessi.filtro_sottocluster(request.user, scelti)
    elenco = list(
        elenco_autorizzazioni([], archiviate=bool(g.get("archiviate")), sottocluster=sottocluster)
    )
    for a in elenco:
        a.residuo = a.importo_autorizzato - a.consumato
        a.avviso = avviso_sforamento(a, a.consumato)
    return render(
        request,
        "reports/extra_budget_elenco.html",
        {
            "elenco": elenco,
            "filtro_sottocluster": permessi.contesto_filtro_sottocluster(request.user, scelti),
            "filtri": g,
        },
    )


@login_required
def extra_budget_spese(request, pk):
    """Spese di un'autorizzazione extra budget: voci collegate e importi anno per anno."""
    autorizzazione = get_object_or_404(
        m.AutorizzazioneExtraBudget.objects.select_related("cluster"), pk=pk
    )
    vista = request.GET.get("vista") if request.GET.get("vista") in VISTE else "cassa"
    try:
        livello = Livello(request.GET.get("livello") or Livello.PROBABILE)
    except ValueError:
        livello = Livello.PROBABILE
    spese = spese_extra_budget(autorizzazione, vista, livello)
    return render(
        request,
        "reports/extra_budget_spese.html",
        {
            "s": spese,
            "anni": spese.anni,
            "righe": [(r, [r.per_anno.get(a) for a in spese.anni]) for r in spese.righe],
            "totali": [spese.totali()[a] for a in spese.anni],
            "viste": [(v, ETICHETTE_VISTE[v]) for v in VISTE],
            "livelli": LIVELLI,
        },
    )
