"""Run the ACTUAL power restore script's Bash file-operations functions in a sandbox.

All paths are temporary; no systemd, cloud provider or machine power changes.
"""
from __future__ import annotations
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=(ROOT/"restore-owner-direct-power.sh").read_text("utf-8")
A="# FILE OPERATIONS BEGIN"
B="# FILE OPERATIONS END"
if SCRIPT.count(A)!=1 or SCRIPT.count(B)!=1:
    raise AssertionError("Restoration helper test anchors missing")
FUNCTIONS=SCRIPT[SCRIPT.index(A):SCRIPT.index(B)+len(B)]


class FileMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.power=self.root/"installed"
        self.power.mkdir()
        self.backup=self.root/"backup"
        self.backup.mkdir()
        self.names=("power_ops.py","power_direct.py","power_write_mcp.py",
                    "vps_unified_status.py")
        self.original={}
        for name in self.names:
            self.original[name]=f"old-{name}".encode()
            (self.power/name).write_bytes(self.original[name])

    def shell(self, body):
        code=(
            "set -Eeuo pipefail\n"
            f"POWER='{self.power}'\nBACKUP='{self.backup}'\n"
            "fail(){ printf 'BLOCKED: %s\\n' \"$*\" >&2; exit 2; }\n"
            +FUNCTIONS+"\n"+body
        )
        return subprocess.run(["bash","-c",code],capture_output=True,
                              text=True,check=False,timeout=12)

    def test_missing_only_new_direct_module_installs_then_rolls_back(self):
        (self.power/"power_direct.py").unlink()
        run=self.shell(
            "check_target_files\n"
            "backup_target_files\n"
            "test ! -e \"$BACKUP/power_direct.py\"\n"
            "test -s \"$BACKUP/power_ops.py\"\n"
            "printf 'new-module\\n' > \"$POWER/power_direct.py\"\n"
            "printf 'new-code\\n' > \"$POWER/power_ops.py\"\n"
            "restore_target_files\n"
            "test ! -e \"$POWER/power_direct.py\"\n"
        )
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual((self.power/"power_ops.py").read_bytes(),
                         self.original["power_ops.py"])
        self.assertFalse((self.backup/"power_direct.py").exists())

    def test_updating_existing_direct_module_restores_original(self):
        run=self.shell(
            "check_target_files\n"
            "backup_target_files\n"
            "printf 'changed\\n' > \"$POWER/power_direct.py\"\n"
            "printf 'changed\\n' > \"$POWER/power_write_mcp.py\"\n"
            "restore_target_files\n"
        )
        self.assertEqual(run.returncode,0,run.stderr)
        for name in self.names:
            self.assertEqual((self.power/name).read_bytes(),self.original[name])

    def test_missing_legacy_file_still_fails_closed(self):
        (self.power/"power_ops.py").unlink()
        run=self.shell("check_target_files\n")
        self.assertEqual(run.returncode,2)
        self.assertIn("required_existing_power_file_missing",run.stderr)

    def test_dangling_symlink_and_directory_never_pass_preflight(self):
        path=self.power/"power_direct.py"
        path.unlink()
        path.symlink_to(self.root/"nonexistent")
        self.assertFalse(path.exists())
        self.assertTrue(path.is_symlink())
        run=self.shell("check_target_files\n")
        self.assertEqual(run.returncode,2)
        self.assertIn("existing_power_file_missing_or_unsafe",run.stderr)
        path.unlink()
        path.mkdir()
        run=self.shell("check_target_files\n")
        self.assertEqual(run.returncode,2)
        self.assertIn("existing_power_file_missing_or_unsafe",run.stderr)

    def test_missing_existing_module_after_preflight_rejected_by_backup(self):
        run=self.shell(
            "check_target_files\n"
            "rm \"$POWER/power_direct.py\"\n"
            "backup_target_files\n"
        )
        self.assertEqual(run.returncode,2)
        self.assertIn("existing_power_file_changed_before_backup",run.stderr)

    def test_new_symlink_appearing_after_preflight_is_not_allowed(self):
        (self.power/"power_direct.py").unlink()
        run=self.shell(
            "check_target_files\n"
            "ln -s \"$POWER/no-target\" \"$POWER/power_direct.py\"\n"
            "backup_target_files\n"
        )
        self.assertEqual(run.returncode,2)
        self.assertIn("existing_power_file_changed_before_backup",run.stderr)

    def test_newly_installed_module_removed_even_if_dangling_symlink_on_rollback(self):
        (self.power/"power_direct.py").unlink()
        run=self.shell(
            "check_target_files\n"
            "backup_target_files\n"
            "ln -s \"$POWER/no-target\" \"$POWER/power_direct.py\"\n"
            "restore_target_files\n"
        )
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertFalse((self.power/"power_direct.py").is_symlink())

    def test_rollback_refuses_missing_backups_for_legacy_files(self):
        run=self.shell(
            "check_target_files\n"
            "backup_target_files\n"
            "rm \"$BACKUP/power_ops.py\"\n"
            "restore_target_files\n"
        )
        self.assertEqual(run.returncode,2)
        self.assertIn("required_power_rollback_backup_missing",run.stderr)


if __name__=="__main__":
    unittest.main()
