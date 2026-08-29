# Meridian

Last updated: 2026-08-26

## What this is and why it exists

Meridian evaluates national AI policy documents against 8 governance dimensions
(Transparency, Accountability, Privacy, Safety, Human Autonomy, Inclusivity,
Fairness, Environmental Sustainability). For each dimension it produces a
coverage verdict, a maturity stage, a risk framing and an implementation
roadmap, plus a synthesised brief and two chat surfaces (AI Auditor, AI
Rapporteur).

It is a portfolio piece for a **UNDP Digital/AI internship application**. That
goal drives every technical decision below. The instrument is not judged on
feature count — it is judged on whether a policy specialist reading the output
would find it defensible. Consequences that follow:

- A wrong verdict is worse than a missing one. Failed dimensions are excluded
  from scoring rather than guessed at.
- Every claim must cite the document. Fabricated citations are surfaced; the
  weaker "unsupported" class is computed but deliberately not shown, because
  it produced noise on legitimate paraphrase.
- The output must read as policy analysis, not model output. No `**` leaking
  into rendered text, no generic recommendations, no scores without a stated
  basis.
- Scores must be defensible in both directions: harsh enough that a soft
  guidance document cannot score well, lenient enough that the EU AI Act — the
  strongest instrument in existence — lands high. Both failures happened and
  both were fixed.

## Architecture

- Backend: FastAPI, async SQLAlchemy, PostgreSQL
- Vectors: ChromaDB with BAAI/bge-small-en-v1.5
- LLM: Gemini (`gemini-3.6-flash`, 5-key rotation) with Groq fallback
  (`openai/gpt-oss-120b`)
- Frontend: Next.js 14

Analysis runs four module roles per dimension — `module_1_normative`,
`module_2_practical`, `module_3_implementation`, `module_4_incident`. Modules
1+2 and 3+4 are combined into two prompts, so a dimension costs 2 LLM calls and
a full run costs 16.

### Theoretical basis

Findings are graded on a **normative-force ladder**: T0 Aspirational,
T1 Intentional, T2 Assigned, T3 Obligatory, T4 Enforceable. This is grounded in
the Abbott & Snidal legalization framework (obligation / precision /
delegation) — worth knowing, because it is the part of Meridian that is a
research contribution rather than an engineering one, and it is what makes the
scores arguable rather than arbitrary.

Tier counters are **cumulative**:
`n_enforceable <= n_binding <= n_institutional <= n_commitment <= n_scored`.
This property is the source of several past bugs — any single binding sentence
also lifts every weaker counter, so thresholds built on the weaker counters are
degenerate.

Maturity has five stages: Unaddressed → Emerging → Delegated →
Operationalized → Institutionalized.

## Important files

| File | Role |
| --- | --- |
| `backend/src/gap_analyzer.py` | Core scoring, ~3.5k lines. Single source of verdict truth. |
| `backend/src/evidence_strength.py` | `meets_force_bar`, coverage/maturity from profile, risk basis |
| `backend/src/retrieval.py` | Chunk selection, incident-pool filtering |
| `backend/src/verify.py` | Citation verification, division-vocabulary detection |
| `backend/src/analysis_prompts.py` | Prompt construction |
| `backend/src/deterministic.py` | Dimension term vocabularies |
| `backend/src/chat.py` | Auditor / Rapporteur, routing, session context cache |
| `backend/src/meridian_facts.py` | Meridian's own method as prompt context, derived from live constants |
| `backend/src/analysis_brief.py` | The open run compacted for cross-dimension questions |
| `backend/src/brief_synthesis.py` | Brief sections |
| `backend/src/tasks.py` | `run_full_analysis_pipeline` |
| `backend/main.py` | Migrations, routes, startup warm |
| `frontend/components/MarkdownLite.tsx` | Safe inline markdown renderer |
| `frontend/app/workspace/page.tsx` | Upload, run trigger, progress poller |
| `frontend/app/analysis/page.tsx` | Results, run selector |

