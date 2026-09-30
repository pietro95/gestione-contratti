from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from accounts.forms import LoginForm


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    pass


@login_required
def home(request):
    return render(request, "home.html")


@never_cache
@require_GET
def healthz(request):
    """Senza autenticazione: 200 se il database risponde, 503 altrimenti, senza dettagli."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})
