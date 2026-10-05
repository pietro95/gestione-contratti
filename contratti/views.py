"""Interfaccia operativa (F4). Lettura per tutti i ruoli; modifiche solo Editor e Admin.

Ogni vista che modifica dati è protetta da ``editor_required``: il Reader riceve 403.
"""

import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.permissions import editor_required
from accounts.roles import ADMIN, role_of
from contratti import adapters, forms, permessi, selettori, servizi
from contratti import models as m
from contratti.engine.budget import valore
from contratti.engine.scadenzario import genera_rate
from contratti.engine.tipi import Alert, Livello, Quota
from contratti.importer import proposte as proposte_import

PER_PAGINA = 50


def oggi_richiesta(request) -> datetime.date:
    """Data di oggi; solo l'Admin può simulare un'altra data con ``?oggi=AAAA-MM-GG``."""
    valore_oggi = request.GET.get("oggi")
    if valore_oggi and role_of(request.user) == ADMIN:
        try:
            return datetime.date.fromisoformat(valore_oggi)
        except ValueError:
            pass
    return datetime.date.today()


def storico(oggetto) -> list[dict]:
    """Modifiche registrate da simple-history: chi, quando, campo, prima e dopo."""
    voci = []
    record = list(oggetto.history.select_related("history_user").order_by("history_date"))
    precedente = None
    for h in record:
        modifiche = []
        if precedente is not None:
            delta = h.diff_against(precedente)
            for change in delta.changes:
                campo = oggetto._meta.get_field(change.field)
                modifiche.append((campo.verbose_name, change.old, change.new))
        voci.append(
            {
                "data": h.history_date,
                "utente": h.history_user,
                "tipo": {"+": "Creazione", "~": "Modifica", "-": "Cancellazione"}[h.history_type],
                "modifiche": modifiche,
                "motivo": h.history_change_reason or "",
            }
        )
        precedente = h
    return list(reversed(voci))


# --- Cluster visibili -----------------------------------------------------------------


def _cluster_richiesti(request) -> list[str]:
    """Codici dei cluster da mostrare: di default i propri (F9.2), «tutti» a richiesta."""
    return permessi.codici_filtro(request.user, request.GET.getlist("area"))


def _contesto_cluster(request) -> dict:
    return {
        "aree": permessi.scelte_filtro(request.user),
        "area_scelte": permessi.selezione_filtro(request.user, request.GET.getlist("area")),
    }


def _etichetta_cluster(valore: str) -> str:
    if valore == permessi.TUTTI:
        return "Tutti i cluster"
    if valore == permessi.MIEI:
        return "I miei cluster"
    return f"Cluster: {valore}"


# --- Cruscotto -------------------------------------------------------------------------


@login_required
def home(request):
    """Pagina iniziale: numeri chiave, cose da fare, prossime scadenze, budget dell'anno."""
    from reports.budget import ETICHETTE_VISTE, NATURE, VISTE, Filtri, calcola_budget

    oggi = oggi_richiesta(request)
    codici = permessi.codici_filtro(request.user, [])
    gruppi = selettori.cruscotto(oggi, {"area": codici})
    contratti = selettori.contratti_base().filter(archiviato=False)
    if codici:
        contratti = contratti.filter(fabbisogno__cluster__codice__in=codici)
    righe = selettori.righe_contratti(contratti, oggi)
    entro = oggi + datetime.timedelta(days=90)
    prossime = sorted(
        (r for r in righe if r.stato == "attivo" and r.fine and oggi <= r.fine <= entro),
        key=lambda r: r.fine,
    )
    priorita = {Alert.ROSSO: 0, Alert.ARANCIONE: 1, Alert.GIALLO: 2}
    da_fare = sorted(
        (r for colore in priorita for r in gruppi[colore]),
        key=lambda r: (priorita[r.alert], r.data_limite or datetime.date.max),
    )
    budget = None
    try:
        # OPEX e CAPEX affiancati, mai sommati.
        per_natura = {
            s.filtri.natura: s.totali()["totale"]
            for s in calcola_budget(Filtri(anno=oggi.year, area=tuple(codici)), oggi).sezioni()
        }
        budget = {
            "nature": NATURE,
            "righe": [
                (ETICHETTE_VISTE[v], [per_natura[n][v][Livello.PROBABILE] for n in NATURE])
                for v in VISTE
            ],
        }
    except adapters.ParametroMancante:
        pass
    return render(
        request,
        "home.html",
        {
            "oggi": oggi,
            "conteggi": {colore.value: len(gruppi[colore]) for colore in priorita},
            "attivi": sum(1 for r in righe if r.stato == "attivo"),
            "da_fare": da_fare[:8],
            "da_fare_totale": len(da_fare),
            "prossime": prossime[:8],
            "prossime_totale": len(prossime),
            "budget": budget,
            "cluster_propri": permessi.cluster_propri(request.user),
        },
    )


@login_required
def cerca(request):
    """Ricerca globale su contratti, fabbisogni e fornitori (barra superiore)."""
    q = request.GET.get("q", "").strip()
    risultati = {"contratti": [], "fabbisogni": [], "fornitori": []}
    if len(q) >= 2:
        oggi = oggi_richiesta(request)
        contratti = selettori.contratti_base().filter(
            Q(descrizione__icontains=q)
            | Q(fabbisogno__descrizione__icontains=q)
            | Q(numero_contratto__icontains=q)
            | Q(cig__icontains=q)
            | Q(numero_rda__icontains=q)
            | Q(fornitore__ragione_sociale__icontains=q)
        )
        risultati["contratti"] = selettori.righe_contratti(
            contratti.order_by("archiviato", "-data_inizio")[:25], oggi
        )
        risultati["fabbisogni"] = list(
            m.Fabbisogno.objects.filter(Q(descrizione__icontains=q) | Q(referente__icontains=q))
            .select_related("categoria")
            .order_by("archiviato", "descrizione")[:15]
        )
        risultati["fornitori"] = list(
            m.Fornitore.objects.filter(
                Q(ragione_sociale__icontains=q)
                | Q(partita_iva__icontains=q)
                | Q(codice_sap__icontains=q)
            ).order_by("archiviato", "ragione_sociale")[:15]
        )
    return render(
        request,
        "contratti/cerca.html",
        {"q": q, "risultati": risultati, "trovati": sum(len(v) for v in risultati.values())},
    )


