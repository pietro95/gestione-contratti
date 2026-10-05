from django.urls import path

from connettore import views_utente

app_name = "connettore"

urlpatterns = [
    path("", views_utente.collegamenti, name="collegamenti"),
    path("<int:pk>/revoca/", views_utente.revoca, name="revoca"),
    path("revoca-tutti/", views_utente.revoca_tutti, name="revoca_tutti"),
]
