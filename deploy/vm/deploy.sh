#!/bin/sh
# Build the demo from the checked-out commit and start it, replacing the
# running one.
#
#   deploy/vm/deploy.sh
#
# Reads from $MERIDIAN_HOME (default /srv/meridian):
#   .env    GEMINI_API_KEY, SITE_ADDRESS and SITE_URL (see README.md)
#   seed/   seed.sql and chroma/, as made by deploy/huggingface/make_seed.sh
set -eu

MERIDIAN_HOME="${MERIDIAN_HOME:-/srv/meridian}"
export MERIDIAN_HOME
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

test -f "$MERIDIAN_HOME/.env" || { echo "missing $MERIDIAN_HOME/.env" >&2; exit 1; }
if [ ! -f "$MERIDIAN_HOME/seed/seed.sql" ] || [ ! -d "$MERIDIAN_HOME/seed/chroma" ]; then
    echo "missing $MERIDIAN_HOME/seed (seed.sql and chroma/)" >&2
    exit 1
fi

"$REPO/deploy/huggingface/build_space.sh" "$MERIDIAN_HOME/space"

compose() { docker compose -f "$REPO/deploy/vm/compose.yml" --env-file "$MERIDIAN_HOME/.env" "$@"; }
compose build meridian
start=$(date +%s)
compose up -d

until compose exec -T meridian python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:7860/readyz', timeout=3)" \
    >/dev/null 2>&1; do
    if [ $(( $(date +%s) - start )) -gt 300 ]; then
        compose logs --tail 80 meridian
        exit 1
    fi
    sleep 2
done
echo "serving $(git -C "$REPO" rev-parse --short HEAD), ready $(( $(date +%s) - start )) s after start"
