"""Offline document-reader and HTTP/MCP regressions; no OCR servers or models.

Run: python -m unittest discover -s tests -p 'test_document_reader.py' -v
Flask/requests are needed for transport tests. API keys are test-only environment
values; imports never generate ~/.readpdf/key or start any backend process.
"""
import asyncio
import base64
import copy
import importlib.util
import json
import os
import pathlib
import sys
import subprocess
import tempfile
import unittest
from unittest import mock

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import document_reader as reader


def make_package():
    def page(number, text, status="ok", flags=None):
        return {"physical_page": number, "width": 612, "height": 792, "rotation": 0,
                "text_raw": text, "status": status, "quality_flags": flags or [],
                "engine": "native" if text else None, "provenance": {"source": "native"},
                "blocks": ([{"block_id": f"p{number}-b1", "type": "text", "text_raw": text,
                             "bbox": None, "extraction_method": "native",
                             "quality_flags": flags or [], "validation_state": "unvalidated"}]
                           if text else [])}
    return {"schema_version": "1.0", "doc_id": "a" * 64, "revision_id": "b" * 64,
            "source": {"filename": "sample.pdf", "sha256": "b" * 64}, "total_pages": 4,
            "coverage": {"requested_pages": [1, 2, 3], "processed_pages": [1, 2],
                         "failed_pages": [3], "unprocessed_pages": [3, 4]},
            "status": "partial", "quality_flags": ["partial_coverage", "ocr_failed"],
            "issues": [{"physical_page": 3, "code": "ocr_failed"}],
            "run": {"pipeline_version": "p0", "pipeline_signature": "sig-one"},
            "pages": [page(1, "Alpha beta.\nUnicode 中文: café. Alpha."),
                      page(2, "Second page alpha. A literal [needle].", flags=["low_confidence"]),
                      page(3, "", status="failed", flags=["ocr_failed"]),
                      page(4, "", status="not_requested")]}


def load_transport(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    import engines
    with mock.patch.dict(os.environ, {"READPDF_API_KEY": "reader-unit-test-key"}), \
            mock.patch.object(engines, "load_config", return_value={}):
        spec.loader.exec_module(module)
    return module


class PackageFixture(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = pathlib.Path(self.directory.name) / "sample.document.json"
        self.package = make_package()
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.package, ensure_ascii=False), encoding="utf-8")


