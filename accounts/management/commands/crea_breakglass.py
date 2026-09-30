"""Crea l'unico account locale di emergenza, o ne cambia la password.

La password si digita due volte (getpass) e non passa mai da argomenti o variabili
d'ambiente: va custodita fuori dall'applicazione (SPEC §8.1).
"""

from getpass import getpass

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Crea l'account break-glass (uno solo) o ne reimposta la password."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="breakglass")
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help="Reimposta la password dell'account break-glass esistente.",
        )

    def handle(self, *args, username, reset_password, **options):
        model = get_user_model()
        existing = model.objects.filter(is_breakglass=True).first()
        if existing and not reset_password:
            raise CommandError(
                f"Esiste già l'account break-glass '{existing.username}'. "
                "Usa --reset-password per cambiarne la password."
            )
        if reset_password and not existing:
            raise CommandError("Nessun account break-glass da aggiornare.")
        if not existing and model.objects.filter(username__iexact=username).exists():
            raise CommandError(f"Il nome utente '{username}' è già in uso.")

        user = existing or model(username=username)
        password = self._ask_password(user)

        with transaction.atomic():
            user.set_password(password)
            user.is_breakglass = True
            user.is_active = True
            user.is_staff = True
            user.is_superuser = True
            user.save()

        action = "aggiornata la password di" if existing else "creato"
        self.stdout.write(self.style.SUCCESS(f"Break-glass: {action} '{user.username}'."))

    def _ask_password(self, user):
        min_length = settings.BREAKGLASS_MIN_PASSWORD_LENGTH
        password = getpass(f"Password (almeno {min_length} caratteri): ")
        if getpass("Ripeti la password: ") != password:
            raise CommandError("Le password non coincidono.")
        if len(password) < min_length:
            raise CommandError(f"Password troppo corta: servono almeno {min_length} caratteri.")
        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        return password
