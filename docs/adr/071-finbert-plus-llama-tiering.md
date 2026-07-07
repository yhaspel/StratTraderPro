# ADR-071 — A two-tier FinBERT → Llama scoring stack

**Date:** 2026-07-07
**Status:** Accepted
**Milestone:** M07 — Sentiment Pipeline
**Reference:** `project-plan/07-sentiment-pipeline.md` §6.3 (FinBERT worker), §6.4
(Llama worker + routing), §6.5 (aggregation), §2/§4 (graceful degradation);
AC-07-3, AC-07-4, AC-07-5, AC-07-8, AC-07-10

## Context

Two different questions are hiding inside "score this article":

- **Which way, cheaply, for everything.** Every ingested article needs a fast
  directional read so the per-symbol and market-wide aggregates stay current.
  That is a bulk, latency-sensitive, high-volume job.
- **How much does this actually matter, in detail, for the few that do.** An 8-K,
  a trading halt, or a guidance cut wants a *structured* read — direction plus an
  impact magnitude, a horizon, and a summary — that a 3-class classifier can't
  produce. That is a low-volume, expensive, high-value job.

Running the expensive structured model on **every** article would blow the
latency and cost budget (ADR-070: a local 8B on CPU is ~2.6 s/article estimated)
for no benefit on the 90%+ of articles that are routine. Running **only** the
cheap classifier loses the impact/horizon signal that downstream sizing (M08)
actually wants. Neither model alone is the answer.

## Decision

Score in **two tiers**: FinBERT on **every** article for a fast 3-class polarity,
then Llama on **only** the articles that are material or that FinBERT is unsure
about, for the structured read. The tiering is a single routing predicate, the
LLM tier is independently disable-able, and every failure mode of the second tier
degrades to the first.

### 1. The two tiers

**Tier 1 — FinBERT, every article** (`score_article` in
`backend/apps/sentiment/routing.py`, §6.3). `get_finbert().score(title + body)`
returns `{positive, negative, neutral}` (summing to 1) + the argmax `label` +
`confidence`. We store one `ArticleScore(model=FINBERT)` row with
`polarity = positive − negative ∈ [-1, 1]`, and mark `NewsArticle.tier1_scored`.
Target: every new article scored within 60 s of ingestion (AC-07-3);
`sentiment_articles_scored_total{tier="1",result="ok"}` increments.

**Tier 2 — Llama, routed only** (`_score_tier2`, §6.4). For routed articles,
`get_llama().score(title, body)` returns the structured
`{sentiment, impact (0–10), horizon_days, summary}`. We store a second
`ArticleScore(model=LLAMA)` row whose `polarity` is the direction scaled by
impact (`±1.0 × impact/10`), mark `tier2_scored`, and write an `LLMInferenceLog`
row (metadata only — never the body or output, AC-07-12).

### 2. The routing rule, and the fallback paths

The routing predicate is a single line (`routing.py`):

```
routed = article.material  OR  finbert.confidence < 0.7
```

- **`material`** is set at ingest (`services.is_material`): the `EDGAR` and
  `NASDAQ_HALTS` sources are always material, plus a regex over the title/body
  for `8-K`, `halt(ed)`, `guidance`, `profit warning`, `bankruptcy`, `SEC
  filing`. This guarantees a high-impact item reaches Tier 2 **even when FinBERT
  is highly confident** (§10.1 routing test) — a confident-but-consequential 8-K
  must not skip the structured read.
- **`confidence < 0.7`** catches the articles FinBERT itself is unsure about,
  where the structured model is most likely to add signal.

Three things can go wrong in Tier 2, and each falls back to the FinBERT score
already on the article:

| Tier-2 outcome | Handling | Metric |
|---|---|---|
| **LLM worker disabled/down** | `get_llama()` returns `None` → Tier 2 skipped, FinBERT stands (§3). | — |
| **Inference raises** | caught; warn (no body logged); FinBERT stands. | `…scored_total{tier="2",result="error"}` |
| **Output fails JSON schema** | `parse_llama_json` → `valid=False`; the Tier-2 row is **not** written, FinBERT stands. | `llm_invalid_responses_total`, `…{tier="2",result="invalid"}` |

The plan (§6.4) specifies **retry-once before the FinBERT fallback** on an invalid
response; the built `_score_tier2` currently takes the FinBERT fallback on the
first invalid parse (a single inference attempt), which is the safe end state —
the article always keeps a valid FinBERT score. Adding the intermediate retry is
a small, isolated change if the invalid-response rate warrants it (see the §12
`llm_invalid_responses > 5%/hr` alert). Either way the invariant holds: **a
Tier-2 miss never loses the article — it degrades to Tier 1.**

### 3. FinBERT-only graceful degradation is a first-class path (AC-07-10)

