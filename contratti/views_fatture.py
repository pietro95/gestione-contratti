"""Fatture (F11.3, SPEC Rev14–Rev15): elenchi, presa in carico singola e multipla,
lavorazione della fattura, esecuzione del contratto.

Lettura per tutti i ruoli; le modifiche sono di Admin ed Editor (``editor_required``), con i
controlli di ``contratti.fatture`` (cluster del contratto, chi ha in carico la fattura,
Admin e addetto): il Reader riceve 403.
"""

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import editor_required
from contratti import acquisti, fatture, permessi
from contratti import forms_fatture as forms
from contratti import models as m
from contratti.engine import acquisti as motore
from contratti.views import PER_PAGINA, filtri_attivi, oggi_richiesta, storico

Passo = motore.PassoFattura
VISTE = {
    "da_prendere": "Da prendere in carico",
    "mie": "Le mie fatture",
    "tutte": "Tutte le fatture",
}


def _errore(request, exc) -> None:
    messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))


def _fattura(pk) -> m.Fattura:
    return get_object_or_404(fatture.QS_FATTURE, pk=pk)


def _riga(f: m.Fattura, oggi, contratto_proposto=None, referente_proposto=None) -> dict:
    passo = fatture.passo_fattura(f, oggi)
    return {
        "f": f,
        "passo": passo,
        "passo_label": motore.ETICHETTE_PASSO[passo] if passo else "Trasferita",
        "giorni": (oggi - f.data_registrazione).days,
        "ferma": not f.fuori_registro and fatture.ferma(f, oggi),
        "contratto_proposto": contratto_proposto,
        "referente_proposto": referente_proposto,
        "anomalie": fatture.anomalie(f),
    }


def conteggio_da_prendere() -> int:
    return m.Fattura.objects.filter(
        referente__isnull=True, fuori_registro=False, archiviato=False
    ).count()


# --- Elenchi ------------------------------------------------------------------------------


@login_required
def fatture_elenco(request):
    oggi = oggi_richiesta(request)
    g = request.GET
    from reports.acquisti import elenco_fatture

    proposte = {"1": True, "0": False}.get(g.get("proposte"))
    elenco = elenco_fatture(
        request.user,
        oggi,
        g.get("vista") or "da_prendere",
        testo=g.get("q", ""),
        passo=g.get("passo", ""),
        proposte=proposte,
        fuori_registro=bool(g.get("fuori_registro")),
        archiviate=bool(g.get("archiviate")),
    )
    vista, righe = elenco.vista, elenco.righe
    proposte_a_me, solo_proposte = elenco.proposte_a_me, elenco.solo_proposte
    pagina = Paginator(righe, PER_PAGINA).get_page(g.get("pagina"))
    return render(
        request,
        "contratti/fatture_elenco.html",
        {
            "pagina": pagina,
            "totale": len(righe),
            "vista": vista,
            "viste": VISTE,
            "titolo_vista": VISTE[vista],
            "filtri": g,
            "oggi": oggi,
            "solo_proposte": solo_proposte,
            "proposte_a_me": proposte_a_me,
            "passi": [*motore.ETICHETTE_PASSO.items(), ("trasferita", "Trasferita")],
            "attivi": filtri_attivi(
                g,
                {
                    "q": "Testo",
                    "passo": lambda v: "Passo: "
                    + dict(motore.ETICHETTE_PASSO).get(v, "Trasferita"),
                    "fuori_registro": lambda v: "Con le fuori registro",
                    "archiviate": lambda v: "Con le archiviate",
                },
            ),
            "scrive": fatture.scrive(request.user),
            "gestisce": fatture.gestisce(request.user),
            "da_prendere": conteggio_da_prendere(),
        },
    )


