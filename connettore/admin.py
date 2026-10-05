from django.contrib import admin

from connettore.models import OperazioneMCP, RegistroChiamata


@admin.register(RegistroChiamata)
class RegistroChiamataAdmin(admin.ModelAdmin):
    """Sola lettura: il registro non si modifica né si cancella."""

    list_display = ("timestamp", "utente", "client_id", "metodo", "tool", "esito", "durata_ms")
    list_filter = ("esito", "metodo", "tool")
    search_fields = ("utente__username", "client_id", "tool", "messaggio")
    date_hierarchy = "timestamp"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OperazioneMCP)
class OperazioneMCPAdmin(admin.ModelAdmin):
    """Sola lettura: anteprime e conferme di scrittura dal connettore."""

    list_display = ("creata_il", "utente", "tool", "stato", "confermata_il")
    list_filter = ("stato", "tool")
    search_fields = ("utente__username", "tool", "codice")
    date_hierarchy = "creata_il"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
