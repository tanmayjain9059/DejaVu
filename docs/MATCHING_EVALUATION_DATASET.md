# Matching evaluation dataset v1

## Purpose and limitations

The benchmark at `tests/data/matching_benchmark_v1.json` contains 100 deterministic synthetic queries, balanced across the 10 supported item categories. It is a development fixture for exercising ranking and evaluation code, not a representative sample of CVR College reports and not evidence of campus accuracy.

The dataset includes:
- 60 queries with one relevant candidate
- 20 queries with multiple relevant candidates
- 20 queries with no relevant candidate in the candidate pool
- 4–5 hard distractors per query, depending on the label pattern

Labels are known because the examples are constructed synthetically. This is not a substitute for independent human adjudication of real-world matches.

## JSON record format

Each entry in `cases` contains:

| Field | Meaning |
|---|---|
| `case_id` | Unique query identifier |
| `label` | Human-readable synthetic scenario description |
| `lost` | Lost-item report object |
| `candidates` | Candidate found-report objects |
| `relevant_ids` | IDs of all relevant candidates; an empty array means the labelled candidate pool contains no match |

Candidate report objects must have unique `id` values. The `relevant_ids` array may contain zero, one or multiple candidate IDs and every listed ID must exist in that query's candidates.

## Running evaluation

From the repository root:

```bash
python scripts/evaluate_matching.py
python scripts/evaluate_matching.py --ks 1,3,5 --score-threshold 0.72 --output reports/matching-evaluation.json
```

Use `--dataset path/to/labelled.json` to evaluate another dataset. Recall@K is macro-averaged over queries with at least one relevant candidate. Precision@K and HitRate@K include no-match queries, which count as zero retrieval hits. The no-match rejection rate measures the share of no-match queries for which every candidate score is below the diagnostic threshold. Pair-level false-positive rate is reported separately. The report also includes total evaluation time and per-query mean, p50, p95 and maximum ranking latency. Per-query timing wraps `engine.rank`; the first query includes lazy model-loading time when the model is loaded on demand, so treat it as a cold-start measurement rather than steady-state latency.

The score threshold is an evaluation diagnostic only. It must never approve a claim, establish ownership, or replace staff review.

## Creating a real evaluation set

Before using campus records, obtain institutional approval and define a retention and access policy. Minimise fields to those required for matching; remove names, roll numbers, email addresses, phone numbers, account IDs, claim evidence and other direct identifiers. Do not copy private claim attachments into the benchmark. Use consented and access-controlled images only if visual matching is being evaluated.

Have at least two reviewers independently label candidate relevance using a documented rubric, resolve disagreements, and preserve an adjudication record separately from the benchmark. Include difficult negatives and no-match queries. Split tuning and holdout evaluation by query or time period, not by individual candidate pair, to reduce leakage. Do not tune weights on the final holdout set.

Report dataset size, category coverage, positive/no-match distribution, reviewer agreement, model revision, configuration, latency and resource use alongside retrieval metrics. Never present this synthetic benchmark or a small convenience sample as a validated estimate of production performance.
