"""Build-time transform must match the actual decoded Windows update UI."""
import base64
import lzma
import unittest
from pathlib import Path

from glacier_patch_windows_update_ui import patch


class WindowsUpdatePatchTests(unittest.TestCase):
    @staticmethod
    def decode():
        original = Path(__file__).resolve().parent.parent / "glacier-windows" / "update_ui.py.xz.b64"
        return lzma.decompress(base64.b64decode(original.read_text("ascii"))).decode("utf-8")

    def test_signed_ui_patch_handles_current_compressed_source(self):
        source = self.decode()
        self.assertIn("from update_core import (", source)
        source = source.replace("from update_core import (", "from secure_update import (")
        result = patch(source)
        self.assertIn("from glacier_signed_install27 import launch_verified_setup", result)
        self.assertIn("launch_verified_setup(", result)
        self.assertIn("self.auto_download = True", result)
        self.assertIn("从自有 VPS HTTPS", result)
        self.assertIn("GlacierUpdateDialog28", result)
        self.assertIn("GlacierPrimaryUpdate28", result)
        self.assertIn("安装更新并重启", result)
        self.assertIn("下载中断后可继续", result)
        self.assertIn("已保留下载进度", result)
        self.assertNotIn("安装更新并退出", result)
        self.assertNotIn("代理核心未运行，无法通过 VLESS 检查更新", result)
        self.assertNotIn("subprocess.Popen([str(self.ready_path)", result)
        compile(result, "update_ui.py", "exec")

    def test_patch_fails_closed_for_stale_or_double_patch(self):
        original = self.decode().replace("from update_core import (",
                                         "from secure_update import (")
        with self.assertRaises(ValueError):
            patch(patch(original))
        with self.assertRaises(ValueError):
            patch(original.replace("if not self.browser.proc", "if not self.browser.process"))


if __name__ == "__main__":
    unittest.main()