## Pipeline logic

1. Ingest every document in the run before any scoring begins.
2. Retrieve per dimension per module role. The incident pool is
   grounding-filtered and capped at 2 chunks per document so one long statute
   cannot crowd out the others.
3. The LLM returns findings tagged with normative-force tiers.
4. Cumulative tier counters are built into one `EvidenceProfile`.
5. Coverage and maturity are both derived from that one profile through the
   shared `meets_force_bar()` predicate. **Nothing else computes a verdict.**
6. Citations are verified against retrieved text and full document text.
7. Maturity index = mean of stage scores over assessed dimensions only
   (`UNADDRESSED 0, EMERGING 50, DELEGATED 65, DEVELOPING 78, ESTABLISHED 100`).

### The two load-bearing predicates

```python
def meets_force_bar(profile) -> bool:
    return (profile.n_binding >= 2
            or (profile.n_binding >= 1 and profile.n_enforceable >= 1))
```

Deliberately not `n_binding >= 1`. Because counters are cumulative, a lone
binding sentence lifts everything below it; pairing a duty with *enforcement*
is the one genuinely independent signal available.

Institutionalized requires
`n_binding >= 2 and (n_enforceable >= 2 or (document_enforcement_regime and n_enforceable >= 1))`.

## Problems faced, and what fixed them

This is the most valuable section in the file. Most of these were found by
reading the code end to end rather than by testing, and several had shipped
visibly wrong analyses before being caught.

### Duplicated verdict logic — the root cause of nearly everything

**Problem.** Three separate places computed coverage. They drifted. One
recomputed `coverage_from_profile` *without* the mechanisms argument, so Japan
shipped "Covered" on 1-of-7 mechanisms while the prompt itself said Partial.
Separately, `maturity_from_profile` kept the old degenerate `n_binding >= 1`
bar after the coverage side had been fixed, producing a document that read
"Partial — stands alone rather than forming a developed regime" and
"Operationalized" in the same breath. That contradiction is what the user saw
on the EU run.

**Fix.** Collapsed to a single computation whose result lives in a `determined`
dict that all downstream code reads. Extracted `meets_force_bar()` so coverage
and maturity physically cannot hold separate answers to the same question.
`test_verdict_single_source.py` is an AST-level test that fails the build if a
second verdict computation reappears.

**Lesson.** Two functions answering the same question will each keep their own
answer. The fix is structural, not a careful edit.

### Reconciliation was conditional

**Problem.** When `coverage_rules` came back empty the whole downstream
reconciliation block was skipped, so Nigeria and Kenya shipped "Covered"
alongside narrative text saying the document lacks bias testing.

**Fix.** Reconciliation via `detect_ladder_raise_contradiction` now runs
unconditionally.

### Maturity was too strict, then correctly loosened

**Problem.** EU AI Act scored 79.2 — indefensible for the strongest AI statute
in the world. Japan with three instruments scored below where a reader would
place it. The linear rank average was the culprit: it treated the gap between
stages as uniform when it is not.

**Fix.** Two changes. Stage *scores* (0 / 50 / 78 / 100) replaced the linear
rank average. And `_document_enforcement_regime(workspace_id)` — cached per
workspace, driven by `detect_enforcement_regime` over sampled text — lets a
document that demonstrably carries enforcement reach Institutionalized on one
enforceable finding instead of two. EU projects to ~91, Japan with all three
documents to 75.8.

### Citation caveats that were our fault, not the model's

**Problem.** Fairness and Inclusivity threw citation caveats on the EU run. The
prompt hardcoded "article, section or recital" as the citation vocabulary, so
when the model correctly read *Part 4* it relabelled it *Section 4* to fit our
closed list. The user identified this precisely: not hallucination, but our
constraint corrupting a correct reading.

