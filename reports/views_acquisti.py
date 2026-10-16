"""Viste del processo d'acquisto (F11.4, SPEC §5.7, §5.8): cruscotto acquisti, stato delle
RDA, contratti da chiudere, anomalie dell'esecuzione. Sola lettura, tutti i ruoli; export XLSX
e PDF con i filtri in evidenza."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from contratti import models as m
from contratti import permessi
from contratti import stanziamenti as servizi_stanziamenti
from contratti.engine import acquisti as motore
from contratti.views import oggi_richiesta
from reports import acquisti, pdf, xlsx
from reports.export import suffisso_cluster
from reports.export_acquisti import (
    DESCRIZIONE_ANOMALIE,
    anomalie_xlsx,
    contratti_da_chiudere_xlsx,
    stato_rda_xlsx,
)
from reports.forms import FiltriClusterForm, FiltriRdaForm

Passo = motore.PassoFattura


def _pdf(request, template, contesto, form, titolo, nome):
    contesto |= {
        "titolo": titolo,
        "filtri": form.descrizione(),
        "voci_filtri": form.voci(),
        "cluster": permessi.descrivi_filtro(form.codici_cluster()),
    }
    return pdf.risposta(template, contesto, nome, request)


@login_required
def cruscotto_acquisti(request):
    """Il cruscotto dell'addetto (SPEC §5.7), visibile a tutti: RDA da processare per azione,
    fatture da lavorare per passo, contratti da chiudere."""
    oggi = oggi_richiesta(request)
    form = FiltriClusterForm(request.GET, utente=request.user)
    codici = form.codici_cluster() if form.is_valid() else ()
    rda = acquisti.rda_da_processare(codici, oggi)
    fatture = acquisti.fatture_da_lavorare(oggi)
    da_chiudere = acquisti.contratti_da_chiudere(codici, oggi)
    return render(
        request,
        "reports/cruscotto_acquisti.html",
        {
            "oggi": oggi,
            "form": form,
            "rda": rda,
            "rda_totale": sum(len(g[2]) for g in rda),
            "rda_ferme": sum(1 for g in rda for r in g[2] if r.ferma),
            "da_prendere": fatture[Passo.PRESA_IN_CARICO],
            "da_convalidare": fatture[Passo.CONVALIDA],
            "bloccate": fatture[Passo.BLOCCATA],
            "fatture_per_passo": [
                (p, motore.ETICHETTE_PASSO[p], fatture[p])
                for p in (Passo.ASSEGNAZIONE, Passo.RDC, Passo.MAP_MIGO, Passo.TRASFERIMENTO)
            ],
            "fatture_ferme": sum(1 for g in fatture.values() for r in g if r.ferma),
            "da_chiudere": da_chiudere,
            "addetto": permessi.e_addetto(request.user),
        },
    )


@login_required
def stato_rda(request):
    oggi = oggi_richiesta(request)
    form = FiltriRdaForm(request.GET, utente=request.user)
    contesto = {"form": form, "oggi": oggi}
    if not form.is_valid():
        return render(request, "reports/stato_rda.html", contesto)
    righe = acquisti.stato_rda(form.filtri(), oggi)
    nome = f"{oggi:%Y.%m.%d}_Stato_RDA{suffisso_cluster(form.codici_cluster())}"
    if request.GET.get("formato") == "xlsx":
        return xlsx.risposta(stato_rda_xlsx(righe, oggi, form.descrizione()), f"{nome}.xlsx")
    contesto |= {
        "righe": righe,
        "per_fase": acquisti.conteggi_per_fase(righe),
        "totale": sum((r.importo for r in righe), acquisti.ZERO),
        "ferme": sum(1 for r in righe if r.ferma),
    }
    if request.GET.get("formato") == "pdf":
        return _pdf(
            request, "reports/pdf/stato_rda.html", contesto, form, "Stato delle RDA", f"{nome}.pdf"
        )
    return render(request, "reports/stato_rda.html", contesto)


@login_required
def contratti_da_chiudere(request):
    oggi = oggi_richiesta(request)
    form = FiltriClusterForm(request.GET, utente=request.user)
    contesto = {"form": form, "oggi": oggi}
    if not form.is_valid():
        return render(request, "reports/contratti_da_chiudere.html", contesto)
    righe = acquisti.contratti_da_chiudere(form.codici_cluster(), oggi)
    nome = f"{oggi:%Y.%m.%d}_Contratti_da_chiudere{suffisso_cluster(form.codici_cluster())}"
    if request.GET.get("formato") == "xlsx":
        wb = contratti_da_chiudere_xlsx(righe, oggi, form.descrizione())
        return xlsx.risposta(wb, f"{nome}.xlsx")
    per_motivo = {}
    for r in righe:
        per_motivo[r.motivo_label] = per_motivo.get(r.motivo_label, 0) + 1
    contesto |= {"righe": righe, "per_motivo": per_motivo}
    if request.GET.get("formato") == "pdf":
        return _pdf(
            request, "reports/pdf/contratti_da_chiudere.html", contesto, form,
            "Contratti da chiudere", f"{nome}.pdf",
        )  # fmt: skip
    return render(request, "reports/contratti_da_chiudere.html", contesto)


@login_required
def stanziamenti(request):
    """Stanziamenti proposti (rate scadute senza fattura) e registrati attivi (SPEC Rev22)."""
    oggi = oggi_richiesta(request)
    form = FiltriClusterForm(request.GET, utente=request.user)
    contesto = {"form": form, "oggi": oggi}
    if not form.is_valid():
        return render(request, "reports/stanziamenti.html", contesto)
    codici = form.codici_cluster()
    registrati = m.Stanziamento.objects.filter(
        archiviato=False, fattura__isnull=True, voce__contratto__archiviato=False
    )
    if codici:
        registrati = registrati.filter(voce__contratto__fabbisogno__cluster__codice__in=codici)
    registrati = [
        s
        for s in registrati.select_related(
            "voce__contratto__fabbisogno", "voce__contratto__fornitore", "rata"
        ).order_by("competenza_dal", "pk")
        if not s.chiuso
    ]
    proposte = servizi_stanziamenti.proposte(oggi, codici)
    contesto |= {
        "proposte": proposte,
        "registrati": registrati,
        "totale_proposto": sum((p.importo for p in proposte), acquisti.ZERO),
        "totale_registrato": sum((s.importo for s in registrati), acquisti.ZERO),
        "tolleranza": servizi_stanziamenti.tolleranza(oggi),
        "puo_modificare": permessi.cluster_modificabili(request.user) != frozenset(),
    }
    return render(request, "reports/stanziamenti.html", contesto)


@login_required
def anomalie_esecuzione(request):
    oggi = oggi_richiesta(request)
    form = FiltriClusterForm(request.GET, utente=request.user)
    contesto = {"form": form, "oggi": oggi}
    if not form.is_valid():
        return render(request, "reports/anomalie_esecuzione.html", contesto)
    righe = acquisti.anomalie_esecuzione(form.codici_cluster(), oggi)
    nome = f"{oggi:%Y.%m.%d}_Anomalie_esecuzione{suffisso_cluster(form.codici_cluster())}"
    if request.GET.get("formato") == "xlsx":
        return xlsx.risposta(anomalie_xlsx(righe, oggi, form.descrizione()), f"{nome}.xlsx")
    contesto |= {
        "righe": righe,
        "conteggi": [
            (k, DESCRIZIONE_ANOMALIE.get(k, k), n)
            for k, n in acquisti.conteggi_anomalie(righe).items()
        ],
        "descrizioni": DESCRIZIONE_ANOMALIE,
        "per_fattura": acquisti.PER_FATTURA,
    }
    if request.GET.get("formato") == "pdf":
        return _pdf(
            request, "reports/pdf/anomalie_esecuzione.html", contesto, form,
            "Anomalie dell'esecuzione", f"{nome}.pdf",
        )  # fmt: skip
    return render(request, "reports/anomalie_esecuzione.html", contesto)
