"""URL di prova per i controlli di ruolo: esistono solo nei test."""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.urls import path
from django.views import View

from accounts.permissions import RoleRequiredMixin, admin_required, editor_required
from config.urls import urlpatterns as app_urlpatterns


@login_required
def lettura(request):
    return HttpResponse("lettura")


@editor_required
def modifica(request):
    return HttpResponse("modifica")


@admin_required
def amministrazione(request):
    return HttpResponse("amministrazione")


class ModificaView(RoleRequiredMixin, View):
    def post(self, request):
        return HttpResponse("modificato")


urlpatterns = [
    *app_urlpatterns,
    path("prova/lettura/", lettura, name="prova-lettura"),
    path("prova/modifica/", modifica, name="prova-modifica"),
    path("prova/amministrazione/", amministrazione, name="prova-amministrazione"),
    path("prova/modifica-cbv/", ModificaView.as_view(), name="prova-modifica-cbv"),
]