@login_required
def cruscotto(request):
    oggi = oggi_richiesta(request)
    filtri = {"area": _cluster_richiesti(request), "categoria": request.GET.get("categoria", "")}
    gruppi = selettori.cruscotto(oggi, filtri)
    return render(
        request,
        "contratti/cruscotto.html",
        {
            "oggi": oggi,
            "gruppi": [
                (Alert.ROSSO, "Scaduti senza rinnovo", gruppi[Alert.ROSSO]),
                (
                    Alert.ARANCIONE,
                    "Data limite superata, pratica non avviata",
                    gruppi[Alert.ARANCIONE],
                ),
                (Alert.GIALLO, "In avvicinamento o pratica in corso", gruppi[Alert.GIALLO]),
            ],
            "filtri": filtri,
            **_contesto_cluster(request),
            "categorie": m.Categoria.objects.all(),
            "proposte_aperte": m.PropostaRaggruppamento.objects.filter(stato="proposta").count()
            + m.PropostaPredecessore.objects.filter(stato="proposta").count(),
        },
    )


# --- Contratti -------------------------------------------------------------------------


def _filtra_contratti(request, oggi):
    g = request.GET
    qs = selettori.contratti_base()
    if not g.get("archiviati"):
        qs = qs.filter(archiviato=False)
    if q := g.get("q", "").strip():
        qs = qs.filter(
            Q(descrizione__icontains=q)
            | Q(fabbisogno__descrizione__icontains=q)
            | Q(numero_contratto__icontains=q)
            | Q(cig__icontains=q)
            | Q(numero_rda__icontains=q)
            | Q(fornitore__ragione_sociale__icontains=q)
        )
    if codici := _cluster_richiesti(request):
        qs = qs.filter(fabbisogno__cluster__codice__in=codici)
    # Finanziato: almeno una voce su WBS a progetto (F9.2).
    su_progetto = Q(voci__archiviato=False, voci__wbs__tipo=m.WBS.Tipo.PROGETTO)
    if g.get("finanziamento") == m.Contratto.Finanziamento.FINANZIATO:
        qs = qs.filter(su_progetto).distinct()
    elif g.get("finanziamento") == m.Contratto.Finanziamento.ORDINARIO:
        qs = qs.exclude(su_progetto)
    if g.get("fornitore"):
        qs = qs.filter(fornitore_id=g["fornitore"])
    righe = selettori.righe_contratti(qs.order_by("-data_inizio", "pk"), oggi)
    if g.get("stato"):
        righe = [r for r in righe if r.stato == g["stato"]]
    if g.get("alert"):
        righe = [r for r in righe if r.alert and r.alert.value == g["alert"]]
    if anno := g.get("anno", "").strip():
        try:
            anno = int(anno)
        except ValueError:
            anno = None
        if anno:
            inizio, fine = datetime.date(anno, 1, 1), datetime.date(anno, 12, 31)
            righe = [
                r
                for r in righe
                if r.contratto.data_inizio and r.contratto.data_inizio <= fine and r.fine >= inizio
            ]
    return righe


ORDINAMENTI_CONTRATTI = {
    "fabbisogno": lambda r: r.contratto.fabbisogno.descrizione.lower(),
    "fornitore": lambda r: r.contratto.fornitore.ragione_sociale.lower(),
    "inizio": lambda r: r.contratto.data_inizio or datetime.date.min,
    "fine": lambda r: r.fine or datetime.date.min,
    "alert": lambda r: (selettori.ORDINE_ALERT[r.alert], r.data_limite or datetime.date.max),
}
STATI_TEMPORALI = [
    ("attivo", "Attivo"),
    ("futuro", "Futuro"),
    ("scaduto", "Scaduto"),
    ("senza_data", "Senza data"),
]


def ordina_righe(righe, ordina: str, criteri: dict):
    campo = ordina.lstrip("-")
    if campo not in criteri:
        return righe
    return sorted(righe, key=criteri[campo], reverse=ordina.startswith("-"))


def filtri_attivi(g, etichette: dict) -> list[tuple[str, str]]:
    """(parametro, testo) dei filtri valorizzati, per le etichette rimovibili."""
    attivi = []
    for chiave, descrivi in etichette.items():
        valore = g.get(chiave, "").strip()
        if valore:
            testo = descrivi(valore) if callable(descrivi) else f"{descrivi}: {valore}"
            if testo:
                attivi.append((chiave, testo))
    return attivi


def _ordine_qs(ordina: str, campi: dict, default: tuple) -> tuple:
    campo = campi.get(ordina.lstrip("-"))
    if not campo:
        return default
    return (f"-{campo}" if ordina.startswith("-") else campo, "pk")


def _nome(modello, pk):
    try:
        return str(modello.objects.get(pk=int(pk)))
    except (ValueError, modello.DoesNotExist):
        return None


@login_required
def contratti_elenco(request):
    oggi = oggi_richiesta(request)
    g = request.GET
    righe = ordina_righe(
        _filtra_contratti(request, oggi), g.get("ordina", ""), ORDINAMENTI_CONTRATTI
    )
    pagina = Paginator(righe, PER_PAGINA).get_page(g.get("pagina"))
    contesto = {
        "pagina": pagina,
        "totale": len(righe),
        "attivi": filtri_attivi(
            g,
            {
                "q": "Testo",
                "area": _etichetta_cluster,
                "stato": lambda v: "Stato: " + dict(STATI_TEMPORALI).get(v, v),
                "alert": lambda v: "Alert: " + v,
                "anno": "Attivi nell'anno",
                "fornitore": lambda v: (_nome(m.Fornitore, v) or v),
                "finanziamento": lambda v: m.Contratto.Finanziamento(v).label
                if v in m.Contratto.Finanziamento.values
                else v,
                "archiviati": lambda v: "Con gli archiviati",
            },
        ),
        "filtri": request.GET,
        **_contesto_cluster(request),
        "fornitori": m.Fornitore.objects.filter(archiviato=False),
        "stati": STATI_TEMPORALI,
        "alert": [(a.value, a.value.capitalize()) for a in Alert],
        "finanziamenti": m.Contratto.Finanziamento.choices,
    }
    template = (
        "contratti/_contratti_tabella.html" if request.headers.get("HX-Request") else
        "contratti/contratti_elenco.html"
    )  # fmt: skip
    return render(request, template, contesto)


