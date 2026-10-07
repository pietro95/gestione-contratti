"""Richieste di RDA (F11.2, SPEC §4, §5.7, §5.9).

Lettura per tutti i ruoli; ogni modifica è di Admin ed Editor dei cluster della RDA
(``editor_required`` + ``permessi.verifica``): il Reader riceve 403.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import editor_required
from contratti import acquisti, permessi
from contratti import forms_rda as forms
from contratti import models as m
from contratti.engine import acquisti as motore
from contratti.views import (
    PER_PAGINA,
    _cluster_richiesti,
    _contesto_cluster,
    _pk_o_none,
    filtri_attivi,
    oggi_richiesta,
    storico,
)

Fase = motore.Fase


def _errore(request, exc) -> None:
    messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))


def _qs_rda():
    return acquisti.QS_RDA.select_related(
        "cluster",
        "fabbisogno",
        "contratto_in_scadenza__fabbisogno",
        "contratto_in_scadenza__fornitore",
        "referente_utente",
        "fornitore_proposto",
        "richiedente",
        "gruppo_acquisti",
    ).prefetch_related(
        Prefetch("posizioni", queryset=m.PosizioneRDA.objects.order_by("numero")),
    )


def _rda(pk) -> m.RichiestaAcquisto:
    return get_object_or_404(_qs_rda(), pk=pk)


def _modificabile(request, rda) -> None:
    permessi.verifica(request.user, rda.cluster_id)


def riga(rda: m.RichiestaAcquisto, oggi) -> dict:
    dati = acquisti.dati_rda(rda)
    fase = motore.fase(dati, oggi)
    data = motore.data_fase(dati, oggi)
    return {
        "rda": rda,
        "fase": fase,
        "fase_label": motore.ETICHETTE_FASE[fase],
        "data_fase": data,
        "giorni": (oggi - data).days if data else None,
        "importo": sum((p.importo for p in rda.posizioni.all()), acquisti.ZERO),
        "fabbisogno": rda.fabbisogno_della_pratica(),
    }


# --- Elenco -----------------------------------------------------------------------------


@login_required
def rda_elenco(request):
    oggi = oggi_richiesta(request)
    g = request.GET
    qs = _qs_rda()
    if not g.get("archiviate"):
        qs = qs.filter(archiviato=False)
    if codici := _cluster_richiesti(request):
        qs = qs.filter(cluster__codice__in=codici)
    if g.get("mie"):
        qs = qs.filter(referente_utente=request.user)
    if q := g.get("q", "").strip():
        qs = qs.filter(
            Q(numero_rda__icontains=q)
            | Q(descrizione__icontains=q)
            | Q(intestazione__icontains=q)
            | Q(fabbisogno__descrizione__icontains=q)
            | Q(contratto_in_scadenza__fabbisogno__descrizione__icontains=q)
            | Q(referente__icontains=q)
        )
    righe = [riga(r, oggi) for r in qs.order_by("-data_creazione", "-pk")]
    if fase := g.get("fase"):
        righe = [r for r in righe if r["fase"] == fase]
    pagina = Paginator(righe, PER_PAGINA).get_page(g.get("pagina"))
    return render(
        request,
        "contratti/rda_elenco.html",
        {
            "pagina": pagina,
            "totale": len(righe),
            "oggi": oggi,
            "filtri": g,
            "fasi": list(motore.ETICHETTE_FASE.items()),
            "attivi": filtri_attivi(
                g,
                {
                    "q": "Testo",
                    "fase": lambda v: "Fase: " + motore.ETICHETTE_FASE.get(v, v),
                    "mie": lambda v: "Le mie RDA",
                    "archiviate": lambda v: "Con le archiviate",
                },
            ),
            **_contesto_cluster(request),
            "puo_scrivere": permessi.puo_modificare(request.user),
        },
    )


# --- Nuova richiesta dal fabbisogno --------------------------------------------------------


@editor_required
def rda_nuova(request, fabbisogno_pk):
    """Richiesta di RDA dal fabbisogno: rinnovo, primo acquisto o acquisto aggiuntivo."""
    f = get_object_or_404(
        m.Fabbisogno.objects.select_related("cluster", "categoria"), pk=fabbisogno_pk
    )
    permessi.verifica_oggetto(request.user, f)
    dati = request.POST if request.method == "POST" else request.GET
    aggiuntivo = dati.get("aggiuntivo") == "1"
    scelto = _pk_o_none(dati.get("contratto"))
    contratto = m.Contratto.objects.filter(pk=scelto, fabbisogno=f).first() if scelto else None
    try:
        proposta = acquisti.proposta_richiesta(
            f, oggi_richiesta(request), aggiuntivo=aggiuntivo, contratto_in_scadenza=contratto
        )
    except acquisti.OperazioneNonAmmessa as exc:
        _errore(request, exc)
        return redirect("contratti:fabbisogno", pk=f.pk)
    istanza = m.RichiestaAcquisto(
        origine=m.RichiestaAcquisto.Origine.PORTALE,
        scopo=proposta.scopo,
        cluster=f.cluster,
        fabbisogno=None if proposta.contratto_in_scadenza else f,
        contratto_in_scadenza=proposta.contratto_in_scadenza,
        referente_utente=request.user,
        data_creazione=oggi_richiesta(request),
    )
    iniziali = {
        "descrizione": proposta.descrizione,
        "intestazione": proposta.intestazione,
        "fornitore_proposto": proposta.fornitore_proposto,
        "richiedente": proposta.richiedente,
        "gruppo_acquisti": proposta.gruppo_acquisti,
        "percorso_file_server": proposta.percorso_file_server,
        "rup": proposta.rup,
        "cup": proposta.cup,
    }
    form = forms.RichiestaForm(request.POST or None, instance=istanza, initial=iniziali)
    formset = forms.PosizioniFormSet(
        request.POST or None,
        initial=forms.iniziali_posizioni(proposta.posizioni),
        prefix="pos",
        cluster=f.cluster,
    )
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        try:
            rda = acquisti.salva_richiesta(form.save(commit=False), formset.posizioni())
            if "invia" in request.POST:
                acquisti.invia(rda, request.user)
        except (acquisti.OperazioneNonAmmessa, ValidationError) as exc:
            _errore(request, exc)
        else:
            messages.success(
                request,
                "Richiesta inviata all'addetto." if "invia" in request.POST
                else "Richiesta salvata in bozza: inviala quando è completa.",
            )  # fmt: skip
            return redirect("contratti:rda", pk=rda.pk)
    return render(
        request,
        "contratti/rda_form.html",
        {
            "form": form,
            "formset": formset,
            "fabbisogno": f,
            "proposta": proposta,
            "aggiuntivo": aggiuntivo,
            "titolo": "Nuova richiesta di RDA",
            "nuova": True,
        },
    )


@editor_required
def rda_modifica(request, pk):
    rda = _rda(pk)
    _modificabile(request, rda)
    if acquisti.fase(rda) in (Fase.ANNULLATA, Fase.CHIUSA):
        messages.error(request, "La RDA è annullata o chiusa: non si modifica.")
        return redirect("contratti:rda", pk=pk)
    form = forms.RichiestaForm(request.POST or None, instance=rda)
    formset = forms.PosizioniFormSet(
        request.POST or None,
        initial=forms.iniziali_posizioni(rda.posizioni.all()),
        prefix="pos",
        cluster=rda.cluster,
    )
    correzione = acquisti.correzione_diretta(rda)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        try:
            acquisti.salva_richiesta(form.save(commit=False), formset.posizioni())
            if "invia" in request.POST:
                acquisti.invia(rda, request.user)
        except (acquisti.OperazioneNonAmmessa, ValidationError) as exc:
            _errore(request, exc)
        else:
            messages.success(request, "Richiesta aggiornata.")
            return redirect("contratti:rda", pk=pk)
    return render(
        request,
        "contratti/rda_form.html",
        {
            "form": form,
            "formset": formset,
            "rda": rda,
            "fabbisogno": rda.fabbisogno_della_pratica(),
            "correzione": correzione,
            "puo_inviare": not correzione,
            "titolo": f"Modifica — {rda}",
        },
    )


@editor_required
def rda_registra(request):
    """RDA già inserita in SAP, registrata a mano (migrazione): anche senza legami."""
    form = forms.RdaManualeForm(
        request.POST or None,
        instance=m.RichiestaAcquisto(origine=m.RichiestaAcquisto.Origine.MANUALE),
        utente=request.user,
    )
    if request.method == "POST" and form.is_valid():
        permessi.verifica(request.user, form.cleaned_data["cluster"].pk)
        rda = form.save()
        messages.success(request, "RDA registrata. Collegala alla pratica e ai contratti.")
        return redirect("contratti:rda", pk=rda.pk)
    return render(
        request,
        "contratti/form.html",
        {"form": form, "titolo": "Registra una RDA già in SAP"},
    )


# --- Dettaglio e azioni -----------------------------------------------------------------


@login_required
def rda_dettaglio(request, pk):
    oggi = oggi_richiesta(request)
    rda = _rda(pk)
    r = riga(rda, oggi)
    scheda = acquisti.scheda(rda)
    pratica = rda.contratto_in_scadenza or rda.fabbisogno
    generati = list(rda.contratti_generati.filter(archiviato=False).select_related("fornitore"))
    return render(
        request,
        "contratti/rda_dettaglio.html",
        {
            "r": r,
            "rda": rda,
            "oggi": oggi,
            "scheda": scheda,
            "testo": motore.componi_testo_richiesta(scheda),
            "eventi": rda.eventi.select_related("utente").order_by("-data", "-pk"),
            "pratica": pratica,
            "stato_pratica": _stato_pratica(pratica, rda, oggi),
            "generati": [(c, acquisti.differenza_da_rda(c)) for c in generati],
            "proposti": acquisti.contratti_proposti(rda),
            "puo_modificare": permessi.puo_modificare(request.user, rda.cluster_id),
            "puo_inviare": r["fase"] in acquisti.FASI_MODIFICABILI_DAL_REFERENTE,
            "puo_rimandare": r["fase"] == Fase.INVIATA,
            "chiusa": r["fase"] in (Fase.ANNULLATA, Fase.CHIUSA),
            "form_sap": forms.DatiSapForm(instance=rda),
            "form_nota": forms.NotaForm(),
            "form_pratica": forms.CollegaPraticaForm(
                rda=rda,
                utente=request.user,
                initial={"contratto": rda.contratto_in_scadenza, "fabbisogno": rda.fabbisogno},
            ),
            "form_contratto": forms.CollegaContrattoForm(rda=rda),
            "storico": storico(rda),
            "tipi_evento": m.EventoRDA.Tipo,
        },
    )


def _stato_pratica(pratica, rda, oggi):
    """(etichetta, data) dello stato della pratica legata alla RDA."""
    if pratica is None or rda.scopo == m.RichiestaAcquisto.Scopo.AGGIUNTIVO:
        return None
    stato = acquisti.stato_pratica_con_data(pratica, oggi)
    if stato is None:
        return (m.StatoPratica.Stato.NON_AVVIATA.label, None)
    return (m.StatoPratica.Stato(stato[0]).label, stato[1])


def _azione(request, pk, esegui, successo: str):
    rda = _rda(pk)
    _modificabile(request, rda)
    try:
        esegui(rda)
    except (acquisti.OperazioneNonAmmessa, ValidationError) as exc:
        _errore(request, exc)
    else:
        messages.success(request, successo)
    return redirect("contratti:rda", pk=pk)


@editor_required
@require_POST
def rda_invia(request, pk):
    return _azione(
        request, pk, lambda r: acquisti.invia(r, request.user), "Richiesta inviata all'addetto."
    )


@editor_required
@require_POST
def rda_rimanda(request, pk):
    form = forms.NotaForm(request.POST)
    nota = form.cleaned_data["nota"] if form.is_valid() else ""
    return _azione(
        request,
        pk,
        lambda r: acquisti.rimanda(r, nota, request.user),
        "Richiesta rimandata al referente.",
    )


@editor_required
@require_POST
def rda_annulla(request, pk):
    form = forms.NotaForm(request.POST)
    motivo = form.cleaned_data["nota"] if form.is_valid() else ""
    return _azione(
        request, pk, lambda r: acquisti.annulla(r, motivo, request.user), "RDA annullata."
    )


@editor_required
@require_POST
def rda_dati_sap(request, pk):
    rda = _rda(pk)
    _modificabile(request, rda)
    form = forms.DatiSapForm(request.POST, instance=m.RichiestaAcquisto.objects.get(pk=pk))
    if not form.is_valid():
        messages.error(request, "Dati SAP non validi: " + "; ".join(
            f"{k}: {' '.join(v)}" for k, v in form.errors.items()
        ))  # fmt: skip
        return redirect("contratti:rda", pk=pk)
    d = form.cleaned_data
    return _azione(
        request,
        pk,
        lambda r: acquisti.aggiorna_dati_sap(
            r, d["numero_rda"], d["data_inserimento"], d["data_rilascio"]
        ),
        "Dati SAP registrati.",
    )


@editor_required
@require_POST
def rda_collega_pratica(request, pk):
    rda = _rda(pk)
    _modificabile(request, rda)
    form = forms.CollegaPraticaForm(request.POST, rda=rda, utente=request.user)
    if not form.is_valid():
        messages.error(request, "; ".join(form.non_field_errors()) or "Scelta non valida.")
        return redirect("contratti:rda", pk=pk)
    d = form.cleaned_data
    return _azione(
        request,
        pk,
        lambda r: acquisti.collega_pratica(r, contratto=d["contratto"], fabbisogno=d["fabbisogno"]),
        "Pratica della RDA aggiornata.",
    )


@editor_required
@require_POST
def rda_collega_contratto(request, pk):
    rda = _rda(pk)
    _modificabile(request, rda)
    form = forms.CollegaContrattoForm(request.POST, rda=rda)
    if not form.is_valid():
        messages.error(request, "Scegli un contratto del cluster senza RDA d'origine.")
        return redirect("contratti:rda", pk=pk)
    contratto = form.cleaned_data["contratto"]
    permessi.verifica_oggetto(request.user, contratto)
    return _azione(
        request,
        pk,
        lambda r: acquisti.collega_contratto(r, contratto),
        f"{contratto} collegato a questa RDA.",
    )


@editor_required
@require_POST
def contratto_collega_rda(request, pk):
    """Dal contratto: collega la RDA d'origine (scelta o proposta per n. RDA)."""
    contratto = get_object_or_404(m.Contratto.objects.select_related("fabbisogno"), pk=pk)
    permessi.verifica_oggetto(request.user, contratto)
    form = forms.CollegaRdaForm(request.POST, contratto=contratto)
    if not form.is_valid():
        messages.error(request, "Scegli una RDA dello stesso cluster.")
    else:
        try:
            acquisti.collega_contratto(form.cleaned_data["rda"], contratto)
        except acquisti.OperazioneNonAmmessa as exc:
            _errore(request, exc)
        else:
            messages.success(request, f"RDA d'origine: {form.cleaned_data['rda']}.")
    return redirect("contratti:contratto", pk=pk)


