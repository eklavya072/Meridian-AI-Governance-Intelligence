"""Rebuild the vector index by re-embedding the text Chroma kept in SQLite.

A torn HNSW segment left the store segfaulting on any read. The vectors lived
only in that index — `embeddings` holds ids, and `embeddings_queue` had been
pruned to 508 rows — but every chunk's TEXT and metadata survived in
`embedding_metadata`. Re-embedding from there restores the corpus without
re-parsing a single PDF, and keeps the original chunk ids, so cached analyses
still resolve their evidence.
"""
import json, os, sqlite3, sys, time
os.environ["HF_HUB_OFFLINE"] = "1"

SRC = "data/chroma/chroma.sqlite3"
DEST = sys.argv[1] if len(sys.argv) > 1 else "data/chroma_rebuilt"

from sentence_transformers import SentenceTransformer
import chromadb
from src.vectorstore import COLLECTION_NAME, NullEmbeddingFunction

con = sqlite3.connect(f"file:{SRC}?mode=ro", uri=True)
rows = con.execute("""
    SELECT e.embedding_id, m.key, m.string_value, m.int_value, m.float_value, m.bool_value
    FROM embeddings e JOIN embedding_metadata m ON m.id = e.id
""").fetchall()
con.close()

records: dict[str, dict] = {}
for eid, key, sv, iv, fv, bv in rows:
    val = sv if sv is not None else (iv if iv is not None else (fv if fv is not None else bv))
    records.setdefault(eid, {})[key] = val

ids, texts, metas = [], [], []
for eid, md in records.items():
    doc = md.pop("chroma:document", None)
    if not doc:
        continue
    ids.append(eid)
    texts.append(doc)
    metas.append({k: ("" if v is None else v) for k, v in md.items()})
print(f"loaded {len(ids)} chunks from sqlite", flush=True)

model = SentenceTransformer("BAAI/bge-small-en-v1.5")
client = chromadb.PersistentClient(path=DEST)
coll = client.get_or_create_collection(COLLECTION_NAME,
                                       embedding_function=NullEmbeddingFunction(),
                                       metadata={"hnsw:space": "cosine"})

BATCH, t0 = 256, time.time()
for i in range(0, len(ids), BATCH):
    sl = slice(i, i + BATCH)
    embs = model.encode(texts[sl], normalize_embeddings=True,
                        batch_size=32, show_progress_bar=False).tolist()
    coll.add(ids=ids[sl], documents=texts[sl], embeddings=embs, metadatas=metas[sl])
    done = min(i + BATCH, len(ids))
    rate = done / max(time.time() - t0, 1e-9)
    print(f"  {done}/{len(ids)}  {rate:.0f}/s  eta {(len(ids)-done)/max(rate,1e-9)/60:.1f}min", flush=True)

print(f"REBUILD COMPLETE: {coll.count()} chunks in {DEST} ({(time.time()-t0)/60:.1f} min)", flush=True)
