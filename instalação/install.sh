#!/usr/bin/env bash
set -euo pipefail

# Forge3D Linux base installer. It uses the same real trellis.cpp GGUF model
# directories as Windows and keeps optional UltraShape unsupported here because
# this release validates the native Windows worker path only.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_ROOT="$PROJECT_ROOT/runtime"
RUNTIME_DIR="$RUNTIME_ROOT/trellis"
MODELS_ROOT="$PROJECT_ROOT/models/trellis2-gguf"
DOWNLOADS_DIR="$RUNTIME_ROOT/downloads"
LOG_DIR="$PROJECT_ROOT/logs/install"
mkdir -p "$RUNTIME_ROOT" "$DOWNLOADS_DIR" "$LOG_DIR"
LOG_FILE="$LOG_DIR/install-$(date +%Y%m%d-%H%M%S).log"
PROFILE=""; SKIP_MODELS=0; SKIP_ENGINE=0; SKIP_FRONTEND=0; INSTALL_BLENDER=0; REPAIR=0

log() { printf '%s [%s] %s\n' "$(date '+%F %T')" "$1" "$2" | tee -a "$LOG_FILE"; }
info() { log INFO "$*"; }
warn() { log WARN "$*" >&2; }
die() { log ERROR "$*" >&2; exit 1; }
usage() { cat <<'EOF'
Uso: bash instalação/install.sh [--profile 6gb|8gb|12gb|16gb] [--skip-models] [--skip-engine] [--skip-frontend] [--install-blender] [--repair]
UltraShape é experimental e suportado pelo instalador Windows separado.
EOF
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="${2:-}"; shift 2 ;;
    --skip-models) SKIP_MODELS=1; shift ;;
    --skip-engine) SKIP_ENGINE=1; shift ;;
    --skip-frontend) SKIP_FRONTEND=1; shift ;;
    --install-blender) INSTALL_BLENDER=1; shift ;;
    --repair) REPAIR=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 1 ;;
  esac
done
if [[ -z "$PROFILE" && -f "$RUNTIME_ROOT/engine-profile.json" ]]; then
  PROFILE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["profile"])' "$RUNTIME_ROOT/engine-profile.json" 2>/dev/null || true)"
fi
PROFILE="${PROFILE:-8gb}"
case "$PROFILE" in
  6gb) DEFAULT_QUANT=q4; QUANTS=(q4); RESOLUTION=512; ATLAS=1024; FACES=150000; TIERS='[{"id":"balanced","label":"Equilibrado","resolution":512,"atlas":1024,"texture_resolution":1024,"quant":"q4","description":"Q4, geometria 512, atlas 1K e PBR 1K."}]' ;;
  8gb) DEFAULT_QUANT=q4; QUANTS=(q4); RESOLUTION=512; ATLAS=1024; FACES=150000; TIERS='[{"id":"balanced","label":"Equilibrado","resolution":512,"atlas":1024,"texture_resolution":1024,"quant":"q4","description":"Q4, geometria 512, atlas 1K e PBR 1K."}]' ;;
  12gb) DEFAULT_QUANT=q4; QUANTS=(q4 q8); RESOLUTION=1024; ATLAS=2048; FACES=200000; TIERS='[{"id":"balanced","label":"Equilibrado","resolution":512,"atlas":2048,"texture_resolution":1024,"quant":"q4","description":"Q4, geometria 512, atlas 2K e PBR 1K."},{"id":"detailed","label":"Detalhado","resolution":1024,"atlas":2048,"texture_resolution":1024,"quant":"q8","description":"Q8, geometria 1024, atlas 2K e PBR 1K; experimental."}]' ;;
  16gb) DEFAULT_QUANT=q4; QUANTS=(q4 q8); RESOLUTION=1536; ATLAS=2048; FACES=300000; TIERS='[{"id":"balanced","label":"Equilibrado","resolution":512,"atlas":2048,"texture_resolution":1024,"quant":"q4","description":"Q4, geometria 512, atlas 2K e PBR 1K."},{"id":"detailed","label":"Detalhado","resolution":1024,"atlas":2048,"texture_resolution":1024,"quant":"q8","description":"Q8, geometria 1024, atlas 2K e PBR 1K."},{"id":"maximum","label":"Máximo","resolution":1536,"atlas":2048,"texture_resolution":1024,"quant":"q8","description":"Q8, geometria 1536, atlas 2K e PBR 1K; experimental."}]' ;;
  *) die "Perfil inválido: $PROFILE" ;;
