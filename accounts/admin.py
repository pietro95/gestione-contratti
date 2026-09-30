from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from accounts.models import LoginAttempt, User


@admin.register(User)
class AccountsUserAdmin(UserAdmin):
    list_display = ("username", "first_name", "last_name", "is_staff", "is_breakglass")
    list_filter = ("is_staff", "is_superuser", "is_active", "is_breakglass", "groups")
    readonly_fields = ("is_breakglass", "last_login", "date_joined")
    fieldsets = (*UserAdmin.fieldsets, ("Emergenza", {"fields": ("is_breakglass",)}))


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "username", "success", "esito", "backend", "ip_address")
    list_filter = ("success", "esito", "backend")
    search_fields = ("username", "ip_address")
    date_hierarchy = "timestamp"

    # Log in sola lettura: niente aggiunte, modifiche o cancellazioni dall'admin.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
