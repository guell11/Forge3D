#!/usr/bin/env bash
set -euo pipefail

PID_FILE="${1:?pid file required}"
EXPECTED_BIN="${2:?expected binary required}"

[[ -f "$PID_FILE" ]] || exit 0
PID_VALUE="$(python3 -c 'import json,sys; print(int(json.load(open(sys.argv[1], encoding="utf-8"))["pid"]))' "$PID_FILE")"
RECORDED_BIN="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["expected_bin"])' "$PID_FILE")"
[[ "$(readlink -f "$EXPECTED_BIN")" == "$(readlink -f "$RECORDED_BIN")" ]] || { echo 'TRELLIS_RELEASE_FAILED: PID file belongs to another executable.' >&2; exit 2; }
if [[ ! -d "/proc/$PID_VALUE" ]]; then rm -f "$PID_FILE"; exit 0; fi
[[ "$(readlink -f "/proc/$PID_VALUE/exe")" == "$(readlink -f "$EXPECTED_BIN")" ]] || { echo 'TRELLIS_RELEASE_FAILED: managed PID does not match TRELLIS executable.' >&2; exit 2; }
kill -TERM "$PID_VALUE"
for _ in {1..200}; do
  [[ ! -d "/proc/$PID_VALUE" ]] && { rm -f "$PID_FILE"; echo 'TRELLIS_RELEASED:managed process stopped'; exit 0; }
  sleep 0.1
done
echo 'TRELLIS_RELEASE_FAILED: process did not stop within 20 seconds.' >&2
exit 2
