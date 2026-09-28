#!/bin/sh
# Build the demo's data: a database seed and a copy of the vector index.
#
#   deploy/huggingface/make_seed.sh <out-dir>
#
# Reads the local development database and backend/data/chroma, and writes
# <out-dir>/seed.sql and <out-dir>/chroma. Stop the API first: the index is
# copied as files, and a process writing to it would tear the copy.
#
# The seed holds the eight showcase workspaces, each with ONLY the run the
# study reports (older runs came from earlier builds of the scorer), and the
# briefs written from those runs. Chats, upload logs, the quota ledger and
# every local file path are left out.
set -eu

OUT="${1:?usage: make_seed.sh <out-dir>}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PG="-h localhost -U aura"
export PGPASSWORD="${PGPASSWORD:-aura}"
SEED_DB=meridian_seed

# The run per country the study reports, by id prefix.
PREFERRED="'8edf3aca','c7e27689','a4b4831b','45870080','f58a2856','62fbc554','a3fd11f3','ffb0518c'"

mkdir -p "$OUT"
dropdb $PG --if-exists "$SEED_DB"
createdb $PG "$SEED_DB"
pg_dump $PG --no-owner --no-privileges aura_sdg | psql $PG -q -d "$SEED_DB" >/dev/null

psql $PG -q -v ON_ERROR_STOP=1 -d "$SEED_DB" <<SQL
DELETE FROM chat_messages;
DELETE FROM chat_sessions;
DELETE FROM upload_logs;
DELETE FROM provider_health;
DELETE FROM reports WHERE workspace_id NOT IN (
    SELECT workspace_id FROM analyses WHERE left(id::text, 8) IN ($PREFERRED));
DELETE FROM analyses WHERE left(id::text, 8) NOT IN ($PREFERRED);
DELETE FROM workspaces WHERE id NOT IN (SELECT workspace_id FROM analyses);

-- No local paths in a public image. The showcase is read-only, so the
-- stored file references are never read; the names still label the cards.
UPDATE workspaces SET
    policy_file_path = NULL,
    dimension_results = NULL,
    pending_documents = (
        SELECT json_agg(json_build_object('file_path', '', 'file_name', d->>'file_name'))
        FROM json_array_elements(pending_documents) d);

-- Status text from the run on show, not from whichever retry came last.
UPDATE workspaces w SET status_detail = format(
    'Analysis complete. %s/%s citations verified.', c.verified, c.total)
FROM (
    SELECT a.workspace_id,
           count(*) AS total,
           count(*) FILTER (WHERE (e->>'verified')::bool) AS verified
    FROM analyses a,
         json_array_elements(a.governance_gaps) g,
         json_array_elements(g->'evidence') e
    GROUP BY a.workspace_id) c
WHERE c.workspace_id = w.id;
SQL

pg_dump $PG --no-owner --no-privileges "$SEED_DB" > "$OUT/seed.sql"
dropdb $PG "$SEED_DB"

rm -rf "$OUT/chroma"
cp -R "$REPO/backend/data/chroma" "$OUT/chroma"

echo "seed: $(grep -c '^COPY' "$OUT/seed.sql") tables, $(du -sh "$OUT/chroma" | cut -f1) index -> $OUT"
