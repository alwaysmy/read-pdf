"""Bounded, read-only views of existing Document Package JSON files.

These helpers do not open PDFs, schedule OCR, load models, or repair packages.
Run extract_pdf first and pass its ``package_path``. ``max_chars`` bounds only
returned text (including inter-block separators); coverage, page statuses, and
quality metadata are always returned separately. Search is literal and
case-insensitive, with at most ``max_hits`` snippets of 320 characters each.
Read cursors are deterministic continuation offsets, not authentication tokens.
"""
import base64
import hashlib
import json
import math
import pathlib
import re

MAX_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_PAGES = 100_000
MAX_READ_CHARS = 100_000
MAX_SEARCH_HITS = 100
MAX_QUERY_CHARS = 256
SEARCH_SNIPPET_CHARS = 320
_COVERAGE_KEYS = ("requested_pages", "processed_pages", "failed_pages", "unprocessed_pages")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
_INCOMPLETE_FLAGS = {"completion_truncated", "audit_batch_unaligned", "empty_extraction",
                     "extraction_error", "ocr_failed", "table_extraction_failed", "low_content"}


class DocumentReaderError(ValueError):
    """A bad request or malformed/unavailable document package."""


def _require(condition, message):
    if not condition:
        raise DocumentReaderError(message)


def _integer(value, name, minimum, maximum):
    _require(type(value) is int and minimum <= value <= maximum,
             f"{name} must be an integer between {minimum} and {maximum} (not bool)")
    return value


def _string(value, name, nonempty=False):
    _require(isinstance(value, str) and (not nonempty or bool(value.strip())),
             f"{name} must be {'a nonempty' if nonempty else 'a'} string")


def _flags(value, name):
    _require(isinstance(value, list) and all(isinstance(v, str) for v in value),
             f"{name} must be an array of strings")


def _page_numbers(value, name, total):
    _require(isinstance(value, list), f"{name} must be an array of page numbers")
    for number in value:
        _integer(number, name, 1, total)
    _require(len(set(value)) == len(value), f"{name} must not contain duplicate pages")


def _finite_number(value, name, minimum=None):
    try:
        valid = (type(value) in (int, float) and math.isfinite(value)
                 and (minimum is None or value >= minimum))
    except OverflowError:
        valid = False
    _require(valid, f"{name} must be a finite number")


