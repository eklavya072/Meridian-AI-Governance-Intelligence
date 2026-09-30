#!/usr/bin/env bash
# Replace the running API with another image, with no downtime. The same
# command is the rollback: pass the tag of the release to go back to.
#
#   deploy/rollout.sh ghcr.io/eklavya072/meridian:sha-<commit>
#
# 1. Start a container on the new image beside the old one.
# 2. Wait for the new one's /readyz. If it never comes, remove it and leave
#    the old one serving: a failed rollout changes nothing.
# 3. Stop the old container (it drains in-flight analyses first) and remove it.
#
# Caddy resolves `api` on every connection, so traffic reaches the new
# container as soon as it is up and stops reaching the old one once it is gone.
# Requires the Chroma server (--profile scale, CHROMA_HOST=chroma in
# .env.prod): two containers must never open one embedded index.
set -euo pipefail

IMAGE="${1:?usage: deploy/rollout.sh <image>}"
READY_TIMEOUT="${READY_TIMEOUT:-180}"
now() { python3 -c 'import time; print(time.time())'; }
compose() { docker compose -f docker-compose.prod.yml --env-file .env.prod --profile scale "$@"; }

if ! grep -qE '^CHROMA_HOST=.+' .env.prod; then
  echo "rollout needs CHROMA_HOST set in .env.prod (see docker-compose.prod.yml)" >&2
  exit 1
fi

old=$(compose ps -q api)
[ -n "$old" ] || { echo "no running api container to replace" >&2; exit 1; }

pull_start=$(now)
docker pull -q "$IMAGE" >/dev/null
started=$(now)
MERIDIAN_IMAGE="$IMAGE" compose up -d --no-deps --no-recreate --scale api=2 api
new=$(compose ps -q api | grep -vxF "$old" || true)
[ -n "$new" ] || { echo "the new container did not start" >&2; exit 1; }

probe='import sys,urllib.request
try: urllib.request.urlopen("http://localhost:8000/readyz", timeout=3); sys.exit(0)
except Exception: sys.exit(1)'
deadline=$(( $(date +%s) + READY_TIMEOUT ))
until docker exec "$new" python -c "$probe" 2>/dev/null; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "new container not ready after ${READY_TIMEOUT}s; keeping the old one" >&2
    docker rm -f "$new" >/dev/null
    exit 1
  fi
  sleep 1
done
ready=$(now)

docker stop "$old" >/dev/null
docker rm "$old" >/dev/null
done_at=$(now)

# pull: fetching the image. ready_after: new container started to /readyz.
# switch: new container started to old container removed.
awk -v img="$IMAGE" -v p="$pull_start" -v s="$started" -v r="$ready" -v d="$done_at" \
  'BEGIN { printf "image=%s pull=%.1fs ready_after=%.1fs switch=%.1fs\n", img, s - p, r - s, d - s }'
