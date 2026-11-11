import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import episode_final_assembler as a


class EpisodeAssemblerContractTests(unittest.TestCase):
    def test_episode_timing_is_locked(self):
        self.assertEqual(len(a.SHOT_SECONDS), 31)
        self.assertEqual(sum(a.SHOT_SECONDS), 160)
        self.assertEqual(a.FRAMES, 3840)
        self.assertEqual(a.FPS, 24)
        self.assertEqual((a.WIDTH, a.HEIGHT), (1080, 1920))

    def test_ffmpeg_command_fixed_31_shots_and_mix(self):
        clips = [Path(f"SH{i:02d}.mp4") for i in range(1, 32)]
        cmd = a.build_ffmpeg_command("ffmpeg", clips, Path("MixedAudio.wav"), Path("out.partial.mp4"))
        self.assertEqual(cmd.count("-i"), 32)
        self.assertIn("31:a:0", cmd)
        self.assertIn("-frames:v", cmd)
        self.assertIn("3840", cmd)
        self.assertIn("-c:v", cmd)
        self.assertIn("libx264", cmd)
        self.assertEqual(cmd[-1], "out.partial.mp4")
        self.assertIn("concat=n=31:v=1:a=0[v]", cmd[cmd.index("-filter_complex")+1])

    def test_bad_clip_count_is_rejected(self):
        with self.assertRaisesRegex(a.AssemblyError, "clip_count_mismatch"):
            a.build_ffmpeg_command("ffmpeg", [Path("SH01.mp4")], Path("audio.wav"), Path("out.mp4"))

    def test_requires_exact_decoded_frames_and_dimensions(self):
        x = {"codec_type": "video", "codec_name": "h264", "width": 1080,
             "height": 1920, "avg_frame_rate": "24/1", "nb_read_frames": "72", "duration": "3.0000"}
        a._verify_video_meta(x, 3, final=True)
        for wrong in ({"nb_read_frames":"71"}, {"height":1080}, {"avg_frame_rate":"30000/1001"}, {"duration":"2.5"}):
            with self.subTest(wrong=wrong), self.assertRaises(a.AssemblyError):
                a._verify_video_meta(dict(x, **wrong), 3)

    def test_reject_short_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            wav = Path(temp)/"mix.wav"
            with wave.open(str(wav),"wb") as f:
                f.setnchannels(2);f.setsampwidth(2);f.setframerate(48000)
                f.writeframes(b"\x00" * 48000 * 4)
            with self.assertRaisesRegex(a.AssemblyError,"mixdown_requires_160s"):
                a._verify_wav(wav)

    def test_missing_assets_fail_closed_even_when_dry_run(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(a.AssemblyError,"required_file_missing"):
                a.assemble(Path(temp), "ffmpeg", "ffprobe", dry_run=True)

    def test_symlink_and_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"workspace"; root.mkdir()
            with self.assertRaisesRegex(a.AssemblyError,"path_outside_workspace"):
                a._managed_path(Path(temp)/"elsewhere.mp4", root, is_file=False)
            link=root/"alias"
            try:
                link.symlink_to(Path(temp), target_is_directory=True)
            except (OSError, NotImplementedError):
                return
            with self.assertRaisesRegex(a.AssemblyError,"managed_path_is_link"):
                a._managed_path(link/"missing.mp4", root, is_file=False)

    def test_hashing_is_streamed_and_repeatable(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"a";p.write_bytes(b"abc"*100000)
            import hashlib
            self.assertEqual(a._sha256_file(p), hashlib.sha256(b"abc"*100000).hexdigest())


if __name__ == "__main__": unittest.main()
