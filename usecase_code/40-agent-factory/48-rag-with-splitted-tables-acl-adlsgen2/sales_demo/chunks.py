"""Verify supplied TextSplit outputs; this module never performs text splitting.

The caller must authenticate service provenance. Local fixture arrays exercise
validation only and are not evidence that Azure AI Search ran a skill.
"""

import hashlib
import json
from pathlib import Path
import re

import tiktoken


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _skip_space(text: str, start: int) -> int:
    while start < len(text) and text[start].isspace():
        start += 1
    return start


def _json_record_spans(text: str) -> list[tuple[int, int]]:
    decoder = json.JSONDecoder()
    try:
        parsed = json.loads(text)
        index = _skip_space(text, 0)
        if isinstance(parsed, dict):
            index = _skip_space(text, index + 1)
            while text[index] != "}":
                key, index = decoder.raw_decode(text, index)
                index = _skip_space(text, index)
                if text[index] != ":":
                    raise ValueError("invalid JSON object")
                index = _skip_space(text, index + 1)
                if key in ("records", "rows") and isinstance(parsed[key], list):
                    break
                _, index = decoder.raw_decode(text, index)
                index = _skip_space(text, index)
                if text[index] == ",":
                    index = _skip_space(text, index + 1)
            else:
                raise ValueError("JSON input must contain a records or rows array")
        elif not isinstance(parsed, list):
            raise ValueError("JSON input must be a table array or object")
        if text[index] != "[":
            raise ValueError("JSON input must contain a records or rows array")
        spans = []
        index = _skip_space(text, index + 1)
        while text[index] != "]":
            start = index
            row, index = decoder.raw_decode(text, start)
            if not isinstance(row, dict):
                raise ValueError("JSON table records must be objects")
            spans.append((start, index))
            index = _skip_space(text, index)
            if text[index] == ",":
                index = _skip_space(text, index + 1)
        return spans
    except (json.JSONDecodeError, IndexError) as exc:
        raise ValueError("cannot locate serialized JSON records") from exc


def _excel_record_spans(text: str) -> list[tuple[int, int]]:
    starts = list(re.finditer(r"(?m)^ROW [1-9]\d*\n", text))
    ends = list(re.finditer(r"(?m)^END ROW\n", text))
    if not starts or len(starts) != len(ends):
        raise ValueError("normalized Excel input must contain complete ROW/END ROW blocks")
    spans = []
    for index, (start, end) in enumerate(zip(starts, ends)):
        if start.end() >= end.start() or (index + 1 < len(starts) and end.end() > starts[index + 1].start()):
            raise ValueError("normalized Excel row markers are not consecutive")
        spans.append((start.start(), end.end()))
    return spans


def verify_chunks(
    text: str, chunks: list[dict], parent_id: str, source: str, export_dir: Path | None = None,
) -> dict:
    """Fail closed unless three supplied chunks reconstruct all source codepoints.

    Offsets and lengths must be the actual TextSplit UTF-8 byte, UTF-16 code-unit,
    and codepoint arrays, mapped to the named scalar fields. No normalization,
    whitespace trimming, overlap removal, or inferred offsets are permitted.
    """
    if not isinstance(text, str) or not text:
        raise ValueError("source text must be a nonempty string")
    if not isinstance(parent_id, str) or not parent_id.strip():
        raise ValueError("parent_id must be a nonempty string")
    if source not in ("json", "excel"):
        raise ValueError("source must be json or excel")
    if not isinstance(chunks, list) or len(chunks) != 3:
        raise ValueError("exactly three service chunks are required")
    target = None
    if export_dir is not None:
        candidate = Path(export_dir)
        target = candidate.resolve()
        if any(part.casefold() == "ingestion" for part in (*candidate.parts, *target.parts)):
            raise ValueError("chunk envelopes must be exported outside ingestion")
    encoding = tiktoken.encoding_for_model("text-embedding-3-large")
    if encoding.name != "cl100k_base":
        raise ValueError("unexpected tokenizer; expected cl100k_base")
    input_tokens = len(encoding.encode(text, disallowed_special=()))
    if input_tokens <= 9000:
        raise ValueError("source table must contain more than 9000 tokens")
    positions = {"utf8": 0, "utf16": 0, "codepoint": 0}
    metadata = []
    pieces = []
    boundaries = []
    for ordinal, chunk in enumerate(chunks, 1):
        if not isinstance(chunk, dict):
            raise ValueError("each chunk must be a dictionary")
        if type(chunk.get("ordinal")) is not int or chunk["ordinal"] != ordinal:
            raise ValueError("service chunk ordinals must be exactly 1, 2, 3 in order")
        piece = chunk.get("chunk_text")
        if not isinstance(piece, str) or not piece:
            raise ValueError("chunk_text must be a nonempty string")
        lengths = {
            "utf8": len(piece.encode("utf-8")),
            "utf16": len(piece.encode("utf-16-le")) // 2,
            "codepoint": len(piece),
        }
        for unit, length in lengths.items():
            offset_field, length_field = f"offset_{unit}", f"length_{unit}"
            if type(chunk.get(offset_field)) is not int or type(chunk.get(length_field)) is not int:
                raise ValueError(f"{unit} offsets and lengths must be integers, not bool")
            if chunk[offset_field] != positions[unit] or chunk[length_field] != length:
                raise ValueError(f"{unit} offset/length mismatch: gaps, overlaps, or wrong units")
        start = positions["codepoint"]
        if text[start:start + lengths["codepoint"]] != piece:
            raise ValueError("chunk_text does not match the exact source slice")
        tokens = len(encoding.encode(piece, disallowed_special=()))
        if tokens > 6000 or tokens >= 8000:
            raise ValueError("each chunk must have <=6000 tokens and strictly <8000 tokens")
        metadata.append({
            "ordinal": ordinal, "parent_id": parent_id, "source": source,
            "tokens": tokens, "sha256": _sha256(piece),
            **{f"offset_{unit}": positions[unit] for unit in positions},
            **{f"length_{unit}": lengths[unit] for unit in lengths},
        })
        pieces.append(piece)
        for unit in positions:
            positions[unit] += lengths[unit]
        if ordinal < 3:
            boundaries.append(positions["codepoint"])
    if "".join(pieces) != text:
        raise ValueError("chunk concatenation does not equal the complete original source")
    spans = _json_record_spans(text) if source == "json" else _excel_record_spans(text)
    inside = [any(start < cut < end for start, end in spans) for cut in boundaries]
    if not any(inside):
        raise ValueError("at least one actual split boundary must fall inside a serialized record/row")
    result = {
        "verified": True, "parent_id": parent_id, "source": source,
        "verification_scope": "supplied service offsets; caller authenticates service provenance",
        "tokenizer": encoding.name, "input_tokens": input_tokens,
        "input_sha256": _sha256(text), "reconstructed_sha256": _sha256("".join(pieces)),
        "chunk_count": 3, "split_inside_record": inside, "chunks": metadata,
    }
    if target is not None:
        target.mkdir(parents=True, exist_ok=True)
        stem = "car-sales-xyz" if source == "json" else "car-calculator-tool"
        for item, piece in zip(metadata, pieces):
            envelope = {**item, "chunk_text": piece, "input_sha256": result["input_sha256"]}
            path = target / f"{stem}-part-{item['ordinal']}.json"
            path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")
    return result