**Fix.** `detect_division_vocabulary(texts)` reads the document's own division
words (11 kinds, OCR-tolerant) and `_citation_instruction()` feeds them to the
prompt. Also split `classify_narrative_citations` into `fabricated` vs
`unsupported`, and render only `fabricated` — the unsupported class fired on
legitimate paraphrase and was pure noise.

### Citations verified only when the document cross-referenced itself

**Problem.** India's run 2 reported `Principle 4`, `Principle 6` and
`Section 4` as fabricated. All three are real and were read correctly. The
Guidelines number their seven sutras as bare ordinals — `4. Fairness and
Equity`, `6. Understandable by Design` — and the DPDP Act numbers its sections
the same way (`38. (1) The provisions of this Act`). The division WORD appears
only in running prose. `_citation_present` demanded the literal string
"Principle 4", so a citation passed only when the document happened to
cross-reference that division elsewhere — an accident of drafting, not
evidence.

**Fix.** A bare-ordinal fallback in `_citation_present`: the document names
that kind of division somewhere AND enumerates one with that number. Both
halves are required, or any numbered list would clear any citation.
Documents are now scored SEPARATELY (`classify_narrative_citations` takes a
list, fed by `_workspace_document_texts`) — the Guidelines enumerate exactly
1-7, so `Principle 8` is still caught, whereas concatenating the 44-section
DPDP Act would have lent it an ordinal it does not have.

**Lesson.** Third time in this file that a citation caveat was our constraint
rather than the model's error. When a caveat fires, suspect the checker first.

### Cached dimensions cited chunks that no longer existed

**Problem.** India run 2 scored 38/49 citations. Every one of the 11 failures
was in one of the five dimensions restored from the dimension cache; the three
freshly analysed ones passed 19/19. Reason:
`"Cited chunk_id does not exist in the vector store."`

Re-running re-ingests every document, and chunk ids were `uuid.uuid4()` — an
unchanged file came back under an entirely new set of ids, orphaning the
evidence the cache had carried over. Silent: it degrades the headline citation
number and makes cached evidence unverifiable, but never fails the run.

**Fix.** `_deterministic_chunk_id()` — `uuid5` over document key, ordinal and a
sha1 of the chunk text. Same bytes in, same ids out. Assigned before the
non-English filter so dropping a chunk never renumbers the survivors.

### The framework resync helped the index, not the analysis

**What was predicted.** Frameworks indexed at up to 98.6% near-duplicates
(OECD AI Principles: 1,320 chunks collapsing to 20 distinct passages), and
retrieval pulls only 3x headroom before its containment dedup discards the
rest without fetching replacements. That reads like starved recall, so a
resync was expected to improve the evidence reaching the scorer.

**What actually happened.** 33 frameworks resynced, 0 errors, collection
46,944 -> 15,468. The EU analysis was then re-run twice against the clean
corpus — genuinely re-analysed, 9 LLM calls, no cache hits — and returned
IDENTICAL numbers both times: 7 Covered / 1 Partial, coverage 84.4, binding
share 47.4, maturity 92.9, 104 retrieved.

**Why — still open.** The first explanation written here was wrong: it claimed
`framework_evidence` was empty everywhere. It is not. The inspection script
read the gap's top level, where the field does not live; it hangs off
`module_1`. The same EU analysis carries 15 framework citations across 7
frameworks (UNESCO x5, NIST x3, EU AI Act x2, Global Digital Compact x2).

What is actually established is narrower: verdicts come from the country
document's own text through the normative-force ladder, and framework
alignment was measured and rejected for scoring, so framework retrieval feeds
the narrative and the requirement citations rather than the verdict. Why
cleaner framework chunks changed nothing measurable is NOT yet explained.

**Worth keeping anyway, for operational reasons only:** a 67% smaller index,
`/frameworks` down from 12.9s to 5.7s, and far less storage and embedding cost.
Do not sell it as an analysis improvement.

