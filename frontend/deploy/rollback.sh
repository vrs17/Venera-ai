#!/usr/bin/env bash
# deploy/rollback.sh — return :5173 to a KNOWN-GOOD state, run-as-ymamajonov.
#
# Two targets:
#   --to-vite      (DEFAULT, safe floor) Stop+remove the container, re-enable & start
#                  the vite --user service on :5173. vite predates the container.
#   --to-previous  Re-bind the PREVIOUS repo digest (recorded by cutover.sh in the
#                  state file) on :5173 via the systemd unit. Use when the new image
#                  is bad but the container path itself is fine. Re-pulls if pruned.
#
# Idempotent; health-gates the restored target on /healthz (backend-independent) and
# exits non-zero if it cannot be made healthy (so an operator/CI knows it is NOT good).

set -euo pipefail

CONTAINER_NAME="brb-frontend"
UNIT_NAME="container-brb-frontend"
VITE_UNIT="brb-frontend.service"
PORT=5173
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/brb-cutover"
STATE_FILE="${STATE_DIR}/state.env"
USER_UNIT_DIR="${HOME}/.config/systemd/user"
HEALTH_RETRIES=20
HEALTH_SLEEP=1
LOG_PREFIX="[rollback]"
MODE="to-vite"

log() { printf '%s %s\n' "$LOG_PREFIX" "$*" >&2; }
die() { printf '%s ERROR: %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --to-vite)     MODE="to-vite"; shift;;
    --to-previous) MODE="to-previous"; shift;;
    -h|--help)     sed -n '2,16p' "$0"; exit 0;;
    *) die "unknown arg: $1";;
  esac
done

[ "$(id -un)" = "ymamajonov" ] || die "must run as ymamajonov; current=$(id -un)"
command -v podman >/dev/null || die "podman not found on PATH"
: "${XDG_RUNTIME_DIR:?XDG_RUNTIME_DIR unset — run inside the ymamajonov user session}"

health_gate() {
  local i code
  for i in $(seq 1 "$HEALTH_RETRIES"); do
    code="$(curl -fsS -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/healthz" 2>/dev/null || true)"
    [ "$code" = "200" ] && { log "health OK on :${PORT} after ${i} try(ies)"; return 0; }
    sleep "$HEALTH_SLEEP"
  done
  log "health FAIL on :${PORT}: last code='${code:-none}'"
  return 1
}

stop_container() {
  log "stopping container path (unit + container) to free :${PORT}"
  systemctl --user stop    "${UNIT_NAME}.service" 2>/dev/null || true
  systemctl --user disable "${UNIT_NAME}.service" 2>/dev/null || true
  podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}

case "$MODE" in
  to-vite)
    stop_container
    log "re-enabling + starting vite ${VITE_UNIT} on :${PORT}"
    systemctl --user enable "$VITE_UNIT" >/dev/null 2>&1 || true
    systemctl --user start  "$VITE_UNIT"
    health_gate || die "vite did NOT become healthy on :${PORT} — host is NOT in a known-good state"
    log "rolled back to vite. :${PORT} is the original known-good baseline."
    ;;

  to-previous)
    PREV_DIGEST=""
    [ -f "$STATE_FILE" ] && PREV_DIGEST="$(grep -E '^previous_image_digest=' "$STATE_FILE" | grep -vE '=(none|unknown|vite)$' | tail -1 | cut -d= -f2-)"
    [ -n "$PREV_DIGEST" ] || die "no usable previous_image_digest recorded — use --to-vite instead"
    : "${API_UPSTREAM:?set API_UPSTREAM to the same value cutover used (not stored in plaintext state)}"
    log "restoring previous image ${PREV_DIGEST} on :${PORT}"
    # Free :5173 first (vite uses --strictPort; a leftover binder would EADDRINUSE).
    systemctl --user stop "$VITE_UNIT" 2>/dev/null || true
    # Build the supervised unit the same way cutover does (no manual run on the live port).
    podman create --replace --name "$CONTAINER_NAME" \
      -p "0.0.0.0:${PORT}:8080" -e API_UPSTREAM="$API_UPSTREAM" "$PREV_DIGEST" >/dev/null
    podman generate systemd --new --name --restart-policy always \
      --container-prefix container --time 10 "$CONTAINER_NAME" > "${USER_UNIT_DIR}/${UNIT_NAME}.service"
    podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    systemctl --user daemon-reload
    systemctl --user enable "${UNIT_NAME}.service" >/dev/null 2>&1 || true
    systemctl --user start  "${UNIT_NAME}.service"
    health_gate || die "previous image did NOT become healthy on :${PORT}; consider --to-vite"
    log "rolled back to previous image ${PREV_DIGEST} on :${PORT}."
    ;;
esac

{ printf 'ts=%s\nresult=rollback_%s\n' "$(date -u +%FT%TZ)" "$MODE"; } >> "$STATE_FILE" 2>/dev/null || true