def _validate_package(package):
    _require(isinstance(package, dict), "Document package must be a JSON object")
    _require(package.get("schema_version") == "1.0", "Unsupported document schema_version; expected '1.0'")
    for key in ("doc_id", "revision_id"):
        _require(isinstance(package.get(key), str) and _SHA256.fullmatch(package[key]),
                 f"{key} must be a SHA256 hex string")
    total = _integer(package.get("total_pages"), "total_pages", 0, MAX_PAGES)
    coverage = package.get("coverage")
    _require(isinstance(coverage, dict), "coverage must be an object")
    for key in _COVERAGE_KEYS:
        _page_numbers(coverage.get(key), f"coverage.{key}", total)
    processed, failed = set(coverage["processed_pages"]), set(coverage["failed_pages"])
    _require(not processed & failed, "coverage processed_pages and failed_pages must be disjoint")
    _require((processed | failed) <= set(coverage["requested_pages"]),
             "coverage processed/failed pages must be requested pages")
    _require(not processed & set(coverage["unprocessed_pages"]),
             "coverage processed_pages and unprocessed_pages must be disjoint")
    _require(processed | failed | set(coverage["unprocessed_pages"]) == set(range(1, total + 1)),
             "coverage must account for every physical page")
    _flags(package.get("quality_flags"), "quality_flags")
    _string(package.get("status"), "status", nonempty=True)
    source = package.get("source")
    _require(isinstance(source, dict), "source must be an object")
    _string(source.get("filename"), "source.filename", nonempty=True)
    _require(isinstance(source.get("sha256"), str) and _SHA256.fullmatch(source["sha256"]),
             "source.sha256 must be a SHA256 hex string")
    _require(source["sha256"].lower() == package["revision_id"].lower(),
             "source.sha256 must match revision_id")
    _require(isinstance(package.get("run"), dict), "run must be an object")
    pages = package.get("pages")
    _require(isinstance(pages, list), "pages must be an array")
    seen_pages = set()
    seen_blocks = set()
    for page in pages:
        _require(isinstance(page, dict), "Each page must be an object")
        number = _integer(page.get("physical_page"), "physical_page", 1, total)
        _require(number not in seen_pages, f"Duplicate physical_page: {number}")
        seen_pages.add(number)
        label = f"pages[{number}]"
        for dimension in ("width", "height"):
            _finite_number(page.get(dimension), f"{label}.{dimension}", 0)
        _finite_number(page.get("rotation"), f"{label}.rotation")
        _string(page.get("text_raw"), f"{label}.text_raw")
        _string(page.get("status"), f"{label}.status", nonempty=True)
        _require((page["status"] == "failed") == (number in failed),
                 f"{label}.status must agree with coverage.failed_pages")
        _flags(page.get("quality_flags"), f"{label}.quality_flags")
        _require(page.get("engine") is None or isinstance(page["engine"], str),
                 f"{label}.engine must be a string or null")
        _require(isinstance(page.get("provenance"), dict), f"{label}.provenance must be an object")
        blocks = page.get("blocks")
        _require(isinstance(blocks, list), f"{label}.blocks must be an array")
        for block in blocks:
            _require(isinstance(block, dict), f"{label}: each block must be an object")
            for field in ("block_id", "type", "text_raw", "extraction_method", "validation_state"):
                _string(block.get(field), f"{label}.block.{field}", nonempty=field != "text_raw")
            block_key = (number, block["block_id"])
            _require(block_key not in seen_blocks, f"Duplicate block_id on page {number}: {block['block_id']}")
            seen_blocks.add(block_key)
            _flags(block.get("quality_flags"), f"{label}.block.quality_flags")
            _require("bbox" in block, f"{label}.block.bbox is required")
            bbox = block["bbox"]
            if bbox is not None:
                _require(isinstance(bbox, list) and len(bbox) == 4,
                         f"{label}.block.bbox must be null or four numbers")
                for coordinate in bbox:
                    _finite_number(coordinate, f"{label}.block.bbox coordinate")
                _require(bbox[0] <= bbox[2] and bbox[1] <= bbox[3], f"{label}.block.bbox is inverted")
                _string(block.get("coordinate_space", page.get("coordinate_space")),
                        f"{label}.block.coordinate_space (or page.coordinate_space)", nonempty=True)
    _require(processed | failed <= seen_pages, "pages must contain every processed or failed page")
    return package


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise DocumentReaderError(f"Invalid JSON constant: {value}")


def _load(package_path):
    _require(isinstance(package_path, (str, pathlib.Path)) and bool(str(package_path).strip()),
             "package_path must be a nonempty path to an existing Document Package JSON file")
    try:
        path = pathlib.Path(package_path).expanduser()
        _require(path.is_file(), f"Document package not found or not a regular file: {path}")
        _require(path.stat().st_size <= MAX_PACKAGE_BYTES,
                 f"Document package exceeds {MAX_PACKAGE_BYTES} byte limit")
        with path.open("rb") as file:
            raw = file.read(MAX_PACKAGE_BYTES + 1)
        _require(len(raw) <= MAX_PACKAGE_BYTES, f"Document package exceeds {MAX_PACKAGE_BYTES} byte limit")
        package = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                             parse_constant=_invalid_constant)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise DocumentReaderError(f"Cannot read Document Package JSON: {exc}") from exc
    return path, _validate_package(package), hashlib.sha256(raw).hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _incomplete_quality_pages(package):
    pages = []
    for page in package["pages"]:
        flags = set(page["quality_flags"])
        for block in page["blocks"]:
            flags.update(block["quality_flags"])
        if (flags & _INCOMPLETE_FLAGS or page["status"] == "failed" or page.get("error")
                or page.get("truncated") or page.get("finish_reason") == "length"):
            pages.append(page["physical_page"])
    return sorted(pages)