esac
MODELS=(birefnet.gguf dinov3.gguf ss_flow.gguf ss_dec.gguf shape_flow_512.gguf shape_flow_1024.gguf shape_dec.gguf tex_flow_512.gguf tex_flow_1024.gguf tex_dec.gguf)

require() { command -v "$1" >/dev/null 2>&1 || die "Comando obrigatório não encontrado: $1"; }
download() {
  local url="$1" final="$2" minimum="${3:-1024}" sha="${4:-}" part="$2.part"
  if [[ -f "$final" && $(wc -c <"$final") -ge "$minimum" ]]; then
    if [[ -z "$sha" || "$(sha256sum "$final" | awk '{print $1}')" == "$sha" ]]; then info "Já existe: $(basename "$final")"; return; fi
    rm -f -- "$final"
  fi
  mkdir -p "$(dirname "$final")"
  info "Baixando com retomada: $(basename "$final")"
  curl -fL --retry 4 --retry-delay 2 -C - -o "$part" "$url" 2>&1 | tee -a "$LOG_FILE"
  [[ -f "$part" && $(wc -c <"$part") -ge "$minimum" ]] || die "Download incompleto: $part"
  if [[ -n "$sha" && "$(sha256sum "$part" | awk '{print $1}')" != "$sha" ]]; then die "Checksum SHA-256 inválido: $(basename "$final")"; fi
  mv -f -- "$part" "$final"
}
test_models() { local dir="$1"; for model in "${MODELS[@]}"; do [[ -f "$dir/$model" && $(wc -c <"$dir/$model") -ge 1048576 ]] || die "Peso GGUF ausente/incompleto: $dir/$model"; done; }
install_blender() {
  local version=4.5.12 archive="blender-$version-linux-x64.tar.xz" target="$RUNTIME_ROOT/blender/blender-$version-linux-x64" exe="$target/blender"
  download "https://download.blender.org/release/Blender4.5/$archive" "$DOWNLOADS_DIR/$archive" 100000000 '95e3a2dfedba3bd32ca54fc355eac6b15a11986954ccb02815a07535d0120a25'
  if [[ ! -x "$exe" ]]; then mkdir -p "$RUNTIME_ROOT/blender"; tar -C "$RUNTIME_ROOT/blender" -xf "$DOWNLOADS_DIR/$archive"; fi
  [[ -x "$exe" ]] || { warn 'Blender portátil não foi encontrado após extração.'; return 1; }
  "$exe" --background --version 2>&1 | tee -a "$LOG_FILE" || return 1
  local calibration="$RUNTIME_ROOT/blender-calibration" source="$RUNTIME_ROOT/blender-calibration/source.glb" output="$RUNTIME_ROOT/blender-calibration/transform.glb" parameters="$RUNTIME_ROOT/blender-calibration/parameters.json"
  mkdir -p "$calibration"
  "$PYTHON" -c "import sys; sys.path.insert(0,r'$PROJECT_ROOT/backend'); from app.adapters.demo import _cube_glb; open(r'$source','wb').write(_cube_glb())" || return 1
  printf '%s' '{"kind":"transform","transform":{"translation":[0,0,0],"rotation_degrees":[0,0,0],"scale":[1,1,1]}}' > "$parameters"
  rm -f -- "$output"
  "$exe" --background --factory-startup --python "$PROJECT_ROOT/scripts/blender_worker.py" -- transform --input "$source" --output "$output" --parameters "$parameters" 2>&1 | tee -a "$LOG_FILE" || return 1
  [[ -f "$output" && $(wc -c <"$output") -ge 20 && "$(head -c 4 "$output")" == glTF ]] || { warn 'Worker Blender não produziu GLB válido na calibração.'; return 1; }
  BLENDER_ENABLED=1; BLENDER_EXECUTABLE="$exe"; BLENDER_DETAIL='Blender portátil e worker passaram em uma operação GLB real.'
}

