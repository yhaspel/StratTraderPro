# Runbook — sentiment queue backlog / unscored articles

**Owner:** Yuval
**Status:** Executable checklist — the ingest → score → aggregate pipeline, the
`sentiment_queue_depth` gauge, the `queue_backlog()` helper, and the FinBERT-only
degradation are built and unit-tested (M07, AC-07-9 / AC-07-10) with the **canned
fakes**. Live feeds and the real `llm-worker` are **deferred externals** (per-source
ToS review + the gated weight download); the alerting logic and the recovery levers
below are exercised in CI against fixtures.
**Companion docs:** `docs/adr/071-finbert-plus-llama-tiering.md` (the tiers +
degradation this operationalizes — read §2/§3 first),
`docs/runbooks/llm-worker-cold-start.md` (if Tier-2 specifically is the problem),
`project-plan/07-sentiment-pipeline.md` §6.1, §6.4, §12; AC-07-9.

## The one thing to know first

**A backlog is a throughput problem, not an outage.** Fetchers keep persisting
`NewsArticle` rows every 15 min regardless of whether the scorer keeps up; unscored
articles simply queue on `tier1_scored=false` and get picked up by the next
`score_pending_articles` run. The dashboard keeps serving the **last** aggregates,
so users see slightly stale sentiment, not errors. This runbook is about sizing the
backlog, finding *why* the scorer fell behind, and draining it — and, if one
article is poisoning the batch, removing it.

## How the pipeline flows (§6.1, §6.4)

Three beat tasks (`apps.sentiment.tasks`, cadence in `CELERY_BEAT_SCHEDULE`):

1. **`ingest_news`** — every **15 min** (`SENTIMENT_INGEST_INTERVAL_SECONDS=900`).
   Pulls each fetcher, persists with sha256(url+title) dedup. One bad source is
   caught and skipped so it can't stop the others.
2. **`score_pending_articles`** — every **120 s**. Takes up to **200**
   `tier1_scored=false` articles oldest-first, FinBERT-scores each (+ routes
   material / low-confidence ones to Tier 2), then **sets
   `sentiment_queue_depth{queue="finbert"}`** to the remaining unscored count.
3. **`aggregate_sentiment`** — every **5 min**. Recomputes per-symbol EWMA +
   market-wide from the scored rows.

The backlog lives at step 2: if articles arrive faster than 200-per-120s can score
them, or the scorer stalls, `tier1_scored=false` grows.

## Symptoms / when to open this

- **Alert: backlog `depth > 500` OR oldest unscored `> 30 min`** (§12, AC-07-9) —
  the primary trigger. Backed by the `sentiment_queue_depth{queue="finbert"}` gauge
  and the `queue_backlog()` helper:

  ```python
  # manage.py shell
  from apps.sentiment.tasks import queue_backlog
  print(queue_backlog())   # {"depth": N, "oldest_age_min": M, "alert": bool}
  ```

  `alert` is `True` exactly when `depth > 500 or oldest_age_min > 30`.
- **Alert: `llm_invalid_responses_total` > 5% / hr** (§12) — Tier-2 output failing
  the JSON schema. Not a backlog per se (invalid responses fall back to FinBERT,
  ADR-071 §2), but a sign the LLM tier is misbehaving — cross-link
  `docs/runbooks/llm-worker-cold-start.md`.
- **Alert: fetcher error rate > 10% / hr** (§12) — a source is failing. `ingest_news`
  skips a failing source (logs `news.fetch.error`), so this shows as
  `news_articles_ingested_total{source}` flat-lining for one source while others
  climb — usually a feed URL / ToS / auth issue, not a backlog.

## Step 1 — Size the backlog

| Signal | What it tells you |
|---|---|
| `queue_backlog()["depth"]` / `sentiment_queue_depth{queue="finbert"}` | How many articles are unscored right now. A few hundred that drains within a couple of `score_pending_articles` cycles is normal churn; a monotonically climbing depth is a stuck or under-scaled scorer. |
| `queue_backlog()["oldest_age_min"]` | Age of the oldest unscored article. Rising past 30 min means the scorer isn't reaching the tail — either it's not running, or intake outruns it. |
| `sentiment_articles_scored_total{tier="1",result="ok"}` | If this is flat while depth climbs, the scorer **isn't running** (beat/worker health). If it's climbing but depth still grows, intake simply outruns throughput (Step 3). |

