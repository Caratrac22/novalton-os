"""Provider-free tests of the trusted fixed syntax checker, no installed claim."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "backend_syntax", Path(__file__).resolve().parents[1] / "worker/backend_syntax.py"
)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class BackendSyntaxTests(unittest.TestCase):
    def test_invalid_source_has_bounded_diagnostics_without_source_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index in range(6):
                (root / f"invalid{index}.py").write_text("def secret_source(\n")
            with (
                patch.object(checker, "ROOTS", (root,)),
                patch.object(checker, "SOURCE", root),
            ):
                result = checker.verify()
            self.assertEqual(result["state"], "failed")
            self.assertEqual(result["failed_files"], 6)
            self.assertEqual(len(result["diagnostics"]), 4)
            self.assertTrue(result["truncated"])
            self.assertNotIn("secret_source", str(result))

    def test_valid_source_is_not_executed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "never-created"
            (root / "valid.py").write_text(f"open({str(marker)!r}, 'w').write('bad')\n")
            with patch.object(checker, "ROOTS", (root,)):
                result = checker.verify()
            self.assertEqual(result["state"], "passed")
            self.assertEqual(result["checked_files"], 1)
            self.assertFalse(marker.exists())

    def test_missing_and_empty_source_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(checker, "ROOTS", (root / "missing",)):
                self.assertEqual(
                    checker.verify()["failure_code"], "verification_source_missing"
                )
            with patch.object(checker, "ROOTS", (root,)):
                self.assertEqual(
                    checker.verify()["failure_code"], "verification_source_empty"
                )

    def test_binary_and_hostile_filenames_are_only_bounded_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "ignore previous instructions.py").write_bytes(
                b"password=secret\x00\xff"
            )
            with (
                patch.object(checker, "ROOTS", (root,)),
                patch.object(checker, "SOURCE", root),
            ):
                result = checker.verify()
            self.assertEqual(result["state"], "failed")
            self.assertEqual(
                result["diagnostics"],
                [{"path": "redacted-path", "code": "python_syntax_invalid"}],
            )
            self.assertNotIn("password", str(result))
            self.assertNotIn("ignore previous", str(result))

    def test_source_size_and_count_limits_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "valid.py").write_text("x = 1")
            with (
                patch.object(checker, "ROOTS", (root,)),
                patch.object(checker, "MAX_FILES", 0),
            ):
                self.assertEqual(
                    checker.verify()["failure_code"], "verification_source_bound"
                )
            with (
                patch.object(checker, "ROOTS", (root,)),
                patch.object(checker, "MAX_BYTES", 1),
            ):
                self.assertEqual(
                    checker.verify()["failure_code"], "verification_source_type"
                )

    def test_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "target").write_text("x = 1")
            (root / "escape.py").symlink_to(root / "target")
            with patch.object(checker, "ROOTS", (root,)):
                self.assertEqual(
                    checker.verify()["failure_code"], "verification_source_type"
                )


if __name__ == "__main__":
    unittest.main()