def _catena(contratto) -> list:
    """Contratti della catena dei rinnovi, dal più vecchio al più recente."""
    prima, c, visti = [], contratto.predecessore, {contratto.pk}
    while c is not None and c.pk not in visti and len(prima) < 20:
        prima.insert(0, c)
        visti.add(c.pk)
        c = c.predecessore
    dopo, c = [], m.Contratto.objects.filter(predecessore=contratto).first()
    while c is not None and c.pk not in visti and len(dopo) < 20:
        dopo.append(c)
        visti.add(c.pk)
        c = m.Contratto.objects.filter(predecessore=c).first()
    return [*prima, contratto, *dopo]


def _previsti_dopo(contratto, oggi):
    """Rinnovi previsti, se questo è il contratto da cui partono."""
    base = adapters.contratto_base_previsti(contratto.fabbisogno)
    if base is None or base.pk != contratto.pk:
        return []
    return adapters.previsti_fabbisogno(contratto.fabbisogno, adapters.orizzonte_default(oggi))


def _contratto(pk):
    return get_object_or_404(selettori.contratti_base(), pk=pk)


@login_required
def contratto_dettaglio(request, pk):
    oggi = oggi_richiesta(request)
    contratto = _contratto(pk)
    riga = selettori.riga_contratto(contratto, oggi, selettori.finestra_alert(oggi))
    s = adapters.scadenza(contratto)
    voci = (
        contratto.voci.filter(archiviato=False)
        .select_related(
            "conto", "proroga", "piano_fatturazione", "wbs", "conto_rinnovi", "wbs_rinnovi"
        )
        .prefetch_related("quote", "piano_fatturazione__rate")
    )
    voci_engine, esiti = adapters.voci_contratto(contratto)
    valori = {v.riferimento: {liv: valore(v, liv) for liv in Livello} for v in voci_engine}
    successore = m.Contratto.objects.filter(predecessore=contratto).first()
    rinnovi_scollegati = (
        servizi.candidati_rinnovo(contratto)
        if successore is None and not contratto.archiviato
        else []
    )
    confluiti = list(contratto.confluiti.select_related("fornitore").order_by("data_inizio"))
    return render(
        request,
        "contratti/contratto_dettaglio.html",
        {
            "c": contratto,
            "riga": riga,
            "fine_contrattuale": adapters.scadenze.data_fine_contrattuale(s) if s else None,
            "disdetta": adapters.scadenze.data_ultima_disdetta(s) if s else None,
            "voci": [(v, valori.get(v.pk)) for v in voci],
            "totali": {
                liv: sum((x[liv] for x in valori.values()), Decimal("0.00")) for liv in Livello
            },
            "esiti": esiti,
            "successore": successore or contratto.confluito_in,
            "rinnovi_scollegati": rinnovi_scollegati,
            "confluiti": confluiti,
            "sostituito_da_spesa": adapters.sostituito_da_spesa(contratto, riga.fine),
            "puo_confluire": bool(servizi.candidati_confluenza(contratto))
            and not contratto.archiviato,
            "pratica": contratto.stati_pratica.select_related("utente").order_by("-data", "-id"),
            "form_pratica": forms.PassaggioPraticaForm(initial={"data": oggi}),
            "storico": storico(contratto),
            "catena": _catena(contratto),
            "previsti": _previsti_dopo(contratto, oggi),
            "puo_modificare": permessi.puo_modificare(
                request.user, contratto.fabbisogno.cluster_id
            ),
        },
    )


# Procedura guidata del nuovo contratto: dati del contratto, voci con il piano di
# fatturazione, scadenzario generato. Le rate si creano al salvataggio di ogni voce.
PASSI = [(1, "Contratto"), (2, "Voci e fatturazione"), (3, "Scadenzario")]


def _passo(numero: int) -> dict:
    return {"passo": numero, "passi_titoli": PASSI}


def _genera_rate(request, voce: m.VoceContratto) -> None:
    """Rate generate dal piano appena salvato; quelle modificate a mano non si toccano."""
    try:
        rate = servizi.genera_scadenzario(voce)
    except servizi.ScadenzarioBloccato as exc:
        messages.warning(request, f"Voce salvata, rate non rigenerate: {exc}")
        return
    if rate:
        messages.success(request, f"Voce salvata: {len(rate)} rate generate.")
    elif voce.piano_fatturazione.modalita == m.ModalitaFatturazione.SAL:
        messages.info(request, "Voce salvata. Fatturazione a SAL: le rate si inseriscono a mano.")
    else:
        messages.info(request, "Voce salvata. Nessuna rata generata dal piano.")


@editor_required
def contratto_guidata(request, pk):
    """Ultimo passo del nuovo contratto: le rate generate, voce per voce."""
    contratto = get_object_or_404(m.Contratto, pk=pk)
    permessi.verifica_oggetto(request.user, contratto)
    voci = (
        contratto.voci.filter(archiviato=False)
        .select_related("piano_fatturazione")
        .prefetch_related("piano_fatturazione__rate")
        .order_by("pk")
    )
    righe = []
    for v in voci:
        piano = getattr(v, "piano_fatturazione", None)
        rate = sorted(piano.rate.all(), key=lambda r: r.numero) if piano else []
        righe.append((v, rate, sum((r.importo for r in rate), Decimal("0.00"))))
    return render(
        request,
        "contratti/guidata_riepilogo.html",
        {"c": contratto, "voci": righe} | _passo(3),
    )