def _summary(path, package):
    result = {key: package[key] for key in
              ("schema_version", "doc_id", "revision_id", "source", "total_pages", "coverage",
               "quality_flags", "status", "run")}
    result["package_path"] = str(path.resolve())
    result["reader_mode"] = "existing_package_only"
    result["page_statuses"] = [
        {key: page[key] for key in ("physical_page", "status", "quality_flags", "engine", "provenance")}
        for page in sorted(package["pages"], key=lambda page: page["physical_page"])
    ]
    result["issues"] = package.get("issues", [])
    result["incomplete_quality_pages"] = _incomplete_quality_pages(package)
    return result


def _select_pages(pages, total):
    if pages is None:
        return list(range(1, total + 1))
    if isinstance(pages, str):
        _require(bool(pages.strip()) and len(pages) <= 10_000, "pages must be a nonempty page range")
        selected = set()
        for part in pages.split(","):
            match = re.fullmatch(r"\s*([0-9]+)\s*(?:-\s*([0-9]+)\s*)?", part)
            _require(match is not None, "pages must be 1-based numbers/ranges such as '1,3-5'")
            try:
                start = int(match.group(1))
                end = int(match.group(2) or start)
            except ValueError as exc:
                raise DocumentReaderError("Page number is too large") from exc
            _integer(start, "page", 1, total)
            _integer(end, "page", start, total)
            selected.update(range(start, end + 1))
        return sorted(selected)
    _page_numbers(pages, "pages", total)
    return sorted(pages)


def _text_blocks(package, selected):
    """Yield actual block text; page-only text has an honest null block citation."""
    selected = set(selected)
    for page in sorted(package["pages"], key=lambda page: page["physical_page"]):
        if page["physical_page"] not in selected:
            continue
        if page["blocks"]:
            for block in page["blocks"]:
                if block["text_raw"]:
                    yield page, block, block["text_raw"]
        elif page["text_raw"]:
            yield page, None, page["text_raw"]


def _citation(package, page, block):
    return {"doc_id": package["doc_id"], "revision_id": package["revision_id"],
            "physical_page": page["physical_page"], "block_id": block["block_id"] if block else None,
            "bbox": block["bbox"] if block else None,
            "coordinate_space": (block.get("coordinate_space", page.get("coordinate_space"))
                                 if block and block["bbox"] is not None else None),
            "quality_flags": block["quality_flags"] if block else page["quality_flags"],
            "validation_state": block["validation_state"] if block else "unvalidated"}