**The lesson.** Two predictions in a row — the chunker fix and this resync —
were argued from a plausible mechanism and both failed to move a single
verdict. Measure the output before claiming the benefit; a real defect in a
component does not imply a defect in the result.

### The chunk window crawled one character at a time

**Problem.** `recursive_character_split` took its overlap as a quarter of the
MAXIMUM chunk size — a flat 700 chars — rather than a quarter of the chunk it
actually emitted. `_find_sentence_boundary` may return a boundary only 101
chars past `start`, and `end - 700` then fell BEHIND `start`; the
`max(..., start + 1)` floor took over and the window advanced by a single
character, re-emitting almost the same passage on every pass.

The live EU AI Act index carried runs of chunks 695, 692, 689, 686 chars long,
each a three-character shift of the last: 514 of its 1,707 chunks sat in a
duplicate set, 15.1% exact duplicates, corpus-wide 13.0%. Retrieval pays for
this directly — a candidate sweep spends its budget on near-identical windows,
so the scorer sees a fraction of the distinct passages the count implies. This
is a second, independent cause of the starved-retrieval failure already
recorded for duplicate stacking.

**Fix.** `overlap_chars = min(MAX_CHUNK_CHARS // 4, (end - start) // 4)`, which
keeps the stride at 75% of whatever was emitted. On the EU AI Act: 1,707 chunks
to 357, 15.1% duplicates to 0.0%, average chunk 785 to 2,171 chars. Indexed
characters came to 775,142 against a 620,074-char document — the 1.25x a clean
25% overlap should give, so nothing is skipped.

**What it did not do.** The EU verdicts were unchanged (7 Covered / 1 Partial,
coverage 84.4, maturity 92.9). That document is dense enough that a half-wasted
budget still surfaced sufficient evidence. The gain should land on the THIN
instruments — India's Guidelines, Nigeria's NAIS — where a starved sweep pushes
a dimension to Partial for the wrong reason. Unverified until those re-run.

**Not rebuilt.** 14 frameworks totalling 3,252 chunks have no source PDF on
disk (Robodebt alone is 2,169), so a blanket re-ingest would destroy them.
Workspace documents re-chunk on every analysis run and fix themselves; the 35
frameworks that do have PDFs need a deliberate sync.

### A torn vector index read as an out-of-memory death

**Problem.** The API kept dying seconds after an EU AI Act run started — no
traceback, only a leaked-semaphore warning at interpreter shutdown. Because
uvicorn's reloader parent keeps holding port 8000 after its worker dies, the
API looked up and answered nothing; the workspace page polled a corpse for
over two hours. Swap was near full at the time, so this was read as an OOM
kill and `WARM_FRAMEWORK_COUNTS` was added to shrink the startup footprint.

That reading was wrong. With memory sampling attached the process died at
**307 MB RSS** with swap to spare, and the macOS crash report named it:
`SIGSEGV`, inside `chromadb_rust_bindings`. A bare `collection.count()`
reproduced it standalone with exit 139. The HNSW segment directory had been
written mid-crash and was torn; SQLite was clean, `integrity_check` ok, all
47,365 embeddings present. Every subsequent crash was the *first* crash's
damage being re-read, which is why it looked like a memory problem that got
worse each run.

**Fix.** Delete the HNSW segment directory. Chroma rebuilds it from the
embeddings in SQLite — verified on a copy first: `count()` returned all 47,365
and a vector query came back in 0.2 s with sensible neighbours. The torn index
is kept as `data/chroma_hnsw_corrupt_<timestamp>` rather than deleted.

**The lesson worth keeping.** Memory pressure was real and concurrent, and it
made a plausible story that cost hours. A process that dies without a
traceback has a signal; on macOS it is in
`~/Library/Logs/DiagnosticReports/*.ips` under `termination`. Read it before
theorising.

### Crashes wedged workspaces permanently

