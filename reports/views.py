"""Report (F5): budget dell'anno e piano ordini. Sola lettura, visibili a tutti i ruoli."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from contratti import models as m
from contratti import permessi
from contratti.engine.tipi import Livello
from contratti.selettori import codici_cluster
from contratti.views import oggi_richiesta
from reports import pdf, xlsx
from reports.budget import (
    ETICHETTE_VISTE,
    LIVELLI,
    NATURE,
    PARTI,
    RAGGRUPPAMENTI,
    VISTE,
    calcola_budget,
)
from reports.export import budget_xlsx, descrivi_filtri, piano_xlsx, suffisso_cluster, voci_filtri
from reports.extra_budget import avviso_sforamento, elenco_autorizzazioni, spese_extra_budget
from reports.forms import FiltriBudgetForm, FiltriPianoForm
from reports.piano_ordini import calcola_piano
from reports.wbs import elenco_wbs, spese_wbs

VISTA_SEMPLIFICATA = "semplificata"


def _celle(totali, livello) -> list:
    """Per ogni vista: consolidato, previsionale e totale al livello scelto."""
    return [[totali[parte][vista][livello] for parte in PARTI] for vista in VISTE]


def _sezione(b, criterio, livello) -> dict:
    """Una natura del budget (OPEX o CAPEX): riepilogo, gruppi e totali, mai sommati tra loro."""
    totali = b.totali()
    return {
        "natura": b.filtri.natura,
        "budget": b,
        "criterio": RAGGRUPPAMENTI[criterio],
        "riepilogo": [
            (ETICHETTE_VISTE[vista], [[totali[p][vista][liv] for p in PARTI] for liv in LIVELLI])
            for vista in VISTE
        ],
        "gruppi": [
            {
                "etichetta": g.etichetta,
                "celle": _celle(g.totali, livello),
                # CAPEX per WBS: il dettaglio per conto, come lo legge il Controllo di gestione.
                "sotto": [(sg.etichetta, _celle(sg.totali, livello)) for sg in g.sotto("conto")]
                if criterio == "wbs"
                else [],
                "voci": [(v, [v.importi[vista][livello] for vista in VISTE]) for v in g.voci],
            }
            for g in b.gruppi(criterio)
        ],
        "totale_celle": _celle(totali, livello),
        "kpi": [(ETICHETTE_VISTE[v], *[totali[p][v][livello] for p in PARTI]) for v in VISTE],
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
    criteri = {n: form.criterio(n) for n in NATURE}
    if request.GET.get("formato") == "xlsx":
        natura = b.filtri.natura or "OPEX_CAPEX"
        nome = f"{oggi:%Y.%m.%d}_Budget_{b.filtri.anno}_{natura}.xlsx"
        return xlsx.risposta(budget_xlsx(b, criteri), nome)
    contesto |= {
        "budget": b,
        "sezioni": [_sezione(s, criteri[s.filtri.natura], livello) for s in b.sezioni()],
        "livelli": LIVELLI,
        "n_avvisi": len(b.rinnovi_mancanti) + len(b.avvisi) + (1 if b.senza_data else 0),
        "livello": livello,
    }
    if request.GET.get("formato") == "pdf":
        natura = b.filtri.natura or "OPEX_CAPEX"
        titolo = f"Budget {b.filtri.anno}" + (f" · {b.filtri.natura}" if b.filtri.natura else "")
        codici = codici_cluster(b.filtri.area)
        contesto |= {
            "titolo": titolo,
            "filtri": descrivi_filtri(b),
            "voci_filtri": voci_filtri(b),
            "cluster": permessi.descrivi_filtro(codici),
            "dettaglio": bool(request.GET.get("dettaglio")),
        }
        nome = f"{oggi:%Y.%m.%d}_Budget_{b.filtri.anno}_{natura}{suffisso_cluster(codici)}.pdf"
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
    categoria = d["categoria"].pk if d.get("categoria") else None
    piano = calcola_piano(
        d["anno"],
        oggi,
        area=form.codici_cluster(),
        categoria=categoria,
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
    # interni (categoria, procedura, lead time, data limite, fase, ritardo, fisso e probabile).
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
        codici = form.codici_cluster()
        contesto |= {
            "titolo": f"Piano ordini {piano.anno}",
            # Gli avvisi di frazionamento sono una verifica interna: nel PDF solo a richiesta.
            "con_avvisi": bool(request.GET.get("dettaglio")),
            "filtri": form.descrizione(),
            "voci_filtri": form.voci(),
            "cluster": permessi.descrivi_filtro(codici),
        }
        nome = f"{oggi:%Y.%m.%d}_Piano_ordini_{piano.anno}{suffisso_cluster(codici)}.pdf"
        return pdf.risposta("reports/pdf/piano_ordini.html", contesto, nome, request)
    return render(request, "reports/piano_ordini.html", contesto)


@login_required
def wbs_elenco(request):
    """WBS di cluster (di default dei propri cluster) e WBS a progetto, con il numero di voci."""
    g = request.GET
    codici = permessi.codici_filtro(request.user, g.getlist("area"))
    tipo = g.get("tipo", "") if g.get("tipo") in m.WBS.Tipo.values else ""
    return render(
        request,
        "reports/wbs_elenco.html",
        {
            "elenco": elenco_wbs(codici, tipo, archiviate=bool(g.get("archiviate"))),
            "aree": permessi.scelte_filtro(request.user),
            "area_scelte": permessi.selezione_filtro(request.user, g.getlist("area")),
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
        "righe": [(r, [r.per_anno.get(a) for a in spese.anni]) for r in spese.righe],
        "totali": [spese.totali()[a] for a in spese.anni],
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
    codici = permessi.codici_filtro(request.user, g.getlist("area"))
    elenco = list(elenco_autorizzazioni(codici, archiviate=bool(g.get("archiviate"))))
    for a in elenco:
        a.residuo = a.importo_autorizzato - a.consumato
        a.avviso = avviso_sforamento(a, a.consumato)
    return render(
        request,
        "reports/extra_budget_elenco.html",
        {
            "elenco": elenco,
            "aree": permessi.scelte_filtro(request.user),
            "area_scelte": permessi.selezione_filtro(request.user, g.getlist("area")),
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
