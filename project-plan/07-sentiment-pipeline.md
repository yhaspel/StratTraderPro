# Milestone 07 — Sentiment Pipeline

> **Week:** 7
> **Duration:** 5 working days
> **Depends on:** M06 (Market Data + Regime)
> **Unlocks:** M08 (Risk sizing uses sentiment as an input)

## 1. Purpose

Ingest breaking financial news, tag ticker symbols, score sentiment with a tiered model stack (FinBERT → local Llama), and expose both per-symbol and market-wide scores to downstream sizing and the dashboard. Built for **cost-predictable privacy**: runs entirely on our cloud infrastructure, no per-token LLM API fees.

## 2. In Scope

- News ingestion workers: FMP news, SEC EDGAR 8-K, Benzinga RSS, Nasdaq halts RSS, Finnhub free tier.
- Dedup by URL + title hash.
- Symbol tagger: regex + small spaCy NER model.
- FinBERT (ProsusAI/finbert) inference worker.
- Local Llama-3.1-8B (GGUF Q4_K_M) inference worker via `llama-cpp-python`.
- Tiered scoring: FinBERT for all articles; Llama for low-confidence or high-impact articles.
- Aggregation: EWMA per symbol (24h window), market-wide cap-weighted score.
- Sentiment API + dashboard widgets (market panel + per-symbol spark).
- Graceful degradation: LLM worker outage → FinBERT-only with banner.

## 3. Out of Scope

- Social media ingestion (Twitter/X, Reddit) — post-MVP.
- Image/video news — post-MVP.
- Fine-tuning FinBERT on our corpus — post-MVP.
- Per-language sentiment (English news only in MVP).

## 4. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-07-1 | News fetchers pull from all five sources every 15 min; dedupe works on title+url. |
| AC-07-2 | Symbol tagger achieves ≥ 90% precision, ≥ 85% recall on a curated 200-article test set. |
| AC-07-3 | Every new article receives a FinBERT score within 60s of ingestion. |
| AC-07-4 | Articles with FinBERT confidence < 0.7 OR tagged "material" (8-K, halt, guidance) are additionally scored by Llama; structured output contains `sentiment`, `impact`, `horizon_days`, `summary`. |
| AC-07-5 | `SentimentScore` rows upserted: per-symbol EWMA (half-life 6h), market-wide cap-weighted. |
| AC-07-6 | Dashboard shows current market sentiment score ∈ [-1, +1] with history line. |
| AC-07-7 | Clicking a symbol opens per-symbol sentiment + recent article feed. |
| AC-07-8 | LLM worker processes 200 "Tier 2" articles/day on CPU (4 vCPU / 8 GB RAM) without queue lag exceeding 10 min. |
| AC-07-9 | Queue depth alert fires when backlog > 500 articles or oldest unscored > 30 min. |
| AC-07-10 | If LLM worker is down, FinBERT-only pipeline continues; UI banner surfaces degraded state. |
| AC-07-11 | Article content retention: raw body kept 90 days, scores kept 1y, rolled up to daily after 30 days. |
| AC-07-12 | No article text or scoring output is logged at INFO level (PII / copyright concerns). |

## 5. Definition of Done

Baseline DoD applies, plus:

- LLM worker Docker image size ≤ 6 GB; model weights volume-mounted, not baked in.
- Prompt template for Llama versioned in code under `apps/sentiment/prompts/v1.md`.
- Inference costs monitored; monthly dashboard.
- Runbook `docs/runbooks/llm-worker-cold-start.md` committed.

## 6. Implementation Tasks

### 6.1 News fetchers (`apps/sentiment/fetchers/`)

One fetcher per source, all implementing:
```python
class NewsFetcher(Protocol):
    async def fetch_since(self, since: datetime) -> list[RawArticle]: ...
```

Fetchers:
- `fmp.py` — `/stable/news/stock-latest` and `/stable/news/press-releases-latest`.
- `edgar.py` — SEC EDGAR Atom feed for 8-K filings; pull linked filings, extract narrative.
- `benzinga.py` — RSS parse; fallback via `feedparser`.
- `nasdaq_halts.py` — RSS of trading halts; high-impact flag.
- `finnhub.py` — free tier headlines.

Celery task `sentiment.ingest_news` kicks each fetcher every 15 min; persists `NewsArticle` rows with dedup (unique on `sha256` of url+title).

