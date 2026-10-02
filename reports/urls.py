from django.urls import path

from reports import views

app_name = "reports"

urlpatterns = [
    path("budget/", views.budget, name="budget"),
    path("piano-ordini/", views.piano_ordini, name="piano_ordini"),
    path("wbs/", views.wbs_elenco, name="wbs"),
    path("wbs/<int:pk>/", views.wbs_spese, name="wbs_spese"),
]
