# Runbook — llm-worker cold start / bringing up Tier-2

**Owner:** Yuval
**Status:** Executable checklist — the tiered scorer, the flag gating, the
FakeScorer default, and the FinBERT-only degradation are built and unit-tested
(M07, AC-07-4 / AC-07-10) with the **canned fakes**. The **real `llm-worker` with
downloaded weights is a deferred external** — the gated Meta-Llama-3.1-8B GGUF +
`ProsusAI/finbert` download (accept the HF/Meta license, pin the SHA-256) and the
Day-1 tokens/sec benchmark have **not** run. This runbook applies the moment the
weights are on the volume and the flags are flipped.
**Companion docs:** `docs/adr/070-local-llm-sentiment.md` (the local-LLM +
flag/fake decision this operationalizes — read §1/§2 first),
`docs/adr/071-finbert-plus-llama-tiering.md` (the tiering + degradation),
`docs/runbooks/sentiment-queue-backlog.md` (if the worker is up but the queue is
growing), `project-plan/07-sentiment-pipeline.md` §5, §6.4, §12.

## The one thing to know first

**Everything works with no weights.** By default (`SENTIMENT_FAKE_SCORERS=true`,
`LLM_WORKER_ENABLED=false`) the pipeline runs the deterministic `FakeFinBert` /
`FakeLlama` and, with the LLM flag off, FinBERT-only. So "sentiment scores exist
but there are no Tier-2 rows" is the **expected default state**, not a fault. This
runbook is about the deliberate step of turning the *real* Llama tier on — mounting
the GGUF, flipping the flags, absorbing the cold-start load, and confirming real
Tier-2 rows are landing — and about falling back if it misbehaves.

## The flags that decide what runs (ADR-070 §2)

| Flag | Default | Turn it to | To get |
|---|---:|---|---|
| `SENTIMENT_FAKE_SCORERS` | `true` | `false` | Real models instead of the canned fakes. **Required** for any real scoring. |
| `FINBERT_ENABLED` | `false` | `true` | Real `ProsusAI/finbert` (transformers) instead of `FakeFinBert`. |
| `LLM_WORKER_ENABLED` | `false` | `true` | The Tier-2 Llama tier on at all. Off ⇒ FinBERT-only (AC-07-10). |
| `LLAMA_GGUF_PATH` | `/models/…Q4_K_M.gguf` | volume path | Where `LlamaScorer` loads the GGUF from. |

Read together:

- **All defaults** → fakes, FinBERT-only. CI and local dev. No weights.
- **`FINBERT_ENABLED=true` + `SENTIMENT_FAKE_SCORERS=false`, LLM off** → real
  FinBERT, no Tier 2. The FinBERT-only production shape (and the §5 descope).
- **All three on, fakes off** → the full real two-tier stack. Set **only** on the
  dedicated `llm-worker` service.

## Step 1 — Put the weights on the volume (deferred external)

The `llm-worker` service has a **persistent volume** holding the GGUF; weights are
**volume-mounted, not baked into the image** (DoD §5, ADR-070 §1).

1. Download the **gated** `Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf` and
   `ProsusAI/finbert` from an **authenticated Hugging Face** path, having accepted
   the Meta Llama-3.1 community license and the FinBERT license (§11).
2. **Pin + verify the SHA-256** of the GGUF before it goes live — a mismatch means
   the wrong/tampered weight; do not run it.
3. Place the GGUF on the mounted volume at `LLAMA_GGUF_PATH`
   (`/models/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf` by default). The spaCy model
   (`en_core_web_sm`) is downloaded in the worker image build, not to the volume.

The image itself must stay **≤ 6 GB** (§5) — it carries the `ml-worker.txt` runtime
(`transformers[torch]`, `llama-cpp-python`, `spacy`), **not** the weights.

## Step 2 — Flip the flags on the llm-worker service only

On the `llm-worker` Railway service env (not the base backend):

```
SENTIMENT_FAKE_SCORERS=false
FINBERT_ENABLED=true
LLM_WORKER_ENABLED=true
LLAMA_GGUF_PATH=/models/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf
```

Redeploy / restart the worker so the settings are picked up. Leave the base
backend on its defaults — only the dedicated worker carries the heavy deps and the
flags.

