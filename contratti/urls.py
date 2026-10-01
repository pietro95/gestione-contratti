from django.urls import path

from contratti import views

app_name = "contratti"

urlpatterns = [
    path("cruscotto/", views.cruscotto, name="cruscotto"),
    path("contratti/", views.contratti_elenco, name="contratti"),
    path("contratti/nuovo/", views.contratto_nuovo, name="contratto_nuovo"),
    path("contratti/<int:pk>/", views.contratto_dettaglio, name="contratto"),
    path("contratti/<int:pk>/modifica/", views.contratto_modifica, name="contratto_modifica"),
    path("contratti/<int:pk>/rinnovo/", views.contratto_rinnovo, name="contratto_rinnovo"),
    path("contratti/<int:pk>/proroga/", views.proroga_nuova, name="proroga_nuova"),
    path("contratti/<int:contratto_pk>/voci/nuova/", views.voce_modifica, name="voce_nuova"),
    path("contratti/<int:contratto_pk>/voci/<int:pk>/", views.voce_modifica, name="voce_modifica"),
    path(
        "contratti/<int:contratto_pk>/voci/anteprima/",
        views.voce_anteprima,
        name="voce_anteprima",
    ),
    path(
        "contratti/<int:contratto_pk>/voci/<int:pk>/anteprima/",
        views.voce_anteprima,
        name="voce_anteprima_esistente",
    ),
    path("voci/<int:pk>/scadenzario/", views.scadenzario_genera, name="scadenzario_genera"),
    path("rate/<int:pk>/", views.rata_modifica, name="rata_modifica"),
    path("pratica/<str:tipo>/<int:pk>/", views.pratica_avanza, name="pratica_avanza"),
    path("archivia/<str:tipo>/<int:pk>/", views.archivia, name="archivia"),
    path("fabbisogni/", views.fabbisogni_elenco, name="fabbisogni"),
    path("fabbisogni/nuovo/", views.fabbisogno_modifica, name="fabbisogno_nuovo"),
    path("fabbisogni/<int:pk>/", views.fabbisogno_dettaglio, name="fabbisogno"),
    path("fabbisogni/<int:pk>/modifica/", views.fabbisogno_modifica, name="fabbisogno_modifica"),
    path("fornitori/", views.fornitori_elenco, name="fornitori"),
    path("fornitori/nuovo/", views.fornitore_modifica, name="fornitore_nuovo"),
    path("fornitori/<int:pk>/", views.fornitore_dettaglio, name="fornitore"),
    path("fornitori/<int:pk>/modifica/", views.fornitore_modifica, name="fornitore_modifica"),
    path("proposte/", views.proposte_elenco, name="proposte"),
    path(
        "proposte/<str:tipo>/<int:pk>/<str:azione>/",
        views.proposta_azione,
        name="proposta_azione",
    ),
]
