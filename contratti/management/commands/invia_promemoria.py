"""Promemoria per email: rilasci in attesa (all'addetto al rilascio) e contratti in scadenza
(ai referenti). SPEC §5.10. Da lanciare una volta al giorno (container ``notifiche``)."""

import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from contratti import promemoria


class Command(BaseCommand):
    help = "Invia i promemoria per email: rilasci in attesa e contratti in scadenza."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tipo", choices=["rilasci", "scadenze", "tutti"], default="tutti",
            help="Quali promemoria preparare (default: tutti).",
        )  # fmt: skip
        parser.add_argument("--oggi", help="Data di calcolo AAAA-MM-GG (default: oggi).")
        parser.add_argument(
            "--dry-run", action="store_true", help="Mostra i messaggi senza spedirli."
        )
        parser.add_argument(
            "--anche-weekend", action="store_true", help="Invia anche di sabato e domenica."
        )

    def handle(self, *args, **opzioni):
        try:
            oggi = (
                datetime.date.fromisoformat(opzioni["oggi"])
                if opzioni["oggi"]
                else timezone.localdate()
            )
        except ValueError as exc:
            raise CommandError("La data va scritta AAAA-MM-GG.") from exc
        if oggi.weekday() >= 5 and not opzioni["anche_weekend"]:
            self.stdout.write("Fine settimana: nessun promemoria (usa --anche-weekend).")
            return
        simula = opzioni["dry_run"]
        if not simula and not settings.NOTIFICHE_EMAIL_ATTIVE:
            raise CommandError(
                "Notifiche spente: configurare EMAIL_HOST (o NOTIFICHE_EMAIL_ATTIVE=true)."
            )
        tipi = ("rilasci", "scadenze") if opzioni["tipo"] == "tutti" else (opzioni["tipo"],)
        messaggi, partite = promemoria.invia_promemoria(oggi, tipi, simula)
        for msg in messaggi:
            nomi = ", ".join(str(u) for u in msg.destinatari) or "nessun destinatario"
            self.stdout.write(f"{msg.tipo} → {nomi}: {msg.oggetto}")
            if simula:
                self.stdout.write(msg.corpo + "\n")
        self.stdout.write(
            f"{len(messaggi)} messaggi preparati"
            + ("." if simula else f", {partite} email partite.")
        )
