"""Filtri e tag di presentazione: importi all'italiana, badge di stato, ordinamento e filtri."""

from decimal import Decimal

from django import forms, template
from django.template.defaultfilters import floatformat
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html

register = template.Library()

# Testi brevi e colori coerenti in tutte le pagine (classi .stato-* di static/css/app.css).
ALERT = {
    "rosso": ("rosso", "Senza rinnovo"),
    "arancione": ("arancione", "Oltre la data limite"),
    "giallo": ("giallo", "In avvicinamento"),
    "verde": ("verde", "Regolare"),
}
STATO = {
    "attivo": ("verde", "Attivo"),
    "futuro": ("blu", "Futuro"),
    "scaduto": ("grigio", "Scaduto"),
    "senza_data": ("grigio", "Senza data"),
}


@register.filter
def euro(valore):
    """1234.5 → "1.234,50 €"."""
    if valore is None or valore == "":
        return "—"
    return f"{floatformat(Decimal(valore), '2g')} €"


def _badge(classe, testo):
    return format_html('<span class="stato stato-{}">{}</span>', classe, testo)


@register.filter
def alert_badge(valore):
    if not valore:
        return "—"
    return _badge(*ALERT[str(valore)])


@register.filter
def alert_testo(valore):
    return ALERT[str(valore)][1] if valore else ""


@register.filter
def stato_badge(valore):
    classe, testo = STATO.get(valore, ("grigio", valore))
    return _badge(classe, testo)


# Fasi della RDA (SPEC §5.7): grigio = aspetta il referente, giallo = l'addetto o SAP,
# blu = il contratto, verde = esecuzione e chiusura.
FASE_RDA = {
    "bozza": ("grigio", "Bozza"),
    "da_correggere": ("arancione", "Da correggere"),
    "inviata": ("giallo", "Inviata"),
    "inserita": ("giallo", "Inserita in SAP"),
    "rilasciata": ("giallo", "Rilasciata"),
    "contratto_emesso": ("blu", "Contratto emesso"),
    "in_esecuzione": ("verde", "In esecuzione"),
    "chiusa": ("verde", "Chiusa"),
    "annullata": ("grigio", "Annullata"),
}


@register.filter
def quantita(valore):
    """2.000 → «2», 2.500 → «2,5» (come nella scheda SAP)."""
    from contratti.engine.acquisti import formato_quantita

    return "" if valore in (None, "") else formato_quantita(Decimal(valore))


@register.filter
def importo_sap(valore):
    """1348.98 → «1.348,98», senza simbolo: da incollare in SAP."""
    from contratti.engine.acquisti import formato_euro

    return "" if valore in (None, "") else formato_euro(Decimal(valore)).removesuffix(" €")


@register.filter
def fase_badge(valore):
    classe, testo = FASE_RDA.get(str(valore), ("grigio", valore))
    return _badge(classe, testo)


@register.filter
def iniziali(utente):
    nome = (utente.get_full_name() or utente.get_username()).replace(".", " ").split()
    return "".join(p[0] for p in nome[:2]).upper() or "?"


LARGHI = {"descrizione", "note", "link_documenti", "fabbisogno", "fornitore"}


@register.filter
def colonna(campo):
    """Larghezza della colonna di un campo nel form, dal tipo di widget e dal nome."""
    widget = campo.field.widget
    nome = campo.name.split("-")[-1]
    if isinstance(widget, forms.Textarea):
        return "col-12"
    if nome in LARGHI:
        return "col-12 col-lg-6" if nome in ("fabbisogno", "fornitore") else "col-12"
    if isinstance(widget, forms.CheckboxInput):
        return "col-sm-6 col-lg-4 d-flex align-items-end"
    if isinstance(widget, forms.DateInput):
        return "col-sm-6 col-lg-3"
    return "col-sm-6 col-lg-4"


@register.filter
def e_checkbox(campo):
    return isinstance(campo.field.widget, forms.CheckboxInput)


@register.simple_tag(takes_context=True)
def query_con(context, **kwargs):
    """Querystring corrente con alcuni parametri cambiati (paginazione con filtri)."""
    query = context["request"].GET.copy()
    for chiave, valore in kwargs.items():
        query[chiave] = valore
    return query.urlencode()


@register.simple_tag(takes_context=True)
def query_senza(context, *chiavi):
    """Querystring corrente senza alcuni parametri (rimozione di un filtro attivo)."""
    query = context["request"].GET.copy()
    for chiave in (*chiavi, "pagina"):
        query.pop(chiave, None)
    return query.urlencode()


@register.simple_tag(takes_context=True)
def ordina(context, campo, etichetta):
    """Intestazione di colonna ordinabile: alterna crescente / decrescente."""
    query = context["request"].GET.copy()
    attuale = query.get("ordina", "")
    discendente = attuale == campo
    query["ordina"] = f"-{campo}" if discendente else campo
    query.pop("pagina", None)
    if attuale == campo:
        icona, aria = "bi-sort-up", "crescente"
    elif attuale == f"-{campo}":
        icona, aria = "bi-sort-down", "decrescente"
    else:
        icona, aria = "bi-arrow-down-up", None
    return format_html(
        '<a class="ordina" href="?{}">{} <i class="bi {}" aria-hidden="true"></i>{}</a>',
        query.urlencode(),
        etichetta,
        icona,
        format_html('<span class="visually-hidden"> (ordine {})</span>', aria) if aria else "",
    )


@register.inclusion_tag("_nav_voce.html", takes_context=True)
def nav_voce(context, nome_url, etichetta, icona, *prefissi, conteggio=None):
    """Voce della barra laterale, evidenziata se la pagina corrente le appartiene."""
    try:
        url = reverse(nome_url)
    except NoReverseMatch:
        url = "#"
    percorso = context["request"].path
    attivo = percorso == url or any(percorso.startswith(p) for p in prefissi)
    return {
        "url": url,
        "etichetta": etichetta,
        "icona": icona,
        "attivo": attivo,
        "conteggio": conteggio,
    }
