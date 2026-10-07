#!/bin/bash
# Verifica dall'esterno dell'host pubblico del connettore MCP (SPEC_MCP §2.2, punto 7).
#
#   deploy/verifica_mcp.sh https://mcp-contratti.esempio.it ammesso   # da un IP in allowlist
#   deploy/verifica_mcp.sh https://mcp-contratti.esempio.it esterno   # da un IP fuori allowlist
#
# «ammesso» (rete interna o rete di Anthropic): certificato valido, metadati 200, /mcp senza
# token 401 con resource_metadata, ogni altro percorso 404.
# «esterno» (es. una connessione mobile): nessuna risposta (connessione scartata dal firewall
# perimetrale) oppure 403 dall'Access List sugli endpoint del connettore; gli altri percorsi
# anche 404 (dipende dall'ordine delle regole nel proxy). Mai una risposta dell'app.
# Esce con 1 se un controllo fallisce. Non usa token né credenziali.
# CURL_OPZIONI: opzioni in più per curl (in CI: --cacert e --resolve verso il proxy di prova).
set -uo pipefail
read -ra EXTRA <<<"${CURL_OPZIONI:-}"

# curl con le opzioni in più. ${EXTRA[@]+...}: con bash 3.2 (macOS) e set -u un array vuoto
# espanso con "${EXTRA[@]}" è «unbound variable».
richiesta() {
  curl ${EXTRA[@]+"${EXTRA[@]}"} "$@"
}

[ $# -eq 2 ] || { echo "uso: $0 <url pubblico> ammesso|esterno" >&2; exit 2; }
BASE="${1%/}"
MODO="$2"
FALLITI=0

codice() {  # metodo percorso → codice HTTP (000 se la connessione fallisce)
  richiesta -sS -o /dev/null -w '%{http_code}' --max-time 10 -X "$1" \
    -H 'Content-Type: application/json' --data-binary "${3:-}" "$BASE$2" 2>/dev/null || true
}

verifica() {  # descrizione atteso ottenuto
  if [ "$2" = "$3" ]; then
    echo "ok    $1 ($3)"
  else
    echo "ERRORE $1: atteso $2, ottenuto $3"
    FALLITI=1
  fi
}

PUBBLICI=(
  "GET /.well-known/oauth-protected-resource"
  "GET /.well-known/oauth-protected-resource/mcp"
  "GET /.well-known/oauth-authorization-server"
)
NASCOSTI=(/ /admin/ /accounts/login/ /oauth/authorize/ /healthz /cruscotto/ /report/budget/ /static/css/app.css)

bloccato() {  # descrizione codice ammessi... → ok se il codice è tra gli ammessi o 000
  local descrizione="$1" c="$2"
  shift 2
  if [ "$c" = "000" ]; then
    echo "ok    $descrizione (nessuna risposta: bloccato dal firewall)"
    return
  fi
  for a in "$@"; do
    if [ "$c" = "$a" ]; then
      echo "ok    $descrizione ($c)"
      return
    fi
  done
  echo "ERRORE $descrizione: atteso $* o nessuna risposta, ottenuto $c"
  FALLITI=1
}

case "$MODO" in
  esterno)
    for voce in "${PUBBLICI[@]}"; do
      read -r metodo percorso <<<"$voce"
      bloccato "$metodo $percorso" "$(codice "$metodo" "$percorso")" 403
    done
    bloccato "POST /mcp" "$(codice POST /mcp '{}')" 403
    bloccato "POST /oauth/token/" "$(codice POST /oauth/token/ '')" 403
    for p in "${NASCOSTI[@]}"; do
      bloccato "GET $p" "$(codice GET "$p")" 403 404
    done
    ;;
  ammesso)
    # Senza -k: il certificato deve essere valido per una CA pubblica.
    if richiesta -sS -o /dev/null --max-time 10 "$BASE/.well-known/oauth-protected-resource"; then
      echo "ok    certificato TLS valido"
    else
      echo "ERRORE certificato TLS non valido o host non raggiungibile"
      FALLITI=1
    fi
    for voce in "${PUBBLICI[@]}"; do
      read -r metodo percorso <<<"$voce"
      verifica "$metodo $percorso" 200 "$(codice "$metodo" "$percorso")"
    done
    risorsa=$(richiesta -sS --max-time 10 "$BASE/.well-known/oauth-protected-resource" || true)
    case "$risorsa" in
      *"\"resource\": \"$BASE/mcp\""* | *"\"resource\":\"$BASE/mcp\""*) echo "ok    resource = $BASE/mcp" ;;
      *) echo "ERRORE resource diversa da $BASE/mcp: $risorsa"; FALLITI=1 ;;
    esac
    intestazioni=$(richiesta -sS -o /dev/null -D - --max-time 10 -X POST \
      -H 'Content-Type: application/json' --data '{}' "$BASE/mcp" || true)
    verifica "POST /mcp senza token" 401 "$(awk 'NR==1 {print $2}' <<<"$intestazioni")"
    if grep -qi '^www-authenticate: Bearer .*resource_metadata=' <<<"$intestazioni"; then
      echo "ok    WWW-Authenticate con resource_metadata"
    else
      echo "ERRORE WWW-Authenticate senza resource_metadata"
      FALLITI=1
    fi
    verifica "GET /mcp" 405 "$(codice GET /mcp)"
    token=$(codice POST /oauth/token/ '')
    case "$token" in
      400 | 401) echo "ok    POST /oauth/token/ senza dati ($token)" ;;
      *) echo "ERRORE POST /oauth/token/ senza dati: atteso 400 o 401, ottenuto $token"; FALLITI=1 ;;
    esac
    for p in "${NASCOSTI[@]}"; do verifica "GET $p" 404 "$(codice GET "$p")"; done
    ;;
  *)
    echo "modo sconosciuto: $MODO (ammesso|esterno)" >&2
    exit 2
    ;;
esac

if [ "$FALLITI" -ne 0 ]; then
  echo "Verifica NON superata."
  exit 1
fi
echo "Verifica superata."
