#!/bin/bash
# Preparazione delle sessioni cloud di Claude Code. Fuori dal cloud non fa nulla.
if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
  exit 0
fi

# PostgreSQL è preinstallato ma spento nelle VM cloud.
service postgresql start >/dev/null 2>&1 || true
for i in 1 2 3 4 5; do
  pg_isready -q && break
  sleep 1
done

# Utente e database di sviluppo/test (idempotente).
su postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='contratti'\" | grep -q 1 || psql -c \"CREATE ROLE contratti LOGIN SUPERUSER PASSWORD 'contratti'\"" >/dev/null 2>&1 || true
su postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='contratti'\" | grep -q 1 || createdb -O contratti contratti" >/dev/null 2>&1 || true

# Dipendenze Python, solo se il progetto è già stato inizializzato.
if [ -f "$CLAUDE_PROJECT_DIR/pyproject.toml" ]; then
  cd "$CLAUDE_PROJECT_DIR" && uv sync --quiet || true
fi
exit 0
