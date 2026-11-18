#!/bin/bash
# Comando unico per l'esercizio dell'app, lanciabile da qualsiasi utente con sudo.
# Installato come /usr/local/bin/gestione-contratti da installa_utente_servizio.sh.
#
#   gestione-contratti stato
#   gestione-contratti aggiorna latest            (ultimo tag vX.Y.Z, con conferma)
#   gestione-contratti aggiorna v2.19.2 [--si]
#   gestione-contratti backup [etichetta]
#   gestione-contratti manage <comando> [argomenti]
#   gestione-contratti ripristina <file.dump>
#   gestione-contratti log [servizio]
#
# Tre passi: l'utente lancia il comando → se serve si rilancia con sudo (chiede la password
# dell'utente) → da root scende subito all'utente di servizio, che esegue tutto il lavoro.
# Nessun file dell'app viene mai creato da root o da un utente personale: i permessi restano
# quelli dell'utente di servizio, chiunque lanci il comando.
set -euo pipefail

UTENTE_SERVIZIO=gestcontratti

# Tutto dentro main: bash legge la funzione per intero prima di eseguirla, quindi il checkout
# di una nuova versione (che riscrive questo file) non altera il comando in esecuzione.
main() {
  local script deploy_dir src app_dir
  script="$(readlink -f "${BASH_SOURCE[0]}")"
  deploy_dir="$(dirname "$script")"
  src="$(dirname "$deploy_dir")"
  app_dir="$(dirname "$src")"

  # --- 1. Utente personale: rilancio con sudo ----------------------------------------------
  if [ "$(id -un)" != "$UTENTE_SERVIZIO" ] && [ "$EUID" -ne 0 ]; then
    exec sudo -- "$script" "$@"
  fi

  # --- 2. Root: discesa all'utente di servizio ---------------------------------------------
  if [ "$EUID" -eq 0 ]; then
    local home_servizio protetta=0
    home_servizio="$(getent passwd "$UTENTE_SERVIZIO" | cut -d: -f6)"
    [ -n "$home_servizio" ] || {
      echo "ERRORE: manca l'utente $UTENTE_SERVIZIO. Lanciare una volta:" >&2
      echo "  sudo $deploy_dir/installa_utente_servizio.sh   (RUNBOOK §7.1)" >&2
      exit 1
    }
    if sessione_protetta; then protetta=1; fi
    exec runuser -u "$UTENTE_SERVIZIO" -- env -i \
      HOME="$home_servizio" USER="$UTENTE_SERVIZIO" LOGNAME="$UTENTE_SERVIZIO" \
      PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
      LANG="${LANG:-C.UTF-8}" TERM="${TERM:-dumb}" \
      GC_OPERATORE="${SUDO_USER:-root}" GC_SESSIONE_PROTETTA="$protetta" \
      bash "$script" "$@"
  fi

  # --- 3. Utente di servizio: il lavoro ----------------------------------------------------
  cd "$deploy_dir"
  local comando="${1:-aiuto}"
  if [ $# -gt 0 ]; then shift; fi
  case "$comando" in
    stato) stato ;;
    aggiorna) aggiorna "$src" "$app_dir" "$@" ;;
    backup) ./backup.sh "$@" ;;
    manage) ./manage.sh "$@" ;;
    ripristina) ./ripristina.sh "$@" ;;
    log)
      # shellcheck source=deploy/comune.sh
      source ./comune.sh
      compose logs --tail 100 --follow "$@"
      ;;
    aiuto | -h | --help) aiuto ;;
    *)
      echo "ERRORE: comando sconosciuto: $comando" >&2
      aiuto >&2
      exit 1
      ;;
  esac
}

