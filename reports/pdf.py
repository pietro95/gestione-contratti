"""PDF dei report generati dal server con WeasyPrint (F9.6).

Il PDF non dipende dal browser né dal dialogo di stampa del sistema: A4 orizzontale, intestazione
e numeri di pagina su ogni pagina. I template sono dedicati (``reports/pdf/``), senza Bootstrap.
Si leggono solo file locali di ``static/``: nessuna risorsa esterna.
"""

from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone

STATICI = Path(settings.BASE_DIR) / "static"


def _url(relativo: str) -> str:
    return (STATICI / relativo).resolve().as_uri()


def _solo_statici(url: str, *args, **kwargs):
    """Risolve solo i file di ``static/``: niente rete, niente altri percorsi."""
    from weasyprint.urls import default_url_fetcher

    radice = STATICI.resolve().as_uri() + "/"
    if not url.startswith(radice) or ".." in url:
        raise ValueError(f"Risorsa non ammessa nel PDF: {url}")
    return default_url_fetcher(url, *args, **kwargs)


def documento(template: str, contesto: dict, request=None):
    """Documento impaginato da WeasyPrint (pagine e dimensioni, per i test)."""
    from weasyprint import HTML  # import pesante: solo quando si genera un PDF

    contesto = {
        **contesto,
        "pdf_css": _url("css/pdf.css"),
        "pdf_logo": _url("img/logo/siciliacque_pdf.png"),  # SVG troppo pesante su ogni pagina
        "generato_il": timezone.localtime(),
    }
    html = render_to_string(template, contesto, request=request)
    return HTML(string=html, base_url=STATICI.resolve().as_uri() + "/",
                url_fetcher=_solo_statici).render()  # fmt: skip


def genera(template: str, contesto: dict, request=None) -> bytes:
    return documento(template, contesto, request).write_pdf()


def risposta(template: str, contesto: dict, nome_file: str, request=None) -> HttpResponse:
    response = HttpResponse(genera(template, contesto, request), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{nome_file}"'
    return response
