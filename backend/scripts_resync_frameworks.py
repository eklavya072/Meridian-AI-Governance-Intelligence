"""Re-chunk every framework in config/frameworks.yaml with the fixed splitter.

The overlap bug made the chunk window crawl one character at a time, so the
frameworks indexed at up to 98.6% near-duplicates: OECD AI Principles held
1,320 chunks that collapse to 20 distinct passages. Retrieval dedups
near-duplicates but only pulls 3x headroom, so it cannot recover the recall it
discards — the modules were being starved of framework evidence.

Frameworks absent from the config are never touched: sync_framework ingests
before it deletes, and only iterates what the config lists.
"""
import os, time
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from src.vectorstore import VectorStore
from src.framework_sync import FrameworkSyncService, load_frameworks_config

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
        print(f"[{i:2d}/33] {name[:52]:<52} {n0:>6} -> {r.get('chunk_count',0):<6}", flush=True)
    else:
        err += 1
        print(f"[{i:2d}/33] {name[:52]:<52} ERROR {r.get('error','')[:60]}", flush=True)

print(f"\nRESYNC DONE: {ok} synced, {err} errored, "
      f"collection {before} -> {vs.collection.count()} in {(time.time()-t0)/60:.1f} min", flush=True)
