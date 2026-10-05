from django.contrib import admin

from connettore.models import RegistroChiamata


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
