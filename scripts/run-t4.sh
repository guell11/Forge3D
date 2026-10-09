#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
MODEL_DIR="$PROJECT_ROOT/models/trellis2-gguf/q4"
RUNTIME_DIR="$PROJECT_ROOT/runtime/trellis"

if [[ -f "$PROJECT_ROOT/runtime/engine.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/runtime/engine.env"
  set +a
fi

fail() { printf 'Forge3D T4: %s\n' "$*" >&2; exit 1; }

command -v nvidia-smi >/dev/null 2>&1 || fail 'nvidia-smi ausente; escolha GPU T4 no runtime Linux.'
GPU_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1 | xargs || true)"
[[ "$GPU_NAME" == *T4* ]] || fail "GPU 0 não parece ser uma T4 (detectada: ${GPU_NAME:-indisponível})."

[[ -x "$PYTHON" ]] || fail 'Python do projeto ausente; execute bash instalação/install.sh --profile 8gb.'
[[ -x "$RUNTIME_DIR/trellis-cli" ]] || fail 'trellis-cli ausente; execute o instalador Linux com perfil 8gb.'
[[ -d "$MODEL_DIR" ]] || fail 'Pesos GGUF Q4 ausentes; execute o instalador Linux com perfil 8gb.'
for model in birefnet.gguf dinov3.gguf ss_flow.gguf ss_dec.gguf shape_flow_512.gguf shape_flow_1024.gguf shape_dec.gguf tex_flow_512.gguf tex_flow_1024.gguf tex_dec.gguf; do
  [[ -s "$MODEL_DIR/$model" ]] || fail "Peso GGUF Q4 ausente: $MODEL_DIR/$model"
done
[[ -f "$PROJECT_ROOT/frontend/dist/index.html" ]] || {
  command -v npm >/dev/null 2>&1 || fail 'npm ausente; instale Node.js 20.19+ ou 22.12+ e tente novamente.'
  NODE_VERSION="$(node --version | sed 's/^v//')"
  NODE_MAJOR="${NODE_VERSION%%.*}"
  NODE_MINOR="$(printf '%s' "$NODE_VERSION" | cut -d. -f2)"
  if (( NODE_MAJOR < 20 || (NODE_MAJOR == 20 && NODE_MINOR < 19) || NODE_MAJOR == 21 || (NODE_MAJOR == 22 && NODE_MINOR < 12) )); then
    fail "Node.js 20.19+ ou 22.12+ obrigatório (detectado: v$NODE_VERSION)."
  fi
  (cd "$PROJECT_ROOT/frontend" && npm install --no-audit --no-fund && VITE_API_BASE_URL=/api npm run build)
}

if [[ -z "${FORGE3D_ACCESS_TOKEN:-}" || ${#FORGE3D_ACCESS_TOKEN} -lt 32 ]]; then
  fail 'Defina FORGE3D_ACCESS_TOKEN com pelo menos 32 caracteres antes de iniciar.'
fi

export CUDA_VISIBLE_DEVICES=0
export ENGINE_PROFILE=8gb
export TRELLIS_CLI_GPU_INDEX=0
export TRELLIS_CLI_REQUIRE_GPU=1
export TRELLIS_DEFAULT_RESOLUTION=512
export TRELLIS_DEFAULT_ATLAS=1024
export TRELLIS_AUTOSTART=0
export ULTRASHAPE_ENABLED=0
export TRELLIS_CLI_MODELS_DIR="$MODEL_DIR"
export TRELLIS_CLI_BIN="$RUNTIME_DIR/trellis-cli"
export TRELLIS_SERVER_BIN="$RUNTIME_DIR/trellis-server"
export ENGINE_PROFILE_PATH="$PROJECT_ROOT/runtime/engine-profile.json"
"$TRELLIS_CLI_BIN" --help >/dev/null || fail 'Preflight trellis-cli --help falhou.'

cd "$PROJECT_ROOT"
exec "$PYTHON" scripts/serve_remote.py --host 127.0.0.1 --port "${FORGE3D_PORT:-7860}"