@editor_required
@require_POST
def fatture_azione(request):
    """Azioni sulle fatture selezionate: prendi in carico, fuori registro, assegna ai
    referenti proposti."""
    azione = request.POST.get("azione")
    pks = [int(v) for v in request.POST.getlist("fattura") if v.isdigit()]
    ritorno = request.POST.get("ritorno") or "da_prendere"
    if not pks:
        messages.warning(request, "Nessuna fattura selezionata.")
        return redirect(f"{_url_elenco()}?vista={ritorno}")
    try:
        if azione == "prendi":
            esito = fatture.prendi_in_carico(pks, request.user)
            fatto = ("presa in carico", "prese in carico")
        elif azione == "fuori_registro":
            esito = fatture.segna_fuori_registro(pks, request.user)
            fatto = ("segnata fuori registro", "segnate fuori registro")
        elif azione == "assegna_proposti":
            if not fatture.gestisce(request.user):
                raise PermissionDenied
            esito = fatture.assegna_ai_proposti(pks, request.user)
            fatto = ("assegnata al referente proposto", "assegnate ai referenti proposti")
        else:
            messages.error(request, "Azione non prevista.")
            return redirect(f"{_url_elenco()}?vista={ritorno}")
    except acquisti.OperazioneNonAmmessa as exc:
        _errore(request, exc)
        return redirect(f"{_url_elenco()}?vista={ritorno}")
    if esito.fatte:
        n = len(esito.fatte)
        messages.success(
            request, f"1 fattura {fatto[0]}." if n == 1 else f"{n} fatture {fatto[1]}."
        )
    for f, motivo in esito.rifiutate:
        messages.warning(request, f"Fattura {f.numero}: {motivo}.")
    return redirect(f"{_url_elenco()}?vista={ritorno}")


def _url_elenco():
    from django.urls import reverse

    return reverse("contratti:fatture")


@editor_required
def fattura_nuova(request, contratto_pk=None):
    contratto = None
    if contratto_pk is not None:
        contratto = get_object_or_404(m.Contratto, pk=contratto_pk)
        permessi.verifica_oggetto(request.user, contratto)
    form = forms.FatturaForm(request.POST or None, contratto=contratto)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            fattura = fatture.registra(
                numero=d["numero"],
                data=d["data"],
                importo_documento=d["importo_documento"],
                fornitore=d.get("fornitore"),
                contratto=contratto,
                note=d.get("note", ""),
            )
        except (acquisti.OperazioneNonAmmessa, ValidationError) as exc:
            _errore(request, exc)
        else:
            messages.success(request, "Fattura registrata.")
            return redirect("contratti:fattura", pk=fattura.pk)
    return render(
        request,
        "contratti/form.html",
        {
            "form": form,
            "titolo": "Registra una fattura",
            "nota": (
                f"Contratto {contratto}" if contratto else
                "Di norma le fatture arrivano dall'import settimanale (Gestione → Import)."
            ),
            "annulla": contratto,
            "avanti": "Registra",
        },
    )  # fmt: skip


# --- Dettaglio e lavorazione -------------------------------------------------------------


@login_required
def fattura_dettaglio(request, pk):
    oggi = oggi_richiesta(request)
    f = _fattura(pk)
    proposto = fatture.contratto_proposto(f)
    referente = fatture.referente_proposto(f)
    r = _riga(f, oggi, proposto, referente)
    puo_lavorare = fatture.puo_lavorare(request.user, f)
    documenti = list(f.documenti.all())
    iniziali_importi = {
        "valore_base": f.valore_base,
        "oneri": f.oneri,
        "bollo": f.bollo,
        "iva": f.iva,
        "voce": f.voce_id,
        "rata": f.rata_id,
    }
    if f.valore_base is None:
        iniziali_importi["valore_base"] = motore.valore_base_proposto(
            f.importo_documento, f.oneri, f.bollo
        )
    return render(
        request,
        "contratti/fattura_dettaglio.html",
        {
            "r": r,
            "f": f,
            "oggi": oggi,
            "documenti": documenti,
            "proposto": proposto,
            "referente_proposto": referente,
            "puo_lavorare": puo_lavorare,
            "puo_convalidare": fatture.puo_convalidare(request.user, f),
            "scrive": fatture.scrive(request.user),
            "gestisce": fatture.gestisce(request.user),
            "documento_proposto": fatture.documento_proposto(f),
            "indicazioni": fatture.indicazioni_validazione(f),
            "commento_pac": fatture.commento_pac(f),
            "form_contratto": forms.ContrattoFatturaForm(
                fattura=f,
                initial={
                    "contratto": f.contratto_id or getattr(proposto, "pk", None),
                    "voce": f.voce_id,
                },
            ),  # fmt: skip
            "form_convalida": forms.ConvalidaForm(instance=f),
            "form_importi": forms.ImportiForm(fattura=f, initial=iniziali_importi),
            "aliquote_iva": fatture.aliquote_iva(),
            "form_documento": forms.DocumentoFatturaForm(
                initial={
                    "tipo": (
                        m.DocumentoEsecuzione.Tipo.ODA
                        if r["passo"]
                        in (
                            None,
                            Passo.RDC,
                            Passo.CONVALIDA,
                            Passo.ASSEGNAZIONE,
                            Passo.PRESA_IN_CARICO,
                        )
                        else fatture.documento_proposto(f)
                    ),
                    "data": oggi,
                }
            ),  # fmt: skip
            "form_trasferimento": forms.TrasferimentoForm(initial={"data": oggi}),
            "form_riassegna": forms.RiassegnaForm(),
            "storico": storico(f),
            "Passo": Passo,
        },
    )