@editor_required
def contratto_nuovo(request):
    iniziali = {}
    if f := request.GET.get("fabbisogno"):
        iniziali["fabbisogno"] = f
    iniziali.setdefault(
        "procedura", m.Procedura.objects.filter(codice="affidamento_diretto").first()
    )
    form = forms.ContrattoForm(request.POST or None, initial=iniziali, utente=request.user)
    if request.method == "POST" and form.is_valid():
        contratto = form.save()
        messages.success(
            request, "Contratto creato. Ora la prima voce, con il suo piano di fatturazione."
        )
        url = reverse("contratti:voce_nuova", args=[contratto.pk])
        return redirect(f"{url}?guidata=1")
    return render(
        request,
        "contratti/form.html",
        {"form": form, "titolo": "Nuovo contratto", "avanti": "Avanti: voci e fatturazione"}
        | _passo(1),
    )


@editor_required
def contratto_modifica(request, pk):
    contratto = get_object_or_404(m.Contratto, pk=pk)
    permessi.verifica_oggetto(request.user, contratto)
    form = forms.ContrattoModificaForm(request.POST or None, instance=contratto)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Contratto aggiornato.")
        return redirect("contratti:contratto", pk=pk)
    return render(
        request,
        "contratti/form.html",
        {"form": form, "titolo": f"Modifica contratto — {contratto}", "annulla": contratto},
    )


def _coppie(valori) -> list[tuple[int, int]]:
    """Valori "12-34" dei checkbox → coppie di pk; quelli non validi si ignorano."""
    coppie = []
    for testo in valori:
        a, _, b = testo.partition("-")
        if _pk_o_none(a) and _pk_o_none(b):
            coppie.append((int(a), int(b)))
    return coppie


@editor_required
@require_POST
def fabbisogno_doppioni(request, pk):
    """Archivia i contratti registrati due volte nel fabbisogno (si tiene quello con più dati)."""
    f = get_object_or_404(m.Fabbisogno, pk=pk)
    permessi.verifica_oggetto(request.user, f)
    try:
        n = servizi.unisci_doppioni(f, _coppie(request.POST.getlist("doppioni")))
    except servizi.OperazioneNonAmmessa as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"{n} contratti doppi archiviati." if n else "Nessuna modifica.")
    return redirect("contratti:fabbisogno", pk=pk)


@editor_required
@require_POST
def fabbisogno_collega(request, pk):
    """Ricuce le catene dei rinnovi interrotte (es. dopo un accorpamento)."""
    f = get_object_or_404(m.Fabbisogno, pk=pk)
    permessi.verifica_oggetto(request.user, f)
    try:
        n = servizi.collega_contratti(f, _coppie(request.POST.getlist("collegamenti")))
    except servizi.OperazioneNonAmmessa as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"{n} contratti collegati al loro rinnovo.")
    return redirect("contratti:fabbisogno", pk=pk)


@editor_required
def contratto_collega(request, pk):
    """Collega a mano come rinnovo un contratto già registrato nello stesso fabbisogno."""
    contratto = get_object_or_404(m.Contratto.objects.select_related("fabbisogno"), pk=pk)
    permessi.verifica_oggetto(request.user, contratto)
    candidati = servizi.candidati_rinnovo(contratto)
    if request.method == "POST":
        scelto = next(
            (c for c in candidati if c.pk == _pk_o_none(request.POST.get("successore"))), None
        )
        if scelto is None:
            messages.error(request, "Scegli il contratto che rinnova questo.")
        else:
            servizi.collega_rinnovo(contratto, scelto)
            messages.success(request, f"Collegato: {scelto} è il rinnovo di questo contratto.")
            return redirect("contratti:contratto", pk=pk)
    return render(
        request,
        "contratti/collega.html",
        {
            "c": contratto,
            "fine": adapters.data_fine_effettiva(contratto),
            "candidati": [(x, adapters.data_fine_effettiva(x)) for x in candidati],
            "ha_successore": m.Contratto.objects.filter(predecessore=contratto).exists(),
        },
    )


@editor_required
@require_POST
def contratto_scollega(request, pk):
    """Toglie il collegamento al predecessore: il contratto torna inizio di una catena."""
    contratto = get_object_or_404(m.Contratto, pk=pk)
    permessi.verifica_oggetto(request.user, contratto)
    try:
        predecessore = servizi.scollega_predecessore(contratto)
    except servizi.OperazioneNonAmmessa as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Scollegato da {predecessore}.")
    return redirect("contratti:contratto", pk=pk)


@editor_required
def contratto_confluiti(request, pk):
    """Contratto nuovo che sostituisce anche altri contratti (F9.3): sceglie quali."""
    nuovo = get_object_or_404(m.Contratto.objects.select_related("fabbisogno"), pk=pk)
    permessi.verifica_oggetto(request.user, nuovo)
    candidati = servizi.candidati_confluenza(nuovo)
    if request.method == "POST":
        scelti = {str(v) for v in request.POST.getlist("confluiti")}
        da_collegare = [c for c in candidati if str(c.pk) in scelti]
        if not da_collegare:
            messages.error(request, "Scegli almeno un contratto.")
        else:
            for c in da_collegare:
                servizi.confluisci(c, nuovo)
            messages.success(request, f"{len(da_collegare)} contratti confluiti in questo.")
            return redirect("contratti:contratto", pk=pk)
    return render(
        request,
        "contratti/confluiti.html",
        {"c": nuovo, "candidati": [(x, adapters.data_fine_effettiva(x)) for x in candidati]},
    )


@editor_required
@require_POST
def contratto_togli_confluenza(request, pk):
    """Il contratto non è più sostituito dal contratto in cui era confluito."""
    contratto = get_object_or_404(m.Contratto, pk=pk)
    permessi.verifica_oggetto(request.user, contratto)
    ritorno = request.POST.get("ritorno") == "nuovo"
    try:
        nuovo = servizi.togli_confluenza(contratto)
    except servizi.OperazioneNonAmmessa as exc:
        messages.error(request, str(exc))
        return redirect("contratti:contratto", pk=pk)
    messages.success(request, f"{contratto} non è più sostituito da {nuovo}.")
    return redirect("contratti:contratto", pk=nuovo.pk if ritorno else pk)