## Step 2 — Inspect the unscored rows

Look at *what* is stuck — a uniform backlog (scale it) vs. a pile from one source
or one giant body (a poison article):

```python
# manage.py shell
from apps.sentiment.models import NewsArticle
qs = NewsArticle.objects.filter(tier1_scored=False).order_by("fetched_at")
print(qs.count())
for a in qs[:10]:
    print(a.id, a.source, a.fetched_at, len(a.body), a.material, a.title[:60])
```

- **Even spread across sources, recent** → throughput; Step 3.
- **All from one `source`** → that fetcher dumped a burst, or a source is
  malformed; still drains, just scale to catch up.
- **One very old row that never clears while newer rows behind it do** → a **poison
  article** (Step 4) — `score_pending_articles` orders oldest-first, so a single row
  that reliably fails will sit at the head every cycle.

## Step 3 — Drain / scale the scorer

**Kick a drain now** (safe, idempotent — it just scores the oldest unscored batch):

```python
# manage.py shell
from apps.sentiment.tasks import score_pending_articles
print(score_pending_articles(limit=500))   # {"scored": N}; raise limit to catch up
```

Re-run until `queue_backlog()["depth"]` falls. If it keeps refilling faster than it
drains, throughput is the issue:

- **Scale the `sentiment` worker** — add replicas / concurrency so more
  `score_pending_articles` work runs in parallel (§6.3 targets ≥ 500 FinBERT
  articles/hr per replica). FinBERT is the bulk tier; more replicas is the lever.
- **Shorten the interval** — lower `SENTIMENT_SCORE_INTERVAL_SECONDS` (default 120)
  and/or raise the per-run `limit` (default 200) so each cycle clears more.
- **If Tier 2 is the drag** (material-heavy burst, slow Llama), that's a separate
  problem — the FinBERT tier and the queue gauge are Tier 1; check
  `llm_inference_latency_seconds` and consider FinBERT-only via
  `LLM_WORKER_ENABLED=false` (`docs/runbooks/llm-worker-cold-start.md` Step 5).

## Step 4 — Clear a poison article

If one row keeps failing and blocking the oldest-first batch, take it out of the
queue. Scoring FinBERT-side rarely raises (the fake/real scorer handles any string),
so a true poison is usually a data problem — mark it scored to skip it, or delete it
if it's junk:

```python
# manage.py shell
from apps.sentiment.models import NewsArticle
a = NewsArticle.objects.get(id=<id>)        # the stuck row from Step 2
# Option A — skip it (keep the record, take it out of the unscored queue):
NewsArticle.objects.filter(pk=a.pk).update(tier1_scored=True)
# Option B — it's junk (bad ingest): delete it; its scores/logs cascade.
# a.delete()
```

Both are also doable in the Django admin. After either, re-run
`score_pending_articles` — the tail should now clear.

## Step 5 — Verify recovery

- `queue_backlog()["depth"]` falling and `["oldest_age_min"]` back under 30;
  `queue_backlog()["alert"]` is `False`.
- `sentiment_queue_depth{queue="finbert"}` trending down.
- `sentiment_articles_scored_total{tier="1",result="ok"}` climbing steadily.
- `aggregate_sentiment` has run since the drain, so `GET /api/v1/sentiment/market/`
  shows a fresh `produced_at`.
- The backlog alert clears.

## Note on the deferred externals

The pipeline, the `sentiment_queue_depth` gauge, `queue_backlog()`, the drain task,
and the FinBERT-only fallback are all proven in unit tests **against the canned
fakes and fixture articles** — no live feed and no real weight run in CI. The **live
news feeds** (pending the per-source ToS review — Benzinga/Finnhub/Yahoo) and the
**real `llm-worker`** (the gated GGUF download + Day-1 benchmark) are **deferred
externals** (ADR-070, ADR-071). This runbook becomes fully live once feeds and the
worker are wired; the backlog/alert logic itself does not change.
