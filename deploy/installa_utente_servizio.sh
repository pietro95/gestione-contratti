#!/bin/bash
# Installazione una tantum dell'utente di servizio e del comando gestione-contratti
# (RUNBOOK §7.1). Idempotente: si può rilanciare.
#
#   sudo /appdata/gestione-contratti/app/deploy/installa_utente_servizio.sh [--chiave <file>]
#
# Passi:
#   1. crea l'utente di sistema gestcontratti (senza login, nel gruppo docker);
#   2. gli copia la deploy key di GitHub (cercata in /root/.ssh e /home/*/.ssh, oppure --chiave);
#   3. gli assegna app/, config/ e log/ (postgres/, import/, allegati/, static/ e backup/ non
#      si toccano: appartengono agli utenti interni dei container);
#   4. verifica che possa leggere il .env e scaricare da GitHub;
#   5. collega /usr/local/bin/gestione-contratti a deploy/gestione-contratti.sh.
set -euo pipefail

UTENTE=gestcontratti
HOME_UTENTE=/var/lib/$UTENTE
NOME_CHIAVE=gestione-contratti_deploy
ALIAS_SSH=github-gestione-contratti
COMANDO=/usr/local/bin/gestione-contratti

errore() {
  echo "ERRORE: $*" >&2
  exit 1
}

script="$(readlink -f "${BASH_SOURCE[0]}")"
DEPLOY_DIR="$(dirname "$script")"
SRC="$(dirname "$DEPLOY_DIR")"
APP_DIR="$(dirname "$SRC")"

[ "$EUID" -eq 0 ] || errore "lanciare con sudo: sudo $script"
chiave=""
if [ "${1:-}" = "--chiave" ]; then
  chiave="${2:-}"
  [ -f "$chiave" ] || errore "chiave non trovata: $chiave"
fi
getent group docker >/dev/null || errore "manca il gruppo docker."
[ -f "$APP_DIR/config/.env" ] || errore "manca $APP_DIR/config/.env."

# --- 1. Utente ---------------------------------------------------------------------------
# UID scelto a mano: 999 e 1000 sono gli UID interni dei container (postgres e app); un utente
# dell'host con lo stesso UID diventerebbe proprietario dei loro dati.
if ! getent passwd "$UTENTE" >/dev/null; then
  uid=990
  while getent passwd "$uid" >/dev/null || getent group "$uid" >/dev/null; do
    uid=$((uid - 1))
    [ "$uid" -gt 100 ] || errore "nessun UID di sistema libero."
  done
  echo "==> Creazione dell'utente $UTENTE (UID $uid)"
  groupadd --system --gid "$uid" "$UTENTE"
  useradd --system --uid "$uid" --gid "$UTENTE" --home-dir "$HOME_UTENTE" --create-home \
    --shell /usr/sbin/nologin --comment "Servizio gestione-contratti" "$UTENTE"
else
  echo "==> Utente $UTENTE già presente"
fi
uid="$(id -u "$UTENTE")"
case "$uid" in 999 | 1000) errore "l'utente $UTENTE ha UID $uid, che è un UID dei container: rimuoverlo e rilanciare." ;; esac
usermod -aG docker "$UTENTE"
HOME_UTENTE="$(getent passwd "$UTENTE" | cut -d: -f6)"

# --- 2. Deploy key -----------------------------------------------------------------------
remoto="$(git -C "$SRC" config --get remote.origin.url || true)"
echo "==> Repository remoto: $remoto"
ssh_dir="$HOME_UTENTE/.ssh"
install -d -m 700 -o "$UTENTE" -g "$UTENTE" "$ssh_dir"
if [ -f "$ssh_dir/$NOME_CHIAVE" ] && [ -z "$chiave" ]; then
  echo "==> Deploy key già presente"
else
  if [ -z "$chiave" ]; then
    trovate=()
    for f in /root/.ssh/$NOME_CHIAVE /home/*/.ssh/$NOME_CHIAVE; do
      [ -f "$f" ] && trovate+=("$f")
    done
    [ "${#trovate[@]}" -gt 0 ] || errore "deploy key non trovata in /root/.ssh né in /home/*/.ssh: indicarla con --chiave <file>."
    [ "${#trovate[@]}" -eq 1 ] || errore "più deploy key trovate (${trovate[*]}): sceglierne una con --chiave <file>."
    chiave="${trovate[0]}"
  fi
  echo "==> Copia della deploy key da $chiave"
  install -m 600 -o "$UTENTE" -g "$UTENTE" "$chiave" "$ssh_dir/$NOME_CHIAVE"
  [ -f "$chiave.pub" ] && install -m 644 -o "$UTENTE" -g "$UTENTE" "$chiave.pub" "$ssh_dir/$NOME_CHIAVE.pub"
  # Chiave fidata di github.com dal known_hosts dell'utente da cui viene la chiave.
  known_origine="$(dirname "$chiave")/known_hosts"
  if [ -f "$known_origine" ]; then
    ssh-keygen -F github.com -f "$known_origine" | grep -v '^#' >"$ssh_dir/known_hosts" || true
    chown "$UTENTE:$UTENTE" "$ssh_dir/known_hosts"
    chmod 644 "$ssh_dir/known_hosts"
  fi
fi
[ -s "$ssh_dir/known_hosts" ] \
  || errore "manca la chiave di github.com in $ssh_dir/known_hosts: lanciare ssh-keyscan github.com, verificare l'impronta con quella pubblicata da GitHub e scriverla nel file."
cat >"$ssh_dir/config" <<FINE
Host $ALIAS_SSH
  HostName github.com
  User git
  IdentityFile $ssh_dir/$NOME_CHIAVE
  IdentitiesOnly yes
FINE
chown "$UTENTE:$UTENTE" "$ssh_dir/config"
chmod 600 "$ssh_dir/config"

# --- 3. Proprietà ------------------------------------------------------------------------
echo "==> Proprietà di app/, config/ e log/ a $UTENTE"
mkdir -p "$APP_DIR/log"
chown -R "$UTENTE:$UTENTE" "$SRC" "$APP_DIR/config" "$APP_DIR/log"
chmod 600 "$APP_DIR/config/.env"

# --- 4. Verifiche ------------------------------------------------------------------------
come_servizio() {
  runuser -u "$UTENTE" -- env -i HOME="$HOME_UTENTE" PATH=/usr/local/bin:/usr/bin:/bin "$@"
}
echo "==> Verifica: lettura del .env"
come_servizio test -r "$APP_DIR/config/.env" || errore "$UTENTE non legge $APP_DIR/config/.env."
echo "==> Verifica: accesso a Docker"
come_servizio docker ps --quiet >/dev/null || errore "$UTENTE non accede a Docker."
echo "==> Verifica: accesso a GitHub"
come_servizio git -C "$SRC" ls-remote --tags origin >/dev/null \
  || errore "$UTENTE non scarica da GitHub: controllare la deploy key e $ssh_dir/config."

# --- 5. Comando --------------------------------------------------------------------------
ln -sfn "$DEPLOY_DIR/gestione-contratti.sh" "$COMANDO"
echo
echo "Installazione completata. Da ora, con il proprio utente:"
echo "  gestione-contratti stato"
echo "  gestione-contratti aggiorna latest"
