"""Keep Windows/macOS release signing compatibility strict and independent."""
import tempfile
import unittest
from pathlib import Path

from scripts.glacier_prepare_rotated_update import PLATFORM_VERSIONS, prepare

PUBLIC = "02" * 32


class PerPlatformVersionTests(unittest.TestCase):
    def test_versions_are_independent(self):
        self.assertEqual(PLATFORM_VERSIONS["windows"], "0.20.22")
        self.assertEqual(PLATFORM_VERSIONS["macos"], "0.20.20")

    def test_unexpected_platform_is_refused_before_file_access(self):
        with self.assertRaises(ValueError):
            prepare(Path("/nonexistent"), "android", PUBLIC)

    def test_wrong_mac_version_cannot_be_signed(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,"mac_update_core.py").write_text(
                'CURRENT_VERSION = "0.20.15"\\n', encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "Unexpected Glacier client version"):
                prepare(directory, "macos", PUBLIC)


if __name__ == "__main__":
    unittest.main()
