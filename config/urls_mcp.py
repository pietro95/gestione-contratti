"""URL del container ``mcp`` (host pubblico, SPEC_MCP §2.2): SOLO il connettore.

Admin, interfaccia, login e autorizzazione non esistono su questo processo, anche se il
proxy fosse configurato male. ``/healthz`` serve al controllo di salute del container e
il proxy non lo pubblica.
"""

from django.urls import include, path
from oauth2_provider import views as oauth_views

from accounts import views as accounts_views
from connettore import oauth
from connettore import views as connettore_views

oauth_patterns = (
    [path("token/", oauth_views.TokenView.as_view(), name="token")],
    "oauth2_provider",
)

urlpatterns = [
    path("mcp", connettore_views.endpoint, name="mcp"),
    path(
        ".well-known/oauth-protected-resource",
        oauth.MetadatiRisorsa.as_view(),
        name="oauth-resource-metadata",
    ),
    path(
        ".well-known/oauth-protected-resource/mcp",
        oauth.MetadatiRisorsa.as_view(),
        name="oauth-resource-metadata-mcp",
    ),
    path(
        ".well-known/oauth-authorization-server",
        oauth.MetadatiServer.as_view(),
        name="oauth-server-metadata",
    ),
    path("oauth/", include(oauth_patterns)),
    path("healthz", accounts_views.healthz, name="healthz"),
]
