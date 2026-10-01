#!/bin/bash
# Processo principale del container "backup": un dump al giorno all'ora BACKUP_ORA (HH:MM,
# fuso Europe/Rome, default 02:30). Se un backup fallisce lo scrive nel log e riprova il
# giorno dopo: il container resta attivo.
set -uo pipefail

ora="${BACKUP_ORA:-02:30}"
echo "Backup pianificato ogni giorno alle $ora (conservazione ${BACKUP_GIORNI:-14} giorni)."
while true; do
  adesso=$(date +%s)
  prossimo=$(date -d "today $ora" +%s)
  if [ "$prossimo" -le "$adesso" ]; then
    prossimo=$(date -d "tomorrow $ora" +%s)
  fi
  sleep $((prossimo - adesso))
  bash /scripts/backup.sh || echo "ERRORE: backup non riuscito $(date '+%d/%m/%Y %H:%M')" >&2
done
