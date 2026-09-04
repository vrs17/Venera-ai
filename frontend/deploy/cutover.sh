#!/usr/bin/env bash
# deploy/cutover.sh — promote a freshly built image to be the live :5173 frontend.
#
# IDENTITY MODEL (chosen): run-as-ymamajonov.
#   ymamajonov has subuid/subgid (165536:65536), linger ON, working rootless
#   podman (XDG_RUNTIME_DIR=/run/user/1001), AND owns the live brb-frontend.service
#   --user vite unit. So the SAME user retires vite and runs the new container ->
#   NO cross-user (sudo -u / -M) machinery. The DevOps-owned host nginx
#   (-> localhost:5173) is NOT touched.
#
# WHAT IT DOES (minimal-window single-slot swap on :5173):
#   1. Preflight (identity/podman/curl/ss/registry-DNS), login, pull, resolve to an
#      immutable REPO DIGEST (prune-safe; a reboot can always re-pull).
#   2. Start a SEPARATELY-NAMED staging container on a temp port and /healthz-gate it
#      there (live :5173 untouched -> a bad image is caught with ZERO downtime).
#   3. Only then: stop vite (frees :5173), generate a systemd --user unit and start
#      it as the SINGLE thing that binds :5173 (supervised from first bind; no
#      manual podman-run double-bind), /healthz-gate :5173, disable vite.
#   4. Any failure AFTER vite is stopped triggers auto-rollback to vite (known-good).
#
# HONEST WINDOW NOTE: host nginx points at :5173 and must not change, and vite uses
# --strictPort, so two processes can never hold :5173 at once -> an unavoidable brief
# swap window (~1-3s). It is MINIMIZED (image already pulled + proven healthy on the
# staging port first). TRUE zero-downtime needs the DevOps host nginx to become the
# switch — out of scope here, NOT claimed.
#
# /healthz is backend-independent; we NEVER gate on /api (192.168.77.96:8080 is
# unreachable -> /api 502s regardless; that is a separate backend/network problem).
#
# Usage:
#   export REGISTRY_USER=<deploy-token-user> REGISTRY_PASSWORD=<deploy-token-secret>
#   deploy/cutover.sh --image <immutable-ref> --api-upstream <url> [options]
#   e.g. --image registry.gitlab.brb-tech.uz/<grp>/brbtechllm_frontend@sha256:<digest>
#        --api-upstream http://192.168.77.96:8080
# Options:
#   --image REF           REQUIRED. Immutable ref: @sha256:<digest> or :<full-40-char-SHA>.
#   --api-upstream URL    REQUIRED. Injected as API_UPSTREAM at runtime (empty fails closed).
#   --port PORT           Live port host nginx targets. Default 5173.
#   --temp-port PORT      Staging pre-gate port. Default 5174.
#   --registry HOST       Registry to login to / DNS-check. Default: first path segment of --image.
#   --no-login            Skip podman login (auth.json already present / local image).
#   --keep-vite-stopped   Don't disable vite's [Install] (default: disable so it can't
#                         re-grab :5173 at next boot). vite is always STOPPED either way.
#   -h --help             This help.
#
# Credentials (never on argv, never logged): REGISTRY_USER / REGISTRY_PASSWORD env,
# piped via `podman login --password-stdin`. Or pre-existing
# $XDG_RUNTIME_DIR/containers/auth.json with --no-login.

set -euo pipefail

# ----------------------------- constants / defaults -----------------------------
CONTAINER_NAME="brb-frontend"            # the live container + systemd unit base name
STAGING_NAME="brb-frontend-staging"      # SEPARATE name: re-runs never touch the live slot
UNIT_NAME="container-brb-frontend"
USER_UNIT_DIR="${HOME}/.config/systemd/user"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/brb-cutover"
STATE_FILE="${STATE_DIR}/state.env"
LOG_PREFIX="[cutover]"
VITE_UNIT="brb-frontend.service"         # the existing --user vite unit owned by ymamajonov

PORT=5173
TEMP_PORT=5174
IMAGE=""
API_UPSTREAM=""
REGISTRY=""
DO_LOGIN=1
DISABLE_VITE=1
HEALTH_RETRIES=20
HEALTH_SLEEP=1

