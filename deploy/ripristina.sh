#!/bin/bash
# Ripristino del database da un dump (deploy/restore.md §2). SOSTITUISCE i dati attuali.
#
#   /appdata/gestione-contratti/app/deploy/ripristina.sh <file.dump> [--conferma]
#
# Passi: backup di sicurezza dei dati attuali → arresto dell'app → database ricreato vuoto →
# pg_restore → riavvio dell'app → controllo di /healthz. Senza --conferma chiede di digitare
# RIPRISTINA. Agisce solo sui container del progetto gestione-contratti.
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=deploy/comune.sh
source ./comune.sh

[ $# -ge 1 ] || errore "uso: $0 <file.dump> [--conferma]"
nome="$(basename "$1")"
[ -f "$APP_DIR/backup/$nome" ] || errore "dump non trovato: $APP_DIR/backup/$nome"
if [ "${2:-}" != "--conferma" ]; then
  echo "Il database attuale sarà SOSTITUITO con $nome."
  read -r -p "Digitare RIPRISTINA per continuare: " risposta
  [ "$risposta" = "RIPRISTINA" ] || errore "annullato."
fi

echo "==> Backup di sicurezza dei dati attuali"
compose exec -T backup bash /scripts/backup.sh prima_del_ripristino
echo "==> Arresto dell'applicazione"
compose stop web
echo "==> Ripristino di $nome"
compose exec -T backup bash -c '
  set -euo pipefail
  export PGPASSWORD="$POSTGRES_PASSWORD" PGOPTIONS="-c client_min_messages=warning"
  psql -q -h db -U "$POSTGRES_USER" -d postgres \
    -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\" WITH (FORCE)" \
    -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\""
  pg_restore -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error "/backup/$1"
' _ "$nome"
echo "==> Riavvio dell'applicazione"
compose up --detach web
host_app="$(valore_env DJANGO_ALLOWED_HOSTS | cut -d, -f1)"
bind="$(valore_env APP_BIND)"
for _ in $(seq 1 30); do
  if curl -fsS --max-time 3 -H "Host: $host_app" -H "X-Forwarded-Proto: https" \
    "http://${bind:-127.0.0.1}:$(valore_env APP_PORT)/healthz" >/dev/null 2>&1; then
    echo "Ripristino completato da $nome."
    exit 0
  fi
  sleep 2
done
errore "l'applicazione non risponde dopo il ripristino: compose logs web (RUNBOOK §10)."