aiuto() {
  cat <<'FINE'
uso: gestione-contratti <comando> [argomenti]

  stato                         versione installata e stato dei container
  aggiorna latest [--si]        installa l'ultimo tag vX.Y.Z (chiede conferma)
  aggiorna <tag> [--si]         installa un tag preciso (anche per il rollback)
  backup [etichetta]            dump del database e archivio degli allegati
  manage <comando> [argomenti]  comando di Django, es. manage import_fatture /import/x.xlsx --dry-run
  ripristina <file.dump>        SOSTITUISCE il database con un dump di backup/
  log [servizio]                ultimi log (web, db, backup, mcp, notifiche); Ctrl+C per uscire

Si lancia con il proprio utente (con o senza sudo): il lavoro lo esegue l'utente di servizio.
FINE
}

# Vero se il comando gira dentro tmux o screen: una disconnessione SSH non lo interrompe.
sessione_protetta() {
  local pid=$$ nome
  while [ "$pid" -gt 1 ]; do
    nome="$(cat "/proc/$pid/comm" 2>/dev/null || true)"
    case "$nome" in tmux* | screen* | SCREEN*) return 0 ;; esac
    pid="$(awk '/^PPid:/ {print $2}' "/proc/$pid/status" 2>/dev/null || echo 1)"
  done
  return 1
}

stato() {
  # shellcheck source=deploy/comune.sh
  source ./comune.sh
  echo "Versione installata: $APP_VERSION"
  compose ps
}

# Ultimo tag nel formato esatto vX.Y.Z: i tag malformati (es. v.2.5.0) non si scelgono mai.
ultimo_tag() {
  git -C "$1" tag --list 'v*' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -n 1
}

aggiorna() {
  local src="$1" app_dir="$2"
  shift 2
  local richiesta="${1:-}" conferma=false attuale versione log_dir log
  [ -n "$richiesta" ] || {
    echo "ERRORE: uso: gestione-contratti aggiorna latest|<tag> [--si]" >&2
    exit 1
  }
  if [ "${2:-}" = "--si" ]; then conferma=true; fi

  echo "==> Tag disponibili su GitHub"
  git -C "$src" fetch --tags --quiet origin
  if [ "$richiesta" = "latest" ]; then
    versione="$(ultimo_tag "$src")"
    [ -n "$versione" ] || { echo "ERRORE: nessun tag vX.Y.Z trovato." >&2; exit 1; }
  else
    versione="$richiesta"
    git -C "$src" rev-parse --quiet --verify "refs/tags/$versione" >/dev/null || {
      echo "ERRORE: il tag $versione non esiste. Ultimo disponibile: $(ultimo_tag "$src")" >&2
      exit 1
    }
  fi
  attuale="$(git -C "$src" describe --tags --always)"
  if [ "$attuale" = "$versione" ]; then
    echo "La versione $versione è già installata: nulla da fare."
    return 0
  fi

  echo "Versione installata: $attuale"
  echo "Versione da installare: $versione"
  if [ "${GC_SESSIONE_PROTETTA:-0}" != "1" ]; then
    echo "ATTENZIONE: non sei in tmux o screen. Se la connessione SSH cade a metà, il deploy si"
    echo "            interrompe. Per sicurezza: tmux, poi rilancia il comando."
  fi
  if ! $conferma; then
    local risposta
    read -r -p "Procedere? [s/N] " risposta
    case "$risposta" in s | S | si | SI | sì) ;; *) echo "Annullato."; return 0 ;; esac
  fi

  log_dir="$app_dir/log"
  mkdir -p "$log_dir"
  log="$log_dir/$(date +%Y.%m.%d_%H%M)_aggiorna_${versione//[^A-Za-z0-9.]/_}.log"
  {
    echo "Aggiornamento $attuale → $versione"
    echo "Lanciato da: ${GC_OPERATORE:-sconosciuto}, $(date '+%d/%m/%Y %H:%M:%S')"
  } | tee "$log"
  # Il deploy è sempre quello della versione installata: è lui che scarica la nuova.
  if "$src/deploy/deploy.sh" "$versione" 2>&1 | tee -a "$log"; then
    echo "Log: $log"
  else
    echo "Deploy non riuscito. Log: $log" >&2
    echo "Rollback: RUNBOOK §7 (gestione-contratti aggiorna $attuale)." >&2
    exit 1
  fi
}

main "$@"; exit $?
