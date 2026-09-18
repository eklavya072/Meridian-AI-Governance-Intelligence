"""Re-chunk and re-index every framework listed in config/frameworks.yaml.

Run this after changing the chunker, the embedding model, or the framework
list — the reference corpus is otherwise only ingested once, so a splitter
change silently leaves the old chunks in place.

Safe to re-run: `sync_framework` ingests before it deletes, and iterates only
what the config lists, so a framework absent from the config is never touched
and a failure part-way through cannot empty the store.

Worth knowing what a bad chunker costs here. A past overlap bug advanced the
chunk window one character at a time, indexing the OECD AI Principles as 1,320
chunks that collapse to 20 distinct passages. Retrieval dedups near-duplicates
but only pulls 3x headroom, so it could not recover the recall it discarded and
the modules were starved of framework evidence. Nothing errored.
"""

import os
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")

from src.framework_sync import FrameworkSyncService, load_frameworks_config
from src.vectorstore import VectorStore

vs = VectorStore()
svc = FrameworkSyncService(vs)
before = vs.collection.count()
print(f"collection before: {before}", flush=True)

t0 = time.time()
ok = err = 0
for i, fw in enumerate(load_frameworks_config(), 1):
    name = fw["name"]
    n0 = vs.count_chunks(framework_filter=[name])
    r = svc.sync_framework(fw)
    if r.get("status") == "synced":
        ok += 1
        print(f"[{i:2d}/33] {name[:52]:<52} {n0:>6} -> {r.get('chunk_count', 0):<6}", flush=True)
    else:
        err += 1
        print(f"[{i:2d}/33] {name[:52]:<52} ERROR {r.get('error', '')[:60]}", flush=True)

print(
    f"\nRESYNC DONE: {ok} synced, {err} errored, "
    f"collection {before} -> {vs.collection.count()} in {(time.time() - t0) / 60:.1f} min",
    flush=True,
)
