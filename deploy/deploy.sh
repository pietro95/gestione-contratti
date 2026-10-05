#!/bin/bash
# Installazione e aggiornamento sul server Docker condiviso.
#
#   /appdata/gestione-contratti/app/deploy/deploy.sh <versione>     es. v1.0 (tag git)
#
# Passi: controlli → backup pre-aggiornamento → checkout della versione → build (con i file
# statici) → migrate → riavvio → attesa di /healthz. Si ferma al primo errore.
# Agisce solo sul progetto Compose "gestione-contratti": nessun prune, nessun down -v,
# nessuna operazione sugli altri container o immagini del server.
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=deploy/comune.sh
source ./comune.sh

# Tutto dentro main: bash legge la funzione per intero prima di eseguirla, quindi il checkout
# di una nuova versione (che riscrive questo file) non altera lo script in esecuzione.
attendi_mcp() {
  echo -n "==> Attesa del connettore MCP su $MCP_BIND:$MCP_PORT "
  for _ in $(seq 1 30); do
    if curl -fsS --max-time 3 -H "Host: $MCP_HOST" -H "X-Forwarded-Proto: https" \
      "http://$MCP_BIND:$MCP_PORT/healthz" >/dev/null 2>&1; then
      echo "ok"
      return 0
    fi
    echo -n "."
    sleep 2
  done
  echo
  compose logs --tail 50 mcp
  errore "il connettore MCP non risponde. Vedi RUNBOOK §12."
}

main() {
  [ $# -eq 1 ] || errore "uso: $0 <versione>  (tag git, es. v1.0; oppure un commit)"
  VERSIONE_RICHIESTA="$1"

  # --- Controlli ------------------------------------------------------------------------
  command -v docker >/dev/null || errore "docker non installato."
  docker compose version >/dev/null 2>&1 || errore "manca il plugin docker compose."
  [ -f "$ENV_FILE" ] || errore "manca $ENV_FILE: copiare .env.example e compilarlo (RUNBOOK §3)."
  if [ "$(stat -c %a "$ENV_FILE")" != "600" ]; then
    echo "ATTENZIONE: $ENV_FILE dovrebbe avere permessi 600 (contiene password)." >&2
  fi
  for v in APP_PORT DJANGO_SECRET_KEY DATABASE_URL POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB; do
    [ -n "$(valore_env "$v")" ] || errore "variabile $v vuota o assente in $ENV_FILE."
  done
  APP_PORT="$(valore_env APP_PORT)"
  APP_BIND="$(valore_env APP_BIND)"
  APP_BIND="${APP_BIND:-127.0.0.1}"
  HOST_APP="$(valore_env DJANGO_ALLOWED_HOSTS | cut -d, -f1)"
  pg_pwd="$(valore_env POSTGRES_PASSWORD)"
  case "$(valore_env DATABASE_URL)" in
    *":$pg_pwd@"*) ;;
    *) errore "la password in DATABASE_URL non coincide con POSTGRES_PASSWORD." ;;
  esac
  if mcp_attivo; then
    for v in MCP_HOST MCP_URL_PUBBLICO MCP_URL_INTERNO MCP_DATABASE_URL; do
      [ -n "$(valore_env "$v")" ] || errore "connettore MCP: variabile $v vuota in $ENV_FILE (RUNBOOK §12)."
    done
    MCP_PORT="$(valore_env MCP_PORT)"
    MCP_BIND="$(valore_env MCP_BIND)"
    MCP_BIND="${MCP_BIND:-127.0.0.1}"
    MCP_HOST="$(valore_env MCP_HOST)"
    [ "$(valore_env MCP_URL_PUBBLICO)" = "https://$MCP_HOST" ] \
      || errore "MCP_URL_PUBBLICO deve essere https://\$MCP_HOST (senza percorso)."
    case "$(valore_env MCP_DATABASE_URL)" in
      *"//$(valore_env POSTGRES_USER):"*) errore "MCP_DATABASE_URL deve usare un utente diverso da POSTGRES_USER." ;;
    esac
  fi
  [ -z "$(git -C "$SRC" status --porcelain --untracked-files=no)" ] \
    || errore "modifiche locali in $SRC: il codice sul server non si modifica a mano."

  mkdir -p "$APP_DIR"/{postgres,backup,import,config/certs}

  in_esecuzione=false
  if [ -n "$(compose ps --quiet db 2>/dev/null)" ]; then
    in_esecuzione=true
  elif ss -ltnH "( sport = :$APP_PORT )" | grep -q .; then
    errore "la porta $APP_PORT è già usata da un altro servizio: sceglierne un'altra nel .env."
  fi
  if mcp_attivo && [ -z "$(compose ps --quiet mcp 2>/dev/null)" ] \
    && ss -ltnH "( sport = :$MCP_PORT )" | grep -q .; then
    errore "la porta $MCP_PORT (MCP_PORT) è già usata da un altro servizio."
  fi

  # --- Backup prima di toccare qualcosa -------------------------------------------------
  if $in_esecuzione; then
    echo "==> Backup pre-aggiornamento"
    compose exec -T backup bash /scripts/backup.sh "pre_${VERSIONE_RICHIESTA//[^A-Za-z0-9.]/_}"
  fi

  # --- Codice ---------------------------------------------------------------------------
  echo "==> Codice: $VERSIONE_RICHIESTA"
  git -C "$SRC" fetch --tags --quiet origin
  git -C "$SRC" -c advice.detachedHead=false checkout --quiet "$VERSIONE_RICHIESTA"
  APP_VERSION="$(git -C "$SRC" describe --tags --always)"
  export APP_VERSION

  # --- Immagine e database --------------------------------------------------------------
  echo "==> Build dell'immagine gestione-contratti:$APP_VERSION"
  compose build --pull web
  echo "==> Database"
  compose up --detach --wait db
  echo "==> Migration"
  compose run --rm --no-deps web python manage.py migrate --noinput
  echo "==> Permessi di $APP_DIR/import"
  compose run --rm --no-deps --user 0 web chown -R 1000:1000 /import
  compose run --rm --no-deps web python manage.py check --deploy --fail-level ERROR
  if mcp_attivo; then
    echo "==> Utente PostgreSQL del connettore MCP (sola lettura)"
    compose run --rm --no-deps web python manage.py ruolo_db_mcp
  fi

  # --- Avvio ----------------------------------------------------------------------------
  echo "==> Avvio"
  compose up --detach --remove-orphans
  echo -n "==> Attesa di /healthz su $APP_BIND:$APP_PORT "
  for _ in $(seq 1 30); do
    if curl -fsS --max-time 3 -H "Host: $HOST_APP" -H "X-Forwarded-Proto: https" \
      "http://$APP_BIND:$APP_PORT/healthz" >/dev/null 2>&1; then
      echo "ok"
      if mcp_attivo; then attendi_mcp; fi
      echo "Installata la versione $APP_VERSION."
      # Pulizia: solo le immagini di questo progetto, tenendo l'attuale e la precedente.
      docker image ls gestione-contratti --format '{{.Tag}}' | grep -vxF -e "$APP_VERSION" -e locale \
        | tail -n +2 | sed 's/^/gestione-contratti:/' | xargs -r docker image rm >/dev/null 2>&1 || true
      return 0
    fi
    echo -n "."
    sleep 2
  done
  echo
  compose ps
  compose logs --tail 50 web
  errore "l'applicazione non risponde. Vedi RUNBOOK §7 (rollback)."
}

main "$@"; exit $?
