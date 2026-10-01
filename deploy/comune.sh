#!/bin/bash
# Funzioni comuni agli script di deploy. Da includere con: source deploy/comune.sh
#
# Struttura (tutto sotto una sola cartella, default /appdata/gestione-contratti):
#   app/       checkout git del codice (qui sta questo script)
#   config/    .env (permessi 600) e certs/ (CA interna per LDAPS)
#   postgres/  dati del database
#   static/    file statici, serviti dal reverse proxy
#   backup/    dump giornalieri e pre-aggiornamento
#   import/    Excel e CSV da importare, con i report delle anomalie (in /import nel container)

PROGETTO=gestione-contratti
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$(cd "$DEPLOY_DIR/.." && pwd)"
APP_DIR="${APP_DIR:-$(cd "$SRC/.." && pwd)}"
ENV_FILE="$APP_DIR/config/.env"
export APP_DIR

errore() {
  echo "ERRORE: $*" >&2
  exit 1
}

# Valore di una variabile del .env, senza eseguire il file (i DN LDAP contengono spazi).
# Vuoto se la variabile manca (mai un errore: gli script girano con set -e).
valore_env() {
  { grep -E "^$1=" "$ENV_FILE" || true; } | tail -n 1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'
}

# Docker Compose limitato a questo progetto: non tocca gli altri container del server.
compose() {
  docker compose --project-name "$PROGETTO" --file "$DEPLOY_DIR/docker-compose.prod.yml" \
    --env-file "$ENV_FILE" "$@"
}
