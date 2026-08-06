#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"

if [[ -f "$PROJECT_ROOT/runtime/engine.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/runtime/engine.env"
  set +a
fi

PYTHON="$PROJECT_ROOT/.venv/bin/python"
[[ -x "$PYTHON" ]] || { echo "Ambiente Python não encontrado. Execute primeiro um instalador em instalação/." >&2; exit 1; }
command -v npm >/dev/null || { echo "Node.js/NPM não encontrado. Instale Node.js LTS e execute novamente o instalador." >&2; exit 1; }

port_open() {
  local port="$1"
  (echo >"/dev/tcp/127.0.0.1/$port") >/dev/null 2>&1
}

wait_for_port() {
  local port="$1" seconds="${2:-30}" end=$((SECONDS + seconds))
  until port_open "$port"; do
    (( SECONDS >= end )) && return 1
    sleep 0.4
  done
}

BACKEND_PORT=8000
FRONTEND_PORT=5173
TRELLIS_SERVER_PORT="${TRELLIS_SERVER_PORT:-8091}"
TRELLIS_AUTOSTART="${TRELLIS_AUTOSTART:-0}" # CLI por job e o padrão; servidor fica só para compatibilidade.
TRELLIS_DEFAULT_RESOLUTION="${TRELLIS_DEFAULT_RESOLUTION:-512}"
TRELLIS_DEFAULT_ATLAS="${TRELLIS_DEFAULT_ATLAS:-1024}"
TRELLIS_MANAGED_PID_FILE="${TRELLIS_MANAGED_PID_FILE:-$PROJECT_ROOT/runtime/trellis-server.pid.json}"
STAMP="$(date +%Y%m%d-%H%M%S)"

if [[ "$TRELLIS_AUTOSTART" != "0" && -n "${TRELLIS_SERVER_BIN:-}" && -n "${TRELLIS_MODELS_DIR:-}" && -x "$TRELLIS_SERVER_BIN" && -d "$TRELLIS_MODELS_DIR" ]] && ! port_open "$TRELLIS_SERVER_PORT"; then
  nohup "$TRELLIS_SERVER_BIN" --models "$TRELLIS_MODELS_DIR" --port "$TRELLIS_SERVER_PORT" --res "$TRELLIS_DEFAULT_RESOLUTION" --atlas "$TRELLIS_DEFAULT_ATLAS" \
    >"$LOG_DIR/trellis-$STAMP.out.log" 2>"$LOG_DIR/trellis-$STAMP.err.log" &
  TRELLIS_PID=$!
  if wait_for_port "$TRELLIS_SERVER_PORT" 10; then
    python3 -c "import json,pathlib,datetime; pathlib.Path(r'$TRELLIS_MANAGED_PID_FILE').write_text(json.dumps({'pid':$TRELLIS_PID,'expected_bin':r'$TRELLIS_SERVER_BIN','started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}),encoding='utf-8')"
  else
    echo 'AVISO: servidor TRELLIS não respondeu; UltraShape não poderá confirmar a liberação de VRAM.' >&2
  fi
fi

if ! port_open "$BACKEND_PORT"; then
  (
    cd "$PROJECT_ROOT/backend"
    nohup "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" \
      >"$LOG_DIR/api-$STAMP.out.log" 2>"$LOG_DIR/api-$STAMP.err.log" &
  )
  wait_for_port "$BACKEND_PORT" 30 || { echo "A API não iniciou. Veja $LOG_DIR" >&2; exit 1; }
fi

if ! port_open "$FRONTEND_PORT"; then
  (
    cd "$PROJECT_ROOT/frontend"
    nohup npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" \
      >"$LOG_DIR/ui-$STAMP.out.log" 2>"$LOG_DIR/ui-$STAMP.err.log" &
  )
  wait_for_port "$FRONTEND_PORT" 45 || { echo "A interface não iniciou. Veja $LOG_DIR" >&2; exit 1; }
fi

URL="http://127.0.0.1:$FRONTEND_PORT"
echo "Engine 3D pronta em $URL"
if command -v xdg-open >/dev/null; then xdg-open "$URL" >/dev/null 2>&1 &
elif command -v open >/dev/null; then open "$URL"
fi