def _azione(request, pk, esegui, successo: str, *, controllo=None):
    f = _fattura(pk)
    if not (controllo or fatture.puo_lavorare)(request.user, f):
        raise PermissionDenied("Non puoi modificare questa fattura.")
    try:
        esegui(f)
    except (acquisti.OperazioneNonAmmessa, ValidationError) as exc:
        _errore(request, exc)
    else:
        messages.success(request, successo)
    return redirect("contratti:fattura", pk=pk)


@editor_required
@require_POST
def fattura_prendi(request, pk):
    _fattura(pk)
    esito = fatture.prendi_in_carico([pk], request.user)
    if esito.fatte:
        messages.success(request, "Fattura presa in carico.")
    for _f, motivo in esito.rifiutate:
        messages.warning(request, f"Non presa in carico: {motivo}.")
    return redirect("contratti:fattura", pk=pk)


@editor_required
@require_POST
def fattura_lascia(request, pk):
    return _azione(
        request, pk, lambda f: fatture.lascia(f, request.user),
        "Fattura lasciata: è di nuovo tra quelle da prendere in carico.",
        controllo=lambda u, f: f.referente_id == u.pk or fatture.gestisce(u),
    )  # fmt: skip


@editor_required
@require_POST
def fattura_riassegna(request, pk):
    form = forms.RiassegnaForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Scegli a chi assegnarla.")
        return redirect("contratti:fattura", pk=pk)
    nuovo = form.cleaned_data["utente"]
    return _azione(
        request, pk, lambda f: fatture.riassegna(f, nuovo, request.user),
        f"Fattura assegnata a {nuovo}.",
        controllo=lambda u, f: fatture.gestisce(u),
    )  # fmt: skip


@editor_required
@require_POST
def fattura_contratto(request, pk):
    f = _fattura(pk)
    if request.POST.get("scollega"):
        return _azione(
            request, pk, lambda x: fatture.assegna_contratto(x, None), "Contratto tolto."
        )
    form = forms.ContrattoFatturaForm(request.POST, fattura=f)
    if not form.is_valid():
        messages.error(request, "Contratto non valido: " + "; ".join(
            f"{k}: {' '.join(v)}" for k, v in form.errors.items()
        ))  # fmt: skip
        return redirect("contratti:fattura", pk=pk)
    contratto, voce = form.cleaned_data["contratto"], form.cleaned_data["voce"]
    # Serve poter modificare anche nel cluster del contratto scelto.
    permessi.verifica_oggetto(request.user, contratto)
    return _azione(
        request, pk, lambda x: fatture.assegna_contratto(x, contratto, voce),
        f"Fattura assegnata al contratto {contratto}.",
    )  # fmt: skip


@editor_required
@require_POST
def fattura_convalida(request, pk):
    f = _fattura(pk)
    form = forms.ConvalidaForm(request.POST, instance=m.Fattura.objects.get(pk=pk))
    if not form.is_valid():
        messages.error(request, "Convalida non valida: " + "; ".join(
            f"{k}: {' '.join(v)}" for k, v in form.errors.items()
        ))  # fmt: skip
        return redirect("contratti:fattura", pk=pk)
    d = form.cleaned_data
    del f
    return _azione(
        request, pk,
        lambda x: fatture.convalida(
            x, d["esito_convalida"], d["nota_convalida"], d["bloccata_fino_al"]
        ),
        "Convalida registrata.",
        controllo=fatture.puo_convalidare,
    )  # fmt: skip


@editor_required
@require_POST
def fattura_importi(request, pk):
    f = _fattura(pk)
    form = forms.ImportiForm(request.POST, fattura=f)
    if not form.is_valid():
        messages.error(request, "Importi non validi: " + "; ".join(
            f"{k}: {' '.join(v)}" for k, v in form.errors.items()
        ))  # fmt: skip
        return redirect("contratti:fattura", pk=pk)
    d = form.cleaned_data
    if scorporo := request.POST.get("scorporo"):
        try:
            aliquota = Decimal(scorporo)
        except InvalidOperation:
            messages.error(request, "Aliquota IVA non valida.")
            return redirect("contratti:fattura", pk=pk)
        return _azione(
            request, pk,
            lambda x: fatture.scorpora_iva(
                x, aliquota, d["oneri"], d["bollo"], d.get("voce"), d.get("rata")
            ),
            f"IVA {aliquota.normalize():f}% scorporata: valore base e IVA registrati.",
        )  # fmt: skip
    return _azione(
        request, pk,
        lambda x: fatture.aggiorna_importi(
            x, d["valore_base"], d["oneri"], d["bollo"], d.get("voce"), d.get("rata"),
            iva=d.get("iva"),
        ),
        "Importi registrati.",
    )  # fmt: skip