class DocumentReaderTests(PackageFixture):
    def test_open_is_metadata_only_and_never_spawns_work(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("No extraction allowed")), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("No server allowed")):
            result = reader.open_document(self.path)
        self.assertEqual(result["coverage"], self.package["coverage"])
        self.assertEqual(result["quality_flags"], self.package["quality_flags"])
        self.assertEqual(result["reader_mode"], "existing_package_only")
        self.assertEqual(len(result["page_statuses"]), 4)
        self.assertNotIn("text", result)
        self.assertNotIn("text_raw", result["pages"][0])

    def test_read_small_limit_retains_complete_status_and_quality(self):
        result = reader.read_document(self.path, max_chars=5)
        self.assertEqual(result["text"], "Alpha")
        self.assertEqual(result["returned_chars"], 5)
        self.assertTrue(result["truncated"])
        self.assertTrue(result["next_cursor"])
        self.assertEqual(result["coverage"], self.package["coverage"])
        self.assertEqual(result["issues"], self.package["issues"])
        self.assertEqual(result["quality_flags"], self.package["quality_flags"])
        self.assertEqual(result["page_statuses"][2]["status"], "failed")
        self.assertEqual(result["page_statuses"][1]["quality_flags"], ["low_confidence"])
        self.assertEqual(result["unavailable_pages"], [3, 4])
        citation = result["citations"][0]
        self.assertEqual(citation["physical_page"], 1)
        self.assertEqual(citation["block_id"], "p1-b1")
        self.assertEqual((citation["source_start"], citation["source_end"]), (0, 5))

    def test_cursor_reconstructs_all_text_without_drops_or_duplication(self):
        expected = "\n\n".join(page["text_raw"] for page in self.package["pages"] if page["text_raw"])
        cursor, pieces = None, []
        for _ in range(len(expected) + 1):
            result = reader.read_document(self.path, max_chars=1, cursor=cursor)
            self.assertLessEqual(len(result["text"]), 1)
            pieces.append(result["text"])
            for citation in result["citations"]:
                page = self.package["pages"][citation["physical_page"] - 1]
                self.assertEqual(result["text"][citation["output_start"]:citation["output_end"]],
                                 page["blocks"][0]["text_raw"][citation["source_start"]:citation["source_end"]])
            cursor = result["next_cursor"]
            if cursor is None:
                break
        self.assertIsNone(cursor)
        self.assertEqual("".join(pieces), expected)

    def test_cursor_is_deterministic_and_budget_may_change(self):
        first = reader.read_document(self.path, max_chars=3)
        again = reader.read_document(self.path, max_chars=3)
        self.assertEqual(first["next_cursor"], again["next_cursor"])
        next_part = reader.read_document(self.path, max_chars=9, cursor=first["next_cursor"])
        self.assertEqual(next_part["text"], self.package["pages"][0]["text_raw"][3:12])

    def test_cursor_rejects_revision_pipeline_content_and_selection_changes(self):
        original = copy.deepcopy(self.package)
        cursor = reader.read_document(self.path, max_chars=1)["next_cursor"]
        for mutation in ("revision", "pipeline", "content"):
            with self.subTest(mutation=mutation):
                self.package = copy.deepcopy(original)
                if mutation == "revision":
                    self.package["revision_id"] = "c" * 64
                    self.package["source"]["sha256"] = "c" * 64
                elif mutation == "pipeline":
                    self.package["run"]["pipeline_signature"] = "sig-two"
                else:
                    self.package["pages"][0]["blocks"][0]["text_raw"] += " changed"
                self.save()
                with self.assertRaisesRegex(reader.DocumentReaderError, "Stale or incompatible cursor"):
                    reader.read_document(self.path, cursor=cursor)
        self.package = original
        self.save()
        with self.assertRaisesRegex(reader.DocumentReaderError, "Stale or incompatible cursor"):
            reader.read_document(self.path, pages=[1], cursor=cursor)

    def test_malformed_cursor_is_a_clear_error(self):
        for cursor in (True, 10, {}, [], "", "!bad", "a" * 4097, "W10", "eyJvZmZzZXQiOnRydWV9"):
            with self.subTest(cursor=str(cursor)[:30]), self.assertRaises(reader.DocumentReaderError):
                reader.read_document(self.path, cursor=cursor)
        valid = reader.read_document(self.path, max_chars=1)["next_cursor"]
        decoded = json.loads(base64.urlsafe_b64decode(valid + "=" * (-len(valid) % 4)))
        for bad_offset in (True, -1, 1_000_000, 1.1, "1"):
            decoded["offset"] = bad_offset
            bad = base64.urlsafe_b64encode(json.dumps(decoded).encode()).decode()
            with self.subTest(offset=bad_offset), self.assertRaises(reader.DocumentReaderError):
                reader.read_document(self.path, cursor=bad)

    def test_page_selection_is_physical_one_based_and_sorted(self):
        for pages in ("2", [2], "2,2", "2-2"):
            with self.subTest(pages=pages):
                result = reader.read_document(self.path, pages=pages)
                self.assertEqual(result["text"], self.package["pages"][1]["text_raw"])
                self.assertEqual(result["citations"][0]["physical_page"], 2)
        self.assertEqual(reader.read_document(self.path, pages="2,1")["selected_pages"], [1, 2])
        self.assertEqual(reader.read_document(self.path, pages=[])["text"], "")
        self.assertEqual(reader.read_document(self.path, pages=[4])["unavailable_pages"], [4])
        self.assertEqual(reader.read_document(self.path, pages=[4])["text"], "")

    def test_invalid_page_ranges_and_types(self):
        for pages in (True, 1, {}, [True], [1.0], [1, 1], [0], [5], "0", "5", "3-1", "1-9999999999",
                      "", "1,,2", "-1", "1.5", "*", "all", "1; echo bad"):
            with self.subTest(pages=pages), self.assertRaises(reader.DocumentReaderError):
                reader.read_document(self.path, pages=pages)

    def test_limits_are_hard_bounded_integers(self):
        for value in (True, False, 0, -1, 1.5, "10", None, {}, [], reader.MAX_READ_CHARS + 1):
            with self.subTest(value=value), self.assertRaises(reader.DocumentReaderError):
                reader.read_document(self.path, max_chars=value)
        for value in (True, False, 0, -1, 1.5, "10", None, {}, [], reader.MAX_SEARCH_HITS + 1):
            with self.subTest(value=value), self.assertRaises(reader.DocumentReaderError):
                reader.search_document(self.path, "alpha", max_hits=value)

    def test_empty_and_page_only_text_has_no_fabricated_block(self):
        self.package["pages"][0]["blocks"] = []
        self.save()
        result = reader.read_document(self.path, pages=[1])
        self.assertEqual(result["text"], self.package["pages"][0]["text_raw"])
        self.assertIsNone(result["citations"][0]["block_id"])
        empty = reader.read_document(self.path, pages=[3])
        self.assertEqual(empty["text"], "")
        self.assertFalse(empty["truncated"])
        self.assertIsNone(empty["next_cursor"])

    def test_search_is_literal_case_insensitive_with_grounded_offsets(self):
        result = reader.search_document(self.path, "ALPHA", max_hits=2)
        self.assertEqual(result["returned_hits"], 2)
        self.assertEqual(result["total_matches"], 3)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["coverage"], self.package["coverage"])
        self.assertEqual(result["unsearched_pages"], [3, 4])
        self.assertFalse(result["complete_document_search"])
        literal = reader.search_document(self.path, "[needle]")
        hit = literal["hits"][0]
        self.assertEqual(hit["citation"]["physical_page"], 2)
        page_text = self.package["pages"][1]["text_raw"]
        self.assertEqual(page_text[hit["match_start"]:hit["match_end"]], "[needle]")
        self.assertEqual(hit["text"], page_text[hit["snippet_start"]:hit["snippet_end"]])

    def test_search_snippets_are_bounded_and_include_match(self):
        long_text = "prefix " * 100 + "needle" + " suffix" * 100
        self.package["pages"][0]["text_raw"] = long_text
        self.package["pages"][0]["blocks"][0]["text_raw"] = long_text
        self.save()
        for hit in reader.search_document(self.path, "needle")["hits"]:
            self.assertLessEqual(len(hit["text"]), reader.SEARCH_SNIPPET_CHARS)
            self.assertIn("needle", hit["text"])

    def test_no_match_discloses_incomplete_coverage(self):
        result = reader.search_document(self.path, "absent text")
        self.assertEqual(result["hits"], [])
        self.assertEqual(result["match_status"], "no_match_in_available_text")
        self.assertEqual(result["unsearched_pages"], [3, 4])
        self.assertIn("Unprocessed or failed", result["message"])
        self.assertEqual(result["quality_flags"], self.package["quality_flags"])

    def test_query_validation(self):
        for query in (None, True, 1, {}, [], "", " \n ", "x" * 257):
            with self.subTest(query=str(query)[:20]), self.assertRaises(reader.DocumentReaderError):
                reader.search_document(self.path, query)

    def test_nonexistent_path_directory_and_bad_path_type(self):
        for path in (self.path.parent / "absent.json", self.path.parent, True, None, [], ""):
            with self.subTest(path=path), self.assertRaises(reader.DocumentReaderError):
                reader.open_document(path)

    def test_non_json_and_non_object_packages(self):
        for data in (b"not json", b"[]", b"null", b"true", b'"string"', b"\xff", b'{"x":1,"x":2}', b'{"x":NaN}'):
            self.path.write_bytes(data)
            with self.subTest(data=data), self.assertRaises(reader.DocumentReaderError):
                reader.open_document(self.path)

    def test_schema_errors_are_clear(self):
        cases = [(("schema_version",), "99"), (("revision_id",), "not-hash"),
                 (("total_pages",), True), (("coverage",), []), (("source",), []),
                 (("source", "sha256"), "abc"), (("quality_flags",), "warning"),
                 (("run",), []), (("pages",), {}), (("pages", 0, "blocks"), {}),
                 (("pages", 0, "physical_page"), False), (("pages", 0, "width"), "612"),
                 (("pages", 0, "blocks", 0, "text_raw"), None),
                 (("pages", 0, "blocks", 0, "bbox"), [1, 2]),
                 (("coverage", "processed_pages"), [1, 1]),
                 (("coverage", "unprocessed_pages"), [1, 3, 4])]
        for keys, value in cases:
            self.package = make_package()
            target = self.package
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = value
            self.save()
            with self.subTest(keys=keys), self.assertRaises(reader.DocumentReaderError):
                reader.open_document(self.path)

    def test_content_quality_prevents_false_complete_search(self):
        self.package["total_pages"] = 1
        self.package["pages"] = self.package["pages"][:1]
        self.package["coverage"] = {"requested_pages": [1], "processed_pages": [1],
                                    "failed_pages": [], "unprocessed_pages": []}
        for flag in ("completion_truncated", "audit_batch_unaligned", "empty_extraction", "extraction_error"):
            self.package["quality_flags"] = [flag]
            self.package["pages"][0]["quality_flags"] = [flag]
            self.package["pages"][0]["status"] = "needs_review"
            self.save()
            with self.subTest(flag=flag):
                result = reader.search_document(self.path, "not present")
                self.assertEqual(result["unsearched_pages"], [])
                self.assertEqual(result["incomplete_quality_pages"], [1])
                self.assertFalse(result["complete_document_search"])
                self.assertIn("not conclusive", result["message"])
        self.package["quality_flags"] = []
        self.package["pages"][0]["quality_flags"] = []
        self.save()
        self.assertTrue(reader.search_document(self.path, "not present")["complete_document_search"])

    def test_bbox_requires_and_preserves_coordinate_space(self):
        block = self.package["pages"][0]["blocks"][0]
        block["bbox"] = [0, 0, 100, 200]
        self.save()
        with self.assertRaisesRegex(reader.DocumentReaderError, "coordinate_space"):
            reader.read_document(self.path)
        self.package["pages"][0]["coordinate_space"] = "pdf_points"
        self.save()
        citation = reader.read_document(self.path)["citations"][0]
        self.assertEqual(citation["coordinate_space"], "pdf_points")
        self.assertEqual(citation["bbox"], [0, 0, 100, 200])

    def test_source_revision_and_failed_page_status_must_agree(self):
        self.package["source"]["sha256"] = "c" * 64
        self.save()
        with self.assertRaisesRegex(reader.DocumentReaderError, "source.sha256 must match"):
            reader.open_document(self.path)
        self.package = make_package()
        self.package["pages"][2]["status"] = "ok"
        self.save()
        with self.assertRaisesRegex(reader.DocumentReaderError, "coverage.failed_pages"):
            reader.open_document(self.path)

    def test_extreme_json_numbers_are_clear_errors(self):
        self.path.write_text('{"value":' + "9" * 5000 + "}", encoding="utf-8")
        with self.assertRaises(reader.DocumentReaderError):
            reader.open_document(self.path)
        self.package["pages"][0]["width"] = 10 ** 400
        self.save()
        with self.assertRaises(reader.DocumentReaderError):
            reader.open_document(self.path)

    def test_real_native_cli_package_roundtrip(self):
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF unavailable for actual native CLI roundtrip")
        pdf = self.path.parent / "native.pdf"
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((72, 72), "Native subprocess evidence: exact 0 mV and 2.5 units.")
            doc.save(pdf)
        result = subprocess.run([sys.executable, str(SCRIPTS / "extract_pdf.py"), str(pdf),
                                 "--output-dir", str(self.path.parent), "--no-pdfmux", "--no-table", "--json"],
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        extraction = json.loads(result.stdout[result.stdout.index("{"):])
        package_path = extraction["package_path"]
        opened = reader.open_document(package_path)
        self.assertEqual(opened["revision_id"], extraction["revision_id"])
        self.assertEqual(opened["coverage"]["processed_pages"], [1])
        read = reader.read_document(package_path, max_chars=12)
        self.assertEqual(read["text"], "Native subpr")
        self.assertIsNotNone(read["next_cursor"])
        search = reader.search_document(package_path, "exact 0 mV")
        self.assertEqual(search["returned_hits"], 1)
        self.assertEqual(search["hits"][0]["citation"]["physical_page"], 1)
        self.assertTrue(search["complete_document_search"])

    def test_file_size_limit_prevents_unbounded_loading(self):
        with mock.patch.object(reader, "MAX_PACKAGE_BYTES", 10):
            with self.assertRaisesRegex(reader.DocumentReaderError, "byte limit"):
                reader.open_document(self.path)


class DocumentTransportTests(PackageFixture):
    @classmethod
    def setUpClass(cls):
        cls.server = load_transport("reader_test_http_server", "server.py")
        cls.mcp = load_transport("reader_test_mcp_server", "mcp_server.py")
        cls.server.app.config.update(TESTING=True)

    def setUp(self):
        super().setUp()
        self.client = self.server.app.test_client()
        self.headers = {"Authorization": "Bearer reader-unit-test-key"}

    def post(self, endpoint, body, auth=True):
        return self.client.post(endpoint, json=body, headers=self.headers if auth else {})

    def test_document_endpoints_require_authentication(self):
        for endpoint in ("/document/open", "/document/read", "/document/search"):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.post(endpoint, {"package_path": str(self.path)}, auth=False).status_code, 401)

    def test_endpoints_read_package_without_cli_or_backend(self):
        with mock.patch.object(self.server, "_run_cli", side_effect=AssertionError("No CLI allowed")), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("No backend allowed")):
            opened = self.post("/document/open", {"package_path": str(self.path)})
            read = self.post("/document/read", {"package_path": str(self.path), "max_chars": 4})
            search = self.post("/document/search", {"package_path": str(self.path), "query": "alpha", "max_hits": 1})
        for response in (opened, read, search):
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertEqual(response.get_json()["coverage"], self.package["coverage"])
        self.assertEqual(read.get_json()["text"], "Alph")
        self.assertEqual(search.get_json()["returned_hits"], 1)
        continued = self.post("/document/read", {"package_path": str(self.path), "max_chars": 4,
                                               "cursor": read.get_json()["next_cursor"]})
        self.assertEqual(continued.status_code, 200)
        self.assertEqual(continued.get_json()["text"], "a be")

    def test_document_input_errors_are_400(self):
        for endpoint, body in [
            ("/document/open", []), ("/document/read", True), ("/document/search", "string"),
            ("/document/open", {}), ("/document/open", {"package_path": []}),
            ("/document/open", {"package_path": str(self.path), "extra": 1}),
            ("/document/search", {"package_path": str(self.path)}),
            ("/document/read", {"package_path": str(self.path), "max_chars": True}),
            ("/document/read", {"package_path": str(self.path), "pages": [0]}),
            ("/document/search", {"package_path": str(self.path), "query": "a", "max_hits": 101}),
            ("/document/open", {"package_path": str(self.path.parent / "absent")}),
        ]:
            with self.subTest(endpoint=endpoint, body=body):
                response = self.post(endpoint, body)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.get_json())
        self.path.write_text("{}", encoding="utf-8")
        self.assertEqual(self.post("/document/open", {"package_path": str(self.path)}).status_code, 400)

    def test_legacy_endpoints_handle_nonmapping_and_bad_field_types(self):
        for endpoint in ("/extract", "/layout", "/config"):
            for body in ([1], True, "text", 1, []):
                with self.subTest(endpoint=endpoint, body=body):
                    self.assertEqual(self.post(endpoint, body).status_code, 400)
        for endpoint in ("/extract", "/layout"):
            for body in ({"pdf": []}, {"pdf": True}, {"engine": []}, {"source": {}},
                         {"dpi": {}}, {"dpi": True}, {"output_dir": 1}):
                with self.subTest(endpoint=endpoint, body=body):
                    self.assertEqual(self.post(endpoint, body).status_code, 400)

    def test_mcp_new_tools_relay_inputs_and_metadata_without_coercion(self):
        def transport(endpoint, body):
            response = self.post(endpoint, body)
            return response.get_json()
        with mock.patch.object(self.mcp, "_post", side_effect=transport):
            self.assertEqual(self.mcp.open_document(str(self.path))["coverage"], self.package["coverage"])
            result = self.mcp.read_document(str(self.path), pages=[2], max_chars=6)
            self.assertEqual(result["text"], "Second")
            self.assertEqual(result["citations"][0]["physical_page"], 2)
            self.assertIn("error", self.mcp.read_document(str(self.path), max_chars=True))
            self.assertIn("error", self.mcp.search_document(str(self.path), "a", max_hits=True))
            self.assertEqual(self.mcp.search_document(str(self.path), "ALPHA", max_hits=1)["returned_hits"], 1)

    def test_fastmcp_rejects_bool_and_string_limits_before_transport(self):
        try:
            from mcp.server.fastmcp.tools import Tool
            from mcp.server.fastmcp.exceptions import ToolError
        except ImportError:
            self.skipTest("Optional MCP SDK unavailable")
        read_tool = Tool.from_function(self.mcp.read_document)
        search_tool = Tool.from_function(self.mcp.search_document)
        with mock.patch.object(self.mcp, "_post") as post:
            for tool, arguments in (
                (read_tool, {"max_chars": True}), (read_tool, {"max_chars": "10"}),
                (read_tool, {"pages": [True]}), (read_tool, {"pages": [1.0]}),
                (search_tool, {"query": "alpha", "max_hits": True}),
                (search_tool, {"query": "alpha", "max_hits": "10"}),
            ):
                with self.subTest(arguments=arguments), self.assertRaises(ToolError):
                    asyncio.run(tool.run({"package_path": str(self.path), **arguments}))
            post.assert_not_called()

    def test_fastmcp_registers_all_six_tools_without_starting_server(self):
        try:
            import mcp.server.fastmcp
        except ImportError:
            self.skipTest("Optional MCP SDK unavailable")
        with mock.patch.object(mcp.server.fastmcp, "FastMCP") as factory:
            self.mcp.main()
        registered = [call.args[0].__name__ for call in factory.return_value.add_tool.call_args_list]
        self.assertEqual(registered, ["extract_pdf", "layout_pdf", "list_engines", "open_document",
                                      "read_document", "search_document"])
        factory.return_value.run.assert_called_once_with()

    def test_mcp_extract_preserves_quality_coverage_and_page_statuses(self):
        response = {"status": "partial", "file": "out.md", "engine": "hybrid", "size_bytes": 42,
                    "total_tables": 0, "time_s": 1, "package_path": str(self.path),
                    "revision_id": "b" * 64, "doc_id": "a" * 64, "coverage": self.package["coverage"],
                    "issues": self.package["issues"], "quality_flags": self.package["quality_flags"],
                    "page_statuses": [{"physical_page": 3, "status": "failed"}]}
        with mock.patch.object(self.mcp, "_post", return_value=response):
            result = self.mcp.extract_pdf("sample.pdf")
        self.assertEqual(result["output"], "out.md")
        for field in ("package_path", "revision_id", "doc_id", "coverage", "issues", "quality_flags", "page_statuses"):
            self.assertEqual(result[field], response[field])

    def test_existing_mcp_layout_and_list_contracts_remain(self):
        with mock.patch.object(self.mcp, "_post", return_value={"status": "ok", "layout_path": "layout.json",
                                                             "total_blocks": 2, "total_crops": 1}):
            self.assertEqual(self.mcp.layout_pdf("sample.pdf")["layout_json"], "layout.json")
        with mock.patch.object(self.mcp, "_get", return_value={"engines": [{"name": "native"}]}):
            self.assertEqual(self.mcp.list_engines(), {"engines": [{"name": "native"}]})


if __name__ == "__main__":
    unittest.main()
