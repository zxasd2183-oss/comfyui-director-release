from pathlib import Path
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from episode_asset_readiness import inspect_episode_inputs


class EpisodeInputReadinessTests(unittest.TestCase):
    def test_empty_workspace_reports_all_missing_without_claiming_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            r = inspect_episode_inputs(Path(folder))
            self.assertTrue(r['ok'])
            self.assertEqual(r['missing_shot_ids'], [f'{i:02d}' for i in range(1, 32)])
            self.assertEqual(r['clip_candidate_count'], 0)
            self.assertFalse(r['input_inventory_complete'])
            self.assertFalse(r['clips_codec_and_timing_verified'])
            self.assertFalse(r['artistic_approval_verified'])
            self.assertEqual(r['mixdown_status'], 'missing')

    def test_missing_workspace_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(inspect_episode_inputs(Path(folder) / 'nope')['reason'], 'workspace_unavailable')

    def test_complete_inputs_are_only_unvalidated_candidates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            clips = root / 'Outputs' / 'EP01' / 'Clips'; clips.mkdir(parents=True)
            for i in range(1, 32):
                (clips / f'SH{i:02d}.mp4').write_bytes(b'!' * 1024)
            audio_dir = root / 'Outputs' / 'EP01' / 'Audio'; audio_dir.mkdir(parents=True)
            with wave.open(str(audio_dir / 'MixedAudio.wav'), 'wb') as wav:
                wav.setnchannels(2); wav.setsampwidth(2); wav.setframerate(48000)
                wav.writeframes(b'\x00' * (160 * 48000 * 2 * 2))
            r = inspect_episode_inputs(root)
            self.assertEqual(r['clip_candidate_count'], 31)
            self.assertEqual(r['mixdown_status'], 'pcm_metadata_valid')
            self.assertTrue(r['input_inventory_complete'])
            self.assertFalse(r['clips_codec_and_timing_verified'])
            self.assertFalse(r['artistic_approval_verified'])
            (root / 'Outputs' / 'EP01' / 'Final').mkdir()
            (root / 'Outputs' / 'EP01' / 'Final' / 'WaitingOffice_EP01_v001.mp4').write_bytes(b'x')
            self.assertFalse(inspect_episode_inputs(root)['input_inventory_complete'])

    def test_symlink_clip_rejected_without_resolving_outside_workspace(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); clips = root / 'Outputs' / 'EP01' / 'Clips'; clips.mkdir(parents=True)
            outside = root.parent / (root.name + '_outside'); outside.write_bytes(b'x' * 1024)
            try:
                (clips / 'SH01.mp4').symlink_to(outside)
            except (NotImplementedError, OSError):
                outside.unlink(); return
            try:
                r = inspect_episode_inputs(root)
                self.assertIn('01', r['invalid_shot_ids'])
                self.assertNotIn('01', r['missing_shot_ids'])
            finally:
                outside.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