def _pk_o_none(valore):
    try:
        return int(valore)
    except (TypeError, ValueError):
        return None


@editor_required
def contratto_sposta(request, pk):
    """Sposta il contratto in un altro fabbisogno: anteprima della catena, poi conferma."""
    contratto = get_object_or_404(m.Contratto.objects.select_related("fabbisogno"), pk=pk)
    permessi.verifica_oggetto(request.user, contratto)
    successivi = servizi.contratto_e_successivi(contratto)[1:]
    form = forms.SpostaContrattoForm(
        request.POST or None,
        contratto=contratto,
        n_successivi=len(successivi),
        utente=request.user,
    )
    contesto = {"c": contratto, "form": form, "successivi": successivi}
    if request.method != "POST" or not form.is_valid():
        return render(request, "contratti/sposta.html", contesto)
    destinazione = form.cleaned_data["destinazione"]
    con_successivi = form.cleaned_data.get("con_successivi", False)
    try:
        if request.POST.get("passo") == "conferma":
            scelto = _pk_o_none(request.POST.get("predecessore"))
            predecessore = m.Contratto.objects.filter(pk=scelto).first() if scelto else None
            a = servizi.sposta_contratto(
                contratto, destinazione, con_successivi=con_successivi, predecessore=predecessore
            )
            n = len(a.contratti)
            messages.success(
                request,
                f"{'Contratto spostato' if n == 1 else f'{n} contratti spostati'} in "
                f"«{destinazione.descrizione}».",
            )
            for avviso in a.avvisi:
                messages.info(request, avviso)
            return redirect("contratti:contratto", pk=contratto.pk)
        contesto["anteprima"] = servizi.anteprima_spostamento(
            contratto, destinazione, con_successivi=con_successivi
        )
    except (servizi.OperazioneNonAmmessa, ValidationError) as exc:
        messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
    contesto |= {"destinazione": destinazione, "con_successivi": con_successivi}
    return render(request, "contratti/sposta.html", contesto)


@editor_required
def fabbisogno_accorpa(request, pk):
    """Accorpa questo fabbisogno in un altro: anteprima dei collegamenti, poi conferma."""
    origine = get_object_or_404(m.Fabbisogno, pk=pk)
    permessi.verifica_oggetto(request.user, origine)
    form = forms.SceltaFabbisognoForm(request.POST or None, escludi=origine, utente=request.user)
    contesto = {"f": origine, "form": form}
    if request.method != "POST" or not form.is_valid():
        return render(request, "contratti/accorpa.html", contesto)
    destinazione = form.cleaned_data["destinazione"]
    try:
        if request.POST.get("passo") == "conferma":
            collegamenti = []
            for valore in request.POST.getlist("collegamenti"):
                p, _, s = valore.partition("-")
                if _pk_o_none(p) and _pk_o_none(s):
                    collegamenti.append((int(p), int(s)))
            doppioni = None
            if request.POST.get("doppioni_presenti"):
                doppioni = _coppie(request.POST.getlist("doppioni"))
            servizi.accorpa_fabbisogni(
                origine,
                destinazione,
                collegamenti=collegamenti,
                doppioni_confermati=doppioni,
                previsto_da_origine=request.POST.get("previsto_da") == "origine",
                pratica_da_origine=request.POST.get("pratica_da") == "origine",
            )
            messages.success(
                request, f"«{origine.descrizione}» accorpato e archiviato: i contratti sono qui."
            )
            return redirect("contratti:fabbisogno", pk=destinazione.pk)
        contesto["anteprima"] = servizi.anteprima_accorpamento(origine, destinazione)
    except (servizi.OperazioneNonAmmessa, ValidationError) as exc:
        messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
    contesto["destinazione"] = destinazione
    return render(request, "contratti/accorpa.html", contesto)


@editor_required
def contratto_rinnovo(request, pk):
    """Registra il rinnovo: nuovo contratto precompilato dal predecessore (SPEC §5.3)."""
    predecessore = get_object_or_404(m.Contratto, pk=pk)
    permessi.verifica_oggetto(request.user, predecessore)
    if adapters.ha_successore(predecessore):
        messages.error(request, "Il contratto ha già un successore registrato.")
        return redirect("contratti:contratto", pk=pk)
    fine = adapters.data_fine_effettiva(predecessore)
    iniziali = {
        campo: getattr(predecessore, campo)
        for campo in (
            "fornitore",
            "descrizione",
            "procedura",
            "durata_mesi",
            "tacito_rinnovo",
            "preavviso_disdetta_giorni",
        )
    }
    if fine:
        iniziali["data_inizio"] = fine + datetime.timedelta(days=1)
    voci_iniziali = [
        {
            "origine": v.pk,
            "riporta": True,
            "descrizione": v.descrizione,
            "importo_fisso": v.importo_fisso,
            "massimale_variabile": v.massimale_variabile,
        }
        for v in predecessore.voci.filter(archiviato=False, proroga__isnull=True).order_by("id")
    ]
    form = forms.RinnovoForm(request.POST or None, initial=iniziali)
    formset = forms.VociRinnovoFormSet(request.POST or None, initial=voci_iniziali, prefix="voci")
    sostituibili = servizi.candidati_sostituiti(predecessore)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        voci = [
            {
                "origine": d["origine"],
                "descrizione": d["descrizione"],
                "importo_fisso": d["importo_fisso"],
                "massimale_variabile": d.get("massimale_variabile") or Decimal("0.00"),
            }
            for d in formset.cleaned_data
            if d.get("riporta")
        ]
        scelti = set(request.POST.getlist("sostituisce"))
        sostituisce = [c for c in sostituibili if str(c.pk) in scelti]
        try:
            nuovo = servizi.registra_rinnovo(
                predecessore, form.cleaned_data, voci, utente=request.user, sostituisce=sostituisce
            )
        except (servizi.OperazioneNonAmmessa, ValidationError) as exc:
            messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
        else:
            messages.success(request, "Rinnovo registrato: i previsti del periodo sono sostituiti.")
            return redirect("contratti:contratto", pk=nuovo.pk)
    return render(
        request,
        "contratti/rinnovo.html",
        {
            "form": form,
            "formset": formset,
            "predecessore": predecessore,
            "fine": fine,
            "sostituibili": sostituibili,
            "sostituisce_scelti": request.POST.getlist("sostituisce"),
        },
    )


