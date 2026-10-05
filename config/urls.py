from django.contrib import admin
from django.urls import include, path

from accounts import views as accounts_views
from connettore import oauth
from contratti import views as contratti_views

urlpatterns = [
    path("", contratti_views.home, name="home"),
    path("healthz", accounts_views.healthz, name="healthz"),
    path("accounts/", include("accounts.urls")),
    path("", include("contratti.urls")),
    path("report/", include("reports.urls")),
    path("admin/", admin.site.urls),
    path("connettore/", include("connettore.urls")),
    # Connettore MCP: login e consenso solo sull'host interno (SPEC_MCP §2.1).
    path(
        "oauth/",
        include(
            ([path("authorize/", oauth.Autorizza.as_view(), name="authorize")], "oauth2_provider")
        ),
    ),
]
