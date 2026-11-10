"""Runtime-safety tests for optional AI matching models.

These tests use fake model modules so normal CI never downloads model weights.
"""
import sys
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from app.matching import MatchingEngine, lexical_similarity


class MatchingModelRuntimeTests(unittest.TestCase):
    def test_semantic_model_initialises_only_once_under_concurrent_first_requests(self):
        constructed = []
        guard = threading.Lock()

        class FakeSentenceTransformer:
            def __init__(self, model_name, revision=None, **kwargs):
                with guard:
                    constructed.append((model_name, revision))

        fake_module = types.ModuleType("sentence_transformers")
        fake_module.SentenceTransformer = FakeSentenceTransformer
        engine = MatchingEngine()
        engine.semantic_enabled = True
        engine._text_status = "not_loaded"

        with patch.dict(sys.modules, {"sentence_transformers": fake_module}), patch.dict("os.environ", {"SEMANTIC_MODEL_REVISION": "minilm-r7"}):
            with ThreadPoolExecutor(max_workers=12) as pool:
                models = list(pool.map(lambda _: engine._load_text_model(), range(24)))

        self.assertEqual(len(constructed), 1)
        self.assertEqual(constructed[0][1], "minilm-r7")
        self.assertTrue(all(model is models[0] for model in models))
        self.assertEqual(engine.model_status()["text"]["state"], "ready")

    def test_clip_initialises_only_once_under_concurrent_first_requests(self):
        constructed = []
        guard = threading.Lock()

        class FakeClipModel:
            def eval(self):
                return self

        class FakeClipProcessor:
            @classmethod
            def from_pretrained(cls, model_name, revision=None, **kwargs):
                return cls()

        class FakeClipModelFactory:
            @classmethod
            def from_pretrained(cls, model_name, revision=None):
                with guard:
                    constructed.append((model_name, revision))
                return FakeClipModel()

        fake_module = types.ModuleType("transformers")
        fake_module.CLIPModel = FakeClipModelFactory
        fake_module.CLIPProcessor = FakeClipProcessor
        engine = MatchingEngine()
        engine.clip_enabled = True
        engine._clip_status = "not_loaded"

        with patch.dict(sys.modules, {"transformers": fake_module}), patch.dict("os.environ", {"CLIP_MODEL_REVISION": "clip-r3"}):
            with ThreadPoolExecutor(max_workers=12) as pool:
                pairs = list(pool.map(lambda _: engine._load_clip(), range(24)))

        self.assertEqual(len(constructed), 1)
        self.assertEqual(constructed[0][1], "clip-r3")
        self.assertTrue(all(pair[0] is pairs[0][0] for pair in pairs))
        self.assertTrue(all(pair[1] is pairs[0][1] for pair in pairs))
        self.assertEqual(engine.model_status()["image"]["state"], "ready")

    def test_semantic_inference_failure_uses_lexical_fallback_and_updates_status(self):
        class BrokenModel:
            def encode(self, *_args, **_kwargs):
                raise RuntimeError("private implementation detail")

        engine = MatchingEngine()
        engine.semantic_enabled = True
        engine._text_attempted = True
        engine._text_model = BrokenModel()
        engine._text_status = "ready"
        left, right = "blue backpack with a yellow zipper", "blue bag with yellow zipper"

        score, source = engine.text_similarity(left, right)

        self.assertEqual(source, "lexical_baseline")
        self.assertEqual(score, lexical_similarity(left, right))
        status = engine.model_status()["text"]
        self.assertEqual(status["state"], "unavailable")
        self.assertTrue(status["failed"])

    def test_model_status_does_not_expose_exception_messages(self):
        engine = MatchingEngine()
        engine.semantic_enabled = True
        engine._text_attempted = True
        engine._text_status = "unavailable"
        engine._text_failure = "RuntimeError: secret/path/token"

        status = engine.model_status()

        self.assertEqual(status["text"]["state"], "unavailable")
        self.assertTrue(status["text"]["failed"])
        self.assertNotIn("secret", str(status))


if __name__ == "__main__":
    unittest.main()