@editor_required
def proroga_nuova(request, pk):
    contratto = get_object_or_404(m.Contratto, pk=pk)
    permessi.verifica_oggetto(request.user, contratto)
    form = forms.ProrogaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        voce = None
        if d.get("importo_fisso"):
            voce = {
                "descrizione": d.get("descrizione_voce")
                or f"Proroga al {d['nuova_data_fine']:%d/%m/%Y}",
                "importo_fisso": d["importo_fisso"],
                "modalita": d["modalita"],
                "periodicita": d.get("periodicita") or "",
            }
        try:
            servizi.registra_proroga(
                contratto,
                {k: d[k] for k in ("data_atto", "nuova_data_fine", "riferimento", "note")},
                voce,
            )
        except (servizi.OperazioneNonAmmessa, ValidationError) as exc:
            form.add_error(None, "; ".join(getattr(exc, "messages", [str(exc)])))
        else:
            messages.success(request, "Proroga registrata.")
            return redirect("contratti:contratto", pk=pk)
    return render(
        request,
        "contratti/form.html",
        {
            "form": form,
            "titolo": f"Registra proroga — {contratto}",
            "annulla": contratto,
            "nota": f"Data di fine attuale: {adapters.data_fine_effettiva(contratto):%d/%m/%Y}"
            if contratto.data_inizio
            else None,
        },
    )


# --- Voci, scadenzario, rate --------------------------------------------------------


def _voce_form(request, contratto, voce=None):
    piano = getattr(voce, "piano_fatturazione", None) if voce else None
    dati = request.POST or None
    return (
        forms.VoceForm(dati, instance=voce, contratto=contratto, prefix="voce"),
        forms.PianoForm(dati, instance=piano, prefix="piano"),
        forms.QuoteFormSet(
            dati, instance=voce or m.VoceContratto(contratto=contratto), prefix="quote"
        ),
    )


@editor_required
def voce_modifica(request, contratto_pk, pk=None):
    contratto = get_object_or_404(m.Contratto, pk=contratto_pk)
    permessi.verifica_oggetto(request.user, contratto)
    voce = get_object_or_404(m.VoceContratto, pk=pk, contratto=contratto) if pk else None
    form, piano_form, quote = _voce_form(request, contratto, voce)
    guidata = request.GET.get("guidata") == "1"
    if request.method == "POST" and form.is_valid() and piano_form.is_valid() and quote.is_valid():
        with transaction.atomic():
            voce_salvata = form.save(commit=False)
            voce_salvata.contratto = contratto
            voce_salvata.save()
            piano = piano_form.save(commit=False)
            piano.voce = voce_salvata
            piano.save()
            quote.instance = voce_salvata
            quote.save()
        _genera_rate(request, voce_salvata)
        if guidata:
            return redirect("contratti:contratto_guidata", pk=contratto.pk)
        if request.GET.get("ritorno") == "piani":
            return redirect("contratti:piani_da_verificare")
        return redirect("contratti:contratto", pk=contratto.pk)
    contesto = {"form": form, "piano_form": piano_form, "quote": quote, "c": contratto}
    contesto |= {"voce": voce, "guidata": guidata} | (_passo(2) if guidata else {})
    return render(request, "contratti/voce_form.html", contesto)


@editor_required
@require_POST
def voce_anteprima(request, contratto_pk, pk=None):
    """Anteprima delle rate dai dati del form, senza salvare (htmx)."""
    contratto = get_object_or_404(m.Contratto, pk=contratto_pk)
    permessi.verifica_oggetto(request.user, contratto)
    voce = get_object_or_404(m.VoceContratto, pk=pk, contratto=contratto) if pk else None
    form, piano_form, quote = _voce_form(request, contratto, voce)
    contesto = {"rate": None, "errore": None}
    if not (form.is_valid() and piano_form.is_valid() and quote.is_valid()):
        contesto["errore"] = "Completa i campi obbligatori per vedere l'anteprima."
    elif contratto.data_inizio is None:
        contesto["errore"] = "Il contratto non ha la data di inizio."
    else:
        d, p = form.cleaned_data, piano_form.cleaned_data
        s = adapters.scadenza(contratto)
        inizio, fine = contratto.data_inizio, adapters.scadenze.data_fine_contrattuale(s)
        if d.get("proroga"):
            inizio, fine = adapters.periodi_proroghe(contratto)[d["proroga"].pk]
        piano_tmp = m.PianoFatturazione(**{k: p.get(k) for k in p})
        voce_engine = adapters.Voce(
            importo_fisso=d["importo_fisso"],
            inizio=inizio,
            fine=fine,
            anno_impegno=inizio.year,
            piano=adapters.piano_engine(piano_tmp, inizio),
            quote=tuple(
                Quota(q["dal"], q["al"], q["importo"])
                for q in quote.cleaned_data
                if q and q.get("dal") and q.get("al") and q.get("importo") is not None
            ),
        )
        contesto["rate"] = genera_rate(voce_engine)
        contesto["totale"] = sum((r.importo for r in contesto["rate"]), Decimal("0.00"))
    return render(request, "contratti/_anteprima_rate.html", contesto)


@editor_required
@require_POST
def scadenzario_genera(request, pk):
    voce = get_object_or_404(m.VoceContratto, pk=pk)
    permessi.verifica_oggetto(request.user, voce)
    try:
        rate = servizi.genera_scadenzario(voce)
    except servizi.ScadenzarioBloccato as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Scadenzario generato: {len(rate)} rate.")
    return redirect("contratti:contratto", pk=voce.contratto_id)


