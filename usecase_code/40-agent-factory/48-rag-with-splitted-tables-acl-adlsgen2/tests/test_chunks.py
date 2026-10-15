"""Synthetic TextSplit offset fixtures only, NOT evidence of cloud skill success."""

import copy
import json
from pathlib import Path
import shutil
import unittest

import tiktoken

from sales_demo.chunks import verify_chunks


ARTIFACTS = Path(__file__).resolve().parent.parent / ".test-artifacts-chunks"


def fixture(text=None):
    if text is None:
        text = json.dumps({"records": [
            {"sale_id": f"S-{i:04d}", "description": "blue car café 🚙 " * 30}
            for i in range(65)
        ]}, ensure_ascii=False, indent=2) + "\n"
    cuts = [text.index("café", len(text) // 3) + 2,
            text.index("café", len(text) * 2 // 3) + 2]
    offsets = [0, *cuts, len(text)]
    chunks = []
    for ordinal, (start, end) in enumerate(zip(offsets, offsets[1:]), 1):
        piece = text[start:end]
        chunks.append({
            "chunk_text": piece, "ordinal": ordinal,
            "offset_utf8": len(text[:start].encode("utf-8")),
            "length_utf8": len(piece.encode("utf-8")),
            "offset_utf16": len(text[:start].encode("utf-16-le")) // 2,
            "length_utf16": len(piece.encode("utf-16-le")) // 2,
            "offset_codepoint": start, "length_codepoint": len(piece),
        })
    return text, chunks


class ChunkTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(ARTIFACTS, ignore_errors=True)

    def test_offline_fixture_exact_unicode_reconstruction_and_envelopes(self):
        text, chunks = fixture()
        result = verify_chunks(text, chunks, "parent-json-1", "json", ARTIFACTS / "audit")
        self.assertTrue(result["verified"])
        self.assertEqual(result["chunk_count"], 3)
        self.assertGreater(result["input_tokens"], 9000)
        self.assertTrue(any(result["split_inside_record"]))
        self.assertTrue(all(c["tokens"] <= 6000 for c in result["chunks"]))
        for index, chunk in enumerate(chunks, 1):
            path = ARTIFACTS / "audit" / f"car-sales-xyz-part-{index}.json"
            envelope = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(envelope["chunk_text"], chunk["chunk_text"])
            self.assertEqual(envelope["parent_id"], "parent-json-1")

    def test_bad_arrays_offsets_lengths_and_text_fail(self):
        text, original = fixture()
        variants = [original[:2], original + [copy.deepcopy(original[2])]]
        for field, value in [
            ("ordinal", 1), ("offset_utf8", 0), ("offset_utf16", 0),
            ("offset_codepoint", 0), ("length_utf8", 0), ("length_utf16", 0),
            ("length_codepoint", 0), ("ordinal", True), ("offset_codepoint", 1.5),
            ("chunk_text", "invented text"),
        ]:
            chunks = copy.deepcopy(original)
            chunks[1][field] = value
            variants.append(chunks)
        missing = copy.deepcopy(original)
        del missing[0]["offset_utf16"]
        variants.append(missing)
        for chunks in variants:
            with self.subTest(chunks=len(chunks)), self.assertRaises(ValueError):
                verify_chunks(text, chunks, "parent", "json")

    def test_gap_and_unicode_unit_confusion_fail(self):
        text, chunks = fixture()
        chunks[1]["offset_codepoint"] += 1
        with self.assertRaises(ValueError):
            verify_chunks(text, chunks, "parent", "json")
        text, chunks = fixture()
        chunks[1]["offset_utf16"] = chunks[1]["offset_utf8"]
        with self.assertRaises(ValueError):
            verify_chunks(text, chunks, "parent", "json")

    def test_offline_normalized_excel_fixture_and_malformed_rows(self):
        text = "worksheet=Car sales\nschema=car-sales-normalized-v1\n" + "".join(
            f'ROW {i}\nsale_id="S-{i:04d}"\ndescription="'
            + "blue car café 🚙 " * 30 + '"\nEND ROW\n'
            for i in range(1, 66)
        )
        text, chunks = fixture(text)
        result = verify_chunks(text, chunks, "parent-excel-1", "excel")
        self.assertTrue(result["verified"])
        self.assertTrue(any(result["split_inside_record"]))
        malformed = text.replace("END ROW", "END", 1)
        malformed, chunks = fixture(malformed)
        with self.assertRaisesRegex(ValueError, "ROW"):
            verify_chunks(malformed, chunks, "parent", "excel")

    def test_incomplete_tail_and_missing_parent_or_bad_source_fail(self):
        text, chunks = fixture()
        last = chunks[-1]
        last["chunk_text"] = last["chunk_text"][:-1]
        for field in ("length_utf8", "length_utf16", "length_codepoint"):
            last[field] -= 1
        with self.assertRaisesRegex(ValueError, "complete"):
            verify_chunks(text, chunks, "parent", "json")
        text, chunks = fixture()
        for parent, source in (("", "json"), ("parent", "other")):
            with self.subTest(parent=parent, source=source), self.assertRaises(ValueError):
                verify_chunks(text, chunks, parent, source)

    def test_small_source_and_oversized_chunk_fail(self):
        text, chunks = fixture()
        with self.assertRaises(ValueError):
            verify_chunks("small", chunks, "parent", "json")
        long_piece = text[:len(text) * 3 // 4]
        pieces = [long_piece, text[len(long_piece):-1], text[-1:]]
        rebuilt = []
        start = 0
        for i, piece in enumerate(pieces, 1):
            rebuilt.append({
                "ordinal": i, "chunk_text": piece,
                "offset_utf8": len(text[:start].encode("utf-8")),
                "length_utf8": len(piece.encode("utf-8")),
                "offset_utf16": len(text[:start].encode("utf-16-le")) // 2,
                "length_utf16": len(piece.encode("utf-16-le")) // 2,
                "offset_codepoint": start, "length_codepoint": len(piece),
            })
            start += len(piece)
        self.assertGreater(len(tiktoken.get_encoding("cl100k_base").encode(long_piece)), 6000)
        with self.assertRaisesRegex(ValueError, "6000"):
            verify_chunks(text, rebuilt, "parent", "json")

    def test_ingestion_export_rejected_before_writing(self):
        text, chunks = fixture()
        with self.assertRaisesRegex(ValueError, "ingestion"):
            verify_chunks(text, chunks, "parent", "json", ARTIFACTS / "ingestion" / "audit")
        self.assertFalse((ARTIFACTS / "ingestion").exists())

    def test_exclusively_record_boundary_cuts_do_not_prove_requirement(self):
        text, chunks = fixture()
        boundaries = [text.index('    {', len(text) // 3),
                      text.index('    {', len(text) * 2 // 3)]
        offsets = [0, *boundaries, len(text)]
        for chunk, start, end in zip(chunks, offsets, offsets[1:]):
            piece = text[start:end]
            chunk.update(
                chunk_text=piece, offset_codepoint=start, length_codepoint=len(piece),
                offset_utf8=len(text[:start].encode("utf-8")), length_utf8=len(piece.encode("utf-8")),
                offset_utf16=len(text[:start].encode("utf-16-le")) // 2,
                length_utf16=len(piece.encode("utf-16-le")) // 2,
            )
        with self.assertRaisesRegex(ValueError, "inside"):
            verify_chunks(text, chunks, "parent", "json")


if __name__ == "__main__":
    unittest.main()
