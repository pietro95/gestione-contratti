from django.contrib.auth.forms import AuthenticationForm


class LoginForm(AuthenticationForm):
    """Un solo messaggio generico per ogni rifiuto: nessun dettaglio tecnico all'utente."""

    error_messages = {
        "invalid_login": (
            "Accesso non riuscito. Controlla nome utente e password; "
            "se il problema persiste contatta l'ufficio IT."
        ),
        "inactive": (
            "Accesso non riuscito. Controlla nome utente e password; "
            "se il problema persiste contatta l'ufficio IT."
        ),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Nome utente"
        self.fields["password"].label = "Password"
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"
