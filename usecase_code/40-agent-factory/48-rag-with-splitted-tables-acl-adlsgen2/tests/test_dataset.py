"""Local deterministic fixture tests; evaluation answers remain outside ingestion."""

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import unittest
from zipfile import ZipFile

import openpyxl
import tiktoken

from sales_demo.dataset import generate


ARTIFACTS = Path(__file__).resolve().parent.parent / ".test-artifacts-dataset"


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ARTIFACTS / "first"
        cls.report = generate(cls.root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(ARTIFACTS, ignore_errors=True)

    def test_publication_shape_hashes_counts_and_token_budgets(self):
        manifest = json.loads((self.root / "publication.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest), {"dataset", "version", "seed", "state", "partitions", "files"})
        self.assertEqual(manifest["state"], "generated")
        self.assertEqual(manifest["dataset"], "car-sales")
        self.assertEqual({p["id"] for p in manifest["partitions"]}, {"json", "excel"})
        encoding = tiktoken.encoding_for_model("text-embedding-3-large")
        self.assertEqual(encoding.name, "cl100k_base")
        ids = []
        for partition in manifest["partitions"]:
            self.assertEqual(set(partition), {
                "id", "source", "site", "library", "input_path", "rows_path",
                "input_sha256", "rows_sha256", "input_tokens", "row_count",
                "sale_ids_sha256", "expected_chunks",
            })
            payload = (self.root / "master" / partition["input_path"]).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), partition["input_sha256"])
            count = len(encoding.encode(payload.decode("utf-8")))
            self.assertEqual(count, partition["input_tokens"])
            self.assertGreaterEqual(count, 13500)
            self.assertLessEqual(count, 14500)
            self.assertEqual(partition["expected_chunks"], 3)
            rows = [json.loads(line) for line in
                    (self.root / "master" / partition["rows_path"]).read_text(encoding="utf-8").splitlines()]
            self.assertGreater(len(rows), 0)
            self.assertEqual(len(rows), partition["row_count"])
            ids.append({r["sale_id"] for r in rows})
        self.assertFalse(ids[0] & ids[1])
        self.assertNotIn("total", json.dumps(manifest).lower())
        for entry in manifest["files"]:
            self.assertEqual(set(entry), {"path", "sha256"})
            blob = (self.root / "master" / entry["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(blob).hexdigest(), entry["sha256"])
            self.assertEqual(blob, (self.root / "project" / entry["path"]).read_bytes())

    def test_whole_workbook_rows_match_authoritative_jsonl(self):
        path = self.root / "master" / "originals" / "car-calculator-tool.xlsx"
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
        sheet = workbook["Car sales"]
        iterator = sheet.iter_rows(values_only=True)
        fields = next(iterator)
        actual = [dict(zip(fields, row)) for row in iterator]
        workbook.close()
        expected = [json.loads(line) for line in
                    (self.root / "master" / "structured" / "excel" / "rows.jsonl")
                    .read_text(encoding="utf-8").splitlines()]
        self.assertEqual(actual, expected)
        normalized = (self.root / "master" / "ingestion" / "excel" / "retail"
                      / "sales-excel" / "car-calculator-tool.txt").read_text(encoding="utf-8")
        self.assertEqual(normalized.count("\nROW "), len(actual))
        self.assertEqual(normalized.count("\nEND ROW\n"), len(actual))

    def test_independent_expected_decimal_totals_and_isolation(self):
        expected = json.loads((self.root / "evaluation" / "expected.json").read_text(encoding="utf-8"))
        subtotals = {}
        for source in ("json", "excel"):
            rows = [json.loads(line) for line in
                    (self.root / "master" / "structured" / source / "rows.jsonl")
                    .read_text(encoding="utf-8").splitlines()]
            subtotal = sum(
                Decimal(0) if row["status"] == "cancelled"
                else Decimal(row["quantity"]) * Decimal(row["unit_price_minor"])
                - Decimal(row["discount_minor"]) - Decimal(row["refund_minor"])
                for row in rows
            )
            subtotals[source] = int(subtotal)
        self.assertEqual(expected["source_subtotals_minor"], subtotals)
        self.assertEqual(expected["total_minor"], sum(subtotals.values()))
        self.assertTrue(expected["image_expected_fact"])
        for tree in ("master", "project"):
            self.assertFalse(list((self.root / tree).rglob("expected.json")))
            self.assertEqual(len(list((self.root / tree / "ingestion").rglob("*.*"))), 2)
        self.assertTrue((self.root / "fixtures" / "overlap.json").is_file())

    def test_six_library_layout_and_separate_overlap_fixture(self):
        for tree in ("master", "project"):
            libraries = [path for path in (self.root / tree / "ingestion").glob("*/*/*") if path.is_dir()]
            self.assertEqual(len(libraries), 6)
            self.assertEqual(sum(bool(list(path.iterdir())) for path in libraries), 2)
        fixture = json.loads((self.root / "fixtures" / "overlap.json").read_text(encoding="utf-8"))
        self.assertTrue(fixture["fixture_only"])
        self.assertTrue(fixture["not_for_ingestion"])
        partitions = fixture["partition_rows"]
        seen = {}
        expected = {"excel": Decimal(0), "json": Decimal(0)}
        for source in sorted(partitions):
            for row in partitions[source]:
                key = (row["dataset"], row["version"], row["sale_id"])
                if key not in seen:
                    seen[key] = row
                    expected[source] += (
                        Decimal(row["quantity"]) * Decimal(row["unit_price_minor"])
                        - Decimal(row["discount_minor"]) - Decimal(row["refund_minor"])
                    ) if row["status"] != "cancelled" else Decimal(0)
        self.assertEqual(fixture["expected"]["input_row_count"], 6)
        self.assertEqual(fixture["expected"]["unique_row_count"], 4)
        self.assertEqual(fixture["expected"]["source_subtotals_minor"],
                         {source: int(amount) for source, amount in expected.items()})
        self.assertTrue(all(key[2].startswith("FIXTURE-") for key in seen))

    def test_existing_output_refused_without_modification(self):
        before = (self.root / "publication.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "empty"):
            generate(self.root, seed=999)
        self.assertEqual((self.root / "publication.json").read_bytes(), before)

    def test_reproducible_artifacts_and_separate_seed(self):
        second = ARTIFACTS / "second"
        generate(second)
        first_files = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        second_files = {p.relative_to(second): p.read_bytes() for p in second.rglob("*") if p.is_file()}
        self.assertEqual(first_files, second_files)
        changed = ARTIFACTS / "different"
        generate(changed, seed=49)
        json_path = Path("master") / "structured" / "json" / "rows.jsonl"
        self.assertNotEqual((self.root / json_path).read_bytes(), (changed / json_path).read_bytes())

    def test_image_docx_is_original_drawing_and_has_no_answer_in_document_text(self):
        image = self.root / "master" / "images" / "car-random-image.png"
        self.assertEqual(image.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        with ZipFile(self.root / "master" / "images" / "car-random-image.docx") as archive:
            self.assertEqual(archive.read("word/media/car-random-image.png"), image.read_bytes())
            xml = archive.read("word/document.xml").decode("utf-8").lower()
            for answer_word in ("magenta", "triangle", "73"):
                self.assertNotIn(answer_word, xml)

    def test_invalid_arguments_fail_without_publication(self):
        for version, seed in (("../v1", 48), ("", 48), ("v1", True), ("v1", 1.5)):
            with self.subTest(version=version, seed=seed), self.assertRaises(ValueError):
                generate(ARTIFACTS / "invalid", version=version, seed=seed)
        self.assertFalse((ARTIFACTS / "invalid" / "publication.json").exists())


if __name__ == "__main__":
    unittest.main()
