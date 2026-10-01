from django.urls import path

from reports import views

app_name = "reports"

urlpatterns = [
    path("budget/", views.budget, name="budget"),
    path("piano-ordini/", views.piano_ordini, name="piano_ordini"),
]
