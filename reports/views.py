"""Report (F5): budget dell'anno e piano ordini. Sola lettura, visibili a tutti i ruoli."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from contratti.views import oggi_richiesta
from reports import xlsx
from reports.budget import ETICHETTE_VISTE, LIVELLI, PARTI, RAGGRUPPAMENTI, VISTE, calcola_budget
from reports.export import budget_xlsx, piano_xlsx
from reports.forms import FiltriBudgetForm, FiltriPianoForm
from reports.piano_ordini import calcola_piano


def _celle(totali, livello) -> list:
    """Per ogni vista: consolidato, previsionale e totale al livello scelto."""
    return [[totali[parte][vista][livello] for parte in PARTI] for vista in VISTE]


@login_required
def budget(request):
    oggi = oggi_richiesta(request)
    form = FiltriBudgetForm(request.GET, anno_default=oggi.year)
    contesto = {"form": form, "oggi": oggi, "viste": [ETICHETTE_VISTE[v] for v in VISTE]}
    if not form.is_valid():
        return render(request, "reports/budget.html", contesto)
    b = calcola_budget(form.filtri(), oggi)
    criterio, livello = form.criterio, form.livello_scelto
    if request.GET.get("formato") == "xlsx":
        nome = f"{oggi:%Y.%m.%d}_Budget_{b.filtri.anno}.xlsx"
        return xlsx.risposta(budget_xlsx(b, criterio), nome)
    totali = b.totali()
    riepilogo = [
        (ETICHETTE_VISTE[vista], [[totali[p][vista][liv] for p in PARTI] for liv in LIVELLI])
        for vista in VISTE
    ]
    gruppi = [
        {
            "etichetta": g.etichetta,
            "celle": _celle(g.totali, livello),
            "voci": [(v, [v.importi[vista][livello] for vista in VISTE]) for v in g.voci],
        }
        for g in b.gruppi(criterio)
    ]
    contesto |= {
        "budget": b,
        "riepilogo": riepilogo,
        "livelli": LIVELLI,
        "gruppi": gruppi,
        "totale_celle": _celle(totali, livello),
        "n_avvisi": len(b.rinnovi_mancanti) + len(b.avvisi) + (1 if b.senza_data else 0),
        "kpi": [(ETICHETTE_VISTE[v], *[totali[p][v][livello] for p in PARTI]) for v in VISTE],
        "criterio": RAGGRUPPAMENTI[criterio],
        "livello": livello,
    }
    return render(request, "reports/budget.html", contesto)


@login_required
def piano_ordini(request):
    oggi = oggi_richiesta(request)
    form = FiltriPianoForm(request.GET, anno_default=oggi.year)
    contesto = {"form": form, "oggi": oggi}
    if not form.is_valid():
        return render(request, "reports/piano_ordini.html", contesto)
    d = form.cleaned_data
    categoria = d["categoria"].pk if d.get("categoria") else None
    piano = calcola_piano(d["anno"], oggi, area=d.get("area") or "", categoria=categoria)
    if request.GET.get("formato") == "xlsx":
        nome = f"{oggi:%Y.%m.%d}_Piano_ordini_{piano.anno}.xlsx"
        return xlsx.risposta(piano_xlsx(piano, oggi, form.descrizione()), nome)
    contesto |= {"piano": piano, "totali": piano.totali(), "livelli": LIVELLI}
    return render(request, "reports/piano_ordini.html", contesto)
