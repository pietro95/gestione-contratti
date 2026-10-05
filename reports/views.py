"""Report (F5): budget dell'anno e piano ordini. Sola lettura, visibili a tutti i ruoli."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from contratti import models as m
from contratti import permessi
from contratti.engine.tipi import Livello
from contratti.views import oggi_richiesta
from reports import xlsx
from reports.budget import (
    ETICHETTE_VISTE,
    LIVELLI,
    NATURE,
    PARTI,
    RAGGRUPPAMENTI,
    VISTE,
    calcola_budget,
)
from reports.export import budget_xlsx, piano_xlsx
from reports.forms import FiltriBudgetForm, FiltriPianoForm
from reports.piano_ordini import calcola_piano
from reports.wbs import elenco_wbs, spese_wbs


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
    if request.GET.get("formato") == "xlsx":
        nome = f"{oggi:%Y.%m.%d}_Piano_ordini_{piano.anno}.xlsx"
        natura = d.get("natura") or ""
        return xlsx.risposta(piano_xlsx(piano, oggi, form.descrizione(), natura), nome)
    contesto |= {
        "piano": piano,
        # Con il filtro di natura, solo i totali di quella natura (un previsto misto resta
        # in elenco con l'importo intero, ma la sua quota dell'altra natura non si conta).
        "per_natura": {d["natura"]: piano.totali(d["natura"])}
        if d.get("natura")
        else piano.totali_per_natura(),
        "livelli": LIVELLI,
    }
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
            "area_scelta": permessi.scelta_filtro(request.user, g.getlist("area")),
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
    return render(
        request,
        "reports/wbs_spese.html",
        {
            "s": spese,
            "anni": spese.anni,
            "righe": [(r, [r.per_anno.get(a) for a in spese.anni]) for r in spese.righe],
            "totali": [spese.totali()[a] for a in spese.anni],
            "viste": [(v, ETICHETTE_VISTE[v]) for v in VISTE],
            "livelli": LIVELLI,
        },
    )
