from django.contrib import admin
from django.urls import include, path

from accounts import views as accounts_views
from contratti import views as contratti_views

urlpatterns = [
    path("", contratti_views.home, name="home"),
    path("healthz", accounts_views.healthz, name="healthz"),
    path("accounts/", include("accounts.urls")),
    path("", include("contratti.urls")),
    path("report/", include("reports.urls")),
    path("admin/", admin.site.urls),
]