**Problem.** The analysis worker runs in-process, so a crash left the row in
`PROCESSING` with nothing behind it — and the run endpoint refuses to start an
analysis for a workspace already in that state. Two EU workspaces were stuck
that way, one for nine hours, with no way back but editing the database.

**Fix.** A startup sweep reclaims them: `PROCESSING` returns to `QUEUED` so it
can be re-run, `GENERATING_REPORT` returns to `COMPLETE` because its analysis
had already finished and only the brief was lost. A row in a live state at
startup is orphaned by definition. Note the literals are upper-case — the
Postgres enum labels are the member *names*, not the lower-case values, and
because the statement fails into a warning a wrong-case sweep silently
no-ops. `test_orphan_recovery.py` pins both.

### Chunk ids rendered as provisions

**Problem.** India's Human Autonomy verdict shipped "in Section
3081a297-54ab-4efd-9c8c-492521016736", three times. The evidence headers carry
chunk ids and the citation rule says to cite only numbers that literally
appear in the passages, so the model complied.

**Fix.** `_CHUNK_ID_PROHIBITION` in the prompt, plus `strip_chunk_id_citations`
applied where the narrative enters the pipeline — a prompt rule alone is
probabilistic and a reader must never see a UUID presented as a provision.

### Emerging paid three different profiles the same score

**Problem.** `Emerging` was reached by two branches covering three materially
different profiles, all worth 50: a lone binding duty (T3), a named institution
with no duty (T2), and a bare principle (T0/T1). Live on India — Inclusivity
(binding duty), Human Autonomy (named institution) and Fairness (principle
only) scored identically while their own narratives said plainly different
things. One says "imposes a binding requirement", the next says "imposes no
binding requirement on anyone", and the index could not tell them apart.

**Fix.** A fifth stage, **Delegated** (65), between Emerging and
Operationalized: an owner or a duty exists, but not a working regime. It
surfaces the DELEGATION axis that Abbott & Snidal separate from obligation and
that `n_institutional` already measured — the counter was computed and then
discarded at staging.

Deliberately does NOT move the T3/T4 force bar, so a document binding nobody
still cannot reach Operationalized. EU 91.0 → 92.9, Japan 75.8 → 77.6, India
63.2 → 67.0; ordering preserved, ceiling untouched, and India's Fairness stays
at 50 because it genuinely has neither owner nor duty.

**Note.** Stored analyses keep the old four-stage labels until re-run.

### One number could not say two different things

**Problem.** The headline metric measured legalized force and was labelled
"maturity", so a reader heard "Japan is mediocre at governing AI" when the
evidence said "Japan addresses nearly everything and deliberately binds little".
Mechanism breadth WAS computed (`detect_mechanisms`) but survived only as a
sentence spliced into `coverage_reasoning` — nothing downstream could aggregate
it, so the breadth axis existed in the analysis and not in the output.

**Fix.** Two axes, reported side by side.

- `mechanisms_present` (name → tier) and `mechanisms_absent` now persist on
  every `GovernanceGap`.
- `coverage_index` — share of framework-required mechanisms addressed at all.
  Deliberately NOT tier-weighted; weighting breadth by force folds the force
  axis back in and collapses the distinction the second number exists to draw.
- `binding_share` — of the mechanisms present, how many are carried by an
  actual duty (tier >= 3). The bridge between the two.
- Display name is **Binding Force**, not Maturity or Legalization: descriptive
  rather than evaluative, since "maturity" reads as a report card.

The interesting cases are exactly where the two diverge — soft law reads high
coverage / low force, a narrow statute reads the inverse.

**Not done.** Mechanisms still gate coverage DOWNWARD only. A promotion path
was tried before and shipped wrong verdicts on three countries (see the note in
`coverage_from_profile`); breadth must never buy a force verdict.

### Responsible agency was always empty

**Problem.** The implementation section never named a body.