@editor_required
@require_POST
def contratto_scollega_rda(request, pk):
    contratto = get_object_or_404(m.Contratto.objects.select_related("fabbisogno", "rda"), pk=pk)
    permessi.verifica_oggetto(request.user, contratto)
    rda = contratto.rda
    try:
        acquisti.scollega_contratto(contratto)
    except acquisti.OperazioneNonAmmessa as exc:
        _errore(request, exc)
    else:
        messages.success(request, f"Contratto scollegato dalla RDA {rda}.")
    if request.POST.get("ritorno") == "rda" and rda is not None:
        return redirect("contratti:rda", pk=rda.pk)
    return redirect("contratti:contratto", pk=pk)


# --- Contratto registrato dalla RDA ----------------------------------------------------------


@editor_required
def rda_contratto(request, pk):
    """Il contratto emesso dal Procurement, precompilato dalla RDA (rinnovo o una tantum)."""
    rda = _rda(pk)
    _modificabile(request, rda)
    if acquisti.fase(rda) == Fase.ANNULLATA:
        messages.error(request, "La RDA è annullata.")
        return redirect("contratti:rda", pk=pk)
    iniziali = acquisti.iniziali_contratto(rda, oggi_richiesta(request))
    form = forms.ContrattoDaRdaForm(
        request.POST or None, initial=iniziali, rda=rda, utente=request.user
    )
    voci_iniziali = [
        {
            "posizione": p.numero,
            "descrizione": p.descrizione_breve,
            "importo_fisso": p.importo - p.di_cui_variabile,
            "massimale_variabile": p.di_cui_variabile,
        }
        for p in rda.posizioni.all()
    ]
    formset = forms.VociDaRdaFormSet(request.POST or None, initial=voci_iniziali, prefix="voci")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        voci = [
            {
                "posizione": d.get("posizione"),
                "descrizione": d["descrizione"],
                "importo_fisso": d["importo_fisso"],
                "massimale_variabile": d.get("massimale_variabile") or 0,
            }
            for d in formset.cleaned_data
            if d
        ]
        try:
            contratto = acquisti.registra_contratto_da_rda(
                rda,
                form.dati_contratto(),
                voci,
                modalita=form.cleaned_data["modalita"],
                periodicita=form.cleaned_data.get("periodicita") or "",
                fabbisogno=form.cleaned_data.get("fabbisogno"),
            )
        except (acquisti.OperazioneNonAmmessa, ValidationError) as exc:
            _errore(request, exc)
        else:
            differenza = acquisti.differenza_da_rda(contratto)
            messages.success(request, "Contratto registrato dalla RDA.")
            if differenza:
                messages.info(
                    request,
                    f"Il massimo del contratto differisce dalla RDA di "
                    f"{motore.formato_euro(differenza)}: la RDA resta com'è.",
                )
            return redirect("contratti:contratto", pk=contratto.pk)
    return render(
        request,
        "contratti/rda_contratto.html",
        {
            "rda": rda,
            "form": form,
            "formset": formset,
            "importo_rda": acquisti.importo_rda(rda),
            "predecessore": acquisti.contratto_in_scadenza_libero(rda),
        },
    )


