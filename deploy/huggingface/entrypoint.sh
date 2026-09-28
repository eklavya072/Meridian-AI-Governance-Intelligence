#!/bin/sh
# Start Postgres on loopback, load the showcase seed on a fresh disk, give
# the app a writable copy of the index, then hand the process to the API.
set -eu

STATE=/tmp/meridian
PGDATA="$STATE/postgres"
PGBIN="$(ls -d /usr/lib/postgresql/*/bin | sort -V | tail -n 1)"
mkdir -p "$STATE/uploads"

fresh=0
if [ ! -s "$PGDATA/PG_VERSION" ]; then
    # Trust auth on a server that listens on 127.0.0.1 only.
    "$PGBIN/initdb" -D "$PGDATA" -U aura --auth=trust -E UTF8 >/dev/null
    fresh=1
fi
"$PGBIN/pg_ctl" -D "$PGDATA" -l "$STATE/postgres.log" -w \
    -o "-c listen_addresses=127.0.0.1 -c port=5432 -k $STATE" start

if [ "$fresh" = 1 ]; then
    "$PGBIN/createdb" -h 127.0.0.1 -U aura aura_sdg
    "$PGBIN/psql" -h 127.0.0.1 -U aura -d aura_sdg -q -v ON_ERROR_STOP=1 \
        -f /opt/seed/seed.sql >/dev/null
fi

if [ ! -d "$STATE/chroma" ]; then
    cp -r /opt/seed/chroma "$STATE/chroma"
fi

cd /app
exec uvicorn main:app --host 0.0.0.0 --port 7860
