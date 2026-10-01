#!/bin/bash
# Comandi di Django nel container dell'applicazione in esecuzione.
#
#   /appdata/gestione-contratti/app/deploy/manage.sh import_excel /import/Contratti_IT.xlsx --area IT --dry-run
#   /appdata/gestione-contratti/app/deploy/manage.sh crea_breakglass
#
# I file da importare vanno in /appdata/gestione-contratti/import, che nel container è /import.
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=deploy/comune.sh
source ./comune.sh
[ $# -ge 1 ] || errore "uso: $0 <comando di manage.py> [argomenti]"
if [ -t 0 ] && [ -t 1 ]; then
  compose exec web python manage.py "$@"
else
  compose exec -T web python manage.py "$@"
fi