log() { printf '%s %s\n' "$LOG_PREFIX" "$*" >&2; }
die() { printf '%s ERROR: %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

# ----------------------------- arg parsing -----------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --image)             IMAGE="${2:?}"; shift 2;;
    --api-upstream)      API_UPSTREAM="${2:?}"; shift 2;;
    --port)              PORT="${2:?}"; shift 2;;
    --temp-port)         TEMP_PORT="${2:?}"; shift 2;;
    --registry)          REGISTRY="${2:?}"; shift 2;;
    --no-login)          DO_LOGIN=0; shift;;
    --keep-vite-stopped) DISABLE_VITE=0; shift;;
    -h|--help)           sed -n '2,47p' "$0"; exit 0;;
    *) die "unknown arg: $1 (see --help)";;
  esac
done

[ -n "$IMAGE" ]        || die "--image is required (immutable @sha256:<digest> or :<full-SHA>)"
[ -n "$API_UPSTREAM" ] || die "--api-upstream is required (empty would fail closed)"

# Immutability guard: never promote a moving tag.
case "$IMAGE" in
  *@sha256:*) : ;;
  *:*)
    _tag="${IMAGE##*:}"
    printf '%s' "$_tag" | grep -Eq '^[0-9a-f]{40}$' \
      || die "tag '$_tag' is not immutable. Use @sha256:<digest> or :<full-40-char-SHA> (refusing latest/sha-<short>/vX)." ;;
  *) die "--image '$IMAGE' has no tag/digest." ;;
esac

# ----------------------------- preflight (before touching :5173) -----------------------------
[ "$(id -un)" = "ymamajonov" ] || die "must run as ymamajonov (chosen identity model); current=$(id -un)"
command -v podman >/dev/null || die "podman not found on PATH"
command -v curl   >/dev/null || die "curl not found (needed for the health gate)"
command -v ss     >/dev/null || die "ss not found (install iproute2)"
: "${XDG_RUNTIME_DIR:?XDG_RUNTIME_DIR unset — run inside the ymamajonov user session (loginctl/linger)}"

reg="${REGISTRY:-$(printf '%s' "$IMAGE" | cut -d/ -f1)}"
reghost="${reg%%:*}"
# DNS preflight: registry.gitlab.brb-tech.uz did NOT resolve from this host at design
# time. Fail EARLY (before any :5173 disruption) with a clear message.
if printf '%s' "$reghost" | grep -q '\.'; then
  getent hosts "$reghost" >/dev/null \
    || die "registry host '$reghost' does not resolve. Add a DNS/hosts entry or point --registry at a reachable mirror (or --no-login with a locally-present image) before the first pull."
fi

mkdir -p "$STATE_DIR" "$USER_UNIT_DIR"

# One deliberate bind choice for the whole script. The live unit was generated with
# 0.0.0.0 (LAN-accessible); keep parity. Set to 127.0.0.1 ONLY if rollback.sh's create
# -p matches (host nginx -> localhost works either way).
BIND_ADDR="${BIND_ADDR:-0.0.0.0}"

# Sweep a STALE, non-running brb-frontend container up-front: `podman container exists`
# is true for Created/Exited too, so a crash mid-swap could otherwise fake a redeploy
# with a self-referential digest. Orphan = exists + NOT running + unit inactive.
if podman container exists "$CONTAINER_NAME" 2>/dev/null \
   && [ "$(podman inspect --type container --format '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null || echo false)" != "true" ] \
   && ! systemctl --user is-active --quiet "${UNIT_NAME}.service" 2>/dev/null; then
  log "sweeping orphaned non-running container ${CONTAINER_NAME} before mode detection"
  podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