**Fix.** Three compounding causes. `"ai"` was in `_MODULE2_AGENCY_SKIP` so any
agency with "AI" in its name was discarded. PDF text extraction breaks words
("Off ice", "Ar ticle") so exact matching failed — added `_ocr_tolerant_phrase`
and `_has_named_body_keyword_ocr`. And `re.finditer` is non-overlapping, so
"The Personal Information Protection Commission" consumed the span and the
actual name was never seen — now strips leading filler instead of discarding
the match. Added `document_named_bodies()` to feed real candidates into the
prompt.

### Korea Human Autonomy wrongly Missing

**Problem.** Article 34(1)(4) says "Human management and supervision" — the
vocabulary had none of those bigrams.

**Fix.** Added `human management / supervision / intervention / review /
monitoring / judgment / judgement` to Human Autonomy core terms. Checked
against the real Korean AI Framework Act.

### The chat surfaces could not describe the instrument they belong to

**Problem.** Three separate failures, all producing a confident non-answer.

"Why eight dimensions and not more?" returned *"the retrieved policy context
does not contain evidence detailing why an 8-dimension model is used"* — no
document in the corpus describes Meridian, so a question about the method had
nothing to retrieve. "What frameworks do you use?" riffed generically instead
of naming the 33 indexed sources. And the Rapporteur, asked which dimension
came out strongest, replied that the context held *"no specific policy
evaluation or scorecard"* and then drifted into unrelated material about
compute capacity — because `main.py` passed only `{"gaps": {...}}`, so
`decision_analytics` (coverage index, binding share, `strongest_dimension`)
never reached the prompt at all.

**Fix.** `src/meridian_facts.py` states the method as prompt context, with
every countable fact DERIVED from the live constants — dimension list, tier
labels, stage scores, the 45-mechanism vocabulary, and the roster read from
`get_framework_library`. A hand-typed description drifts the first time a
threshold moves. `src/analysis_brief.py` compacts the open run — eight
verdicts, both indices, mechanism and binding counts — into context for
cross-dimension questions. Both are attached by intent, not on every turn.

Note the roster reads the frameworks CONFIG, not vector-store metadata: a
metadata scan also sweeps up every uploaded country document and each name
variant a sync has written, which is how the first version answered "97
sources" for a library of 33.

**Also fixed alongside it.**
- The Rapporteur read `analyses[0]` — the newest run — whatever the run
  selector showed, so every two-run country was answered from the wrong one.
  `analysis_id` now flows from the selector through `ChatProvider`.
- A typed "why is Fairness Partial" never built a reasoning trail; only the
  "Ask about this finding" button did. So the most common phrasing — and the
  one that asks "what proof do you have" — reached the model with the verdict
  and none of the evidence.
- **False premises were being agreed with.** Asked "why is Human Autonomy
  partial" on a run where it scored Covered, the model argued the case for
  Partial. It now corrects the premise in the opening sentence. This one
  matters more than it looks: a leading question is the easiest way to get a
  wrong verdict in front of a reader.

