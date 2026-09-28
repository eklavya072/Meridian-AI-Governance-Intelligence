#!/bin/sh
# Build the demo's data: a database seed and a copy of the vector index.
#
#   deploy/huggingface/make_seed.sh <out-dir>
#
# Reads the local development database and backend/data/chroma, and writes
# <out-dir>/seed.sql and <out-dir>/chroma. Stop the API first: the index is
# copied as files, and a process writing to it would tear the copy.
#
# The local database is the curated set: one run per country and document
# set (the study's run over the full set, plus a run over the first document
# alone where a country's set grew). The seed keeps every COMPLETE run, the
# briefs, and the workspaces that own them. Chats, upload logs, the quota
# ledger and every local file path are left out.
set -eu

OUT="${1:?usage: make_seed.sh <out-dir>}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PG="-h localhost -U aura"
export PGPASSWORD="${PGPASSWORD:-aura}"
SEED_DB=meridian_seed

mkdir -p "$OUT"
dropdb $PG --if-exists "$SEED_DB"
createdb $PG "$SEED_DB"
pg_dump $PG --no-owner --no-privileges aura_sdg | psql $PG -q -d "$SEED_DB" >/dev/null

psql $PG -q -v ON_ERROR_STOP=1 -d "$SEED_DB" <<SQL
DELETE FROM chat_messages;
DELETE FROM chat_sessions;
DELETE FROM upload_logs;
DELETE FROM provider_health;
-- A run that lost dimensions to the provider is not an example.
DELETE FROM analyses a WHERE EXISTS (
    SELECT 1 FROM json_array_elements(a.governance_gaps) g
    WHERE coalesce(g->>'analysis_error', '') <> '');
DELETE FROM reports WHERE workspace_id NOT IN (SELECT workspace_id FROM analyses);
DELETE FROM workspaces WHERE id NOT IN (SELECT workspace_id FROM analyses);

-- No local paths in a public image. The showcase is read-only, so the
-- stored file references are never read; the names still label the cards.
UPDATE workspaces SET
    policy_file_path = NULL,
    dimension_results = NULL,
    pending_documents = (
        SELECT json_agg(json_build_object('file_path', '', 'file_name', d->>'file_name'))
        FROM json_array_elements(pending_documents) d);

-- Status text from the run on show (the one over the most documents), not
-- from whichever retry came last.
UPDATE workspaces w SET status_detail = format(
    'Analysis complete. %s/%s citations verified.', c.verified, c.total)
FROM (
    SELECT DISTINCT ON (a.workspace_id) a.workspace_id,
           (SELECT count(*) FROM json_array_elements(a.governance_gaps) g,
                   json_array_elements(g->'evidence') e) AS total,
           (SELECT count(*) FROM json_array_elements(a.governance_gaps) g,
                   json_array_elements(g->'evidence') e
             WHERE (e->>'verified')::bool) AS verified
    FROM analyses a
    ORDER BY a.workspace_id,
             json_array_length(coalesce(a.ragas_metrics->'evaluated_documents', '[]')) DESC,
             a.created_at DESC) c
WHERE c.workspace_id = w.id;
SQL

# The showcase runs record the build they came from, 97f37e6. Publishing
# the repository rewrote history to leave unpublished working material out,
# which changed that commit's hash to 01646e4 without changing a line of its
# code. The provenance is pointed at the commit that exists.
pg_dump $PG --no-owner --no-privileges "$SEED_DB" \
    | sed 's/97f37e67aacba68bc5cb023ac73c37dd75937e00/01646e49e59e1f9b3cd599c946999298748a74a6/g' \
    > "$OUT/seed.sql"
dropdb $PG "$SEED_DB"

rm -rf "$OUT/chroma"
cp -R "$REPO/backend/data/chroma" "$OUT/chroma"

echo "seed: $(grep -c '^COPY' "$OUT/seed.sql") tables, $(du -sh "$OUT/chroma" | cut -f1) index -> $OUT"