# MODE DETECTION + ROLLBACK-TARGET CAPTURE (before :5173 is touched). Robust signal =
# what ACTUALLY holds :5173 (running state), NOT the state file.
#   container unit active / container running -> REDEPLOY (rollback to the prev container)
#   else vite active / nothing                -> FIRST-DEPLOY (rollback floor = vite)
DEPLOY_MODE="first-deploy"
PREV_DIGEST="none"
if systemctl --user is-active --quiet "${UNIT_NAME}.service" 2>/dev/null \
   || podman ps --filter name="^${CONTAINER_NAME}$" --filter status=running -q 2>/dev/null | grep -q .; then
  DEPLOY_MODE="redeploy"
  # podman <4 ERRORS on `{{index .RepoDigests 0}}` for a *container* (image-only field);
  # `{{.ImageName}}` is the container's image ref and — the unit binds by digest — is
  # already the immutable @sha256 ref. (Verified on podman 3.4.4.)
  PREV_DIGEST="$(podman inspect --type container --format '{{.ImageName}}' "$CONTAINER_NAME" 2>/dev/null || true)"
  case "$PREV_DIGEST" in
    *@sha256:*) : ;;   # good: usable immutable rollback target
    *) log "WARN: live container image '${PREV_DIGEST:-<none>}' is not a @sha256 ref; rollback floor = vite"; PREV_DIGEST="none" ;;
  esac
  log "MODE=redeploy: container unit holds :${PORT}; rollback target=${PREV_DIGEST}"
elif systemctl --user is-active --quiet "$VITE_UNIT" 2>/dev/null; then
  DEPLOY_MODE="first-deploy"; PREV_DIGEST="vite"
  log "MODE=first-deploy: vite holds :${PORT}; rollback floor=vite"
else
  DEPLOY_MODE="first-deploy"; PREV_DIGEST="vite"
  log "MODE=first-deploy: neither unit active; rollback floor=vite"
fi

# ----------------------------- helpers -----------------------------
health_gate() {  # $1=port $2=label — poll /healthz until 200 or retries exhausted
  local port="$1" label="$2" i code
  for i in $(seq 1 "$HEALTH_RETRIES"); do
    code="$(curl -fsS -o /dev/null -w '%{http_code}' "http://127.0.0.1:${port}/healthz" 2>/dev/null || true)"
    [ "$code" = "200" ] && { log "health OK ($label) on :${port} after ${i} try(ies)"; return 0; }
    sleep "$HEALTH_SLEEP"
  done
  log "health FAIL ($label) on :${port}: last code='${code:-none}' after ${HEALTH_RETRIES} tries"
  return 1
}

wait_port_free() {  # die (with the holder) if :PORT is still bound after freeing the slot
  local i
  for i in $(seq 1 20); do
    ss -tlnH "( sport = :$PORT )" 2>/dev/null | grep -q ":$PORT" || return 0
    sleep 0.5
  done
  local holder; holder="$(ss -tlnpH "( sport = :$PORT )" 2>/dev/null | grep -oE 'pid=[0-9]+' | head -1)"
  die ":$PORT still held after freeing the live slot (${holder:-unknown}) — aborting before bind"
}

free_live_slot() {  # stop WHATEVER holds :5173 (covers both modes), then confirm freed
  log "freeing :${PORT} (mode=${DEPLOY_MODE}): stopping vite and/or container unit"
  systemctl --user stop "$VITE_UNIT"            2>/dev/null || true
  systemctl --user stop "${UNIT_NAME}.service"  2>/dev/null || true
  podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  wait_port_free   # dies with the holder PID if :5173 is still bound -> EXIT trap rolls back
}

# Redeploy floor: rebuild the single systemd binder on the PREVIOUS digest + restart.
# Guarded so a pruned-previous + unreachable-registry create failure FALLS BACK to vite
# instead of aborting the trap mid-way and leaving :5173 down.
rollback_to_previous_container() {
  local prev="$1"
  log "rollback: restoring PREVIOUS container image ${prev} on :${PORT}"
  systemctl --user stop "${UNIT_NAME}.service" 2>/dev/null || true
  systemctl --user stop "$VITE_UNIT"           2>/dev/null || true
  podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  wait_port_free || true
  podman create --replace --name "$CONTAINER_NAME" \
    -p "${BIND_ADDR}:${PORT}:8080" -e API_UPSTREAM="$API_UPSTREAM" "$prev" >/dev/null \
    || { log "rollback: create of previous image failed (pruned + registry unreachable?) -> vite floor"; restart_vite; return; }
  podman generate systemd --new --name --restart-policy always \
    --container-prefix container --time 10 "$CONTAINER_NAME" > "${USER_UNIT_DIR}/${UNIT_NAME}.service" || true
  podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  systemctl --user daemon-reload || true
  systemctl --user enable "${UNIT_NAME}.service" >/dev/null 2>&1 || true
  systemctl --user start  "${UNIT_NAME}.service" || true
  health_gate "$PORT" "rollback-prev" || log "rollback: previous image NOT healthy on :${PORT} — manual intervention needed"
}

