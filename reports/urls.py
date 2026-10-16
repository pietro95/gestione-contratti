from django.urls import path

from reports import views, views_acquisti

app_name = "reports"

urlpatterns = [
    path("budget/", views.budget, name="budget"),
    path("piano-ordini/", views.piano_ordini, name="piano_ordini"),
    path("wbs/", views.wbs_elenco, name="wbs"),
    path("wbs/<int:pk>/", views.wbs_spese, name="wbs_spese"),
    path("extra-budget/", views.extra_budget_elenco, name="extra_budget"),
    path("extra-budget/<int:pk>/", views.extra_budget_spese, name="extra_budget_spese"),
    path("acquisti/", views_acquisti.cruscotto_acquisti, name="cruscotto_acquisti"),
    path("rda/", views_acquisti.stato_rda, name="stato_rda"),
    path("da-chiudere/", views_acquisti.contratti_da_chiudere, name="contratti_da_chiudere"),
    path("stanziamenti/", views_acquisti.stanziamenti, name="stanziamenti"),
    path("anomalie/", views_acquisti.anomalie_esecuzione, name="anomalie_esecuzione"),
]