require python3; require curl; require tar
python3 -c 'import sys; assert sys.version_info >= (3,10),sys.version' || die 'Python 3.10+ é obrigatório.'
if [[ "$REPAIR" == 1 ]]; then info 'Modo de reparo: arquivos válidos serão preservados e .part retomados.'; fi
PYTHON="$PROJECT_ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  info 'Criando ambiente virtual Python isolado.'
  env -u PYTHONPATH -u PYTHONHOME PYTHONNOUSERSITE=1 python3 -I -m venv --without-pip "$PROJECT_ROOT/.venv" || die 'Não foi possível criar o venv; confira python3-venv.'
fi
# Kaggle sometimes exposes sitecustomize/PYTHONPATH from the host image and
# creates a valid venv without pip. Recover in place; never erase models/jobs.
venv_python() { env -u PYTHONPATH -u PYTHONHOME PYTHONNOUSERSITE=1 "$PYTHON" -I "$@"; }
if ! venv_python -m pip --version >/dev/null 2>&1; then
  warn 'pip ausente no venv; instalando pelo bootstrap oficial HTTPS sem executar ensurepip.'
  download 'https://bootstrap.pypa.io/get-pip.py' "$DOWNLOADS_DIR/get-pip.py" 100000
  venv_python "$DOWNLOADS_DIR/get-pip.py" >>"$LOG_FILE" 2>&1 || die 'Bootstrap pip falhou; consulte o log de instalação.'
fi
venv_python -m pip --version >/dev/null 2>&1 || die 'pip não ficou disponível no venv.'
venv_python -m pip install --upgrade pip 2>&1 | tee -a "$LOG_FILE"
venv_python -m pip install -r "$PROJECT_ROOT/backend/requirements.txt" 2>&1 | tee -a "$LOG_FILE"
venv_python -c 'import fastapi,uvicorn; print("API_IMPORT_OK")' 2>&1 | tee -a "$LOG_FILE"
if [[ "$SKIP_FRONTEND" == 0 ]]; then require npm; (cd "$PROJECT_ROOT/frontend" && npm install) 2>&1 | tee -a "$LOG_FILE"; fi

SERVER_BIN="$RUNTIME_DIR/trellis-server"
CLI_BIN="$RUNTIME_DIR/trellis-cli"
MODELS_DIR="$MODELS_ROOT/$DEFAULT_QUANT"
SERVER_PORT=8091
if [[ "$SKIP_ENGINE" == 0 ]]; then
  BACKEND=vulkan
  if command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then BACKEND=cuda; fi
  BUNDLE="trellis-$BACKEND-linux-x64.tar.gz"
  if [[ ! -x "$SERVER_BIN" || ! -x "$CLI_BIN" ]]; then download "https://github.com/pwilkin/trellis.cpp/releases/latest/download/$BUNDLE" "$DOWNLOADS_DIR/$BUNDLE" 1048576; mkdir -p "$RUNTIME_DIR"; tar -C "$RUNTIME_DIR" -xzf "$DOWNLOADS_DIR/$BUNDLE"; chmod +x "$SERVER_BIN" "$CLI_BIN" || true; fi
  [[ -x "$SERVER_BIN" && -x "$CLI_BIN" ]] || die 'Bundle trellis.cpp sem trellis-cli obrigatório.'
  if [[ "$SKIP_MODELS" == 0 ]]; then
    for quant in "${QUANTS[@]}"; do for model in "${MODELS[@]}"; do download "https://huggingface.co/ilintar/trellis2-gguf/resolve/main/$quant/$model" "$MODELS_ROOT/$quant/$model" 1048576; done; done
  fi