# First-deploy floor (also last-resort for a redeploy with no usable prev): bring vite back.
restart_vite() {
  log "rollback: removing container ${CONTAINER_NAME} to free :${PORT}, bringing vite back"
  systemctl --user stop "${UNIT_NAME}.service" 2>/dev/null || true
  podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  systemctl --user enable "$VITE_UNIT" >/dev/null 2>&1 || true
  systemctl --user start  "$VITE_UNIT" || true
  health_gate "$PORT" "rollback-vite" || log "rollback: vite NOT healthy on :${PORT} — manual intervention needed"
}

# Dispatch by CAPTURED mode. Redeploy with a real prev @sha256 -> previous container;
# everything else (first-deploy, or prev degraded to none/vite) -> vite floor.
do_rollback() {
  if [ "$DEPLOY_MODE" = "redeploy" ] && [ -n "$PREV_DIGEST" ] \
     && [ "$PREV_DIGEST" != "none" ] && [ "$PREV_DIGEST" != "vite" ]; then
    rollback_to_previous_container "$PREV_DIGEST"
  else
    [ "$DEPLOY_MODE" = "redeploy" ] && log "rollback: redeploy with no usable previous digest -> vite floor"
    restart_vite
  fi
}

record_state() {  # append-only audit; no secrets
  # Normalize floor markers: `vite`/empty are NOT pullable image refs, so rollback.sh
  # --to-previous must skip them. Writing `none` makes it cleanly die -> use --to-vite.
  local prev_for_state="$PREV_DIGEST"
  case "$prev_for_state" in vite|"") prev_for_state="none";; esac
  {
    printf 'ts=%s\n' "$(date -u +%FT%TZ)"
    printf 'mode=%s\n' "${DEPLOY_MODE:-unknown}"
    printf 'image_ref=%s\n' "$IMAGE"
    printf 'image_digest=%s\n' "${IMAGE_DIGEST:-unknown}"
    printf 'previous_image_digest=%s\n' "$prev_for_state"   # key rollback.sh --to-previous reads
    case "$1" in
      swap_failed_rolled_back_redeploy)
        [ "$prev_for_state" != "none" ] && printf 'rolled_back_to=%s\n' "$prev_for_state" || printf 'rolled_back_to=vite\n' ;;
      swap_failed_rolled_back_first-deploy) printf 'rolled_back_to=vite\n' ;;
    esac
    printf 'api_upstream_host=%s\n' "$(printf '%s' "$API_UPSTREAM" | sed -E 's#^([a-z]+://[^/]+).*#\1#')"
    printf 'result=%s\n' "$1"
  } >> "$STATE_FILE"
}

# ----------------------------- 1. login + pull + resolve REPO digest -----------------------------
if [ "$DO_LOGIN" = 1 ]; then
  : "${REGISTRY_USER:?set REGISTRY_USER (or --no-login if auth.json already present)}"
  : "${REGISTRY_PASSWORD:?set REGISTRY_PASSWORD (never passed as an arg)}"
  log "podman login -> ${reg} (password via stdin, not logged)"
  printf '%s' "$REGISTRY_PASSWORD" | podman login -u "$REGISTRY_USER" --password-stdin "$reg" >/dev/null \
    || die "podman login failed for ${reg}"
fi

log "pulling ${IMAGE}"
podman pull "$IMAGE" >/dev/null || die "pull failed: $IMAGE"
# Resolve to the REGISTRY REPO DIGEST (registry/repo@sha256:...), NOT the local image
# Id. The repo digest survives `podman image prune` and lets the systemd unit re-pull
# on reboot; a local Id can be pruned and break the next boot.
IMAGE_DIGEST="$(podman inspect --format '{{if .RepoDigests}}{{index .RepoDigests 0}}{{end}}' "$IMAGE" 2>/dev/null || true)"
[ -n "$IMAGE_DIGEST" ] || IMAGE_DIGEST="$IMAGE"   # fallback: trust the provided immutable ref
log "resolved repo digest ${IMAGE_DIGEST}"

