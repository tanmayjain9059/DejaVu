import unittest
from scripts.evaluate_matching import evaluate, load_cases

class FakeEngine:
    def __init__(self, scores): self.scores = scores
    def rank(self, _lost, candidates, limit=5):
        rows = [{"report": c, "score": self.scores[c["id"]], "engine": "fake"} for c in candidates]
        return sorted(rows, key=lambda row: row["score"], reverse=True)[:limit]

class MatchingEvaluationTests(unittest.TestCase):
    def test_retrieval_metrics_and_false_positive_diagnostics(self):
        case = {"case_id":"Q1","lost":{"category":"electronics"},
                "candidates":[{"id":"positive"},{"id":"negative-a"},{"id":"negative-b"}],
                "relevant_ids":["positive"]}
        result = evaluate(FakeEngine({"positive":.9,"negative-a":.8,"negative-b":.1}),[case],ks=(1,2),threshold=.75)
        self.assertEqual(result["metrics"]["precision@1"],1.0)
        self.assertEqual(result["metrics"]["recall@1"],1.0)
        self.assertEqual(result["metrics"]["precision@2"],.5)
        self.assertEqual(result["metrics"]["recall@2"],1.0)
        self.assertEqual(result["metrics"]["mrr"],1.0)
        self.assertEqual(result["threshold_diagnostics"]["false_positives"],1)
        self.assertEqual(result["threshold_diagnostics"]["false_positive_rate"],.5)
        self.assertEqual(result["by_category"]["electronics"]["queries"],1)

    def test_missed_relevant_candidate(self):
        case = {"case_id":"Q2","lost":{"category":"stationery"},
                "candidates":[{"id":"positive"},{"id":"negative"}],"relevant_ids":["positive"]}
        result = evaluate(FakeEngine({"positive":.2,"negative":.9}),[case],ks=(1,2))
        self.assertEqual(result["metrics"]["hit_rate@1"],0.0)
        self.assertEqual(result["metrics"]["mrr"],.5)

    def test_benchmark_labels_validate(self):
        cases, description = load_cases()
        self.assertTrue(cases); self.assertIn("Synthetic",description)

if __name__ == "__main__": unittest.main()