# --- Per le pagine di fabbisogno e contratto ------------------------------------------------


def richieste_del_fabbisogno(f: m.Fabbisogno, oggi) -> list[dict]:
    """RDA del fabbisogno: legate al fabbisogno, ai suoi contratti in scadenza o generati."""
    qs = (
        _qs_rda()
        .filter(
            Q(fabbisogno=f)
            | Q(contratto_in_scadenza__fabbisogno=f)
            | Q(contratti_generati__fabbisogno=f)
        )
        .filter(archiviato=False)
        .distinct()
        .order_by("-data_creazione", "-pk")
    )
    return [riga(r, oggi) for r in qs]


def contesto_pratica(oggetto, oggi) -> dict:
    """Stato corrente della pratica (passaggi o RDA) e le RDA che la muovono (SPEC §5.7)."""
    ultimo = acquisti.ultimo_passaggio(oggetto)
    corrente = acquisti.stato_pratica_con_data(oggetto, oggi)
    rda = [riga(r, oggi) for r in acquisti.rda_della_pratica(oggetto)]
    return {
        "pratica_corrente": m.StatoPratica.Stato(corrente[0]).label if corrente else None,
        "pratica_data": corrente[1] if corrente else None,
        "pratica_da_rda": corrente is not None and corrente != ultimo,
        "pratica_rda": rda,
    }