def _encode_cursor(guard, offset):
    data = json.dumps(dict(guard, offset=offset), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _cursor_offset(cursor, guard, total_chars):
    if cursor is None:
        return 0
    _require(isinstance(cursor, str) and 0 < len(cursor) <= 4096,
             "cursor must be a nonempty continuation token of at most 4096 characters")
    try:
        data = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        decoded = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object,
                             parse_constant=_invalid_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise DocumentReaderError("Invalid read cursor") from exc
    _require(isinstance(decoded, dict), "Invalid read cursor")
    _require(all(decoded.get(key) == value for key, value in guard.items()),
             "Stale or incompatible cursor: document, revision, pipeline, package, or pages changed")
    return _integer(decoded.get("offset"), "cursor offset", 0, total_chars)


def open_document(package_path):
    """Inspect metadata of an existing .document.json package; never extract/OCR."""
    path, package, _ = _load(package_path)
    result = _summary(path, package)
    result["pages"] = [{"physical_page": page["physical_page"], "width": page["width"],
                        "height": page["height"], "rotation": page["rotation"],
                        "block_count": len(page["blocks"]), "text_chars": len(page["text_raw"])}
                       for page in sorted(package["pages"], key=lambda page: page["physical_page"])]
    return result


def read_document(package_path, pages=None, max_chars=8000, cursor=None):
    """Read up to max_chars (1..100000) characters plus complete coverage/quality.

    pages is a 1-based range string or array of integers; omitted means all pages.
    Follow next_cursor with the same package and page selection. Changing the
    character budget is allowed. Returned offsets are Python character offsets.
    Inter-block separators count toward the budget but have no source citation.
    """
    _integer(max_chars, "max_chars", 1, MAX_READ_CHARS)
    path, package, fingerprint = _load(package_path)
    selected = _select_pages(pages, package["total_pages"])
    pieces = []
    total_chars = 0
    for page, block, text in _text_blocks(package, selected):
        if pieces:
            pieces.append((total_chars, total_chars + 2, "\n\n", None, None))
            total_chars += 2
        pieces.append((total_chars, total_chars + len(text), text, page, block))
        total_chars += len(text)
    guard = {"version": 1, "doc_id": package["doc_id"], "revision_id": package["revision_id"],
             "pipeline": _digest(package["run"]), "package": fingerprint, "pages": _digest(selected)}
    offset = _cursor_offset(cursor, guard, total_chars)
    end = min(offset + max_chars, total_chars)
    text_parts, citations = [], []
    for start, stop, text, page, block in pieces:
        lo, hi = max(offset, start), min(end, stop)
        if lo >= hi:
            continue
        text_parts.append(text[lo - start:hi - start])
        if page is not None:
            citation = _citation(package, page, block)
            citation.update({"output_start": lo - offset, "output_end": hi - offset,
                             "source_start": lo - start, "source_end": hi - start})
            citations.append(citation)
    result = _summary(path, package)
    result.update({"text": "".join(text_parts), "returned_chars": end - offset,
                   "total_chars": total_chars, "offset": offset, "truncated": end < total_chars,
                   "next_cursor": _encode_cursor(guard, end) if end < total_chars else None,
                   "selected_pages": selected, "citations": citations,
                   "unavailable_pages": sorted(set(selected) - set(package["coverage"]["processed_pages"]))})
    return result


def search_document(package_path, query, max_hits=20):
    """Literal case-insensitive search of existing package blocks, without OCR.

    At most 100 hits, each containing up to 320 snippet characters. A no-match
    result only covers existing text and always discloses unprocessed pages.
    """
    _integer(max_hits, "max_hits", 1, MAX_SEARCH_HITS)
    _string(query, "query", nonempty=True)
    _require(len(query) <= MAX_QUERY_CHARS, f"query must not exceed {MAX_QUERY_CHARS} characters")
    path, package, _ = _load(package_path)
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    hits, total_matches = [], 0
    for page, block, text in _text_blocks(package, range(1, package["total_pages"] + 1)):
        for match in pattern.finditer(text):
            total_matches += 1
            if len(hits) >= max_hits:
                continue
            start = max(0, match.start() - (SEARCH_SNIPPET_CHARS - len(query)) // 2)
            start = max(0, min(start, len(text) - SEARCH_SNIPPET_CHARS))
            end = min(len(text), start + SEARCH_SNIPPET_CHARS)
            hits.append({"citation": _citation(package, page, block), "text": text[start:end],
                         "snippet_start": start, "snippet_end": end,
                         "match_start": match.start(), "match_end": match.end()})
    result = _summary(path, package)
    unsearched = sorted(set(package["coverage"]["unprocessed_pages"]) |
                        set(package["coverage"]["failed_pages"]))
    result.update({"query": query, "hits": hits, "returned_hits": len(hits),
                   "total_matches": total_matches, "truncated": total_matches > len(hits),
                   "search_scope": "available_package_text_only", "unsearched_pages": unsearched,
                   "complete_document_search": not (unsearched or result["incomplete_quality_pages"]
                                                      or set(package["quality_flags"]) & _INCOMPLETE_FLAGS),
                   "match_status": "matches_found" if hits else "no_match_in_available_text"})
    if not hits:
        result["message"] = "No matches in the extracted package text."
        if unsearched:
            result["message"] += " Unprocessed or failed pages were not fully searched."
        if result["incomplete_quality_pages"] or set(package["quality_flags"]) & _INCOMPLETE_FLAGS:
            result["message"] += " Quality warnings indicate potentially incomplete extraction; absence is not conclusive."
    return result
