from django.apps import AppConfig


class ConnettoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "connettore"
    verbose_name = "Connettore MCP"

    def ready(self):
        from connettore import esecuzione  # noqa: F401  (registra i segnali della storia)
