"""Il container mcp espone solo il connettore (SPEC_MCP §2.2, punto 4)."""

import pytest
from django.urls import URLPattern, URLResolver

from config import urls_mcp

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_mcp")]


def percorsi(patterns, prefisso=""):
    for p in patterns:
        if isinstance(p, URLResolver):
            yield from percorsi(p.url_patterns, prefisso + str(p.pattern))
        elif isinstance(p, URLPattern):
            yield prefisso + str(p.pattern)


def test_solo_gli_endpoint_del_connettore():
    assert sorted(percorsi(urls_mcp.urlpatterns)) == [
        ".well-known/oauth-authorization-server",
        ".well-known/oauth-protected-resource",
        ".well-known/oauth-protected-resource/mcp",
        "healthz",
        "mcp",
        "oauth/token/",
    ]


@pytest.mark.parametrize(
    "percorso",
    ["/admin/", "/accounts/login/", "/oauth/authorize/", "/cruscotto/", "/report/budget/"],
)
def test_il_resto_non_esiste(client, admin_user, percorso):
    client.force_login(admin_user)
    assert client.get(percorso, HTTP_HOST="mcp.esempio.test", secure=True).status_code == 404


def test_impostazioni_del_container_mcp():
    from config.settings import mcp

    assert mcp.ROOT_URLCONF == "config.urls_mcp"
    assert not any("Session" in m or "Csrf" in m for m in mcp.MIDDLEWARE)