## Step 3 — Absorb the cold start (first-load latency is expected)

`LlamaScorer` loads the GGUF **lazily on the first score call** into a class-level
singleton (`LlamaScorer._llm`), constructed with `n_ctx=4096`, `n_threads=4`. So:

- The **first** Tier-2 article after a worker (re)start pays the full multi-GB GGUF
  load into RAM — seconds to tens of seconds — then every subsequent article reuses
  the loaded model. `FinBertScorer` lazy-loads its transformers pipeline the same
  way on its first call.
- A cold worker therefore shows a one-off latency spike, then settles. Don't read
  the first `llm_inference_latency_seconds` sample as steady state.
- **Watch memory on first load.** An 8B GGUF plus `n_ctx=4096` is the OOM risk in
  the plan's risk table (§16); if the worker OOMs on load, the fix is a smaller
  context / batch or a larger worker, not a code change.

## Step 4 — Verify real Tier-2 scores are landing

Confirm the worker is actually producing Tier-2 rows, not just running FinBERT:

- **`LLMInferenceLog` rows** are being created — one per Tier-2 attempt (metadata
  only: `prompt_version`, `valid`, `latency_ms` — never the body/output, AC-07-12):

  ```python
  # manage.py shell
  from apps.sentiment.models import LLMInferenceLog, ArticleScore
  print(LLMInferenceLog.objects.order_by("-created_at")[:5].values("valid", "latency_ms", "prompt_version"))
  print(ArticleScore.objects.filter(model=ArticleScore.Model.LLAMA).count())  # > 0 once Tier 2 runs
  ```

- **`llm_inference_latency_seconds`** (histogram) is observing samples, and
  **`sentiment_articles_scored_total{tier="2",result="ok"}`** is climbing.
- **`GET /api/v1/sentiment/market/`** returns `"degraded": false` (Tier 2 is on).
- A material article (an 8-K, a halt) has **both** a `FINBERT` and a `LLAMA`
  `ArticleScore` row with a populated `impact` / `summary`.

If `LLMInferenceLog` rows appear but `valid=false` dominates, that is the
invalid-response path (JSON failing the schema) — see the
`llm_invalid_responses_total` alert in `docs/runbooks/sentiment-queue-backlog.md`;
each invalid response falls back to the article's FinBERT score, so scores are
still produced.

## Step 5 — The FinBERT-only fallback (the safe state)

If the Llama tier misbehaves (OOM loops, bad latency, invalid responses) and you'd
rather run the always-available FinBERT tier, **turn Tier 2 off** — it is the
intended safe state, not an outage (AC-07-10, §15):

```
LLM_WORKER_ENABLED=false      # on the llm-worker service; redeploy/restart
```

`get_llama()` now returns `None`, `_score_tier2` returns immediately, and the
pipeline is FinBERT-only. `routing.llm_degraded()` becomes `true`, the market API
returns `"degraded": true`, and the dashboard shows the degraded banner. Nothing
queues up waiting for a worker that isn't draining. Flip it back to `true` to
resume Tier 2. This is also the plan's §5 descope lever if the Day-1 latency
benchmark shows p95 > 5 s.

## Step 6 — Verify recovery

- `sentiment_articles_scored_total{tier="2",result="ok"}` climbing; new
  `ArticleScore(model=LLAMA)` rows on material articles.
- `llm_inference_latency_seconds` settled below the first-load spike and within the
  benchmark budget.
- `GET /api/v1/sentiment/market/` → `"degraded": false`.
- `llm_invalid_responses_total` flat (invalid rate under the 5%/hr alert).

## Note on the deferred real-weights run

Everything above is proven with the **canned fakes** — the tiering, the flag
gating (`get_finbert` / `get_llama`), and the FinBERT-only degradation all have
unit coverage; CI never touches a weight. What has **not** run is the **real
`llm-worker` with downloaded weights**, which waits on the gated GGUF + FinBERT
download (SHA-256-pinned, authenticated HF) and the **Day-1 tokens/sec benchmark**
on the actual worker size (§6.4, §16). When it first runs, walk Steps 1–4 once end
to end, record the measured p95 per-article, and — per the plan's kickoff note —
if p95 > 5 s, stay FinBERT-only (Step 5) for MVP.
