#!/bin/bash
# Backup del database: pg_dump in formato custom, verificato, con rotazione.
#
# Dal server:   /appdata/gestione-contratti/app/deploy/backup.sh [etichetta]
# (si esegue dentro il container "backup" dello stack, che ha pg_dump della stessa versione
# del server PostgreSQL). Il container lo lancia da solo ogni giorno (backup_pianificato.sh).
#
# File: $APP_DIR/backup/AAAA.MM.GG_HHMM_contratti[_etichetta].dump
# Rotazione: si cancellano i dump più vecchi di BACKUP_GIORNI (default 14). Lo storico lungo
# lo dà il backup della VM, che copre anche questa cartella.
set -euo pipefail

if [ "${BACKUP_NEL_CONTAINER:-}" != "1" ]; then
  cd "$(dirname "$0")"
  # shellcheck source=deploy/comune.sh
  source ./comune.sh
  compose exec -T backup bash /scripts/backup.sh "$@"
  exit
fi

etichetta="${1:-}"
nome="$(date +%Y.%m.%d_%H%M)_contratti${etichetta:+_$etichetta}.dump"
tmp="/backup/.${nome}.parziale"
export PGPASSWORD="$POSTGRES_PASSWORD"

pg_dump --host="${PGHOST:-db}" --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" \
  --format=custom --no-owner --file="$tmp"
# Un dump illeggibile va scoperto oggi, non il giorno del ripristino.
pg_restore --list "$tmp" >/dev/null
mv "$tmp" "/backup/$nome"
echo "Backup completato: $nome ($(du -h "/backup/$nome" | cut -f1))"

giorni="${BACKUP_GIORNI:-14}"
find /backup/ -maxdepth 1 -name '*_contratti*.dump' -mtime +"$giorni" -print -delete \
  | sed 's/^/Rimosso per rotazione: /'
