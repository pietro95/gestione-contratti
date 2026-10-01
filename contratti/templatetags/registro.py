"""Filtri di presentazione: importi all'italiana e badge degli alert."""

from decimal import Decimal

from django import template
from django.template.defaultfilters import floatformat
from django.utils.html import format_html

register = template.Library()

ALERT = {
    "rosso": ("danger", "🔴 Scaduto"),
    "arancione": ("warning", "🟠 Oltre la data limite"),
    "giallo": ("warning-subtle text-dark", "🟡 In avvicinamento"),
    "verde": ("success", "🟢 Regolare"),
}
STATO = {
    "attivo": ("success", "Attivo"),
    "futuro": ("info", "Futuro"),
    "scaduto": ("secondary", "Scaduto"),
    "senza_data": ("dark", "Senza data"),
}


@register.filter
def euro(valore):
    """1234.5 → "1.234,50 €"."""
    if valore is None or valore == "":
        return "—"
    return f"{floatformat(Decimal(valore), '2g')} €"


@register.filter
def alert_badge(valore):
    if not valore:
        return "—"
    classe, testo = ALERT[str(valore)]
    return format_html('<span class="badge text-bg-{}">{}</span>', classe, testo)


@register.filter
def stato_badge(valore):
    classe, testo = STATO.get(valore, ("light", valore))
    return format_html('<span class="badge text-bg-{}">{}</span>', classe, testo)


@register.simple_tag(takes_context=True)
def query_con(context, **kwargs):
    """Querystring corrente con alcuni parametri cambiati (paginazione con filtri)."""
    query = context["request"].GET.copy()
    for chiave, valore in kwargs.items():
        query[chiave] = valore
    return query.urlencode()
