import importlib.util
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location("sales_demo_entry", Path(__file__).resolve().parents[1] / "main.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class CommandTests(unittest.TestCase):
    def test_all_writes_require_explicit_approval_before_io(self):
        for command in sorted(entry.MUTATIONS):
            with self.subTest(command=command), self.assertRaisesRegex(ValueError, "--apply"):
                entry.run(entry.parser().parse_args([command]))

    def test_all_paid_operations_require_separate_approval(self):
        for command in sorted(entry.PAID):
            with self.subTest(command=command), self.assertRaisesRegex(ValueError, "--allow-paid"):
                entry.run(entry.parser().parse_args([command, "--apply"]))

    def test_generated_state_cannot_be_written_inside_source_template(self):
        with self.assertRaises(ValueError):
            entry.external_output(Path(entry.__file__).parent / "generated")
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(entry.external_output(Path(root)), Path(root).resolve())


if __name__ == "__main__":
    unittest.main()