### 6.2 Symbol tagger (`apps/sentiment/tagger.py`)

- First pass: regex on uppercase tickers `\b[A-Z]{1,5}\b` against a curated `TickerRegistry` (S&P 1500 + top ETFs).
- Second pass: spaCy `en_core_web_sm` NER for company names → map via `AliasTable` (`Apple Inc` → `AAPL`).
- Returns `symbols[]` + confidence per symbol.
- Rejects articles with 0 high-confidence symbols from being routed to Tier 2 (unless flagged material).

### 6.3 FinBERT worker (`apps/sentiment/workers/finbert.py`)

- Model: `ProsusAI/finbert` loaded once at process start.
- Transformers pipeline: `text-classification`, 3-class.
- Outputs: `{positive, negative, neutral}` with confidences summing to 1 + argmax class.
- Runs in the standard Celery `sentiment` queue worker (1 replica minimum).
- Throughput target: ≥ 500 articles/hr on CPU.

### 6.4 Llama worker (`apps/sentiment/workers/llama.py`)

- Dedicated Railway service `llm-worker` with a persistent volume holding the GGUF file.
- `llama-cpp-python` server-style with `n_threads=4`, `n_ctx=4096`.
- Model: `Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf`.
- Prompt template (versioned):
  ```
  You are a financial news analyst. Rate the sentiment impact of the news below on the affected ticker(s).
  Respond with ONLY valid JSON:
  {"sentiment": "POSITIVE|NEUTRAL|NEGATIVE", "impact": 0-10 integer, "horizon_days": int, "summary": "<=80 chars"}
  News:
  {{ title }}
  {{ body | truncate(1200) }}
  ```
- Response JSON-schema-validated; invalid response → retry once; second fail → fall back to FinBERT score.
- Triggering logic in `sentiment.route_articles` task: if article has `material=True` OR FinBERT confidence < 0.7 → enqueue on `llm` queue.
- Throughput on Railway 4-vCPU plan: ~30 tok/s × ~80 tokens ≈ 2.6s/article. 200 articles/day = ~9 min/day compute — plenty of headroom.

### 6.5 Aggregation (`apps/sentiment/aggregator.py`)

- Per-symbol EWMA of `polarity = pos - neg` with 6h half-life.
- Market-wide: weighted average of per-symbol scores weighted by S&P 500 market caps (updated weekly).
- Store as `SentimentScore(scope='SYMBOL:XXX'|'MARKET', polarity, impact, window_minutes=1440, produced_at)`.
- Channels event emitted on update: `sentiment.updated`.

### 6.6 API

```
GET /api/v1/sentiment/market/          → current market-wide + last 7d
GET /api/v1/sentiment/symbol/{sym}/    → current per-symbol + last 30d
GET /api/v1/sentiment/articles/?symbol&from&to → recent articles (paginated)
```

### 6.7 Dashboard widgets

- Market sentiment spark line (top of dashboard).
- Sector heatmap (11 GICS sectors; sentiment × average impact).
- "Recent impactful news" feed: top 10 by |impact|, click opens article detail modal.
- Per-symbol chips on the positions widget — small ▲▼ colored indicator per open position.

## 7. Tech Stack Notes

- **FinBERT** loaded via `transformers[torch]` CPU build.
- **`llama-cpp-python`** over `ollama` HTTP because it keeps the process in-tree with Celery worker lifecycle.
- **spaCy `en_core_web_sm`** is ~13 MB; light enough to bundle.
- Prompt versioning via file hash; logged with each inference so we can reproduce later.

## 8. Data Model Changes

Migrations:
- `sentiment.0001_initial` — `NewsArticle`, `SentimentScore`, `TickerRegistry`, `AliasTable`, `LLMInferenceLog`.

## 9. API Contract Changes

Paths per §6.6. `SentimentScore` response:
```json
{
  "scope": "MARKET",
  "polarity": 0.23,
  "impact": 2.4,
  "window_minutes": 1440,
  "produced_at": "2026-04-14T19:15:00Z",
  "components": {"articles_count":137,"tier2_count":22}
}
```

## 10. Test Plan

### 10.1 Unit tests

- Fetcher dedup on repeat article.
- Symbol tagger achieves ≥ threshold precision/recall on curated test set.
- FinBERT inference: sanity check on a handful of known positive/negative headlines.
- Llama prompt produces valid JSON (test doubles the LLM backend with a canned response).
- Aggregation EWMA half-life is mathematically correct.
- Routing logic: material article flagged even with high FinBERT confidence.