@editor_required
def rata_modifica(request, pk):
    rata = get_object_or_404(m.Rata.objects.select_related("piano__voce__contratto"), pk=pk)
    permessi.verifica_oggetto(request.user, rata)
    form = forms.RataForm(request.POST or None, instance=rata)
    if request.method == "POST" and form.is_valid():
        try:
            servizi.salva_rata_manuale(form.save(commit=False))
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            messages.success(request, "Rata aggiornata (marcata come modificata a mano).")
            return redirect("contratti:contratto", pk=rata.piano.voce.contratto_id)
    return render(
        request,
        "contratti/form.html",
        {"form": form, "titolo": f"Modifica {rata}", "annulla": rata.piano.voce.contratto},
    )


# --- Pratica di rinnovo -------------------------------------------------------------


@editor_required
@require_POST
def pratica_avanza(request, tipo, pk):
    modello = {"contratto": m.Contratto, "fabbisogno": m.Fabbisogno}.get(tipo)
    if modello is None:
        raise Http404
    oggetto = get_object_or_404(modello, pk=pk)
    permessi.verifica_oggetto(request.user, oggetto)
    form = forms.PassaggioPraticaForm(request.POST)
    if form.is_valid():
        d = form.cleaned_data
        servizi.avanza_pratica(oggetto, d["stato"], d["data"], d.get("note", ""), request.user)
        messages.success(request, "Passaggio della pratica registrato.")
    else:
        messages.error(request, "Passaggio non valido: indica stato e data.")
    destinazione = "contratti:contratto" if tipo == "contratto" else "contratti:fabbisogno"
    return redirect(destinazione, pk=pk)


# --- Archiviazione -----------------------------------------------------------------

ARCHIVIABILI = {
    "contratto": (m.Contratto, "contratti:contratto"),
    "fabbisogno": (m.Fabbisogno, "contratti:fabbisogno"),
    "fornitore": (m.Fornitore, "contratti:fornitore"),
    "voce": (m.VoceContratto, None),
}


@editor_required
def archivia(request, tipo, pk):
    if tipo not in ARCHIVIABILI:
        raise Http404
    modello, url_dettaglio = ARCHIVIABILI[tipo]
    oggetto = get_object_or_404(modello, pk=pk)
    if tipo != "fornitore":  # i fornitori sono in comune
        permessi.verifica_oggetto(request.user, oggetto)
    ritorno = (
        reverse(url_dettaglio, args=[pk])
        if url_dettaglio
        else reverse("contratti:contratto", args=[oggetto.contratto_id])
    )
    if request.method == "POST":
        ripristina = request.POST.get("ripristina") == "1"
        servizi.archivia(oggetto, not ripristina)
        messages.success(request, "Ripristinato." if ripristina else "Archiviato.")
        return redirect(ritorno)
    return render(request, "contratti/archivia.html", {"oggetto": oggetto, "ritorno": ritorno})


# --- Fabbisogni ----------------------------------------------------------------------


@login_required
def fabbisogni_elenco(request):
    g = request.GET
    qs = m.Fabbisogno.objects.select_related("categoria").annotate(
        n_contratti=Count("contratti", filter=Q(contratti__archiviato=False))
    )
    if not g.get("archiviati"):
        qs = qs.filter(archiviato=False)
    if q := g.get("q", "").strip():
        qs = qs.filter(
            Q(descrizione__icontains=q) | Q(referente__icontains=q) | Q(note__icontains=q)
        )
    if codici := _cluster_richiesti(request):
        qs = qs.filter(cluster__codice__in=codici)
    if g.get("decisione"):
        qs = qs.filter(decisione=g["decisione"])
    if g.get("categoria"):
        qs = qs.filter(categoria_id=g["categoria"])
    ordine = _ordine_qs(
        g.get("ordina", ""),
        {
            "descrizione": "descrizione",
            "area": "cluster__codice",
            "categoria": "categoria__nome",
            "decisione": "decisione",
            "contratti": "n_contratti",
        },
        ("cluster__codice", "descrizione"),
    )
    pagina = Paginator(qs.order_by(*ordine), PER_PAGINA).get_page(g.get("pagina"))
    return render(
        request,
        "contratti/fabbisogni_elenco.html",
        {
            "pagina": pagina,
            "filtri": g,
            "attivi": filtri_attivi(
                g,
                {
                    "q": "Testo",
                    "area": _etichetta_cluster,
                    "decisione": lambda v: "Decisione: "
                    + dict(m.Fabbisogno.Decisione.choices).get(v, v),
                    "categoria": lambda v: _nome(m.Categoria, v),
                    "archiviati": lambda v: "Con gli archiviati",
                },
            ),
            **_contesto_cluster(request),
            "decisioni": m.Fabbisogno.Decisione.choices,
            "categorie": m.Categoria.objects.all(),
        },
    )


def _spesa_ricorrente(f: m.Fabbisogno, oggi: datetime.date) -> dict | None:
    """Spesa senza contratto: prossime spese (calcolate) e promemoria (SPEC §5.6)."""
    from contratti.engine import spese

    s = adapters.spesa_ricorrente(f, oggi)
    if s is None:
        return None
    colore, prossima = adapters.promemoria_spesa(f, oggi)
    tutte = spese.occorrenze(s, datetime.date(oggi.year + 3, 12, 31))
    return {
        "alert": colore,
        "prossima": prossima,
        "prossime": [d for d in tutte if d >= oggi][:3],
        "ultime": [d for d in tutte if d < oggi][-3:],
    }


@login_required
def fabbisogno_dettaglio(request, pk):
    oggi = oggi_richiesta(request)
    f = get_object_or_404(m.Fabbisogno.objects.select_related("categoria", "impianto"), pk=pk)
    contratti = selettori.righe_contratti(
        selettori.contratti_base().filter(fabbisogno=f).order_by("data_inizio"), oggi
    )
    previsti = adapters.previsti_fabbisogno(f, adapters.orizzonte_default(oggi))
    return render(
        request,
        "contratti/fabbisogno_dettaglio.html",
        {
            "f": f,
            "contratti": contratti,
            "previsti": [(p, sum((valore(v) for v in p.voci), Decimal("0.00"))) for p in previsti],
            "natura_previsti": adapters.natura_previsti(f, adapters.contratto_base_previsti(f)),
            "spesa": _spesa_ricorrente(f, oggi),
            "doppioni": servizi.doppioni_del_fabbisogno(f),
            "collegamenti": [
                (p, s, adapters.data_fine_effettiva(p))
                for p, s in servizi.collegamenti_del_fabbisogno(f)
            ],
            "pratica": f.stati_pratica.order_by("-data", "-id"),
            "form_pratica": forms.PassaggioPraticaForm(initial={"data": oggi}),
            "storico": storico(f),
            "puo_modificare": permessi.puo_modificare(request.user, f.cluster_id),
        },
    )