**Deliberately NOT built.** Comparison questions ("how does this fare against
the EU AI Act", "what should it improve", "best implementation plan") are
declined and handed to the Analysis section. A hybrid document+framework
retrieval path was built for them first and then removed: answering from a
handful of retrieved passages means producing verdicts and recommendations
outside the scored pipeline, ungrounded in the force ladder — a second source
of verdict truth, which is the exact failure this codebase keeps eliminating.
The referral returns in 0.1s with no LLM call.

### Chat latency had no ceiling

**Problem.** The requirement is under 30s always, ~20s average. Measured
overhead was already fine (0.1–1.6s; retrieval is not the cost) but the LLM
ran 4–19s, and two settings made the tail unbounded: `CHAT_MAX_OUTPUT_TOKENS`
was 2048 against prompts that ask for ~140 words, and the 429 path could
`time.sleep` for up to **120 seconds** — a retry ladder written for the
analysis pipeline, where waiting beats losing a run. On a chat turn someone is
watching a spinner.

**Fix.** Output cap to 1024, and a `CHAT_DEADLINE_SECONDS` wall-clock budget
(24s) checked before each attempt and before every backoff sleep. A sleep that
would leave no room for the retry it precedes is refused rather than taken.
Past the budget it raises `ChatDeadlineExceeded` and the caller degrades to its
template reply, which every chat path already handles.

Measured after: n=25, **avg 7.7s, max 20.4s**, none over 30s.

### Chat blocked the event loop

**Problem.** Auditor and Rapporteur took far too long on basic questions. A
sync `chat_fn` was being called inside an `async def`, stalling every other
request.

**Fix.** Wrapped in `asyncio.to_thread`. Also bounded `_session_contexts` with
an LRU cap of 500, and made `_known_framework_names` a single-pass size-keyed
build.

### The frameworks endpoint did 33 queries

**Fix.** `_framework_chunk_counts(vector_store)` — one pass, cached on
collection size. 4.5s (19.6s on a larger corpus) to 0.02s.

### The progress poller never stopped

**Problem.** Estimated time displayed forever; the run never reported complete
until the page was reloaded. The interval id was stored in React state and the
effect had an array dependency, so each render cancelled and recreated the
poller.

**Fix.** A `hasActiveRun` / `isRunActive` boolean drives the interval. No
interval id in state.

### Migrations shared one transaction

**Problem.** `ALTER TYPE ... ADD VALUE` cannot run inside a transaction block
and aborted every other migration with it.

**Fix.** Each migration gets its own AUTOCOMMIT connection.

### The AI Auditor leaked raw markdown

**Fix.** `MarkdownLite.tsx` renders `**bold**`, `*italic*`, `` `code` ``,
lists and headings without `dangerouslySetInnerHTML`.

## Things we deliberately did NOT change

- `provider_router` key rotation is correct. An earlier claim that it had a
  rotation bug was wrong and is retracted — do not re-open it.
- `undp-contrib/rapida` is out of scope. Do not read or touch it.
- `_SUBREFERENCE_KINDS` (Clause, Paragraph) stay excluded from the narrative
  citation check; they are too generic to verify reliably.
- Only `fabricated_citations` render. `unsupported` stays computed but hidden.
- The instrument measures **enforceable rights only**. This is a scope choice,
  not a gap — but it still needs a README caveat so a reader does not mistake
  it for an omission.

## Known bugs / open issues

1. **`GEMINI_RPD_LIMIT=1000` is a local guess** that does not match Google's
   real per-model daily quota. The counter read 146/1000 while all five keys
   were already returning 429, so the app burns keys instead of halting the run
   early. Set it to the model's actual limit.
2. **The Groq fallback cannot serve analysis.** Prompts are ~16k tokens against
   an 8,000 TPM org limit, so it returns 413 every time it is actually needed.
   Treat it as if no fallback exists until the tier or prompt size changes.
3. **India workspace holds stale partial rows** — the two identical 5/8
   partials from the quota-exhausted run are still there alongside the two
   good runs, so the selector shows five. Deleting them is still open.
4. **EU stored score is stale** (79.2, predates the maturity fixes).

## Dataset state

One workspace per country. A workspace holds N documents and M runs; each run
records which documents it covered, so a country can be scored "guidelines
only" then "guidelines + statutes" for comparison. That two-run pattern is
intentional and should be preserved for every country.

| Country | Status |
| --- | --- |
| EU | AI Act, 79.2 stored, needs re-run (projected ~91) |
| Japan | Run 1 guidelines 57.0; run 2 + both acts 75.8 |
| Korea | Verified against the real AI Framework Act |
| India | Run 1 guidelines 60.5; run 2 + DPDP Act 63.2, 46/46 citations, complete |
| Brazil, Kenya, Nigeria/Zambia | Documents not yet supplied |

### India detail

Workspace `0a664e4c-c8d8-4b17-a9df-35cc0ff7b748`.

Run 1, `India AI Governance Guidelines.pdf`, 48/48 citations, maturity 60.5.
Run 2 adds `DPDP Act 2023.pdf`: **46/46 citations, 8/8 assessed, maturity
63.2**, no fabricated citations, no failed dimensions.

```
                Run 1 (guidelines)          Run 2 (+ DPDP Act)
Transparency    Covered Operationalized     Covered Operationalized
Accountability  Covered Institutionalized   Covered Institutionalized
Privacy         Partial Operationalized     Covered Institutionalized
Safety          Covered Operationalized     Covered Operationalized
Human Autonomy  Partial Emerging            Partial Emerging
Inclusivity     Partial Emerging            Partial Emerging
Fairness        Partial Emerging            Partial Emerging
Environmental   Missing Unaddressed         Missing Unaddressed
```

Privacy moving to Covered / Institutionalized is exactly what adding the DPDP
Act was meant to exercise, and `document_enforcement_regime` returns true for
the workspace, which is what carries it there on one enforceable finding.

**Why 63.2 and not ~80, and why that is the right answer.** Stage scores give
`78+100+100+78+50+50+50+0 = 506 / 8 = 63.2`. Environmental at 0 costs 12.5
points alone; the three Emerging dimensions cost another 10.5 against
Operationalized. Environmental alone reaching Operationalized gives 73.0, the
three Emerging alone 73.8, both 83.5.

The structural reason is that the ladder measures enforceable normative force
and India has no binding AI-specific instrument. Verified directly against the
documents: the Guidelines contain **zero** "shall", 23 "should", 14
"recommend", 5 "voluntary", zero penalties and zero "right to"; the DPDP Act
contains 146 "shall", 15 penalty references and 12 "right to" but reaches only
the data-adjacent dimensions. Human Autonomy, Fairness, Inclusivity and
Environmental have no enforceable backing in India at all — confirmed by term
counts (zero occurrences of human review, automated decision, protected
characteristic, fairness metric, energy, carbon or e-waste in either file).

Scoring India near 80 on these two documents would mean treating aspiration as
obligation, which is the failure mode this instrument exists to avoid. The
EU / Japan / India spread of ~91 / 75.8 / 63.2 is evidence it discriminates.

The verdicts were independently checked against the source text and are not
model error. The three bugs found alongside them were all in the REPORTING
layer — citations and prose — and none of them moved a verdict: run 2 produced
identical coverage and maturity before and after the fixes.

## Next planned steps

1. Delete the two stale partial analysis rows so India shows exactly two runs.
2. Re-run EU to pick up the maturity fixes.
3. Fix `GEMINI_RPD_LIMIT`; decide what to do about the Groq fallback.
4. Obtain documents for Brazil, Kenya, Nigeria and run them.
5. Write the scope note / README caveat on measuring enforceable rights only.

## Working constraints

- Downloads: if a file is needed, ask — the user downloads it and it appears in
  their Downloads folder. Check only the **top 7 most recent** files, no more,
  and ask before previewing anything.
- Prose style: at most 1–2 bolded words per paragraph. No clutter.
- Code must not read as generated. Match surrounding style, comment density and
  naming.
- Anything destined for UNDP (e.g. the RAPIDA PR) must leave no AI trail.
- Do not go near the `rapida` / crisis-mapping files.

## Test status

708 passed, 1 skipped. `tsc` clean.

Structural guards worth knowing about: `test_verdict_single_source.py` (AST,
prevents duplicate verdict logic), `test_chat_guards.py`,
`test_responsible_agency.py`, `test_risk_framing.py`,
`test_division_vocabulary.py`, `test_human_autonomy_vocabulary.py`,
`test_brief_depth.py`, `test_candidate_bodies.py`,
`test_chat_knowledge.py` (which context a question attracts — routing was the
part that was wrong, not the model).