### 10.2 Integration

- End-to-end ingest → FinBERT → (tier-2 path) → aggregate → API fetch.
- Queue lag alert fires when a backlog is injected.
- LLM worker down → FinBERT-only path still produces scores.

### 10.3 E2E

- Dashboard shows market sentiment spark after ingesting a fixture news set.
- Per-symbol drill-down shows recent articles + scores.

### 10.4 Performance

- FinBERT: 500 articles/hr on CPU.
- Llama: 200 Tier-2 articles/day with queue lag < 10 min.
- API `/sentiment/market/` p95 < 120ms (cached).

### 10.5 Security

- Input length limited (1200 chars post-truncation) — prevent prompt injection from overly long bodies.
- LLM responses validated against a JSON schema; never `eval`'d.
- Article HTML stripped server-side before storing body.

## 11. Security Considerations

- **Prompt-injection defense:** Article bodies are untrusted. We wrap them in a clearly-delimited block and instruct the model to ignore any instructions inside. We also only accept the model's output if it parses as our JSON schema — we don't read arbitrary model output into the system.
- **Copyright:** We don't re-publish full article bodies; UI shows only our summary + a link to the source. Bodies stored internally for scoring only; 90-day retention.
- **Model provenance:** Only download Llama weights from an authenticated Hugging Face path; pin SHA-256; block at image-build time otherwise.
- **Licensing:** Llama-3.1 license reviewed; usage within StratTraderPro complies with community license for our user count.

## 12. Observability

- Prometheus:
  - `news_articles_ingested_total{source}`
  - `news_articles_deduped_total`
  - `sentiment_articles_scored_total{tier,result}`
  - `sentiment_queue_depth{queue}`
  - `llm_inference_latency_seconds` histogram
  - `llm_invalid_responses_total`
- Alerts:
  - Queue depth > 500 or oldest > 30 min.
  - LLM invalid responses > 5% / hr.
  - Fetcher error rate > 10% / hr.
- Grafana **Data Pipelines**: new panels for sentiment throughput + LLM latency.

## 13. Translation & Localization

- All sentiment UI strings keyed `sentiment.*`.
- Polarity / impact numeric only — no translation needed.
- Article list: headlines in source language (English). Later we may auto-translate for non-English UI; deferred.
- Sector names translated via `sentiment.sector.TECHNOLOGY`, `...HEALTHCARE`, etc.
- Tooltip explanations translated.

## 14. Documentation Deliverables

- `/docs/adr/070-local-llm-sentiment.md`.
- `/docs/adr/071-finbert-plus-llama-tiering.md`.
- `/docs/runbooks/llm-worker-cold-start.md`.
- `/docs/runbooks/sentiment-queue-backlog.md`.
- User help: "How StratTraderPro reads the news".

## 15. Rollback Plan

- Feature flag `SENTIMENT_ENABLED` hides widgets + disables fetchers.
- Feature flag `LLM_WORKER_ENABLED` — turning off drops Tier 2 to FinBERT-only.
- Migrations additive.

## 16. Risks & Mitigations

| Risk | L | I | Mitigation |
|---|---|---|---|
| Prompt injection via news body | Med | Med | Clear delimiters, JSON-only output validation. |
| News source content licensing complaint | Low | Med | Summary-only display; link to source; honor robots.txt for any scrapers. |
| Llama output drifts to English-irrelevant | Low | Low | JSON schema rejection + retry; golden-file tests. |
| LLM worker OOM | Med | Med | `n_ctx=4096`, `n_batch` tuned; memory limit alert. |
| Symbol tagger produces false positives (common words as tickers) | Med | Low | Whitelist + alias table + minimum confidence threshold. |

## 17. Exit Gate Checklist

- [ ] AC-07-1 … AC-07-12 pass.
- [ ] FinBERT + Llama both produce scores in staging.
- [ ] Queue backlog alert verified by manual injection.
- [ ] Degraded-mode banner appears when LLM worker is killed.
- [ ] ADRs 070, 071 committed.
- [ ] Grafana sentiment panels live.
- [ ] Tag `v0.7.0-sentiment`.

Proceed to **M08 Risk Engine + Kill Switches**.
