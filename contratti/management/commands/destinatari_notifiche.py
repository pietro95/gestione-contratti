"""Chi riceve le email di avviso (SPEC §5.10): addetti e utenti operativi, con l'indirizzo che
risulta da LDAP. Serve a capire perché un avviso non parte."""

from django.conf import settings
from django.core.management.base import BaseCommand

from accounts import rubrica
from contratti import notifiche


class Command(BaseCommand):
    help = "Mostra i destinatari delle email di avviso con il loro indirizzo."

    def handle(self, *args, **opzioni):
        attive = "sì" if settings.NOTIFICHE_EMAIL_ATTIVE else "NO (manca EMAIL_HOST)"
        self.stdout.write(f"Notifiche attive: {attive}")
        prova = getattr(settings, "NOTIFICHE_PROVA_A", "")
        self.stdout.write(f"Modalità di prova: {prova or 'no'}")
        gruppi = (
            ("Addetti amministrativi", notifiche.addetti_amministrativi()),
            ("Addetti al rilascio", notifiche.addetti_al_rilascio()),
            ("Admin ed Editor (nuove fatture)", notifiche.utenti_operativi()),
        )
        for titolo, utenti in gruppi:
            self.stdout.write(f"\n{titolo} ({len(utenti)}):")
            if not utenti:
                self.stdout.write("  nessuno: l'avviso non parte (funzione non assegnata?)")
            indirizzi = rubrica.indirizzi(utenti)
            for u in utenti:
                self.stdout.write(
                    f"  {u.get_username()} → {indirizzi.get(u.pk, 'NESSUN INDIRIZZO')}"
                )
