#!/bin/bash
# Prova di ripristino senza toccare il database in uso (deploy/restore.md §1).
#
#   /appdata/gestione-contratti/app/deploy/verifica_ripristino.sh [file.dump]
#
# Ripristina il dump (default: il più recente) in un database temporaneo "verifica_ripristino",
# confronta il numero di righe delle tabelle principali con il database in uso, poi lo elimina.
# Se il dump è più vecchio dei dati attuali, differenze nei conteggi sono attese: lo script
# le mostra e termina con errore solo se il ripristino fallisce o il dump risulta vuoto.
set -euo pipefail

if [ "${BACKUP_NEL_CONTAINER:-}" != "1" ]; then
  cd "$(dirname "$0")"
  # shellcheck source=deploy/comune.sh
  source ./comune.sh
  dump="${1:-}"
  [ -z "$dump" ] || dump="/backup/$(basename "$dump")"
  compose exec -T backup bash -s -- "$dump" <verifica_ripristino.sh
  exit
fi

export PGPASSWORD="$POSTGRES_PASSWORD" PGUSER="$POSTGRES_USER" PGHOST="${PGHOST:-db}"
export PGOPTIONS="-c client_min_messages=warning"
dump="${1:-}"
if [ -z "$dump" ]; then
  dump="$(ls -1t /backup/*_contratti*.dump 2>/dev/null | head -n 1 || true)"
fi
[ -f "$dump" ] || { echo "ERRORE: nessun dump trovato in /backup." >&2; exit 1; }
echo "Dump: $(basename "$dump")"

verifica=verifica_ripristino
psql -q -d postgres -c "DROP DATABASE IF EXISTS $verifica" -c "CREATE DATABASE $verifica"
trap 'psql -q -d postgres -c "DROP DATABASE IF EXISTS $verifica"' EXIT
pg_restore --no-owner --no-acl --exit-on-error -d "$verifica" "$dump"

tabelle=(contratti_fornitore contratti_fabbisogno contratti_contratto contratti_vocecontratto
  contratti_rata contratti_proroga contratti_statopratica accounts_user django_migrations)
printf '%-28s %10s %10s\n' tabella "in uso" ripristino
totale=0
for t in "${tabelle[@]}"; do
  a=$(psql -tA -d "$POSTGRES_DB" -c "SELECT count(*) FROM $t")
  b=$(psql -tA -d "$verifica" -c "SELECT count(*) FROM $t")
  segno=""
  [ "$a" = "$b" ] || segno="  <-- diverso"
  printf '%-28s %10s %10s%s\n' "$t" "$a" "$b" "$segno"
  totale=$((totale + b))
done
migr=$(psql -tA -d "$verifica" -c "SELECT count(*) FROM django_migrations")
[ "$migr" -gt 0 ] || { echo "ERRORE: dump senza schema applicativo." >&2; exit 1; }
echo "Ripristino riuscito ($totale righe nelle tabelle controllate)."
