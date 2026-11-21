"""Static guard: official binary upgrade tests run only on disposable CI devices."""
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class OfficialUpgradeSafety(unittest.TestCase):
    def test_three_platform_versions_sha256_and_synthetic_only(self):
        workflow=(ROOT/'.github/workflows/glacier-three-platform-inplace-upgrade.yml').read_text(encoding='utf8')
        win=(ROOT/'scripts/glacier_win_inplace_upgrade.ps1').read_text(encoding='utf8')
        mac=(ROOT/'scripts/glacier_mac_inplace_upgrade.sh').read_text(encoding='utf8')
        android=(ROOT/'scripts/glacier_android_stable_upgrade_smoke.sh').read_text(encoding='utf8')
        for phrase in ('pull_request:', 'windows-2022','macos-26',
                       'reactivecircus/android-emulator-runner@v2',
                       'glacier-android-browser-v0.2.10','glacier-android-browser-v0.2.11'):
            self.assertIn(phrase,workflow)
        for phrase in ('glacier-v0.20.34','glacier-v0.20.35',
                       '7954c7551d43446b6c6acffd9b07d90bb4bf086aa44e351f288bd26aeacbcb5f',
                       'd90c43d727f0dad3e89eb97af7b4e1ae5b6df1ddb8cbd2dac04f5eb4894a724e',
                       'Get-FileHash','ExtractAssociatedIcon','synthetic-qa-data-preserve-2026'):
            self.assertIn(phrase,win)
        for phrase in ('glacier-macos-v0.20.34','glacier-macos-v0.20.35',
                       '57c943bfabcbf0f4e726262bcb10079d49d97730a3206bd853e5a0730784a511',
                       '181e8ca08295336eff5313675642f3d1407df198ecedc7284cf1d19fda61121c',
                       'hdiutil verify','codesign --verify --deep','CFBundleIconFile',
                       'synthetic-qa-data-preserve-2026'):
            self.assertIn(phrase,mac)
        for phrase in ('synthetic-qa-data-preserve-2026','apksigner','adb install -r',
                       'root_uid','versionCode=','6d8fb8a4b3dd90427ff2f7959394df4b73f37c117a7d1d2e983bde0f10a1ff4e'):
            self.assertIn(phrase,android)
        self.assertNotIn('workflow_dispatch:',workflow)
        for bad in ('adb uninstall','pm clear','pm uninstall','gh release delete',
                    'gh release upload','gh release create','rm -rf "$HOME"',
                    'Set-Clipboard','os.environ["PASSWORD"]'):
            self.assertNotIn(bad,workflow+win+mac+android)

if __name__=='__main__':
    unittest.main()