@editor_required
@require_POST
def fattura_documento(request, pk):
    form = forms.DocumentoFatturaForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Documento non valido: " + "; ".join(
            f"{k}: {' '.join(v)}" for k, v in form.errors.items()
        ))  # fmt: skip
        return redirect("contratti:fattura", pk=pk)
    d = form.cleaned_data
    return _azione(
        request, pk,
        lambda x: fatture.registra_documento(x, d["tipo"], d["numero"], d["data"]),
        "Documento registrato.",
    )  # fmt: skip


@editor_required
@require_POST
def fattura_trasferisci(request, pk):
    if request.POST.get("annulla"):
        return _azione(request, pk, fatture.annulla_trasferimento, "Trasferimento annullato.")
    form = forms.TrasferimentoForm(request.POST)
    data = form.cleaned_data["data"] if form.is_valid() else timezone.localdate()
    return _azione(
        request, pk, lambda x: fatture.trasferisci(x, request.user, data),
        "Fattura trasferita per il pagamento.",
    )  # fmt: skip


@editor_required
@require_POST
def fattura_fuori_registro(request, pk):
    valore = request.POST.get("valore") != "0"
    f = _fattura(pk)
    esito = fatture.segna_fuori_registro([f.pk], request.user, valore)
    for _x, motivo in esito.rifiutate:
        raise PermissionDenied(motivo)
    messages.success(
        request, "Fattura segnata fuori registro." if valore else "Fattura di nuovo nel registro."
    )
    return redirect("contratti:fattura", pk=pk)


# --- Esecuzione del contratto ---------------------------------------------------------------


def contesto_esecuzione(contratto: m.Contratto, oggi) -> dict:
    """Dati della scheda «Esecuzione» del contratto (SPEC §5.8)."""
    lista = list(
        fatture.QS_FATTURE.filter(contratto=contratto, archiviato=False).order_by("data", "pk")
    )
    riepilogo = acquisti.riepilogo_esecuzione(contratto, oggi)
    return {
        "esecuzione": riepilogo,
        "motivo_chiusura": (
            motore.ETICHETTE_MOTIVO[riepilogo.motivo_da_chiudere]
            if riepilogo.motivo_da_chiudere else None
        ),
        "fatture": [_riga(f, oggi) for f in lista],
        "documenti_esecuzione": list(
            contratto.documenti_esecuzione.filter(archiviato=False)
            .select_related("fattura", "voce")
            .order_by("data", "pk")
        ),
        "form_documento_esecuzione": forms.DocumentoEsecuzioneForm(
            contratto=contratto, initial={"data": oggi}
        ),
    }  # fmt: skip


@editor_required
@require_POST
def contratto_documento(request, pk):
    contratto = get_object_or_404(m.Contratto, pk=pk)
    permessi.verifica_oggetto(request.user, contratto)
    if contratto.data_chiusura is not None:
        messages.error(request, "Il contratto è chiuso: prima si annulla la chiusura.")
        return redirect("contratti:contratto", pk=pk)
    form = forms.DocumentoEsecuzioneForm(request.POST, contratto=contratto)
    if form.is_valid():
        doc = form.save(commit=False)
        doc.contratto = contratto
        doc._change_reason = "Registrato dal contratto"
        doc.save()
        messages.success(request, f"{doc} registrato.")
    else:
        messages.error(request, "Documento non valido: " + "; ".join(
            f"{k}: {' '.join(v)}" for k, v in form.errors.items()
        ))  # fmt: skip
    return redirect(f"/contratti/{pk}/#esecuzione")


@editor_required
@require_POST
def contratto_chiudi(request, pk):
    contratto = get_object_or_404(m.Contratto, pk=pk)
    permessi.verifica_oggetto(request.user, contratto)
    try:
        if request.POST.get("annulla"):
            acquisti.annulla_chiusura(contratto)
            messages.success(request, "Chiusura annullata.")
        else:
            acquisti.chiudi(contratto, request.user)
            messages.success(request, "Contratto chiuso.")
    except acquisti.OperazioneNonAmmessa as exc:
        _errore(request, exc)
    return redirect("contratti:contratto", pk=pk)