# ----------------------------- 2. pre-gate on a SEPARATE staging container -----------------------------
# Live :5173 (vite) is untouched here. A bad image fails the gate with zero downtime.
# Auto-pick a free temp port if the requested one is busy (a stray dev server, a
# prior run, etc.) so the pre-gate never fails on EADDRINUSE.
_orig_tp="$TEMP_PORT"
for _tp in "$TEMP_PORT" $((TEMP_PORT+1)) $((TEMP_PORT+2)) $((TEMP_PORT+3)) 15174 25174; do
  ss -tlnH "( sport = :$_tp )" 2>/dev/null | grep -q ":$_tp" || { TEMP_PORT="$_tp"; break; }
done
[ "$TEMP_PORT" != "$_orig_tp" ] && log "temp port $_orig_tp busy; using free temp port $TEMP_PORT"
log "starting staging container ${STAGING_NAME} on temp :${TEMP_PORT} for pre-gate"
podman run -d --replace --name "$STAGING_NAME" \
  -p "127.0.0.1:${TEMP_PORT}:8080" -e API_UPSTREAM="$API_UPSTREAM" "$IMAGE_DIGEST" >/dev/null
if ! health_gate "$TEMP_PORT" "staging"; then
  podman logs --tail 30 "$STAGING_NAME" 2>&1 | sed "s/^/${LOG_PREFIX} ctrlog: /" >&2 || true
  podman rm -f "$STAGING_NAME" >/dev/null 2>&1 || true
  record_state "pregate_failed_no_swap"
  die "health gate failed on staging :${TEMP_PORT}; aborted before touching :5173 (zero downtime, vite still live)"
fi
log "staging healthy; removing it before the live swap"
podman rm -f "$STAGING_NAME" >/dev/null 2>&1 || true

# ----------------------------- 3. swap to :5173 (the brief window) -----------------------------
# From here any non-zero exit -> captured-mode rollback (previous container, or vite).
# `do_rollback || true` guarantees the audit line is reached even if rollback hits set -e.
trap 'rc=$?; if [ "$rc" != 0 ]; then log "failure during swap (rc=$rc) -> rollback (mode=${DEPLOY_MODE})"; do_rollback || true; record_state "swap_failed_rolled_back_${DEPLOY_MODE}"; fi' EXIT

log "swap window begins (mode=${DEPLOY_MODE})"
free_live_slot

# Create the live spec (stopped), generate a systemd --user unit from it, then let
# SYSTEMD be the only thing that binds :5173 (supervised from the first bind; no
# manual podman-run double-bind). --new makes the unit recreate the container on
# each start/reboot from the immutable repo digest.
log "creating live spec + generating ${UNIT_NAME}.service (Restart=always)"
podman create --replace --name "$CONTAINER_NAME" \
  -p "${BIND_ADDR}:${PORT}:8080" -e API_UPSTREAM="$API_UPSTREAM" "$IMAGE_DIGEST" >/dev/null
podman generate systemd --new --name --restart-policy always \
  --container-prefix container --time 10 "$CONTAINER_NAME" > "${USER_UNIT_DIR}/${UNIT_NAME}.service"
podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true   # the --new unit recreates it on start
systemctl --user daemon-reload
systemctl --user enable "${UNIT_NAME}.service" >/dev/null
log "starting systemd-supervised container on live :${PORT}"
systemctl --user start "${UNIT_NAME}.service"
health_gate "$PORT" "live" || die "supervised container failed /healthz on :${PORT}"

# ----------------------------- 4. retire vite cleanly -----------------------------
if [ "$DISABLE_VITE" = 1 ]; then
  log "disabling vite ${VITE_UNIT} so it cannot re-grab :${PORT} at next boot"
  systemctl --user disable "$VITE_UNIT" >/dev/null 2>&1 || true
fi

trap - EXIT
record_state "cutover_ok"
log "DONE. ${CONTAINER_NAME} (${IMAGE_DIGEST}) is live on :${PORT}, supervised by ${UNIT_NAME}.service."
log "Crash auto-restart + reboot survival via the unit (linger already on)."
log "Rollback: deploy/rollback.sh --to-vite  (or --to-previous, prev digest ${PREV_DIGEST:-none})."
