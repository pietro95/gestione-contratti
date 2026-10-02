from django.urls import path

from contratti import views, views_import

app_name = "contratti"

urlpatterns = [
    path("cruscotto/", views.cruscotto, name="cruscotto"),
    path("cerca/", views.cerca, name="cerca"),
    path("contratti/", views.contratti_elenco, name="contratti"),
    path("contratti/nuovo/", views.contratto_nuovo, name="contratto_nuovo"),
    path("contratti/<int:pk>/", views.contratto_dettaglio, name="contratto"),
    path("contratti/<int:pk>/modifica/", views.contratto_modifica, name="contratto_modifica"),
    path("contratti/<int:pk>/rinnovo/", views.contratto_rinnovo, name="contratto_rinnovo"),
    path("contratti/<int:pk>/proroga/", views.proroga_nuova, name="proroga_nuova"),
    path("contratti/<int:pk>/sposta/", views.contratto_sposta, name="contratto_sposta"),
    path("contratti/<int:pk>/scadenzario/", views.contratto_guidata, name="contratto_guidata"),
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
    path("fabbisogni/<int:pk>/accorpa/", views.fabbisogno_accorpa, name="fabbisogno_accorpa"),
    path("fabbisogni/<int:pk>/doppioni/", views.fabbisogno_doppioni, name="fabbisogno_doppioni"),
    path("fornitori/", views.fornitori_elenco, name="fornitori"),
    path("fornitori/nuovo/", views.fornitore_modifica, name="fornitore_nuovo"),
    path("fornitori/<int:pk>/", views.fornitore_dettaglio, name="fornitore"),
    path("fornitori/<int:pk>/modifica/", views.fornitore_modifica, name="fornitore_modifica"),
    path("piani-da-verificare/", views.piani_da_verificare, name="piani_da_verificare"),
    path("import/", views_import.importazioni, name="importazioni"),
    path("import/carica/<str:tipo>/", views_import.importazione_carica, name="importazione_carica"),
    path(
        "import/modello/<str:tipo>/",
        views_import.importazione_modello,
        name="importazione_modello",
    ),
    path("import/<int:pk>/", views_import.importazione, name="importazione"),
    path(
        "import/<int:pk>/conferma/",
        views_import.importazione_conferma,
        name="importazione_conferma",
    ),
    path(
        "import/<int:pk>/annulla/", views_import.importazione_annulla, name="importazione_annulla"
    ),
    path("import/<int:pk>/report/", views_import.importazione_report, name="importazione_report"),
    path("proposte/", views.proposte_elenco, name="proposte"),
    path(
        "proposte/<str:tipo>/<int:pk>/<str:azione>/",
        views.proposta_azione,
        name="proposta_azione",
    ),
]
