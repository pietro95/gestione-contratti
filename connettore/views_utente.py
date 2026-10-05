"""Pagina «Connettore MCP» dell'utente (host interno): collegamenti, revoca, ultime chiamate.

Ognuno vede e revoca solo i propri collegamenti; l'Admin revoca quelli degli altri da
Amministrazione (RUNBOOK §12.7). Un collegamento è un refresh token attivo di Claude.
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from oauth2_provider.models import RefreshToken, get_application_model

from connettore.models import RegistroChiamata
from connettore.oauth import connettore_attivo, utente_ammesso
from contratti import adapters
from contratti import models as m


def _attivo_o_404():
    if not connettore_attivo():
        raise Http404


def _collegamenti(user):
    return (
        RefreshToken.objects.filter(user=user, revoked__isnull=True)
        .select_related("application", "access_token")
        .order_by("-updated")
    )


def _revoca(rt: RefreshToken) -> None:
    """Revoca il collegamento intero: il refresh, i suoi predecessori e l'access token."""
    if rt.token_family:
        RefreshToken.revoke_family(rt.token_family)
    else:
        rt.revoke()


@login_required
def collegamenti(request):
    _attivo_o_404()
    oggi = timezone.localdate()
    claude_code = get_application_model().objects.filter(client_type="public").first()
    return render(
        request,
        "connettore/collegamenti.html",
        {
            "collegamenti": _collegamenti(request.user),
            "chiamate": RegistroChiamata.objects.filter(utente=request.user)[:20],
            "url_mcp": f"{settings.MCP_URL_PUBBLICO}/mcp",
            "client_claude_code": claude_code.client_id if claude_code else "",
            "ammesso": utente_ammesso(request.user),
            "giorni_login": int(adapters.parametro(m.Parametro.Chiave.MCP_GIORNI_LOGIN, oggi)),
        },
    )


@login_required
@require_POST
def revoca(request, pk):
    _attivo_o_404()
    rt = get_object_or_404(RefreshToken, pk=pk, user=request.user, revoked__isnull=True)
    _revoca(rt)
    messages.success(request, f"Collegamento «{rt.application.name}» revocato.")
    return redirect("connettore:collegamenti")


@login_required
@require_POST
def revoca_tutti(request):
    _attivo_o_404()
    n = 0
    for rt in list(_collegamenti(request.user)):
        _revoca(rt)
        n += 1
    messages.success(request, f"Collegamenti revocati: {n}.")
    return redirect("connettore:collegamenti")
