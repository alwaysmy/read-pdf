"""Offline regression tests for OpenAI-compatible completion metadata.

Run: python -m unittest discover -s tests -p 'test_completion_metadata.py' -v
"""
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import engines


class CompletionMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.image = pathlib.Path(self.tmpdir.name) / "page.png"
        self.image.write_bytes(b"test-image")
        self.src_cfg = {"endpoint": "http://test.invalid/v1/", "api_key": "test-key"}

    def response(self, content="page text", finish_reason="stop", **metadata):
        return {
            "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
            **metadata,
        }

    def call_with_response(self, body, engine=None, **kwargs):
        response = Mock(status_code=200)
        response.json.return_value = body
        with patch("requests.post", return_value=response) as post:
            result = engines.call_local(engine or {}, self.src_cfg, self.image, "Read page", **kwargs)
        return result, post

    def test_length_preserves_partial_text_and_all_usage_details(self):
        usage = {
            "prompt_tokens": 100,
            "completion_tokens": 64,
            "total_tokens": 164,
            "completion_tokens_details": {"reasoning_tokens": 8},
        }
        (text, stats), _ = self.call_with_response(
            self.response("unfinished table |", "length", usage=usage, model="ocr-v1"),
            max_tokens=64,
        )
        self.assertEqual(text, "unfinished table |")
        self.assertEqual(stats["finish_reason"], "length")
        self.assertEqual(stats["usage"], usage)
        self.assertEqual(stats["model"], "ocr-v1")
        self.assertTrue(stats["truncated"])
        self.assertEqual(stats["quality_flags"], ["completion_truncated"])
        self.assertNotIn("error", stats)

    def test_stop_is_not_truncated_even_at_token_limit(self):
        (text, stats), _ = self.call_with_response(
            self.response(usage={"completion_tokens": 64}, model="ocr-v1"), max_tokens=64
        )
        self.assertEqual(text, "page text")
        self.assertEqual(stats["finish_reason"], "stop")
        self.assertFalse(stats["truncated"])
        self.assertEqual(stats["quality_flags"], [])

    def test_legacy_server_without_optional_metadata_still_returns_text(self):
        body = {"choices": [{"message": {"content": "legacy text"}}]}
        (text, stats), _ = self.call_with_response(body)
        self.assertEqual(text, "legacy text")
        self.assertNotIn("usage", stats)
        self.assertNotIn("model", stats)
        self.assertNotIn("finish_reason", stats)
        self.assertFalse(stats["truncated"])
        self.assertEqual(stats["quality_flags"], [])

    def test_null_or_other_finish_reasons_are_preserved_without_false_truncation(self):
        for reason in (None, "content_filter", "tool_calls"):
            with self.subTest(reason=reason):
                (text, stats), _ = self.call_with_response(self.response("partial text", reason))
                self.assertEqual(text, "partial text")
                self.assertEqual(stats["finish_reason"], reason)
                self.assertFalse(stats["truncated"])

    def test_request_contract_is_unchanged(self):
        for order, first_type in (("image-first", "image_url"), ("text-first", "text")):
            with self.subTest(order=order):
                _, post = self.call_with_response(
                    self.response(), {"message_order": order}, temp=0.2, max_tokens=64
                )
                args, kwargs = post.call_args
                self.assertEqual(args, ("http://test.invalid/v1/chat/completions",))
                self.assertEqual(kwargs["headers"], {"Authorization": "Bearer test-key"})
                self.assertEqual(kwargs["timeout"], 180)
                self.assertEqual(kwargs["json"]["max_tokens"], 64)
                self.assertEqual(kwargs["json"]["temperature"], 0.2)
                content = kwargs["json"]["messages"][0]["content"]
                self.assertEqual(content[0]["type"], first_type)

    def test_http_error_keeps_existing_error_contract(self):
        response = Mock(status_code=503, text="Service unavailable")
        with patch("requests.post", return_value=response):
            text, stats = engines.call_local({}, self.src_cfg, self.image, "Read page")
        self.assertEqual(text, "")
        self.assertEqual(stats, {"error": "HTTP 503: Service unavailable"})
        response.json.assert_not_called()

    def test_invalid_response_keeps_existing_error_contract(self):
        (text, stats), _ = self.call_with_response({"choices": []})
        self.assertEqual(text, "")
        self.assertIn("error", stats)

    def test_request_exception_keeps_existing_error_contract(self):
        with patch("requests.post", side_effect=RuntimeError("connection failed")):
            text, stats = engines.call_local({}, self.src_cfg, self.image, "Read page")
        self.assertEqual(text, "")
        self.assertEqual(stats, {"error": "connection failed"})

    def test_unified_entry_point_preserves_completion_metadata(self):
        engine = {"sources": {"local": self.src_cfg}, "max_tokens": 64}
        response = Mock(status_code=200)
        response.json.return_value = self.response("partial", "length", model="ocr-v1")
        with patch.object(engines, "get_engine", return_value=(engine, "local")):
            with patch("requests.post", return_value=response):
                text, stats = engines.call("glm", self.image)
        self.assertEqual(text, "partial")
        self.assertEqual(stats["model"], "ocr-v1")
        self.assertEqual(stats["finish_reason"], "length")
        self.assertTrue(stats["truncated"])

    def test_cloud_entry_point_retains_existing_job_stats(self):
        engine = {"sources": {"cloud": self.src_cfg}}
        expected = ("cloud page", {"source": "cloud", "job_id": "job-123"})
        with patch.object(engines, "get_engine", return_value=(engine, "cloud")):
            with patch.object(engines, "call_cloud_aistudio", return_value=expected):
                self.assertEqual(engines.call("paddle_vl", self.image), expected)


if __name__ == "__main__":
    unittest.main()
