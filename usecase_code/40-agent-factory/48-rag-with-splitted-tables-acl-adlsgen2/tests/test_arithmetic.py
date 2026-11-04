"""Offline arithmetic tests; no service calls or generated expected answers."""

import copy
from decimal import Decimal
import unittest

from sales_demo.arithmetic import aggregate_records, row_sales_minor, validate_row


def sale(sale_id="SALE-000001", **changes):
    row = {
        "dataset": "car-sales", "version": "v1", "sale_id": sale_id,
        "dealership": "North Motors", "date": "2026-01-14", "car_model": "Cedar EV",
        "quantity": 2, "unit_price_minor": 1234567, "discount_minor": 10000,
        "refund_minor": 3000, "tax_minor": 9000, "status": "completed", "currency": "USD",
    }
    row.update(changes)
    return row


class ArithmeticTests(unittest.TestCase):
    def test_integer_pretax_rule_and_cancelled(self):
        row = sale()
        validate_row(row, "car-sales", "v1")
        self.assertEqual(row_sales_minor(row), 2456134)
        self.assertEqual(row_sales_minor(sale(status="cancelled")), 0)
        self.assertEqual(row_sales_minor(sale(tax_minor=999999)), 2456134)

    def test_independent_decimal_oracle_and_reconciliation(self):
        rows = [sale(), sale("SALE-000002", quantity=3, refund_minor=0),
                sale("SALE-000003", status="cancelled")]
        expected = sum(
            (Decimal(r["quantity"]) * Decimal(r["unit_price_minor"])
             - Decimal(r["discount_minor"]) - Decimal(r["refund_minor"]))
            if r["status"] != "cancelled" else Decimal(0)
            for r in rows
        )
        result = aggregate_records({"json": rows[:2], "excel": rows[2:]})
        self.assertEqual(result["total_minor"], int(expected))
        self.assertEqual(sum(result["source_subtotals_minor"].values()), result["total_minor"])
        self.assertEqual(result["unique_row_count"], 3)
        self.assertEqual(result["currency"], "USD")

    def test_cross_source_overlap_is_attributed_once_independent_of_order(self):
        common = sale()
        partitions = {"json": [common], "excel": [copy.deepcopy(common)]}
        result = aggregate_records(partitions)
        self.assertEqual(result, aggregate_records(dict(reversed(list(partitions.items())))))
        self.assertEqual(result["source_subtotals_minor"], {"excel": row_sales_minor(common), "json": 0})
        self.assertEqual(result["duplicate_count"], 1)
        self.assertEqual(result["deduplication"]["key"], ["dataset", "version", "sale_id"])
        self.assertIn("lexicograph", result["deduplication"]["attribution"])

    def test_conflicting_duplicates_and_internal_duplicates_fail(self):
        with self.assertRaisesRegex(ValueError, "conflict"):
            aggregate_records({"json": [sale()], "excel": [sale(tax_minor=1)]})
        with self.assertRaisesRegex(ValueError, "within"):
            aggregate_records({"json": [sale(), sale()]})

    def test_distinct_versions_are_distinct_business_keys(self):
        result = aggregate_records({"json": [sale()], "excel": [sale(version="v2")]})
        self.assertEqual(result["unique_row_count"], 2)
        self.assertEqual(result["total_minor"], row_sales_minor(sale()) * 2)

    def test_validation_rejects_bad_values(self):
        changes = [
            {"quantity": True}, {"quantity": 1.0}, {"unit_price_minor": 3.2},
            {"discount_minor": -1}, {"refund_minor": -1}, {"tax_minor": False},
            {"quantity": -1}, {"unit_price_minor": -1}, {"tax_minor": -1},
            {"discount_minor": 99999999}, {"refund_minor": 99999999},
            {"status": "unknown"}, {"status": True}, {"date": "2026-02-30"},
            {"date": "2026-1-14"}, {"date": 20260114}, {"sale_id": ""},
            {"dealership": " "}, {"car_model": None}, {"currency": "EUR"},
            {"version": "../v1"}, {"dataset": ""},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                row_sales_minor(sale(**change))
        with self.assertRaises(ValueError):
            validate_row(sale(), "car-sales", "v2")
        with self.assertRaises(ValueError):
            validate_row(sale(), "another-dataset", "v1")
        missing = sale()
        del missing["quantity"]
        with self.assertRaises(ValueError):
            row_sales_minor(missing)

    def test_zero_value_refund_boundary_and_large_exact_integer(self):
        self.assertEqual(row_sales_minor(sale(quantity=0, discount_minor=0, refund_minor=0)), 0)
        self.assertEqual(row_sales_minor(sale(quantity=1, unit_price_minor=500,
                                              discount_minor=100, refund_minor=400)), 0)
        row = sale(unit_price_minor=2**62, discount_minor=0, refund_minor=0)
        self.assertEqual(row_sales_minor(row), 2**63)

    def test_each_numeric_field_rejects_bool_float_and_nonfinite_values(self):
        for field in ("quantity", "unit_price_minor", "discount_minor", "refund_minor", "tax_minor"):
            for value in (True, False, 0.0, float("nan"), float("inf"), "0", None):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    row_sales_minor(sale(**{field: value}))

    def test_business_id_cannot_contain_line_or_control_separators(self):
        for value in ("SALE\n001", "SALE\r001", "SALE\t001", "SALE\x00001"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                row_sales_minor(sale(sale_id=value))

    def test_empty_and_malformed_partitions(self):
        result = aggregate_records({"json": [], "excel": []})
        self.assertEqual(result["total_minor"], 0)
        self.assertEqual(result["source_subtotals_minor"], {"excel": 0, "json": 0})
        for value in ([], {"": []}, {"json": None}, {"json": [None]}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                aggregate_records(value)


if __name__ == "__main__":
    unittest.main()
