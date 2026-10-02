"""Import dall'interfaccia (F9.1): elenco, caricamento con anteprima, conferma, modelli."""

from django import forms as dj_forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import editor_required
from contratti import importazioni as imp_svc
from contratti import models as m
from contratti.forms import FormBase
from reports import xlsx

PER_PAGINA = 30
RIGHE_ANTEPRIMA = 500  # anomalie mostrate in pagina; il file XLSX le ha tutte


class CaricaForm(FormBase):
    file = dj_forms.FileField(label="File")
    area = dj_forms.ChoiceField(choices=[], required=False, label="Cluster")

    def __init__(self, *args, tipo: imp_svc.Tipo, utente=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tipo = tipo
        self.fields["file"].widget.attrs["accept"] = ",".join(tipo.estensioni)
        self.fields["file"].help_text = (
            f"{', '.join(tipo.estensioni)}, al massimo 10 MB. Prima vedi l'anteprima."
            if tipo.con_conferma
            else f"{', '.join(tipo.estensioni)}, al massimo 10 MB."
        )
        if tipo.chiede_area:
            self.fields["area"].required = True
            self.fields["area"].choices = imp_svc.cluster_importabili(tipo, utente)
        else:
            del self.fields["area"]


def _tipo(codice: str) -> imp_svc.Tipo:
    tipo = imp_svc.TIPI.get(codice)
    if tipo is None:
        raise Http404
    return tipo


@editor_required
def importazioni(request):
    tipi = imp_svc.tipi_per(request.user)
    registro = m.Importazione.objects.select_related("utente").defer("contenuto", "risultato")
    return render(
        request,
        "contratti/import/elenco.html",
        {
            "schede": [(t, CaricaForm(tipo=t, prefix=t.codice, utente=request.user)) for t in tipi],
            "registro": [
                (imp, imp_svc.TIPI[imp.tipo].titolo if imp.tipo in imp_svc.TIPI else imp.tipo)
                for imp in registro[:PER_PAGINA]
            ],
        },
    )


@editor_required
@require_POST
def importazione_carica(request, tipo):
    tipo = _tipo(tipo)
    if not imp_svc.puo_usare(request.user, tipo):
        raise PermissionDenied
    form = CaricaForm(
        request.POST, request.FILES, tipo=tipo, prefix=tipo.codice, utente=request.user
    )
    if not form.is_valid():
        for errori in form.errors.values():
            for e in errori:
                messages.error(request, f"{tipo.titolo}: {e}")
        return redirect("contratti:importazioni")
    opzioni = {"area": form.cleaned_data["area"]} if tipo.chiede_area else {}
    try:
        imp = imp_svc.carica(tipo, form.cleaned_data["file"], opzioni, request.user)
    except imp_svc.ImportNonAmmesso as exc:
        messages.error(request, f"{tipo.titolo}: {exc}")
        return redirect("contratti:importazioni")
    return redirect("contratti:importazione", pk=imp.pk)


def _importazione(request, pk) -> m.Importazione:
    imp = get_object_or_404(m.Importazione.objects.select_related("utente", "confermata_da"), pk=pk)
    if imp.tipo not in imp_svc.TIPI:
        raise Http404
    return imp


def _righe_conteggi(tipo, dati):
    conteggi = dati.get("conteggi", {}) if dati else {}
    return [(etichetta, conteggi.get(k, 0)) for k, etichetta in tipo.etichette.items()]


@editor_required
def importazione(request, pk):
    imp = _importazione(request, pk)
    tipo = imp_svc.TIPI[imp.tipo]
    if imp_svc.scaduta(imp):
        imp.stato = m.Importazione.Stato.SCADUTA
        imp.save(update_fields=["stato"])
    dati = imp.esito if imp.stato == m.Importazione.Stato.CONFERMATA else imp.anteprima
    anomalie = dati.get("anomalie", []) if dati else []
    return render(
        request,
        "contratti/import/dettaglio.html",
        {
            "imp": imp,
            "tipo": tipo,
            "conteggi": _righe_conteggi(tipo, dati),
            "anteprima_conteggi": _righe_conteggi(tipo, imp.anteprima),
            "anomalie": anomalie[:RIGHE_ANTEPRIMA],
            "anomalie_totali": len(anomalie),
            "mappature": dati.get("mappature", []) if dati else [],
            "riepilogo": dati.get("riepilogo", []) if dati else [],
            "puo_confermare": imp.stato == m.Importazione.Stato.ANTEPRIMA
            and imp_svc.puo_confermare(request.user, imp),
            "gia_importato": imp_svc.gia_importato(imp),
        },
    )


@editor_required
@require_POST
def importazione_conferma(request, pk):
    try:
        imp = imp_svc.conferma(pk, request.user)
    except m.Importazione.DoesNotExist as exc:
        raise Http404 from exc
    except imp_svc.ImportNonAmmesso as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Import di «{imp.nome_file}» eseguito.")
    return redirect("contratti:importazione", pk=pk)


@editor_required
@require_POST
def importazione_annulla(request, pk):
    try:
        imp_svc.annulla(pk, request.user)
    except m.Importazione.DoesNotExist as exc:
        raise Http404 from exc
    except imp_svc.ImportNonAmmesso as exc:
        messages.error(request, str(exc))
    else:
        messages.info(request, "Anteprima annullata: nessun dato importato.")
    return redirect("contratti:importazioni")


@editor_required
def importazione_report(request, pk):
    imp = _importazione(request, pk)
    if imp.tipo == "quadratura" and imp.risultato:
        risposta = HttpResponse(bytes(imp.risultato), content_type=xlsx.TIPO_XLSX)
        risposta["Content-Disposition"] = f'attachment; filename="quadratura_{imp.pk}.xlsx"'
        return risposta
    confermata = imp.stato == m.Importazione.Stato.CONFERMATA
    dati = imp.esito if confermata else imp.anteprima
    nome = f"{'esito' if confermata else 'anteprima'}_import_{imp.pk}.xlsx"
    return xlsx.risposta(imp_svc.report_xlsx(imp, dati or {}), nome)


@editor_required
def importazione_modello(request, tipo):
    tipo = _tipo(tipo)
    if tipo.modello is None or not imp_svc.puo_usare(request.user, tipo):
        raise Http404
    nome = tipo.nome_modello or f"Modello_import_{tipo.codice}.xlsx"
    return xlsx.risposta(tipo.modello(), nome)
