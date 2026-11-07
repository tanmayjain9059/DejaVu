#!/usr/bin/env python3
"""Evaluate LostLink retrieval against labelled JSON data; metrics are not ownership decisions."""
from __future__ import annotations
import argparse, json, os, sys, time, time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_DATA = ROOT / "tests" / "data" / "matching_benchmark_v1.json"


def load_cases(dataset: Path = DEFAULT_DATA):
    payload = json.loads(dataset.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError("Dataset must be a JSON object containing a cases array")
    cases, seen = payload["cases"], set()
    if not cases:
        raise ValueError("Dataset contains no labelled cases")
    for case in cases:
        cid = case.get("case_id")
        if not cid or cid in seen:
            raise ValueError(f"Missing or duplicate case_id: {cid!r}")
        seen.add(cid)
        candidates, relevant = case.get("candidates"), case.get("relevant_ids")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError(f"{cid}: candidates must be non-empty")
        if not isinstance(relevant, list):
            raise ValueError(f"{cid}: relevant_ids must be an array (empty means no known match)")
        ids = [item.get("id") for item in candidates]
        if None in ids or len(ids) != len(set(ids)):
            raise ValueError(f"{cid}: candidate IDs must be present and unique")
        if not set(relevant).issubset(ids):
            raise ValueError(f"{cid}: relevant_ids contains an unknown candidate")
        if not isinstance(case.get("lost"), dict):
            raise ValueError(f"{cid}: lost must be an object")
    return cases, payload.get("description", "No dataset description supplied")


def _averages(values):
    return {key: round(sum(items) / len(items), 4) if items else None
            for key, items in values.items()}


def evaluate(engine, cases: list[dict[str, Any]], ks=(1, 3, 5), threshold=0.72):
    """Compute macro retrieval metrics, pairwise diagnostics and no-match rejection."""
    ks = tuple(sorted(set(int(k) for k in ks)))
    if not ks or ks[0] < 1:
        raise ValueError("ks must contain positive integers")
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    values = defaultdict(list)
    categories = defaultdict(lambda: defaultdict(list))
    engine_counts = Counter()
    tp = fp = tn = fn = pairs = 0
    no_match_count = no_match_rejected = 0
    relevant_query_count = 0
    query_latencies_ms = []
    evaluation_started = time.perf_counter()

    for case in cases:
        query_started = time.perf_counter()
        ranked = engine.rank(case["lost"], case["candidates"], limit=len(case["candidates"]))
        query_latencies_ms.append((time.perf_counter() - query_started) * 1000)
        relevant = set(case["relevant_ids"])
        ranked_ids = [item["report"]["id"] for item in ranked]
        expected_ids = {item["id"] for item in case["candidates"]}
        if len(ranked_ids) != len(set(ranked_ids)) or set(ranked_ids) != expected_ids:
            raise ValueError(f'{case["case_id"]}: rank() must return every candidate exactly once')
        category = str(case["lost"].get("category") or "unspecified")
        scores = []
        for item in ranked:
            engine_counts[item.get("engine", "unknown")] += 1
            positive = item["report"]["id"] in relevant
            score = float(item["score"])
            scores.append(score)
            predicted = score >= threshold
            pairs += 1
            if predicted and positive:
                tp += 1
            elif predicted:
                fp += 1
            elif positive:
                fn += 1
            else:
                tn += 1

        rank = next((i for i, rid in enumerate(ranked_ids, 1) if rid in relevant), None)
        mrr = 1 / rank if rank else 0.0
        values["mrr"].append(mrr)
        categories[category]["mrr"].append(mrr)
        if relevant:
            relevant_query_count += 1
        else:
            no_match_count += 1
            if not scores or max(scores) < threshold:
                no_match_rejected += 1

        for k in ks:
            selected = set(ranked_ids[:k])
            found = len(selected & relevant)
            precision = found / min(k, len(ranked_ids))
            hit = float(found > 0)
            values[f"precision@{k}"].append(precision)
            values[f"hit_rate@{k}"].append(hit)
            categories[category][f"precision@{k}"].append(precision)
            categories[category][f"hit_rate@{k}"].append(hit)
            if relevant:
                recall = found / len(relevant)
                values[f"recall@{k}"].append(recall)
                categories[category][f"recall@{k}"].append(recall)

    elapsed_seconds = time.perf_counter() - evaluation_started
    ordered_latencies = sorted(query_latencies_ms)

    def percentile(values, fraction):
        if not values:
            return None
        index = max(0, min(len(values) - 1, int((len(values) * fraction + 0.999999)) - 1))
        return round(values[index], 3)

    category_output = {}
    for cat, metrics in sorted(categories.items()):
        cat_cases = [c for c in cases if str(c["lost"].get("category") or "unspecified") == cat]
        category_output[cat] = {
            "queries": len(cat_cases),
            "queries_with_relevant_candidates": sum(bool(c["relevant_ids"]) for c in cat_cases),
            "no_match_queries": sum(not c["relevant_ids"] for c in cat_cases),
            **_averages(metrics),
        }

    return {
        "queries": len(cases),
        "queries_with_relevant_candidates": relevant_query_count,
        "no_match_queries": no_match_count,
        "candidate_pairs_scored": pairs,
        "latency": {
            "measurement": "wall-clock time around engine.rank per query; includes cold model load on first query when lazy-loaded",
            "total_evaluation_seconds": round(elapsed_seconds, 3),
            "mean_query_ms": round(sum(query_latencies_ms) / len(query_latencies_ms), 3) if query_latencies_ms else None,
            "p50_query_ms": percentile(ordered_latencies, 0.50),
            "p95_query_ms": percentile(ordered_latencies, 0.95),
            "max_query_ms": round(max(query_latencies_ms), 3) if query_latencies_ms else None,
        },
        "metrics": _averages(values),
        "no_match_rejection": {
            "threshold": threshold,
            "rejected_no_match_queries": no_match_rejected,
            "no_match_rejection_rate": round(no_match_rejected / no_match_count, 4) if no_match_count else None,
            "note": "A no-match query is rejected only when every candidate score is below the diagnostic threshold."
        },
        "by_category": category_output,
        "threshold_diagnostics": {
            "score_threshold": threshold, "true_positives": tp, "false_positives": fp,
            "true_negatives": tn, "false_negatives": fn,
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else None,
            "note": "Diagnostic only; not an ownership or claim-approval rule."
        },
        "engine_counts": dict(engine_counts),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--ks", default="1,3,5")
    parser.add_argument("--score-threshold", type=float, default=0.72)
    parser.add_argument("--require-semantic-model", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        ks = tuple(int(v.strip()) for v in args.ks.split(",") if v.strip())
        cases, description = load_cases(args.dataset)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"Invalid evaluation input: {exc}") from exc

    os.environ["USE_CLIP_MODEL"] = "false"
    os.environ["USE_SEMANTIC_MODEL"] = "false"
    from app.matching import MatchingEngine

    baseline = MatchingEngine()
    baseline.semantic_enabled = baseline.clip_enabled = False
    baseline_result = evaluate(baseline, cases, ks, args.score_threshold)

    semantic = MatchingEngine()
    semantic.semantic_enabled, semantic.clip_enabled = True, False
    semantic_result = evaluate(semantic, cases, ks, args.score_threshold)
    loaded = semantic._text_model is not None
    output = {
        "benchmark_description": description,
        "data_status": "synthetic development data; not campus ground truth",
        "dataset": str(args.dataset),
        "query_count": len(cases),
        "candidate_pair_count": sum(len(c["candidates"]) for c in cases),
        "baseline": baseline_result,
        "semantic": {
            "available": loaded,
            **(semantic_result if loaded else {
                "metrics": None,
                "note": "Model did not load; semantic metrics are not reported."
            }),
        },
    }
    rendered = json.dumps(output, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.require_semantic_model and not loaded:
        raise SystemExit("Sentence Transformers did not load; refusing to report semantic metrics.")


if __name__ == "__main__":
    main()