@editor_required
def fabbisogno_modifica(request, pk=None):
    f = get_object_or_404(m.Fabbisogno, pk=pk) if pk else None
    if f is not None:
        permessi.verifica_oggetto(request.user, f)
    iniziali = (
        {} if f else {"categoria": m.Categoria.objects.filter(nome="Da classificare").first()}
    )
    form = forms.FabbisognoForm(
        request.POST or None, instance=f, initial=iniziali, utente=request.user
    )
    if request.method == "POST" and form.is_valid():
        f = form.save()
        messages.success(request, "Fabbisogno salvato.")
        return redirect("contratti:fabbisogno", pk=f.pk)
    return render(
        request,
        "contratti/form.html",
        {"form": form, "titolo": "Modifica fabbisogno" if f else "Nuovo fabbisogno", "annulla": f},
    )


# --- Fornitori -----------------------------------------------------------------------


@login_required
def fornitori_elenco(request):
    g = request.GET
    qs = m.Fornitore.objects.annotate(
        n_contratti=Count("contratti", filter=Q(contratti__archiviato=False))
    )
    if not g.get("archiviati"):
        qs = qs.filter(archiviato=False)
    if q := g.get("q", "").strip():
        qs = qs.filter(
            Q(ragione_sociale__icontains=q)
            | Q(partita_iva__icontains=q)
            | Q(codice_sap__icontains=q)
        )
    ordine = _ordine_qs(
        g.get("ordina", ""),
        {
            "ragione_sociale": "ragione_sociale",
            "codice_sap": "codice_sap",
            "contratti": "n_contratti",
        },
        ("ragione_sociale",),
    )
    pagina = Paginator(qs.order_by(*ordine), PER_PAGINA).get_page(g.get("pagina"))
    attivi = filtri_attivi(g, {"q": "Testo", "archiviati": lambda v: "Con gli archiviati"})
    return render(
        request,
        "contratti/fornitori_elenco.html",
        {"pagina": pagina, "filtri": g, "attivi": attivi},
    )


@login_required
def fornitore_dettaglio(request, pk):
    oggi = oggi_richiesta(request)
    f = get_object_or_404(m.Fornitore, pk=pk)
    contratti = selettori.righe_contratti(
        selettori.contratti_base().filter(fornitore=f).order_by("-data_inizio"), oggi
    )
    return render(
        request,
        "contratti/fornitore_dettaglio.html",
        {
            "f": f,
            "contratti": contratti,
            "stesso_codice": f.fornitori_stesso_codice_sap(),
            "storico": storico(f),
            "puo_modificare": role_of(request.user) in ("Admin", "Editor"),
        },
    )


@editor_required
def fornitore_modifica(request, pk=None):
    f = get_object_or_404(m.Fornitore, pk=pk) if pk else None
    form = forms.FornitoreForm(request.POST or None, instance=f)
    if request.method == "POST" and form.is_valid():
        f = form.save()
        messages.success(request, "Fornitore salvato.")
        return redirect("contratti:fornitore", pk=f.pk)
    return render(
        request,
        "contratti/form.html",
        {"form": form, "titolo": "Modifica fornitore" if f else "Nuovo fornitore", "annulla": f},
    )


# --- Proposte dell'import ------------------------------------------------------------


@login_required
def piani_da_verificare(request):
    """Elenco di lavoro: voci con piano `Da verificare`, il cui fatturato è un pro-rata."""
    voci = list(selettori.voci_piano_da_verificare(_cluster_richiesti(request)))
    return render(
        request,
        "contratti/piani_da_verificare.html",
        {
            **_contesto_cluster(request),
            "voci": voci,
            "totale": sum((v.peso for v in voci), Decimal("0.00")),
            "puo_modificare": role_of(request.user) in ("Admin", "Editor"),
        },
    )


@login_required
def proposte_elenco(request):
    return render(
        request,
        "contratti/proposte.html",
        {
            "raggruppamenti": m.PropostaRaggruppamento.objects.filter(stato="proposta")
            .prefetch_related("contratti__fornitore")
            .order_by("motivazione"),
            "predecessori": m.PropostaPredecessore.objects.filter(stato="proposta")
            .select_related("predecessore", "successore")
            .order_by("successore__data_inizio"),
            "puo_modificare": role_of(request.user) in ("Admin", "Editor"),
        },
    )


@editor_required
@require_POST
def proposta_azione(request, tipo, pk, azione):
    modelli = {"raggruppamento": m.PropostaRaggruppamento, "predecessore": m.PropostaPredecessore}
    if tipo not in modelli or azione not in ("conferma", "scarta"):
        raise Http404
    proposta = get_object_or_404(modelli[tipo], pk=pk)
    if tipo == "raggruppamento":
        coinvolti = proposta.contratti.select_related("fabbisogno")
    else:
        coinvolti = [proposta.predecessore, proposta.successore]
    permessi.verifica(request.user, *{c.fabbisogno.cluster_id for c in coinvolti})
    funzione = {
        ("raggruppamento", "conferma"): proposte_import.conferma_raggruppamento,
        ("predecessore", "conferma"): proposte_import.conferma_predecessore,
    }.get((tipo, azione), proposte_import.scarta)
    try:
        funzione(proposta)
    except proposte_import.PropostaNonApplicabile as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request, "Proposta confermata." if azione == "conferma" else "Proposta scartata."
        )
    return redirect("contratti:proposte")