fi
[[ -x "$SERVER_BIN" ]] || die 'Runtime TRELLIS ausente.'
[[ -x "$CLI_BIN" ]] || die 'trellis-cli obrigatório ausente.'
test_models "$MODELS_DIR"
"$CLI_BIN" --help 2>&1 | tee -a "$LOG_FILE" || die 'Preflight trellis-cli --help falhou.'

BLENDER_ENABLED=0; BLENDER_EXECUTABLE=''; BLENDER_DETAIL='Não solicitado; capability indisponível.'
if [[ "$INSTALL_BLENDER" == 1 ]]; then install_blender || warn 'Blender opcional indisponível; o perfil base continua válido.'; fi
python3 - "$RUNTIME_ROOT/engine-profile.json" "$PROFILE" "$LOG_FILE" "$DEFAULT_QUANT" "$RESOLUTION" "$ATLAS" "$FACES" "$SERVER_PORT" "$TIERS" "${QUANTS[*]}" "$BLENDER_ENABLED" "$BLENDER_EXECUTABLE" "$BLENDER_DETAIL" <<'PY'
import datetime,json,pathlib,sys
path,profile,log,default,res,atlas,faces,port,tiers,quants,blender_enabled,blender_exe,blender_detail=sys.argv[1:]
payload={"schema_version":2,"profile":profile,"generated_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"install_log":log,"trellis":{"runtime":"trellis.cpp","model_sets":quants.split(),"default_quant":default,"resolution":int(res),"atlas":int(atlas),"face_target":int(faces),"server_port":int(port),"qualities":json.loads(tiers)},"ultrashape":{"requested":False,"enabled":False,"available":False,"mode":"experimental","detail":"Windows-native experimental installer required."},"blender":{"requested":blender_enabled=='1',"enabled":blender_enabled=='1',"available":blender_enabled=='1',"version":"4.5.12","executable":blender_exe,"detail":blender_detail}}
pathlib.Path(path).write_text(json.dumps(payload,indent=2),encoding="utf-8")
PY
write_env() { printf '%s=%q\n' "$1" "$2"; }
{
  printf '%s\n' '# Gerado pelo instalador Forge3D. Não coloque tokens aqui.'
  write_env ENGINE_PROFILE "$PROFILE"
  write_env ENGINE_PROFILE_PATH "$RUNTIME_ROOT/engine-profile.json"
  write_env TRELLIS_SERVER_URL "http://127.0.0.1:$SERVER_PORT"
  write_env TRELLIS_SERVER_PORT "$SERVER_PORT"
  write_env TRELLIS_SERVER_BIN "$SERVER_BIN"
  write_env TRELLIS_MODELS_DIR "$MODELS_DIR"
  write_env TRELLIS_DEFAULT_RESOLUTION "$RESOLUTION"
  write_env TRELLIS_DEFAULT_ATLAS "$ATLAS"
  write_env ENGINE_MODE trellis_cli
  write_env TRELLIS_CLI_BIN "$CLI_BIN"
  write_env TRELLIS_CLI_MODELS_DIR "$MODELS_DIR"
  write_env TRELLIS_AUTOSTART 0
  write_env TRELLIS_MANAGED_PID_FILE "$RUNTIME_ROOT/trellis-server.pid.json"
  write_env TRELLIS_RELEASE_SCRIPT "$PROJECT_ROOT/scripts/release-trellis.sh"
  write_env ULTRASHAPE_ENABLED 0
  write_env BLENDER_ENABLED "$BLENDER_ENABLED"
  write_env BLENDER_EXECUTABLE "$BLENDER_EXECUTABLE"
  write_env BLENDER_VERSION 4.5.12
  write_env MESH_OPERATIONS_PYTHON "$BLENDER_EXECUTABLE"
  write_env MESH_OPERATIONS_WORKER "$PROJECT_ROOT/scripts/blender_worker.py"
} >"$RUNTIME_ROOT/engine.env"
chmod +x "$PROJECT_ROOT/run.sh" "$PROJECT_ROOT/scripts/run.sh" || true
info "Instalação base concluída. Log: $LOG_FILE"
echo "Execute: $PROJECT_ROOT/run.sh"