`LLM_WORKER_ENABLED` (default `False`) gates the whole second tier.
`get_llama()` returns `None` whenever it is off, so `_score_tier2` returns
immediately and the pipeline runs **FinBERT-only** — no error, no retry, no
queue growth on an `llm` queue that isn't being drained. `routing.llm_degraded()`
surfaces this state, and the market API (`SentimentMarketView`) returns
`"degraded": true` so the dashboard can render the degraded banner. This is the
whole point of tiering: the expensive, fragile half can be **switched off
entirely** (an outage, a cost freeze, or the descope in §5) and the system keeps
producing valid, always-available sentiment from the cheap half. Turning
`LLM_WORKER_ENABLED` back on resumes Tier 2 with no other change.

### 4. Aggregation — per-symbol EWMA + market-wide cap-weighted (§6.5)

`backend/apps/sentiment/aggregator.py` rolls the per-article scores up over a
**24 h window** (`WINDOW_MINUTES = 1440`):

- **Per symbol:** an EWMA of each article's `polarity`, weighted by recency with
  a **6 h half-life** — `weight = 0.5 ^ (age_hours / 6)` (`ewma`,
  `aggregate_symbol`). Recent news dominates; a day-old item is down-weighted
  ~16×. Impact is the mean of the Llama impacts in the window. Stored as
  `SentimentScore(scope="SYMBOL:XXX")` (AC-07-5).
- **Market-wide:** a **market-cap-weighted** average of the per-symbol EWMA
  polarities (`aggregate_market`), stored as `SentimentScore(scope="MARKET")`
  with `components.tier2_count` so the API can show how much of the read came
  from Tier 2. In the built code the weight is a `TickerRegistry`-id **placeholder**
  standing in for cap; loading real S&P 500 caps weekly is a deferred external
  (noted inline in `aggregate_market`).

Both are recomputed by the `aggregate_sentiment` beat task every 5 min over the
symbols seen in the window.

### 5. The descope lever — FinBERT-only MVP

The plan's kickoff note (2026-07-05) calls Llama-8B latency the milestone's
wildcard: benchmark Q4_K_M tokens/sec on the real worker on Day 1, and **if p95
per-article > 5 s, ship FinBERT-only for MVP and keep Tier 2 behind its flag.**
This design makes that a *config* decision, not a code change: leave
`LLM_WORKER_ENABLED=false` and the pipeline is a complete, shippable FinBERT-only
product with the degraded banner on; flip it on once the benchmark clears. The
tiering exists precisely so this lever is free.

## Consequences

**Positive:**

- **Cost and latency track value.** The expensive model runs on the ~small
  fraction of articles that are material or uncertain; the cheap model keeps the
  aggregates current for everything. AC-07-8's ~200 Tier-2/day budget is a
  consequence of the routing rule, not a hope.
- **Every second-tier failure is absorbed.** Disabled, raised, or invalid — all
  three collapse to the FinBERT score. The system has no state in which a routed
  article ends up unscored.
- **Degradation is a switch, not an incident.** FinBERT-only is one flag and is
  the same code path the descope uses. The dashboard already knows how to show it.

**Negative / honest limits:**

- **The retry-once step in §6.4 isn't wired.** The built routing falls back to
  FinBERT on the first invalid parse. This is safe (never loses a score) but
  slightly less generous than the plan; worth adding only if the invalid-response
  alert fires in practice.
- **Market weighting is a placeholder.** Cap-weighting uses a registry-id stand-in
  until the weekly S&P 500 cap load lands (deferred). The *shape* is
  cap-weighted; the *weights* aren't yet real caps.
- **The routing threshold (0.7) and the material regex are hand-tuned.** They
  encode our priors about what deserves the expensive tier, not a learned policy.
  They're cheap to adjust (`_CONF_THRESHOLD`, `_MATERIAL_RE`) but unproven against
  a live tape until the deferred benchmark and real feeds run.

## Alternatives considered

1. **FinBERT only.** Rejected as the *target* (kept as the MVP/descope floor and
   the degradation path): fast and robust, but no impact/horizon/summary for M08
   sizing. It is deliberately the graceful-degradation floor, not the ceiling.
2. **Llama on every article.** Rejected: blows the latency/cost budget (§6.4) for
   no benefit on routine articles, and would make AC-07-8's throughput target
   unreachable.
3. **A single mid-size instruction model for both tiers.** Rejected: FinBERT is a
   purpose-built financial 3-class model that is cheap enough to run on
   everything; collapsing the tiers would either over-spend on Tier 1 or
   under-deliver on Tier 2's structure.
4. **Confidence threshold only (drop the `material` override).** Rejected: a
   confident-but-consequential 8-K/halt would skip the structured read exactly
   when it matters most. The `material` OR-clause is the guard against that.

## See also

- ADR-070 — why the Tier-2 model is a local Llama, and the flag/fake design
- `docs/runbooks/llm-worker-cold-start.md` — verifying Tier-2 is producing scores
- `docs/runbooks/sentiment-queue-backlog.md` — backlog + invalid-response alerting
- `backend/apps/sentiment/routing.py` — the routing rule + the three fallbacks
- `backend/apps/sentiment/aggregator.py` — EWMA + cap-weighted aggregation
- `project-plan/07-sentiment-pipeline.md` §6.3–§6.5, kickoff note (2026-07-05)
