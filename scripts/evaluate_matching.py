#!/usr/bin/env python3
"""Evaluate LostLink retrieval against labelled JSON data; metrics are not ownership decisions."""
from __future__ import annotations
import argparse, json, os, sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
DEFAULT_DATA = ROOT / "tests" / "data" / "matching_benchmark.json"

def load_cases(dataset: Path = DEFAULT_DATA):
    payload = json.loads(dataset.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError("Dataset must be a JSON object containing a cases array")
    cases, seen = payload["cases"], set()
    if not cases: raise ValueError("Dataset contains no labelled cases")
    for case in cases:
        cid = case.get("case_id")
        if not cid or cid in seen: raise ValueError(f"Missing or duplicate case_id: {cid!r}")
        seen.add(cid)
        candidates, relevant = case.get("candidates"), case.get("relevant_ids")
        if not isinstance(candidates, list) or not candidates: raise ValueError(f"{cid}: candidates must be non-empty")
        if not isinstance(relevant, list) or not relevant: raise ValueError(f"{cid}: relevant_ids must contain positive labels")
        ids = [item.get("id") for item in candidates]
        if None in ids or len(ids) != len(set(ids)): raise ValueError(f"{cid}: candidate IDs must be present and unique")
        if not set(relevant).issubset(ids): raise ValueError(f"{cid}: relevant_ids contains an unknown candidate")
        if not isinstance(case.get("lost"), dict): raise ValueError(f"{cid}: lost must be an object")
    return cases, payload.get("description", "No dataset description supplied")

def _averages(values):
    return {key: round(sum(items) / len(items), 4) if items else 0.0 for key, items in values.items()}

def evaluate(engine, cases: list[dict[str, Any]], ks=(1, 3, 5), threshold=0.72):
    """Compute macro query-level retrieval metrics and pairwise threshold diagnostics."""
    ks = tuple(sorted(set(int(k) for k in ks)))
    if not ks or ks[0] < 1: raise ValueError("ks must contain positive integers")
    if not 0 <= threshold <= 1: raise ValueError("threshold must be between 0 and 1")
    values, categories = defaultdict(list), defaultdict(lambda: defaultdict(list))
    engine_counts = Counter()
    tp = fp = tn = fn = pairs = 0
    for case in cases:
        ranked = engine.rank(case["lost"], case["candidates"], limit=len(case["candidates"]))
        relevant = set(case["relevant_ids"])
        ranked_ids = [item["report"]["id"] for item in ranked]
        if len(ranked_ids) != len(set(ranked_ids)) or set(ranked_ids) != {x["id"] for x in case["candidates"]}:
            raise ValueError(f'{case["case_id"]}: rank() must return every candidate exactly once')
        category = str(case["lost"].get("category") or "unspecified")
        for item in ranked:
            engine_counts[item.get("engine", "unknown")] += 1
            positive, predicted = item["report"]["id"] in relevant, float(item["score"]) >= threshold
            pairs += 1
            if predicted and positive: tp += 1
            elif predicted: fp += 1
            elif positive: fn += 1
            else: tn += 1
        rank = next((i for i, rid in enumerate(ranked_ids, 1) if rid in relevant), None)
        mrr = 1 / rank if rank else 0.0
        values["mrr"].append(mrr); categories[category]["mrr"].append(mrr)
        for k in ks:
            found = len(set(ranked_ids[:k]) & relevant)
            precision, recall, hit = found / min(k, len(ranked_ids)), found / len(relevant), float(found > 0)
            for target in (values, categories[category]):
                target[f"precision@{k}"].append(precision)
                target[f"recall@{k}"].append(recall)
                target[f"hit_rate@{k}"].append(hit)
    return {
        "queries": len(cases), "candidate_pairs_scored": pairs, "metrics": _averages(values),
        "by_category": {cat: {"queries": len(v["mrr"]), **_averages(v)} for cat, v in sorted(categories.items())},
        "threshold_diagnostics": {
            "score_threshold": threshold, "true_positives": tp, "false_positives": fp,
            "true_negatives": tn, "false_negatives": fn,
            "precision": round(tp/(tp+fp), 4) if tp+fp else None,
            "false_positive_rate": round(fp/(fp+tn), 4) if fp+tn else None,
            "note": "Diagnostic only; not an ownership or claim-approval rule."
        }, "engine_counts": dict(engine_counts)
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
    os.environ["USE_CLIP_MODEL"] = "false"; os.environ["USE_SEMANTIC_MODEL"] = "false"
    from app.matching import MatchingEngine
    baseline = MatchingEngine(); baseline.semantic_enabled = baseline.clip_enabled = False
    baseline_result = evaluate(baseline, cases, ks, args.score_threshold)
    semantic = MatchingEngine(); semantic.semantic_enabled, semantic.clip_enabled = True, False
    semantic_result = evaluate(semantic, cases, ks, args.score_threshold)
    loaded = semantic._text_model is not None
    output = {
        "benchmark_description": description,
        "data_status": "labelled development data; synthetic unless documented otherwise",
        "dataset": str(args.dataset), "query_count": len(cases),
        "candidate_pair_count": sum(len(c["candidates"]) for c in cases),
        "baseline": baseline_result,
        "semantic": {"available": loaded, **(semantic_result if loaded else {
            "metrics": None, "note": "Model did not load; semantic metrics are not reported."
        })}
    }
    rendered = json.dumps(output, indent=2); print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.require_semantic_model and not loaded:
        raise SystemExit("Sentence Transformers did not load; refusing to report semantic metrics.")

if __name__ == "__main__": main()
