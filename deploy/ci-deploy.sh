#!/usr/bin/env bash
# Barno prod tarqatish. GitLab runner buni prod HOSTNING O'ZIDA, ~/Venera
# egasi nomidan ishga tushiradi (.gitlab-ci.yml -> deploy / rollback).
#
#   deploy/ci-deploy.sh <commit>     prod daraxtini sinovdan o'tgan commitga
#                                    fast-forward qiladi, API'ni qayta
#                                    ishga tushiradi, apps/web o'zgargan
#                                    bo'lsa frontend obrazini qayta yig'adi,
#                                    ikkala /health'ni kutadi.
#   deploy/ci-deploy.sh --rollback   oxirgi deploy qoldirgan pre-ci-* tegiga
#                                    qaytadi (kod + API + frontend obrazi).
#
# Har deploy oldidan prod HEAD `pre-ci-<vaqt>` tegi bilan belgilanadi, shu
# teg rollback nuqtasi. Hech narsa SSH talab qilmaydi.
set -euo pipefail

PROD="${PROD_TREE:-$HOME/Venera}"
API_HEALTH="http://127.0.0.1:8000/api/health"
WEB_HEALTH="http://127.0.0.1:5173/healthz"
IMG="localhost/venera-frontend"

wait_ok() {                      # url, sekund
  for _ in $(seq 1 "$2"); do
    curl -fsS -m 3 "$1" >/dev/null 2>&1 && return 0
    sleep 1
  done
  echo "javob yo'q: $1 ($2 s)" >&2
  return 1
}

restart_api() {
  systemctl --user restart venera-api
  wait_ok "$API_HEALTH" 40
  echo "API: $(curl -fsS -m 3 "$API_HEALTH")"
}

build_web() {                    # yangi obraz + sana-sha tegi, keyin unit restart
  podman build -q -t "$IMG:latest" apps/web
  podman tag "$IMG:latest" "$IMG:$(date +%F)-$(git rev-parse --short HEAD)"
  restart_web
}

restart_web() {
  systemctl --user restart venera-frontend
  wait_ok "$WEB_HEALTH" 60
  echo "Web: ok"
}

cd "$PROD"

if [ "${1:-}" = "--rollback" ]; then
  tag=$(git tag --list 'pre-ci-*' --sort=-creatordate | head -1)
  [ -n "$tag" ] || { echo "pre-ci-* teg yo'q, qaytadigan nuqta yo'q" >&2; exit 1; }
  echo "rollback: $tag ($(git rev-parse --short "$tag"))"
  git reset -q --hard "$tag"
  restart_api
  short=$(git rev-parse --short HEAD)
  img=$(podman images --format '{{.Repository}}:{{.Tag}}' "$IMG" | grep -- "-$short\$" | head -1 || true)
  if [ -n "$img" ]; then
    podman tag "$img" "$IMG:latest"
    restart_web
  else
    echo "shu commit uchun tayyor frontend obrazi yo'q, qayta yig'iladi"
    build_web
  fi
  git tag -d "$tag" >/dev/null
  exit 0
fi

sha="${1:?foydalanish: ci-deploy.sh <commit> | --rollback}"
git fetch -q origin
git rev-parse -q --verify "$sha^{commit}" >/dev/null || { echo "noma'lum commit: $sha" >&2; exit 1; }

before=$(git rev-parse HEAD)
git tag -f "pre-ci-$(date +%Y%m%d-%H%M%S)" "$before" >/dev/null
if [ "$before" != "$(git rev-parse "$sha")" ]; then
  git merge -q --ff-only "$sha"
fi
echo "prod: $(git rev-parse --short "$before") -> $(git rev-parse --short HEAD)"

if git diff --name-only "$before" HEAD | grep -q '^apps/api/pyproject.toml$'; then
  echo "API bog'liqliklari o'zgargan, o'rnatiladi"
  apps/api/venv/bin/pip install -q -e apps/api
fi
restart_api

if [ "${FORCE_WEB:-0}" = "1" ] || git diff --name-only "$before" HEAD | grep -q '^apps/web/'; then
  echo "apps/web o'zgargan, frontend obrazi qayta yig'iladi"
  build_web
else
  echo "apps/web o'zgarmagan, frontend o'z holida"
fi
