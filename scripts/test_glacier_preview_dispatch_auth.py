"""Offline source checks for Glacier preview VPS sync release dispatch.

No production URLs are contacted and no OIDC credentials are read.
"""
import ast
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/glacier-preview-immediate.yml"
WIN = "Queue Windows-only signer after the independently mirrored EXE is available"
PAIRED = "Request signed release only after the newest paired installers are mirrored"


def block(source, label):
    marker = "      - name: " + label + "\n"
    assert source.count(marker) == 1, "Missing/duplicate Glacier action: " + label
    tail = source.split(marker, 1)[1]
    return tail.split("\n      - name: ", 1)[0]


def python_program(step):
    key = "python3 - <<'PY'\n"
    assert step.count(key) == 1
    fragment = step.split(key, 1)[1].split("\n          PY", 1)[0]
    return "\n".join(line[10:] if line.startswith("          ") else line
                     for line in fragment.splitlines()) + "\n"


def verify_authenticated(step):
    if "GH_TOKEN: ${{ github.token }}" not in step:
        raise ValueError("GitHub Actions token is missing")
    code = python_program(step)
    if ('"Authorization":"Bearer "+os.environ["GH_TOKEN"]' not in code
            or "urllib.request.Request(api,headers=headers)" not in code
            and 'urllib.request.Request(\n' not in code):
        raise ValueError("Authenticated GitHub Releases API required")
    if "raw.githubusercontent.com" in code:
        raise ValueError("Stale anonymous raw CDN is not a trusted signed source")
    if "contents/channels/" not in code or "?ref=glacier-browser-updates-v2" not in code:
        raise ValueError("Signed feed must be fetched by pinned branch via GitHub REST")
    if 'base64.b64decode(' not in code or 'doc.get("encoding")!="base64"' not in code:
        raise ValueError("Encoded REST contents require explicit validation")
    ast.parse(code)
    shell = step.split("        run: |\n", 1)[1]
    shell = "\n".join(line[10:] if line.startswith("          ") else line
                      for line in shell.splitlines())
    result = subprocess.run(["bash", "-n"], input=shell, text=True,
                            capture_output=True)
    if result.returncode:
        raise ValueError("Workflow Bash parse failed: " + result.stderr[:500])


class PreviewVpsDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text(encoding="utf-8")

    def test_oidc_and_origin_scope_remain_intact(self):
        for expected in (
            "glacier-preview-vps-update-sync",
            "https://sync.borealos.cn/downloads/notify",
            "id-token: write",
            "contents: read",
            "actions: write",
            "github.ref == 'refs/heads/main'",
        ):
            self.assertIn(expected, self.source)

    def test_windows_independent_signer_dispatch_has_authenticated_source(self):
        verify_authenticated(block(self.source, WIN))

    def test_paired_dispatch_has_authenticated_source(self):
        verify_authenticated(block(self.source, PAIRED))

    def test_unauthed_regression_is_rejected(self):
        source = block(self.source, WIN).replace(
            '"Authorization":"Bearer "+os.environ["GH_TOKEN"]',
            '"Authorization":"anonymous"')
        with self.assertRaisesRegex(ValueError, "Authenticated"):
            verify_authenticated(source)

    def test_raw_cdn_regression_is_rejected(self):
        source = block(self.source, PAIRED).replace(
            "contents/channels/", "raw.githubusercontent.com/channels/")
        with self.assertRaisesRegex(ValueError, "raw CDN"):
            verify_authenticated(source)


if __name__ == "__main__":
    unittest.main()
