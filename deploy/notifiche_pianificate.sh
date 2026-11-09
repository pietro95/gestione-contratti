#!/bin/bash
# Processo principale del container "notifiche": ogni giorno all'ora NOTIFICHE_ORA (HH:MM,
# fuso Europe/Rome, default 08:30) lancia i promemoria per email (manage.py invia_promemoria:
# rilasci in attesa, contratti in scadenza; sabato e domenica non parte nulla). Se un lancio
# fallisce lo scrive nel log e riprova il giorno dopo: il container resta attivo.
set -uo pipefail

ora="${NOTIFICHE_ORA:-08:30}"
echo "Promemoria per email ogni giorno alle $ora."
while true; do
  adesso=$(date +%s)
  prossimo=$(date -d "today $ora" +%s)
  if [ "$prossimo" -le "$adesso" ]; then
    prossimo=$(date -d "tomorrow $ora" +%s)
  fi
  sleep $((prossimo - adesso))
  python manage.py invia_promemoria || echo "ERRORE: promemoria non inviati $(date '+%d/%m/%Y %H:%M')" >&2
done
