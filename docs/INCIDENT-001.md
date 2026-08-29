# INCIDENT-001 — Provider capacity exhaustion under a 429 storm

**Date:** 2026-08-30
**Type:** Induced drill, not a production incident
**Provider:** Mocked. Zero Gemini quota consumed.
**Duration:** 12 failed calls, start to full recovery

Meridian has never run in production, so this is a deliberately induced
failure rather than a post-mortem of one that happened to us. The mechanism
is real: the same classifier, circuit breaker and readiness path the service
uses, driven by a fake provider that returns `429 RESOURCE_EXHAUSTED` with a
`Retry-After: 37` header. Inducing real 429s would have burned quota to prove
something a fake provider proves identically.

---

## What was broken on purpose

Three configured credentials, all healthy. Every subsequent call to every
credential returns 429 with a Retry-After header — the shape of a genuine
rate-limit storm rather than a single exhausted key.

## Timeline

| Point | Observation |
|---|---|
| t0 | 3 credentials healthy, 0 open, 3 requests recorded |
| wave 1 (3 failed calls) | 3 healthy, 0 open — **a single 429 does not drop a credential** |
| wave 2 (6 failed calls) | 3 healthy, 0 open |
| wave 3 (9 failed calls) | **0 healthy, 3 open** — all three circuits opened |
| detection | **0.002 s** after the first 429, at the 9th failed call |
| steady state | `next_available()` → `None`; `/readyz` reports `credentials_healthy: 0` → **503** |
| cooldown elapses | one probe admitted per credential (`provider_circuit_half_open`) |
| probe succeeds | `provider_circuit_closed`; credential back in rotation |

## What the signals showed

Every transition emitted a structured log event with the credential id and
the reason — not a `print()` to stdout, which is where all provider
behaviour used to go:

```
provider_circuit_opened   key_id=geminiprovider:0 kind=quota consecutive_failures=3 immediate=False
provider_circuit_half_open key_id=geminiprovider:0
provider_circuit_closed    key_id=geminiprovider:0 previous=half_open
```

`/readyz` flipped to 503 with `credentials_healthy: 0` while
`has_headroom: true` — the daily budget was untouched and nothing could
serve. That combination is the whole reason credential health was added to
readiness; before it, this state reported 200 and the service kept accepting
analyses it could not finish.

## Detection latency, honestly

**0.002 s** is the in-process figure and it flatters the system. The real
detection cost is **9 failed provider calls** — three consecutive failures
across three credentials. Against a live provider each of those is a network
round trip, so the wall-clock number would be seconds, not milliseconds. The
9-call figure is the one worth quoting.

That is the intended trade. `BREAKER_FAILURE_THRESHOLD = 3` exists because
one 429 is ordinary free-tier behaviour; dropping a credential on the first
one would take a healthy pool out of service constantly. Three consecutive
failures is a pattern.

## What this would have looked like before the breaker

The credential picker was `next_key()`, a plain round-robin. A credential
that 429'd was skipped for exactly that call and handed straight back on the
next pick. With `max_attempts = max(MAX_RETRIES, len(api_keys))`, every
operation spent its full retry budget re-asking credentials it had just been
told were exhausted, then fell through to a Groq fallback that cannot serve
analysis prompts anyway (~16k tokens against an 8,000 TPM limit → 413), and
reported `"All Gemini API keys exhausted"`.

Two things were wrong with that. It wasted the budget of every dimension in
the run, and the message it produced was also what a **mistyped model name**
produced — because a 404 was raised as `QuotaExceededError`. An operator
reading "all keys exhausted" could not tell whether to wait for quota or fix
one line of config.

## The fix, and what stops it recurring silently

1. **`src/provider_errors.py`** — one classifier, three outcomes: QUOTA,
   RETRYABLE, TERMINAL. A 404 or an invalid key is now TERMINAL: it opens
   that credential's circuit immediately, does not rotate, does not fall
   back, and logs `provider_terminal_failure`. Capacity problems and
   configuration problems no longer share a message.
2. **`src/key_health.py`** — a CLOSED/OPEN/HALF_OPEN breaker per credential,
   with per-credential request and token accounting persisted date-keyed
   across restarts.
3. **`CapacityExhausted`** carries a time: "retry after Ns", or "daily budget
   spent; retry tomorrow" when no timer will help.
4. **Readiness reads credential health**, so an exhausted pool stops traffic
   instead of accepting work that cannot finish.
5. **29 tests** in `tests/unit/test_provider_resilience.py` cover this
   scenario and the others — one credential out, all out, mid-run timeout,
   concurrent accounting, persistence across restart. The storm case asserts
   directly that a dropped credential is not re-asked.

## One thing the drill measured that the design did not intend

`seconds_until_any_available` reported **60 s** while the provider's
`Retry-After` header asked for **37 s**. The cooldown takes the *longer* of
our default and the provider's request, so we wait 60 s rather than 37 s.

This is safe but not free: it delays recovery by 23 s in this case. It is
deliberate — waiting longer than asked never causes a rate-limit violation,
and a provider that under-reports its own backoff would otherwise send us
straight back into the storm. Recorded here because it was surprising in the
output, and because a future change that tightens it should know it was a
choice rather than an oversight.

## Not covered by this drill

- Behaviour against the **live** provider under a real storm.
- A **partial** storm — some credentials healthy, others not — which is the
  more common real-world shape.
- Recovery when the daily budget, rather than a rate limit, is what is
  exhausted. That does not recover on a timer, and the code path returns
  "retry tomorrow" instead of a duration; it is unit-tested but has not been
  drilled.
